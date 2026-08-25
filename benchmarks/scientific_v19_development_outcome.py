from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import (
    attach_artifact_integrity,
    file_sha256,
    validate_artifact_integrity,
)


CANDIDATE_ID = "targeted-dual-coverage-agent-v19"
CANDIDATE_SHA = "c509511f09dbcd3b4206ec1b74a7abc9510d9e73"
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v19.json"
OUTPUT = ROOT / "benchmarks" / "scientific_v19_development_outcome.json"
RUNS = {
    "memoryagentbench_summarization": [
        ROOT / "benchmarks" / f"scientific_mab_v19_run{run}_results.json"
        for run in (1, 2, 3)
    ],
    "memops_longitudinal_operation": [
        ROOT
        / "benchmarks"
        / f"scientific_memops_v19_longitudinal_run{run}_results.json"
        for run in (1, 2, 3)
    ],
}


def _file_record(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(ROOT).as_posix(),
        "bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def _source_sha(artifact: dict[str, Any]) -> str:
    return str(artifact.get("candidate_source_sha") or artifact.get("source_sha"))


def _raw_path(artifact: dict[str, Any]) -> Path:
    path = Path(str(artifact["raw_output"]["path"]))
    return path if path.is_absolute() else ROOT / path


def _validate_run(
    *,
    family: str,
    expected_run: int,
    path: Path,
    protocol: dict[str, Any],
) -> dict[str, object]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_artifact_integrity(artifact)
    if errors:
        raise RuntimeError(f"invalid artifact integrity: {path}: {errors}")
    if _source_sha(artifact) != CANDIDATE_SHA:
        raise RuntimeError(f"candidate SHA mismatch: {path}")
    if artifact.get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError(f"candidate id mismatch: {path}")
    if artifact.get("protocol_digest") != protocol["protocol_digest"]:
        raise RuntimeError(f"protocol digest mismatch: {path}")
    if artifact.get("run_number") != expected_run:
        raise RuntimeError(f"run number mismatch: {path}")
    if family.startswith("memops_") and artifact.get("family") != family:
        raise RuntimeError(f"family mismatch: {path}")
    if artifact.get("status") != "pass" or artifact.get("gate_pass") is not True:
        raise RuntimeError(f"development gate did not pass: {path}")
    if artifact.get("final_split_touched") is not False:
        raise RuntimeError(f"held-out split was touched: {path}")
    if artifact.get("production_case_count") != 0:
        raise RuntimeError(f"production cases present: {path}")
    if artifact.get("false_verified_promotions") != 0:
        raise RuntimeError(f"false verified promotions present: {path}")
    if artifact.get("promoted_memory_ids"):
        raise RuntimeError(f"promoted memories present: {path}")
    if not artifact.get("gate_checks") or not all(artifact["gate_checks"].values()):
        raise RuntimeError(f"gate check failed: {path}")

    spec = protocol["frozen_development_gate"]
    statistics = artifact["statistics"]
    if statistics["cluster_count"] < spec["minimum_independent_clusters_per_family"]:
        raise RuntimeError(f"insufficient independent clusters: {path}")
    if statistics["ci_lower"] <= spec[
        "paired_cluster_bootstrap_ci_lower_strictly_greater_than"
    ]:
        raise RuntimeError(f"non-positive confidence lower bound: {path}")
    if statistics["mean_difference"] < 0.0:
        raise RuntimeError(f"negative mean difference: {path}")
    if statistics["repeats"] != protocol["frozen_parameters"]["bootstrap_repeats"]:
        raise RuntimeError(f"bootstrap repeat mismatch: {path}")
    if statistics["seed"] != protocol["frozen_parameters"]["seed"]:
        raise RuntimeError(f"bootstrap seed mismatch: {path}")
    if statistics["confidence_level"] != protocol["frozen_parameters"][
        "confidence_level"
    ]:
        raise RuntimeError(f"confidence level mismatch: {path}")
    if artifact["intervention_coverage"] < spec["minimum_intervention_coverage"]:
        raise RuntimeError(f"intervention coverage mismatch: {path}")

    raw_path = _raw_path(artifact).resolve()
    raw_record = artifact["raw_output"]
    if raw_path.stat().st_size != raw_record["bytes"]:
        raise RuntimeError(f"raw evidence size mismatch: {raw_path}")
    if file_sha256(raw_path) != raw_record["sha256"]:
        raise RuntimeError(f"raw evidence hash mismatch: {raw_path}")

    return {
        "run_number": expected_run,
        "artifact": _file_record(path),
        "raw": _file_record(raw_path),
        "case_count": artifact["case_count"],
        "intervention_coverage": artifact["intervention_coverage"],
        "statistics": statistics,
        "gate_checks": artifact["gate_checks"],
        "gate_pass": True,
    }


def main() -> int:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    spec = protocol["frozen_development_gate"]
    if set(RUNS) != set(spec["families"]):
        raise RuntimeError("outcome family set differs from frozen protocol")
    required_runs = int(spec["required_reproducible_runs"])

    families: dict[str, object] = {}
    for family, paths in RUNS.items():
        if len(paths) != required_runs:
            raise RuntimeError(f"required run count mismatch: {family}")
        run_records = [
            _validate_run(
                family=family,
                expected_run=expected_run,
                path=path,
                protocol=protocol,
            )
            for expected_run, path in enumerate(paths, start=1)
        ]
        families[family] = {
            "required_runs": required_runs,
            "passing_runs": required_runs,
            "all_runs_pass": True,
            "runs": run_records,
        }

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v19_development_outcome.v1",
            "status": "passed_development_gate_v19",
            "candidate_id": CANDIDATE_ID,
            "candidate_source_sha": CANDIDATE_SHA,
            "protocol_digest": protocol["protocol_digest"],
            "required_independent_families": spec[
                "required_independent_families"
            ],
            "passing_independent_families": len(families),
            "required_reproducible_runs_per_family": required_runs,
            "all_required_runs_pass": True,
            "families": families,
            "final_split_touched": False,
            "admission_arms_executed": [],
            "admission_permitted_next": True,
            "claim_boundary": (
                "Development-only evidence passed on six exact-SHA runs. No held-out, "
                "SOTA, universal, production, 100%-pass, or revolutionary claim is "
                "permitted until the same exact candidate SHA passes every frozen "
                "admission arm."
            ),
        }
    )
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
