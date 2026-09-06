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
PREVIOUS_HARNESS_COMMIT = "404c6b127e580d8531176d9e79cd1782bbacc79b"
FALLBACK_HARNESS_COMMIT = "0dd456e1100a6beb5e60bdf94ddf5ffa071b2965"
FAILURE_COMMIT = "dfc065b51c928ac3ece4f56e3e2a965053e29d9f"
PROBE_COMMIT = "e11ebc8e737cd3156b82d89b93b243e65f21869a"
FAILURE = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_6.json"
PROBE = ROOT / "benchmarks" / "scientific_v31_longmem_fallback_probe_results.json"
MARKER = ROOT / "benchmarks" / "scientific_longmemeval_v31_final" / "full_run_marker.json"
RETAINED = ROOT / "benchmarks" / "scientific_longmemeval_v31_final" / "retained_partials"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_fallback_continuation_plan.json"
HARNESSES = (
    "benchmarks/scientific_mab_v19_final.py",
    "benchmarks/scientific_mab_v31_final.py",
    "benchmarks/scientific_memops_v31_final.py",
    "benchmarks/scientific_longmemeval_v2_backend.py",
    "benchmarks/scientific_longmemeval_v2_backend_v31.py",
    "benchmarks/scientific_longmemeval_v2_run.py",
    "benchmarks/scientific_longmemeval_v2_run_v31.py",
)
CHANGED_HARNESS = "benchmarks/scientific_longmemeval_v2_backend_v31.py"


def _record(path: Path) -> dict[str, object]:
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": file_sha256(path)}


def _commit_record(commit: str, path: str) -> dict[str, object]:
    content = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)
    return {"path": path, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def main() -> int:
    failure = json.loads(FAILURE.read_text(encoding="utf-8"))
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    for label, payload in (("failure", failure), ("fallback probe", probe)):
        errors = validate_artifact_integrity(payload)
        if errors:
            raise RuntimeError(f"invalid {label} integrity: {errors}")
    if failure["observed_state"]["outcome_scores_opened"] is not False:
        raise RuntimeError("LongMem outcomes were opened before fallback plan")
    if probe["status"] != "passed_first_batch_digest_only_fallback_probe":
        raise RuntimeError("fallback probe did not pass")
    before = {path: _commit_record(PREVIOUS_HARNESS_COMMIT, path) for path in HARNESSES}
    after = {path: _commit_record(FALLBACK_HARNESS_COMMIT, path) for path in HARNESSES}
    changed = [path for path in HARNESSES if before[path]["sha256"] != after[path]["sha256"]]
    if changed != [CHANGED_HARNESS]:
        raise RuntimeError(f"unexpected frozen-harness changes: {changed}")
    retained = sorted(path.name for path in RETAINED.iterdir() if path.is_dir())
    if len(retained) != 5:
        raise RuntimeError(f"expected five retained pre-plan partials, found {len(retained)}")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_fallback_continuation.v1",
            "status": "preregistered_fallback_streaming_continuation_before_outcome",
            "preregistered_at": "2026-08-26",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": marker["logical_full_run_count"],
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "failure_evidence": {
                **_record(FAILURE),
                "commit": FAILURE_COMMIT,
                "payload_sha256": failure["integrity"]["payload_sha256"],
                "failure_type": failure["failure"]["type"],
                "outcome_scores_opened": False,
                "scientific_gate_evaluated": False,
            },
            "fallback_probe": {
                **_record(PROBE),
                "commit": PROBE_COMMIT,
                "payload_sha256": probe["integrity"]["payload_sha256"],
                "question_kind": probe["input"]["question_kind"],
                "question_count": probe["input"]["question_count"],
                "answer_or_gold_read": False,
                "model_calls_made": 0,
                "scores_opened": False,
                "maximum_recall_seconds": probe["measurements"]["maximum_recall_seconds"],
                "private_gib": probe["measurements"]["private_gib_after_probe"],
                "chain_errors": probe["measurements"]["chain_errors"],
            },
            "harness_change": {
                "previous_commit": PREVIOUS_HARNESS_COMMIT,
                "fallback_commit": FALLBACK_HARNESS_COMMIT,
                "changed_frozen_harness_files": changed,
                "changed_file_count": len(changed),
                "previous_file": before[CHANGED_HARNESS],
                "fallback_file": after[CHANGED_HARNESS],
                "all_fallback_harness_files": [after[path] for path in HARNESSES],
            },
            "semantic_equivalence_contract": {
                "original_formula": "Materialize every document token set, then intersect each with query tokens.",
                "streaming_formula": "Tokenize one document at a time and retain only its query-token intersection.",
                "query_token_intersections_identical": True,
                "document_frequency_identical": True,
                "query_weights_identical": True,
                "phrase_hits_identical": True,
                "recency_scores_identical": True,
                "ranking_tuples_identical": True,
                "budget_fit_identical": True,
                "selection_relevance_reason_exactly_equal_in_tests": True,
                "configurations_tested": 4,
                "definitions_in_equivalence_test": 600,
                "original_simultaneous_document_token_sets_minimum": 101,
                "streaming_simultaneous_document_token_sets_maximum": 2,
            },
            "frozen_invariants": {
                "candidate_source_sha": CANDIDATE_SOURCE_SHA,
                "protocol_digest": marker["protocol_digest"],
                "official_repository_sha": marker["official_repository_sha"],
                "model": "mistral:7b",
                "evaluator_model": "mistral:7b",
                "prompt_build_max_workers": 4,
                "reader_max_concurrent_requests": 4,
                "shuffle_questions_seed": 17,
                "prompts_unchanged": True,
                "models_unchanged": True,
                "thresholds_unchanged": True,
                "question_order_unchanged": True,
                "scoring_unchanged": True,
            },
            "continuation_execution": {
                "same_output_root_required": "benchmarks/scientific_longmemeval_v31_final",
                "same_marker_required": _record(MARKER),
                "logical_full_run_count_must_remain": 1,
                "retained_partials_before_continuation": retained,
                "retained_partial_count_before_continuation": len(retained),
                "current_partial_must_be_retained_on_restart": True,
                "restart_first_incomplete_arm": "candidate_web_small",
                "fallback_harness_commit_required": FALLBACK_HARNESS_COMMIT,
                "fresh_scientific_run_forbidden": True,
                "memory_monitoring_required": True,
            },
            "claim_boundary": (
                "This continuation plan and digest-only probe are not benchmark outcomes "
                "and authorize no pass, 100%-pass, SOTA, or revolutionary claim."
            ),
        }
    )
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
