from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity, file_sha256


CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
RESOURCE_HARNESS_COMMIT = "627f7b054229f1f33f04fe35464b4fd77add65ee"
RESOURCE_PLAN_COMMIT = "9cebc2e733e38dd9b862a946bff9bc27fc084e7d"
RUN_ROOT = ROOT / "benchmarks" / "scientific_longmemeval_v31_final"
MARKER = RUN_ROOT / "full_run_marker.json"
RUN_ARGS = RUN_ROOT / "candidate_web_small" / "run_args.json"
CONSOLE_LOG = RUN_ROOT / "continuation4_console.log"
SCRATCH_DB = (
    RUN_ROOT
    / "candidate-scratch"
    / "wavemind-lme-v6-d98_k2l4"
    / "candidate.sqlite3.scientific-events.sqlite3"
)
SCRATCH_WAL = Path(str(SCRATCH_DB) + "-wal")
SCRATCH_SHM = Path(str(SCRATCH_DB) + "-shm")
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_4.json"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def main() -> int:
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    run_args = json.loads(RUN_ARGS.read_text(encoding="utf-8"))
    if marker.get("logical_full_run_count") != 1 or marker.get("status") == "completed":
        raise RuntimeError("controlled abort is not in the incomplete logical run")
    if list(RUN_ROOT.rglob("per_question.jsonl")):
        raise RuntimeError("per-question outcomes exist before safety-abort freeze")
    if list(RUN_ROOT.rglob("aggregated_metrics.json")):
        raise RuntimeError("aggregate outcomes exist before safety-abort freeze")
    connection = sqlite3.connect(f"file:{SCRATCH_DB.as_posix()}?mode=ro", uri=True)
    try:
        event_count, event_json_bytes, max_sequence = connection.execute(
            "SELECT count(*), coalesce(sum(length(event_json)), 0), "
            "coalesce(max(sequence), 0) FROM scientific_memory_events"
        ).fetchone()
    finally:
        connection.close()
    if (event_count, event_json_bytes, max_sequence) != (28768, 97046543, 28768):
        raise RuntimeError("controlled-abort scratch aggregate changed")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_infrastructure_failure.v4",
            "status": "safety_aborted_before_outcomes",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": 1,
            "infrastructure_failure_sequence": 4,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "resource_harness_commit": RESOURCE_HARNESS_COMMIT,
            "resource_continuation_plan_commit": RESOURCE_PLAN_COMMIT,
            "failure": {
                "stage": "candidate_web_small_first_query_selection",
                "type": "ControlledMemorySafetyAbort",
                "causal_diagnosis": (
                    "Serializing shared queries removed concurrency but private bytes "
                    "still grew monotonically inside the first query. The frozen v6 "
                    "operation selector retained a full token set for each of 28,768 "
                    "definitions, expanding 97 MB of serialized event JSON into many "
                    "gigabytes of Python token objects."
                ),
                "operator_interrupt_sent": True,
                "reason_for_interrupt": (
                    "Prevent recurrence of the already proven Windows resource "
                    "exhaustion and collateral Codex/application crashes."
                ),
                "python_traceback_emitted": False,
                "candidate_or_threshold_failure": False,
                "scientific_gate_evaluated": False,
            },
            "resource_telemetry": {
                "samples": [
                    {
                        "elapsed_minutes": 5.6,
                        "cpu_seconds": 329.84,
                        "private_gib": 6.17,
                        "free_virtual_gib": 21.6,
                    },
                    {
                        "elapsed_minutes": 10.8,
                        "cpu_seconds": 645.61,
                        "private_gib": 9.43,
                        "free_virtual_gib": 18.4,
                    },
                    {
                        "elapsed_minutes": 15.2,
                        "cpu_seconds": 907.02,
                        "private_gib": 11.99,
                        "free_virtual_gib": 15.8,
                    },
                ],
                "private_memory_growth_gib": 5.82,
                "growth_plateau_observed": False,
                "previous_oom_peak_bytes": 29787037696,
            },
            "scratch_evidence": {
                "database": _record(SCRATCH_DB),
                "database_wal": _record(SCRATCH_WAL),
                "database_shm": _record(SCRATCH_SHM),
                "event_count": event_count,
                "event_json_bytes": event_json_bytes,
                "max_sequence": max_sequence,
                "all_definitions_registered_before_selection": True,
            },
            "observed_state": {
                "completed_official_arms": [],
                "partial_arm": "candidate_web_small",
                "completed_prompt_rows": 0,
                "answers_generated": False,
                "outcome_scores_opened": False,
                "per_question_files": 0,
                "aggregated_metrics_files": 0,
                "marker_completed": False,
                "marker": _record(MARKER),
                "run_args": _record(RUN_ARGS),
                "console_log": _record(CONSOLE_LOG),
            },
            "frozen_execution_parameters": {
                "model": run_args["model"],
                "evaluator_model": run_args["evaluator_model"],
                "shuffle_questions_seed": run_args["shuffle_questions_seed"],
                "prompt_build_max_workers": run_args["prompt_build_max_workers"],
                "reader_max_concurrent_requests": run_args[
                    "reader_max_concurrent_requests"
                ],
            },
            "continuation_policy": {
                "same_logical_run_required": True,
                "partial_retained_verbatim_required": True,
                "candidate_unchanged_required": True,
                "data_unchanged_required": True,
                "prompts_unchanged_required": True,
                "models_unchanged_required": True,
                "thresholds_unchanged_required": True,
                "worker_counts_unchanged_required": True,
                "permitted_harness_change": (
                    "Replace the v6 selector's retained full-token-set mapping with "
                    "streaming computation of the exact same query-token intersections. "
                    "Require exact selection, relevance, and reason equivalence tests."
                ),
                "attempts_count_as_scientific_runs": 1,
            },
            "claim_boundary": (
                "The controlled safety abort produced no benchmark outcome and "
                "authorizes no pass, 100%-pass, SOTA, or revolutionary claim."
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
