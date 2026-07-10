import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "kubernetes_postgres_qdrant_dr_smoke.py"
)
SPEC = importlib.util.spec_from_file_location(
    "kubernetes_postgres_qdrant_dr_smoke", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _passing_observation():
    return {
        "source_namespace": "wavemind-serverless",
        "recovery_namespace": "wavemind-serverless-dr",
        "source_service": (
            "http://wavemind-serverless-keda.wavemind-serverless."
            "svc.cluster.local:8000"
        ),
        "recovery_service": (
            "http://wavemind-serverless-keda.wavemind-serverless-dr."
            "svc.cluster.local:8000"
        ),
        "backup_format": "pg_dump-custom",
        "backup_bytes": 4096,
        "backup_sha256": "a" * 64,
        "source_state_stopped": True,
        "recovery_services": ["postgres", "qdrant", "redis"],
        "recovery_pvcs": 3,
        "postgres_restore_completed": True,
        "memory_count": 24,
        "restored": {"rate": 1.0},
        "recovery_stats": {
            "index_healthy": True,
            "index_expected_records": 24,
            "index_vector_records": 24,
            "index_missing_records": 0,
            "index_extra_records": 0,
        },
        "recovery_api_uid_before": "uid-before",
        "recovery_api_uid_after": "uid-after",
        "restored_after_api_replacement": {"rate": 1.0},
        "restore_elapsed_ms": 42000.0,
        "restore_budget_ms": 180000.0,
    }


def test_dr_evaluator_requires_independent_restore_and_exact_index(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_RUN_ID", "777")
    monkeypatch.setenv("GITHUB_REPOSITORY", "CaspianG/wavemind")

    payload = MODULE.evaluate_kubernetes_postgres_qdrant_dr_smoke(
        _passing_observation()
    )

    assert payload["status"] == "pass"
    assert payload["summary"]["passed_checks"] == 10
    assert payload["summary"]["check_count"] == 10
    assert payload["source_ref"] == "abc123"
    assert payload["workflow_run_url"] == (
        "https://github.com/CaspianG/wavemind/actions/runs/777"
    )
    assert "not managed-cloud PITR" in payload["claim_boundary"]


def test_dr_evaluator_rejects_in_place_or_incomplete_restore():
    observed = _passing_observation()
    observed["recovery_namespace"] = observed["source_namespace"]
    observed["backup_bytes"] = 0
    observed["source_state_stopped"] = False
    observed["restored"]["rate"] = 0.95
    observed["recovery_stats"]["index_vector_records"] = 23
    observed["recovery_api_uid_after"] = observed["recovery_api_uid_before"]
    observed["restore_elapsed_ms"] = 200000.0

    payload = MODULE.evaluate_kubernetes_postgres_qdrant_dr_smoke(observed)
    checks = {check["id"]: check for check in payload["checks"]}

    assert payload["status"] == "fail"
    assert checks["source_and_recovery_non_loopback"]["passed"] is False
    assert checks["postgres_backup_materialized"]["passed"] is False
    assert checks["source_state_services_stopped"]["passed"] is False
    assert checks["all_memories_recalled_after_restore"]["passed"] is False
    assert checks["qdrant_rebuilt_from_postgres"]["passed"] is False
    assert checks["recovery_api_replaced"]["passed"] is False
    assert checks["restore_time_budget"]["passed"] is False


def test_dr_runner_is_wired_after_serverless_lifecycle():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "kubernetes-operator-smoke.yml"
    ).read_text(encoding="utf-8")

    assert "kubernetes_postgres_qdrant_dr_smoke.py" in workflow
    assert "kubernetes_postgres_qdrant_dr_smoke_ci_results.json" in workflow
    assert workflow.index("kubernetes_serverless_lifecycle_smoke.py") < workflow.index(
        "kubernetes_postgres_qdrant_dr_smoke.py"
    )
