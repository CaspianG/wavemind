import argparse
import json
from collections import defaultdict

import pytest

from benchmarks.http_cluster_load_benchmark import (
    load_node_manifest,
    parse_node_specs,
    run_external_batch_query_profile,
    run_from_args,
    validate_external_cluster_payload,
)
from benchmarks.scale_readiness_benchmark import run_sustained_http_cluster_workload
from wavemind import ClusterNode, QueryResult


class FakeHTTPClusterClient:
    def __init__(self):
        self.records = defaultdict(lambda: defaultdict(list))
        self.tombstones = defaultdict(lambda: defaultdict(list))
        self.next_id = 0

    def remember(
        self,
        address,
        *,
        text,
        namespace,
        tags=(),
        ttl_seconds=None,
        metadata=None,
        priority=1.0,
    ):
        self.next_id += 1
        self.records[address][namespace].append(
            {
                "id": self.next_id,
                "text": text,
                "namespace": namespace,
                "tags": list(tags),
                "metadata": dict(metadata or {}),
                "priority": priority,
            }
        )
        return self.next_id

    def query(self, address, *, text, namespace, top_k=3, tags=(), min_score=None):
        records = self.records[address][namespace]
        tombstone_texts = {
            item
            for tombstone in self.tombstones[address][namespace]
            for item in tombstone.get("texts", [])
        }
        results = []
        for record in records:
            if record["text"] in tombstone_texts:
                continue
            results.append(
                QueryResult(
                    id=int(record["id"]),
                    text=str(record["text"]),
                    score=1.0 if text == record["text"] or text in record["text"] else 0.5,
                    vector_score=1.0,
                    field_score=0.0,
                    graph_score=0.0,
                    namespace=namespace,
                    tags=tuple(record.get("tags") or ()),
                    metadata=dict(record.get("metadata") or {}),
                )
            )
        return sorted(results, key=lambda result: result.score, reverse=True)[:top_k]

    def query_batch(self, address, *, queries):
        items = []
        for index, item in enumerate(queries):
            results = self.query(
                address,
                text=item["text"],
                namespace=item["namespace"],
                top_k=int(item.get("top_k", 3)),
                tags=tuple(item.get("tags") or ()),
                min_score=item.get("min_score"),
            )
            items.append(
                {
                    "index": index,
                    "text": item["text"],
                    "namespace": item["namespace"],
                    "results": results,
                }
            )
        return {"count": len(items), "items": items}

    def forget(self, address, *, namespace, id=None, text=None):
        records = self.records[address][namespace]
        kept = []
        deleted = 0
        for record in records:
            if (id is not None and int(record["id"]) == int(id)) or (
                text is not None and record["text"] == text
            ):
                deleted += 1
                continue
            kept.append(record)
        self.records[address][namespace] = kept
        return deleted

    def export_namespace(self, address, *, namespace, limit=1000, include_expired=False, tags=()):
        return [dict(record) for record in self.records[address][namespace]][:limit]

    def export_namespace_state(
        self,
        address,
        *,
        namespace,
        limit=1000,
        include_expired=False,
        tags=(),
        include_tombstones=True,
    ):
        return {
            "records": self.export_namespace(
                address,
                namespace=namespace,
                limit=limit,
                include_expired=include_expired,
                tags=tags,
            ),
            "tombstones": (
                [dict(tombstone) for tombstone in self.tombstones[address][namespace]]
                if include_tombstones
                else []
            ),
        }

    def log_tombstone(self, address, *, namespace, record_keys=(), texts=()):
        self.next_id += 1
        self.tombstones[address][namespace].append(
            {"record_keys": list(record_keys), "texts": list(texts)}
        )
        return self.next_id


def test_parse_node_specs_accepts_ids_urls_and_zones():
    nodes = parse_node_specs(
        ["node-a=http://127.0.0.1:8001", "https://example.test"],
        ["node-a=zone-a"],
    )

    assert nodes[0].id == "node-a"
    assert nodes[0].address == "http://127.0.0.1:8001"
    assert nodes[0].zone == "zone-a"
    assert nodes[1].id == "node-001"
    assert nodes[1].address == "https://example.test"


def test_parse_node_specs_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate node id"):
        parse_node_specs(["node-a=http://one.test", "node-a=http://two.test"])


def test_load_node_manifest_supports_repeatable_service_runs(tmp_path):
    manifest = tmp_path / "nodes.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "wavemind.external_http_cluster.v1",
                "deployment_id": "staging-eu-2026-07-06",
                "environment": "staging",
                "source": "k8s-service",
                "nodes": [
                    {"id": "node-a", "url": "https://node-a.test", "zone": "eu-a"},
                    {"id": "node-b", "address": "https://node-b.test", "zone": "eu-b"},
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = load_node_manifest(manifest)

    assert payload["node_specs"] == [
        "node-a=https://node-a.test",
        "node-b=https://node-b.test",
    ]
    assert payload["zone_specs"] == ["node-a=eu-a", "node-b=eu-b"]
    assert payload["deployment_id"] == "staging-eu-2026-07-06"
    assert payload["environment"] == "staging"
    assert payload["source"] == "k8s-service"


def test_sustained_http_cluster_workload_reports_slo_ready_metrics():
    nodes = [
        ClusterNode(id="node-a", address="http://node-a.test", zone="zone-a"),
        ClusterNode(id="node-b", address="http://node-b.test", zone="zone-b"),
        ClusterNode(id="node-c", address="http://node-c.test", zone="zone-c"),
        ClusterNode(id="node-d", address="http://node-d.test", zone="zone-a"),
    ]

    result = run_sustained_http_cluster_workload(
        nodes,
        client=FakeHTTPClusterClient(),
        engine="test external workload",
        namespace_prefix="tenant:test-http-load",
        namespace_count=3,
        memories_per_namespace=3,
        replication_factor=3,
        max_workers=3,
    )

    assert result["engine"] == "test external workload"
    assert result["nodes"] == 4
    assert result["namespaces"] == 3
    assert result["writes"] == 9
    assert result["failover_queries"] == 9
    assert result["write_success_rate"] == 1.0
    assert result["query_hit_rate"] == 1.0
    assert result["failover_hit_rate"] == 1.0
    assert result["forget_success_rate"] == 1.0
    assert result["delete_suppression_rate"] == 1.0
    assert result["repair_missing_before"] is True
    assert result["repair_ok"] is True
    assert result["repair_repaired_total"] >= 1
    assert result["repaired_replica"] is True
    assert result["success_rate"] == 1.0
    assert result["error_count"] == 0


def test_external_batch_query_profile_compares_individual_and_batch_requests():
    nodes = [
        ClusterNode(id="node-a", address="http://node-a.test", zone="zone-a"),
        ClusterNode(id="node-b", address="http://node-b.test", zone="zone-b"),
        ClusterNode(id="node-c", address="http://node-c.test", zone="zone-c"),
    ]

    result = run_external_batch_query_profile(
        nodes=nodes,
        client=FakeHTTPClusterClient(),
        namespace="tenant:test-external-batch",
        batch_size=12,
    )

    assert result["success"] is True
    assert result["individual_success"] is True
    assert result["batch_success"] is True
    assert result["individual_node"] == "node-a"
    assert result["batch_node"] == "node-b"
    assert result["write_node_count"] == 3
    assert result["individual_http_requests"] == 12
    assert result["batch_http_requests"] == 1
    assert result["request_reduction_ratio"] >= 0.9


def test_http_cluster_load_cli_payload_uses_external_engine(tmp_path):
    output = tmp_path / "http_cluster_load.json"
    args = argparse.Namespace(
        node=[
            "node-a=http://node-a.test",
            "node-b=http://node-b.test",
            "node-c=http://node-c.test",
            "node-d=http://node-d.test",
        ],
        nodes_file=None,
        zone=[],
        api_key=None,
        timeout=15.0,
        replication_factor=3,
        write_quorum=None,
        read_quorum=1,
        read_fanout=None,
        namespace_prefix="tenant:test-cli",
        deployment_id="test-deployment",
        environment="test",
        source="unit-test",
        namespace_count=2,
        memories_per_namespace=2,
        workers=2,
        batch_query_size=12,
        min_success_rate=1.0,
        min_failover_hit_rate=0.95,
        p99_slo_ms=1000.0,
        fail_on_slo=False,
        output=output,
    )

    from benchmarks import http_cluster_load_benchmark as benchmark

    original_client = benchmark.HTTPNamespaceShardClient
    benchmark.HTTPNamespaceShardClient = lambda **kwargs: FakeHTTPClusterClient()
    try:
        payload = run_from_args(args)
    finally:
        benchmark.HTTPNamespaceShardClient = original_client

    assert payload["scenario"]["name"] == "http_cluster_load"
    assert payload["scenario"]["node_count"] == 4
    assert payload["scenario"]["node_addresses"] == [
        "http://node-a.test",
        "http://node-b.test",
        "http://node-c.test",
        "http://node-d.test",
    ]
    assert payload["scenario"]["read_fanout"] == 3
    assert payload["scenario"]["deployment_id"] == "test-deployment"
    assert payload["scenario"]["environment"] == "test"
    assert payload["scenario"]["source"] == "unit-test"
    result = payload["results"][0]
    assert result["engine"] == "WaveMind external HTTP cluster load"
    assert result["slo_pass"] is True
    assert result["batch_query"]["success"] is True
    assert result["batch_query"]["individual_http_requests"] == 12
    assert result["batch_query"]["batch_http_requests"] == 1
    assert result["batch_query"]["request_reduction_ratio"] >= 0.9
    output.write_text(json.dumps(payload), encoding="utf-8")
    assert json.loads(output.read_text(encoding="utf-8"))["results"][0]["slo_pass"] is True


def test_http_cluster_load_cli_accepts_nodes_file(tmp_path):
    manifest = tmp_path / "nodes.json"
    manifest.write_text(
        json.dumps(
            {
                "deployment_id": "manifest-deployment",
                "environment": "staging",
                "source": "manifest",
                "nodes": [
                    {"id": "node-a", "url": "http://node-a.test", "zone": "zone-a"},
                    {"id": "node-b", "url": "http://node-b.test", "zone": "zone-b"},
                    {"id": "node-c", "url": "http://node-c.test", "zone": "zone-c"},
                    {"id": "node-d", "url": "http://node-d.test", "zone": "zone-a"},
                ],
            }
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        node=[],
        nodes_file=manifest,
        zone=[],
        api_key=None,
        timeout=15.0,
        replication_factor=3,
        write_quorum=None,
        read_quorum=1,
        read_fanout=1,
        namespace_prefix="tenant:test-manifest",
        deployment_id=None,
        environment=None,
        source=None,
        namespace_count=2,
        memories_per_namespace=2,
        workers=2,
        batch_query_size=12,
        min_success_rate=1.0,
        min_failover_hit_rate=0.95,
        p99_slo_ms=1000.0,
        fail_on_slo=False,
        output=tmp_path / "http_cluster_load.json",
    )

    from benchmarks import http_cluster_load_benchmark as benchmark

    original_client = benchmark.HTTPNamespaceShardClient
    benchmark.HTTPNamespaceShardClient = lambda **kwargs: FakeHTTPClusterClient()
    try:
        payload = run_from_args(args)
    finally:
        benchmark.HTTPNamespaceShardClient = original_client

    assert payload["scenario"]["node_count"] == 4
    assert payload["scenario"]["node_ids"] == ["node-a", "node-b", "node-c", "node-d"]
    assert payload["scenario"]["zones"] == ["zone-a", "zone-b", "zone-c"]
    assert payload["scenario"]["deployment_id"] == "manifest-deployment"
    assert payload["scenario"]["environment"] == "staging"
    assert payload["scenario"]["source"] == "manifest"


def test_external_cluster_payload_validator_reports_missing_and_pass(tmp_path):
    missing = validate_external_cluster_payload(None)
    assert missing["status"] == "action_required"
    assert "missing artifact" in missing["issues"]

    args = argparse.Namespace(
        node=[
            "node-a=http://node-a.test",
            "node-b=http://node-b.test",
            "node-c=http://node-c.test",
            "node-d=http://node-d.test",
        ],
        nodes_file=None,
        zone=[],
        api_key=None,
        timeout=15.0,
        replication_factor=3,
        write_quorum=None,
        read_quorum=1,
        read_fanout=1,
        namespace_prefix="tenant:test-validator",
        deployment_id="validator-deployment",
        environment="staging",
        source="unit-test",
        namespace_count=32,
        memories_per_namespace=8,
        workers=2,
        batch_query_size=12,
        min_success_rate=1.0,
        min_failover_hit_rate=0.95,
        p99_slo_ms=1000.0,
        fail_on_slo=False,
        output=tmp_path / "http_cluster_load.json",
    )

    from benchmarks import http_cluster_load_benchmark as benchmark

    original_client = benchmark.HTTPNamespaceShardClient
    benchmark.HTTPNamespaceShardClient = lambda **kwargs: FakeHTTPClusterClient()
    try:
        payload = run_from_args(args)
    finally:
        benchmark.HTTPNamespaceShardClient = original_client

    evidence = validate_external_cluster_payload(payload)

    assert evidence["status"] == "pass"
    assert evidence["issues"] == []
    assert "validator-deployment" in evidence["evidence"]
