from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "wavemind.verified_experience_admission.v1"
BENCHMARK_SCHEMA = "wavemind.verified_experience_benchmark.v1"
ARTIFACT = Path("benchmarks/verified_experience_results.json")
DATASET_REVISION = "verified-experience-stateful-v1-frozen-20260803"
EXPECTED_DOMAINS = ("travel", "customer_support", "shopping_assistant")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _repository_sha(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8"
    ).strip()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("benchmark artifact must be a JSON object")
    return value


def canonical_artifact_sha256(path: Path) -> str:
    """Hash text artifacts independently of the checkout line-ending policy."""
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def _check(identifier: str, passed: bool, evidence: Any, target: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "passed": bool(passed),
        "evidence": evidence,
        "target": target,
    }


def evaluate_verified_experience_admission(
    root: Path,
    *,
    expected_source_sha: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    expected_sha = expected_source_sha or _repository_sha(root)
    artifact_path = root / ARTIFACT
    if not artifact_path.exists():
        checks = [_check("artifact", False, "missing", str(ARTIFACT))]
        return _result(expected_sha, checks)
    payload = _load(artifact_path)
    dataset = _mapping(payload.get("dataset"))
    protocol = _mapping(payload.get("protocol"))
    metrics = _mapping(payload.get("metrics"))
    safety = _mapping(payload.get("safety"))
    training = _mapping(payload.get("training"))
    embedded = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    source_sha = str(payload.get("source_sha") or "")
    fingerprint = str(dataset.get("fingerprint_sha256") or "")
    checks = [
        _check(
            "artifact-schema",
            payload.get("schema") == BENCHMARK_SCHEMA
            and payload.get("status") == "pass",
            {"schema": payload.get("schema"), "status": payload.get("status")},
            "passing verified-experience benchmark v1",
        ),
        _check(
            "source-sha",
            bool(_SHA_RE.fullmatch(source_sha)) and source_sha == expected_sha,
            source_sha,
            expected_sha,
        ),
        _check(
            "frozen-dataset",
            dataset.get("revision") == DATASET_REVISION
            and dataset.get("domains") == list(EXPECTED_DOMAINS)
            and int(dataset.get("held_out_tasks") or 0) == 150
            and int(dataset.get("held_out_per_domain") or 0) == 50
            and bool(re.fullmatch(r"[0-9a-f]{64}", fingerprint))
            and dataset.get("split_frozen_before_evaluation") is True
            and dataset.get("answer_metadata_visible_to_agent") is False,
            dataset,
            "frozen 3-domain/150-task split without answer leakage",
        ),
        _check(
            "fair-protocol",
            int(protocol.get("repeats") or 0) == 5
            and protocol.get("same_tasks_and_environment_verifiers") is True
            and protocol.get("evaluation_store_read_only") is True
            and protocol.get("no_llm_api_gpu") is True
            and protocol.get("no_test_specific_rules") is True
            and protocol.get("independent_environment_verification") is True,
            protocol,
            "five comparable repeats with executable independent verifiers",
        ),
        _check(
            "capture-rate",
            float(training.get("capture_rate") or 0.0) >= 0.99,
            training.get("capture_rate"),
            ">= 0.99",
        ),
        _check(
            "unverified-auto-promotion",
            int(safety.get("unverified_auto_promotions") or 0) == 0,
            safety.get("unverified_auto_promotions"),
            0,
        ),
        _check(
            "namespace-leakage",
            int(safety.get("namespace_leakage") or 0) == 0,
            safety.get("namespace_leakage"),
            0,
        ),
        _check(
            "rollback-provenance",
            float(safety.get("rollback_provenance_parity") or 0.0) == 1.0,
            safety.get("rollback_provenance_parity"),
            1.0,
        ),
        _check(
            "task-success-uplift",
            float(metrics.get("task_success_uplift") or 0.0) >= 0.10,
            metrics.get("task_success_uplift"),
            ">= 0.10",
        ),
        _check(
            "all-domain-uplift",
            all(
                float(value) > 0.0
                for value in _mapping(
                    metrics.get("domain_task_success_uplift")
                ).values()
            )
            and set(_mapping(metrics.get("domain_task_success_uplift")))
            == set(EXPECTED_DOMAINS),
            metrics.get("domain_task_success_uplift"),
            "positive in all three domains",
        ),
        _check(
            "repeated-error-reduction",
            float(metrics.get("repeated_error_relative_reduction") or 0.0) >= 0.50,
            metrics.get("repeated_error_relative_reduction"),
            ">= 0.50",
        ),
        _check(
            "context-token-reduction",
            float(
                metrics.get("context_token_relative_reduction_vs_full_history") or 0.0
            )
            >= 0.30,
            metrics.get("context_token_relative_reduction_vs_full_history"),
            ">= 0.30",
        ),
        _check(
            "unnecessary-intervention",
            float(metrics.get("unnecessary_intervention_rate", 1.0)) <= 0.10,
            metrics.get("unnecessary_intervention_rate"),
            "<= 0.10",
        ),
        _check(
            "runtime-p95",
            float(metrics.get("runtime_p95_ms") or float("inf")) <= 75.0,
            metrics.get("runtime_p95_ms"),
            "<= 75 ms",
        ),
        _check(
            "embedded-checks",
            len(embedded) == 10
            and all(
                isinstance(item, dict) and item.get("passed") is True
                for item in embedded
            ),
            embedded,
            "all ten benchmark checks pass",
        ),
    ]
    return _result(
        expected_sha,
        checks,
        artifact_sha256=canonical_artifact_sha256(artifact_path),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _result(
    source_sha: str, checks: list[dict[str, Any]], *, artifact_sha256: str | None = None
) -> dict[str, Any]:
    admitted = bool(checks) and all(check["passed"] for check in checks)
    return {
        "schema": SCHEMA,
        "status": "admitted" if admitted else "blocked",
        "admitted": admitted,
        "source_sha": source_sha,
        "artifact": ARTIFACT.as_posix(),
        "artifact_sha256": artifact_sha256,
        "artifact_hash_normalization": "lf" if artifact_sha256 else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "passed": sum(check["passed"] for check in checks),
            "total": len(checks),
            "blockers": [check["id"] for check in checks if not check["passed"]],
        },
        "checks": checks,
        "claim_boundary": "Admission applies only to the frozen local verified-experience protocol; it is not an official STATE-Bench score.",
    }


def render_verified_experience_admission_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Verified Agent Experience Admission",
        "",
        f"Status: **{payload.get('status', 'blocked')}**",
        "",
        f"Source SHA: `{payload.get('source_sha', '')}`",
        "",
    ]
    lines.extend(
        f"- {'PASS' if item['passed'] else 'FAIL'} `{item['id']}`"
        for item in payload.get("checks", [])
    )
    lines.extend(["", str(payload.get("claim_boundary") or "")])
    return "\n".join(lines) + "\n"
