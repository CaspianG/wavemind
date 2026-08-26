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
FALLBACK_HARNESS_COMMIT = "0dd456e1100a6beb5e60bdf94ddf5ffa071b2965"
WRAPPER = ROOT / "benchmarks" / "scientific_longmemeval_v2_backend_v31.py"
RUN_ROOT = ROOT / "benchmarks" / "scientific_longmemeval_v31_final"
BASE_DB = RUN_ROOT / "candidate-scratch" / "wavemind-lme-v6-d98_k2l4" / "candidate.sqlite3"
QUESTIONS = RUN_ROOT / "runtime_inputs" / "questions_web.json"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_fallback_probe_results.json"


def _private_gib() -> float:
    info = psutil.Process().memory_info()
    return round(getattr(info, "private", info.vms) / (1024**3), 6)


def main() -> int:
    committed_wrapper = subprocess.check_output(
        ["git", "show", f"{FALLBACK_HARNESS_COMMIT}:benchmarks/scientific_longmemeval_v2_backend_v31.py"],
        cwd=ROOT,
    )
    if hashlib.sha256(committed_wrapper).hexdigest() != file_sha256(WRAPPER):
        raise RuntimeError("fallback probe wrapper does not match exact fix commit")
    spec = importlib.util.spec_from_file_location("v31_fallback_probe_wrapper", WRAPPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load v31 fallback wrapper")
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    wrapper.register_backend(official_repository=OFFICIAL, candidate_repository=CANDIDATE)
    from evaluation import harness

    questions = harness.load_questions(str(QUESTIONS))
    random.Random(17).shuffle(questions)
    selected_questions = questions[:4]
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
    reconciler._select_ranked_memories = types.MethodType(
        wrapper._memory_safe_select_ranked_memories,
        reconciler,
    )
    rows = []
    try:
        for position, question in enumerate(selected_questions):
            question_text, question_image = harness.get_question_components(question["question"])
            started = time.perf_counter()
            recall = runtime.evaluation_recall(
                question_text,
                context={},
                moment=0.0,
                token_budget=8192,
                latency_budget_ms=1000.0,
                max_safety_risk=0.0,
            )
            rows.append(
                {
                    "shuffled_position": position,
                    "question_sha256": hashlib.sha256(question_text.encode("utf-8")).hexdigest(),
                    "question_chars": len(question_text),
                    "question_has_image": question_image is not None,
                    "recall_seconds": round(time.perf_counter() - started, 6),
                    "selected_count": len(recall.selected_memory_ids),
                    "estimated_tokens": recall.estimated_tokens,
                    "reason": recall.reason,
                    "context_sha256": hashlib.sha256(
                        json.dumps(
                            list(recall.contents),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest(),
                }
            )
        chain_started = time.perf_counter()
        chain_errors = list(runtime.event_log.validate_chain())
        chain_seconds = time.perf_counter() - chain_started
        private_gib = _private_gib()
    finally:
        runtime.close()
    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_fallback_probe.v1",
            "status": "passed_first_batch_digest_only_fallback_probe",
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "fallback_harness_commit": FALLBACK_HARNESS_COMMIT,
            "input": {
                "question_kind": "held_out_digest_only_infrastructure_probe",
                "shuffle_seed": 17,
                "question_count": 4,
                "answer_or_gold_read_by_probe": False,
            },
            "measurements": {
                "runtime_open_seconds": round(runtime_open_seconds, 6),
                "rows": rows,
                "maximum_recall_seconds": max(row["recall_seconds"] for row in rows),
                "total_recall_seconds": round(sum(row["recall_seconds"] for row in rows), 6),
                "chain_validation_seconds": round(chain_seconds, 6),
                "chain_errors": chain_errors,
                "private_gib_after_probe": private_gib,
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
                "The exact fallback fix passes only if all first-batch digest-only recalls "
                "complete within 30 seconds each, chain validation has no errors, and "
                "private memory remains below 3 GiB without model calls or scores."
            ),
            "claim_boundary": (
                "This digest-only infrastructure probe is not a benchmark outcome and "
                "authorizes no scientific pass or revolutionary claim."
            ),
        }
    )
    measurements = payload["measurements"]
    if measurements["maximum_recall_seconds"] >= 30.0:
        raise RuntimeError("fallback probe exceeded the per-query time limit")
    if measurements["chain_errors"]:
        raise RuntimeError("fallback probe chain validation failed")
    if measurements["private_gib_after_probe"] >= 3.0:
        raise RuntimeError("fallback probe exceeded 3 GiB private memory")
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
