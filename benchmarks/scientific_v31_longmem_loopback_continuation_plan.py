from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity, file_sha256, validate_artifact_integrity


CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
HARNESS_COMMIT = "0dd456e1100a6beb5e60bdf94ddf5ffa071b2965"
FAILURE_AND_PROBE_COMMIT = "a1b2a0fad1700825a0d85d519d4327a4a2c5e39c"
FAILURE = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_7.json"
PROBE = ROOT / "benchmarks" / "scientific_v31_longmem_loopback_probe_results.json"
MARKER = ROOT / "benchmarks" / "scientific_longmemeval_v31_final" / "full_run_marker.json"
RETAINED = ROOT / "benchmarks" / "scientific_longmemeval_v31_final" / "retained_partials"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_loopback_continuation_plan.json"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def main() -> int:
    failure = json.loads(FAILURE.read_text(encoding="utf-8"))
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    for label, payload in (("failure", failure), ("loopback probe", probe)):
        errors = validate_artifact_integrity(payload)
        if errors:
            raise RuntimeError(f"invalid {label} integrity: {errors}")
    if failure["observed_state"]["outcome_scores_opened"] is not False:
        raise RuntimeError("LongMem outcomes were opened before loopback continuation plan")
    if probe["status"] != "passed_synthetic_loopback_transport_probe":
        raise RuntimeError("synthetic loopback transport probe did not pass")
    retained = sorted(path.name for path in RETAINED.iterdir() if path.is_dir())
    if len(retained) != 6:
        raise RuntimeError(f"expected six retained pre-plan partials, found {len(retained)}")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_loopback_continuation.v1",
            "status": "preregistered_loopback_bypass_continuation_before_outcome",
            "preregistered_at": "2026-08-27",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": marker["logical_full_run_count"],
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "failure_evidence": {
                **_record(FAILURE),
                "commit": FAILURE_AND_PROBE_COMMIT,
                "payload_sha256": failure["integrity"]["payload_sha256"],
                "failure_type": failure["failure"]["type"],
                "completed_prompt_rows": failure["observed_state"]["completed_prompt_rows"],
                "answers_generated": False,
                "outcome_scores_opened": False,
                "scientific_gate_evaluated": False,
            },
            "synthetic_transport_probe": {
                **_record(PROBE),
                "commit": FAILURE_AND_PROBE_COMMIT,
                "payload_sha256": probe["integrity"]["payload_sha256"],
                "inherited_status": probe["observed_transport_contrast"][
                    "inherited_httpx_trust_env_true"
                ]["status"],
                "direct_status": probe["observed_transport_contrast"][
                    "explicit_httpx_trust_env_false"
                ]["status"],
                "no_proxy_statuses": [
                    row["status"] for row in probe["no_proxy_concurrent_openai_sdk"]["results"]
                ],
                "benchmark_prompt_read": False,
                "benchmark_answer_or_gold_read": False,
                "scores_opened": False,
            },
            "operational_remediation": {
                "environment": {
                    "NO_PROXY": "127.0.0.1,localhost",
                    "no_proxy": "127.0.0.1,localhost",
                    "OLLAMA_CONTEXT_LENGTH": "32768",
                    "OLLAMA_NUM_PARALLEL": "1",
                },
                "preflight": [
                    "Verify /api/tags exposes the exact preregistered model digest.",
                    "Warm the exact model with synthetic text through the direct loopback route.",
                    "Verify four concurrent synthetic OpenAI SDK requests return HTTP 200.",
                ],
                "scientific_effect": "transport_and_serving_reliability_only",
            },
            "frozen_invariants": {
                "candidate_source_sha": CANDIDATE_SOURCE_SHA,
                "fallback_harness_commit": HARNESS_COMMIT,
                "protocol_digest": marker["protocol_digest"],
                "official_repository_sha": marker["official_repository_sha"],
                "model": "mistral:7b",
                "evaluator_model": "mistral:7b",
                "model_digest": "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091",
                "context_window": 32768,
                "memory_context_max_tokens": 8192,
                "prompt_build_max_workers": 4,
                "reader_max_concurrent_requests": 4,
                "shuffle_questions_seed": 17,
                "prompts_unchanged": True,
                "models_unchanged": True,
                "thresholds_unchanged": True,
                "question_order_unchanged": True,
                "scoring_unchanged": True,
                "client_worker_count_unchanged": True,
            },
            "continuation_execution": {
                "same_output_root_required": "benchmarks/scientific_longmemeval_v31_final",
                "same_marker_required": _record(MARKER),
                "logical_full_run_count_must_remain": 1,
                "retained_partials_before_continuation": retained,
                "retained_partial_count_before_continuation": len(retained),
                "current_partial_must_be_retained_on_restart": True,
                "restart_first_incomplete_arm": "candidate_web_small",
                "fallback_harness_commit_required": HARNESS_COMMIT,
                "fresh_scientific_run_forbidden": True,
                "memory_and_service_monitoring_required": True,
            },
            "claim_boundary": (
                "This continuation plan and synthetic probe are not benchmark outcomes "
                "and authorize no pass, 100%-pass, SOTA, or revolutionary claim."
            ),
        }
    )
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
