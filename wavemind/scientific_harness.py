from __future__ import annotations

import copy
import random
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .evidence import (
    attach_artifact_integrity,
    canonical_json_bytes,
    repository_commit,
    sha256_bytes,
)
from .scientific_admission import (
    INDEPENDENT_VERIFIERS,
    SCIENTIFIC_RUN_SCHEMA,
)
from .scientific_protocol import REQUIRED_BASELINES, REQUIRED_CANDIDATES


@dataclass(frozen=True)
class ScientificCase:
    benchmark_family: str
    case_id: str
    category: str
    payload: Mapping[str, Any]
    full_context_tokens: int


@dataclass(frozen=True)
class ArmResponse:
    action: Mapping[str, Any]
    context_tokens: int
    false_verified_promotions: int = 0
    receipt_digest: str | None = None


@dataclass(frozen=True)
class VerifiedArmOutcome:
    verifier_source: str
    verifier_id: str
    task_success: float
    repeated_errors: int
    stale_or_contradiction_errors: int
    evidence_digest: str


ArmRunner = Callable[[Mapping[str, Any]], ArmResponse]
IndependentVerifier = Callable[
    [ScientificCase, str, ArmResponse], VerifiedArmOutcome
]


def _validate_sha256(value: str | None, *, label: str) -> str:
    digest = str(value or "")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{label} must be sha256")
    return digest


def _validate_outcome(outcome: VerifiedArmOutcome) -> None:
    if outcome.verifier_source not in INDEPENDENT_VERIFIERS:
        raise ValueError("scientific harness requires an independent verifier")
    if not outcome.verifier_id.strip():
        raise ValueError("scientific harness verifier_id is missing")
    if not 0.0 <= float(outcome.task_success) <= 1.0:
        raise ValueError("verified task success must be between zero and one")
    if outcome.repeated_errors < 0 or outcome.stale_or_contradiction_errors < 0:
        raise ValueError("verified error counts cannot be negative")
    _validate_sha256(outcome.evidence_digest, label="verifier evidence digest")


def run_equal_protocol_case(
    case: ScientificCase,
    *,
    candidate_id: str,
    arms: Mapping[str, ArmRunner],
    verifier: IndependentVerifier,
    seed: int,
) -> dict[str, Any]:
    if candidate_id not in REQUIRED_CANDIDATES:
        raise ValueError("candidate is not preregistered")
    expected_arms = REQUIRED_BASELINES | {candidate_id}
    if set(arms) != expected_arms:
        raise ValueError("harness must execute the exact frozen arm set")
    if case.full_context_tokens <= 0:
        raise ValueError("full context token count must be positive")
    frozen_case_bytes = canonical_json_bytes(dict(case.payload))
    case_input_sha256 = sha256_bytes(frozen_case_bytes)
    arm_order = sorted(arms)
    random.Random(f"{seed}:{case.case_id}").shuffle(arm_order)

    outcomes: dict[str, dict[str, float | int]] = {}
    verification_rows: list[dict[str, str]] = []
    candidate_receipt: str | None = None
    verifier_sources: set[str] = set()
    verifier_ids: set[str] = set()
    for arm_id in arm_order:
        payload_copy = copy.deepcopy(dict(case.payload))
        started = time.perf_counter_ns()
        response = arms[arm_id](payload_copy)
        runtime_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        if canonical_json_bytes(dict(case.payload)) != frozen_case_bytes:
            raise RuntimeError("benchmark case was mutated during arm execution")
        if response.context_tokens < 0 or response.false_verified_promotions < 0:
            raise ValueError("arm resource and promotion counts cannot be negative")
        outcome = verifier(case, arm_id, response)
        _validate_outcome(outcome)
        verifier_sources.add(outcome.verifier_source)
        verifier_ids.add(outcome.verifier_id)
        verification_rows.append(
            {
                "arm_id": arm_id,
                "evidence_digest": outcome.evidence_digest,
            }
        )
        outcomes[arm_id] = {
            "task_success": float(outcome.task_success),
            "repeated_errors": outcome.repeated_errors,
            "stale_or_contradiction_errors": outcome.stale_or_contradiction_errors,
            "false_verified_promotions": response.false_verified_promotions,
            "context_tokens": response.context_tokens,
            "runtime_ms": runtime_ms,
        }
        if arm_id == candidate_id:
            candidate_receipt = _validate_sha256(
                response.receipt_digest,
                label="candidate influence receipt digest",
            )
    if len(verifier_sources) != 1 or len(verifier_ids) != 1:
        raise ValueError("every arm must use the same independent verifier")
    return {
        "benchmark_family": case.benchmark_family,
        "case_id": case.case_id,
        "category": case.category,
        "case_input_sha256": case_input_sha256,
        "arm_order": arm_order,
        "full_context_tokens": case.full_context_tokens,
        "verification": {
            "source": next(iter(verifier_sources)),
            "verifier_id": next(iter(verifier_ids)),
            "receipt_digest": candidate_receipt,
            "evidence_digest": sha256_bytes(canonical_json_bytes(verification_rows)),
        },
        "arms": outcomes,
    }


def require_clean_exact_sha(project_root: str | Path, expected_sha: str) -> None:
    root = Path(project_root).resolve()
    if repository_commit(root) != expected_sha:
        raise RuntimeError("held-out run SHA does not match repository HEAD")
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        text=True,
        encoding="utf-8",
    )
    if status.strip():
        raise RuntimeError("held-out run is forbidden on a dirty worktree")


def build_scientific_run_artifact(
    *,
    project_root: str | Path,
    protocol_digest: str,
    source_sha: str,
    candidate_id: str,
    run_id: str,
    seed: int,
    controls: Mapping[str, Any],
    package_metadata: Mapping[str, Any],
    raw_rows: Sequence[Mapping[str, Any]],
    ablation_rows: Sequence[Mapping[str, Any]],
    longmemeval_v2_full_run: bool,
    phase: str = "held-out-admission",
) -> dict[str, Any]:
    if phase == "held-out-admission":
        require_clean_exact_sha(project_root, source_sha)
    payload = {
        "schema": SCIENTIFIC_RUN_SCHEMA,
        "phase": phase,
        "source_sha": source_sha,
        "protocol_digest": protocol_digest,
        "candidate_id": candidate_id,
        "run_id": run_id,
        "seed": seed,
        "longmemeval_v2_full_run": bool(longmemeval_v2_full_run),
        "controls": dict(controls),
        "baselines_executed": sorted(REQUIRED_BASELINES),
        "package_metadata": dict(package_metadata),
        "raw_rows": [dict(row) for row in raw_rows],
        "ablation_rows": [dict(row) for row in ablation_rows],
    }
    return attach_artifact_integrity(payload)
