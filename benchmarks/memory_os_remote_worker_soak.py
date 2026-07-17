from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.memory_os_runtime_soak import redis_environment, run_runtime_soak
from wavemind.memory_os_admission import (
    evaluate_memory_os_admission,
    render_memory_os_admission_markdown,
)


JsonRequest = Callable[[str, str, str, dict[str, Any] | None, str | None, float], dict[str, Any]]
RedisSoak = Callable[..., dict[str, Any]]

PRODUCTION_MIN_DURATION_SECONDS = 6 * 60 * 60
PRODUCTION_MIN_WORKER_CYCLES = 500


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_ref() -> str:
    value = os.getenv("GITHUB_SHA") or os.getenv("WAVEMIND_BENCHMARK_SOURCE_REF")
    if value:
        return value
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _split_worker_urls(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for raw in values or []:
        for value in raw.split(","):
            normalized = value.strip().rstrip("/")
            if normalized and normalized not in result:
                result.append(normalized)
    return result


def _is_loopback(host: str | None) -> bool:
    return (host or "").lower() in {"127.0.0.1", "localhost", "::1"}


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _check(
    check_id: str,
    title: str,
    passed: bool,
    evidence: str,
    action: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "title": title,
        "passed": bool(passed),
        "evidence": evidence,
        "action": action,
    }


def build_preflight(
    *,
    worker_urls: list[str] | None,
    redis_url: str | None,
    api_key_present: bool,
    allow_insecure_http: bool = False,
    allow_insecure_redis: bool = False,
) -> dict[str, Any]:
    workers = _split_worker_urls(worker_urls)
    parsed_workers = [urlparse(value) for value in workers]
    worker_hosts = [item.hostname or "" for item in parsed_workers]
    worker_netlocs = [item.netloc.lower() for item in parsed_workers if item.netloc]
    worker_urls_valid = bool(workers) and all(
        item.scheme in {"http", "https"} and bool(item.hostname) for item in parsed_workers
    )
    workers_remote = worker_urls_valid and all(not _is_loopback(host) for host in worker_hosts)
    distinct_workers = len(set(worker_netlocs)) >= 2
    worker_transport_secure = worker_urls_valid and (
        allow_insecure_http or all(item.scheme == "https" for item in parsed_workers)
    )

    parsed_redis = urlparse(redis_url or "")
    redis_valid = parsed_redis.scheme in {"redis", "rediss"} and bool(parsed_redis.hostname)
    redis_remote = redis_valid and redis_environment(redis_url or "") == "remote_redis"
    redis_transport_secure = redis_valid and (
        allow_insecure_redis or parsed_redis.scheme == "rediss"
    )

    checks = [
        _check(
            "worker-endpoints",
            "At least two distinct worker endpoints are declared",
            worker_urls_valid and distinct_workers,
            f"workers={len(workers)}, distinct_netlocs={len(set(worker_netlocs))}",
            "Set WAVEMIND_REMOTE_WORKER_URLS to at least two direct worker endpoints.",
        ),
        _check(
            "non-loopback-workers",
            "Worker endpoints are outside the benchmark runner",
            workers_remote,
            f"remote={workers_remote}",
            "Use routable production-like worker endpoints, not localhost.",
        ),
        _check(
            "worker-transport",
            "Worker transport is encrypted",
            worker_transport_secure,
            f"https={all(item.scheme == 'https' for item in parsed_workers) if parsed_workers else False}, allow_insecure={allow_insecure_http}",
            "Use HTTPS worker endpoints or explicitly allow insecure transport only in an isolated staging network.",
        ),
        _check(
            "remote-redis",
            "Redis is remote from the benchmark runner",
            redis_remote,
            f"configured={redis_valid}, environment={redis_environment(redis_url or '') if redis_valid else 'missing'}",
            "Set WAVEMIND_REMOTE_REDIS_URL to the Redis used by every target worker.",
        ),
        _check(
            "redis-transport",
            "Redis transport is encrypted",
            redis_transport_secure,
            f"rediss={parsed_redis.scheme == 'rediss'}, allow_insecure={allow_insecure_redis}",
            "Use rediss:// or explicitly allow insecure Redis only in an isolated staging network.",
        ),
        _check(
            "admin-auth",
            "An admin API key is available for the destructive soak namespace",
            api_key_present,
            f"api_key_present={api_key_present}",
            "Set WAVEMIND_API_KEY to an admin-scoped key for the target workers.",
        ),
    ]
    passed = all(item["passed"] for item in checks)
    return {
        "schema": "wavemind.memory_os_remote_worker_preflight.v1",
        "generated_at": _utc_now(),
        "source_ref": _source_ref(),
        "status": "pass" if passed else "action_required",
        "claim_boundary": (
            "This preflight only validates a production-like remote topology contract. "
            "It does not admit Memory OS until the remote worker soak itself passes."
        ),
        "topology": {
            "worker_count": len(workers),
            "distinct_worker_count": len(set(worker_netlocs)),
            "worker_fingerprints": [_fingerprint(value) for value in worker_netlocs],
            "redis_fingerprint": (
                _fingerprint(f"{parsed_redis.hostname}:{parsed_redis.port or 6379}")
                if redis_valid
                else None
            ),
            "worker_https": bool(parsed_workers) and all(item.scheme == "https" for item in parsed_workers),
            "redis_tls": parsed_redis.scheme == "rediss",
        },
        "checks": checks,
        "missing_check_ids": [item["id"] for item in checks if not item["passed"]],
        "required_environment": [
            "WAVEMIND_REMOTE_WORKER_URLS",
            "WAVEMIND_REMOTE_REDIS_URL",
            "WAVEMIND_API_KEY",
        ],
        "worker_required_environment": ["WAVEMIND_COMMIT_SHA"],
        "handoff": {
            "workflow": ".github/workflows/memory-os-remote-soak.yml",
            "github_secret_scope": "repository_actions_secrets",
            "workflow_runner": ["self-hosted", "linux", "wavemind-evidence"],
            "command": "gh workflow run memory-os-remote-soak.yml --ref main -f cycles=500 -f contenders=4",
            "contract": {
                "min_duration_seconds": PRODUCTION_MIN_DURATION_SECONDS,
                "min_worker_cycles": PRODUCTION_MIN_WORKER_CYCLES,
                "max_evidence_age_seconds": 86_400,
                "worker_commit_must_match": True,
                "allowed_error_rate": 0.0,
            },
            "expected_artifacts": [
                "memory_os_remote_worker_soak_results.json",
                "MEMORY_OS_REMOTE_WORKER_SOAK.md",
                "memory_os_admission_results.json",
                "MEMORY_OS_ADMISSION.md",
            ],
        },
    }


def _request_json(
    base_url: str,
    path: str,
    method: str,
    payload: dict[str, Any] | None,
    api_key: str | None,
    timeout: float,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc


def _report_summary(report: dict[str, Any]) -> dict[str, Any]:
    lock = report.get("lock") or {}
    idempotency = report.get("idempotency") or {}
    mutation_count = sum(
        int(report.get(name) or 0)
        for name in (
            "expired_purged",
            "consolidated_steps",
            "concepts_created",
            "priority_predictions",
            "forgetting_demotions",
        )
    ) + int(bool(report.get("index_rebuilt")))
    return {
        "ok": bool(report.get("ok")),
        "actions": list(report.get("actions") or []),
        "lock_required": bool(lock.get("required")),
        "lock_acquired": bool(lock.get("acquired")),
        "lock_released": bool(lock.get("released")),
        "lease_lost": bool(lock.get("lease_lost")),
        "job_claimed": bool(idempotency.get("claimed")),
        "job_completed": bool(idempotency.get("completed")),
        "job_in_doubt": bool(idempotency.get("in_doubt")),
        "job_reason": idempotency.get("reason"),
        "mutation_count": mutation_count,
    }


def run_remote_worker_soak(
    *,
    worker_urls: list[str],
    redis_url: str,
    api_key: str,
    rounds: int = 10,
    min_duration_seconds: float = 0.0,
    min_worker_cycles: int = 1,
    contenders: int = 4,
    timeout: float = 30.0,
    allow_insecure_http: bool = False,
    allow_insecure_redis: bool = False,
    request_json: JsonRequest | None = None,
    redis_soak: RedisSoak | None = None,
) -> dict[str, Any]:
    if rounds <= 0:
        raise ValueError("rounds must be positive")
    if contenders < 2:
        raise ValueError("contenders must be at least 2")
    if min_duration_seconds < 0:
        raise ValueError("min_duration_seconds cannot be negative")
    if min_worker_cycles <= 0:
        raise ValueError("min_worker_cycles must be positive")
    worker_cycles = max(rounds, min_worker_cycles)
    workers = _split_worker_urls(worker_urls)
    request_json = request_json or _request_json
    redis_soak = redis_soak or run_runtime_soak
    preflight = build_preflight(
        worker_urls=workers,
        redis_url=redis_url,
        api_key_present=bool(api_key),
        allow_insecure_http=allow_insecure_http,
        allow_insecure_redis=allow_insecure_redis,
    )
    if preflight["status"] != "pass":
        return {
            "schema": "wavemind.memory_os_remote_worker_soak.v1",
            "generated_at": _utc_now(),
            "source_ref": _source_ref(),
            "status": "action_required",
            "environment": "remote_worker_cluster",
            "preflight": preflight,
            "checks": preflight["checks"],
            "errors": ["Remote worker preflight did not pass."],
        }

    started = time.perf_counter()
    soak_started = started
    soak_started_at = _utc_now()
    source_ref = _source_ref()
    run_id = uuid.uuid4().hex
    namespace = f"evidence:memory-os:{run_id}"
    errors: list[str] = []
    seeded: list[tuple[str, int, str]] = []
    health: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    round_reports: list[dict[str, Any]] = []
    raw_plans: list[dict[str, Any]] = []
    completed_runs = 0
    duplicate_retries = 0
    safe_skips = 0
    job_request_attempts = 0
    job_request_failures = 0
    lock_breach_count = 0
    duplicate_mutation_count = 0
    state_corruption_count = 0
    metrics_lock = Lock()

    try:
        redis_semantics = redis_soak(
            redis_url=redis_url,
            rounds=max(5, min(worker_cycles, 20)),
            contenders=contenders,
        )
    except Exception as exc:
        errors.append(f"remote Redis semantics: {exc}")
        redis_semantics = {
            "schema": "wavemind.memory_os_runtime_soak.v1",
            "status": "fail",
            "environment": redis_environment(redis_url),
            "checks": [],
            "errors": [str(exc)],
        }

    try:
        for index, worker in enumerate(workers):
            try:
                health_payload = request_json(worker, "/healthz", "GET", None, None, timeout)
                health.append(
                    {
                        "worker": preflight["topology"]["worker_fingerprints"][index],
                        "status": health_payload.get("status"),
                        "version": health_payload.get("version"),
                        "commit_sha": health_payload.get("commit_sha"),
                    }
                )
                seed_text = (
                    f"Remote Memory OS worker {index} sentinel {run_id} "
                    "prefers concise incident summaries"
                )
                remembered = request_json(
                    worker,
                    "/remember",
                    "POST",
                    {
                        "text": seed_text,
                        "namespace": namespace,
                        "tags": ["memory-os-remote-soak"],
                        "metadata": {"soak_run_id": run_id, "worker_index": index},
                        "ttl_seconds": max(86_400.0, min_duration_seconds + 3_600.0),
                    },
                    api_key,
                    timeout,
                )
                memory_id = int(remembered["id"])
                seeded.append((worker, memory_id, seed_text))
                for _ in range(2):
                    request_json(
                        worker,
                        "/query",
                        "POST",
                        {"text": "concise incident summaries", "namespace": namespace, "top_k": 1},
                        api_key,
                        timeout,
                    )
                plan = request_json(
                    worker,
                    "/memory-os/plan",
                    "POST",
                    {
                        "namespace": namespace,
                        "target_memories": 50_000,
                        "namespace_count": 64,
                        "node_count": max(3, len(workers)),
                        "deployment": "production",
                        "cache_mode": "redis",
                    },
                    api_key,
                    timeout,
                )
                raw_plans.append(plan)
                execution = plan.get("execution_plan") or {}
                plans.append(
                    {
                        "worker": preflight["topology"]["worker_fingerprints"][index],
                        "safe_to_run": bool(execution.get("safe_to_run")),
                        "requires_shared_cache": bool(execution.get("requires_shared_cache")),
                        "requires_distributed_lock": bool(execution.get("requires_distributed_lock")),
                        "blocked_task_ids": list(execution.get("blocked_task_ids") or []),
                    }
                )
            except Exception as exc:
                errors.append(f"worker {index} setup: {exc}")

        soak_started = time.perf_counter()
        soak_started_at = _utc_now()
        for round_index in range(worker_cycles):
            idempotency_key = f"remote-soak:{run_id}:{round_index}"
            request_payload = {
                "namespace": namespace,
                "consolidate_steps": 0,
                "consolidate_concepts": False,
                "adaptive_forgetting": False,
                "predictive_prefetch": False,
                "architecture_advice": False,
                "priority_boost_per_hit": 0.01,
                "max_priority_boost": 10.0,
                "lock_required": True,
                "lock_ttl_seconds": 30,
                "lock_prefix": f"wavemind:memory-os:remote-soak:{run_id}",
                "idempotency_key": idempotency_key,
                "idempotency_prefix": f"wavemind:memory-os:remote-soak:job:{run_id}",
            }

            def attempt(contender_index: int) -> dict[str, Any]:
                nonlocal job_request_attempts, job_request_failures
                worker = workers[contender_index % len(workers)]
                with metrics_lock:
                    job_request_attempts += 1
                try:
                    return request_json(
                        worker,
                        "/memory-os/run",
                        "POST",
                        request_payload,
                        api_key,
                        timeout,
                    )
                except Exception:
                    with metrics_lock:
                        job_request_failures += 1
                    raise

            reports: list[dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=contenders) as pool:
                futures = [pool.submit(attempt, index) for index in range(contenders)]
                for future in futures:
                    try:
                        reports.append(future.result(timeout=timeout + 5))
                    except Exception as exc:
                        errors.append(f"round {round_index}: {exc}")

            summaries = [_report_summary(report) for report in reports]
            completed = [item for item in summaries if item["job_completed"]]
            completed_runs += len(completed)
            safe_skips += sum(
                bool({"lock_skipped", "duplicate_job_skipped"}.intersection(item["actions"]))
                for item in summaries
                if not item["job_completed"]
            )
            if len(completed) != 1:
                lock_breach_count += 1
                errors.append(f"round {round_index}: expected one completed job, got {len(completed)}")
            if any(item["job_in_doubt"] or item["lease_lost"] for item in summaries):
                lock_breach_count += 1
                errors.append(f"round {round_index}: in-doubt job or lost lease observed")

            try:
                job_request_attempts += 1
                retry = _report_summary(
                    request_json(
                        workers[(round_index + 1) % len(workers)],
                        "/memory-os/run",
                        "POST",
                        request_payload,
                        api_key,
                        timeout,
                    )
                )
                if "duplicate_job_skipped" in retry["actions"] and not retry["job_in_doubt"]:
                    duplicate_retries += 1
                    if retry["mutation_count"]:
                        duplicate_mutation_count += retry["mutation_count"]
                        errors.append(
                            f"round {round_index}: duplicate retry mutated state "
                            f"({retry['mutation_count']} mutations)"
                        )
                else:
                    errors.append(f"round {round_index}: completed retry was not safely skipped")
            except Exception as exc:
                job_request_failures += 1
                retry = {"actions": [], "job_in_doubt": True}
                errors.append(f"round {round_index} retry: {exc}")

            for sentinel_worker, sentinel_id, sentinel_text in seeded:
                try:
                    sentinel = request_json(
                        sentinel_worker,
                        "/query",
                        "POST",
                        {"text": sentinel_text, "namespace": namespace, "top_k": 1},
                        api_key,
                        timeout,
                    )
                    results = (
                        sentinel
                        if isinstance(sentinel, list)
                        else sentinel.get("results") or []
                    )
                    if not results or int(results[0].get("id") or -1) != sentinel_id:
                        state_corruption_count += 1
                        errors.append(
                            f"round {round_index}: sentinel {sentinel_id} was not recalled intact"
                        )
                except Exception as exc:
                    state_corruption_count += 1
                    errors.append(f"round {round_index}: sentinel {sentinel_id} check failed: {exc}")
            round_reports.append(
                {
                    "round": round_index,
                    "completed": len(completed),
                    "safe_skips": sum(
                        bool({"lock_skipped", "duplicate_job_skipped"}.intersection(item["actions"]))
                        for item in summaries
                        if not item["job_completed"]
                    ),
                    "retry_duplicate_skipped": "duplicate_job_skipped" in retry["actions"],
                    "retry_mutations": int(retry.get("mutation_count") or 0),
                }
            )
            target_elapsed = min_duration_seconds * (round_index + 1) / worker_cycles
            remaining = target_elapsed - (time.perf_counter() - soak_started)
            if remaining > 0:
                time.sleep(remaining)
    finally:
        for worker, memory_id, _ in seeded:
            try:
                forgotten = request_json(
                    worker,
                    "/forget",
                    "DELETE",
                    {"id": memory_id, "namespace": namespace},
                    api_key,
                    timeout,
                )
                if int(forgotten.get("deleted") or 0) != 1:
                    errors.append(f"cleanup memory {memory_id}: deleted={forgotten.get('deleted')}")
            except Exception as exc:
                errors.append(f"cleanup memory {memory_id}: {exc}")

    health_ok = len(health) == len(workers) and all(item["status"] == "ok" for item in health)
    versions = {item["version"] for item in health}
    commits = {str(item.get("commit_sha") or "") for item in health}
    worker_commit_ok = len(commits) == 1 and commits == {source_ref}
    plans_ok = len(plans) == len(workers) and all(
        item["safe_to_run"]
        and item["requires_shared_cache"]
        and item["requires_distributed_lock"]
        and not item["blocked_task_ids"]
        for item in plans
    )
    redis_checks = redis_semantics.get("checks") or []
    redis_semantics_ok = (
        redis_semantics.get("status") == "pass"
        and redis_semantics.get("environment") == "remote_redis"
        and bool(redis_checks)
        and all(item.get("passed") for item in redis_checks)
    )
    duration_seconds = time.perf_counter() - soak_started
    error_rate = job_request_failures / job_request_attempts if job_request_attempts else 1.0
    finished_at = _utc_now()
    checks = [
        _check("remote-topology", "Remote topology preflight passes", True, "preflight=pass", "Fix preflight blockers."),
        _check("worker-health", "Every remote worker is healthy", health_ok, f"healthy={sum(item['status'] == 'ok' for item in health)}/{len(workers)}", "Repair unhealthy workers."),
        _check("worker-version", "Every worker runs one version", len(versions) == 1, f"versions={sorted(str(value) for value in versions)}", "Complete the rolling deployment before the soak."),
        _check("worker-commit", "Every worker runs the benchmark commit", worker_commit_ok, f"expected={source_ref}, commits={sorted(commits)}", "Deploy the exact commit under test and set WAVEMIND_COMMIT_SHA on every worker."),
        _check("worker-plan", "Every worker emits a safe Redis and lock plan", plans_ok, f"safe={sum(item['safe_to_run'] for item in plans)}/{len(workers)}", "Fix worker plan blockers before mutation."),
        _check("remote-redis-semantics", "Remote Redis passes lease and retry semantics", redis_semantics_ok, f"status={redis_semantics.get('status')}, environment={redis_semantics.get('environment')}", "Run against the Redis used by every worker."),
        _check("soak-duration", "The configured soak duration is completed", duration_seconds >= min_duration_seconds, f"duration_seconds={duration_seconds:.3f}, required={min_duration_seconds:.3f}", "Run the soak for the full configured duration."),
        _check("worker-cycles", "Every configured worker cycle completes", completed_runs == worker_cycles, f"completed={completed_runs}, required={worker_cycles}", "Run every configured worker cycle."),
        _check("cross-worker-single-flight", "Exactly one worker completes each run id", completed_runs == worker_cycles, f"completed={completed_runs}, cycles={worker_cycles}", "Fix shared lock or idempotency wiring."),
        _check("cross-worker-retry", "Completed jobs are skipped on another worker", duplicate_retries == worker_cycles, f"duplicate_retries={duplicate_retries}, cycles={worker_cycles}", "Fix shared job receipts."),
        _check("error-rate", "Worker request error rate stays at zero", error_rate == 0.0, f"failures={job_request_failures}, attempts={job_request_attempts}, rate={error_rate:.6f}", "Repair worker or network errors and restart the soak."),
        _check("lock-safety", "No lock breach is observed", lock_breach_count == 0, f"lock_breach_count={lock_breach_count}", "Fix cross-worker lease and single-flight semantics."),
        _check("duplicate-mutation-safety", "Duplicate retries never mutate state", duplicate_mutation_count == 0, f"duplicate_mutation_count={duplicate_mutation_count}", "Make completed-job retries side-effect free."),
        _check("state-integrity", "Sentinel memories remain intact through every cycle", state_corruption_count == 0, f"state_corruption_count={state_corruption_count}", "Investigate state corruption before production admission."),
        _check("no-in-doubt-jobs", "No lease loss or in-doubt receipt is observed", not any("in-doubt" in item or "lost lease" in item for item in errors), f"errors={len(errors)}", "Inspect lease heartbeat and worker termination behavior."),
        _check("cleanup", "All seeded soak memories are removed", not any(item.startswith("cleanup") for item in errors), f"seeded={len(seeded)}", "Remove the isolated soak namespace manually."),
    ]
    passed = all(item["passed"] for item in checks) and not errors
    return {
        "schema": "wavemind.memory_os_remote_worker_soak.v1",
        "generated_at": finished_at,
        "started_at": soak_started_at,
        "finished_at": finished_at,
        "source_ref": source_ref,
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "workflow_run_url": (
            f"https://github.com/{os.getenv('GITHUB_REPOSITORY')}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"
            if os.getenv("GITHUB_REPOSITORY") and os.getenv("GITHUB_RUN_ID")
            else None
        ),
        "status": "pass" if passed else "fail",
        "environment": "remote_worker_cluster",
        "claim_boundary": (
            "This evidence combines direct remote worker HTTP concurrency with lease and job-receipt "
            "semantics against the same non-loopback Redis. It admits only this tested worker topology."
        ),
        "preflight": preflight,
        "config": {
            "requested_rounds": rounds,
            "worker_cycles": worker_cycles,
            "min_duration_seconds": min_duration_seconds,
            "min_worker_cycles": min_worker_cycles,
            "contenders": contenders,
            "timeout_seconds": timeout,
        },
        "metrics": {
            "duration_seconds": round(duration_seconds, 3),
            "worker_cycles": worker_cycles,
            "worker_count": len(workers),
            "completed_runs": completed_runs,
            "safe_skips": safe_skips,
            "duplicate_retries": duplicate_retries,
            "job_request_attempts": job_request_attempts,
            "job_request_failures": job_request_failures,
            "error_rate": error_rate,
            "lock_breach_count": lock_breach_count,
            "duplicate_mutation_count": duplicate_mutation_count,
            "state_corruption_count": state_corruption_count,
            "error_count": len(errors),
        },
        "health": health,
        "plans": plans,
        "sample_plan": raw_plans[0] if raw_plans else None,
        "rounds": round_reports,
        "redis_semantics": redis_semantics,
        "checks": checks,
        "errors": errors,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# WaveMind Remote Memory OS Worker Soak",
        "",
        payload.get("claim_boundary") or payload.get("preflight", {}).get("claim_boundary", ""),
        "",
        f"Status: `{payload['status']}`",
        "",
        "## Checks",
        "",
        "| check | result | evidence |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| `{item['id']}` | `{'pass' if item['passed'] else 'action_required'}` | {item['evidence']} |"
        for item in payload.get("checks") or []
    )
    if payload.get("handoff") or payload.get("preflight", {}).get("handoff"):
        handoff = payload.get("handoff") or payload["preflight"]["handoff"]
        lines.extend(
            [
                "",
                "## Handoff",
                "",
                f"- Secret scope: `{handoff['github_secret_scope']}`",
                f"- Workflow: `{handoff['workflow']}`",
                f"- Dispatch: `{handoff['command']}`",
                f"- Minimum duration: `{(handoff.get('contract') or {}).get('min_duration_seconds', PRODUCTION_MIN_DURATION_SECONDS)}` seconds",
                f"- Minimum worker cycles: `{(handoff.get('contract') or {}).get('min_worker_cycles', PRODUCTION_MIN_WORKER_CYCLES)}`",
                "- Every worker must expose `WAVEMIND_COMMIT_SHA` matching the tested commit.",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-url", action="append", default=[])
    parser.add_argument("--redis-url", default=os.getenv("WAVEMIND_REMOTE_REDIS_URL"))
    parser.add_argument("--api-key", default=os.getenv("WAVEMIND_API_KEY"))
    parser.add_argument("--cycles", "--rounds", dest="cycles", type=int, default=PRODUCTION_MIN_WORKER_CYCLES)
    parser.add_argument(
        "--min-duration-seconds",
        type=float,
        default=PRODUCTION_MIN_DURATION_SECONDS,
    )
    parser.add_argument(
        "--min-worker-cycles",
        type=int,
        default=PRODUCTION_MIN_WORKER_CYCLES,
    )
    parser.add_argument("--contenders", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--allow-insecure-http", action="store_true")
    parser.add_argument("--allow-insecure-redis", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--fail-on-action-required", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/memory_os_remote_worker_soak_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/MEMORY_OS_REMOTE_WORKER_SOAK.md"),
    )
    parser.add_argument("--admission-output", type=Path)
    parser.add_argument("--admission-markdown-output", type=Path)
    parser.add_argument(
        "--quality-evidence",
        type=Path,
        default=Path("benchmarks/memory_os_quality_results.json"),
    )
    args = parser.parse_args()
    env_workers = os.getenv("WAVEMIND_REMOTE_WORKER_URLS", "")
    workers = _split_worker_urls([*args.worker_url, env_workers])
    if args.preflight_only:
        payload = build_preflight(
            worker_urls=workers,
            redis_url=args.redis_url,
            api_key_present=bool(args.api_key),
            allow_insecure_http=args.allow_insecure_http,
            allow_insecure_redis=args.allow_insecure_redis,
        )
    else:
        payload = run_remote_worker_soak(
            worker_urls=workers,
            redis_url=args.redis_url or "",
            api_key=args.api_key or "",
            rounds=args.cycles,
            min_duration_seconds=args.min_duration_seconds,
            min_worker_cycles=args.min_worker_cycles,
            contenders=args.contenders,
            timeout=args.timeout,
            allow_insecure_http=args.allow_insecure_http,
            allow_insecure_redis=args.allow_insecure_redis,
        )
    if payload["status"] == "pass" and payload.get("sample_plan") and args.admission_output:
        quality_evidence = (
            json.loads(args.quality_evidence.read_text(encoding="utf-8"))
            if args.quality_evidence.exists()
            else None
        )
        admission = evaluate_memory_os_admission(
            payload["sample_plan"],
            deployment="production",
            redis_url=args.redis_url,
            lock_redis_url=args.redis_url,
            runtime_evidence=payload,
            quality_evidence=quality_evidence,
            expected_commit_sha=str(payload.get("source_ref") or ""),
        )
        args.admission_output.parent.mkdir(parents=True, exist_ok=True)
        args.admission_output.write_text(json.dumps(admission, indent=2) + "\n", encoding="utf-8")
        if args.admission_markdown_output:
            args.admission_markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.admission_markdown_output.write_text(
                render_memory_os_admission_markdown(admission),
                encoding="utf-8",
            )
        if admission["status"] != "admitted":
            payload["status"] = "fail"
            payload.setdefault("errors", []).append(
                f"production admission blocked: {admission['summary']['blocker_ids']}"
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "checks": payload.get("checks")}, indent=2))
    if args.fail_on_action_required and payload["status"] != "pass":
        return 2
    return 0 if payload["status"] in {"pass", "action_required"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
