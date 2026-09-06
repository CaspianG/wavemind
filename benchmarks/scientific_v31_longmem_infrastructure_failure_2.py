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
FIXED_HARNESS_COMMIT = "303d06138fd205a36ea15473c13d0aa71fe4b150"
CONTINUATION_PLAN_COMMIT = "30ceb43dfb241843c67960cb9ff5f172018ca6f2"
RUN_ROOT = ROOT / "benchmarks" / "scientific_longmemeval_v31_final"
MARKER = RUN_ROOT / "full_run_marker.json"
RUN_ARGS = RUN_ROOT / "candidate_web_small" / "run_args.json"
CONSOLE_LOG = RUN_ROOT / "continuation_console.log"
OFFICIAL_ROOT = (
    ROOT.parents[1] / "scientific-evidence" / "upstreams" / "longmemeval-v2"
)
OFFICIAL_REQUIREMENTS = OFFICIAL_ROOT / "requirements.txt"
OFFICIAL_PYPROJECT = OFFICIAL_ROOT / "pyproject.toml"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_2.json"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _external_record(path: Path) -> dict[str, object]:
    return {
        "repository_relative_path": path.relative_to(OFFICIAL_ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def main() -> int:
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    run_args = json.loads(RUN_ARGS.read_text(encoding="utf-8"))
    per_question = sorted(RUN_ROOT.rglob("per_question.jsonl"))
    aggregated = sorted(RUN_ROOT.rglob("aggregated_metrics.json"))
    requirements_text = OFFICIAL_REQUIREMENTS.read_text(encoding="utf-8").lower()
    pyproject_text = OFFICIAL_PYPROJECT.read_text(encoding="utf-8").lower()
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
    if "pillow" not in requirements_text or '"pillow"' not in pyproject_text:
        raise RuntimeError("official LongMemEval repository does not declare Pillow")
    if "ModuleNotFoundError: No module named 'PIL'" not in CONSOLE_LOG.read_text(
        encoding="utf-8", errors="replace"
    ):
        raise RuntimeError("captured continuation log lacks the observed PIL failure")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_infrastructure_failure.v2",
            "status": "infrastructure_failed_before_outcomes",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": 1,
            "infrastructure_failure_sequence": 2,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "fixed_harness_commit": FIXED_HARNESS_COMMIT,
            "continuation_plan_commit": CONTINUATION_PLAN_COMMIT,
            "failure": {
                "stage": "candidate_web_small_prompt_truncation_image_loader",
                "type": "RuntimeError",
                "outer_message": "Prompt building failed for question e83245c5",
                "cause_type": "ModuleNotFoundError",
                "cause_message": "No module named 'PIL'",
                "causal_diagnosis": (
                    "The synchronization fix completed one-time compilation and "
                    "returned memory context. The official harness then imported its "
                    "declared Pillow dependency while truncating that context, but "
                    "Pillow was absent from the scientific environment."
                ),
                "candidate_or_threshold_failure": False,
                "scientific_gate_evaluated": False,
            },
            "observed_state": {
                "completed_official_arms": [],
                "partial_arm": "candidate_web_small",
                "one_time_compilation_completed": True,
                "answers_generated": False,
                "outcome_scores_opened": False,
                "per_question_files": 0,
                "aggregated_metrics_files": 0,
                "marker_completed": False,
                "marker": _record(MARKER),
                "run_args": _record(RUN_ARGS),
                "console_log": _record(CONSOLE_LOG),
            },
            "official_dependency_evidence": {
                "repository_sha": "2cc8c540bdb87fe6761629b585e727e1c4704520",
                "requirements": _external_record(OFFICIAL_REQUIREMENTS),
                "pyproject": _external_record(OFFICIAL_PYPROJECT),
                "dependency_name": "pillow",
                "declared_by_official_repository": True,
                "module_import_name": "PIL",
                "module_available_at_failure": False,
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
            },
            "continuation_policy": {
                "same_logical_run_required": True,
                "partial_retained_verbatim_required": True,
                "candidate_unchanged_required": True,
                "data_unchanged_required": True,
                "harness_unchanged_required": True,
                "prompts_unchanged_required": True,
                "model_unchanged_required": True,
                "thresholds_unchanged_required": True,
                "order_unchanged_required": True,
                "deterministic_parameters_unchanged_required": True,
                "permitted_environment_change": (
                    "Install only the official repository's declared Pillow runtime "
                    "dependency and record the resolved version before continuation."
                ),
                "attempts_count_as_scientific_runs": 1,
            },
            "claim_boundary": (
                "No LongMemEval outcome exists. This second infrastructure failure "
                "is neither a pass nor a scientific gate failure and authorizes no "
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
