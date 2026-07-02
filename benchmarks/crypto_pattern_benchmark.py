from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind
from wavemind.encoders import create_text_encoder


@dataclass(frozen=True)
class CryptoPattern:
    id: str
    text: str
    family: str
    direction: str
    future_return_bps: float
    priority: float


@dataclass(frozen=True)
class CryptoQuery:
    id: str
    text: str
    expected_family: str
    expected_direction: str
    expected_return_bps: float


@dataclass(frozen=True)
class CryptoScenario:
    name: str
    memories: list[CryptoPattern]
    queries: list[CryptoQuery]


@dataclass(frozen=True)
class CryptoMetrics:
    engine: str
    direction_accuracy_at_1: float
    direction_accuracy_at_3: float
    family_accuracy_at_1: float
    mean_abs_return_error_bps: float
    avg_latency_ms: float
    p95_latency_ms: float
    queries: int


FAMILIES = {
    "breakout_up": {
        "direction": "up",
        "return_bps": 145.0,
        "features": ("trend_up", "resistance_break", "volume_expansion", "close_near_high"),
    },
    "breakdown_down": {
        "direction": "down",
        "return_bps": -135.0,
        "features": ("trend_down", "support_break", "volume_expansion", "close_near_low"),
    },
    "mean_reversion_up": {
        "direction": "up",
        "return_bps": 80.0,
        "features": ("oversold", "lower_wick", "volume_capitulation", "range_expansion"),
    },
    "mean_reversion_down": {
        "direction": "down",
        "return_bps": -75.0,
        "features": ("overbought", "upper_wick", "volume_climax", "range_expansion"),
    },
    "range_flat": {
        "direction": "flat",
        "return_bps": 5.0,
        "features": ("sideways", "low_volume", "compressed_range", "mean_touch"),
    },
}


def _feature_text(family: str, index: int, include_outcome: bool) -> tuple[str, float, float]:
    spec = FAMILIES[family]
    drift = ((index % 7) - 3) * 4.0
    future_return = float(spec["return_bps"] + drift)
    volatility = 0.9 + (index % 5) * 0.18
    volume_z = 0.4 + (index % 6) * 0.35
    rsi = {
        "breakout_up": 67 + (index % 5),
        "breakdown_down": 33 - (index % 5),
        "mean_reversion_up": 24 + (index % 4),
        "mean_reversion_down": 76 - (index % 4),
        "range_flat": 49 + (index % 3),
    }[family]
    parts = [
        "asset crypto",
        "symbol BTCUSDT",
        "timeframe 1h",
        f"family_hint {family}",
        f"features {' '.join(spec['features'])}",
        f"volatility_bucket {round(volatility, 2)}",
        f"volume_z_bucket {round(volume_z, 2)}",
        f"rsi_bucket {rsi}",
        f"window_return_bps {round(float(spec['return_bps']) * 0.35, 1)}",
    ]
    if include_outcome:
        parts.extend(
            [
                f"future_direction {spec['direction']}",
                f"future_return_bps {round(future_return, 1)}",
            ]
        )
    return " | ".join(parts), future_return, volume_z


def build_synthetic_crypto_scenario(
    history_count: int = 250,
    query_count: int = 60,
) -> CryptoScenario:
    if history_count < len(FAMILIES):
        raise ValueError("history_count must cover every pattern family")
    if query_count < len(FAMILIES):
        raise ValueError("query_count must cover every pattern family")
    family_names = list(FAMILIES)
    memories: list[CryptoPattern] = []
    for index in range(history_count):
        family = family_names[index % len(family_names)]
        text, future_return, volume_z = _feature_text(family, index, include_outcome=True)
        priority = 1.0 + min(4.0, abs(future_return) / 50.0) + volume_z * 0.2
        memories.append(
            CryptoPattern(
                id=f"hist_{index:04d}_{family}",
                text=text,
                family=family,
                direction=str(FAMILIES[family]["direction"]),
                future_return_bps=future_return,
                priority=priority,
            )
        )
    queries: list[CryptoQuery] = []
    for index in range(query_count):
        family = family_names[(index * 2 + 1) % len(family_names)]
        text, future_return, _volume_z = _feature_text(family, index + history_count, include_outcome=False)
        queries.append(
            CryptoQuery(
                id=f"query_{index:04d}_{family}",
                text=text,
                expected_family=family,
                expected_direction=str(FAMILIES[family]["direction"]),
                expected_return_bps=future_return,
            )
        )
    return CryptoScenario(name="synthetic_crypto_patterns", memories=memories, queries=queries)


def compute_metrics(
    scenario: CryptoScenario,
    rankings: dict[str, list[str]],
    latencies_ms: list[float],
    engine: str,
) -> CryptoMetrics:
    by_id = {item.id: item for item in scenario.memories}
    direction_at_1: list[float] = []
    direction_at_3: list[float] = []
    family_at_1: list[float] = []
    return_errors: list[float] = []
    for query in scenario.queries:
        ranked = [by_id[item_id] for item_id in rankings.get(query.id, []) if item_id in by_id]
        top = ranked[:1]
        top3 = ranked[:3]
        direction_at_1.append(1.0 if top and top[0].direction == query.expected_direction else 0.0)
        direction_at_3.append(1.0 if any(item.direction == query.expected_direction for item in top3) else 0.0)
        family_at_1.append(1.0 if top and top[0].family == query.expected_family else 0.0)
        if top:
            return_errors.append(abs(top[0].future_return_bps - query.expected_return_bps))
    sorted_latencies = sorted(latencies_ms)
    p95_index = min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95)) if sorted_latencies else 0
    return CryptoMetrics(
        engine=engine,
        direction_accuracy_at_1=statistics.mean(direction_at_1) if direction_at_1 else 0.0,
        direction_accuracy_at_3=statistics.mean(direction_at_3) if direction_at_3 else 0.0,
        family_accuracy_at_1=statistics.mean(family_at_1) if family_at_1 else 0.0,
        mean_abs_return_error_bps=statistics.mean(return_errors) if return_errors else math.inf,
        avg_latency_ms=statistics.mean(latencies_ms) if latencies_ms else 0.0,
        p95_latency_ms=sorted_latencies[p95_index] if sorted_latencies else 0.0,
        queries=len(scenario.queries),
    )


def run_wavemind(scenario: CryptoScenario, encoder, top_k: int) -> CryptoMetrics:
    with tempfile.TemporaryDirectory() as tmp:
        memory = WaveMind(
            db_path=Path(tmp) / "crypto-patterns.sqlite3",
            encoder=encoder,
            index_kind="numpy",
            score_threshold=0.0,
            vector_weight=0.72,
            field_weight=0.08,
            priority_weight=0.20,
            lexical_weight=0.20,
            rerank_k=max(top_k, 25),
            persist_access_on_query=False,
            query_feedback_strength=0.0,
        )
        try:
            for item in scenario.memories:
                memory.remember(
                    item.text,
                    namespace="crypto:BTCUSDT:1h",
                    tags=("crypto", item.family, item.direction),
                    priority=item.priority,
                    metadata={
                        "pattern_id": item.id,
                        "family": item.family,
                        "direction": item.direction,
                        "future_return_bps": item.future_return_bps,
                    },
                )
            rankings: dict[str, list[str]] = {}
            latencies: list[float] = []
            for query in scenario.queries:
                started = time.perf_counter()
                results = memory.query(query.text, namespace="crypto:BTCUSDT:1h", top_k=top_k)
                latencies.append((time.perf_counter() - started) * 1000.0)
                rankings[query.id] = [str(result.metadata.get("pattern_id", "")) for result in results]
        finally:
            memory.close()
    return compute_metrics(scenario, rankings, latencies, "WaveMind")


def run_static_vector(scenario: CryptoScenario, encoder, top_k: int) -> CryptoMetrics:
    memory_vectors = encoder.encode_vectors(item.text for item in scenario.memories)
    query_vectors = encoder.encode_vectors(query.text for query in scenario.queries)
    memory_ids = [item.id for item in scenario.memories]
    rankings: dict[str, list[str]] = {}
    latencies: list[float] = []
    for query, qvec in zip(scenario.queries, query_vectors):
        started = time.perf_counter()
        scores = np.dot(memory_vectors, qvec)
        order = np.argsort(scores)[::-1][:top_k]
        latencies.append((time.perf_counter() - started) * 1000.0)
        rankings[query.id] = [memory_ids[int(index)] for index in order]
    return compute_metrics(scenario, rankings, latencies, "Static vector")


def run_benchmark(
    engines: Iterable[str],
    history_count: int = 250,
    query_count: int = 60,
    top_k: int = 5,
    encoder_kind: str = "hash",
) -> dict:
    scenario = build_synthetic_crypto_scenario(history_count=history_count, query_count=query_count)
    encoder = create_text_encoder(kind=encoder_kind, vector_dim=384)
    runners = {
        "wavemind": run_wavemind,
        "static": run_static_vector,
        "static-vector": run_static_vector,
    }
    results = []
    for engine in engines:
        key = engine.lower()
        if key not in runners:
            raise ValueError(f"Unknown engine: {engine}")
        results.append(asdict(runners[key](scenario, encoder, top_k)))
    return {
        "scenario": {
            "name": scenario.name,
            "asset": "BTCUSDT",
            "timeframe": "1h",
            "history_patterns": len(scenario.memories),
            "queries": len(scenario.queries),
            "top_k": top_k,
            "note": "Synthetic pattern-retrieval benchmark. This is not a trading signal or profit claim.",
        },
        "embedding": {
            "kind": encoder_kind,
            "class": type(encoder).__name__,
            "vector_dim": getattr(encoder, "vector_dim", None),
        },
        "results": results,
    }


def print_table(payload: dict) -> None:
    print("| engine | direction@1 | direction@3 | family@1 | abs return error | avg latency |")
    print("|---|---:|---:|---:|---:|---:|")
    for result in payload["results"]:
        print(
            f"| {result['engine']} | "
            f"{result['direction_accuracy_at_1']:.3f} | "
            f"{result['direction_accuracy_at_3']:.3f} | "
            f"{result['family_accuracy_at_1']:.3f} | "
            f"{result['mean_abs_return_error_bps']:.1f} bps | "
            f"{result['avg_latency_ms']:.2f} ms |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engines", nargs="+", choices=["wavemind", "static", "static-vector"], default=["wavemind", "static"])
    parser.add_argument("--history", type=int, default=250)
    parser.add_argument("--queries", type=int, default=60)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--encoder", choices=["hash", "sentence"], default="hash")
    parser.add_argument("--output", type=Path, default=Path("benchmarks/crypto_pattern_results.json"))
    args = parser.parse_args()
    payload = run_benchmark(
        engines=args.engines,
        history_count=args.history,
        query_count=args.queries,
        top_k=args.top_k,
        encoder_kind=args.encoder,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

