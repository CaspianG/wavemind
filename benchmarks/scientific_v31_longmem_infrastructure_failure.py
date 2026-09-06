from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity, file_sha256


CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
PROTOCOL_DIGEST = "bc1f895bdf8bd30027bcc17f1c3a375099c8ee442681382c56ba57fa7580793b"
ORIGINAL_HARNESS_COMMIT = "8d5052b94dea2cdc2db020208800577e3267ab3c"
ADMISSION_PLAN_COMMIT = "8135561b4c532817bf9502556c099a5e52ebb19e"
RUN_ROOT = ROOT / "benchmarks" / "scientific_longmemeval_v31_final"
MARKER = RUN_ROOT / "full_run_marker.json"
RUN_ARGS = RUN_ROOT / "candidate_web_small" / "run_args.json"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure.json"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def main() -> int:
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    run_args = json.loads(RUN_ARGS.read_text(encoding="utf-8"))
    per_question = sorted(RUN_ROOT.rglob("per_question.jsonl"))
    aggregated = sorted(RUN_ROOT.rglob("aggregated_metrics.json"))
    if marker.get("logical_full_run_count") != 1:
        raise RuntimeError("LongMemEval logical full-run count is not exactly one")
    if marker.get("candidate_source_sha") != CANDIDATE_SOURCE_SHA:
        raise RuntimeError("LongMemEval marker candidate SHA mismatch")
    if marker.get("protocol_digest") != PROTOCOL_DIGEST:
        raise RuntimeError("LongMemEval marker protocol mismatch")
    if marker.get("status") == "completed" or marker.get("completed_at"):
        raise RuntimeError("LongMemEval marker unexpectedly records completion")
    if per_question or aggregated:
        raise RuntimeError("outcome-bearing LongMemEval files already exist")
    if run_args.get("prompt_build_max_workers") != 4:
        raise RuntimeError("frozen prompt-worker count changed")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_infrastructure_failure.v1",
            "status": "infrastructure_failed_before_outcomes",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": 1,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "original_harness_commit": ORIGINAL_HARNESS_COMMIT,
            "admission_plan_commit": ADMISSION_PLAN_COMMIT,
            "failure": {
                "stage": "candidate_web_small_prompt_build",
                "type": "RuntimeError",
                "outer_message": "Prompt building failed for question 6652c337",
                "cause_type": "ValueError",
                "cause_message": (
                    "memory already exists: lme-v6-000233a3f2c2d6f006e13912"
                ),
                "causal_diagnosis": (
                    "Four frozen prompt workers entered the adapter's unguarded "
                    "one-time compilation concurrently and attempted duplicate "
                    "evaluation-memory registration."
                ),
                "candidate_or_threshold_failure": False,
                "scientific_gate_evaluated": False,
            },
            "observed_state": {
                "completed_official_arms": [],
                "partial_arm": "candidate_web_small",
                "answers_generated": False,
                "outcome_scores_opened": False,
                "per_question_files": 0,
                "aggregated_metrics_files": 0,
                "marker_completed": False,
                "marker": _record(MARKER),
                "run_args": _record(RUN_ARGS),
            },
            "frozen_execution_parameters": {
                "model": run_args["model"],
                "evaluator_model": run_args["evaluator_model"],
                "temperature": run_args["temperature"],
                "top_p": run_args["top_p"],
                "top_k": run_args["top_k"],
                "shuffle_questions_seed": run_args["shuffle_questions_seed"],
                "prompt_build_max_workers": run_args["prompt_build_max_workers"],
                "reader_max_concurrent_requests": run_args[
                    "reader_max_concurrent_requests"
                ],
                "memory_context_max_tokens": run_args[
                    "memory_context_max_tokens"
                ],
            },
            "continuation_policy": {
                "authorized_by_preregistered_plan": True,
                "same_logical_run_required": True,
                "partial_retained_verbatim_required": True,
                "candidate_unchanged_required": True,
                "data_unchanged_required": True,
                "prompts_unchanged_required": True,
                "model_unchanged_required": True,
                "thresholds_unchanged_required": True,
                "order_unchanged_required": True,
                "deterministic_parameters_unchanged_required": True,
                "permitted_change": (
                    "Synchronize the adapter's one-time compilation so the frozen "
                    "four-worker prompt builder cannot register the same evaluation "
                    "memory twice."
                ),
                "attempts_count_as_scientific_runs": 1,
            },
            "claim_boundary": (
                "No LongMemEval outcome exists. This infrastructure failure is "
                "neither a pass nor a scientific gate failure, and it authorizes no "
                "100%-pass, SOTA, production, universal, or revolutionary claim."
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
