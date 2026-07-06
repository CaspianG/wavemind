import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from wavemind import __version__, SecretEnvRef, WaveMindServerlessSpec, serverless_sample_bundle


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
    assert scaled_object["spec"]["minReplicaCount"] == 0
    assert scaled_object["spec"]["maxReplicaCount"] == 50


def test_serverless_readiness_report_marks_scale_to_zero_safe():
    report = WaveMindServerlessSpec(min_scale=0, max_scale=24).readiness_report()

    assert report["mode"] == "serverless"
    assert report["stateless_workers"] is True
    assert report["scale_to_zero"] is True
    assert report["external_state_required"] is True
    assert report["uses_postgres"] is True
    assert report["uses_external_qdrant"] is True
    assert report["uses_shared_cache"] is True
    assert report["safe_for_pod_eviction"] is True
    assert report["valid_keda_scale_target"] is True
    assert report["keda_scale_target_kind"] == "Deployment"


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
