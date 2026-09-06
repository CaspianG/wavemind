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
PREVIOUS_HARNESS_COMMIT = "303d06138fd205a36ea15473c13d0aa71fe4b150"
RESOURCE_SAFE_HARNESS_COMMIT = "627f7b054229f1f33f04fe35464b4fd77add65ee"
OOM_FAILURE_COMMIT = "d3eb4ec93c0910a5c016726d99b8a12135ddb459"
DEPENDENCY_PLAN_COMMIT = "0b1fe80a97e3e0fa3708b21e805b5bccb6ab5d36"
OOM_FAILURE = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_3.json"
DEPENDENCY_PLAN = (
    ROOT / "benchmarks" / "scientific_v31_longmem_dependency_continuation_plan.json"
)
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_resource_continuation_plan.json"
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
    failure = json.loads(OOM_FAILURE.read_text(encoding="utf-8"))
    dependency_plan = json.loads(DEPENDENCY_PLAN.read_text(encoding="utf-8"))
    for label, payload in (("OOM failure", failure), ("dependency plan", dependency_plan)):
        errors = validate_artifact_integrity(payload)
        if errors:
            raise RuntimeError(f"invalid {label} integrity: {errors}")
    if failure["observed_state"]["outcome_scores_opened"] is not False:
        raise RuntimeError("LongMem outcomes were opened before resource plan")

    before = {
        path: _commit_record(PREVIOUS_HARNESS_COMMIT, path) for path in HARNESSES
    }
    after = {
        path: _commit_record(RESOURCE_SAFE_HARNESS_COMMIT, path) for path in HARNESSES
    }
    changed = [
        path for path in HARNESSES if before[path]["sha256"] != after[path]["sha256"]
    ]
    if changed != [CHANGED_HARNESS]:
        raise RuntimeError(f"unexpected frozen-harness changes: {changed}")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_resource_continuation.v1",
            "status": "preregistered_resource_continuation_before_outcome",
            "preregistered_at": "2026-08-26",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": 1,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "oom_failure": {
                **_record(OOM_FAILURE),
                "commit": OOM_FAILURE_COMMIT,
                "payload_sha256": failure["integrity"]["payload_sha256"],
                "outcome_scores_opened": False,
                "scientific_gate_evaluated": False,
            },
            "dependency_plan": {
                **_record(DEPENDENCY_PLAN),
                "commit": DEPENDENCY_PLAN_COMMIT,
                "payload_sha256": dependency_plan["integrity"]["payload_sha256"],
            },
            "harness_change": {
                "previous_commit": PREVIOUS_HARNESS_COMMIT,
                "resource_safe_commit": RESOURCE_SAFE_HARNESS_COMMIT,
                "changed_frozen_harness_files": changed,
                "changed_file_count": len(changed),
                "previous_file": before[CHANGED_HARNESS],
                "resource_safe_file": after[CHANGED_HARNESS],
                "all_resource_safe_harness_files": [after[path] for path in HARNESSES],
            },
            "resource_safety_contract": {
                "official_prompt_build_max_workers": 4,
                "maximum_concurrent_shared_candidate_queries": 1,
                "query_results_unchanged": True,
                "query_order_semantics_unchanged": True,
                "candidate_compilation_unchanged": True,
                "candidate_retrieval_unchanged": True,
                "prompts_unchanged": True,
                "token_counts_unchanged": True,
                "reader_and_evaluator_models_unchanged": True,
                "scoring_unchanged": True,
                "per_worker_metadata_is_thread_local": True,
                "rationale": (
                    "The shared backend is a single mutable SQLite/runtime instance. "
                    "Serializing entry prevents four simultaneous high-memory recalls "
                    "and thread-local metadata prevents cross-question attribution."
                ),
            },
            "verification": {
                "concurrent_workers_exercised": 4,
                "maximum_observed_simultaneous_recall_in_test": 1,
                "four_distinct_context_digests_preserved": True,
                "scientific_suite_command": "python -m pytest -q tests/test_scientific*.py",
                "scientific_suite_passed": 223,
                "scientific_suite_failed": 0,
            },
            "semantic_invariants": dependency_plan["semantic_invariants"],
            "continuation_execution": {
                "same_output_root_required": "benchmarks/scientific_longmemeval_v31_final",
                "same_marker_required": True,
                "logical_full_run_count_must_remain": 1,
                "third_partial_must_be_retained": True,
                "restart_first_incomplete_arm": "candidate_web_small",
                "resource_safe_harness_commit_required": RESOURCE_SAFE_HARNESS_COMMIT,
                "candidate_source_sha_required": CANDIDATE_SOURCE_SHA,
                "fresh_scientific_run_forbidden": True,
            },
            "claim_boundary": (
                "This resource-continuation plan is not a benchmark outcome and "
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
