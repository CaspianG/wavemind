import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from wavemind import (
    __version__,
    SecretEnvRef,
    ServerlessObservedTelemetry,
    ServerlessWorkloadTarget,
    WaveMindServerlessSpec,
    serverless_sample_bundle,
)


def run_cli(*args):
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "wavemind", *args],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )


def test_serverless_spec_requires_external_postgres_state():
    with pytest.raises(ValueError, match="store='postgres'"):
        WaveMindServerlessSpec(store="sqlite")

    with pytest.raises(ValueError, match="qdrant_url"):
        WaveMindServerlessSpec(index="qdrant", qdrant_url=None)


def test_serverless_bundle_renders_knative_and_keda_resources():
    spec = WaveMindServerlessSpec(
        name="wm-serverless",
        namespace="memory",
        image=f"ghcr.io/caspiang/wavemind:{__version__}",
        min_scale=0,
        max_scale=50,
        target_concurrency=80,
        postgres_dsn=SecretEnvRef("pg", "dsn"),
        qdrant_url=SecretEnvRef("qdrant", "url"),
        redis_url=SecretEnvRef("redis", "url"),
        api_keys=SecretEnvRef("auth", "api-keys"),
    )

    bundle = serverless_sample_bundle(spec)
    service = next(item for item in bundle["items"] if item["apiVersion"] == "serving.knative.dev/v1")
    deployment = next(item for item in bundle["items"] if item["kind"] == "Deployment")
    scaled_object = next(item for item in bundle["items"] if item["kind"] == "ScaledObject")
    container = service["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item for item in container["env"]}

    assert service["apiVersion"] == "serving.knative.dev/v1"
    assert service["kind"] == "Service"
    assert service["metadata"]["name"] == "wm-serverless"
    assert service["spec"]["template"]["metadata"]["annotations"]["autoscaling.knative.dev/min-scale"] == "0"
    assert service["spec"]["template"]["metadata"]["annotations"]["autoscaling.knative.dev/max-scale"] == "50"
    assert service["spec"]["template"]["metadata"]["annotations"]["autoscaling.knative.dev/target"] == "80"
    assert container["args"] == ["serve", "--host", "0.0.0.0", "--port", "8000"]
    assert env["WAVEMIND_STORE"]["value"] == "postgres"
    assert env["WAVEMIND_POSTGRES_DSN"]["valueFrom"]["secretKeyRef"] == {"name": "pg", "key": "dsn"}
    assert env["WAVEMIND_QDRANT_URL"]["valueFrom"]["secretKeyRef"] == {"name": "qdrant", "key": "url"}
    assert env["WAVEMIND_REDIS_URL"]["valueFrom"]["secretKeyRef"] == {"name": "redis", "key": "url"}
    assert deployment["apiVersion"] == "apps/v1"
    assert deployment["metadata"]["name"] == "wm-serverless-keda"
    assert scaled_object["apiVersion"] == "keda.sh/v1alpha1"
    assert scaled_object["spec"]["scaleTargetRef"] == {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "name": "wm-serverless-keda",
    }
    assert scaled_object["spec"]["minReplicaCount"] == 1
    assert scaled_object["spec"]["maxReplicaCount"] == 50


def test_serverless_readiness_report_marks_scale_to_zero_safe():
    report = WaveMindServerlessSpec(min_scale=0, max_scale=24).readiness_report()

    assert report["mode"] == "serverless"
    assert report["stateless_workers"] is True
    assert report["scale_to_zero"] is True
    assert report["scale_to_zero_provider"] == "knative"
    assert report["external_state_required"] is True
    assert report["uses_postgres"] is True
    assert report["uses_external_qdrant"] is True
    assert report["uses_shared_cache"] is True
    assert report["safe_for_pod_eviction"] is True
    assert report["valid_keda_scale_target"] is True
    assert report["keda_scale_target_kind"] == "Deployment"
    assert report["keda_min_scale"] == 1
    assert report["keda_scale_to_zero"] is False


def test_serverless_operational_profile_checks_scale_slo_and_cost():
    spec = WaveMindServerlessSpec(
        min_scale=0,
        max_scale=64,
        target_concurrency=80,
        redis_url=SecretEnvRef("redis", "url"),
        api_keys=SecretEnvRef("auth", "api-keys"),
    )
    target = ServerlessWorkloadTarget(
        requests_per_second=3200,
        avg_request_ms=80,
        p99_request_ms=320,
        cold_start_ms=900,
        target_p99_ms=500,
        cold_start_budget_ms=1500,
        active_fraction=0.35,
        replica_hourly_cost_usd=0.08,
        monthly_budget_usd=750,
    )

    profile = spec.operational_profile(target)

    assert profile["mode"] == "serverless-operational"
    assert profile["valid"] is True
    assert profile["slo_pass"] is True
    assert profile["external_state_ok"] is True
    assert profile["scale_to_zero_safe"] is True
    assert profile["scale_out_possible"] is True
    assert profile["cold_start_budget_ok"] is True
    assert profile["cost_ok"] is True
    assert profile["required_replicas"] == 4
    assert profile["warm_replicas"] == 4
    assert profile["burst_capacity_rps"] == 64000.0
    assert profile["monthly_compute_cost_usd"] < 82


def test_serverless_operational_profile_accepts_observed_telemetry():
    spec = WaveMindServerlessSpec(
        min_scale=0,
        max_scale=64,
        target_concurrency=80,
    )
    profile = spec.operational_profile(
        ServerlessWorkloadTarget(
            requests_per_second=3200,
            avg_request_ms=80,
            p99_request_ms=320,
            cold_start_ms=900,
            target_p99_ms=500,
            cold_start_budget_ms=1500,
            max_error_rate=0.01,
            max_scale_out_seconds=60,
        ),
        observed=ServerlessObservedTelemetry(
            requests_per_second=3280,
            avg_request_ms=72,
            p95_request_ms=180,
            p99_request_ms=300,
            cold_start_ms=850,
            error_rate=0.001,
            max_replicas=5,
            scale_out_seconds=18,
            monthly_compute_cost_usd=92.0,
            source="k6-staging",
        ),
    )

    assert profile["valid"] is True
    assert profile["observed_telemetry_present"] is True
    assert profile["observed_telemetry_source"] == "k6-staging"
    assert profile["observed_slo_pass"] is True
    assert profile["observed_traffic_ok"] is True
    assert profile["observed_p99_ok"] is True
    assert profile["observed_cold_start_budget_ok"] is True
    assert profile["observed_error_rate_ok"] is True
    assert profile["observed_scale_out_ok"] is True
    assert profile["observed_capacity_ok"] is True
    assert profile["observed_cost_ok"] is True


def test_serverless_operational_profile_fails_on_observed_slo_regression():
    spec = WaveMindServerlessSpec(
        min_scale=0,
        max_scale=4,
        target_concurrency=80,
    )
    profile = spec.operational_profile(
        ServerlessWorkloadTarget(
            requests_per_second=3200,
            avg_request_ms=80,
            p99_request_ms=320,
            cold_start_ms=900,
            target_p99_ms=500,
            cold_start_budget_ms=1500,
            max_error_rate=0.01,
            max_scale_out_seconds=60,
        ),
        observed=ServerlessObservedTelemetry(
            requests_per_second=2800,
            avg_request_ms=110,
            p95_request_ms=520,
            p99_request_ms=720,
            cold_start_ms=1100,
            error_rate=0.04,
            max_replicas=6,
            scale_out_seconds=95,
            monthly_compute_cost_usd=900.0,
            source="regression",
        ),
    )

    assert profile["valid"] is False
    assert profile["observed_slo_pass"] is False
    assert profile["observed_traffic_ok"] is False
    assert profile["observed_p99_ok"] is False
    assert profile["observed_cold_start_budget_ok"] is False
    assert profile["observed_error_rate_ok"] is False
    assert profile["observed_scale_out_ok"] is False
    assert profile["observed_capacity_ok"] is False
    assert profile["observed_cost_ok"] is False


def test_serverless_operational_profile_fails_without_shared_cache_or_capacity():
    unsafe = WaveMindServerlessSpec(
        min_scale=0,
        max_scale=2,
        target_concurrency=80,
        redis_url=None,
    )

    profile = unsafe.operational_profile(
        ServerlessWorkloadTarget(
            requests_per_second=3200,
            avg_request_ms=80,
            p99_request_ms=320,
            cold_start_ms=900,
            target_p99_ms=500,
            cold_start_budget_ms=1500,
        )
    )

    assert profile["valid"] is False
    assert profile["uses_shared_cache"] is False
    assert profile["external_state_ok"] is False
    assert profile["scale_out_possible"] is False
    assert profile["required_replicas"] == 4


def test_serverless_workload_target_validates_operational_inputs():
    with pytest.raises(ValueError, match="requests_per_second"):
        ServerlessWorkloadTarget(requests_per_second=0)
    with pytest.raises(ValueError, match="active_fraction"):
        ServerlessWorkloadTarget(active_fraction=1.5)
    with pytest.raises(ValueError, match="monthly_budget"):
        ServerlessWorkloadTarget(monthly_budget_usd=0)
    with pytest.raises(ValueError, match="max_error_rate"):
        ServerlessWorkloadTarget(max_error_rate=2)
    with pytest.raises(ValueError, match="p99_request_ms"):
        ServerlessObservedTelemetry(
            requests_per_second=1,
            avg_request_ms=1,
            p95_request_ms=10,
            p99_request_ms=5,
            cold_start_ms=1,
        )


def test_serverless_cli_emits_bundle_and_readiness(tmp_path):
    bundle_file = tmp_path / "serverless.json"
    run_cli(
        "serverless-sample",
        "--name",
        "wm-cli",
        "--namespace",
        "memory",
        "--max-scale",
        "32",
        "--out",
        str(bundle_file),
    )
    bundle = json.loads(bundle_file.read_text(encoding="utf-8"))

    assert bundle["kind"] == "List"
    assert {item["kind"] for item in bundle["items"]} == {"Service", "Deployment", "ScaledObject"}
    assert any(item["apiVersion"] == "serving.knative.dev/v1" for item in bundle["items"])
    assert any(item["apiVersion"] == "apps/v1" for item in bundle["items"])

    readiness = json.loads(run_cli("serverless-sample", "--readiness").stdout)

    assert readiness["mode"] == "serverless"
    assert readiness["max_scale"] == 24
    assert readiness["uses_postgres"] is True
    assert readiness["valid_keda_scale_target"] is True

    operational = json.loads(
        run_cli(
            "serverless-sample",
            "--operational-profile",
            "--max-scale",
            "64",
            "--target-concurrency",
            "80",
            "--target-rps",
            "3200",
            "--avg-request-ms",
            "80",
            "--p99-request-ms",
            "320",
            "--cold-start-ms",
            "900",
            "--target-p99-ms",
            "500",
            "--cold-start-budget-ms",
            "1500",
        ).stdout
    )

    assert operational["mode"] == "serverless-operational"
    assert operational["slo_pass"] is True
    assert operational["required_replicas"] == 4
    assert operational["burst_capacity_rps"] == 64000.0
    assert operational["cold_start_budget_ok"] is True

    telemetry_file = tmp_path / "telemetry.json"
    telemetry_file.write_text(
        json.dumps(
            {
                "source": "k6-staging",
                "requests_per_second": 3280,
                "avg_request_ms": 72,
                "p95_request_ms": 180,
                "p99_request_ms": 300,
                "cold_start_ms": 850,
                "error_rate": 0.001,
                "max_replicas": 5,
                "scale_out_seconds": 18,
                "monthly_compute_cost_usd": 92.0,
            }
        ),
        encoding="utf-8",
    )
    observed = json.loads(
        run_cli(
            "serverless-sample",
            "--operational-profile",
            "--max-scale",
            "64",
            "--target-concurrency",
            "80",
            "--observed-telemetry",
            str(telemetry_file),
        ).stdout
    )

    assert observed["observed_telemetry_present"] is True
    assert observed["observed_telemetry_source"] == "k6-staging"
    assert observed["observed_slo_pass"] is True
