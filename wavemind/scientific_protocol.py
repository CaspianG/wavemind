from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .evidence import (
    canonical_json_bytes,
    file_sha256,
    sha256_bytes,
    validate_source_manifest,
)


SCIENTIFIC_PROTOCOL_SCHEMA = "wavemind.scientific_memory_protocol.v1"
SCIENTIFIC_PROTOCOL_V2_SCHEMA = "wavemind.scientific_memory_protocol.v2"
SCIENTIFIC_PROTOCOL_V3_SCHEMA = "wavemind.scientific_memory_protocol.v3"
SCIENTIFIC_PROTOCOL_V4_SCHEMA = "wavemind.scientific_memory_protocol.v4"
SCIENTIFIC_PROTOCOL_V5_SCHEMA = "wavemind.scientific_memory_protocol.v5"
SCIENTIFIC_PROTOCOL_V6_SCHEMA = "wavemind.scientific_memory_protocol.v6"
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


def validate_scientific_protocol_v2(
    payload: Mapping[str, Any], *, project_root: str | Path
) -> list[str]:
    """Validate the v2 preregistration without mutating the immutable v1 rules."""

    errors: list[str] = []
    project = Path(project_root).resolve()
    if payload.get("schema") != SCIENTIFIC_PROTOCOL_V2_SCHEMA:
        errors.append("scientific v2 protocol schema is invalid")
    if payload.get("status") != "preregistered":
        errors.append("scientific v2 protocol must remain preregistered")
    source_sha = payload.get("baseline_source_sha")
    if not isinstance(source_sha, str) or not GIT_SHA_RE.fullmatch(source_sha):
        errors.append("scientific v2 baseline source SHA is invalid")
    digest = payload.get("protocol_digest")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        errors.append("scientific v2 protocol digest is invalid")
    elif digest != protocol_digest(payload):
        errors.append("scientific v2 protocol digest mismatch")

    negative = payload.get("immutable_negative_evidence") or {}
    expected_negative = {
        "development_evidence_sha256": project
        / "benchmarks"
        / "scientific_development_evidence_results.json",
        "admission_manifest_sha256": project
        / "scientific-memory-admission"
        / "manifest.json",
    }
    if negative.get("status") != "failed_experiment":
        errors.append("v1 failed_experiment status was not preserved")
    if negative.get("may_be_overwritten") is not False:
        errors.append("v1 negative evidence must be immutable")
    for key, path in expected_negative.items():
        if not path.is_file() or negative.get(key) != file_sha256(path):
            errors.append(f"v1 immutable evidence hash mismatch: {key}")

    candidate = payload.get("candidate") or {}
    if candidate.get("id") != "proof-carrying-state-reconciler-v2":
        errors.append("scientific v2 candidate identity changed")
    if candidate.get("frozen_before_first_v2_outcome") is not True:
        errors.append("scientific v2 candidate must be frozen before outcomes")

    parameters = payload.get("frozen_parameters") or {}
    expected_parameters = {
        "hashing_embedding_dimensions": 384,
        "seed": 17,
        "bootstrap_repeats": 2000,
        "confidence_level": 0.95,
        "maximum_graph_hops": 4,
        "maximum_retrieval_candidates": 20,
        "token_budget": 8192,
        "latency_budget_ms": 1000.0,
        "maximum_safety_risk": 0.0,
        "retrieval_floor": 0.0,
        "top_k_context": 10,
    }
    for key, expected in expected_parameters.items():
        if parameters.get(key) != expected:
            errors.append(f"frozen v2 parameter changed: {key}")

    gate = payload.get("development_gate") or {}
    expected_gate = {
        "required_reproducible_runs": 3,
        "independent_benchmark_families_with_positive_uplift_lcb": 2,
        "minimum_independent_clusters_per_family": 5,
        "task_success_uplift_ci_lower_strictly_greater_than": 0.0,
        "minimum_candidate_intervention_coverage": 0.8,
        "all_observed_family_means_must_be_non_negative": True,
        "false_verified_promotions_maximum": 0,
        "raw_per_case_evidence_required": True,
        "failed_attempts_must_be_retained": True,
    }
    for key, expected in expected_gate.items():
        if gate.get(key) != expected:
            errors.append(f"frozen v2 development gate changed: {key}")
    if "invalid for uplift estimation" not in str(
        gate.get("absent_intervention_policy") or ""
    ):
        errors.append("v2 absent-intervention fail-closed policy is missing")

    v1_admission = {
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
    admission = payload.get("admission_gates") or {}
    for key, expected in v1_admission.items():
        if admission.get(key) != expected:
            errors.append(f"v2 weakened or changed admission gate: {key}")

    validity = payload.get("validity_controls") or {}
    for key in (
        "official_scorers_only",
        "answer_model_and_prompt_bytes_equal_between_paired_arms",
        "duplicate_cluster_detection_required",
        "intervention_audit_required",
        "confidence_interval_unit_must_match_independent_cluster",
    ):
        if validity.get(key) is not True:
            errors.append(f"v2 validity control is missing: {key}")
    if validity.get("gold_fields_exposed_to_candidate") != []:
        errors.append("v2 candidate may not inspect gold fields")

    held_out = payload.get("held_out_policy") or {}
    if held_out.get("opened_at_preregistration") is not False:
        errors.append("v2 held-out data was opened before preregistration")
    if held_out.get("post_hoc_candidate_changes_forbidden") is not True:
        errors.append("v2 post-hoc candidate changes must be forbidden")
    if held_out.get("threshold_relaxation_forbidden") is not True:
        errors.append("v2 threshold relaxation must be forbidden")
    if held_out.get("full_longmemeval_v2_run_count_at_preregistration") != 0:
        errors.append("v2 LongMemEval one-shot was already consumed")
    if held_out.get("maximum_full_longmemeval_v2_runs") != 1:
        errors.append("v2 LongMemEval must remain one-shot")
    terminal = str(payload.get("terminal_rule") or "")
    if "failed_experiment_v2" not in terminal or "remain unchanged" not in terminal:
        errors.append("scientific v2 fail-closed terminal rule is missing")
    return errors


def validate_scientific_protocol_v3(
    payload: Mapping[str, Any], *, project_root: str | Path
) -> list[str]:
    """Validate the hierarchical v3 preregistration and immutable v2 outcome."""

    errors: list[str] = []
    project = Path(project_root).resolve()
    if payload.get("schema") != SCIENTIFIC_PROTOCOL_V3_SCHEMA:
        errors.append("scientific v3 protocol schema is invalid")
    if payload.get("status") != "preregistered":
        errors.append("scientific v3 protocol must remain preregistered")
    if payload.get("protocol_digest") != protocol_digest(payload):
        errors.append("scientific v3 protocol digest mismatch")
    negative = payload.get("immutable_negative_evidence") or {}
    expected_hashes = {
        "v2_outcome_sha256": project / "benchmarks" / "SCIENTIFIC_MEMORY_V2_OUTCOME.md",
        "v2_result_sha256": project
        / "benchmarks"
        / "scientific_memoryagentbench_v2_accurate_pilot_results.json",
    }
    if negative.get("v1_status") != "failed_experiment":
        errors.append("v3 did not preserve the v1 failed experiment")
    if negative.get("v2_status") != "failed_experiment_v2":
        errors.append("v3 did not preserve the v2 failed experiment")
    if negative.get("may_be_overwritten") is not False:
        errors.append("v3 negative evidence must be immutable")
    for key, path in expected_hashes.items():
        if not path.is_file() or negative.get(key) != file_sha256(path):
            errors.append(f"v2 immutable evidence hash mismatch: {key}")
    candidate = payload.get("candidate") or {}
    if candidate.get("id") != "hierarchical-proof-state-reconciler-v3":
        errors.append("scientific v3 candidate identity changed")
    if candidate.get("frozen_before_first_v3_outcome") is not True:
        errors.append("scientific v3 candidate must be frozen before outcomes")
    if "^Document [0-9]+:" not in str(candidate.get("document_segmentation") or ""):
        errors.append("scientific v3 structural segmentation changed")
    if "blank-line boundaries" not in str(candidate.get("paragraph_segmentation") or ""):
        errors.append("scientific v3 paragraph segmentation changed")
    parameters = payload.get("frozen_parameters") or {}
    expected_parameters = {
        "seed": 17,
        "bootstrap_repeats": 2000,
        "confidence_level": 0.95,
        "maximum_graph_hops": 4,
        "maximum_retrieval_candidates": 20,
        "token_budget": 8192,
        "latency_budget_ms": 1000.0,
        "maximum_safety_risk": 0.0,
        "top_k_context": 10,
        "minimum_structural_unit_characters": 1,
        "answer_model": "mistral:7b",
        "answer_model_digest": (
            "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"
        ),
        "context_window": 32768,
    }
    for key, expected in expected_parameters.items():
        if parameters.get(key) != expected:
            errors.append(f"frozen v3 parameter changed: {key}")
    gate = payload.get("development_gate") or {}
    expected_gate = {
        "required_reproducible_runs": 3,
        "independent_benchmark_families_with_positive_uplift_lcb": 2,
        "minimum_independent_clusters_per_family": 5,
        "task_success_uplift_ci_lower_strictly_greater_than": 0.0,
        "minimum_candidate_intervention_coverage": 0.8,
        "all_observed_family_means_must_be_non_negative": True,
        "false_verified_promotions_maximum": 0,
        "raw_per_case_evidence_required": True,
        "failed_attempts_must_be_retained": True,
    }
    for key, expected in expected_gate.items():
        if gate.get(key) != expected:
            errors.append(f"frozen v3 development gate changed: {key}")
    v2 = load_scientific_protocol(
        project / "benchmarks" / "scientific_memory_protocol_v2.json"
    )
    if payload.get("admission_gates") != v2.get("admission_gates"):
        errors.append("v3 admission gates differ from frozen v2 gates")
    validity = payload.get("validity_controls") or {}
    for key in (
        "official_scorers_only",
        "duplicate_cluster_detection_required",
        "intervention_audit_required",
        "confidence_interval_unit_must_match_independent_cluster",
        "structural_segmentation_audit_required",
    ):
        if validity.get(key) is not True:
            errors.append(f"v3 validity control is missing: {key}")
    if validity.get("gold_fields_exposed_to_candidate") != []:
        errors.append("v3 candidate may not inspect gold fields")
    held_out = payload.get("held_out_policy") or {}
    if held_out.get("opened_at_preregistration") is not False:
        errors.append("v3 held-out data was opened before preregistration")
    if held_out.get("threshold_relaxation_forbidden") is not True:
        errors.append("v3 threshold relaxation must be forbidden")
    if held_out.get("maximum_full_longmemeval_v2_runs") != 1:
        errors.append("v3 LongMemEval must remain one-shot")
    terminal = str(payload.get("terminal_rule") or "")
    if "failed_experiment_v3" not in terminal or "remain unchanged" not in terminal:
        errors.append("scientific v3 fail-closed terminal rule is missing")
    return errors


def validate_scientific_protocol_v4(
    payload: Mapping[str, Any], *, project_root: str | Path
) -> list[str]:
    """Validate efficient v4 while preserving every earlier negative outcome."""

    errors: list[str] = []
    project = Path(project_root).resolve()
    if payload.get("schema") != SCIENTIFIC_PROTOCOL_V4_SCHEMA:
        errors.append("scientific v4 protocol schema is invalid")
    if payload.get("status") != "preregistered":
        errors.append("scientific v4 protocol must remain preregistered")
    if payload.get("protocol_digest") != protocol_digest(payload):
        errors.append("scientific v4 protocol digest mismatch")
    negative = payload.get("immutable_negative_evidence") or {}
    if negative.get("v1_status") != "failed_experiment":
        errors.append("v4 did not preserve v1 failure")
    if negative.get("v2_status") != "failed_experiment_v2":
        errors.append("v4 did not preserve v2 failure")
    if negative.get("v3_status") != "failed_experiment_v3_runtime_budget":
        errors.append("v4 did not preserve v3 runtime failure")
    v3_path = project / "benchmarks" / "SCIENTIFIC_MEMORY_V3_OUTCOME.md"
    if not v3_path.is_file() or negative.get("v3_outcome_sha256") != file_sha256(
        v3_path
    ):
        errors.append("v3 immutable outcome hash mismatch")
    if negative.get("may_be_overwritten") is not False:
        errors.append("v4 negative evidence must be immutable")
    candidate = payload.get("candidate") or {}
    if candidate.get("id") != "efficient-hierarchical-proof-state-reconciler-v4":
        errors.append("scientific v4 candidate identity changed")
    if candidate.get("frozen_before_first_v4_outcome") is not True:
        errors.append("scientific v4 candidate must be frozen before outcomes")
    if "Do not duplicate" not in str(candidate.get("evaluation_storage") or ""):
        errors.append("scientific v4 storage isolation changed")
    parameters = payload.get("frozen_parameters") or {}
    expected = {
        "seed": 17,
        "bootstrap_repeats": 2000,
        "confidence_level": 0.95,
        "maximum_graph_hops": 4,
        "maximum_retrieval_candidates": 20,
        "token_budget": 8192,
        "latency_budget_ms": 1000.0,
        "maximum_safety_risk": 0.0,
        "top_k_context": 10,
        "evaluation_legacy_vector_indexing": False,
        "answer_model": "mistral:7b",
        "answer_model_digest": (
            "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"
        ),
        "context_window": 32768,
    }
    for key, value in expected.items():
        if parameters.get(key) != value:
            errors.append(f"frozen v4 parameter changed: {key}")
    v3 = load_scientific_protocol(
        project / "benchmarks" / "scientific_memory_protocol_v3.json"
    )
    if payload.get("development_gate") != v3.get("development_gate"):
        errors.append("v4 development gates differ from frozen v3 gates")
    if payload.get("admission_gates") != v3.get("admission_gates"):
        errors.append("v4 admission gates differ from frozen v3 gates")
    validity = payload.get("validity_controls") or {}
    for key in (
        "official_scorers_only",
        "duplicate_cluster_detection_required",
        "intervention_audit_required",
        "event_chain_validation_required",
        "production_index_absence_required_during_shadow",
    ):
        if validity.get(key) is not True:
            errors.append(f"v4 validity control is missing: {key}")
    if validity.get("gold_fields_exposed_to_candidate") != []:
        errors.append("v4 candidate may not inspect gold fields")
    held_out = payload.get("held_out_policy") or {}
    if held_out.get("opened_at_preregistration") is not False:
        errors.append("v4 held-out data was opened before preregistration")
    if held_out.get("threshold_relaxation_forbidden") is not True:
        errors.append("v4 threshold relaxation must be forbidden")
    if held_out.get("maximum_full_longmemeval_v2_runs") != 1:
        errors.append("v4 LongMemEval must remain one-shot")
    terminal = str(payload.get("terminal_rule") or "")
    if "failed_experiment_v4" not in terminal or "remain unchanged" not in terminal:
        errors.append("scientific v4 fail-closed terminal rule is missing")
    return errors


def validate_scientific_protocol_v5(
    payload: Mapping[str, Any], *, project_root: str | Path
) -> list[str]:
    """Validate atomic-batch v5 and unchanged scientific gates."""

    errors: list[str] = []
    project = Path(project_root).resolve()
    if payload.get("schema") != SCIENTIFIC_PROTOCOL_V5_SCHEMA:
        errors.append("scientific v5 protocol schema is invalid")
    if payload.get("status") != "preregistered":
        errors.append("scientific v5 protocol must remain preregistered")
    if payload.get("protocol_digest") != protocol_digest(payload):
        errors.append("scientific v5 protocol digest mismatch")
    negative = payload.get("immutable_negative_evidence") or {}
    expected_statuses = {
        "v1_status": "failed_experiment",
        "v2_status": "failed_experiment_v2",
        "v3_status": "failed_experiment_v3_runtime_budget",
        "v4_status": "failed_experiment_v4_runtime_budget",
    }
    for key, expected in expected_statuses.items():
        if negative.get(key) != expected:
            errors.append(f"v5 did not preserve negative status: {key}")
    v4_path = project / "benchmarks" / "SCIENTIFIC_MEMORY_V4_OUTCOME.md"
    if not v4_path.is_file() or negative.get("v4_outcome_sha256") != file_sha256(
        v4_path
    ):
        errors.append("v4 immutable outcome hash mismatch")
    candidate = payload.get("candidate") or {}
    if candidate.get("id") != "atomic-batch-hierarchical-proof-state-reconciler-v5":
        errors.append("scientific v5 candidate identity changed")
    if candidate.get("frozen_before_first_v5_outcome") is not True:
        errors.append("scientific v5 candidate must be frozen before outcomes")
    atomic = str(candidate.get("atomic_batch") or "")
    for required in ("BEGIN IMMEDIATE", "executemany", "COMMIT", "ROLLBACK"):
        if required not in atomic:
            errors.append(f"scientific v5 atomic rule is missing: {required}")
    parameters = payload.get("frozen_parameters") or {}
    if parameters.get("event_batch_transaction_count_per_context") != 1:
        errors.append("v5 must use one event transaction per context")
    if parameters.get("evaluation_legacy_vector_indexing") is not False:
        errors.append("v5 evaluation vector indexing must remain disabled")
    if parameters.get("sqlite_synchronous") != "FULL":
        errors.append("v5 SQLite durability was weakened")
    v4 = load_scientific_protocol(
        project / "benchmarks" / "scientific_memory_protocol_v4.json"
    )
    if payload.get("development_gate") != v4.get("development_gate"):
        errors.append("v5 development gates differ from frozen v4 gates")
    if payload.get("admission_gates") != v4.get("admission_gates"):
        errors.append("v5 admission gates differ from frozen v4 gates")
    validity = payload.get("validity_controls") or {}
    for key in (
        "event_chain_validation_required",
        "batch_rollback_test_required",
        "interleaved_writer_test_required",
        "production_index_absence_required_during_shadow",
    ):
        if validity.get(key) is not True:
            errors.append(f"v5 validity control is missing: {key}")
    if validity.get("gold_fields_exposed_to_candidate") != []:
        errors.append("v5 candidate may not inspect gold fields")
    terminal = str(payload.get("terminal_rule") or "")
    if "failed_experiment_v5" not in terminal or "remain unchanged" not in terminal:
        errors.append("scientific v5 fail-closed terminal rule is missing")
    return errors


def validate_scientific_protocol_v6(
    payload: Mapping[str, Any], *, project_root: str | Path
) -> list[str]:
    """Validate operation-aware v6 while preserving every frozen gate."""

    errors: list[str] = []
    project = Path(project_root).resolve()
    if payload.get("schema") != SCIENTIFIC_PROTOCOL_V6_SCHEMA:
        errors.append("scientific v6 protocol schema is invalid")
    if payload.get("status") != "preregistered":
        errors.append("scientific v6 protocol must remain preregistered")
    if payload.get("protocol_digest") != protocol_digest(payload):
        errors.append("scientific v6 protocol digest mismatch")
    negative = payload.get("immutable_negative_evidence") or {}
    expected_statuses = {
        "v1_status": "failed_experiment",
        "v2_status": "failed_experiment_v2",
        "v3_status": "failed_experiment_v3_runtime_budget",
        "v4_status": "failed_experiment_v4_runtime_budget",
        "v5_status": "failed_development_gate",
    }
    for key, expected in expected_statuses.items():
        if negative.get(key) != expected:
            errors.append(f"v6 did not preserve negative status: {key}")
    v5_path = project / "benchmarks" / "SCIENTIFIC_MEMORY_V5_OUTCOME.md"
    if not v5_path.is_file() or negative.get("v5_outcome_sha256") != file_sha256(
        v5_path
    ):
        errors.append("v5 immutable outcome hash mismatch")
    if negative.get("may_be_overwritten") is not False:
        errors.append("v6 negative evidence must remain immutable")
    candidate = payload.get("candidate") or {}
    if candidate.get("id") != "operation-aware-tombstone-reconciler-v6":
        errors.append("scientific v6 candidate identity changed")
    if candidate.get("frozen_before_first_v6_outcome") is not True:
        errors.append("scientific v6 candidate must be frozen before outcomes")
    tombstone = str(candidate.get("tombstone_policy") or "")
    for required in ("forget", "mandatory", "provenance"):
        if required not in tombstone:
            errors.append(f"scientific v6 tombstone rule is missing: {required}")
    parameters = payload.get("frozen_parameters") or {}
    if parameters.get("source_recency_bonus") != 0.0:
        errors.append("v6 generic source-recency bonus must remain disabled")
    if parameters.get("event_batch_transaction_count_per_context") != 1:
        errors.append("v6 must use one event transaction per context")
    v5 = load_scientific_protocol(
        project / "benchmarks" / "scientific_memory_protocol_v5.json"
    )
    if payload.get("development_gate") != v5.get("development_gate"):
        errors.append("v6 development gates differ from frozen v5 gates")
    if payload.get("admission_gates") != v5.get("admission_gates"):
        errors.append("v6 admission gates differ from frozen v5 gates")
    validity = payload.get("validity_controls") or {}
    for key in (
        "official_scorers_only",
        "intervention_audit_required",
        "event_chain_validation_required",
        "batch_rollback_test_required",
        "production_index_absence_required_during_shadow",
        "memory_intent_detection_blind_to_gold_required",
    ):
        if validity.get(key) is not True:
            errors.append(f"v6 validity control is missing: {key}")
    if validity.get("gold_fields_exposed_to_candidate") != []:
        errors.append("v6 candidate may not inspect gold fields")
    sample = payload.get("frozen_development_sample") or {}
    if "all available operation" not in str(sample.get("memops") or "").lower():
        errors.append("v6 MemOps sample must include all available operations")
    if sample.get("required_repeats_on_exact_source_sha") != 3:
        errors.append("v6 reproducibility count changed")
    held_out = payload.get("held_out_policy") or {}
    if held_out.get("opened_at_preregistration") is not False:
        errors.append("v6 held-out data was opened before preregistration")
    if held_out.get("maximum_full_longmemeval_v2_runs") != 1:
        errors.append("v6 LongMemEval must remain one-shot")
    terminal = str(payload.get("terminal_rule") or "")
    if "failed_experiment_v6" not in terminal or "remain unchanged" not in terminal:
        errors.append("scientific v6 fail-closed terminal rule is missing")
    return errors
