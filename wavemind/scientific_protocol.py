from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .evidence import canonical_json_bytes, sha256_bytes, validate_source_manifest


SCIENTIFIC_PROTOCOL_SCHEMA = "wavemind.scientific_memory_protocol.v1"
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_BASELINES = {
    "no-memory",
    "static-vector-retrieval",
    "wavemind-no-field",
    "wavemind-wavefield",
    "wavemind-graph",
    "wavemind-memory-os",
    "wavemind-full-frozen-pipeline",
    "mem0-oss",
    "langgraph",
    "chroma",
    "qdrant-local",
}
REQUIRED_CANDIDATES = (
    "evidence-constrained-associative-graph-v1",
    "causal-utility-controller-v1",
    "hybrid-graph-causal-v1",
)
REQUIRED_BENCHMARK_FAMILIES = {
    "memops",
    "memoryagentbench",
    "state-bench-agent-learning",
    "longmemeval-v2",
}


def protocol_digest(payload: Mapping[str, Any]) -> str:
    content = dict(payload)
    content.pop("protocol_digest", None)
    return sha256_bytes(canonical_json_bytes(content))


def load_scientific_protocol(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("scientific protocol must be a JSON object")
    return payload


def validate_scientific_protocol(
    payload: Mapping[str, Any], *, project_root: str | Path
) -> list[str]:
    errors: list[str] = []
    if payload.get("schema") != SCIENTIFIC_PROTOCOL_SCHEMA:
        errors.append("scientific protocol schema is invalid")
    if payload.get("status") != "preregistered":
        errors.append("scientific protocol must remain preregistered")
    source_sha = payload.get("baseline_source_sha")
    if not isinstance(source_sha, str) or not GIT_SHA_RE.fullmatch(source_sha):
        errors.append("baseline source SHA is invalid")
    digest = payload.get("protocol_digest")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        errors.append("protocol digest is invalid")
    elif digest != protocol_digest(payload):
        errors.append("protocol digest mismatch")
    manifest = payload.get("baseline_source_manifest")
    if not isinstance(manifest, Mapping):
        errors.append("baseline source manifest is missing")
    else:
        errors.extend(
            validate_source_manifest(
                Path(project_root), manifest, require_current_files=True
            )
        )
    baseline_ids = {
        str(row.get("id"))
        for row in payload.get("baselines", [])
        if isinstance(row, Mapping)
    }
    if baseline_ids != REQUIRED_BASELINES:
        errors.append("frozen baseline set differs from preregistration")
    candidates = payload.get("preregistered_candidates")
    candidate_ids = tuple(
        str(row.get("id"))
        for row in candidates or []
        if isinstance(row, Mapping)
    )
    if candidate_ids != REQUIRED_CANDIDATES:
        errors.append("preregistered candidate order or identity changed")
    if any(not bool(row.get("frozen")) for row in candidates or []):
        errors.append("every preregistered candidate must be frozen")
    evaluation = payload.get("evaluation") or {}
    if evaluation.get("required_reproducible_runs") != 3:
        errors.append("scientific admission requires three reproducible runs")
    families = {
        str(row.get("id"))
        for row in evaluation.get("official_benchmark_families", [])
        if isinstance(row, Mapping)
    }
    if families != REQUIRED_BENCHMARK_FAMILIES:
        errors.append("official benchmark family set changed")
    longmem = next(
        (
            row
            for row in evaluation.get("official_benchmark_families", [])
            if isinstance(row, Mapping) and row.get("id") == "longmemeval-v2"
        ),
        {},
    )
    if longmem.get("maximum_full_runs") != 1:
        errors.append("full LongMemEval-V2 must remain one-shot")
    gates = payload.get("admission_gates") or {}
    expected_gates = {
        "independent_benchmark_families_with_positive_uplift_lcb": 2,
        "task_success_uplift_ci_lower_strictly_greater_than": 0.0,
        "longmemeval_v2_uplift_minimum": 0.01,
        "longmemeval_v2_improved_categories_minimum": 4,
        "repeated_error_reduction_minimum": 0.5,
        "stale_or_contradiction_error_rate_maximum": 0.02,
        "false_verified_promotions_maximum": 0,
        "context_reduction_vs_full_context_minimum": 0.3,
        "runtime_p95_must_be_within_frozen_budget": True,
        "raw_per_case_evidence_required": True,
        "ablation_required_for_every_improvement": True,
    }
    for key, expected in expected_gates.items():
        if gates.get(key) != expected:
            errors.append(f"frozen admission gate changed: {key}")
    held_out = payload.get("held_out_policy") or {}
    if held_out.get("opened_at_preregistration") is not False:
        errors.append("held-out data was opened before preregistration")
    if held_out.get("post_hoc_candidate_changes_forbidden") is not True:
        errors.append("post-hoc candidate changes must remain forbidden")
    if held_out.get("threshold_relaxation_forbidden") is not True:
        errors.append("threshold relaxation must remain forbidden")
    if held_out.get("full_longmemeval_v2_run_count_at_preregistration") != 0:
        errors.append("full LongMemEval-V2 was already consumed")
    terminal = str(payload.get("terminal_rule") or "")
    if "failed_experiment" not in terminal or "remain unchanged" not in terminal:
        errors.append("fail-closed terminal rule is missing")
    return errors
