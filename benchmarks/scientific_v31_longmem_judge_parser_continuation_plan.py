from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity, file_sha256, validate_artifact_integrity


CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
PREVIOUS_HARNESS_COMMIT = "0dd456e1100a6beb5e60bdf94ddf5ffa071b2965"
PARSER_HARNESS_COMMIT = "4f8959944e46d9d9cd5c3624e8e82e1f23491c53"
FAILURE_COMMIT = "b259bf3204b6078b4ee4354d1401ff998db0d385"
FAILURE = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_8.json"
MARKER = ROOT / "benchmarks" / "scientific_longmemeval_v31_final" / "full_run_marker.json"
RETAINED = ROOT / "benchmarks" / "scientific_longmemeval_v31_final" / "retained_partials"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_judge_parser_continuation_plan.json"
HARNESSES = (
    "benchmarks/scientific_mab_v19_final.py",
    "benchmarks/scientific_mab_v31_final.py",
    "benchmarks/scientific_memops_v31_final.py",
    "benchmarks/scientific_longmemeval_v2_backend.py",
    "benchmarks/scientific_longmemeval_v2_backend_v31.py",
    "benchmarks/scientific_longmemeval_v2_run.py",
    "benchmarks/scientific_longmemeval_v2_run_v31.py",
)
CHANGED_HARNESS = "benchmarks/scientific_longmemeval_v2_run.py"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _commit_record(commit: str, path: str) -> dict[str, object]:
    content = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)
    return {"path": path, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def main() -> int:
    failure = json.loads(FAILURE.read_text(encoding="utf-8"))
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    errors = validate_artifact_integrity(failure)
    if errors:
        raise RuntimeError(f"invalid failure integrity: {errors}")
    if failure["observed_state"]["outcome_scores_opened_by_operator"] is not False:
        raise RuntimeError("LongMem outcome was opened before parser continuation plan")
    before = {path: _commit_record(PREVIOUS_HARNESS_COMMIT, path) for path in HARNESSES}
    after = {path: _commit_record(PARSER_HARNESS_COMMIT, path) for path in HARNESSES}
    changed = [path for path in HARNESSES if before[path]["sha256"] != after[path]["sha256"]]
    if changed != [CHANGED_HARNESS]:
        raise RuntimeError(f"unexpected frozen-harness changes: {changed}")
    retained = sorted(path.name for path in RETAINED.iterdir() if path.is_dir())
    if len(retained) != 7:
        raise RuntimeError(f"expected seven retained pre-plan partials, found {len(retained)}")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_judge_parser_continuation.v1",
            "status": "preregistered_judge_parser_continuation_before_comparison_aggregate",
            "preregistered_at": "2026-08-27",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": marker["logical_full_run_count"],
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "failure_evidence": {
                **_record(FAILURE),
                "commit": FAILURE_COMMIT,
                "payload_sha256": failure["integrity"]["payload_sha256"],
                "failure_type": failure["failure"]["type"],
                "completed_candidate_arm_metric_opened": False,
                "failed_comparison_arm_aggregate_exists": False,
                "scientific_gate_evaluated": False,
            },
            "harness_change": {
                "previous_commit": PREVIOUS_HARNESS_COMMIT,
                "parser_commit": PARSER_HARNESS_COMMIT,
                "changed_frozen_harness_files": changed,
                "changed_file_count": len(changed),
                "previous_file": before[CHANGED_HARNESS],
                "parser_file": after[CHANGED_HARNESS],
                "all_parser_harness_files": [after[path] for path in HARNESSES],
            },
            "parser_equivalence_contract": {
                "existing_parser_always_attempted_first": True,
                "fallback_only_after_value_error": True,
                "fallback_full_match": "leading [01], comma, reason colon, non-empty reason",
                "returned_label_is_exact_leading_binary": True,
                "reason_does_not_change_binary_score": True,
                "canonical_json_result_unchanged_in_exact_official_parser_test": True,
                "ambiguous_unlabelled_invalid_label_empty_reason_text_still_raises": True,
                "focused_tests_passed": 14,
                "affected_tests_passed": 22,
            },
            "frozen_invariants": {
                "candidate_source_sha": CANDIDATE_SOURCE_SHA,
                "protocol_digest": marker["protocol_digest"],
                "official_repository_sha": marker["official_repository_sha"],
                "model": "mistral:7b",
                "evaluator_model": "mistral:7b",
                "model_digest": "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091",
                "context_window": 32768,
                "reader_max_concurrent_requests": 4,
                "shuffle_questions_seed": 17,
                "prompts_unchanged": True,
                "answers_unchanged": True,
                "models_unchanged": True,
                "thresholds_unchanged": True,
                "question_order_unchanged": True,
                "binary_scoring_rule_unchanged": True,
                "gate_unchanged": True,
            },
            "continuation_execution": {
                "same_output_root_required": "benchmarks/scientific_longmemeval_v31_final",
                "same_marker_required": _record(MARKER),
                "logical_full_run_count_must_remain": 1,
                "retained_partials_before_continuation": retained,
                "retained_partial_count_before_continuation": len(retained),
                "failed_no_retrieval_web_partial_must_be_retained_on_restart": True,
                "completed_candidate_web_arm_must_be_skipped": True,
                "restart_first_incomplete_arm": "no_retrieval_web_small",
                "parser_harness_commit_required": PARSER_HARNESS_COMMIT,
                "loopback_proxy_bypass_required": True,
                "fresh_scientific_run_forbidden": True,
            },
            "claim_boundary": (
                "This parser continuation plan is not a benchmark outcome and authorizes no "
                "pass, 100%-pass, SOTA, or revolutionary claim."
            ),
        }
    )
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
