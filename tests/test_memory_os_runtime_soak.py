import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "benchmarks" / "memory_os_runtime_soak.py"


def _module():
    spec = importlib.util.spec_from_file_location("memory_os_runtime_soak", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runtime_soak_classifies_local_and_remote_redis():
    module = _module()
    assert module.redis_environment("redis://127.0.0.1:6379/0") == "local_redis"
    assert module.redis_environment("rediss://cache.example.net:6380/0") == "remote_redis"


def test_runtime_soak_markdown_exposes_claim_boundary_and_checks():
    module = _module()
    payload = {
        "status": "pass",
        "environment": "local_redis",
        "claim_boundary": "Local evidence only.",
        "config": {"rounds": 2, "contenders": 3},
        "metrics": {
            "duration_seconds": 1.2,
            "completed_runs": 2,
            "duplicate_skips": 2,
            "lock_skips": 2,
            "retry_mutation_delta_max": 0.0,
            "lease_refresh_count": 4,
        },
        "checks": [{"id": "single-flight", "passed": True}],
    }
    markdown = module.render_markdown(payload)
    assert "Local evidence only." in markdown
    assert "`single-flight`" in markdown
    assert "`pass`" in markdown
