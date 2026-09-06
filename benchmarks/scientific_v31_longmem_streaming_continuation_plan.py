from __future__ import annotations

import hashlib
import json
import subprocess
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


CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
PREVIOUS_HARNESS_COMMIT = "627f7b054229f1f33f04fe35464b4fd77add65ee"
STREAMING_HARNESS_COMMIT = "404c6b127e580d8531176d9e79cd1782bbacc79b"
SAFETY_ABORT_COMMIT = "06aec6f0722b44c78be9f41e691a459629e0f60a"
STREAMING_PROBE_COMMIT = "e291423f6b78197b941cd9ea14e09c6ceb619c08"
SAFETY_ABORT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_4.json"
STREAMING_PROBE = ROOT / "benchmarks" / "scientific_v31_longmem_streaming_probe_results.json"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_streaming_continuation_plan.json"
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
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _commit_record(commit: str, path: str) -> dict[str, object]:
    content = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)
    return {
        "path": path,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def main() -> int:
    failure = json.loads(SAFETY_ABORT.read_text(encoding="utf-8"))
    probe = json.loads(STREAMING_PROBE.read_text(encoding="utf-8"))
    for label, payload in (("safety abort", failure), ("streaming probe", probe)):
        errors = validate_artifact_integrity(payload)
        if errors:
            raise RuntimeError(f"invalid {label} integrity: {errors}")
    if failure["observed_state"]["outcome_scores_opened"] is not False:
        raise RuntimeError("LongMem outcomes were opened before streaming plan")
    if probe["status"] != "passed_synthetic_full_scratch_resource_probe":
        raise RuntimeError("full-scratch streaming probe did not pass")

    before = {
        path: _commit_record(PREVIOUS_HARNESS_COMMIT, path) for path in HARNESSES
    }
    after = {
        path: _commit_record(STREAMING_HARNESS_COMMIT, path) for path in HARNESSES
    }
    changed = [
        path for path in HARNESSES if before[path]["sha256"] != after[path]["sha256"]
    ]
    if changed != [CHANGED_HARNESS]:
        raise RuntimeError(f"unexpected frozen-harness changes: {changed}")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_streaming_continuation.v1",
            "status": "preregistered_streaming_continuation_before_outcome",
            "preregistered_at": "2026-08-26",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": 1,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "safety_abort": {
                **_record(SAFETY_ABORT),
                "commit": SAFETY_ABORT_COMMIT,
                "payload_sha256": failure["integrity"]["payload_sha256"],
                "outcome_scores_opened": False,
                "scientific_gate_evaluated": False,
            },
            "streaming_probe": {
                **_record(STREAMING_PROBE),
                "commit": STREAMING_PROBE_COMMIT,
                "payload_sha256": probe["integrity"]["payload_sha256"],
                "query_kind": probe["query_kind"],
                "model_calls_made": 0,
                "scores_opened": False,
                "private_gib": probe["measurements"][
                    "process_memory_after_validation"
                ]["private_gib"],
                "recall_seconds": probe["measurements"]["recall_seconds"],
                "chain_errors": probe["measurements"]["chain_errors"],
            },
            "harness_change": {
                "previous_commit": PREVIOUS_HARNESS_COMMIT,
                "streaming_commit": STREAMING_HARNESS_COMMIT,
                "changed_frozen_harness_files": changed,
                "changed_file_count": len(changed),
                "previous_file": before[CHANGED_HARNESS],
                "streaming_file": after[CHANGED_HARNESS],
                "all_streaming_harness_files": [after[path] for path in HARNESSES],
            },
            "semantic_equivalence_contract": {
                "original_formula": (
                    "Build a full token set per definition, then intersect each set "
                    "with query tokens."
                ),
                "streaming_formula": (
                    "Build one definition token set at a time and retain only its "
                    "intersection with query tokens."
                ),
                "query_token_intersections_identical": True,
                "document_frequency_identical": True,
                "lexical_weights_identical": True,
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
                "official_prompt_build_max_workers": 4,
                "reader_max_concurrent_requests": 4,
                "model": "mistral:7b",
                "evaluator_model": "mistral:7b",
                "shuffle_questions_seed": 17,
                "prompts_unchanged": True,
                "token_counts_unchanged": True,
                "models_unchanged": True,
                "thresholds_unchanged": True,
                "question_order_unchanged": True,
                "scoring_unchanged": True,
            },
            "continuation_execution": {
                "same_output_root_required": "benchmarks/scientific_longmemeval_v31_final",
                "same_marker_required": True,
                "logical_full_run_count_must_remain": 1,
                "controlled_abort_partial_must_be_retained": True,
                "restart_first_incomplete_arm": "candidate_web_small",
                "streaming_harness_commit_required": STREAMING_HARNESS_COMMIT,
                "fresh_scientific_run_forbidden": True,
            },
            "claim_boundary": (
                "This plan and synthetic probe are not benchmark outcomes and "
                "authorize no pass, 100%-pass, SOTA, or revolutionary claim."
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
