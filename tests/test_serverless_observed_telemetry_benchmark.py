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

    def fake_request_json(method, url, payload=None, *, timeout=5.0):
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
        ]
    )
    payload = benchmark.run_from_args(args)

    assert started_nodes
    assert stopped_nodes
    assert payload["source"] == "loopback-api-capacity-estimate"
    assert payload["methodology"].startswith("Measured one real localhost WaveMind API worker")
    assert payload["requests"] == 12
    assert payload["successes"] == 12
    assert payload["failures"] == 0
    assert payload["request_exceptions"] == 0
    assert payload["warmup_queries"] == 3
    assert payload["cache_prewarmed"] is True
    assert payload["operation_serialization"] is False
    assert payload["configured_max_scale"] == 4
    assert payload["requests_per_second"] >= payload["per_replica_requests_per_second"]
    assert payload["observed_slo_pass"] is True


@pytest.mark.parametrize(
    "arguments,error",
    [
        (["--requests", "0"], "--requests must be positive"),
        (["--workers", "0"], "--workers must be positive"),
        (["--seed-memories", "0"], "--seed-memories must be positive"),
        (["--cache-capacity", "-1"], "--cache-capacity cannot be negative"),
        (["--vector-cache-capacity", "-1"], "--vector-cache-capacity cannot be negative"),
        (["--max-scale", "0"], "--max-scale must be positive"),
    ],
)
def test_serverless_observed_telemetry_benchmark_rejects_invalid_args(arguments, error):
    args = benchmark.build_parser().parse_args(arguments)
    with pytest.raises(ValueError, match=error):
        benchmark.run_from_args(args)
