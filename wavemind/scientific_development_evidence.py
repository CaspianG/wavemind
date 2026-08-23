from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .evidence import (
    attach_artifact_integrity,
    file_sha256,
    validate_artifact_integrity,
)
from .evaluation_statistics import paired_cluster_bootstrap
from .scientific_protocol import protocol_digest
from .scientific_state_bench import validate_prepared_state_bench_artifact


SCHEMA = "wavemind.scientific_development_evidence.v1"


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _validate_candidate_artifact(
    payload: Mapping[str, Any],
    *,
    expected_candidate: str,
) -> None:
    errors = validate_artifact_integrity(payload)
    if errors:
        raise ValueError("candidate artifact integrity failed: " + "; ".join(errors))
    if payload.get("phase") != "bounded-development":
        raise ValueError("candidate artifact is not bounded development")
    if payload.get("candidate_id") != expected_candidate:
        raise ValueError("candidate artifact ID mismatch")
    if payload.get("admission_eligible") is not False:
        raise ValueError("development artifact cannot be admission eligible")


def _mab_evidence(
    artifact: Mapping[str, Any],
    *,
    raw_path: Path,
) -> dict[str, Any]:
    raw = artifact.get("raw_results")
    if not isinstance(raw, Mapping) or raw.get("sha256") != file_sha256(raw_path):
        raise ValueError("MAB raw evidence hash mismatch")
    rows = _rows(raw_path)
    if len(rows) != artifact.get("case_count"):
        raise ValueError("MAB raw evidence count mismatch")
    effects = [float(row["paired_effect"]) for row in rows]
    if effects != [float(value) for value in artifact["paired_effect"]["values"]]:
        raise ValueError("MAB paired effects mismatch")
    interval = paired_cluster_bootstrap(
        [
            {
                "context": str(row["case_id"]).rsplit(":q", 1)[0],
                "control": 0.0,
                "candidate": float(row["paired_effect"]),
            }
            for row in rows
        ],
        cluster_key="context",
        baseline_key="control",
        treatment_key="candidate",
        repeats=2000,
        seed=17,
        confidence_level=0.95,
    )
    return {
        "artifact_source_sha": artifact["source_sha"],
        "case_ids": [str(row["case_id"]) for row in rows],
        "raw_path": str(raw_path),
        "raw_sha256": file_sha256(raw_path),
        "paired_cluster_bootstrap": interval,
        "positive_uplift_lcb": interval["ci_lower"] > 0.0,
        "production_case_count": artifact["production_case_count"],
        "promoted_memory_ids": list(artifact["promoted_memory_ids"]),
        "false_verified_promotions": artifact["false_verified_promotions"],
    }


def _memops_evidence(artifact: Mapping[str, Any]) -> dict[str, Any]:
    raw = artifact.get("raw_output")
    if not isinstance(raw, Mapping):
        raise ValueError("MemOps raw evidence metadata is missing")
    raw_path = Path(str(raw["path"])).resolve()
    if not raw_path.is_file() or raw.get("sha256") != file_sha256(raw_path):
        raise ValueError("MemOps raw evidence hash mismatch")
    subjects = sorted({str(case).split("_", 1)[0] for case in artifact["case_ids"]})
    return {
        "artifact_source_sha": artifact["source_sha"],
        "case_ids": list(artifact["case_ids"]),
        "independent_subject_ids": subjects,
        "independent_cluster_count": len(subjects),
        "confidence_interval_status": "insufficient_independent_clusters",
        "observed_mean_effect": artifact["paired_effect"]["mean"],
        "raw_path": str(raw_path),
        "raw_sha256": file_sha256(raw_path),
        "production_case_count": artifact["production_case_count"],
        "promoted_memory_ids": list(artifact["promoted_memory_ids"]),
        "false_verified_promotions": artifact["false_verified_promotions"],
    }


def build_development_evidence(
    *,
    source_sha: str,
    protocol: Mapping[str, Any],
    mab_artifacts: Mapping[str, Mapping[str, Any]],
    mab_raw_paths: Mapping[str, Path],
    memops_artifacts: Mapping[str, Mapping[str, Any]],
    state_bench_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    candidate_ids = tuple(sorted(mab_artifacts))
    if candidate_ids != tuple(sorted(memops_artifacts)) or len(candidate_ids) != 2:
        raise ValueError("exactly two paired preregistered candidates are required")
    if protocol.get("protocol_digest") != protocol_digest(protocol):
        raise ValueError("frozen protocol integrity failed")
    if validate_prepared_state_bench_artifact(state_bench_artifact):
        raise ValueError("prepared STATE-Bench artifact is invalid")
    candidates: dict[str, Any] = {}
    for candidate_id in candidate_ids:
        mab = mab_artifacts[candidate_id]
        memops = memops_artifacts[candidate_id]
        _validate_candidate_artifact(mab, expected_candidate=candidate_id)
        _validate_candidate_artifact(memops, expected_candidate=candidate_id)
        candidates[candidate_id] = {
            "memoryagentbench": _mab_evidence(
                mab,
                raw_path=mab_raw_paths[candidate_id].resolve(),
            ),
            "memops": _memops_evidence(memops),
            "advance_to_validation": False,
            "decision": (
                "No positive lower 95% confidence bound on multicluster MAB; "
                "MemOps mean is negative and has only one independent subject."
            ),
        }
    return attach_artifact_integrity(
        {
            "schema": SCHEMA,
            "source_sha": source_sha,
            "protocol_digest": protocol["protocol_digest"],
            "status": "failed_experiment",
            "admission_eligible": False,
            "candidates": candidates,
            "state_bench": {
                "status": state_bench_artifact["status"],
                "source_sha": state_bench_artifact["source_sha"],
                "official_execution_succeeded": state_bench_artifact["credentials"][
                    "official_execution_succeeded"
                ],
                "validation_or_final_touched": False,
            },
            "longmemeval_v2": {
                "full_451_run_executed": False,
                "reason": "no passed development gate artifact exists",
            },
            "claim_boundary": (
                "Bounded development failed to establish positive causal utility. "
                "No admission, SOTA, WaveField replacement, validation, or held-out "
                "claim is permitted."
            ),
        }
    )
