from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind
from wavemind.encoders import create_text_encoder


@dataclass(frozen=True)
class DynamicMemory:
    id: str
    text: str
    namespace: str = "agent-a"
    tags: tuple[str, ...] = ("profile",)
    ttl_seconds: float | None = None
    priority: float = 1.0


@dataclass(frozen=True)
class Reinforcement:
    text: str
    namespace: str = "agent-a"
    repeat: int = 1


@dataclass(frozen=True)
class DynamicCheck:
    id: str
    category: str
    text: str
    namespace: str
    expected_id: str | None
    forbidden_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DynamicScenario:
    memories: list[DynamicMemory]
    checks: list[DynamicCheck]
    deleted_ids: tuple[str, ...]
    reinforcements: tuple[Reinforcement, ...]


@dataclass(frozen=True)
class DynamicEngineMetrics:
    engine: str
    precision_at_1: float
    precision_at_3: float
    suppression_rate: float
    category_success: dict[str, float]
    avg_latency_ms: float
    p95_latency_ms: float
    checks: int


CORE_MEMORIES: tuple[DynamicMemory, ...] = (
    DynamicMemory(
        id="style_cold",
        text="The assistant should give long exploratory answers with broad background context.",
        priority=1.0,
    ),
    DynamicMemory(
        id="style_hot",
        text="The assistant should give short practical answers with direct next steps.",
        priority=8.0,
    ),
    DynamicMemory(
        id="project_cold",
        text="The user once mentioned an old side project named Garden Notes.",
        priority=1.0,
    ),
    DynamicMemory(
        id="project_hot",
        text="The important project right now is WaveMind dynamic memory benchmarks.",
        priority=8.0,
    ),
    DynamicMemory(
        id="expired_token",
        text="The valid temporary login token for this session is blue-114.",
        ttl_seconds=0,
        priority=1.0,
    ),
    DynamicMemory(
        id="active_token",
        text="The valid temporary login token for this session is green-772.",
        priority=4.0,
    ),
    DynamicMemory(
        id="old_city",
        text="The user's current city is Berlin.",
        priority=1.0,
    ),
    DynamicMemory(
        id="new_city",
        text="The user's current city is Lisbon.",
        priority=5.0,
    ),
    DynamicMemory(
        id="old_role",
        text="The user's current role is product manager.",
        priority=1.0,
    ),
    DynamicMemory(
        id="new_role",
        text="The user's current role is trader.",
        priority=5.0,
    ),
    DynamicMemory(
        id="alice_budget",
        text="The user's monthly tool budget is 2000 dollars.",
        namespace="agent-a",
        priority=4.0,
    ),
    DynamicMemory(
        id="bob_budget",
        text="The user's monthly tool budget is 50 dollars.",
        namespace="agent-b",
        priority=4.0,
    ),
    DynamicMemory(
        id="alice_language",
        text="The user prefers English for technical discussions.",
        namespace="agent-a",
        priority=4.0,
    ),
    DynamicMemory(
        id="bob_language",
        text="The user prefers Spanish for technical discussions.",
        namespace="agent-b",
        priority=4.0,
    ),
)


DYNAMIC_CHECKS: tuple[DynamicCheck, ...] = (
    DynamicCheck(
        id="check_hot_style",
        category="hot_memory",
        text="How should the assistant answer this user?",
        namespace="agent-a",
        expected_id="style_hot",
    ),
    DynamicCheck(
        id="check_hot_project",
        category="hot_memory",
        text="Which project is important right now?",
        namespace="agent-a",
        expected_id="project_hot",
    ),
    DynamicCheck(
        id="check_ttl_token",
        category="ttl",
        text="What temporary login token is still valid?",
        namespace="agent-a",
        expected_id="active_token",
        forbidden_ids=("expired_token",),
    ),
    DynamicCheck(
        id="check_correction_city",
        category="correction",
        text="What is the user's current city?",
        namespace="agent-a",
        expected_id="new_city",
        forbidden_ids=("old_city",),
    ),
    DynamicCheck(
        id="check_correction_role",
        category="correction",
        text="What is the user's current role?",
        namespace="agent-a",
        expected_id="new_role",
        forbidden_ids=("old_role",),
    ),
    DynamicCheck(
        id="check_namespace_budget",
        category="namespace",
        text="What is the user's monthly tool budget?",
        namespace="agent-a",
        expected_id="alice_budget",
        forbidden_ids=("bob_budget",),
    ),
    DynamicCheck(
        id="check_namespace_language",
        category="namespace",
        text="Which language should be used for technical discussions?",
        namespace="agent-a",
        expected_id="alice_language",
        forbidden_ids=("bob_language",),
    ),
    DynamicCheck(
        id="check_stale_token_absent",
        category="ttl",
        text="Is blue-114 still a valid temporary login token?",
        namespace="agent-a",
        expected_id=None,
        forbidden_ids=("expired_token",),
    ),
)


REINFORCEMENTS: tuple[Reinforcement, ...] = (
    Reinforcement("short practical answers with direct next steps", repeat=8),
    Reinforcement("WaveMind dynamic memory benchmarks", repeat=8),
)


FILLER_TOPICS: tuple[str, ...] = (
    "calendar planning",
    "market watchlists",
    "code editor setup",
    "database backups",
    "meeting notes",
    "documentation drafts",
    "feature flags",
    "pricing research",
    "CLI experiments",
    "API smoke tests",
)


def build_dynamic_memory_scenario(memory_count: int = 200) -> DynamicScenario:
    if memory_count < len(CORE_MEMORIES):
        raise ValueError(f"memory_count must be at least {len(CORE_MEMORIES)}")

    memories = list(CORE_MEMORIES)
    for index in range(1, memory_count - len(CORE_MEMORIES) + 1):
        topic = FILLER_TOPICS[(index - 1) % len(FILLER_TOPICS)]
        namespace = "agent-a" if index % 3 else "agent-b"
        memories.append(
            DynamicMemory(
                id=f"filler_{index:03d}",
                text=(
                    f"Background memory {index} about {topic}; "
                    f"this is useful but not part of the dynamic benchmark target."
                ),
                namespace=namespace,
                tags=("profile", "filler", topic.replace(" ", "-")),
                priority=1.0,
            )
        )

    return DynamicScenario(
        memories=memories,
        checks=list(DYNAMIC_CHECKS),
        deleted_ids=("old_city", "old_role"),
        reinforcements=REINFORCEMENTS,
    )


def compute_dynamic_metrics(
    checks: Iterable[DynamicCheck],
    rankings: dict[str, list[str]],
    latencies_ms: list[float],
    engine: str = "benchmark",
) -> DynamicEngineMetrics:
    check_list = list(checks)
    expected_checks = [check for check in check_list if check.expected_id is not None]
    suppression_checks = [check for check in check_list if check.forbidden_ids]

    hit1 = 0
    hit3 = 0
    suppressed = 0
    category_counts: dict[str, int] = {}
    category_hits: dict[str, int] = {}

    for check in check_list:
        ranked_ids = rankings.get(check.id, [])
        expected_ok = True
        if check.expected_id is not None:
            expected_ok = ranked_ids[:1] == [check.expected_id]
            if expected_ok:
                hit1 += 1
            if check.expected_id in ranked_ids[:3]:
                hit3 += 1

        suppression_ok = True
        if check.forbidden_ids:
            forbidden = set(check.forbidden_ids)
            suppression_ok = not forbidden.intersection(ranked_ids[:3])
            if suppression_ok:
                suppressed += 1

        category_counts[check.category] = category_counts.get(check.category, 0) + 1
        if expected_ok and suppression_ok:
            category_hits[check.category] = category_hits.get(check.category, 0) + 1

    sorted_latencies = sorted(latencies_ms)
    if sorted_latencies:
        p95_index = min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95))
        avg_latency = statistics.mean(sorted_latencies)
        p95_latency = sorted_latencies[p95_index]
    else:
        avg_latency = 0.0
        p95_latency = 0.0

    return DynamicEngineMetrics(
        engine=engine,
        precision_at_1=hit1 / len(expected_checks) if expected_checks else 0.0,
        precision_at_3=hit3 / len(expected_checks) if expected_checks else 0.0,
        suppression_rate=suppressed / len(suppression_checks) if suppression_checks else 0.0,
        category_success={
            category: category_hits.get(category, 0) / count
            for category, count in sorted(category_counts.items())
        },
        avg_latency_ms=avg_latency,
        p95_latency_ms=p95_latency,
        checks=len(check_list),
    )


def run_wavemind(scenario: DynamicScenario, encoder, top_k: int) -> DynamicEngineMetrics:
    with tempfile.TemporaryDirectory() as tmp:
        memory = WaveMind(
            db_path=Path(tmp) / "dynamic-memory.sqlite3",
            encoder=encoder,
            index_kind="numpy",
            score_threshold=0.0,
            width=64,
            height=64,
            layers=3,
            evolve_on_feed=3,
            field_weight=0.06,
            priority_weight=0.35,
            lexical_weight=0.20,
            short_query_lexical_weight=1.5,
            rerank_k=30,
            persist_access_on_query=True,
            query_feedback_strength=0.08,
        )
        try:
            ids: dict[str, int] = {}
            for item in scenario.memories:
                ids[item.id] = memory.remember(
                    item.text,
                    namespace=item.namespace,
                    tags=item.tags,
                    ttl_seconds=item.ttl_seconds,
                    priority=item.priority,
                    metadata={"benchmark_id": item.id},
                )

            for deleted_id in scenario.deleted_ids:
                if deleted_id in ids:
                    memory.forget(id=ids[deleted_id])

            for reinforcement in scenario.reinforcements:
                for _ in range(reinforcement.repeat):
                    memory.query(reinforcement.text, namespace=reinforcement.namespace, top_k=1)

            rankings: dict[str, list[str]] = {}
            latencies: list[float] = []
            for check in scenario.checks:
                started = time.perf_counter()
                results = memory.query(check.text, namespace=check.namespace, top_k=top_k)
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[check.id] = [
                    str(result.metadata.get("benchmark_id", ""))
                    for result in results
                ]
        finally:
            memory.store.close()
    return compute_dynamic_metrics(scenario.checks, rankings, latencies, engine="WaveMind")


def run_chroma_static(scenario: DynamicScenario, encoder, top_k: int) -> DynamicEngineMetrics:
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as exc:
        raise RuntimeError(
            'Install Chroma for this benchmark: pip install -e ".[bench]"'
        ) from exc

    client = chromadb.Client(Settings(anonymized_telemetry=False))
    collection = client.create_collection(
        name=f"wavemind_dynamic_memory_{time.time_ns()}",
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )
    collection.add(
        ids=[item.id for item in scenario.memories],
        documents=[item.text for item in scenario.memories],
        metadatas=[
            {
                "namespace": item.namespace,
                "tags": ",".join(item.tags),
                "ttl_seconds": -1 if item.ttl_seconds is None else float(item.ttl_seconds),
            }
            for item in scenario.memories
        ],
        embeddings=[encoder.encode_vector(item.text).tolist() for item in scenario.memories],
    )

    rankings: dict[str, list[str]] = {}
    latencies: list[float] = []
    for check in scenario.checks:
        started = time.perf_counter()
        result = collection.query(
            query_embeddings=[encoder.encode_vector(check.text).tolist()],
            n_results=top_k,
            include=[],
        )
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[check.id] = list(result.get("ids", [[]])[0])

    return compute_dynamic_metrics(
        scenario.checks,
        rankings,
        latencies,
        engine="Chroma static",
    )


def run_benchmark(
    engines: Iterable[str],
    memory_count: int = 200,
    encoder_kind: str = "hash",
    top_k: int = 3,
) -> dict:
    scenario = build_dynamic_memory_scenario(memory_count=memory_count)
    encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    runners = {
        "wavemind": run_wavemind,
        "chroma": run_chroma_static,
        "chroma-static": run_chroma_static,
    }

    results = []
    for engine in engines:
        key = engine.lower()
        if key not in runners:
            raise ValueError(f"Unknown engine: {engine}")
        results.append(asdict(runners[key](scenario, encoder, top_k=top_k)))

    return {
        "scenario": {
            "name": "dynamic_agent_memory",
            "memories": len(scenario.memories),
            "checks": len(scenario.checks),
            "top_k": top_k,
            "behaviors": sorted({check.category for check in scenario.checks}),
        },
        "embedding": {
            "kind": encoder_kind,
            "class": type(encoder).__name__,
            "vector_dim": getattr(encoder, "vector_dim", None),
            "note": (
                "Both engines receive the same embeddings. Chroma static is used as "
                "a plain vector-store baseline without application-layer TTL, delete, "
                "namespace filtering, or recall reinforcement."
            ),
        },
        "results": results,
    }


def print_table(payload: dict) -> None:
    print("| engine | precision@1 | precision@3 | suppression | avg latency | p95 latency |")
    print("|---|---:|---:|---:|---:|---:|")
    for result in payload["results"]:
        print(
            f"| {result['engine']} | "
            f"{result['precision_at_1']:.2f} | "
            f"{result['precision_at_3']:.2f} | "
            f"{result['suppression_rate']:.2f} | "
            f"{result['avg_latency_ms']:.2f} ms | "
            f"{result['p95_latency_ms']:.2f} ms |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memories", type=int, default=200)
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=["wavemind", "chroma", "chroma-static"],
        default=["wavemind", "chroma"],
    )
    parser.add_argument("--output", type=Path, default=Path("benchmarks/dynamic_memory_results.json"))
    args = parser.parse_args()

    payload = run_benchmark(
        engines=args.engines,
        memory_count=args.memories,
        encoder_kind=args.encoder,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
