import argparse

import pytest

from benchmarks import external_http_cluster_loopback as loopback
from benchmarks.local_http_cluster_smoke import LocalAPINode


class FakeProcess:
    def poll(self):
        return None

    def terminate(self):
        return None

    def communicate(self, timeout=None):
        return "", ""


def _args(**overrides):
    values = {
        "nodes": 4,
        "replication_factor": 3,
        "write_quorum": None,
        "read_quorum": 1,
        "read_fanout": 1,
        "namespace_prefix": "tenant:test-external-loopback",
        "namespace_count": 32,
        "memories_per_namespace": 8,
        "workers": 8,
        "timeout": 15.0,
        "readiness_timeout": 20.0,
        "min_success_rate": 1.0,
        "min_failover_hit_rate": 0.95,
        "p99_slo_ms": 1000.0,
        "fail_on_slo": False,
        "deployment_id": "loopback-test",
        "environment": "local-loopback",
        "source": "loopback-api-processes",
        "output": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_loopback_external_runner_starts_nodes_and_uses_external_payload(monkeypatch, tmp_path):
    started = []
    stopped = []
    captured_external_args = []

    def fake_start(root, node_id, **kwargs):
        node = LocalAPINode(
            id=node_id,
            address=f"http://127.0.0.1:{9200 + len(started)}",
            zone=f"zone-{len(started) % 3}",
            db_path=tmp_path / f"{node_id}.sqlite3",
            process=FakeProcess(),
        )
        started.append((root, node, kwargs))
        return node

    def fake_stop(nodes):
        stopped.extend(nodes)

    def fake_external_run(args):
        captured_external_args.append(args)
        return {
            "scenario": {
                "name": "http_cluster_load",
                "node_count": len(args.node),
                "node_ids": [item.split("=", 1)[0] for item in args.node],
                "zones": ["zone-0", "zone-1", "zone-2"],
                "replication_factor": args.replication_factor,
                "write_quorum": 2,
                "read_quorum": args.read_quorum,
                "read_fanout": args.read_fanout,
                "namespace_prefix": args.namespace_prefix,
                "namespace_count": args.namespace_count,
                "memories_per_namespace": args.memories_per_namespace,
                "workers": args.workers,
                "deployment_id": args.deployment_id,
                "environment": args.environment,
                "source": args.source,
            },
            "results": [
                {
                    "engine": "WaveMind external HTTP cluster load",
                    "nodes": len(args.node),
                    "namespaces": args.namespace_count,
                    "memories_per_namespace": args.memories_per_namespace,
                    "replication_factor": args.replication_factor,
                    "write_quorum": 2,
                    "read_quorum": args.read_quorum,
                    "read_fanout": args.read_fanout,
                    "success_rate": 1.0,
                    "write_success_rate": 1.0,
                    "query_hit_rate": 1.0,
                    "failover_hit_rate": 1.0,
                    "delete_suppression_rate": 1.0,
                    "repair_ok": True,
                    "repair_repaired_total": 1,
                    "p99_operation_ms": 50.0,
                    "slo_pass": True,
                }
            ],
        }

    monkeypatch.setattr(loopback, "start_api_node", fake_start)
    monkeypatch.setattr(loopback, "stop_api_nodes", fake_stop)
    monkeypatch.setattr(loopback.external_runner, "run_from_args", fake_external_run)

    payload = loopback.run_from_args(_args())

    assert len(started) == 4
    assert len(stopped) == 4
    assert all(item[2]["capture_output"] is False for item in started)
    assert len(captured_external_args) == 1
    external_args = captured_external_args[0]
    assert external_args.node == [
        "node-000=http://127.0.0.1:9200",
        "node-001=http://127.0.0.1:9201",
        "node-002=http://127.0.0.1:9202",
        "node-003=http://127.0.0.1:9203",
    ]
    assert external_args.source == "loopback-api-processes"
    assert payload["scenario"]["name"] == "http_cluster_load"
    assert payload["scenario"]["started_api_processes"] == 4
    assert payload["results"][0]["engine"] == "WaveMind external HTTP cluster load"
    assert payload["results"][0]["slo_pass"] is True


def test_loopback_external_runner_rejects_invalid_replication_factor():
    with pytest.raises(ValueError, match="cannot exceed"):
        loopback.run_from_args(_args(nodes=2, replication_factor=3))


def test_loopback_external_runner_rejects_read_fanout_below_quorum():
    with pytest.raises(ValueError, match="cannot be smaller"):
        loopback.run_from_args(_args(read_quorum=2, read_fanout=1))
