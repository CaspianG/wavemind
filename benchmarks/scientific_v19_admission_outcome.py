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


CANDIDATE_SHA = "c509511f09dbcd3b4206ec1b74a7abc9510d9e73"
PLAN = ROOT / "benchmarks" / "scientific_v19_admission_plan.json"
MAB_RESULT = ROOT / "benchmarks" / "scientific_mab_v19_final_results.json"
MEMOPS_RESULT = ROOT / "benchmarks" / "scientific_memops_v19_final_results.json"
OUTPUT = ROOT / "benchmarks" / "scientific_v19_admission_outcome.json"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _load_valid(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_artifact_integrity(payload)
    if errors:
        raise RuntimeError(f"invalid artifact integrity: {path}: {errors}")
    return payload


def _raw_record(artifact: dict[str, object]) -> dict[str, object]:
    raw = artifact["raw_output"]
    assert isinstance(raw, dict)
    path = Path(str(raw["path"]))
    if file_sha256(path) != raw["sha256"]:
        raise RuntimeError(f"raw evidence hash mismatch: {path}")
    return _record(path)


def main() -> int:
    plan = _load_valid(PLAN)
    mab = _load_valid(MAB_RESULT)
    memops = _load_valid(MEMOPS_RESULT)
    if plan["candidate"]["source_sha"] != CANDIDATE_SHA:
        raise RuntimeError("v19 admission plan candidate SHA mismatch")
    if mab["candidate_source_sha"] != CANDIDATE_SHA or memops["source_sha"] != CANDIDATE_SHA:
        raise RuntimeError("v19 final candidate SHA mismatch")
    if mab["protocol_digest"] != plan["protocol"]["protocol_digest"]:
        raise RuntimeError("MAB final protocol mismatch")
    if memops["protocol_digest"] != plan["protocol"]["protocol_digest"]:
        raise RuntimeError("MemOps final protocol mismatch")
    if mab["status"] != "pass" or mab["gate_pass"] is not True:
        raise RuntimeError("outcome requires the retained MAB final pass")
    if memops["status"] != "failed_final" or memops["gate_pass"] is not False:
        raise RuntimeError("outcome requires the retained MemOps final failure")

    mab_stats = mab["paired_cluster_bootstrap"]
    memops_stats = memops["statistics"]
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v19_admission_outcome.v1",
            "status": "failed_admission_v19",
            "candidate_id": "targeted-dual-coverage-agent-v19",
            "candidate_source_sha": CANDIDATE_SHA,
            "protocol_digest": plan["protocol"]["protocol_digest"],
            "admission_plan": {
                **_record(PLAN),
                "payload_sha256": plan["integrity"]["payload_sha256"],
            },
            "development_gate": {
                "status": "passed_development_gate_v19",
                "required_runs_passed": 6,
                "required_runs_total": 6,
            },
            "memoryagentbench_final": {
                "status": "pass",
                "case_count": mab["case_count"],
                "independent_cluster_count": mab_stats["cluster_count"],
                "mean_difference": mab_stats["mean_difference"],
                "ci95_lower": mab_stats["ci_lower"],
                "ci95_upper": mab_stats["ci_upper"],
                "intervention_coverage": mab["intervention_coverage"],
                "gate_checks": mab["gate_checks"],
                "artifact": _record(MAB_RESULT),
                "raw": _raw_record(mab),
            },
            "memops_final": {
                "status": "failed_final",
                "case_count": memops["case_count"],
                "independent_subject_cluster_count": memops_stats["cluster_count"],
                "mean_difference": memops_stats["mean_difference"],
                "ci95_lower": memops_stats["ci_lower"],
                "ci95_upper": memops_stats["ci_upper"],
                "required_ci95_lower_strictly_greater_than": 0.0,
                "intervention_coverage": memops["intervention_coverage"],
                "failed_gate": (
                    "paired_subject_cluster_bootstrap_ci_lower_strictly_positive"
                ),
                "gate_checks": memops["gate_checks"],
                "artifact": _record(MEMOPS_RESULT),
                "raw": _raw_record(memops),
            },
            "unopened_held_out_evidence": {
                "longmemeval_v2_examples_downloaded": False,
                "longmemeval_v2_full_run_executed": False,
                "reason": (
                    "The preregistered MemOps final gate failed. Opening the later "
                    "one-shot LongMemEval-V2 arm cannot rescue v19 and would spend "
                    "independent evidence."
                ),
            },
            "post_outcome_policy": {
                "v19_candidate_changes_forbidden": True,
                "v19_final_cases_may_be_used_for_future_tuning": False,
                "thresholds_may_be_relaxed": False,
                "repeat_v19_final_runs_forbidden": True,
                "future_candidates_require_new_preregistration": True,
                "future_gates_require_unopened_development_and_final_evidence": True,
            },
            "claim_boundary": (
                "v19 passed six exact-SHA development runs and the MAB final arm, "
                "but failed the MemOps final positive-LCB gate. No full admission, "
                "100%-pass, SOTA, production, universal, or revolutionary claim is "
                "permitted."
            ),
        }
    )
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
