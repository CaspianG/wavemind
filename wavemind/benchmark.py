from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BenchmarkCase:
    query: str
    expected_text: str
    namespace: str = "default"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkReport:
    precision_at_k: float
    recall_at_k: float
    avg_latency_ms: float
    p95_latency_ms: float
    capacity: int
    cases: int
    misses: list[str] = field(default_factory=list)


def run_benchmark(mind, cases: list[BenchmarkCase], k: int = 3) -> BenchmarkReport:
    if not cases:
        return BenchmarkReport(0.0, 0.0, 0.0, 0.0, mind.stats()["active_memories"], 0, [])

    hits = 0
    precision_terms = []
    latencies = []
    misses = []
    for case in cases:
        started = time.perf_counter()
        results = mind.query(case.query, namespace=case.namespace, tags=case.tags, top_k=k)
        latencies.append((time.perf_counter() - started) * 1000.0)
        texts = [result.text for result in results]
        if case.expected_text in texts:
            hits += 1
            precision_terms.append(1.0 / max(1, len(texts)))
        else:
            precision_terms.append(0.0)
            misses.append(case.query)

    sorted_latencies = sorted(latencies)
    p95_index = min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95))
    return BenchmarkReport(
        precision_at_k=sum(precision_terms) / len(precision_terms),
        recall_at_k=hits / len(cases),
        avg_latency_ms=statistics.mean(latencies),
        p95_latency_ms=sorted_latencies[p95_index],
        capacity=mind.stats()["active_memories"],
        cases=len(cases),
        misses=misses,
    )


def synthetic_cases(namespace: str = "bench") -> list[tuple[str, str]]:
    return [
        ("кошка", "кошка сидит на подоконнике"),
        ("собака", "собака лает во дворе"),
        ("market breakout", "market breakout above resistance"),
        ("agent recall", "agent memory recall improves answers"),
    ]

