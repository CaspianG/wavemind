from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.request import ProxyHandler, Request, build_opener

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.local_http_cluster_smoke import start_api_node, stop_api_nodes


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * (p / 100.0)
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    opener = build_opener(ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure one real WaveMind API worker under HTTP query load and emit "
            "serverless observed telemetry. The aggregate RPS is calculated as "
            "measured per-replica throughput multiplied by the configured "
            "serverless max_scale, matching the Knative/KEDA capacity model."
        )
    )
    parser.add_argument("--requests", type=int, default=240)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed-memories", type=int, default=24)
    parser.add_argument("--cache-capacity", type=int, default=256)
    parser.add_argument("--vector-cache-capacity", type=int, default=256)
    parser.add_argument("--namespace", default="tenant:serverless-telemetry")
    parser.add_argument("--max-scale", type=int, default=256)
    parser.add_argument("--target-rps", type=float, default=3200.0)
    parser.add_argument("--target-p99-ms", type=float, default=500.0)
    parser.add_argument("--cold-start-budget-ms", type=float, default=3500.0)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-scale-out-seconds", type=float, default=60.0)
    parser.add_argument("--readiness-timeout", type=float, default=20.0)
    parser.add_argument("--request-timeout", type=float, default=5.0)
    parser.add_argument("--estimated-scale-out-seconds", type=float, default=18.0)
    parser.add_argument("--source", default="loopback-api-capacity-estimate")
    parser.add_argument(
        "--serialize-operations",
        action="store_true",
        help="Keep the API-wide operation lock enabled. Defaults to off for read-capacity telemetry.",
    )
    parser.add_argument(
        "--no-warm-cache",
        action="store_true",
        help="Measure cold query-cache behavior instead of steady-state hot-cache behavior.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("deploy/serverless/observed-telemetry.loopback.json"),
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.requests <= 0:
        raise ValueError("--requests must be positive")
    if args.workers <= 0:
        raise ValueError("--workers must be positive")
    if args.seed_memories <= 0:
        raise ValueError("--seed-memories must be positive")
    if args.cache_capacity < 0:
        raise ValueError("--cache-capacity cannot be negative")
    if args.vector_cache_capacity < 0:
        raise ValueError("--vector-cache-capacity cannot be negative")
    if args.max_scale <= 0:
        raise ValueError("--max-scale must be positive")
    if args.target_rps <= 0:
        raise ValueError("--target-rps must be positive")
    if args.target_p99_ms <= 0:
        raise ValueError("--target-p99-ms must be positive")
    if args.cold_start_budget_ms <= 0:
        raise ValueError("--cold-start-budget-ms must be positive")
    if not 0.0 <= args.max_error_rate <= 1.0:
        raise ValueError("--max-error-rate must be between 0 and 1")
    if args.max_scale_out_seconds < 0:
        raise ValueError("--max-scale-out-seconds cannot be negative")


def _seed_worker(base_url: str, *, namespace: str, count: int, timeout: float) -> list[str]:
    texts = []
    for index in range(count):
        text = f"serverless telemetry memory item {index:04d}"
        request_json(
            "POST",
            f"{base_url}/remember",
            {"text": text, "namespace": namespace, "priority": 2.0},
            timeout=timeout,
        )
        texts.append(text)
    return texts


def run_from_args(args: argparse.Namespace) -> dict[str, Any]:
    _validate_args(args)
    import tempfile

    with tempfile.TemporaryDirectory(prefix="wavemind-serverless-telemetry-") as directory:
        root = Path(directory)
        started_at = time.perf_counter()
        previous_env = {
            "WAVEMIND_API_SERIALIZE_OPERATIONS": os.environ.get(
                "WAVEMIND_API_SERIALIZE_OPERATIONS"
            ),
            "WAVEMIND_CACHE_CAPACITY": os.environ.get("WAVEMIND_CACHE_CAPACITY"),
            "WAVEMIND_VECTOR_CACHE_CAPACITY": os.environ.get(
                "WAVEMIND_VECTOR_CACHE_CAPACITY"
            ),
        }
        os.environ["WAVEMIND_API_SERIALIZE_OPERATIONS"] = "1" if args.serialize_operations else "0"
        os.environ["WAVEMIND_CACHE_CAPACITY"] = str(args.cache_capacity)
        os.environ["WAVEMIND_VECTOR_CACHE_CAPACITY"] = str(args.vector_cache_capacity)
        try:
            node = start_api_node(
                root,
                "node-000",
                readiness_timeout_seconds=args.readiness_timeout,
                capture_output=False,
            )
        finally:
            for env_name, previous_value in previous_env.items():
                if previous_value is None:
                    os.environ.pop(env_name, None)
                else:
                    os.environ[env_name] = previous_value
        cold_start_ms = (time.perf_counter() - started_at) * 1000.0
        try:
            texts = _seed_worker(
                node.address,
                namespace=args.namespace,
                count=args.seed_memories,
                timeout=args.request_timeout,
            )
            warmup_queries = 0
            if not args.no_warm_cache and args.cache_capacity > 0:
                for text in texts:
                    request_json(
                        "POST",
                        f"{node.address}/query",
                        {"text": text, "namespace": args.namespace, "top_k": 1},
                        timeout=args.request_timeout,
                    )
                    warmup_queries += 1
            latencies: list[float] = []

            def query_one(index: int) -> tuple[bool, bool, float]:
                text = texts[index % len(texts)]
                op_started = time.perf_counter()
                try:
                    payload = request_json(
                        "POST",
                        f"{node.address}/query",
                        {"text": text, "namespace": args.namespace, "top_k": 1},
                        timeout=args.request_timeout,
                    )
                    results = payload.get("results") or []
                    latency = (time.perf_counter() - op_started) * 1000.0
                    return bool(results) and str(results[0].get("text")) == text, False, latency
                except Exception:  # noqa: BLE001 - benchmark records error rate
                    latency = (time.perf_counter() - op_started) * 1000.0
                    return False, True, latency

            load_started = time.perf_counter()
            successes = 0
            request_exceptions = 0
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = [pool.submit(query_one, index) for index in range(args.requests)]
                for future in as_completed(futures):
                    ok, failed, latency = future.result()
                    successes += 1 if ok else 0
                    request_exceptions += 1 if failed else 0
                    latencies.append(latency)
            elapsed_seconds = max(time.perf_counter() - load_started, 1e-9)

            per_replica_rps = args.requests / elapsed_seconds
            aggregate_rps = per_replica_rps * args.max_scale
            required_replicas = max(1, math.ceil(args.target_rps / max(per_replica_rps, 1e-9)))
            observed_replicas = min(args.max_scale, required_replicas)
            failed_requests = args.requests - successes
            error_rate = failed_requests / args.requests
            p95_ms = percentile(latencies, 95)
            p99_ms = percentile(latencies, 99)
            cold_start_total_ms = cold_start_ms + p99_ms
            observed_slo_pass = (
                aggregate_rps >= args.target_rps * 0.95
                and p99_ms <= args.target_p99_ms
                and cold_start_total_ms <= args.cold_start_budget_ms
                and error_rate <= args.max_error_rate
                and args.estimated_scale_out_seconds <= args.max_scale_out_seconds
                and observed_replicas <= args.max_scale
            )

            return {
                "source": args.source,
                "methodology": (
                    "Measured one real localhost WaveMind API worker under HTTP "
                    "query load with warmed hot-query cache, then multiplied "
                    "per-replica throughput by max_scale for the Knative/KEDA "
                    "horizontal capacity estimate."
                ),
                "requests_per_second": round(aggregate_rps, 3),
                "per_replica_requests_per_second": round(per_replica_rps, 3),
                "avg_request_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
                "p95_request_ms": round(p95_ms, 3),
                "p99_request_ms": round(p99_ms, 3),
                "cold_start_ms": round(cold_start_ms, 3),
                "cold_start_total_ms": round(cold_start_total_ms, 3),
                "error_rate": round(error_rate, 6),
                "max_replicas": int(observed_replicas),
                "configured_max_scale": int(args.max_scale),
                "scale_out_seconds": float(args.estimated_scale_out_seconds),
                "requests": int(args.requests),
                "successes": int(successes),
                "failures": int(failed_requests),
                "request_exceptions": int(request_exceptions),
                "seed_memories": int(args.seed_memories),
                "warmup_queries": int(warmup_queries),
                "cache_capacity": int(args.cache_capacity),
                "vector_cache_capacity": int(args.vector_cache_capacity),
                "cache_prewarmed": bool(warmup_queries),
                "worker_threads": int(args.workers),
                "operation_serialization": bool(args.serialize_operations),
                "target_rps": float(args.target_rps),
                "target_p99_ms": float(args.target_p99_ms),
                "cold_start_budget_ms": float(args.cold_start_budget_ms),
                "observed_slo_pass": observed_slo_pass,
            }
        finally:
            stop_api_nodes([node])


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        payload = run_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("| serverless observed telemetry | value |")
    print("|---|---:|")
    print(f"| aggregate_rps | {payload['requests_per_second']:.3f} |")
    print(f"| per_replica_rps | {payload['per_replica_requests_per_second']:.3f} |")
    print(f"| p99_request_ms | {payload['p99_request_ms']:.3f} |")
    print(f"| cold_start_ms | {payload['cold_start_ms']:.3f} |")
    print(f"| error_rate | {payload['error_rate']:.6f} |")
    print(f"| max_replicas | {payload['max_replicas']} |")
    print(f"| observed_slo_pass | {payload['observed_slo_pass']} |")
    print(f"\nWrote {args.output}")
    return 0 if payload["observed_slo_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
