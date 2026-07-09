from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchmarks import serverless_observed_telemetry_benchmark as benchmark


def test_serverless_observed_telemetry_benchmark_emits_capacity(monkeypatch):
    started_nodes = []
    stopped_nodes = []

    def fake_start_api_node(root, node_id, **kwargs):
        node = SimpleNamespace(address=f"http://{node_id}.local")
        started_nodes.append((root, node_id, kwargs))
        return node

    def fake_stop_api_nodes(nodes):
        stopped_nodes.extend(nodes)

    def fake_request_json(method, url, payload=None, *, api_key=None, timeout=5.0):
        assert api_key is None
        if url.endswith("/remember"):
            return {"id": len(str(payload.get("text", "")))}
        if url.endswith("/query"):
            return {"results": [{"text": payload["text"]}]}
        raise AssertionError(f"unexpected request {method} {url}")

    monkeypatch.setattr(benchmark, "start_api_node", fake_start_api_node)
    monkeypatch.setattr(benchmark, "stop_api_nodes", fake_stop_api_nodes)
    monkeypatch.setattr(benchmark, "request_json", fake_request_json)

    args = benchmark.build_parser().parse_args(
        [
            "--requests",
            "12",
            "--workers",
            "3",
            "--seed-memories",
            "3",
            "--max-scale",
            "4",
            "--target-rps",
            "1",
            "--target-p99-ms",
            "10000",
            "--cold-start-budget-ms",
            "10000",
        ]
    )
    payload = benchmark.run_from_args(args)

    assert started_nodes
    assert stopped_nodes
    assert payload["source"] == "loopback-api-capacity-estimate"
    assert payload["node_mode"] == "loopback"
    assert payload["methodology"].startswith("Measured a balanced pool")
    assert payload["requests"] == 12
    assert payload["successes"] == 12
    assert payload["failures"] == 0
    assert payload["request_exceptions"] == 0
    assert payload["measured_replicas"] == 4
    assert payload["external_node_count"] == 0
    assert len(started_nodes) == 4
    assert payload["seed_mode"] == "all"
    assert payload["warmup_queries"] == 12
    assert payload["cache_prewarmed"] is True
    assert payload["cold_start_measured"] is True
    assert payload["operation_serialization"] is False
    assert payload["configured_max_scale"] == 4
    assert payload["horizontal_capacity_estimate"] is True
    assert payload["measured_pool_requests_per_second"] >= payload["per_replica_requests_per_second"]
    assert payload["requests_per_second"] >= payload["per_replica_requests_per_second"]
    assert payload["observed_slo_pass"] is True


def test_serverless_observed_telemetry_benchmark_measures_external_nodes(monkeypatch):
    started_nodes = []
    stopped_nodes = []
    calls = []

    def fail_start_api_node(*args, **kwargs):
        started_nodes.append((args, kwargs))
        raise AssertionError("external mode must not start local API nodes")

    def fake_stop_api_nodes(nodes):
        stopped_nodes.extend(nodes)

    def fake_request_json(method, url, payload=None, *, api_key=None, timeout=5.0):
        calls.append((method, url, dict(payload or {}), api_key, timeout))
        assert api_key == "secret"
        if url.endswith("/remember"):
            return {"id": len(str(payload.get("text", "")))}
        if url.endswith("/query"):
            return {"results": [{"text": payload["text"]}]}
        raise AssertionError(f"unexpected request {method} {url}")

    monkeypatch.setattr(benchmark, "start_api_node", fail_start_api_node)
    monkeypatch.setattr(benchmark, "stop_api_nodes", fake_stop_api_nodes)
    monkeypatch.setattr(benchmark, "request_json", fake_request_json)

    args = benchmark.build_parser().parse_args(
        [
            "--node",
            "https://node-a.example/",
            "--node",
            "http://node-b.example",
            "--api-key",
            "secret",
            "--seed-mode",
            "first",
            "--external-cold-start-ms",
            "1200",
            "--requests",
            "8",
            "--workers",
            "2",
            "--seed-memories",
            "2",
            "--max-scale",
            "4",
            "--target-rps",
            "1",
            "--target-p99-ms",
            "10000",
            "--cold-start-budget-ms",
            "20000",
        ]
    )
    payload = benchmark.run_from_args(args)

    assert not started_nodes
    assert not stopped_nodes
    assert payload["source"] == "external-api-pool-capacity-estimate"
    assert payload["node_mode"] == "external"
    assert payload["methodology"].startswith("Measured a balanced pool of user-supplied")
    assert payload["measured_replicas"] == 2
    assert payload["external_node_count"] == 2
    assert payload["seed_mode"] == "first"
    assert payload["seed_memories"] == 2
    assert payload["warmup_queries"] == 4
    assert payload["cold_start_ms"] == 1200
    assert payload["cold_start_avg_ms"] == 1200
    assert payload["cold_start_measured"] is False
    assert payload["requests"] == 8
    assert payload["successes"] == 8
    assert payload["request_exceptions"] == 0
    assert payload["configured_max_scale"] == 4
    assert payload["observed_slo_pass"] is True
    assert any(call[1] == "https://node-a.example/remember" for call in calls)
    assert any(call[1] == "http://node-b.example/query" for call in calls)


@pytest.mark.parametrize(
    "arguments,error",
    [
        (["--requests", "0"], "--requests must be positive"),
        (["--workers", "0"], "--workers must be positive"),
        (["--replicas", "0"], "--replicas must be positive"),
        (["--replicas", "5", "--max-scale", "4"], "--replicas must be <= --max-scale"),
        (["--seed-memories", "0"], "--seed-memories must be positive"),
        (["--cache-capacity", "-1"], "--cache-capacity cannot be negative"),
        (["--vector-cache-capacity", "-1"], "--vector-cache-capacity cannot be negative"),
        (["--max-scale", "0"], "--max-scale must be positive"),
        (
            ["--node", "ftp://node.example"],
            "--node URLs must start with http:// or https://",
        ),
        (
            ["--node", "http://a.example", "--node", "http://b.example", "--max-scale", "1"],
            "--node count must be <= --max-scale",
        ),
        (
            ["--external-cold-start-ms", "-1"],
            "--external-cold-start-ms cannot be negative",
        ),
    ],
)
def test_serverless_observed_telemetry_benchmark_rejects_invalid_args(arguments, error):
    args = benchmark.build_parser().parse_args(arguments)
    with pytest.raises(ValueError, match=error):
        benchmark.run_from_args(args)
