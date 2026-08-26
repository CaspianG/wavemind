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
STREAMING_HARNESS_COMMIT = "404c6b127e580d8531176d9e79cd1782bbacc79b"
FAILURE_COMMIT = "3ad6d255db7daf4812416a4c32f51c81403de815"
PROCESSOR_PROBE_COMMIT = "1a365fd1056dafb051d38aa6977b96428873b923"
FAILURE = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_5.json"
PROBE = ROOT / "benchmarks" / "scientific_v31_longmem_processor_probe_results.json"
MARKER = ROOT / "benchmarks" / "scientific_longmemeval_v31_final" / "full_run_marker.json"
RETAINED = ROOT / "benchmarks" / "scientific_longmemeval_v31_final" / "retained_partials"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_torchvision_continuation_plan.json"
HARNESSES = (
    "benchmarks/scientific_mab_v19_final.py",
    "benchmarks/scientific_mab_v31_final.py",
    "benchmarks/scientific_memops_v31_final.py",
    "benchmarks/scientific_longmemeval_v2_backend.py",
    "benchmarks/scientific_longmemeval_v2_backend_v31.py",
    "benchmarks/scientific_longmemeval_v2_run.py",
    "benchmarks/scientific_longmemeval_v2_run_v31.py",
)


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _commit_record(path: str) -> dict[str, object]:
    content = subprocess.check_output(
        ["git", "show", f"{STREAMING_HARNESS_COMMIT}:{path}"], cwd=ROOT
    )
    return {"path": path, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def main() -> int:
    failure = json.loads(FAILURE.read_text(encoding="utf-8"))
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    for label, payload in (("failure", failure), ("processor probe", probe)):
        errors = validate_artifact_integrity(payload)
        if errors:
            raise RuntimeError(f"invalid {label} integrity: {errors}")
    if failure["observed_state"]["outcome_scores_opened"] is not False:
        raise RuntimeError("LongMem outcomes were opened before dependency plan")
    if probe["status"] != "passed_official_processor_dependency_probe":
        raise RuntimeError("official processor dependency probe did not pass")
    if marker["logical_full_run_count"] != 1:
        raise RuntimeError("logical LongMem run count changed")
    retained = sorted(path.name for path in RETAINED.iterdir() if path.is_dir())
    if len(retained) != 4:
        raise RuntimeError(f"expected four retained pre-plan partials, found {len(retained)}")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_torchvision_continuation.v1",
            "status": "preregistered_torchvision_continuation_before_outcome",
            "preregistered_at": "2026-08-26",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": 1,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "failure_evidence": {
                **_record(FAILURE),
                "commit": FAILURE_COMMIT,
                "payload_sha256": failure["integrity"]["payload_sha256"],
                "failure_type": failure["failure"]["type"],
                "outcome_scores_opened": False,
                "scientific_gate_evaluated": False,
            },
            "processor_dependency_probe": {
                **_record(PROBE),
                "commit": PROCESSOR_PROBE_COMMIT,
                "payload_sha256": probe["integrity"]["payload_sha256"],
                "question_sha256": probe["input"]["question_sha256"],
                "answer_or_gold_read": False,
                "model_calls_made": 0,
                "scores_opened": False,
                "private_gib_after_processor": probe["measurements"]["private_gib_after_processor"],
                "processor_original_tokens": probe["measurements"]["processor_original_tokens"],
                "processor_truncated_tokens": probe["measurements"]["processor_truncated_tokens"],
            },
            "environment_change": {
                "permitted_change_only": "install resolver-compatible official dependency torchvision 0.28.0",
                "torch_before": "2.13.0+cpu",
                "torch_after": probe["dependency_receipt"]["torch_version"],
                "torch_unchanged": probe["dependency_receipt"]["torch_version"] == "2.13.0+cpu",
                "torchvision_before": None,
                "torchvision_after": probe["dependency_receipt"]["torchvision_version"],
                "cuda_after": probe["dependency_receipt"]["torch_cuda"],
                "distribution_files": probe["dependency_receipt"]["distribution_files"],
            },
            "exact_harness": {
                "required_commit": STREAMING_HARNESS_COMMIT,
                "files": [_commit_record(path) for path in HARNESSES],
                "harness_change_after_streaming_plan": False,
            },
            "frozen_invariants": {
                "candidate_source_sha": CANDIDATE_SOURCE_SHA,
                "protocol_digest": marker["protocol_digest"],
                "official_repository_sha": marker["official_repository_sha"],
                "tier": marker["tier"],
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
                "fresh_scientific_run_forbidden": True,
                "memory_monitoring_required": True,
                "safety_abort_before_system_oom_required": True,
            },
            "claim_boundary": (
                "This dependency continuation plan and processor probe are not benchmark "
                "outcomes and authorize no pass, 100%-pass, SOTA, or revolutionary claim."
            ),
        }
    )
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
