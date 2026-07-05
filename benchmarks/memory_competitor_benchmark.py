from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind


@dataclass(frozen=True)
class MemoryFact:
    id: str
    text: str
    namespace: str = "agent-main"
    priority: float = 1.0
    ttl_seconds: float | None = None


@dataclass(frozen=True)
class QueryCheck:
    id: str
    query: str
    namespace: str
    expected_id: str | None
    forbidden_ids: tuple[str, ...] = ()


FACTS: tuple[MemoryFact, ...] = (
    MemoryFact("old_city", "The user's current city is Berlin.", priority=1.0),
    MemoryFact("new_city", "The user's current city is Lisbon.", priority=7.0),
    MemoryFact("old_role", "The user's current job is product manager.", priority=1.0),
    MemoryFact("new_role", "The user's current job is trader.", priority=7.0),
    MemoryFact("budget", "The user's monthly tools budget is 2000 dollars.", priority=5.0),
    MemoryFact("style", "The user prefers short practical answers.", priority=6.0),
    MemoryFact("expired_token", "The temporary login token blue-114 is valid.", ttl_seconds=0),
    MemoryFact("active_token", "The temporary login token green-772 is valid.", priority=4.0),
    MemoryFact("other_budget", "The user's monthly tools budget is 50 dollars.", namespace="agent-other", priority=5.0),
)

CHECKS: tuple[QueryCheck, ...] = (
    QueryCheck("city", "What is the user's current city?", "agent-main", "new_city", ("old_city",)),
    QueryCheck("role", "What is the user's current job?", "agent-main", "new_role", ("old_role",)),
    QueryCheck("budget", "What is the user's budget?", "agent-main", "budget", ("other_budget",)),
    QueryCheck("style", "How should the assistant answer?", "agent-main", "style"),
    QueryCheck("token", "Which temporary login token is valid now?", "agent-main", "active_token", ("expired_token",)),
    QueryCheck("expired_absent", "Is blue-114 still valid?", "agent-main", None, ("expired_token",)),
)


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _compute_metrics(engine: str, rankings: dict[str, list[str]], latencies_ms: list[float]) -> dict[str, Any]:
    expected_checks = [check for check in CHECKS if check.expected_id is not None]
    suppression_checks = [check for check in CHECKS if check.forbidden_ids]
    hit1 = 0
    hit3 = 0
    suppressed = 0
    for check in CHECKS:
        ranked = rankings.get(check.id, [])
        if check.expected_id is not None:
            if ranked[:1] == [check.expected_id]:
                hit1 += 1
            if check.expected_id in ranked[:3]:
                hit3 += 1
        if check.forbidden_ids and not set(check.forbidden_ids).intersection(ranked[:3]):
            suppressed += 1
    ordered = sorted(latencies_ms)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] if ordered else 0.0
    return {
        "engine": engine,
        "precision_at_1": hit1 / len(expected_checks),
        "precision_at_3": hit3 / len(expected_checks),
        "stale_suppression": suppressed / len(suppression_checks),
        "avg_latency_ms": statistics.mean(latencies_ms) if latencies_ms else 0.0,
        "p95_latency_ms": p95,
        "checks": len(CHECKS),
    }


def run_wavemind(top_k: int = 3) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        memory = WaveMind(
            db_path=Path(tmp) / "competitor-memory.sqlite3",
            index_kind="numpy",
            score_threshold=0.0,
            field_weight=0.06,
            priority_weight=0.35,
            lexical_weight=0.20,
            short_query_lexical_weight=1.5,
            rerank_k=30,
        )
        try:
            stored: dict[str, int] = {}
            for fact in FACTS:
                stored[fact.id] = memory.remember(
                    fact.text,
                    namespace=fact.namespace,
                    priority=fact.priority,
                    ttl_seconds=fact.ttl_seconds,
                    metadata={"benchmark_id": fact.id},
                    tags=("profile",),
                )
            memory.forget(id=stored["old_city"])
            memory.forget(id=stored["old_role"])

            rankings: dict[str, list[str]] = {}
            latencies: list[float] = []
            for check in CHECKS:
                started = time.perf_counter()
                results = memory.query(check.query, namespace=check.namespace, top_k=top_k)
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[check.id] = [
                    str(result.metadata.get("benchmark_id", ""))
                    for result in results
                ]
        finally:
            memory.store.close()
    return _compute_metrics("WaveMind", rankings, latencies)


def skipped_result(engine: str, reason: str) -> dict[str, Any]:
    return {
        "engine": engine,
        "skipped": True,
        "reason": reason,
    }


def run_mem0() -> dict[str, Any]:
    if not (_module_available("mem0") or _module_available("mem0ai")):
        return skipped_result("Mem0", 'Install Mem0 to run this adapter profile: pip install "mem0ai"')
    return skipped_result(
        "Mem0",
        "Mem0 package detected, but this benchmark requires an explicit local/vector-store configuration to avoid network-backed defaults.",
    )


def run_zep() -> dict[str, Any]:
    if not (_module_available("zep_cloud") or _module_available("zep_python")):
        return skipped_result("Zep", "Install the Zep client package and set ZEP_API_KEY or ZEP_API_URL.")
    if not (os.environ.get("ZEP_API_KEY") or os.environ.get("ZEP_API_URL")):
        return skipped_result("Zep", "Set ZEP_API_KEY or ZEP_API_URL to run the Zep adapter profile.")
    return skipped_result(
        "Zep",
        "Zep credentials are present, but the benchmark does not create remote sessions unless --allow-network-services is passed.",
    )


def run_langgraph() -> dict[str, Any]:
    if not _module_available("langgraph"):
        return skipped_result(
            "LangGraph persistent memory",
            'Install LangGraph to run this adapter profile: pip install "langgraph"',
        )
    return skipped_result(
        "LangGraph persistent memory",
        "LangGraph package detected, but no persistent checkpointer/store DSN was provided.",
    )


def run_benchmark(engines: Iterable[str], top_k: int = 3) -> dict[str, Any]:
    runners = {
        "wavemind": lambda: run_wavemind(top_k=top_k),
        "mem0": run_mem0,
        "zep": run_zep,
        "langgraph": run_langgraph,
        "langgraph-persistent": run_langgraph,
    }
    results = []
    for engine in engines:
        key = engine.lower()
        if key not in runners:
            raise ValueError(f"Unknown engine: {engine}")
        results.append(runners[key]())
    return {
        "scenario": {
            "name": "memory_competitor_adapter_profile",
            "description": (
                "Small dynamic-memory adapter profile for comparing WaveMind against "
                "Mem0, Zep, and LangGraph persistent memory when those optional stacks "
                "are installed and explicitly configured. Missing competitors are "
                "reported as skipped instead of being approximated."
            ),
            "facts": len(FACTS),
            "checks": len(CHECKS),
            "top_k": top_k,
            "behaviors": ["correction", "ttl", "namespace", "preference"],
        },
        "results": results,
    }


def print_table(payload: dict[str, Any]) -> None:
    print("| engine | precision@1 | precision@3 | stale suppression | avg latency |")
    print("|---|---:|---:|---:|---:|")
    for result in payload["results"]:
        if result.get("skipped"):
            print(f"| {result['engine']} | skipped | - | - | - |")
            continue
        print(
            f"| {result['engine']} | "
            f"{result['precision_at_1']:.2f} | "
            f"{result['precision_at_3']:.2f} | "
            f"{result['stale_suppression']:.2f} | "
            f"{result['avg_latency_ms']:.2f} ms |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=["wavemind", "mem0", "zep", "langgraph", "langgraph-persistent"],
        default=["wavemind", "mem0", "zep", "langgraph"],
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/memory_competitor_results.json"))
    args = parser.parse_args()

    payload = run_benchmark(engines=args.engines, top_k=args.top_k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
