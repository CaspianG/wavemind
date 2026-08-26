from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity, file_sha256


RUN_ROOT = ROOT / "benchmarks" / "scientific_longmemeval_v31_final"
ARM = RUN_ROOT / "candidate_web_small"
MARKER = RUN_ROOT / "full_run_marker.json"
RUN_ARGS = ARM / "run_args.json"
LOG = RUN_ROOT / "continuation6_console.log"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_6.json"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def main() -> int:
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    args = json.loads(RUN_ARGS.read_text(encoding="utf-8"))
    forbidden = [
        name
        for name in (
            "prompts.jsonl",
            "answers.jsonl",
            "per_question.jsonl",
            "aggregated_metrics.json",
        )
        if (ARM / name).exists()
    ]
    if forbidden:
        raise RuntimeError(f"unexpected benchmark outcomes before failure receipt: {forbidden}")
    retained = sorted(
        path.name
        for path in (RUN_ROOT / "retained_partials").iterdir()
        if path.is_dir()
    )
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_infrastructure_failure.v6",
            "status": "safety_aborted_before_outcomes",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": marker["logical_full_run_count"],
            "infrastructure_failure_sequence": 6,
            "candidate_source_sha": marker["candidate_source_sha"],
            "streaming_harness_commit": "404c6b127e580d8531176d9e79cd1782bbacc79b",
            "torchvision_continuation_plan_commit": "223e722e9b90d4b0fcdad138287146618be1f583",
            "failure": {
                "stage": "candidate_web_small_official_prompt_build_fallback_recall",
                "type": "UnoptimizedFallbackRankedSelector",
                "causal_diagnosis": (
                    "The operation-aware selector was streaming, but a held-out query with "
                    "no eligible operation markers took the frozen candidate fallback "
                    "_select_ranked_memories path. That path materialized a complete token "
                    "set for every one of 28,768 definitions before intersecting with the "
                    "small query token set. The v31 query lock left three workers waiting "
                    "while one CPU-bound fallback selector ran."
                ),
                "operator_interrupt_sent": True,
                "candidate_or_threshold_failure": False,
                "scientific_gate_evaluated": False,
            },
            "read_only_stack_snapshot": {
                "tool": "py-spy 0.4.2 dump",
                "process_python": "3.11.0",
                "main_thread_state": "waiting for ThreadPoolExecutor shutdown",
                "waiting_prompt_workers": 3,
                "active_prompt_workers": 1,
                "active_frames": [
                    "wavemind.scientific_reconciliation._tokens:108",
                    "wavemind.scientific_reconciliation._select_ranked_memories:476-477",
                    "wavemind.scientific_reconciliation.select:230",
                    "wavemind.scientific_runtime.evaluation_recall:491",
                    "scientific_longmemeval_v2_backend.query:244",
                    "scientific_longmemeval_v2_backend_v31.synchronized_query:179",
                    "evaluation.harness.build_prompt_row:567",
                ],
                "question_text_or_answer_emitted": False,
            },
            "resource_telemetry": {
                "samples": [
                    {"elapsed_minutes": 1.52, "private_gib": 3.009},
                    {"elapsed_minutes": 2.31, "private_gib": 3.885},
                    {"elapsed_minutes": 4.61, "private_gib": 3.951},
                    {"elapsed_minutes": 7.36, "private_gib": 3.829},
                    {"elapsed_minutes": 10.98, "private_gib": 3.985},
                    {"elapsed_minutes": 15.14, "private_gib": 4.004},
                    {"elapsed_minutes": 19.21, "private_gib": 3.929},
                ],
                "plateau_observed": True,
                "maximum_observed_private_gib": 4.007,
                "elapsed_minutes_at_abort": 19.21,
                "prompt_rows_completed": 0,
                "top_four_worker_cpu_seconds_range": [276.4, 290.0],
            },
            "observed_state": {
                "completed_official_arms": [],
                "completed_prompt_rows": 0,
                "answers_generated": False,
                "outcome_scores_opened": False,
                "per_question_files": 0,
                "aggregated_metrics_files": 0,
                "marker_completed": False,
                "marker": _record(MARKER),
                "run_args": _record(RUN_ARGS),
                "console_log": _record(LOG),
                "retained_partial_count_before_attempt": 5,
                "retained_partials_before_attempt": retained,
                "current_partial_requires_retention_on_next_continuation": True,
            },
            "frozen_execution_parameters": {
                "model": args["model"],
                "evaluator_model": args["evaluator_model"],
                "prompt_build_max_workers": args["prompt_build_max_workers"],
                "reader_max_concurrent_requests": args["reader_max_concurrent_requests"],
                "shuffle_questions_seed": args["shuffle_questions_seed"],
            },
            "required_fix_boundary": {
                "permitted_change": (
                    "Replace only fallback _select_ranked_memories full token-set "
                    "materialization with an exact streaming query-token intersection."
                ),
                "must_preserve": [
                    "query tokenization",
                    "document frequency",
                    "query weights",
                    "phrase hits",
                    "recency scores",
                    "ranking tuples",
                    "budget fit",
                    "selection relevance and reason",
                ],
                "candidate_source_sha_unchanged_required": True,
                "prompts_models_thresholds_workers_scoring_unchanged_required": True,
            },
            "claim_boundary": (
                "This pre-outcome infrastructure failure contains no answer or score and "
                "authorizes no scientific pass or revolutionary claim."
            ),
        }
    )
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
