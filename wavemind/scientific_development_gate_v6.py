from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import (
    attach_artifact_integrity,
    file_sha256,
    validate_artifact_integrity,
)
from .evaluation_statistics import paired_cluster_bootstrap
from .scientific_protocol import validate_scientific_protocol_v6


SCHEMA = "wavemind.scientific_development_gate.v6"
CANDIDATE_ID = "operation-aware-tombstone-reconciler-v6"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return value


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"raw evidence is empty or invalid: {path}")
    return rows


def _record(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(root).as_posix(),
        "bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def _validate_run_artifact(
    artifact: Mapping[str, Any],
    *,
    candidate_sha: str,
    protocol_digest: str,
) -> None:
    errors = validate_artifact_integrity(artifact)
    if errors:
        raise ValueError("run artifact integrity failed: " + "; ".join(errors))
    if artifact.get("phase") != "bounded-development":
        raise ValueError("run artifact is not bounded development")
    if artifact.get("candidate_id") != CANDIDATE_ID:
        raise ValueError("run artifact candidate ID mismatch")
    if artifact.get("source_sha") != candidate_sha:
        raise ValueError("run artifact exact candidate SHA mismatch")
    if artifact.get("protocol_digest") != protocol_digest:
        raise ValueError("run artifact protocol digest mismatch")
    if artifact.get("final_split_touched") is not False:
        raise ValueError("run artifact touched a forbidden final split")
    if int(artifact.get("production_case_count") or 0) != 0:
        raise ValueError("development candidate entered production")
    if int(artifact.get("false_verified_promotions") or 0) != 0:
        raise ValueError("development candidate has a false verified promotion")
    if artifact.get("promoted_memory_ids") != []:
        raise ValueError("development candidate promoted memory IDs")


def _family_run(
    *,
    family: str,
    artifact_path: Path,
    raw_path: Path,
    candidate_sha: str,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = _load_json(artifact_path)
    _validate_run_artifact(
        artifact,
        candidate_sha=candidate_sha,
        protocol_digest=str(protocol["protocol_digest"]),
    )
    raw_metadata_key = "raw_results" if family == "memoryagentbench" else "raw_output"
    raw_metadata = artifact.get(raw_metadata_key)
    if not isinstance(raw_metadata, Mapping):
        raise ValueError(f"{family} raw metadata is missing")
    if raw_metadata.get("sha256") != file_sha256(raw_path):
        raise ValueError(f"{family} raw evidence hash mismatch")
    rows = _load_rows(raw_path)
    artifact_effects = [float(value) for value in artifact["paired_effect"]["values"]]
    effects = [float(row["paired_effect"]) for row in rows]
    if effects != artifact_effects or len(rows) != int(artifact["case_count"]):
        raise ValueError(f"{family} raw effects or count mismatch")
    if family == "memoryagentbench":
        def cluster(row: Mapping[str, Any]) -> str:
            return str(row["case_id"]).rsplit(":q", 1)[0]

        interventions = [bool(row.get("intervention_present")) for row in rows]
    else:
        def cluster(row: Mapping[str, Any]) -> str:
            return str(row["case_id"]).split("_", 1)[0]

        interventions = [bool(row.get("selected_memory_ids")) for row in rows]
    interval = paired_cluster_bootstrap(
        [
            {
                "cluster": cluster(row),
                "control": 0.0,
                "candidate": float(row["paired_effect"]),
            }
            for row in rows
        ],
        cluster_key="cluster",
        baseline_key="control",
        treatment_key="candidate",
        repeats=int(protocol["frozen_parameters"]["bootstrap_repeats"]),
        seed=int(protocol["frozen_parameters"]["seed"]),
        confidence_level=float(protocol["frozen_parameters"]["confidence_level"]),
    )
    coverage = sum(interventions) / len(interventions)
    return {
        "artifact": str(artifact_path),
        "raw": str(raw_path),
        "case_count": len(rows),
        "cluster_count": interval["cluster_count"],
        "intervention_coverage": coverage,
        "negative_effect_count": sum(value < 0.0 for value in effects),
        "paired_cluster_bootstrap": interval,
        "positive_uplift_lcb": interval["ci_lower"] > 0.0,
        "source_sha": artifact["source_sha"],
    }


def build_v6_development_gate(
    *,
    project_root: str | Path,
    candidate_sha: str,
    protocol_path: str | Path,
    mab_runs: Sequence[tuple[str | Path, str | Path]],
    memops_runs: Sequence[tuple[str | Path, str | Path]],
    retained_failed_attempts: Sequence[str | Path] = (),
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    protocol_file = Path(protocol_path).resolve()
    protocol = _load_json(protocol_file)
    protocol_errors = validate_scientific_protocol_v6(protocol, project_root=root)
    if protocol_errors:
        raise ValueError("v6 protocol validation failed: " + "; ".join(protocol_errors))
    required_runs = int(protocol["development_gate"]["required_reproducible_runs"])
    if len(mab_runs) != required_runs or len(memops_runs) != required_runs:
        raise ValueError("each family must contain exactly three reproducible runs")
    families = {
        "memoryagentbench": [
            _family_run(
                family="memoryagentbench",
                artifact_path=Path(artifact).resolve(),
                raw_path=Path(raw).resolve(),
                candidate_sha=candidate_sha,
                protocol=protocol,
            )
            for artifact, raw in mab_runs
        ],
        "memops": [
            _family_run(
                family="memops",
                artifact_path=Path(artifact).resolve(),
                raw_path=Path(raw).resolve(),
                candidate_sha=candidate_sha,
                protocol=protocol,
            )
            for artifact, raw in memops_runs
        ],
    }
    gate = protocol["development_gate"]
    minimum_clusters = int(gate["minimum_independent_clusters_per_family"])
    minimum_coverage = float(gate["minimum_candidate_intervention_coverage"])
    family_checks: dict[str, Any] = {}
    for family, runs in families.items():
        passed = all(
            run["cluster_count"] >= minimum_clusters
            and run["intervention_coverage"] >= minimum_coverage
            and run["negative_effect_count"] == 0
            and run["positive_uplift_lcb"]
            for run in runs
        )
        family_checks[family] = {
            "passed": passed,
            "reproducible_runs": len(runs),
            "runs": runs,
        }
    positive_families = sum(row["passed"] for row in family_checks.values())
    passed = (
        positive_families
        >= int(gate["independent_benchmark_families_with_positive_uplift_lcb"])
        and all(row["passed"] for row in family_checks.values())
    )
    evidence_files = [protocol_file]
    for pairs in (mab_runs, memops_runs):
        for artifact, raw in pairs:
            evidence_files.extend((Path(artifact).resolve(), Path(raw).resolve()))
    failed_files = [Path(path).resolve() for path in retained_failed_attempts]
    return attach_artifact_integrity(
        {
            "schema": SCHEMA,
            "status": "pass" if passed else "failed_experiment_v6",
            "development_gate_passed": passed,
            "advance_to_validation": passed,
            "admission_eligible": False,
            "candidate_id": CANDIDATE_ID,
            "candidate_source_sha": candidate_sha,
            "protocol_digest": protocol["protocol_digest"],
            "positive_uplift_lcb_families": positive_families,
            "families": family_checks,
            "false_verified_promotions": 0,
            "validation_split_touched": False,
            "final_split_touched": False,
            "longmemeval_v2_full_run_executed": False,
            "evidence_files": [_record(path, root) for path in evidence_files],
            "retained_failed_attempts": [_record(path, root) for path in failed_files],
            "claim_boundary": (
                "Passing bounded development authorizes exact-SHA validation only. "
                "It is not held-out admission, SOTA, or a revolutionary claim."
            ),
        }
    )
