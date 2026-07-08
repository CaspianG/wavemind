from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import tempfile
import time
from collections.abc import Iterable as IterableABC
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import HotMemoryCache, MemoryOSWorker, WaveMind, query_with_cache
from wavemind.encoders import create_text_encoder


@dataclass(frozen=True)
class AgentMemory:
    id: str
    text: str
    namespace: str = "agent-a"
    tags: tuple[str, ...] = ("profile",)
    ttl_seconds: float | None = None
    priority: float = 1.0


@dataclass(frozen=True)
class AgentTask:
    id: str
    prompt: str
    namespace: str
    expected_ids: tuple[str, ...]
    forbidden_ids: tuple[str, ...] = ()
    category: str = "general"


@dataclass(frozen=True)
class AgentCoherenceScenario:
    name: str
    memories: list[AgentMemory]
    tasks: list[AgentTask]


@dataclass(frozen=True)
class AgentCoherenceMetrics:
    engine: str
    task_success_rate: float
    decision_success_at_1: float
    stale_error_rate: float
    namespace_leak_rate: float
    coherent_turns: int
    coherent_turn_rate: float
    context_tokens_returned: int
    full_context_tokens: int
    context_budget_saved: float
    category_success: dict[str, float]
    avg_latency_ms: float
    p95_latency_ms: float
    tasks: int
    memory_os: dict[str, Any] | None = None


class CachedTextEncoder:
    def __init__(self, encoder, texts: Iterable[str]):
        self.encoder = encoder
        self.vector_dim = int(getattr(encoder, "vector_dim"))
        unique_texts = list(dict.fromkeys(str(text) for text in texts))
        self._cache: dict[str, np.ndarray] = {}
        if not unique_texts:
            return
        if hasattr(encoder, "encode_vectors"):
            vectors = encoder.encode_vectors(unique_texts)
            for text, vector in zip(unique_texts, vectors):
                self._cache[text] = np.asarray(vector, dtype=np.float32)
            return
        for text in unique_texts:
            self._cache[text] = np.asarray(encoder.encode_vector(text), dtype=np.float32)

    def encode_vector(self, text: str) -> np.ndarray:
        key = str(text)
        if key not in self._cache:
            self._cache[key] = np.asarray(self.encoder.encode_vector(key), dtype=np.float32)
        return self._cache[key]

    def encode_vectors(self, texts: IterableABC[str]) -> np.ndarray:
        vectors = [self.encode_vector(text) for text in texts]
        if not vectors:
            return np.zeros((0, self.vector_dim), dtype=np.float32)
        return np.stack(vectors).astype(np.float32)


CORE_MEMORIES: tuple[AgentMemory, ...] = (
    AgentMemory(
        "profile_name",
        "The user's name is Andrey.",
        tags=("profile",),
        priority=5.0,
    ),
    AgentMemory(
        "old_role",
        "The user's current role is product manager.",
        tags=("profile", "stale"),
        ttl_seconds=0,
        priority=0.5,
    ),
    AgentMemory(
        "new_role",
        "The user's current role is crypto trader.",
        tags=("profile",),
        priority=9.0,
    ),
    AgentMemory(
        "preference_verbose",
        "The user once wanted long exploratory answers with broad context.",
        tags=("preference", "stale"),
        ttl_seconds=0,
        priority=0.5,
    ),
    AgentMemory(
        "preference_short",
        "The user prefers short practical answers with direct next steps.",
        tags=("preference",),
        priority=9.0,
    ),
    AgentMemory(
        "old_city",
        "The user's current city is Berlin.",
        tags=("profile", "stale"),
        ttl_seconds=0,
        priority=0.5,
    ),
    AgentMemory(
        "new_city",
        "The user's current city is Lisbon.",
        tags=("profile",),
        priority=8.0,
    ),
    AgentMemory(
        "expired_token",
        "The valid temporary login token for this session is blue-114.",
        tags=("temporary", "token", "stale"),
        ttl_seconds=0,
        priority=0.5,
    ),
    AgentMemory(
        "active_token",
        "The valid temporary login token for this session is green-772.",
        tags=("temporary", "token"),
        priority=7.0,
    ),
    AgentMemory(
        "budget_agent_a",
        "The user's monthly tool budget is 2000 dollars.",
        namespace="agent-a",
        tags=("budget",),
        priority=7.0,
    ),
    AgentMemory(
        "budget_agent_b",
        "The user's monthly tool budget is 50 dollars.",
        namespace="agent-b",
        tags=("budget",),
        priority=7.0,
    ),
    AgentMemory(
        "old_project",
        "The old side project was Garden Notes.",
        tags=("project", "stale"),
        ttl_seconds=0,
        priority=0.5,
    ),
    AgentMemory(
        "current_project",
        "The important current project is WaveMind long-term memory.",
        tags=("project",),
        priority=8.0,
    ),
)


TASKS: tuple[AgentTask, ...] = (
    AgentTask("t01_name", "How should I address the user by name?", "agent-a", ("profile_name",), category="profile"),
    AgentTask("t02_role", "What is the user's current role now?", "agent-a", ("new_role",), ("old_role",), "correction"),
    AgentTask("t03_style", "Should the assistant be concise or exploratory?", "agent-a", ("preference_short",), ("preference_verbose",), "personalization"),
    AgentTask("t04_token", "Which temporary login token is still valid?", "agent-a", ("active_token",), ("expired_token",), "ttl"),
    AgentTask("t05_expired", "Can I still use blue-114 as the login token?", "agent-a", (), ("expired_token",), "ttl"),
    AgentTask("t06_city", "What city is the user currently in?", "agent-a", ("new_city",), ("old_city",), "correction"),
    AgentTask("t07_budget", "What is this user's monthly tool budget?", "agent-a", ("budget_agent_a",), ("budget_agent_b",), "namespace"),
    AgentTask("t08_project", "Which project matters right now?", "agent-a", ("current_project",), ("old_project",), "project"),
    AgentTask("t09_style_repeat", "For the next answer, use the user's preferred response style.", "agent-a", ("preference_short",), ("preference_verbose",), "personalization"),
    AgentTask("t10_role_repeat", "When personalizing a trading workflow, what role should I assume for the user?", "agent-a", ("new_role",), ("old_role",), "correction"),
    AgentTask("t11_budget_repeat", "Choose a paid tool tier using the user's budget.", "agent-a", ("budget_agent_a",), ("budget_agent_b",), "namespace"),
    AgentTask("t12_project_repeat", "Tie the next suggestion to the user's active project.", "agent-a", ("current_project",), ("old_project",), "project"),
)


FILLER_TOPICS: tuple[str, ...] = (
    "calendar planning",
    "market watchlists",
    "code editor setup",
    "database backup notes",
    "meeting summaries",
    "documentation drafts",
    "feature flags",
    "pricing research",
    "CLI experiments",
    "API smoke tests",
)


def estimate_tokens(text: str) -> int:
    words = [word for word in text.replace("\n", " ").split(" ") if word]
    return max(1, math.ceil(len(words) * 1.25))


def build_agent_coherence_scenario(memory_count: int = 500) -> AgentCoherenceScenario:
    if memory_count < len(CORE_MEMORIES):
        raise ValueError(f"memory_count must be at least {len(CORE_MEMORIES)}")
    memories = list(CORE_MEMORIES)
    for index in range(1, memory_count - len(CORE_MEMORIES) + 1):
        topic = FILLER_TOPICS[(index - 1) % len(FILLER_TOPICS)]
        namespace = "agent-a" if index % 5 else "agent-b"
        memories.append(
            AgentMemory(
                id=f"filler_{index:04d}",
                text=(
                    f"Long conversation filler memory {index} about {topic}. "
                    "It adds realistic history pressure but is not evidence for the agent task."
                ),
                namespace=namespace,
                tags=("filler", topic.replace(" ", "-")),
                priority=1.0,
            )
        )
    return AgentCoherenceScenario(
        name="agent_coherence",
        memories=memories,
        tasks=list(TASKS),
    )


def cache_encoder_for_scenario(scenario: AgentCoherenceScenario, encoder) -> CachedTextEncoder:
    texts = [memory.text for memory in scenario.memories]
    texts.extend(task.prompt for task in scenario.tasks)
    return CachedTextEncoder(encoder, texts)


def longest_true_run(values: Iterable[bool]) -> int:
    best = 0
    current = 0
    for value in values:
        if value:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def compute_agent_metrics(
    *,
    scenario: AgentCoherenceScenario,
    rankings: dict[str, list[str]],
    returned_texts: dict[str, list[str]],
    latencies_ms: list[float],
    top_k: int,
    engine: str,
    namespace_by_id: dict[str, str],
    memory_os: dict[str, Any] | None = None,
) -> AgentCoherenceMetrics:
    successes: list[bool] = []
    top1_successes: list[bool] = []
    stale_errors: list[bool] = []
    namespace_leaks: list[bool] = []
    category_values: dict[str, list[float]] = {}
    for task in scenario.tasks:
        ranked = rankings.get(task.id, [])[:top_k]
        expected = set(task.expected_ids)
        forbidden = set(task.forbidden_ids)
        has_expected = bool(expected.intersection(ranked)) if expected else True
        has_forbidden = bool(forbidden.intersection(ranked))
        success = has_expected and not has_forbidden
        top1_success = (
            bool(ranked[:1])
            and (not expected or ranked[0] in expected)
            and not has_forbidden
        )
        leak = any(namespace_by_id.get(item_id) not in {None, task.namespace} for item_id in ranked)
        successes.append(success)
        top1_successes.append(top1_success)
        if forbidden:
            stale_errors.append(has_forbidden)
        namespace_leaks.append(leak)
        category_values.setdefault(task.category, []).append(1.0 if success else 0.0)

    context_tokens = sum(
        estimate_tokens(text)
        for values in returned_texts.values()
        for text in values[:top_k]
    )
    full_context_tokens = sum(estimate_tokens(memory.text) for memory in scenario.memories)
    sorted_latencies = sorted(latencies_ms)
    p95_index = min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95)) if sorted_latencies else 0
    coherent_turns = longest_true_run(successes)
    return AgentCoherenceMetrics(
        engine=engine,
        task_success_rate=statistics.mean(successes) if successes else 0.0,
        decision_success_at_1=statistics.mean(top1_successes) if top1_successes else 0.0,
        stale_error_rate=statistics.mean(stale_errors) if stale_errors else 0.0,
        namespace_leak_rate=statistics.mean(namespace_leaks) if namespace_leaks else 0.0,
        coherent_turns=coherent_turns,
        coherent_turn_rate=coherent_turns / len(successes) if successes else 0.0,
        context_tokens_returned=context_tokens,
        full_context_tokens=full_context_tokens,
        context_budget_saved=max(0.0, 1.0 - context_tokens / full_context_tokens) if full_context_tokens else 0.0,
        category_success={
            category: statistics.mean(values)
            for category, values in sorted(category_values.items())
        },
        avg_latency_ms=statistics.mean(latencies_ms) if latencies_ms else 0.0,
        p95_latency_ms=sorted_latencies[p95_index] if sorted_latencies else 0.0,
        tasks=len(scenario.tasks),
        memory_os=memory_os,
    )


def _create_wavemind_for_agent_coherence(
    *,
    db_path: Path,
    encoder,
    top_k: int,
    audit_queries: bool = False,
) -> WaveMind:
    return WaveMind(
        db_path=db_path,
        encoder=encoder,
        index_kind="numpy",
        score_threshold=0.0,
        width=64,
        height=64,
        layers=3,
        evolve_on_feed=0,
        vector_weight=0.62,
        field_weight=0.04,
        priority_weight=0.28,
        lexical_weight=0.42,
        short_query_lexical_weight=1.8,
        rerank_k=max(40, top_k),
        persist_access_on_query=False,
        query_feedback_strength=0.0,
        audit_queries=audit_queries,
    )


def _load_scenario_into_wavemind(
    memory: WaveMind,
    scenario: AgentCoherenceScenario,
) -> dict[str, int]:
    ids_by_agent_id: dict[str, int] = {}
    for item in scenario.memories:
        ids_by_agent_id[item.id] = memory.remember(
            item.text,
            namespace=item.namespace,
            tags=item.tags,
            ttl_seconds=item.ttl_seconds,
            priority=item.priority,
            metadata={"agent_task_id": item.id},
        )
    return ids_by_agent_id


def run_wavemind(scenario: AgentCoherenceScenario, encoder, top_k: int) -> AgentCoherenceMetrics:
    with tempfile.TemporaryDirectory() as tmp:
        memory = _create_wavemind_for_agent_coherence(
            db_path=Path(tmp) / "agent-coherence.sqlite3",
            encoder=encoder,
            top_k=top_k,
        )
        try:
            _load_scenario_into_wavemind(memory, scenario)
            # Simulate repeated use before the final task sequence.
            for _ in range(4):
                memory.query("short practical answers with direct next steps", namespace="agent-a", top_k=1)
                memory.query("WaveMind long-term memory current project", namespace="agent-a", top_k=1)

            rankings: dict[str, list[str]] = {}
            returned_texts: dict[str, list[str]] = {}
            latencies: list[float] = []
            for task in scenario.tasks:
                started = time.perf_counter()
                results = memory.query(task.prompt, namespace=task.namespace, top_k=top_k)
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[task.id] = [str(result.metadata.get("agent_task_id", "")) for result in results]
                returned_texts[task.id] = [result.text for result in results]
        finally:
            memory.close()
    namespace_by_id = {memory.id: memory.namespace for memory in scenario.memories}
    return compute_agent_metrics(
        scenario=scenario,
        rankings=rankings,
        returned_texts=returned_texts,
        latencies_ms=latencies,
        top_k=top_k,
        engine="WaveMind",
        namespace_by_id=namespace_by_id,
    )


def run_wavemind_memory_os(
    scenario: AgentCoherenceScenario,
    encoder,
    top_k: int,
) -> AgentCoherenceMetrics:
    with tempfile.TemporaryDirectory() as tmp:
        memory = _create_wavemind_for_agent_coherence(
            db_path=Path(tmp) / "agent-coherence-memory-os.sqlite3",
            encoder=encoder,
            top_k=top_k,
            audit_queries=True,
        )
        cache = HotMemoryCache(capacity=64, ttl_seconds=120)
        try:
            _load_scenario_into_wavemind(memory, scenario)

            for _ in range(4):
                query_with_cache(
                    memory,
                    cache,
                    "short practical answers with direct next steps",
                    namespace="agent-a",
                    top_k=1,
                )
                query_with_cache(
                    memory,
                    cache,
                    "WaveMind long-term memory current project",
                    namespace="agent-a",
                    top_k=1,
                )
            memory.query("budget recall", namespace="agent-a", top_k=1)
            memory.query("risk limits", namespace="agent-a", top_k=1)
            memory.query("budget recall", namespace="agent-a", top_k=1)

            report = MemoryOSWorker(memory, cache).run_once(
                namespace="agent-a",
                audit_limit=64,
                max_hot_queries=16,
                min_frequency=2,
                top_k=top_k,
                consolidate_steps=0,
                consolidate_concepts=False,
                min_concept_energy=0.01,
                min_concept_size=2,
                max_concepts=2,
                memory_pressure_threshold=64,
                adaptive_forgetting=False,
                forgetting_min_age_seconds=0.0,
                forgetting_priority_decay=0.05,
                forgetting_max_access_count=0,
                target_memories=len(scenario.memories),
                namespace_count=2,
                target_qps=25.0,
                deployment="production",
            )

            rankings: dict[str, list[str]] = {}
            returned_texts: dict[str, list[str]] = {}
            latencies: list[float] = []
            for task in scenario.tasks:
                started = time.perf_counter()
                results = query_with_cache(
                    memory,
                    cache,
                    task.prompt,
                    namespace=task.namespace,
                    top_k=top_k,
                )
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[task.id] = [str(result.metadata.get("agent_task_id", "")) for result in results]
                returned_texts[task.id] = [result.text for result in results]

            cache_stats = cache.stats()
            report_dict = report.as_dict()
            memory_os = {
                "worker_ok": report.ok,
                "scanned_events": report.scanned_events,
                "hot_queries": len(report.hot_queries),
                "prewarm_warmed": report.prewarm.warmed,
                "predictive_prefetch_generated": report.predictive_prefetch.generated_queries,
                "predictive_prefetch_warmed": report.predictive_prefetch.warmed,
                "priority_predictions": report.priority_predictions,
                "priority_boosted": len(report.priority_boosted_ids),
                "forgetting_demotions": report.forgetting_demotions,
                "concepts_created": report.concepts_created,
                "cache_hits": cache_stats.hits,
                "cache_misses": cache_stats.misses,
                "cache_size": cache_stats.size,
                "cache_hit_rate": (
                    cache_stats.hits / (cache_stats.hits + cache_stats.misses)
                    if cache_stats.hits + cache_stats.misses
                    else 0.0
                ),
                "policy_status": report.policy_manifest.status,
                "suggestions": len(report.suggestions),
                "actions": list(report.actions),
                "recommendations": list(report.recommendations[:3]),
                "report": report_dict,
            }
        finally:
            memory.close()
    namespace_by_id = {memory.id: memory.namespace for memory in scenario.memories}
    return compute_agent_metrics(
        scenario=scenario,
        rankings=rankings,
        returned_texts=returned_texts,
        latencies_ms=latencies,
        top_k=top_k,
        engine="WaveMind + Memory OS",
        namespace_by_id=namespace_by_id,
        memory_os=memory_os,
    )


def run_static_vector(scenario: AgentCoherenceScenario, encoder, top_k: int) -> AgentCoherenceMetrics:
    vectors = encoder.encode_vectors(memory.text for memory in scenario.memories)
    vector_by_id = {
        memory.id: np.asarray(vector, dtype=np.float32)
        for memory, vector in zip(scenario.memories, vectors)
    }
    text_by_id = {memory.id: memory.text for memory in scenario.memories}
    namespace_by_id = {memory.id: memory.namespace for memory in scenario.memories}
    ids_by_namespace: dict[str, list[str]] = {}
    for memory in scenario.memories:
        ids_by_namespace.setdefault(memory.namespace, []).append(memory.id)

    rankings: dict[str, list[str]] = {}
    returned_texts: dict[str, list[str]] = {}
    latencies: list[float] = []
    query_vectors = encoder.encode_vectors(task.prompt for task in scenario.tasks)
    for task, query_vector in zip(scenario.tasks, query_vectors):
        started = time.perf_counter()
        scored = [
            (memory_id, float(np.dot(query_vector, vector_by_id[memory_id])))
            for memory_id in ids_by_namespace.get(task.namespace, [])
        ]
        scored.sort(key=lambda row: row[1], reverse=True)
        selected = [memory_id for memory_id, _ in scored[:top_k]]
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[task.id] = selected
        returned_texts[task.id] = [text_by_id[memory_id] for memory_id in selected]
    return compute_agent_metrics(
        scenario=scenario,
        rankings=rankings,
        returned_texts=returned_texts,
        latencies_ms=latencies,
        top_k=top_k,
        engine="Static vector",
        namespace_by_id=namespace_by_id,
    )


def run_chroma_static(scenario: AgentCoherenceScenario, encoder, top_k: int) -> AgentCoherenceMetrics:
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as exc:
        raise RuntimeError('Install Chroma for this benchmark: pip install -e ".[bench]"') from exc

    client = chromadb.Client(Settings(anonymized_telemetry=False))
    collection = client.create_collection(
        name=f"wavemind_agent_coherence_{time.time_ns()}",
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )
    vectors = encoder.encode_vectors(memory.text for memory in scenario.memories)
    collection.add(
        ids=[memory.id for memory in scenario.memories],
        documents=[memory.text for memory in scenario.memories],
        metadatas=[{"namespace": memory.namespace} for memory in scenario.memories],
        embeddings=[vector.tolist() for vector in vectors],
    )
    text_by_id = {memory.id: memory.text for memory in scenario.memories}
    namespace_by_id = {memory.id: memory.namespace for memory in scenario.memories}

    rankings: dict[str, list[str]] = {}
    returned_texts: dict[str, list[str]] = {}
    latencies: list[float] = []
    query_vectors = encoder.encode_vectors(task.prompt for task in scenario.tasks)
    for task, query_vector in zip(scenario.tasks, query_vectors):
        started = time.perf_counter()
        result = collection.query(
            query_embeddings=[query_vector.tolist()],
            n_results=top_k,
            where={"namespace": task.namespace},
            include=[],
        )
        latencies.append((time.perf_counter() - started) * 1000.0)
        selected = list(result.get("ids", [[]])[0])
        rankings[task.id] = selected
        returned_texts[task.id] = [text_by_id[memory_id] for memory_id in selected]
    return compute_agent_metrics(
        scenario=scenario,
        rankings=rankings,
        returned_texts=returned_texts,
        latencies_ms=latencies,
        top_k=top_k,
        engine="Chroma static",
        namespace_by_id=namespace_by_id,
    )


def run_benchmark(
    *,
    engines: Iterable[str],
    memory_count: int = 500,
    encoder_kind: str = "hash",
    top_k: int = 5,
) -> dict[str, Any]:
    scenario = build_agent_coherence_scenario(memory_count=memory_count)
    base_encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    encoder = cache_encoder_for_scenario(scenario, base_encoder)
    runners = {
        "wavemind": run_wavemind,
        "wavemind-memory-os": run_wavemind_memory_os,
        "memory-os": run_wavemind_memory_os,
        "static": run_static_vector,
        "static-vector": run_static_vector,
        "chroma": run_chroma_static,
        "chroma-static": run_chroma_static,
    }
    results = []
    for engine in engines:
        key = engine.lower()
        if key not in runners:
            raise ValueError(f"Unknown engine: {engine}")
        results.append(asdict(runners[key](scenario, encoder, top_k)))
    return {
        "schema": "wavemind.agent_coherence_benchmark.v1",
        "generated_at": _utc_now_iso(),
        "scenario": {
            "name": scenario.name,
            "memories": len(scenario.memories),
            "tasks": len(scenario.tasks),
            "top_k": top_k,
            "categories": sorted({task.category for task in scenario.tasks}),
            "description": (
                "Agent task simulation over long user history. It measures whether "
                "retrieved memory lets an agent choose the correct personalized "
                "action while suppressing stale facts and saving context tokens."
            ),
        },
        "embedding": {
            "kind": encoder_kind,
            "class": type(base_encoder).__name__,
            "cached": True,
            "vector_dim": getattr(encoder, "vector_dim", None),
            "note": "All engines receive embeddings from the same WaveMind encoder.",
        },
        "results": results,
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def print_table(payload: dict[str, Any]) -> None:
    print("| engine | task success | top1 decision | stale error | context saved | coherent turns | avg latency |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for result in payload["results"]:
        print(
            f"| {result['engine']} | "
            f"{result['task_success_rate']:.2f} | "
            f"{result['decision_success_at_1']:.2f} | "
            f"{result['stale_error_rate']:.2f} | "
            f"{result['context_budget_saved']:.2f} | "
            f"{result['coherent_turns']} | "
            f"{result['avg_latency_ms']:.2f} ms |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memories", type=int, default=500)
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=[
            "wavemind",
            "wavemind-memory-os",
            "memory-os",
            "static",
            "static-vector",
            "chroma",
            "chroma-static",
        ],
        default=["wavemind", "static"],
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/agent_coherence_results.json"),
    )
    args = parser.parse_args()

    payload = run_benchmark(
        engines=args.engines,
        memory_count=args.memories,
        encoder_kind=args.encoder,
        top_k=args.top_k,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
