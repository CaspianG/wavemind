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
PLAN = ROOT / "benchmarks" / "scientific_v10_mab_final_plan.json"
RESULT = ROOT / "benchmarks" / "scientific_mab_v10_final_results.json"
RAW = ROOT / "benchmarks" / "scientific_mab_v10_final_raw.jsonl"
OUTPUT = ROOT / "benchmarks" / "scientific_v10_admission_outcome.json"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    if validate_artifact_integrity(result):
        raise RuntimeError("invalid MAB v10 final artifact integrity")
    if result["candidate_source_sha"] != CANDIDATE_SHA:
        raise RuntimeError("MAB v10 candidate SHA mismatch")
    if result["status"] != "failed_final":
        raise RuntimeError("v10 outcome generator only preserves the failed gate")
    if result["raw_output"]["sha256"] != file_sha256(RAW):
        raise RuntimeError("MAB v10 raw evidence hash mismatch")

    statistics = result["paired_cluster_bootstrap"]
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_admission_outcome.v10",
            "status": "failed_admission_v10",
            "candidate_id": result["candidate_id"],
            "candidate_source_sha": CANDIDATE_SHA,
            "protocol_digest": result["protocol_digest"],
            "mab_final_plan_digest": plan["plan_digest"],
            "failed_gate": "memoryagentbench_final_positive_uplift_lcb",
            "memoryagentbench_final": {
                "status": result["status"],
                "case_count": result["case_count"],
                "independent_cluster_count": statistics["cluster_count"],
                "intervention_coverage": result["intervention_coverage"],
                "paired_effect_values": result["paired_effect_values"],
                "mean_difference": statistics["mean_difference"],
                "ci95_lower": statistics["ci_lower"],
                "ci95_upper": statistics["ci_upper"],
                "required_ci95_lower_strictly_greater_than": 0.0,
                "production_case_count": result["production_case_count"],
                "false_verified_promotions": result["false_verified_promotions"],
                "promoted_memory_ids": result["promoted_memory_ids"],
                "gate_checks": result["gate_checks"],
                "artifact": _record(RESULT),
                "raw": _record(RAW),
            },
            "unopened_held_out_evidence": {
                "memops_final_executed": False,
                "longmemeval_v2_examples_downloaded": False,
                "longmemeval_v2_full_run_executed": False,
                "reason": (
                    "The preregistered MAB final gate failed. Opening later held-out "
                    "arms cannot rescue v10 and would spend independent evidence."
                ),
            },
            "post_outcome_policy": {
                "v10_candidate_changes_forbidden": True,
                "mab_final_cases_may_be_used_for_future_tuning": False,
                "thresholds_may_be_relaxed": False,
                "future_candidates_require_new_preregistration": True,
                "future_gates_must_use_unopened_development_evidence": True,
            },
            "claim_boundary": (
                "v10 passed six exact-SHA development runs but failed its first "
                "held-out final arm. No full admission, 100%-pass, superiority, SOTA, "
                "production, universal, or revolutionary claim is permitted."
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
