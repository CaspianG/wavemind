import importlib.util
import io
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError


SCRIPT = Path(__file__).resolve().parents[1] / "benchmarks" / "memory_os_remote_worker_soak.py"
WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "memory-os-remote-soak.yml"


def _module():
    spec = importlib.util.spec_from_file_location("memory_os_remote_worker_soak", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_remote_worker_preflight_rejects_local_or_missing_topology():
    module = _module()
    payload = module.build_preflight(
        worker_urls=["http://127.0.0.1:8000"],
        redis_url="redis://127.0.0.1:6379/0",
        api_key_present=False,
    )

    assert payload["status"] == "action_required"
    assert {
        "worker-endpoints",
        "non-loopback-workers",
        "worker-transport",
        "remote-redis",
        "redis-transport",
        "admin-auth",
    }.issubset(payload["missing_check_ids"])


def test_remote_worker_preflight_accepts_secure_distinct_workers():
    module = _module()
    payload = module.build_preflight(
        worker_urls=["https://worker-a.example", "https://worker-b.example"],
        redis_url="rediss://redis.example:6380/0",
        api_key_present=True,
    )

    assert payload["status"] == "pass"
    assert payload["topology"]["worker_count"] == 2
    assert payload["topology"]["distinct_worker_count"] == 2
    assert payload["topology"]["worker_https"] is True
    assert payload["topology"]["redis_tls"] is True
    assert payload["handoff"]["github_secret_scope"] == "repository_actions_secrets"


def test_remote_soak_is_evidence_not_a_github_deployment():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "environment: memory-os-production-evidence" not in workflow
    assert "${{ secrets.WAVEMIND_REMOTE_WORKER_URLS }}" in workflow
    assert "runs-on: [self-hosted, wavemind-evidence]" in workflow
    assert "runs-on: [self-hosted, linux, wavemind-evidence]" not in workflow
    assert "shell: bash" in workflow
    assert "actions/setup-python" not in workflow
    assert "Python 3.10+ is required" in workflow
    assert "--cold-repetitions 10" in workflow


def test_request_json_retries_transient_dns_resolution(monkeypatch):
    module = _module()
    calls = 0
    sleeps: list[float] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return b'{"status":"ok"}'

    def fake_urlopen(_request, timeout):
        nonlocal calls
        calls += 1
        assert timeout == 5.0
        if calls < 3:
            raise URLError(OSError(11001, "getaddrinfo failed"))
        return Response()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    monkeypatch.setattr(module.time, "sleep", sleeps.append)

    payload = module._request_json(
        "https://worker.example",
        "/healthz",
        "GET",
        None,
        None,
        5.0,
    )

    assert payload == {"status": "ok"}
    assert calls == 3
    assert sleeps == [0.25, 0.5]


def test_request_json_does_not_retry_http_failures(monkeypatch):
    module = _module()
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        raise HTTPError(request.full_url, 503, "unavailable", {}, io.BytesIO(b"down"))

    monkeypatch.setattr(module, "urlopen", fake_urlopen)

    try:
        module._request_json(
            "https://worker.example",
            "/healthz",
            "GET",
            None,
            None,
            5.0,
        )
    except RuntimeError as exc:
        assert "HTTP 503" in str(exc)
    else:
        raise AssertionError("HTTP failure must fail without retry")

    assert calls == 1


def test_remote_worker_soak_proves_cross_worker_single_flight_and_retry():
    module = _module()
    lock = threading.Lock()
    completed_keys: set[str] = set()
    next_memory_id = 0
    memory_by_worker: dict[str, int] = {}
    query_top_ks: dict[str, set[int]] = {}

    def request_json(base_url, path, method, payload, api_key, timeout):
        nonlocal next_memory_id
        assert base_url.startswith("https://worker-")
        assert timeout == 5.0
        if path == "/healthz":
            return {
                "status": "ok",
                "version": "2.6.0",
                "commit_sha": module._source_ref(),
            }
        assert api_key == "test-key"
        if path == "/remember":
            with lock:
                next_memory_id += 1
                memory_by_worker[base_url] = next_memory_id
                return {"id": next_memory_id}
        if path == "/query":
            query_top_ks.setdefault(base_url, set()).add(int(payload["top_k"]))
            return {"results": [{"id": memory_by_worker[base_url], "score": 1.0}]}
        if path == "/memory-os/plan":
            return {
                "deployment": "production",
                "target_memories": 50_000,
                "namespace_count": 64,
                "worker_count": 3,
                "effective_cache_mode": "redis",
                "hot_query_count": 4,
                "enabled_task_ids": [
                    "memory-os",
                    "cache-prewarm",
                    "predictive-prefetch",
                    "adaptive-forgetting",
                    "consolidation",
                    "maintenance",
                    "architecture-advice",
                ],
                "tasks": [
                    {"id": value}
                    for value in [
                        "memory-os",
                        "cache-prewarm",
                        "predictive-prefetch",
                        "adaptive-forgetting",
                        "consolidation",
                        "maintenance",
                        "architecture-advice",
                    ]
                ],
                "required_infrastructure": [
                    "Redis-compatible shared hot-query cache",
                    "distributed worker lock or single-flight scheduler",
                    "durable queue or Kubernetes CronJobs",
                    "OpenTelemetry metrics for worker duration, errors, and warmed queries",
                ],
                "policy_manifest": {
                    "decision_ids": [
                        "prefetch-policy",
                        "priority-policy",
                        "forgetting-policy",
                        "consolidation-policy",
                        "scale-policy",
                        "coordination-policy",
                    ]
                },
                "execution_plan": {
                    "safe_to_run": True,
                    "blocked_task_ids": [],
                    "requires_shared_cache": True,
                    "requires_distributed_lock": True,
                    "state_mutating_task_ids": [],
                    "singleton_task_ids": [],
                    "steps": [],
                },
                "architecture_advice": {"status": "ok"},
            }
        if path == "/memory-os/run":
            key = payload["idempotency_key"]
            with lock:
                first = key not in completed_keys
                completed_keys.add(key)
            if first:
                return {
                    "ok": True,
                    "actions": ["memory_os_completed"],
                    "lock": {
                        "required": True,
                        "acquired": True,
                        "released": True,
                        "lease_lost": False,
                    },
                    "idempotency": {
                        "claimed": True,
                        "completed": True,
                        "in_doubt": False,
                        "reason": None,
                    },
                }
            return {
                "ok": True,
                "actions": ["duplicate_job_skipped"],
                "lock": {
                    "required": True,
                    "acquired": False,
                    "released": False,
                    "lease_lost": False,
                },
                "idempotency": {
                    "claimed": False,
                    "completed": False,
                    "in_doubt": False,
                    "reason": "completed",
                },
            }
        if path == "/forget":
            return {"deleted": 1}
        raise AssertionError(f"unexpected request: {method} {path}")

    def redis_soak(**kwargs):
        assert kwargs["redis_url"].startswith("rediss://")
        return {
            "schema": "wavemind.memory_os_runtime_soak.v1",
            "status": "pass",
            "environment": "remote_redis",
            "checks": [{"id": "single-flight", "passed": True}],
        }

    payload = module.run_remote_worker_soak(
        worker_urls=["https://worker-a.example", "https://worker-b.example"],
        redis_url="rediss://redis.example:6380/0",
        api_key="test-key",
        rounds=3,
        min_duration_seconds=0,
        min_worker_cycles=1,
        contenders=4,
        timeout=5.0,
        request_json=request_json,
        redis_soak=redis_soak,
    )

    assert payload["status"] == "pass"
    assert payload["metrics"]["completed_runs"] == 3
    assert payload["metrics"]["duplicate_retries"] == 3
    assert payload["metrics"]["error_count"] == 0
    assert payload["metrics"]["worker_cycles"] == 3
    assert payload["metrics"]["lock_breach_count"] == 0
    assert payload["metrics"]["duplicate_mutation_count"] == 0
    assert payload["metrics"]["state_corruption_count"] == 0
    assert payload["sample_plan"]["hot_query_count"] == 4
    assert all({1, 2}.issubset(values) for values in query_top_ks.values())
    assert all(item["passed"] for item in payload["checks"])
