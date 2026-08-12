from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    canonical_json_bytes,
    repository_commit,
    sha256_bytes,
    validate_artifact_integrity,
    validate_source_manifest,
)


SCHEMA = "wavemind.evaluation_development_protocol.v2"
BASELINE_SOURCE_SHA = "8a11e037ff8616211cb640da044c137a1ed28a2b"
SAMPLE_SALT = "wavemind-goal8-bounded-development-v1"
STATE_PER_DOMAIN = 5
MEMOPS_PER_OPERATION = 5
SOURCE_PATHS = (
    "wavemind/evaluation_development_protocol.py",
    "benchmarks/evaluation_development_protocol.py",
    "tests/test_evaluation_development_protocol.py",
)

ERROR_TAXONOMY = (
    "capture_extraction_miss",
    "wrong_granularity",
    "retrieval_miss",
    "stale_or_contradictory_selection",
    "missing_state_transition",
    "bad_consolidation",
    "procedural_applicability_miss",
    "reader_failure",
    "latency_or_cost_overhead",
)
MEMOPS_PRIMARY_CONDITIONS = (
    "target_correct",
    "provenance_supported",
    "not_stale_leakage",
    "not_over_forgetting",
    "not_deleted_resurfacing",
    "not_unverified_injection",
    "not_namespace_leakage",
)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _ranked_sample(
    units: Sequence[Mapping[str, Any]], *, count: int, stratum: str
) -> list[Mapping[str, Any]]:
    if len(units) < count:
        raise ValueError(f"not enough development units for stratum {stratum}")
    return sorted(
        units,
        key=lambda unit: (
            sha256_bytes(
                f"{SAMPLE_SALT}:{stratum}:{unit['unit_id']}".encode("utf-8")
            ),
            str(unit["unit_id"]),
        ),
    )[:count]


def _bounded_units(split_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    units = split_payload.get("units")
    if not isinstance(units, list):
        raise ValueError("evaluation split units are missing")
    development = [
        unit
        for unit in units
        if isinstance(unit, Mapping) and unit.get("split") == "development"
    ]
    selected: list[Mapping[str, Any]] = []
    by_state_domain: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_memops_operation: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for unit in development:
        if unit.get("dataset") == "state-bench":
            by_state_domain[str(unit.get("domain"))].append(unit)
        elif unit.get("dataset") == "memops":
            by_memops_operation[str(unit.get("operation_type"))].append(unit)
    for domain in sorted(by_state_domain):
        selected.extend(
            _ranked_sample(
                by_state_domain[domain],
                count=STATE_PER_DOMAIN,
                stratum=f"state-bench:{domain}",
            )
        )
    for operation in sorted(by_memops_operation):
        selected.extend(
            _ranked_sample(
                by_memops_operation[operation],
                count=MEMOPS_PER_OPERATION,
                stratum=f"memops:{operation}",
            )
        )
    return [
        {
            "dataset": str(unit["dataset"]),
            "unit_id": str(unit["unit_id"]),
            "stratum": str(unit.get("domain") or unit.get("operation_type")),
            "cluster_id": str(unit.get("subject_id") or unit["unit_id"]),
            "derived_fingerprint": str(unit["derived_fingerprint"]),
        }
        for unit in sorted(
            selected, key=lambda unit: (str(unit["dataset"]), str(unit["unit_id"]))
        )
    ]


def build_evaluation_development_protocol(
    *,
    project_root: str | Path,
    dataset_manifest_path: str | Path,
    split_manifest_path: str | Path,
    judge_policy_path: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    dataset = _json(Path(dataset_manifest_path))
    split = _json(Path(split_manifest_path))
    judge = _json(Path(judge_policy_path))
    if split.get("source_sha") is None:
        raise ValueError("split manifest source SHA is missing")
    bounded_units = _bounded_units(split)
    unit_digest = sha256_bytes(canonical_json_bytes(bounded_units))
    payload = {
        "schema": SCHEMA,
        "revision": "goal8-bounded-development-v2-20260812",
        "source_sha": repository_commit(root),
        "baseline_source_sha": BASELINE_SOURCE_SHA,
        "phase": "development_only",
        "heldout_access": "forbidden",
        "frozen_inputs": {
            "dataset_manifest_payload_sha256": dataset.get("integrity", {}).get(
                "payload_sha256"
            ),
            "split_manifest_payload_sha256": split.get("integrity", {}).get(
                "payload_sha256"
            ),
            "judge_policy_payload_sha256": judge.get("integrity", {}).get(
                "payload_sha256"
            ),
            "sample_salt": SAMPLE_SALT,
            "bounded_units_sha256": unit_digest,
        },
        "bounded_sample": {
            "state_bench_per_domain": STATE_PER_DOMAIN,
            "memops_per_operation_type": MEMOPS_PER_OPERATION,
            "unit_count": len(bounded_units),
            "units": bounded_units,
        },
        "families": [
            {
                "id": "state-bench-agent-learning",
                "layer": "workflow",
                "primary_metric": "deterministic_final_state_pass",
                "secondary_metrics": [
                    "turns",
                    "tool_calls",
                    "tool_errors",
                    "context_characters",
                ],
                "cluster_unit": "task_id",
                "quality_claim_eligible": False,
                "blocked_until": (
                    "a local open-weight tool-calling agent profile is pinned before "
                    "execution; recorded trajectories may validate the scorer but may "
                    "not measure a WaveMind treatment effect"
                ),
            },
            {
                "id": "memops-lifecycle",
                "layer": "lifecycle",
                "primary_metric": "operation_state_transition",
                "primary_metric_definition": {
                    "pass_when_all": list(MEMOPS_PRIMARY_CONDITIONS),
                    "unit": "target_state",
                    "aggregation": "mean_then_paired_by_subject_id",
                },
                "secondary_metrics": [
                    "target_binding",
                    "provenance_support",
                    "stale_leakage",
                    "over_forgetting",
                    "unsupported_inference",
                ],
                "cluster_unit": "subject_id",
                "quality_claim_eligible": True,
                "reader": "deterministic_structured_state_v1",
            },
        ],
        "comparators": [
            "no_memory",
            "full_correct_state_oracle",
            "static_hybrid_same_corpus",
            "wavemind_core",
            "wavemind_memory_os",
        ],
        "fairness": {
            "same_source_corpus": True,
            "same_backend_query_view": True,
            "same_context_budget": True,
            "gold_and_evaluator_metadata_hidden": True,
            "competitor_substitution_forbidden": True,
            "non_comparable_embeddings_must_be_declared": True,
        },
        "error_taxonomy": list(ERROR_TAXONOMY),
        "bounded_go_no_go": {
            "minimum_primary_point_lift": 0.05,
            "maximum_other_family_regression": 0.02,
            "maximum_stale_or_contradictory_leakage": 0.02,
            "maximum_namespace_leakage": 0.0,
            "maximum_deleted_evidence_resurfacing": 0.0,
            "maximum_context_regression": 0.10,
            "maximum_warm_p95_latency_regression": 0.20,
            "candidate_limit_per_hypothesis": 2,
            "validation_or_final_error_analysis_forbidden": True,
        },
        "statistics": {
            "paired": True,
            "clustered_by_family_cluster_unit": True,
            "confidence_level": 0.95,
            "bootstrap_repeats": 2000,
            "seed": 17,
            "multiple_primary_correction": "holm",
            "bounded_dev_point_gate_is_not_final_quality_evidence": True,
        },
        "run_requirements": {
            "exact_source_sha": True,
            "complete_per_case_evidence": True,
            "failed_error_skipped_rows_retained": True,
            "environment_fingerprint": True,
            "dataset_and_protocol_checksums": True,
            "product_tuning_before_baseline_error_taxonomy": False,
            "heavy_or_gpu_run_requires_user_permission": True,
        },
        "source_manifest": build_source_manifest(root, SOURCE_PATHS),
        "claim_boundary": (
            "Frozen development-only protocol and sample selection. It does not run a "
            "benchmark, open validation/final data, or establish a quality claim."
        ),
    }
    return attach_artifact_integrity(payload)


def validate_evaluation_development_protocol(
    payload: Mapping[str, Any],
    *,
    project_root: str | Path,
    dataset_manifest_path: str | Path,
    split_manifest_path: str | Path,
    judge_policy_path: str | Path,
) -> list[str]:
    root = Path(project_root).resolve()
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != SCHEMA:
        errors.append("development protocol schema is invalid")
    if payload.get("phase") != "development_only":
        errors.append("development protocol phase is not development-only")
    if payload.get("heldout_access") != "forbidden":
        errors.append("development protocol does not forbid held-out access")
    source_manifest = payload.get("source_manifest")
    if not isinstance(source_manifest, Mapping):
        errors.append("development protocol source manifest is missing")
    else:
        errors.extend(
            validate_source_manifest(root, source_manifest, require_current_files=True)
        )

    dependencies = (
        ("dataset_manifest_payload_sha256", Path(dataset_manifest_path)),
        ("split_manifest_payload_sha256", Path(split_manifest_path)),
        ("judge_policy_payload_sha256", Path(judge_policy_path)),
    )
    frozen = payload.get("frozen_inputs")
    if not isinstance(frozen, Mapping):
        errors.append("development protocol frozen inputs are missing")
        frozen = {}
    for field, path in dependencies:
        current = _json(path).get("integrity", {}).get("payload_sha256")
        if frozen.get(field) != current:
            errors.append(f"development protocol dependency mismatch: {field}")

    sample = payload.get("bounded_sample")
    units = sample.get("units") if isinstance(sample, Mapping) else None
    if not isinstance(units, list):
        errors.append("development protocol bounded units are missing")
        units = []
    if sample.get("unit_count") != len(units) if isinstance(sample, Mapping) else True:
        errors.append("development protocol bounded unit count mismatch")
    if any(unit.get("dataset") not in {"state-bench", "memops"} for unit in units):
        errors.append("development protocol contains an unsupported dataset")
    split = _json(Path(split_manifest_path))
    expected_units = _bounded_units(split)
    if units != expected_units:
        errors.append("development protocol bounded selection changed")
    expected_digest = sha256_bytes(canonical_json_bytes(expected_units))
    if frozen.get("bounded_units_sha256") != expected_digest:
        errors.append("development protocol bounded selection digest mismatch")

    taxonomy = payload.get("error_taxonomy")
    if taxonomy != list(ERROR_TAXONOMY):
        errors.append("development protocol error taxonomy changed")
    families = payload.get("families")
    if not isinstance(families, list):
        errors.append("development protocol task families are missing")
    else:
        memops = next(
            (
                family
                for family in families
                if isinstance(family, Mapping)
                and family.get("id") == "memops-lifecycle"
            ),
            None,
        )
        definition = (
            memops.get("primary_metric_definition")
            if isinstance(memops, Mapping)
            else None
        )
        if not isinstance(definition, Mapping) or definition.get(
            "pass_when_all"
        ) != list(MEMOPS_PRIMARY_CONDITIONS):
            errors.append("MemOps primary lifecycle metric definition changed")
    go_no_go = payload.get("bounded_go_no_go")
    if not isinstance(go_no_go, Mapping):
        errors.append("development protocol go/no-go policy is missing")
    else:
        if go_no_go.get("candidate_limit_per_hypothesis") != 2:
            errors.append("development protocol candidate stop rule changed")
        if go_no_go.get("validation_or_final_error_analysis_forbidden") is not True:
            errors.append("development protocol permits non-development error analysis")
    requirements = payload.get("run_requirements")
    if not isinstance(requirements, Mapping):
        errors.append("development protocol run requirements are missing")
    elif requirements.get("product_tuning_before_baseline_error_taxonomy") is not False:
        errors.append("development protocol permits tuning before baseline taxonomy")
    return errors
