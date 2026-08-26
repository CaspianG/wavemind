from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import time
import types
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT.parent / "wavemind-scientific-v31-official-exact"
if str(CANDIDATE) in sys.path:
    sys.path.remove(str(CANDIDATE))
sys.path.insert(0, str(CANDIDATE))

from wavemind.evidence import attach_artifact_integrity, file_sha256
from wavemind.scientific_runtime import (
    ScientificCandidateMode,
    ScientificMemoryRuntime,
)


CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
STREAMING_HARNESS_COMMIT = "404c6b127e580d8531176d9e79cd1782bbacc79b"
WRAPPER = ROOT / "benchmarks" / "scientific_longmemeval_v2_backend_v31.py"
SCRATCH_DIR = (
    ROOT
    / "benchmarks"
    / "scientific_longmemeval_v31_final"
    / "candidate-scratch"
    / "wavemind-lme-v6-d98_k2l4"
)
BASE_DB = SCRATCH_DIR / "candidate.sqlite3"
EVENT_DB = SCRATCH_DIR / "candidate.sqlite3.scientific-events.sqlite3"
EVENT_WAL = Path(str(EVENT_DB) + "-wal")
EVENT_SHM = Path(str(EVENT_DB) + "-shm")
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_streaming_probe_results.json"
SYNTHETIC_QUERY = "synthetic infrastructure memory probe"


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _memory() -> dict[str, float]:
    info = psutil.Process().memory_info()
    return {
        "rss_gib": round(info.rss / (1024**3), 6),
        "vms_gib": round(info.vms / (1024**3), 6),
        "private_gib": round(getattr(info, "private", info.vms) / (1024**3), 6),
    }


def _git_sha(path: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True
    ).strip()


def main() -> int:
    if _git_sha(CANDIDATE) != CANDIDATE_SOURCE_SHA:
        raise RuntimeError("synthetic probe candidate SHA changed")
    if subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=CANDIDATE, text=True
    ).strip():
        raise RuntimeError("synthetic probe candidate worktree is dirty")
    committed_wrapper = subprocess.check_output(
        ["git", "show", f"{STREAMING_HARNESS_COMMIT}:benchmarks/scientific_longmemeval_v2_backend_v31.py"],
        cwd=ROOT,
    )
    if hashlib.sha256(committed_wrapper).hexdigest() != file_sha256(WRAPPER):
        raise RuntimeError("streaming wrapper does not match its exact commit")

    spec = importlib.util.spec_from_file_location("v31_streaming_probe_wrapper", WRAPPER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load streaming wrapper")
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)

    started = time.perf_counter()
    runtime = ScientificMemoryRuntime(
        BASE_DB,
        mode=ScientificCandidateMode.OPERATION_AWARE_TOMBSTONE_RECONCILER,
    )
    after_open = time.perf_counter()
    reconciler = runtime.state_reconciler
    reconciler._select_operation_memories = types.MethodType(
        wrapper._memory_safe_select_operation_memories,
        reconciler,
    )
    try:
        recall_started = time.perf_counter()
        recall = runtime.evaluation_recall(
            SYNTHETIC_QUERY,
            context={},
            moment=0.0,
            token_budget=8192,
            latency_budget_ms=1000.0,
            max_safety_risk=0.0,
        )
        after_recall = time.perf_counter()
        chain_errors = runtime.event_log.validate_chain()
        after_chain = time.perf_counter()
        payload = attach_artifact_integrity(
            {
                "schema": "wavemind.scientific_v31_longmem_streaming_probe.v1",
                "status": "passed_synthetic_full_scratch_resource_probe",
                "query_kind": "synthetic_non_held_out",
                "query_sha256": hashlib.sha256(
                    SYNTHETIC_QUERY.encode("utf-8")
                ).hexdigest(),
                "candidate_source_sha": CANDIDATE_SOURCE_SHA,
                "streaming_harness_commit": STREAMING_HARNESS_COMMIT,
                "streaming_wrapper": _record(WRAPPER),
                "scratch": {
                    "base_database": _record(BASE_DB),
                    "event_database": _record(EVENT_DB),
                    "event_database_wal": _record(EVENT_WAL),
                    "event_database_shm": _record(EVENT_SHM),
                    "event_count": 28768,
                    "event_json_bytes": 97046543,
                },
                "measurements": {
                    "open_seconds": round(after_open - started, 6),
                    "recall_seconds": round(after_recall - recall_started, 6),
                    "chain_validation_seconds": round(
                        after_chain - after_recall, 6
                    ),
                    "selected_count": len(recall.selected_memory_ids),
                    "estimated_tokens": recall.estimated_tokens,
                    "chain_errors": list(chain_errors),
                    "process_memory_after_validation": _memory(),
                },
                "scientific_boundary": {
                    "held_out_question_text_used": False,
                    "model_calls_made": 0,
                    "answers_generated": 0,
                    "scores_opened": False,
                    "gate_evaluated": False,
                },
                "decision_rule": (
                    "The streaming implementation is resource-viable only if the "
                    "full scratch opens, synthetic recall completes, chain validation "
                    "has no errors, and private memory remains below 2 GiB."
                ),
                "claim_boundary": (
                    "A synthetic infrastructure probe is not a held-out benchmark "
                    "outcome and authorizes no scientific pass or revolutionary claim."
                ),
            }
        )
    finally:
        runtime.close()
    if payload["measurements"]["chain_errors"]:
        raise RuntimeError("synthetic full-scratch chain validation failed")
    if payload["measurements"]["process_memory_after_validation"]["private_gib"] >= 2.0:
        raise RuntimeError("streaming full-scratch probe exceeded 2 GiB private memory")
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
