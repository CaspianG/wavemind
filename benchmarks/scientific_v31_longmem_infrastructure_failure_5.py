from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import subprocess
import sys
import time
import types
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT.parent / "wavemind-scientific-v31-official-exact"
OFFICIAL = ROOT.parents[1] / "scientific-evidence" / "upstreams" / "longmemeval-v2"
if str(CANDIDATE) in sys.path:
    sys.path.remove(str(CANDIDATE))
sys.path.insert(0, str(CANDIDATE))

from wavemind.evidence import attach_artifact_integrity, file_sha256
from wavemind.scientific_runtime import ScientificCandidateMode, ScientificMemoryRuntime


CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
STREAMING_HARNESS_COMMIT = "404c6b127e580d8531176d9e79cd1782bbacc79b"
STREAMING_PLAN_COMMIT = "878b650c9eb7aefb76b23aefaecf362676e57f50"
RUN_ROOT = ROOT / "benchmarks" / "scientific_longmemeval_v31_final"
MARKER = RUN_ROOT / "full_run_marker.json"
RUN_ARGS = RUN_ROOT / "candidate_web_small" / "run_args.json"
CONSOLE_LOG = RUN_ROOT / "continuation5_console.log"
WRAPPER = ROOT / "benchmarks" / "scientific_longmemeval_v2_backend_v31.py"
BASE_DB = (
    RUN_ROOT
    / "candidate-scratch"
    / "wavemind-lme-v6-d98_k2l4"
    / "candidate.sqlite3"
)
QUESTIONS = RUN_ROOT / "runtime_inputs" / "questions_web.json"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_5.json"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _external_record(path: Path) -> dict[str, object]:
    return {
        "repository_relative_path": path.relative_to(OFFICIAL).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _private_gib() -> float:
    info = psutil.Process().memory_info()
    return round(getattr(info, "private", info.vms) / (1024**3), 6)


def main() -> int:
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    run_args = json.loads(RUN_ARGS.read_text(encoding="utf-8"))
    if marker.get("logical_full_run_count") != 1 or marker.get("status") == "completed":
        raise RuntimeError("dependency abort is not in the incomplete logical run")
    if list(RUN_ROOT.rglob("per_question.jsonl")) or list(
        RUN_ROOT.rglob("aggregated_metrics.json")
    ):
        raise RuntimeError("outcome files exist before dependency failure freeze")
    committed_wrapper = subprocess.check_output(
        ["git", "show", f"{STREAMING_HARNESS_COMMIT}:benchmarks/scientific_longmemeval_v2_backend_v31.py"],
        cwd=ROOT,
    )
    if hashlib.sha256(committed_wrapper).hexdigest() != file_sha256(WRAPPER):
        raise RuntimeError("phase probe wrapper does not match streaming commit")

    spec = importlib.util.spec_from_file_location("v31_dependency_phase_wrapper", WRAPPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load v31 wrapper")
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    wrapper.register_backend(
        official_repository=OFFICIAL,
        candidate_repository=CANDIDATE,
    )
    from evaluation import harness
    import torch

    questions = harness.load_questions(str(QUESTIONS))
    random.Random(17).shuffle(questions)
    question_text, question_image = harness.get_question_components(
        questions[0]["question"]
    )
    measurements: dict[str, object] = {
        "question_sha256": hashlib.sha256(question_text.encode("utf-8")).hexdigest(),
        "question_chars": len(question_text),
        "question_has_image": question_image is not None,
    }
    started = time.perf_counter()
    runtime = ScientificMemoryRuntime(
        BASE_DB,
        mode=ScientificCandidateMode.OPERATION_AWARE_TOMBSTONE_RECONCILER,
    )
    measurements["runtime_open_seconds"] = round(time.perf_counter() - started, 6)
    reconciler = runtime.state_reconciler
    reconciler._select_operation_memories = types.MethodType(
        wrapper._memory_safe_select_operation_memories,
        reconciler,
    )
    try:
        started = time.perf_counter()
        recall = runtime.evaluation_recall(
            question_text,
            context={},
            moment=0.0,
            token_budget=8192,
            latency_budget_ms=1000.0,
            max_safety_risk=0.0,
        )
        measurements["optimized_recall_seconds"] = round(
            time.perf_counter() - started, 6
        )
        memory_context = [
            {"type": "text", "value": value}
            for value in recall.contents
            if value.strip()
        ]
        measurements["context_items"] = len(memory_context)
        measurements["context_chars"] = sum(
            len(item["value"]) for item in memory_context
        )
        measurements["context_estimated_tokens"] = recall.estimated_tokens
        started = time.perf_counter()
        chain_errors = runtime.event_log.validate_chain()
        measurements["chain_validation_seconds"] = round(
            time.perf_counter() - started, 6
        )
        measurements["chain_errors"] = list(chain_errors)
        started = time.perf_counter()
        try:
            harness.truncate_memory_context(
                memory_context,
                max_tokens=8192,
                question_id="digest-only-dependency-phase-probe",
            )
        except ImportError as exc:
            processor_error = {
                "type": type(exc).__name__,
                "message": str(exc).strip(),
                "seconds_until_error": round(time.perf_counter() - started, 6),
                "private_gib_after_error": _private_gib(),
            }
        else:
            raise RuntimeError("processor unexpectedly initialized without torchvision")
    finally:
        runtime.close()
    if "requires the Torchvision library" not in processor_error["message"]:
        raise RuntimeError("phase probe did not reproduce missing Torchvision")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_infrastructure_failure.v5",
            "status": "safety_aborted_before_outcomes",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": 1,
            "infrastructure_failure_sequence": 5,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "streaming_harness_commit": STREAMING_HARNESS_COMMIT,
            "streaming_continuation_plan_commit": STREAMING_PLAN_COMMIT,
            "failure": {
                "stage": "candidate_web_small_official_context_processor_initialization",
                "type": "MissingOfficialTorchvisionDependency",
                "processor_error": processor_error,
                "causal_diagnosis": (
                    "The exact streaming recall and chain validation complete below "
                    "one GiB in the isolated phase probe. The official Qwen3.5 "
                    "AutoProcessor then imports Qwen3VLVideoProcessor, which requires "
                    "Torchvision. Four prompt workers concurrently attempted this "
                    "missing initialization, creating the observed memory growth."
                ),
                "operator_interrupt_sent": True,
                "candidate_or_threshold_failure": False,
                "scientific_gate_evaluated": False,
            },
            "phase_probe": measurements,
            "full_run_resource_telemetry": {
                "samples": [
                    {"elapsed_minutes": 1.71, "private_gib": 3.542},
                    {"elapsed_minutes": 4.53, "private_gib": 5.622},
                    {"elapsed_minutes": 11.06, "private_gib": 9.721},
                ],
                "growth_plateau_observed": False,
                "aborted_to_prevent_repeated_system_oom": True,
            },
            "official_dependency_evidence": {
                "pyproject": _external_record(OFFICIAL / "pyproject.toml"),
                "requirements_torch": _external_record(
                    OFFICIAL / "requirements-torch.txt"
                ),
                "torchvision_declared": True,
                "official_historical_torch_pin": "2.6.0+cu124",
                "official_historical_torchvision_pin": "0.21.0+cu124",
                "installed_torch_version": str(torch.__version__),
                "installed_torchvision_at_failure": False,
                "dry_run_compatible_torchvision": "0.28.0",
                "dry_run_packages_to_install": 1,
                "dry_run_existing_torch_change": False,
            },
            "observed_state": {
                "completed_official_arms": [],
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
                "prompt_build_max_workers": run_args["prompt_build_max_workers"],
                "reader_max_concurrent_requests": run_args[
                    "reader_max_concurrent_requests"
                ],
                "shuffle_questions_seed": run_args["shuffle_questions_seed"],
            },
            "continuation_policy": {
                "same_logical_run_required": True,
                "partial_retained_verbatim_required": True,
                "candidate_unchanged_required": True,
                "harness_unchanged_required": True,
                "prompts_models_thresholds_workers_unchanged_required": True,
                "permitted_environment_change": (
                    "Install only torchvision 0.28.0, the resolver-compatible form "
                    "of the official declared dependency, without changing Torch."
                ),
                "attempts_count_as_scientific_runs": 1,
            },
            "claim_boundary": (
                "This dependency failure and phase probe contain no answer or score "
                "and authorize no scientific pass or revolutionary claim."
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
