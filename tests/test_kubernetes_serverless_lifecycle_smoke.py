import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "kubernetes_serverless_lifecycle_smoke.py"
)
SPEC = importlib.util.spec_from_file_location(
    "kubernetes_serverless_lifecycle_smoke", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _passing_observation():
    return {
        "service_address": (
            "http://wavemind-serverless-keda.wavemind-serverless."
            "svc.cluster.local:8000"
        ),
        "external_services": ["postgres", "qdrant", "redis"],
        "persistent_volume_claims": 3,
        "zero_replicas": True,
        "zero_endpoints": True,
        "cold_start_ms": 4200.0,
        "cold_start_budget_ms": 120000.0,
        "restored_after_zero": {"rate": 1.0},
        "ready_replicas": 3,
        "endpoint_count": 3,
        "zone_count": 3,
        "cross_replica": {
            "replicas": 3,
            "visible_replicas": 3,
            "suppressed_replicas": 3,
            "deleted": 1,
            "write_active_counts": [25, 25, 25],
            "delete_active_counts": [24, 24, 24],
            "seed_count": 24,
        },
        "burst": {
            "requests": 120,
            "successes": 120,
            "errors": 0,
            "p99_ms": 180.0,
        },
        "burst_p99_budget_ms": 2000.0,
        "final_restore": {"rate": 1.0},
    }


def test_serverless_lifecycle_evaluator_requires_all_runtime_invariants(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_RUN_ID", "777")
    monkeypatch.setenv("GITHUB_REPOSITORY", "CaspianG/wavemind")

    payload = MODULE.evaluate_kubernetes_serverless_lifecycle_smoke(
        _passing_observation()
    )

    assert payload["status"] == "pass"
    assert payload["summary"]["passed_checks"] == payload["summary"]["check_count"] == 12
    assert "does not unlock remote managed" in payload["claim_boundary"]
    assert payload["source_ref"] == "abc123"
    assert payload["workflow_run_url"] == (
        "https://github.com/CaspianG/wavemind/actions/runs/777"
    )


def test_serverless_lifecycle_evaluator_rejects_local_or_incomplete_evidence():
    observed = _passing_observation()
    observed["service_address"] = "http://127.0.0.1:8000"
    observed["persistent_volume_claims"] = 1
    observed["cross_replica"]["visible_replicas"] = 2
    observed["burst"]["p99_ms"] = 5000.0

    payload = MODULE.evaluate_kubernetes_serverless_lifecycle_smoke(observed)
    checks = {check["id"]: check for check in payload["checks"]}

    assert payload["status"] == "fail"
    assert checks["non_loopback_service_dns"]["passed"] is False
    assert checks["external_durable_state"]["passed"] is False
    assert checks["cross_replica_write_visibility"]["passed"] is False
    assert checks["burst_p99_budget"]["passed"] is False


def test_serverless_resources_use_external_persistent_state_and_zero_api_replicas():
    resources = MODULE.build_serverless_resources(
        namespace="wavemind-serverless",
        image="wavemind:ci-upgrade",
        postgres_image="postgres:16-alpine",
        qdrant_image="qdrant/qdrant:v1.15.1",
        redis_image="redis:7-alpine",
    )
    statefulsets = [item for item in resources if item["kind"] == "StatefulSet"]
    deployment = next(item for item in resources if item["kind"] == "Deployment")
    service = next(
        item
        for item in resources
        if item["kind"] == "Service"
        and item["metadata"]["name"] == "wavemind-serverless-keda"
    )
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item for item in container["env"]}

    assert {item["metadata"]["name"] for item in statefulsets} == {
        "postgres",
        "qdrant",
        "redis",
    }
    assert all(item["spec"]["volumeClaimTemplates"] for item in statefulsets)
    assert deployment["spec"]["replicas"] == 0
    assert deployment["spec"]["template"]["spec"]["topologySpreadConstraints"][0][
        "topologyKey"
    ] == "topology.kubernetes.io/zone"
    assert env["WAVEMIND_STORE"]["value"] == "postgres"
    assert env["WAVEMIND_INDEX"]["value"] == "qdrant"
    assert env["WAVEMIND_SHARED_STORE_REFRESH_SECONDS"]["value"] == "0"
    assert env["WAVEMIND_REDIS_URL"]["valueFrom"]["secretKeyRef"]["name"] == "wavemind-redis"
    assert container["command"] == ["wavemind"]
    assert container["args"][:3] == ["serve", "--host", "0.0.0.0"]
    assert container["readinessProbe"]["httpGet"]["path"] == "/healthz"
    assert service["spec"]["type"] == "ClusterIP"


def test_kind_workflow_runs_serverless_lifecycle_drill():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "kubernetes-operator-smoke.yml"
    ).read_text(encoding="utf-8")

    assert "INSTALL_PRODUCTION=true" in workflow
    assert "kubernetes_serverless_lifecycle_smoke.py" in workflow
    assert "kubernetes_serverless_lifecycle_smoke_ci_results.json" in workflow
    assert "postgres:16-alpine" in workflow
    assert "qdrant/qdrant:v1.15.1" in workflow
    assert "redis:7-alpine" in workflow
