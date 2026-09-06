from __future__ import annotations

import hashlib
import importlib.metadata
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
ENVIRONMENT = ROOT.parents[1] / "scientific-env"
if str(CANDIDATE) in sys.path:
    sys.path.remove(str(CANDIDATE))
sys.path.insert(0, str(CANDIDATE))

from wavemind.evidence import attach_artifact_integrity, file_sha256
from wavemind.scientific_runtime import ScientificCandidateMode, ScientificMemoryRuntime


CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
STREAMING_HARNESS_COMMIT = "404c6b127e580d8531176d9e79cd1782bbacc79b"
WRAPPER = ROOT / "benchmarks" / "scientific_longmemeval_v2_backend_v31.py"
RUN_ROOT = ROOT / "benchmarks" / "scientific_longmemeval_v31_final"
BASE_DB = (
    RUN_ROOT
    / "candidate-scratch"
    / "wavemind-lme-v6-d98_k2l4"
    / "candidate.sqlite3"
)
QUESTIONS = RUN_ROOT / "runtime_inputs" / "questions_web.json"
DIST_INFO = ENVIRONMENT / "Lib" / "site-packages" / "torchvision-0.28.0.dist-info"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_processor_probe_results.json"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _environment_record(path: Path) -> dict[str, object]:
    return {
        "environment_relative_path": path.relative_to(ENVIRONMENT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _private_gib() -> float:
    info = psutil.Process().memory_info()
    return round(getattr(info, "private", info.vms) / (1024**3), 6)


def main() -> int:
    committed_wrapper = subprocess.check_output(
        ["git", "show", f"{STREAMING_HARNESS_COMMIT}:benchmarks/scientific_longmemeval_v2_backend_v31.py"],
        cwd=ROOT,
    )
    if hashlib.sha256(committed_wrapper).hexdigest() != file_sha256(WRAPPER):
        raise RuntimeError("processor probe wrapper does not match streaming commit")
    spec = importlib.util.spec_from_file_location("v31_processor_probe_wrapper", WRAPPER)
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
    import torchvision

    if importlib.metadata.version("torchvision") != "0.28.0":
        raise RuntimeError("resolved Torchvision version changed")
    questions = harness.load_questions(str(QUESTIONS))
    random.Random(17).shuffle(questions)
    question_text, question_image = harness.get_question_components(
        questions[0]["question"]
    )
    runtime_started = time.perf_counter()
    runtime = ScientificMemoryRuntime(
        BASE_DB,
        mode=ScientificCandidateMode.OPERATION_AWARE_TOMBSTONE_RECONCILER,
    )
    runtime_open_seconds = time.perf_counter() - runtime_started
    reconciler = runtime.state_reconciler
    reconciler._select_operation_memories = types.MethodType(
        wrapper._memory_safe_select_operation_memories,
        reconciler,
    )
    try:
        recall_started = time.perf_counter()
        recall = runtime.evaluation_recall(
            question_text,
            context={},
            moment=0.0,
            token_budget=8192,
            latency_budget_ms=1000.0,
            max_safety_risk=0.0,
        )
        recall_seconds = time.perf_counter() - recall_started
        memory_context = [
            {"type": "text", "value": value}
            for value in recall.contents
            if value.strip()
        ]
        chain_started = time.perf_counter()
        chain_errors = runtime.event_log.validate_chain()
        chain_seconds = time.perf_counter() - chain_started
        processor_started = time.perf_counter()
        truncated, original_tokens, truncated_tokens = harness.truncate_memory_context(
            memory_context,
            max_tokens=8192,
            question_id="digest-only-processor-probe",
        )
        processor_seconds = time.perf_counter() - processor_started
        private_gib = _private_gib()
    finally:
        runtime.close()
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_processor_probe.v1",
            "status": "passed_official_processor_dependency_probe",
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "streaming_harness_commit": STREAMING_HARNESS_COMMIT,
            "input": {
                "question_kind": "held_out_digest_only_infrastructure_probe",
                "question_sha256": hashlib.sha256(
                    question_text.encode("utf-8")
                ).hexdigest(),
                "question_chars": len(question_text),
                "question_has_image": question_image is not None,
                "answer_or_gold_read_by_probe": False,
            },
            "dependency_receipt": {
                "torch_version": str(torch.__version__),
                "torchvision_version": str(torchvision.__version__),
                "torch_cuda": torch.version.cuda,
                "distribution_files": [
                    _environment_record(DIST_INFO / name)
                    for name in ("METADATA", "WHEEL", "RECORD")
                ],
                "official_pyproject": {
                    "repository_relative_path": "pyproject.toml",
                    "bytes": (OFFICIAL / "pyproject.toml").stat().st_size,
                    "sha256": file_sha256(OFFICIAL / "pyproject.toml"),
                },
                "official_requirements_torch": {
                    "repository_relative_path": "requirements-torch.txt",
                    "bytes": (OFFICIAL / "requirements-torch.txt").stat().st_size,
                    "sha256": file_sha256(OFFICIAL / "requirements-torch.txt"),
                },
            },
            "measurements": {
                "runtime_open_seconds": round(runtime_open_seconds, 6),
                "optimized_recall_seconds": round(recall_seconds, 6),
                "chain_validation_seconds": round(chain_seconds, 6),
                "official_processor_seconds": round(processor_seconds, 6),
                "context_items": len(memory_context),
                "context_chars": sum(len(item["value"]) for item in memory_context),
                "context_estimated_tokens": recall.estimated_tokens,
                "processor_original_tokens": original_tokens,
                "processor_truncated_tokens": truncated_tokens,
                "processor_truncated_items": len(truncated),
                "chain_errors": list(chain_errors),
                "private_gib_after_processor": private_gib,
            },
            "scientific_boundary": {
                "question_text_emitted": False,
                "answer_or_gold_read": False,
                "model_calls_made": 0,
                "answers_generated": 0,
                "scores_opened": False,
                "gate_evaluated": False,
            },
            "decision_rule": (
                "Processor dependency probe passes only if exact recall, chain "
                "validation, and official truncation complete below 3 GiB private "
                "memory without reading answers or producing scores."
            ),
            "claim_boundary": (
                "This dependency probe is not a benchmark outcome and authorizes no "
                "scientific pass or revolutionary claim."
            ),
        }
    )
    measurements = payload["measurements"]
    if measurements["chain_errors"]:
        raise RuntimeError("processor probe chain validation failed")
    if measurements["private_gib_after_processor"] >= 3.0:
        raise RuntimeError("processor probe exceeded 3 GiB private memory")
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
