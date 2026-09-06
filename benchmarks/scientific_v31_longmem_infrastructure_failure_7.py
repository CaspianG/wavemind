from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity, file_sha256, validate_artifact_integrity


RUN_ROOT = ROOT / "benchmarks" / "scientific_longmemeval_v31_final"
ARM = RUN_ROOT / "candidate_web_small"
MARKER = RUN_ROOT / "full_run_marker.json"
RUN_ARGS = ARM / "run_args.json"
PROMPT_ROWS = ARM / "prompt_rows.jsonl"
PROMPT_SUMMARY = ARM / "prompt_build_summary.json"
LOG = RUN_ROOT / "continuation7_console.log"
PROBE = ROOT / "benchmarks" / "scientific_v31_longmem_loopback_probe_results.json"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_7.json"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def main() -> int:
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    args = json.loads(RUN_ARGS.read_text(encoding="utf-8"))
    summary = json.loads(PROMPT_SUMMARY.read_text(encoding="utf-8"))
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    probe_errors = validate_artifact_integrity(probe)
    if probe_errors:
        raise RuntimeError(f"invalid loopback probe integrity: {probe_errors}")
    forbidden = [
        name
        for name in ("prompts.jsonl", "answers.jsonl", "per_question.jsonl", "aggregated_metrics.json")
        if (ARM / name).exists()
    ]
    if forbidden:
        raise RuntimeError(f"unexpected benchmark outcomes before failure receipt: {forbidden}")
    prompt_row_count = sum(1 for _ in PROMPT_ROWS.open(encoding="utf-8"))
    if prompt_row_count != summary["prompt_row_count"]:
        raise RuntimeError("prompt row count does not match prompt-build summary")
    retained = sorted(path.name for path in (RUN_ROOT / "retained_partials").iterdir() if path.is_dir())

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_infrastructure_failure.v7",
            "status": "failed_before_first_reader_answer",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": marker["logical_full_run_count"],
            "infrastructure_failure_sequence": 7,
            "candidate_source_sha": marker["candidate_source_sha"],
            "fallback_harness_commit": "0dd456e1100a6beb5e60bdf94ddf5ffa071b2965",
            "fallback_continuation_plan_commit": "4ea14f2dc18ccabb08e5348fdba7075a037b8a20",
            "failure": {
                "stage": "candidate_web_small_reader_generation_start",
                "type": "SystemProxyLoopbackInterception",
                "observed_error": "openai.InternalServerError: Error code: 503",
                "generation_progress": "0/240",
                "causal_diagnosis": (
                    "The OpenAI Python client inherited the Windows system proxy for the "
                    "127.0.0.1 Ollama base URL. The failed SDK requests did not reach the "
                    "Ollama access log. A synthetic transport contrast reproduced an empty "
                    "HTTP 503 with httpx trust_env=True and HTTP 200 with trust_env=False."
                ),
                "candidate_or_threshold_failure": False,
                "scientific_gate_evaluated": False,
            },
            "observed_state": {
                "completed_official_arms": [],
                "completed_prompt_rows": prompt_row_count,
                "answers_generated": False,
                "outcome_scores_opened": False,
                "per_question_files": 0,
                "aggregated_metrics_files": 0,
                "marker_completed": False,
                "marker": _record(MARKER),
                "run_args": _record(RUN_ARGS),
                "prompt_build_summary": _record(PROMPT_SUMMARY),
                "prompt_rows": _record(PROMPT_ROWS),
                "console_log": _record(LOG),
                "retained_partial_count_before_attempt": len(retained),
                "retained_partials_before_attempt": retained,
                "current_partial_requires_retention_on_next_continuation": True,
            },
            "diagnostic_probe": {
                **_record(PROBE),
                "payload_sha256": probe["integrity"]["payload_sha256"],
                "scope": probe["probe_scope"],
                "inherited_transport_status": probe["observed_transport_contrast"][
                    "inherited_httpx_trust_env_true"
                ]["status"],
                "direct_transport_status": probe["observed_transport_contrast"][
                    "explicit_httpx_trust_env_false"
                ]["status"],
                "no_proxy_concurrent_statuses": [
                    row["status"] for row in probe["no_proxy_concurrent_openai_sdk"]["results"]
                ],
                "benchmark_prompt_or_answer_used": False,
            },
            "frozen_execution_parameters": {
                "model": args["model"],
                "evaluator_model": args["evaluator_model"],
                "model_digest": "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091",
                "context_window": 32768,
                "memory_context_max_tokens": args["memory_context_max_tokens"],
                "prompt_build_max_workers": args["prompt_build_max_workers"],
                "reader_max_concurrent_requests": args["reader_max_concurrent_requests"],
                "shuffle_questions_seed": args["shuffle_questions_seed"],
            },
            "required_fix_boundary": {
                "permitted_changes": [
                    "Bypass the host system proxy for 127.0.0.1 and localhost.",
                    "Warm the exact-digest local model with synthetic text before concurrent reader calls.",
                    "Enforce the preregistered 32768-token Ollama context window and one server-side sequence.",
                ],
                "candidate_source_sha_unchanged_required": True,
                "harness_commit_unchanged_required": True,
                "prompts_models_thresholds_client_workers_question_order_scoring_unchanged_required": True,
            },
            "claim_boundary": (
                "This pre-answer infrastructure failure contains no answer or score and "
                "authorizes no scientific pass or revolutionary claim."
            ),
        }
    )
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
