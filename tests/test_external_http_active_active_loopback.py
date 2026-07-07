import argparse

import pytest

from benchmarks import external_http_active_active_loopback as loopback
from benchmarks.local_http_active_active_smoke import LocalReplicatedRegion


class FakeProcess:
    def poll(self):
        return None

    def terminate(self):
        return None

    def communicate(self, timeout=None):
        return "", ""


def _args(**overrides):
    values = {
        "regions": 3,
        "replicas_per_region": 3,
        "namespace_prefix": "tenant:test-active-active-loopback",
        "namespace_count": 16,
        "limit": None,
        "timeout": 15.0,
        "readiness_timeout": 20.0,
        "api_key": None,
        "deployment_id": "loopback-active-active-test",
        "environment": "local-loopback",
        "source": "loopback-api-regions",
        "min_success_rate": 1.0,
        "min_convergence_rate": 1.0,
        "min_delete_suppression_rate": 1.0,
        "p99_slo_ms": 1500.0,
        "fail_on_slo": False,
        "output": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_loopback_external_active_active_runner_uses_url_based_external_mode(monkeypatch, tmp_path):
    started = []
    stopped = []
    captured_external_args = []

    def fake_start(root, region_id, **kwargs):
        region = LocalReplicatedRegion(
            id=region_id,
            address=f"http://127.0.0.1:{9400 + len(started)}",
            root_path=tmp_path / region_id,
            process=FakeProcess(),
        )
        started.append((root, region, kwargs))
        return region

    def fake_stop(regions):
        stopped.extend(regions)

    def fake_external_run(args):
        captured_external_args.append(args)
        return {
            "scenario": {
                "name": "local_http_active_active_smoke",
                "source": "external-regions",
                "deployment_id": args.deployment_id,
                "environment": args.environment,
                "evidence_source": args.source,
                "region_count": len(args.region),
                "region_ids": [item.split("=", 1)[0] for item in args.region],
                "replicas_per_region": None,
                "namespace_prefix": args.namespace_prefix,
                "namespace_count": args.namespace_count,
            },
            "results": [
                {
                    "engine": "WaveMind real HTTP active-active service-region sync",
                    "region_count": len(args.region),
                    "namespaces": args.namespace_count,
                    "writes": len(args.region) * args.namespace_count,
                    "sync_cycles": 3,
                    "pair_syncs": 18,
                    "cursor_count": 6,
                    "records_imported": 12,
                    "tombstones_imported": 2,
                    "deleted_records": 2,
                    "field_keys_exported": 12,
                    "final_noop_records_imported": 0,
                    "final_noop_failed_pairs": 0,
                    "convergence_rate": 1.0,
                    "delete_suppression_rate": 1.0,
                    "success_rate": 1.0,
                    "failed_pairs": 0,
                    "has_more_pairs": 0,
                    "avg_sync_ms": 10.0,
                    "p99_sync_ms": 12.0,
                    "avg_operation_ms": 5.0,
                    "p99_operation_ms": 42.0,
                    "slo_pass": True,
                }
            ],
        }

    monkeypatch.setattr(loopback.active_runner, "start_replicated_region", fake_start)
    monkeypatch.setattr(loopback.active_runner, "stop_regions", fake_stop)
    monkeypatch.setattr(loopback.active_runner, "run_from_args", fake_external_run)

    payload = loopback.run_from_args(_args())

    assert len(started) == 3
    assert len(stopped) == 3
    assert all(item[2]["capture_output"] is False for item in started)
    assert len(captured_external_args) == 1
    external_args = captured_external_args[0]
    assert external_args.region == [
        "region-000=http://127.0.0.1:9400",
        "region-001=http://127.0.0.1:9401",
        "region-002=http://127.0.0.1:9402",
    ]
    assert external_args.environment == "local-loopback"
    assert external_args.source == "loopback-api-regions"
    assert payload["scenario"]["source"] == "external-regions"
    assert payload["scenario"]["started_api_processes"] == 3
    assert payload["results"][0]["slo_pass"] is True


def test_loopback_external_active_active_runner_rejects_invalid_region_count():
    with pytest.raises(ValueError, match="at least 2"):
        loopback.run_from_args(_args(regions=1))


def test_loopback_external_active_active_runner_rejects_invalid_replica_count():
    with pytest.raises(ValueError, match="positive"):
        loopback.run_from_args(_args(replicas_per_region=0))
