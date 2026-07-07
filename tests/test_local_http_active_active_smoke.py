import argparse
import subprocess

import pytest

from benchmarks import local_http_active_active_smoke as smoke


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return 0 if self.terminated or self.killed else None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def communicate(self, timeout=None):
        return "", ""


def _args(**overrides):
    values = {
        "region": [],
        "regions": 3,
        "replicas_per_region": 3,
        "namespace_prefix": "tenant:test-active-active",
        "namespace_count": 2,
        "limit": None,
        "timeout": 15.0,
        "readiness_timeout": 20.0,
        "api_key": None,
        "min_success_rate": 1.0,
        "min_convergence_rate": 1.0,
        "min_delete_suppression_rate": 1.0,
        "p99_slo_ms": 1500.0,
        "fail_on_slo": False,
        "output": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _passing_result(region_count=3):
    return {
        "engine": "WaveMind real HTTP active-active service-region sync",
        "region_count": region_count,
        "namespaces": 2,
        "writes": region_count * 2,
        "deleted_records_requested": 1,
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
    }


def test_parse_region_specs_accepts_explicit_and_implicit_ids():
    regions = smoke.parse_region_specs(
        [
            "east=http://127.0.0.1:8001",
            "https://example.test/wavemind",
        ]
    )

    assert regions == {
        "east": "http://127.0.0.1:8001",
        "region-001": "https://example.test/wavemind",
    }


def test_parse_region_specs_rejects_invalid_addresses():
    with pytest.raises(ValueError, match="must start"):
        smoke.parse_region_specs(["east=127.0.0.1:8001", "west=http://127.0.0.1:8002"])


def test_run_from_args_starts_replicated_regions_and_reports_slo(monkeypatch, tmp_path):
    started = []
    stopped = []

    def fake_start(root, region_id, **kwargs):
        region = smoke.LocalReplicatedRegion(
            id=region_id,
            address=f"http://127.0.0.1:{9000 + len(started)}",
            root_path=tmp_path / region_id,
            process=FakeProcess(),
        )
        started.append((root, region, kwargs))
        return region

    def fake_stop(regions):
        stopped.extend(regions)

    def fake_workload(regions, **kwargs):
        assert list(regions) == ["region-000", "region-001", "region-002"]
        assert kwargs["namespace_prefix"] == "tenant:test-active-active"
        assert kwargs["namespace_count"] == 2
        return _passing_result(region_count=len(regions))

    monkeypatch.setattr(smoke, "start_replicated_region", fake_start)
    monkeypatch.setattr(smoke, "stop_regions", fake_stop)
    monkeypatch.setattr(smoke, "run_active_active_service_workload", fake_workload)

    payload = smoke.run_from_args(_args())

    assert len(started) == 3
    assert len(stopped) == 3
    assert payload["scenario"]["name"] == "local_http_active_active_smoke"
    assert payload["scenario"]["source"] == "local-replicated-api-processes"
    assert payload["scenario"]["replicas_per_region"] == 3
    assert payload["scenario"]["root_path"] is None
    assert payload["results"][0]["slo_pass"] is True


def test_run_from_args_allows_external_regions_without_local_region_count(monkeypatch):
    def fake_workload(regions, **kwargs):
        assert regions == {
            "east": "http://127.0.0.1:8001",
            "west": "http://127.0.0.1:8002",
        }
        return _passing_result(region_count=len(regions))

    monkeypatch.setattr(smoke, "run_active_active_service_workload", fake_workload)

    payload = smoke.run_from_args(
        _args(
            region=["east=http://127.0.0.1:8001", "west=http://127.0.0.1:8002"],
            regions=1,
        )
    )

    assert payload["scenario"]["source"] == "external-regions"
    assert payload["scenario"]["replicas_per_region"] is None
    assert payload["results"][0]["slo_pass"] is True


def test_run_from_args_marks_slo_failure(monkeypatch):
    result = _passing_result()
    result["p99_operation_ms"] = 1600.0

    monkeypatch.setattr(
        smoke,
        "start_replicated_region",
        lambda root, region_id, **kwargs: smoke.LocalReplicatedRegion(
            id=region_id,
            address="http://127.0.0.1:9000",
            root_path=root / region_id,
            process=FakeProcess(),
        ),
    )
    monkeypatch.setattr(smoke, "stop_regions", lambda regions: None)
    monkeypatch.setattr(smoke, "run_active_active_service_workload", lambda regions, **kwargs: result)

    payload = smoke.run_from_args(_args())

    assert payload["results"][0]["slo_pass"] is False


def test_stop_regions_terminates_then_kills_if_needed():
    class HangingProcess(FakeProcess):
        def poll(self):
            return None

        def communicate(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("wavemind", timeout)
            return "", ""

    region = smoke.LocalReplicatedRegion(
        id="region-a",
        address="http://127.0.0.1:9000",
        root_path=None,
        process=HangingProcess(),
    )

    smoke.stop_regions([region])

    assert region.process.terminated is True
    assert region.process.killed is True
