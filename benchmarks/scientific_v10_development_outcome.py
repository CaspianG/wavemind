from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import (
    attach_artifact_integrity,
    file_sha256,
    validate_artifact_integrity,
)


CANDIDATE_SHA = "47b68e366aab9ce07b659c61a51c81d634b3fff2"
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v10.json"
OUTPUT = ROOT / "benchmarks" / "scientific_v10_development_outcome.json"
RUNS = {
    "memops_adjacent_operation": [
        ROOT / "benchmarks" / f"scientific_memops_v10_adjacent_run{run}_results.json"
        for run in (1, 2, 3)
    ],
    "memops_longitudinal_operation": [
        ROOT / "benchmarks" / f"scientific_memops_v10_longitudinal_run{run}_results.json"
        for run in (1, 2, 3)
    ],
}


def _file_record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def main() -> int:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    families: dict[str, object] = {}
    for family, paths in RUNS.items():
        run_records = []
        for expected_run, path in enumerate(paths, start=1):
            artifact = json.loads(path.read_text(encoding="utf-8"))
            if validate_artifact_integrity(artifact):
                raise RuntimeError(f"invalid artifact integrity: {path}")
            if artifact["source_sha"] != CANDIDATE_SHA:
                raise RuntimeError(f"candidate SHA mismatch: {path}")
            if artifact["protocol_digest"] != protocol["protocol_digest"]:
                raise RuntimeError(f"protocol digest mismatch: {path}")
            if artifact["family"] != family or artifact["run_number"] != expected_run:
                raise RuntimeError(f"family/run mismatch: {path}")
            if artifact["gate_pass"] is not True:
                raise RuntimeError(f"development gate did not pass: {path}")
            raw_path = Path(artifact["raw_output"]["path"])
            if file_sha256(raw_path) != artifact["raw_output"]["sha256"]:
                raise RuntimeError(f"raw evidence hash mismatch: {raw_path}")
            run_records.append(
                {
                    "run_number": expected_run,
                    "artifact": _file_record(path),
                    "raw": _file_record(raw_path),
                    "case_count": artifact["case_count"],
                    "intervention_coverage": artifact["intervention_coverage"],
                    "statistics": artifact["statistics"],
                    "gate_pass": True,
                }
            )
        families[family] = {
            "required_runs": 3,
            "passing_runs": 3,
            "all_runs_pass": True,
            "runs": run_records,
        }
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v10_development_outcome.v1",
            "status": "passed_development_gate_v10",
            "candidate_source_sha": CANDIDATE_SHA,
            "protocol_digest": protocol["protocol_digest"],
            "required_independent_families": 2,
            "passing_independent_families": 2,
            "required_reproducible_runs_per_family": 3,
            "all_required_runs_pass": True,
            "families": families,
            "final_split_touched": False,
            "admission_arms_executed": [],
            "admission_permitted_next": True,
            "claim_boundary": (
                "Development-only evidence passed. No held-out, SOTA, universal, "
                "production, 100%-pass, or revolutionary claim is permitted until "
                "the exact candidate SHA passes every frozen admission arm."
            ),
        }
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
