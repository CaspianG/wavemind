from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_NO_PROXY_OPENER = build_opener(ProxyHandler({}))
_LOCAL_NO_PROXY = "127.0.0.1,localhost,::1"


@dataclass
class WorkerProcess:
    index: int
    base_url: str
    process: subprocess.Popen[bytes]
    log_path: Path


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
    with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def request_text(url: str, *, timeout: float = 5.0) -> str:
    with _NO_PROXY_OPENER.open(url, timeout=timeout) as response:
        return response.read().decode("utf-8")


def build_worker_env(
    *,
    base_env: dict[str, str],
    db_path: Path,
    redis_url: str,
    redis_prefix: str,
) -> dict[str, str]:
    env = dict(base_env)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT)
        if not existing_pythonpath
        else str(PROJECT_ROOT) + os.pathsep + existing_pythonpath
    )
    env.update(
        {
            "WAVEMIND_DB": str(db_path),
            "WAVEMIND_REDIS_URL": redis_url,
            "WAVEMIND_REDIS_PREFIX": redis_prefix,
            "WAVEMIND_CACHE_TTL_SECONDS": "120",
            "WAVEMIND_VECTOR_CACHE_REDIS_URL": redis_url,
            "WAVEMIND_VECTOR_CACHE_REDIS_PREFIX": f"{redis_prefix}:qvec",
            "WAVEMIND_VECTOR_CACHE_TTL_SECONDS": "300",
            "WAVEMIND_AUDIT_QUERIES": "1",
            "WAVEMIND_ENCODER": "hash",
            "WAVEMIND_INDEX": "numpy",
            "WAVEMIND_LOG_LEVEL": "WARNING",
            "NO_PROXY": _append_local_no_proxy(env.get("NO_PROXY")),
            "no_proxy": _append_local_no_proxy(env.get("no_proxy")),
        }
    )
    return env


def _append_local_no_proxy(current: str | None) -> str:
    if not current:
        return _LOCAL_NO_PROXY
    existing = {item.strip() for item in current.split(",") if item.strip()}
    additions = [item for item in _LOCAL_NO_PROXY.split(",") if item not in existing]
    return current if not additions else current + "," + ",".join(additions)


def redis_client(redis_url: str):
    try:
        import redis
    except ImportError as exc:
        raise RuntimeError('Install Redis support with: pip install "wavemind[redis]"') from exc
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    client.ping()
    return client


def redis_key_count(client: Any, prefix: str, namespace: str | None = None) -> int:
    pattern = f"{prefix}:*" if namespace is None else f"{prefix}:{namespace}:*"
    return sum(1 for _ in client.scan_iter(match=pattern))


def redis_delete_prefix(client: Any, prefix: str) -> int:
    keys = list(client.scan_iter(match=f"{prefix}:*"))
    if keys:
        client.delete(*keys)
    return len(keys)


def redis_delete_namespace(client: Any, prefix: str, namespace: str) -> int:
    keys = list(client.scan_iter(match=f"{prefix}:{namespace}:*"))
    if keys:
        client.delete(*keys)
    return len(keys)


def start_worker(
    *,
    index: int,
    port: int,
    db_path: Path,
    redis_url: str,
    redis_prefix: str,
    log_dir: Path,
) -> WorkerProcess:
    log_path = log_dir / f"uvicorn-{index}.log"
    log_file = log_path.open("wb")
    env = build_worker_env(
        base_env=os.environ,
        db_path=db_path,
        redis_url=redis_url,
        redis_prefix=redis_prefix,
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "wavemind.api:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    log_file.close()
    return WorkerProcess(
        index=index,
        base_url=f"http://127.0.0.1:{port}",
        process=process,
        log_path=log_path,
    )


def wait_for_worker(worker: WorkerProcess, *, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        if worker.process.poll() is not None:
            log_tail = worker.log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise RuntimeError(
                f"API worker {worker.index} exited early with code "
                f"{worker.process.returncode}. Log tail:\n{log_tail}"
            )
        try:
            request_json("GET", f"{worker.base_url}/stats", timeout=1.0)
            return
        except Exception as exc:  # noqa: BLE001 - startup probing needs broad retry
            last_error = exc
            time.sleep(0.2)
    raise TimeoutError(f"API worker {worker.index} did not become ready: {last_error}")


def stop_workers(workers: list[WorkerProcess]) -> None:
    for worker in workers:
        if worker.process.poll() is None:
            worker.process.terminate()
    for worker in workers:
        if worker.process.poll() is None:
            try:
                worker.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.process.kill()
    for worker in workers:
        if worker.process.poll() is None:
            worker.process.wait(timeout=5)


def _remember(worker: WorkerProcess, text: str, namespace: str, *, priority: float = 1.0) -> int:
    payload = request_json(
        "POST",
        f"{worker.base_url}/remember",
        {"text": text, "namespace": namespace, "priority": priority},
    )
    return int(payload["id"])


def _query(worker: WorkerProcess, text: str, namespace: str, *, top_k: int = 1) -> dict[str, Any]:
    return request_json(
        "POST",
        f"{worker.base_url}/query",
        {"text": text, "namespace": namespace, "top_k": top_k},
    )


def _query_batch(
    worker: WorkerProcess,
    queries: list[str],
    namespace: str,
    *,
    top_k: int = 1,
) -> dict[str, Any]:
    return request_json(
        "POST",
        f"{worker.base_url}/query/batch",
        {
            "queries": [
                {"text": text, "namespace": namespace, "top_k": top_k}
                for text in queries
            ]
        },
    )


def _forget(worker: WorkerProcess, memory_id: int, namespace: str) -> int:
    payload = request_json(
        "DELETE",
        f"{worker.base_url}/forget",
        {"id": memory_id, "namespace": namespace},
    )
    return int(payload["deleted"])


def _feedback_batch(
    worker: WorkerProcess,
    namespace: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    return request_json(
        "POST",
        f"{worker.base_url}/feedback/batch",
        {"namespace": namespace, "items": items},
    )


def _audit_count(worker: WorkerProcess, namespace: str, action: str) -> int:
    query = urlencode({"namespace": namespace, "action": action, "limit": 100})
    payload = request_json("GET", f"{worker.base_url}/audit?{query}")
    return len(payload.get("events", []))


def _first_text(payload: dict[str, Any]) -> str | None:
    results = payload.get("results") or []
    if not results:
        return None
    return str(results[0].get("text"))


def _parse_metric(text: str, metric: str) -> float:
    for line in text.splitlines():
        if line.startswith(metric + " "):
            return float(line.split(" ", 1)[1])
    return 0.0


def _collect_metrics(workers: list[WorkerProcess]) -> dict[str, float]:
    metrics_texts = {
        worker.index: request_text(f"{worker.base_url}/metrics")
        for worker in workers
    }
    names = (
        "wavemind_cache_hits_total",
        "wavemind_cache_misses_total",
        "wavemind_vector_cache_hits_total",
        "wavemind_vector_cache_misses_total",
        "wavemind_api_query_requests_total",
        "wavemind_api_query_batch_requests_total",
    )
    return {
        name: sum(_parse_metric(text, name) for text in metrics_texts.values())
        for name in names
    }


def run_benchmark(
    *,
    redis_url: str,
    workers: int = 2,
    requests: int = 40,
    batch_size: int = 12,
    base_port: int = 8210,
    timeout_seconds: float = 30.0,
    namespace: str = "tenant:redis-api-load",
) -> dict[str, Any]:
    if workers < 2:
        raise ValueError("workers must be at least 2")
    if requests < 1:
        raise ValueError("requests must be positive")
    if batch_size < 2:
        raise ValueError("batch_size must be at least 2")

    client = redis_client(redis_url)
    redis_prefix = f"wm:redis-api-load:{uuid.uuid4().hex[:12]}"
    vector_prefix = f"{redis_prefix}:qvec"
    start_time = time.time()
    latencies: list[float] = []
    worker_processes: list[WorkerProcess] = []

    with tempfile.TemporaryDirectory(prefix="wavemind-redis-api-load-") as tmp:
        temp_dir = Path(tmp)
        log_dir = temp_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            for index in range(workers):
                worker_processes.append(
                    start_worker(
                        index=index,
                        port=base_port + index,
                        db_path=temp_dir / f"worker-{index}.sqlite3",
                        redis_url=redis_url,
                        redis_prefix=redis_prefix,
                        log_dir=log_dir,
                    )
                )
            for worker in worker_processes:
                wait_for_worker(worker, timeout_seconds=timeout_seconds)

            writer = worker_processes[0]
            reader = worker_processes[1]

            old_text = "old redis api load budget recall"
            old_id = _remember(writer, old_text, namespace)
            warm_old = _query(writer, "budget recall", namespace)
            cache_keys_after_warm = redis_key_count(client, redis_prefix, namespace)
            shared_old = _query(reader, "budget recall", namespace)
            shared_cache_visible = _first_text(shared_old) == old_text

            fresh_text = "fresh redis api load budget recall"
            fresh_id = _remember(writer, fresh_text, namespace, priority=10.0)
            cache_keys_after_remember = redis_key_count(client, redis_prefix, namespace)
            no_stale_after_remember = _first_text(_query(reader, "budget recall", namespace)) != old_text

            warm_fresh = _query(writer, "fresh budget recall", namespace)
            shared_fresh = _query(reader, "fresh budget recall", namespace)
            shared_fresh_visible = _first_text(shared_fresh) == fresh_text

            feedback_useful_text = "redis batch feedback useful recall"
            feedback_stale_text = "redis batch feedback stale recall"
            feedback_useful_id = _remember(writer, feedback_useful_text, namespace)
            feedback_stale_id = _remember(
                writer,
                feedback_stale_text,
                namespace,
                priority=2.0,
            )
            feedback_query = "batch feedback recall"
            warm_feedback = _query(writer, feedback_query, namespace, top_k=2)
            feedback_first_before = _first_text(warm_feedback)
            batch_cache_keys_after_warm = redis_key_count(client, redis_prefix, namespace)
            shared_feedback = _query(reader, feedback_query, namespace, top_k=2)
            batch_shared_cache_visible = _first_text(shared_feedback) == feedback_first_before
            batch_feedback_payload = _feedback_batch(
                writer,
                namespace,
                [
                    {
                        "id": feedback_useful_id,
                        "useful": True,
                        "strength": 0.5,
                        "query": feedback_query,
                        "reason": "redis-load-accepted",
                    },
                    {
                        "id": feedback_stale_id,
                        "useful": False,
                        "strength": 0.25,
                        "query": feedback_query,
                        "reason": "redis-load-rejected",
                    },
                    {
                        "id": feedback_useful_id,
                        "namespace": namespace + ":wrong",
                        "useful": True,
                    },
                ],
            )
            accepted_feedback = [
                item for item in batch_feedback_payload.get("results", []) if item.get("ok")
            ]
            feedback_by_id = {int(item["id"]): item for item in accepted_feedback}
            batch_cache_keys_after_feedback = redis_key_count(client, redis_prefix, namespace)
            batch_stale_prevented_after_feedback = (
                _first_text(_query(reader, feedback_query, namespace, top_k=2))
                != feedback_first_before
            )
            batch_feedback_audit_events = _audit_count(writer, namespace, "feedback")
            batch_positive_delta = float(
                feedback_by_id.get(feedback_useful_id, {}).get("priority", 1.0)
            ) - 1.0
            batch_negative_delta = float(
                feedback_by_id.get(feedback_stale_id, {}).get("priority", 2.0)
            ) - 2.0

            deleted = _forget(writer, fresh_id, namespace)
            cache_keys_after_forget = redis_key_count(client, redis_prefix, namespace)
            no_stale_after_forget = _first_text(_query(reader, "fresh budget recall", namespace)) != fresh_text

            facts: list[tuple[str, str]] = []
            for index in range(max(4, min(requests, 100))):
                text = f"redis live api load fact {index} unique marker {index}"
                query = f"unique marker {index}"
                _remember(writer, text, namespace)
                facts.append((query, text))

            for query, expected in facts:
                warmed = _query(writer, query, namespace)
                if _first_text(warmed) != expected:
                    raise RuntimeError(f"warm query failed for {query!r}: {warmed}")

            def load_query(index: int) -> tuple[bool, float, int]:
                query, expected = facts[index % len(facts)]
                worker = worker_processes[index % len(worker_processes)]
                started = time.perf_counter()
                payload = _query(worker, query, namespace)
                latency_ms = (time.perf_counter() - started) * 1000.0
                return _first_text(payload) == expected, latency_ms, worker.index

            ok_count = 0
            worker_counts = {worker.index: 0 for worker in worker_processes}
            with ThreadPoolExecutor(max_workers=min(16, requests)) as executor:
                futures = [executor.submit(load_query, index) for index in range(requests)]
                for future in as_completed(futures):
                    ok, latency_ms, worker_index = future.result()
                    ok_count += 1 if ok else 0
                    latencies.append(latency_ms)
                    worker_counts[worker_index] += 1

            batch_namespace = namespace + ":batch-query"
            batch_queries: list[str] = []
            batch_expected: dict[str, str] = {}
            for index in range(batch_size):
                text = f"redis batch query fact {index} unique batch marker {index}"
                query = f"unique batch marker {index}"
                for worker in worker_processes:
                    _remember(worker, text, batch_namespace)
                batch_queries.append(query)
                batch_expected[query] = text

            batch_before_metrics = _collect_metrics(worker_processes)
            for query in batch_queries:
                warmed = _query(writer, query, batch_namespace)
                if _first_text(warmed) != batch_expected[query]:
                    raise RuntimeError(f"batch warm query failed for {query!r}: {warmed}")
            batch_after_warm_metrics = _collect_metrics(worker_processes)
            batch_vector_keys_after_warm = redis_key_count(client, vector_prefix)

            redis_delete_namespace(client, redis_prefix, batch_namespace)
            individual_latencies: list[float] = []
            individual_ok = 0
            for query in batch_queries:
                started = time.perf_counter()
                payload = _query(reader, query, batch_namespace)
                individual_latencies.append((time.perf_counter() - started) * 1000.0)
                individual_ok += 1 if _first_text(payload) == batch_expected[query] else 0
            batch_after_individual_metrics = _collect_metrics(worker_processes)

            redis_delete_namespace(client, redis_prefix, batch_namespace)
            batch_started = time.perf_counter()
            batch_payload = _query_batch(reader, batch_queries, batch_namespace)
            batch_latency_ms = (time.perf_counter() - batch_started) * 1000.0
            batch_items = batch_payload.get("items", [])
            batch_returned_texts = [
                item.get("results", [{}])[0].get("text")
                if item.get("results")
                else None
                for item in batch_items
            ]
            batch_ok = (
                batch_payload.get("count") == batch_size
                and len(batch_items) == batch_size
                and batch_returned_texts
                == [batch_expected[query] for query in batch_queries]
            )
            batch_after_batch_metrics = _collect_metrics(worker_processes)

            warm_vector_misses = (
                batch_after_warm_metrics["wavemind_vector_cache_misses_total"]
                - batch_before_metrics["wavemind_vector_cache_misses_total"]
            )
            individual_vector_hits = (
                batch_after_individual_metrics["wavemind_vector_cache_hits_total"]
                - batch_after_warm_metrics["wavemind_vector_cache_hits_total"]
            )
            batch_vector_hits = (
                batch_after_batch_metrics["wavemind_vector_cache_hits_total"]
                - batch_after_individual_metrics["wavemind_vector_cache_hits_total"]
            )
            individual_total_ms = sum(individual_latencies)
            request_reduction_ratio = 1.0 - (1.0 / float(batch_size))

            metrics = _collect_metrics(worker_processes)
            cache_hits = metrics["wavemind_cache_hits_total"]
            cache_misses = metrics["wavemind_cache_misses_total"]
            vector_cache_hits = metrics["wavemind_vector_cache_hits_total"]
            vector_cache_misses = metrics["wavemind_vector_cache_misses_total"]
            final_keys = redis_key_count(client, redis_prefix, namespace)
            success_rate = ok_count / requests
            elapsed_ms = (time.time() - start_time) * 1000.0
            result = {
                "schema": "wavemind.redis_api_load.v1",
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "engine": "WaveMind FastAPI + real Redis",
                "redis_url": _redact_redis_url(redis_url),
                "workers": workers,
                "requests": requests,
                "batch_query_size": batch_size,
                "namespace": namespace,
                "cache_prefix": redis_prefix,
                "vector_cache_prefix": vector_prefix,
                "old_id": old_id,
                "fresh_id": fresh_id,
                "warm_old_result": _first_text(warm_old),
                "warm_fresh_result": _first_text(warm_fresh),
                "deleted_fresh": deleted == 1,
                "shared_cache_visible_across_processes": shared_cache_visible,
                "shared_fresh_cache_visible_across_processes": shared_fresh_visible,
                "cache_keys_after_warm": cache_keys_after_warm,
                "cache_invalidated_on_remember": cache_keys_after_remember == 0,
                "stale_prevented_after_remember": no_stale_after_remember,
                "batch_feedback_accepted": batch_feedback_payload.get("accepted"),
                "batch_feedback_rejected": batch_feedback_payload.get("rejected"),
                "batch_feedback_shared_cache_visible": batch_shared_cache_visible,
                "batch_feedback_cache_keys_after_warm": batch_cache_keys_after_warm,
                "batch_feedback_cache_invalidated": batch_cache_keys_after_feedback == 0,
                "batch_feedback_stale_prevented": batch_stale_prevented_after_feedback,
                "batch_feedback_audit_events": batch_feedback_audit_events,
                "batch_feedback_positive_priority_delta": batch_positive_delta,
                "batch_feedback_negative_priority_delta": batch_negative_delta,
                "cache_invalidated_on_forget": cache_keys_after_forget == 0,
                "stale_prevented_after_forget": no_stale_after_forget,
                "successful_queries": ok_count,
                "success_rate": success_rate,
                "avg_latency_ms": statistics.mean(latencies) if latencies else 0.0,
                "p95_latency_ms": percentile(latencies, 95),
                "p99_latency_ms": percentile(latencies, 99),
                "max_latency_ms": max(latencies) if latencies else 0.0,
                "batch_query_success": batch_ok,
                "batch_query_individual_success": individual_ok == batch_size,
                "batch_query_individual_http_requests": batch_size,
                "batch_query_batch_http_requests": 1,
                "batch_query_request_reduction_ratio": request_reduction_ratio,
                "batch_query_warm_vector_misses": warm_vector_misses,
                "batch_query_individual_vector_hits": individual_vector_hits,
                "batch_query_batch_vector_hits": batch_vector_hits,
                "batch_query_vector_keys_after_warm": batch_vector_keys_after_warm,
                "batch_query_individual_total_ms": individual_total_ms,
                "batch_query_batch_ms": batch_latency_ms,
                "batch_query_total_speedup": (
                    individual_total_ms / batch_latency_ms
                    if batch_latency_ms > 0
                    else 0.0
                ),
                "batch_query_individual_p95_ms": percentile(individual_latencies, 95),
                "batch_query_individual_p99_ms": percentile(individual_latencies, 99),
                "batch_query_batch_p99_ms": batch_latency_ms,
                "cache_hits_total": cache_hits,
                "cache_misses_total": cache_misses,
                "vector_cache_hits_total": vector_cache_hits,
                "vector_cache_misses_total": vector_cache_misses,
                "redis_keys_after_load": final_keys,
                "worker_query_counts": worker_counts,
                "elapsed_ms": elapsed_ms,
                "ok": (
                    shared_cache_visible
                    and shared_fresh_visible
                    and cache_keys_after_remember == 0
                    and no_stale_after_remember
                    and batch_feedback_payload.get("accepted") == 2
                    and batch_feedback_payload.get("rejected") == 1
                    and batch_shared_cache_visible
                    and batch_cache_keys_after_feedback == 0
                    and batch_stale_prevented_after_feedback
                    and batch_feedback_audit_events >= 2
                    and batch_positive_delta > 0.0
                    and batch_negative_delta < 0.0
                    and deleted == 1
                    and cache_keys_after_forget == 0
                    and no_stale_after_forget
                    and success_rate == 1.0
                    and cache_hits >= requests
                    and batch_ok
                    and individual_ok == batch_size
                    and request_reduction_ratio >= 0.9
                    and warm_vector_misses >= batch_size
                    and individual_vector_hits >= batch_size
                    and batch_vector_hits >= batch_size
                ),
            }
            return result
        finally:
            stop_workers(worker_processes)
            redis_delete_prefix(client, redis_prefix)


def _redact_redis_url(url: str) -> str:
    if "@" not in url:
        return url
    scheme, tail = url.split("://", 1)
    return f"{scheme}://***@{tail.split('@', 1)[1]}"


def enforce_slo(
    result: dict[str, Any],
    *,
    min_success_rate: float,
    max_p99_ms: float,
) -> list[str]:
    failures: list[str] = []
    if not result.get("ok"):
        failures.append("benchmark ok flag is false")
    if float(result.get("success_rate", 0.0)) < min_success_rate:
        failures.append(
            f"success_rate {result.get('success_rate')} < required {min_success_rate}"
        )
    if float(result.get("p99_latency_ms", float("inf"))) > max_p99_ms:
        failures.append(
            f"p99_latency_ms {result.get('p99_latency_ms')} > allowed {max_p99_ms}"
        )
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a real Redis + multi-process FastAPI cache load profile."
    )
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("WAVEMIND_REDIS_URL", "redis://127.0.0.1:6379/0"),
    )
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--base-port", type=int, default=8210)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-slo", action="store_true")
    parser.add_argument("--min-success-rate", type=float, default=1.0)
    parser.add_argument("--max-p99-ms", type=float, default=1000.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_benchmark(
            redis_url=args.redis_url,
            workers=args.workers,
            requests=args.requests,
            batch_size=args.batch_size,
            base_port=args.base_port,
            timeout_seconds=args.timeout,
        )
    except (RuntimeError, TimeoutError, URLError) as exc:
        print(f"redis API load benchmark failed: {exc}", file=sys.stderr)
        return 2

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.fail_on_slo:
        failures = enforce_slo(
            result,
            min_success_rate=args.min_success_rate,
            max_p99_ms=args.max_p99_ms,
        )
        if failures:
            for failure in failures:
                print(f"SLO failure: {failure}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
