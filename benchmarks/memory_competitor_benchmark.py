from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import logging
import os
import statistics
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind
from wavemind.encoders import HashingTextEncoder


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
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


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


def run_mem0(top_k: int = 3) -> dict[str, Any]:
    if not _module_available("mem0"):
        return skipped_result("Mem0", 'Install Mem0 to run this adapter profile: pip install "mem0ai"')
    if not _module_available("fastembed"):
        return skipped_result("Mem0", 'Install fastembed to run Mem0 locally: pip install "fastembed"')
    if not _module_available("qdrant_client"):
        return skipped_result("Mem0", 'Install qdrant-client to run Mem0 locally: pip install "qdrant-client"')

    os.environ.setdefault("MEM0_TELEMETRY", "False")
    logging.getLogger("mem0.utils.spacy_models").setLevel(logging.ERROR)

    from mem0 import Memory

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = {
            "llm": {
                "provider": "openai",
                "config": {"api_key": "dummy-not-used-for-infer-false"},
            },
            "embedder": {
                "provider": "fastembed",
                "config": {"model": "BAAI/bge-small-en-v1.5"},
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": str(root / "qdrant"),
                    "collection_name": "wavemind_mem0_competitor_profile",
                    "embedding_model_dims": 384,
                },
            },
            "history_db_path": str(root / "history.db"),
        }
        memory = Memory.from_config(config)
        stored: dict[str, str] = {}
        try:
            for fact in FACTS:
                expiration_date = None
                if fact.ttl_seconds == 0:
                    expiration_date = datetime.now(timezone.utc) - timedelta(seconds=1)
                response = memory.add(
                    fact.text,
                    user_id=fact.namespace,
                    metadata={"benchmark_id": fact.id},
                    expiration_date=expiration_date,
                    infer=False,
                )
                memory_id = _first_mem0_id(response)
                if memory_id:
                    stored[fact.id] = memory_id

            for stale_id in ("old_city", "old_role"):
                if stale_id in stored:
                    memory.delete(stored[stale_id])

            rankings: dict[str, list[str]] = {}
            latencies: list[float] = []
            for check in CHECKS:
                started = time.perf_counter()
                response = memory.search(
                    check.query,
                    filters={"user_id": check.namespace},
                    top_k=top_k,
                    threshold=0.0,
                    show_expired=False,
                )
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[check.id] = _mem0_benchmark_ids(response)
        finally:
            memory.close()
            del memory
            gc.collect()

    result = _compute_metrics("Mem0", rankings, latencies)
    result["configured"] = True
    result["backend"] = "local qdrant path + fastembed, infer=False"
    return result


def _first_mem0_id(response: Any) -> str | None:
    rows = response.get("results") if isinstance(response, dict) else response
    if not isinstance(rows, list) or not rows:
        return None
    value = rows[0].get("id") if isinstance(rows[0], dict) else None
    return str(value) if value else None


def _mem0_benchmark_ids(response: Any) -> list[str]:
    rows = response.get("results") if isinstance(response, dict) else response
    if not isinstance(rows, list):
        return []
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        metadata = row.get("metadata") or {}
        benchmark_id = metadata.get("benchmark_id")
        if benchmark_id:
            ids.append(str(benchmark_id))
    return ids


def run_zep(
    top_k: int = 3,
    client_factory: Callable[[], Any] | None = None,
    message_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    api_url = os.environ.get("ZEP_API_URL")
    api_key = os.environ.get("ZEP_API_KEY")
    if client_factory is None:
        if not (api_url or api_key):
            return skipped_result("Zep", "Set ZEP_API_URL or ZEP_API_KEY to run the Zep adapter profile.")
        timeout = float(os.environ.get("ZEP_TIMEOUT", "60"))
        if _module_available("zep_cloud"):
            try:
                from zep_cloud import Zep
                from zep_cloud import Message
            except Exception as exc:
                return skipped_result("Zep", f"Import zep-cloud failed: {exc}")
            client_factory = lambda: Zep(base_url=api_url, api_key=api_key, timeout=timeout)
            message_factory = Message
        elif _module_available("zep_python"):
            try:
                from zep_python.client import Zep
                from zep_python.types.message import Message
            except Exception as exc:
                return skipped_result("Zep", f"Import zep-python failed: {exc}")
            client_factory = lambda: Zep(base_url=api_url, api_key=api_key, timeout=timeout)
            message_factory = Message
        else:
            return skipped_result(
                "Zep",
                'Install a Zep SDK to run this adapter profile: pip install "zep-cloud" or pip install "zep-python"',
            )
    if message_factory is None:
        message_factory = lambda **kwargs: kwargs

    client = client_factory()
    if hasattr(client, "memory"):
        return _run_zep_memory_client(client, message_factory, top_k)
    if hasattr(client, "graph"):
        return _run_zep_graph_client(client, top_k)
    return skipped_result("Zep", "The configured Zep SDK client exposes neither .memory nor .graph.")


def _run_zep_memory_client(client: Any, message_factory: Callable[..., Any], top_k: int) -> dict[str, Any]:
    session_prefix = f"wavemind-benchmark-{uuid.uuid4().hex}"
    sessions = {
        namespace: f"{session_prefix}-{namespace}"
        for namespace in sorted({fact.namespace for fact in FACTS} | {check.namespace for check in CHECKS})
    }
    active_facts = [
        fact
        for fact in FACTS
        if fact.ttl_seconds != 0 and fact.id not in {"old_city", "old_role"}
    ]
    try:
        for namespace, session_id in sessions.items():
            client.memory.add_session(
                session_id=session_id,
                user_id=namespace,
                metadata={"benchmark": "wavemind-memory-competitor"},
            )
        for fact in active_facts:
            client.memory.add(
                sessions[fact.namespace],
                messages=[
                    message_factory(
                        role="user",
                        role_type="user",
                        content=fact.text,
                        metadata={
                            "benchmark_id": fact.id,
                            "namespace": fact.namespace,
                            "priority": fact.priority,
                        },
                    )
                ],
            )

        rankings: dict[str, list[str]] = {}
        latencies: list[float] = []
        for check in CHECKS:
            started = time.perf_counter()
            response = client.memory.search_sessions(
                session_ids=[sessions[check.namespace]],
                text=check.query,
                limit=top_k,
                search_scope="messages",
                search_type="similarity",
            )
            latencies.append((time.perf_counter() - started) * 1000.0)
            rankings[check.id] = _zep_benchmark_ids(response)
    except Exception as exc:
        return skipped_result("Zep", f"Zep live adapter failed: {type(exc).__name__}: {exc}")
    finally:
        for session_id in sessions.values():
            try:
                client.memory.delete(session_id)
            except Exception:
                pass
        close = getattr(client, "close", None)
        if callable(close):
            close()

    result = _compute_metrics("Zep", rankings, latencies)
    result["configured"] = True
    result["backend"] = "zep-python live service; benchmark session cleanup"
    return result


def _run_zep_graph_client(client: Any, top_k: int) -> dict[str, Any]:
    graph_prefix = f"wavemind-benchmark-{uuid.uuid4().hex}"
    graphs = {
        namespace: f"{graph_prefix}-{namespace}"
        for namespace in sorted({fact.namespace for fact in FACTS} | {check.namespace for check in CHECKS})
    }
    active_facts = [
        fact
        for fact in FACTS
        if fact.ttl_seconds != 0 and fact.id not in {"old_city", "old_role"}
    ]
    try:
        for namespace, graph_id in graphs.items():
            client.graph.create(
                graph_id=graph_id,
                name=f"WaveMind benchmark {namespace}",
                description="Temporary WaveMind competitor benchmark graph.",
            )
        for fact in active_facts:
            client.graph.add(
                graph_id=graphs[fact.namespace],
                data=fact.text,
                type="text",
                metadata={
                    "benchmark_id": fact.id,
                    "namespace": fact.namespace,
                    "priority": fact.priority,
                },
                source_description="WaveMind competitor benchmark fact",
            )

        rankings: dict[str, list[str]] = {}
        latencies: list[float] = []
        for check in CHECKS:
            started = time.perf_counter()
            response = client.graph.search(
                graph_id=graphs[check.namespace],
                query=check.query,
                limit=top_k,
                scope="episodes",
            )
            latencies.append((time.perf_counter() - started) * 1000.0)
            rankings[check.id] = _zep_benchmark_ids(response)
    except Exception as exc:
        return skipped_result("Zep", f"Zep live adapter failed: {type(exc).__name__}: {exc}")
    finally:
        for graph_id in graphs.values():
            try:
                client.graph.delete(graph_id)
            except Exception:
                pass
        close = getattr(client, "close", None)
        if callable(close):
            close()

    result = _compute_metrics("Zep", rankings, latencies)
    result["configured"] = True
    result["backend"] = "zep-cloud graph live service; benchmark graph cleanup"
    return result


def _zep_benchmark_ids(response: Any) -> list[str]:
    rows = []
    for field_name in ("results", "episodes", "edges", "nodes", "observations", "thread_summaries"):
        rows.extend(_value(response, field_name) or [])
    ids: list[str] = []
    for row in rows:
        message = _value(row, "message")
        summary = _value(row, "summary")
        fact = _value(row, "fact")
        for payload in (row, message, summary, fact):
            metadata = _value(payload, "metadata") or {}
            if isinstance(metadata, dict) and metadata.get("benchmark_id"):
                ids.append(str(metadata["benchmark_id"]))
                break
    return ids


def _value(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def run_langgraph(top_k: int = 3) -> dict[str, Any]:
    if not _module_available("langgraph.store.sqlite"):
        return skipped_result(
            "LangGraph persistent memory",
            'Install LangGraph SQLite store to run this adapter profile: pip install "langgraph" "langgraph-checkpoint-sqlite"',
        )

    from langgraph.store.sqlite import SqliteStore

    encoder = HashingTextEncoder(vector_dim=384)

    def embed(texts: str | list[str]) -> list[list[float]]:
        batch = [texts] if isinstance(texts, str) else list(texts)
        return [encoder.encode_vector(text).astype(float).tolist() for text in batch]

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "langgraph-store.sqlite"
        with SqliteStore.from_conn_string(
            str(db_path),
            index={"dims": 384, "embed": embed, "fields": ["text"]},
        ) as store:
            store.setup()
            for fact in FACTS:
                if fact.ttl_seconds == 0:
                    continue
                store.put(
                    (fact.namespace,),
                    fact.id,
                    {
                        "text": fact.text,
                        "benchmark_id": fact.id,
                        "priority": fact.priority,
                    },
                )
            store.delete(("agent-main",), "old_city")
            store.delete(("agent-main",), "old_role")

            rankings: dict[str, list[str]] = {}
            latencies: list[float] = []
            for check in CHECKS:
                started = time.perf_counter()
                results = store.search((check.namespace,), query=check.query, limit=top_k)
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[check.id] = [
                    str(item.value.get("benchmark_id", item.key))
                    for item in results
                ]

    result = _compute_metrics("LangGraph persistent memory", rankings, latencies)
    result["configured"] = True
    result["backend"] = "langgraph.store.sqlite.SqliteStore + local hash embeddings"
    return result


def run_benchmark(engines: Iterable[str], top_k: int = 3) -> dict[str, Any]:
    runners = {
        "wavemind": lambda: run_wavemind(top_k=top_k),
        "mem0": lambda: run_mem0(top_k=top_k),
        "zep": lambda: run_zep(top_k=top_k),
        "langgraph": lambda: run_langgraph(top_k=top_k),
        "langgraph-persistent": lambda: run_langgraph(top_k=top_k),
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
