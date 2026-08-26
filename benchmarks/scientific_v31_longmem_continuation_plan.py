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


ORIGINAL_PLAN_COMMIT = "8135561b4c532817bf9502556c099a5e52ebb19e"
FAILURE_EVIDENCE_COMMIT = "7dcdcb505cf22503d169f1ad55d2a89d4b241104"
ORIGINAL_HARNESS_COMMIT = "8d5052b94dea2cdc2db020208800577e3267ab3c"
FIXED_HARNESS_COMMIT = "303d06138fd205a36ea15473c13d0aa71fe4b150"
CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
PROTOCOL_DIGEST = "bc1f895bdf8bd30027bcc17f1c3a375099c8ee442681382c56ba57fa7580793b"
PLAN = ROOT / "benchmarks" / "scientific_v31_admission_plan.json"
FAILURE = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure.json"
MARKER = ROOT / "benchmarks" / "scientific_longmemeval_v31_final" / "full_run_marker.json"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_continuation_plan.json"
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


def _commit_bytes(commit: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)


def _commit_record(commit: str, path: str) -> dict[str, object]:
    content = _commit_bytes(commit, path)
    return {
        "path": path,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    failure = json.loads(FAILURE.read_text(encoding="utf-8"))
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    for label, payload in (("admission plan", plan), ("failure", failure)):
        errors = validate_artifact_integrity(payload)
        if errors:
            raise RuntimeError(f"invalid {label} integrity: {errors}")
    if failure["status"] != "infrastructure_failed_before_outcomes":
        raise RuntimeError("failure report is not a pre-outcome infrastructure failure")
    if failure["observed_state"]["outcome_scores_opened"] is not False:
        raise RuntimeError("LongMem outcomes were opened before continuation planning")
    if marker.get("logical_full_run_count") != 1 or marker.get("status") == "completed":
        raise RuntimeError("continuation is not inside the single incomplete logical run")

    original_records = {
        path: _commit_record(ORIGINAL_HARNESS_COMMIT, path) for path in HARNESSES
    }
    fixed_records = {
        path: _commit_record(FIXED_HARNESS_COMMIT, path) for path in HARNESSES
    }
    changed = [
        path
        for path in HARNESSES
        if original_records[path]["sha256"] != fixed_records[path]["sha256"]
    ]
    if changed != [CHANGED_HARNESS]:
        raise RuntimeError(f"unexpected frozen-harness changes: {changed}")

    run_args = failure["frozen_execution_parameters"]
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_continuation_plan.v1",
            "status": "preregistered_infrastructure_continuation_before_outcome",
            "preregistered_at": "2026-08-26",
            "logical_run": failure["logical_run"],
            "logical_full_run_count": 1,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "original_admission_plan": {
                **_record(PLAN),
                "commit": ORIGINAL_PLAN_COMMIT,
                "payload_sha256": plan["integrity"]["payload_sha256"],
            },
            "infrastructure_failure": {
                **_record(FAILURE),
                "commit": FAILURE_EVIDENCE_COMMIT,
                "payload_sha256": failure["integrity"]["payload_sha256"],
                "outcome_scores_opened": False,
                "scientific_gate_evaluated": False,
            },
            "harness_change": {
                "original_commit": ORIGINAL_HARNESS_COMMIT,
                "fixed_commit": FIXED_HARNESS_COMMIT,
                "changed_frozen_harness_files": changed,
                "changed_file_count": len(changed),
                "original_file": original_records[CHANGED_HARNESS],
                "fixed_file": fixed_records[CHANGED_HARNESS],
                "change_scope": (
                    "Add a per-instance lock and double-checked synchronization "
                    "around one-time compilation; candidate compilation, retrieval, "
                    "prompts, model calls, ordering, and scoring remain unchanged."
                ),
                "all_fixed_harness_files": [
                    fixed_records[path] for path in HARNESSES
                ],
            },
            "semantic_invariants": {
                "candidate_source_sha": CANDIDATE_SOURCE_SHA,
                "official_repository_sha": marker["official_repository_sha"],
                "dataset_files": marker["dataset_files"],
                "dataset_revision": plan["official_sources"]["longmemeval_v2"][
                    "dataset_revision"
                ],
                "tier": marker["tier"],
                "question_count": plan["frozen_samples"]["longmemeval_v2"][
                    "question_count"
                ],
                "arm_order": [
                    "candidate_web_small",
                    "no_retrieval_web_small",
                    "candidate_enterprise_small",
                    "no_retrieval_enterprise_small",
                ],
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
                "prompts_unchanged": True,
                "thresholds": plan["frozen_gates"]["longmemeval_v2"],
                "thresholds_unchanged": True,
            },
            "continuation_execution": {
                "same_output_root_required": (
                    "benchmarks/scientific_longmemeval_v31_final"
                ),
                "same_marker_required": True,
                "logical_full_run_count_must_remain": 1,
                "partial_must_be_moved_to_retained_partials": True,
                "restart_first_incomplete_arm": "candidate_web_small",
                "fresh_scientific_run_forbidden": True,
                "post_outcome_candidate_change_forbidden": True,
            },
            "decision_rule": (
                "Continuation may start only from the fixed exact harness commit and "
                "must preserve every semantic invariant above. It remains the first "
                "and only logical LongMemEval full run."
            ),
            "claim_boundary": (
                "This addendum is not a benchmark outcome and authorizes no pass, "
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
