from __future__ import annotations

from collections import defaultdict
from typing import Any

from wavemind.cli import build_parser, main
from wavemind.cluster import ClusterNode
from wavemind.cluster_drill import build_cluster_drill_items, run_cluster_drill
from wavemind.core import QueryResult
from wavemind.sharding import DistributedShardedWaveMind


class _ClusterDrillClient:
    def __init__(self) -> None:
        self.records: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.failed_addresses: set[str] = set()

    def _check(self, address: str) -> None:
        if address in self.failed_addresses:
            raise RuntimeError(f"physical network failure for {address}")

    def remember_batch(self, address: str, *, items: list[dict[str, Any]]) -> dict[str, Any]:
        self._check(address)
        response = []
        for index, item in enumerate(items):
            record = dict(item)
            record["id"] = len(self.records[address]) + 1
            self.records[address].append(record)
            response.append({"index": index, "id": record["id"]})
        return {"count": len(response), "items": response}

    def export_namespace_state(
        self,
        address: str,
        *,
        namespace: str,
        limit: int,
        include_tombstones: bool = True,
        **_: Any,
    ) -> dict[str, Any]:
        self._check(address)
        records = [
            dict(record)
            for record in self.records[address]
            if record["namespace"] == namespace
        ]
        if limit >= 0:
            records = records[:limit]
        return {"records": records, "tombstones": [] if include_tombstones else []}

    def query_batch(self, address: str, *, queries: list[dict[str, Any]]) -> dict[str, Any]:
        self._check(address)
        items = []
        for index, query in enumerate(queries):
            matching = [
                record
                for record in self.records[address]
                if record["namespace"] == query["namespace"]
                and record["text"] == query["text"]
            ]
            results = [
                QueryResult(
                    id=int(record["id"]),
                    text=str(record["text"]),
                    score=1.0,
                    vector_score=1.0,
                    field_score=0.0,
                    graph_score=0.0,
                    namespace=str(record["namespace"]),
                    tags=tuple(record.get("tags") or ()),
                    metadata=dict(record.get("metadata") or {}),
                )
                for record in matching
            ]
            items.append({"index": index, "results": results})
        return {"count": len(items), "items": items}


def _memory(client: _ClusterDrillClient) -> DistributedShardedWaveMind:
    return DistributedShardedWaveMind(
        nodes=[
            ClusterNode(
                id=f"node-{letter}",
                address=f"http://node-{letter}.cluster.local:8000",
                zone=f"zone-{letter}",
            )
            for letter in "abcd"
        ],
        replication_factor=3,
        write_quorum=2,
        read_quorum=1,
        read_fanout=3,
        client=client,
    )


def test_cluster_drill_survives_real_client_network_failure():
    client = _ClusterDrillClient()
    memory = _memory(client)

    seed = run_cluster_drill(
        memory,
        mode="seed",
        namespace_prefix="failure-drill",
        namespace_count=8,
        memories_per_namespace=4,
    )
    failed_node = memory.placement("failure-drill:0000").replicas[0]
    failed_address = next(node.address for node in memory.nodes if node.id == failed_node)
    client.failed_addresses.add(failed_address)
    verify = run_cluster_drill(
        memory,
        mode="verify",
        namespace_prefix="failure-drill",
        namespace_count=8,
        memories_per_namespace=4,
    )

    assert seed["status"] == "pass"
    assert seed["written_memories"] == seed["expected_memories"] == 32
    assert all(value > 0 for value in seed["node_writes"].values())
    assert verify["status"] == "pass"
    assert verify["hit_rate"] == 1.0
    assert failed_node in verify["failed_nodes_seen"]
    assert verify["node_health"][failed_node]["status"] == "degraded"


def test_cluster_drill_items_are_deterministic_and_namespace_scoped():
    first = build_cluster_drill_items(
        namespace_prefix="stable",
        namespace_count=2,
        memories_per_namespace=2,
    )
    second = build_cluster_drill_items(
        namespace_prefix="stable",
        namespace_count=2,
        memories_per_namespace=2,
    )

    assert first == second
    assert {item["namespace"] for item in first} == {"stable:0000", "stable:0001"}
    assert len({item["metadata"]["verification_token"] for item in first}) == 4


def test_cluster_drill_cli_contract_and_zone_validation(capsys):
    args = build_parser().parse_args(
        [
            "cluster-drill",
            "--mode",
            "verify",
            "--node",
            "node-a=http://node-a:8000",
            "--zone",
            "node-a=zone-a",
        ]
    )
    assert args.command == "cluster-drill"
    assert args.mode == "verify"
    assert args.replication_factor == 3

    exit_code = main(
        [
            "cluster-drill",
            "--mode",
            "verify",
            "--node",
            "node-a=http://node-a:8000",
            "--zone",
            "unknown=zone-a",
        ]
    )
    assert exit_code == 2
    assert "unknown nodes" in capsys.readouterr().err
