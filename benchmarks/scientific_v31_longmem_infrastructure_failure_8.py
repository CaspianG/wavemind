from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity, file_sha256


RUN_ROOT = ROOT / "benchmarks" / "scientific_longmemeval_v31_final"
MARKER = RUN_ROOT / "full_run_marker.json"
CANDIDATE = RUN_ROOT / "candidate_web_small"
FAILED_ARM = RUN_ROOT / "no_retrieval_web_small"
LOG = RUN_ROOT / "continuation8_console.log"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_8.json"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _line_count(path: Path) -> int:
    return sum(1 for line in path.open(encoding="utf-8") if line.strip())


def main() -> int:
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    candidate_metrics = CANDIDATE / "aggregated_metrics.json"
    candidate_rows = CANDIDATE / "per_question.jsonl"
    failed_rows = FAILED_ARM / "per_question.jsonl"
    failed_metrics = FAILED_ARM / "aggregated_metrics.json"
    if not candidate_metrics.is_file() or not candidate_rows.is_file():
        raise RuntimeError("candidate web arm was not completed before failure")
    log_text = LOG.read_text(encoding="utf-8")
    if "Generating: 100%" not in log_text or "240/240" not in log_text:
        raise RuntimeError("console log does not prove completed reader generation")
    if not failed_rows.is_file() or _line_count(failed_rows) != 7:
        raise RuntimeError("failed arm does not contain the seven completed scoring rows")
    if failed_metrics.exists():
        raise RuntimeError("unexpected aggregate for failed scoring arm")
    retained = sorted(path.name for path in (RUN_ROOT / "retained_partials").iterdir() if path.is_dir())

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_infrastructure_failure.v8",
            "status": "failed_during_second_arm_scoring_before_aggregate",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": marker["logical_full_run_count"],
            "infrastructure_failure_sequence": 8,
            "candidate_source_sha": marker["candidate_source_sha"],
            "loopback_continuation_plan_commit": "0893153a8ffc650ddd24425f1b2b0c75159c9bc4",
            "failure": {
                "stage": "no_retrieval_web_small_official_scoring",
                "type": "UnacceptedLeadingBinaryReasonFormat",
                "observed_error": "ValueError: Could not parse evaluator binary judgement",
                "observed_judge_shape": "1, reason: <non-empty explanation>",
                "scoring_progress": "7/240",
                "causal_diagnosis": (
                    "The frozen evaluator emitted an unambiguous leading binary label followed "
                    "by a comma and reason field. The official parser accepts JSON and explicit "
                    "label fields but not this semantically equivalent surface form."
                ),
                "candidate_or_threshold_failure": False,
                "scientific_gate_evaluated": False,
            },
            "observed_state": {
                "completed_official_arms": ["candidate_web_small"],
                "completed_reader_outputs_in_failed_arm": 240,
                "completed_scoring_rows_in_failed_arm": _line_count(failed_rows),
                "failed_arm_aggregate_exists": False,
                "failed_arm_scientific_gate_evaluated": False,
                "outcome_scores_opened_by_operator": False,
                "marker_completed": False,
                "marker": _record(MARKER),
                "candidate_web_metrics_unopened": _record(candidate_metrics),
                "candidate_web_rows_unopened": _record(candidate_rows),
                "failed_arm_rows_unopened": _record(failed_rows),
                "console_log": _record(LOG),
                "retained_partial_count": len(retained),
                "retained_partials": retained,
                "failed_arm_partial_requires_retention_on_next_continuation": True,
            },
            "required_fix_boundary": {
                "permitted_change": (
                    "If and only if the frozen parser raises ValueError, accept a full evaluator "
                    "response matching leading 0-or-1, comma, reason colon, non-empty reason."
                ),
                "accepted_compatibility_pattern": "^[01]\\s*,\\s*reason\\s*:\\s*\\S",
                "existing_parser_attempted_first": True,
                "returned_label_identical_to_leading_binary": True,
                "ambiguous_or_unlabelled_text_must_still_fail": True,
                "candidate_source_sha_unchanged_required": True,
                "prompts_models_thresholds_workers_question_order_and_gate_unchanged_required": True,
            },
            "claim_boundary": (
                "The completed candidate arm metric remains unopened, the failed comparison arm "
                "has no aggregate, and this receipt authorizes no pass or revolutionary claim."
            ),
        }
    )
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
