import argparse
import subprocess

import pytest

from benchmarks import local_http_cluster_smoke as smoke


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
        "nodes": 4,
        "replication_factor": 3,
        "write_quorum": None,
        "read_quorum": 1,
        "read_fanout": 1,
        "namespace_prefix": "tenant:test-local-http",
        "namespace_count": 2,
        "memories_per_namespace": 2,
        "workers": 2,
        "timeout": 15.0,
        "readiness_timeout": 20.0,
        "min_success_rate": 1.0,
        "min_failover_hit_rate": 0.95,
        "p99_slo_ms": 1000.0,
        "fail_on_slo": False,
        "output": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_run_from_args_starts_real_node_specs_and_reports_slo(monkeypatch, tmp_path):
    started = []
    stopped = []

    def fake_start(root, node_id, **kwargs):
        node = smoke.LocalAPINode(
            id=node_id,
            address=f"http://127.0.0.1:{9000 + len(started)}",
            zone=f"zone-{len(started) % 3}",
            db_path=tmp_path / f"{node_id}.sqlite3",
            process=FakeProcess(),
        )
        started.append((root, node, kwargs))
        return node

    def fake_stop(nodes):
        stopped.extend(nodes)

    def fake_workload(nodes, **kwargs):
        assert [node.id for node in nodes] == ["node-000", "node-001", "node-002", "node-003"]
        assert kwargs["engine"] == "WaveMind local HTTP cluster smoke"
        assert kwargs["namespace_prefix"] == "tenant:test-local-http"
        assert kwargs["replication_factor"] == 3
        assert kwargs["read_fanout"] == 1
        assert kwargs["max_workers"] == 2
        return {
            "engine": "WaveMind local HTTP cluster smoke",
            "nodes": len(nodes),
            "namespaces": 2,
            "memories_per_namespace": 2,
            "replication_factor": 3,
            "write_quorum": 2,
            "read_quorum": 1,
            "workers": 2,
            "writes": 4,
            "queries": 4,
            "failover_queries": 4,
            "forgets": 2,
            "write_success_rate": 1.0,
            "query_hit_rate": 1.0,
            "failover_hit_rate": 1.0,
            "forget_success_rate": 1.0,
            "delete_suppression_rate": 1.0,
            "repair_ok": True,
            "repair_repaired_total": 1,
            "repaired_replica": True,
            "success_rate": 1.0,
            "p99_operation_ms": 42.0,
        }

    monkeypatch.setattr(smoke, "start_api_node", fake_start)
    monkeypatch.setattr(smoke, "stop_api_nodes", fake_stop)
    monkeypatch.setattr(smoke, "run_sustained_http_cluster_workload", fake_workload)

    payload = smoke.run_from_args(_args())

    assert len(started) == 4
    assert len(stopped) == 4
    assert payload["scenario"]["name"] == "local_http_cluster_smoke"
    assert payload["scenario"]["started_api_processes"] == 4
    assert payload["results"][0]["slo_pass"] is True


def test_run_from_args_marks_slo_failure(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "start_api_node",
        lambda root, node_id, **kwargs: smoke.LocalAPINode(
            id=node_id,
            address=f"http://127.0.0.1:{9000 + int(node_id.rsplit('-', 1)[-1])}",
            zone="zone-a",
            db_path=root / f"{node_id}.sqlite3",
            process=FakeProcess(),
        ),
    )
    monkeypatch.setattr(smoke, "stop_api_nodes", lambda nodes: None)
    monkeypatch.setattr(
        smoke,
        "run_sustained_http_cluster_workload",
        lambda nodes, **kwargs: {
            "engine": "WaveMind local HTTP cluster smoke",
            "nodes": len(nodes),
            "success_rate": 0.75,
            "failover_hit_rate": 1.0,
            "p99_operation_ms": 10.0,
        },
    )

    payload = smoke.run_from_args(_args())

    assert payload["results"][0]["slo_pass"] is False


def test_run_from_args_rejects_invalid_cluster_shape():
    with pytest.raises(ValueError, match="cannot exceed"):
        smoke.run_from_args(_args(nodes=2, replication_factor=3))


def test_run_from_args_rejects_read_fanout_below_read_quorum():
    with pytest.raises(ValueError, match="cannot be smaller"):
        smoke.run_from_args(_args(read_quorum=2, read_fanout=1))


def test_stop_api_nodes_terminates_then_kills_if_needed():
    class HangingProcess(FakeProcess):
        def poll(self):
            return None

        def communicate(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("wavemind", timeout)
            return "", ""

    process = HangingProcess()
    node = smoke.LocalAPINode(
        id="node-000",
        address="http://127.0.0.1:9000",
        zone="zone-a",
        db_path=None,
        process=process,
    )

    smoke.stop_api_nodes([node])

    assert process.terminated is True
    assert process.killed is True
