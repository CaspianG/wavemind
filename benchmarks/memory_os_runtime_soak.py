from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from wavemind import (
    HashingTextEncoder,
    MemoryOSWorker,
    RedisMemoryOSJobGuard,
    RedisMemoryOSLock,
    WaveMind,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_ref() -> str:
    value = os.getenv("GITHUB_SHA") or os.getenv("WAVEMIND_BENCHMARK_SOURCE_REF")
    if value:
        return value[:12]
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def redis_environment(redis_url: str) -> str:
    host = (urlparse(redis_url).hostname or "").lower()
    return "local_redis" if host in {"127.0.0.1", "localhost", "::1"} else "remote_redis"


def run_runtime_soak(
    *,
    redis_url: str,
    rounds: int = 20,
    contenders: int = 4,
) -> dict[str, Any]:
    if rounds <= 0:
        raise ValueError("rounds must be positive")
    if contenders < 2:
        raise ValueError("contenders must be at least 2")
    try:
        import redis
    except ImportError as exc:
        raise RuntimeError('Install Redis support with: pip install "wavemind[redis]"') from exc

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    client.ping()
    prefix = f"wavemind:memory-os:soak:{uuid.uuid4().hex}"
    started = time.perf_counter()
    completed_runs = 0
    duplicate_skips = 0
    lock_skips = 0
    retry_deltas: list[float] = []
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="wavemind-memory-os-soak-") as tmp:
        db_path = Path(tmp) / "memory.sqlite3"
        seed = WaveMind(
            db_path=db_path,
            encoder=HashingTextEncoder(vector_dim=64),
            width=16,
            height=16,
            layers=1,
            audit_queries=True,
        )
        memory_id = seed.remember(
            "The production user prefers concise incident summaries",
            namespace="soak",
            priority=1.0,
        )
        seed.query("incident summaries", namespace="soak", top_k=1)
        seed.query("incident summaries", namespace="soak", top_k=1)
        seed.close()

        def attempt(round_index: int, contender_index: int) -> dict[str, Any]:
            memory = WaveMind(
                db_path=db_path,
                encoder=HashingTextEncoder(vector_dim=64),
                width=16,
                height=16,
                layers=1,
                audit_queries=True,
            )
            try:
                report = MemoryOSWorker(memory).run_once(
                    namespace="soak",
                    consolidate_steps=0,
                    consolidate_concepts=False,
                    adaptive_forgetting=False,
                    predictive_prefetch=False,
                    priority_boost_per_hit=0.01,
                    max_priority_boost=10.0,
                    lock=RedisMemoryOSLock(
                        client,
                        key=f"{prefix}:lock",
                        ttl_seconds=5,
                        heartbeat_interval_seconds=0.25,
                        owner=f"round-{round_index}-worker-{contender_index}",
                    ),
                    lock_required=True,
                    job_guard=RedisMemoryOSJobGuard(
                        client,
                        key=f"{prefix}:job:{round_index}",
                        ttl_seconds=3600,
                        owner=f"round-{round_index}-worker-{contender_index}",
                    ),
                )
                return report.as_dict()
            finally:
                memory.close()

        for round_index in range(rounds):
            with ThreadPoolExecutor(max_workers=contenders) as pool:
                futures = [pool.submit(attempt, round_index, index) for index in range(contenders)]
                reports = []
                for future in futures:
                    try:
                        reports.append(future.result(timeout=30))
                    except Exception as exc:
                        errors.append(f"round {round_index}: {exc}")

            completed = [item for item in reports if item["idempotency"]["completed"]]
            completed_runs += len(completed)
            duplicate_skips += sum(
                "duplicate_job_skipped" in item["actions"] for item in reports
            )
            lock_skips += sum("lock_skipped" in item["actions"] for item in reports)
            if len(completed) != 1:
                errors.append(f"round {round_index}: expected one completion, got {len(completed)}")

            before_retry = WaveMind(
                db_path=db_path,
                encoder=HashingTextEncoder(vector_dim=64),
                width=16,
                height=16,
                layers=1,
            )
            priority_before = before_retry.store.get(memory_id).priority
            before_retry.close()
            retry_report = attempt(round_index, contenders + 1)
            after_retry = WaveMind(
                db_path=db_path,
                encoder=HashingTextEncoder(vector_dim=64),
                width=16,
                height=16,
                layers=1,
            )
            priority_after = after_retry.store.get(memory_id).priority
            after_retry.close()
            retry_deltas.append(abs(priority_after - priority_before))
            if "duplicate_job_skipped" not in retry_report["actions"]:
                errors.append(f"round {round_index}: completed job retry was not skipped")

    lease = RedisMemoryOSLock(
        client,
        key=f"{prefix}:lease",
        ttl_seconds=1,
        heartbeat_interval_seconds=0.1,
        owner="lease-holder",
    )
    lease.acquire()
    lease.start_heartbeat()
    time.sleep(1.25)
    contender = RedisMemoryOSLock(
        client,
        key=f"{prefix}:lease",
        ttl_seconds=1,
        heartbeat_interval_seconds=0.1,
        owner="lease-contender",
    )
    heartbeat_protected = not contender.acquire() and lease.refresh_count >= 5
    lease_released = lease.release()
    post_release_acquired = contender.acquire()
    contender.release()

    failed_guard = RedisMemoryOSJobGuard(
        client,
        key=f"{prefix}:failed-job",
        owner="failed-attempt",
    )
    failed_guard.claim()
    failed_receipt_removed = failed_guard.fail()
    retry_guard = RedisMemoryOSJobGuard(
        client,
        key=f"{prefix}:failed-job",
        owner="retry-attempt",
    )
    failed_job_retryable = retry_guard.claim()
    retry_guard.fail()

    wrong_owner = RedisMemoryOSLock(
        client,
        key=f"{prefix}:ownership",
        ttl_seconds=30,
        owner="original-owner",
    )
    wrong_owner.acquire()
    client.set(wrong_owner.key, "replacement-owner", ex=30)
    wrong_owner_release_rejected = not wrong_owner.release()
    replacement_preserved = client.get(wrong_owner.key) == "replacement-owner"

    for key in client.scan_iter(match=f"{prefix}:*"):
        client.delete(key)

    checks = [
        {"id": "real-redis", "passed": True},
        {
            "id": "single-flight",
            "passed": completed_runs == rounds and not errors,
        },
        {
            "id": "duplicate-job-no-mutation",
            "passed": max(retry_deltas, default=0.0) == 0.0,
        },
        {
            "id": "lease-heartbeat",
            "passed": heartbeat_protected and lease_released and post_release_acquired,
        },
        {
            "id": "failed-job-retry",
            "passed": failed_receipt_removed and failed_job_retryable,
        },
        {
            "id": "atomic-owner-release",
            "passed": wrong_owner_release_rejected and replacement_preserved,
        },
    ]
    passed = all(item["passed"] for item in checks)
    return {
        "schema": "wavemind.memory_os_runtime_soak.v1",
        "generated_at": _utc_now(),
        "source_ref": _source_ref(),
        "status": "pass" if passed else "fail",
        "environment": redis_environment(redis_url),
        "claim_boundary": (
            "This is a real Redis worker concurrency and retry soak. Local Redis results prove "
            "runtime semantics but do not by themselves admit a remote production deployment."
        ),
        "config": {"rounds": rounds, "contenders": contenders},
        "metrics": {
            "duration_seconds": round(time.perf_counter() - started, 3),
            "completed_runs": completed_runs,
            "duplicate_skips": duplicate_skips,
            "lock_skips": lock_skips,
            "retry_mutation_delta_max": max(retry_deltas, default=0.0),
            "lease_refresh_count": lease.refresh_count,
            "error_count": len(errors),
        },
        "checks": checks,
        "errors": errors,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    metrics = payload["metrics"]
    lines = [
        "# WaveMind Memory OS Runtime Soak",
        "",
        payload["claim_boundary"],
        "",
        "| metric | value |",
        "|---|---:|",
        f"| status | `{payload['status']}` |",
        f"| environment | `{payload['environment']}` |",
        f"| rounds | `{payload['config']['rounds']}` |",
        f"| contenders | `{payload['config']['contenders']}` |",
        f"| completed runs | `{metrics['completed_runs']}` |",
        f"| duplicate skips | `{metrics['duplicate_skips']}` |",
        f"| lock skips | `{metrics['lock_skips']}` |",
        f"| max retry mutation delta | `{metrics['retry_mutation_delta_max']}` |",
        f"| lease refreshes | `{metrics['lease_refresh_count']}` |",
        f"| duration seconds | `{metrics['duration_seconds']}` |",
        "",
        "## Checks",
        "",
        "| check | result |",
        "|---|---|",
    ]
    lines.extend(
        f"| `{item['id']}` | `{'pass' if item['passed'] else 'fail'}` |"
        for item in payload["checks"]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-url", default=os.getenv("WAVEMIND_REDIS_URL"))
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--contenders", type=int, default=4)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/memory_os_runtime_soak_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/MEMORY_OS_RUNTIME_SOAK.md"),
    )
    args = parser.parse_args()
    if not args.redis_url:
        parser.error("--redis-url or WAVEMIND_REDIS_URL is required")
    payload = run_runtime_soak(
        redis_url=args.redis_url,
        rounds=args.rounds,
        contenders=args.contenders,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["metrics"], indent=2))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
