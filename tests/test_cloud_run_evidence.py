import hashlib

import pytest

from wavemind.cloud_run_evidence import (
    CloudRunEvidenceError,
    build_cloud_run_managed_telemetry,
    cloud_run_service_identity,
    distribution_percentile,
)


SERVICE_URL = "https://wavemind-managed-abc-uc.a.run.app"


def _service(*, min_instances="0", max_instances="16"):
    return {
        "metadata": {"name": "wavemind-managed"},
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "autoscaling.knative.dev/minScale": min_instances,
                        "autoscaling.knative.dev/maxScale": max_instances,
                    }
                }
            }
        },
        "status": {
            "url": SERVICE_URL,
            "latestReadyRevisionName": "wavemind-managed-00042-abc",
            "conditions": [{"type": "Ready", "status": "True"}],
        },
    }


def _distribution_series(*, counts):
    return [
        {
            "points": [
                {
                    "interval": {"endTime": "2026-07-12T00:02:00Z"},
                    "value": {
                        "distributionValue": {
                            "count": sum(counts),
                            "bucketOptions": {
                                "explicitBuckets": {"bounds": [100.0, 500.0, 1000.0]}
                            },
                            "bucketCounts": list(counts),
                        }
                    },
                }
            ]
        }
    ]


def _scalar_series(values):
    return [
        {
            "points": [
                {
                    "interval": {"endTime": timestamp},
                    "value": {"int64Value": str(value)},
                }
                for timestamp, value in values
            ]
        }
    ]


def test_cloud_run_service_identity_requires_ready_scale_from_zero_service():
    identity = cloud_run_service_identity(
        _service(),
        project_id="wavemind-benchmarks",
        region="us-central1",
        service_name="wavemind-managed",
    )

    assert identity["provider"] == "gcp-cloud-run"
    assert identity["deployment_revision"] == "wavemind-managed-00042-abc"
    assert identity["min_instances"] == 0
    assert identity["configured_max_scale"] == 16
    assert identity["service_url_sha256"] == hashlib.sha256(SERVICE_URL.encode()).hexdigest()

    with pytest.raises(CloudRunEvidenceError, match="min instances = 0"):
        cloud_run_service_identity(
            _service(min_instances="1"),
            project_id="wavemind-benchmarks",
            region="us-central1",
            service_name="wavemind-managed",
        )


def test_distribution_percentile_aggregates_provider_histograms():
    series = _distribution_series(counts=(0, 95, 4, 1))

    assert distribution_percentile(series, 95.0) == 500.0
    assert distribution_percentile(series, 99.0) == 1000.0


def test_build_cloud_run_managed_telemetry_uses_provider_observations(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "29200000000")
    monkeypatch.setenv("GITHUB_REPOSITORY", "CaspianG/wavemind")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    identity = cloud_run_service_identity(
        _service(),
        project_id="wavemind-benchmarks",
        region="us-central1",
        service_name="wavemind-managed",
    )
    load_result = {
        "requests": 2000,
        "successes": 2000,
        "failures": 0,
        "measured_pool_requests_per_second": 4000.0,
        "p99_request_ms": 90.0,
        "target_rps": 3200.0,
        "target_p99_ms": 1000.0,
        "cold_start_budget_ms": 3500.0,
        "error_rate": 0.0,
        "max_error_rate": 0.01,
        "external_node_url_sha256": [identity["service_url_sha256"]],
    }
    metrics = {
        "request_count": _scalar_series([("2026-07-12T00:02:00Z", 2000)]),
        "request_latency": _distribution_series(counts=(0, 100, 1890, 10)),
        "container_startup_latency": _distribution_series(counts=(0, 15, 1, 0)),
        "container_instance_count": _scalar_series(
            [
                ("2026-07-12T00:00:00Z", 0),
                ("2026-07-12T00:01:00Z", 1),
                ("2026-07-12T00:02:00Z", 8),
            ]
        ),
    }

    payload = build_cloud_run_managed_telemetry(
        service_identity=identity,
        load_result=load_result,
        metrics=metrics,
        metric_window_start="2026-07-12T00:00:00Z",
        metric_window_end="2026-07-12T00:03:00Z",
    )

    assert payload["schema"] == "wavemind.managed_serverless_telemetry.v1"
    assert payload["provider_control_plane_observed"] is True
    assert payload["horizontal_capacity_estimate"] is False
    assert payload["capacity_method"] == "provider-observed"
    assert payload["provider_request_count"] == 2000
    assert payload["measured_replicas"] == 8
    assert payload["scale_out_seconds"] == 60.0
    assert payload["cold_start_measured"] is True
    assert payload["scale_out_measured"] is True
    assert payload["scale_to_zero_observed"] is True
    assert payload["observed_slo_pass"] is True


def test_build_cloud_run_managed_telemetry_rejects_wrong_client_endpoint():
    identity = cloud_run_service_identity(
        _service(),
        project_id="wavemind-benchmarks",
        region="us-central1",
        service_name="wavemind-managed",
    )
    load_result = {
        "requests": 2000,
        "successes": 2000,
        "measured_pool_requests_per_second": 4000.0,
        "p99_request_ms": 90.0,
        "target_rps": 3200.0,
        "target_p99_ms": 500.0,
        "error_rate": 0.0,
        "external_node_url_sha256": ["b" * 64],
    }
    metrics = {
        "request_count": _scalar_series([("2026-07-12T00:02:00Z", 2000)]),
        "request_latency": _distribution_series(counts=(0, 1900, 100, 0)),
        "container_startup_latency": _distribution_series(counts=(0, 8, 0, 0)),
        "container_instance_count": _scalar_series(
            [
                ("2026-07-12T00:00:00Z", 0),
                ("2026-07-12T00:01:00Z", 1),
                ("2026-07-12T00:02:00Z", 8),
            ]
        ),
    }

    with pytest.raises(CloudRunEvidenceError, match="attested Cloud Run URL"):
        build_cloud_run_managed_telemetry(
            service_identity=identity,
            load_result=load_result,
            metrics=metrics,
            metric_window_start="2026-07-12T00:00:00Z",
            metric_window_end="2026-07-12T00:03:00Z",
        )
