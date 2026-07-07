from pathlib import Path

from benchmarks.redis_api_load_benchmark import (
    build_worker_env,
    enforce_slo,
    percentile,
    redis_delete_namespace,
    redis_delete_prefix,
    redis_key_count,
)


class FakeRedis:
    def __init__(self):
        self.values = {
            "wm:test:tenant:a:1": "one",
            "wm:test:tenant:a:2": "two",
            "wm:test:tenant:b:1": "three",
            "other:tenant:a:1": "ignored",
        }

    def scan_iter(self, match=None):
        prefix = (match or "").rstrip("*")
        for key in list(self.values):
            if key.startswith(prefix):
                yield key

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)


def test_percentile_interpolates_values():
    assert percentile([], 99) == 0.0
    assert percentile([10.0], 99) == 10.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert round(percentile([1.0, 2.0, 3.0, 4.0], 95), 3) == 3.85


def test_redis_key_count_and_prefix_delete_are_scoped():
    redis = FakeRedis()

    assert redis_key_count(redis, "wm:test", "tenant:a") == 2
    assert redis_key_count(redis, "wm:test") == 3
    assert redis_delete_namespace(redis, "wm:test", "tenant:a") == 2
    assert redis.values == {
        "wm:test:tenant:b:1": "three",
        "other:tenant:a:1": "ignored",
    }
    assert redis_delete_prefix(redis, "wm:test") == 1
    assert redis.values == {"other:tenant:a:1": "ignored"}


def test_build_worker_env_sets_production_cache_controls(tmp_path):
    db_path = tmp_path / "worker.sqlite3"
    env = build_worker_env(
        base_env={"PYTHONPATH": "existing"},
        db_path=db_path,
        redis_url="redis://127.0.0.1:6379/0",
        redis_prefix="wm:test",
    )

    assert env["WAVEMIND_DB"] == str(db_path)
    assert env["WAVEMIND_REDIS_URL"] == "redis://127.0.0.1:6379/0"
    assert env["WAVEMIND_REDIS_PREFIX"] == "wm:test"
    assert env["WAVEMIND_VECTOR_CACHE_REDIS_URL"] == "redis://127.0.0.1:6379/0"
    assert env["WAVEMIND_VECTOR_CACHE_REDIS_PREFIX"] == "wm:test:qvec"
    assert env["WAVEMIND_VECTOR_CACHE_TTL_SECONDS"] == "300"
    assert env["WAVEMIND_AUDIT_QUERIES"] == "1"
    assert env["WAVEMIND_ENCODER"] == "hash"
    assert "127.0.0.1" in env["NO_PROXY"]
    assert "localhost" in env["NO_PROXY"]
    assert "::1" in env["no_proxy"]
    assert "existing" in env["PYTHONPATH"]
    assert str(Path(__file__).resolve().parents[1]) in env["PYTHONPATH"]


def test_enforce_slo_reports_actionable_failures():
    result = {"ok": True, "success_rate": 1.0, "p99_latency_ms": 42.0}
    assert enforce_slo(result, min_success_rate=1.0, max_p99_ms=100.0) == []

    failures = enforce_slo(
        {"ok": False, "success_rate": 0.9, "p99_latency_ms": 101.0},
        min_success_rate=1.0,
        max_p99_ms=100.0,
    )

    assert "benchmark ok flag is false" in failures
    assert any("success_rate" in failure for failure in failures)
    assert any("p99_latency_ms" in failure for failure in failures)
