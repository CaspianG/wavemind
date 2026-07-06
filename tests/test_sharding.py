from pathlib import Path

import pytest

from wavemind import (
    ClusterNode,
    DistributedShardedWaveMind,
    DistributedWriteQuorumError,
    HashingTextEncoder,
    HTTPNamespaceShardClient,
    DistributedRepairReport,
    NamespaceShardRouter,
    ShardedWaveMind,
    WaveMind,
)


class LocalWaveMindServiceClient:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.minds = {}

    def _mind(self, address: str) -> WaveMind:
        mind = self.minds.get(address)
        if mind is None:
            mind = WaveMind(
                db_path=self.tmp_path / f"{address}.sqlite3",
                width=32,
                height=32,
                layers=2,
                encoder=HashingTextEncoder(vector_dim=64),
            )
            self.minds[address] = mind
        return mind

    def remember(
        self,
        address: str,
        *,
        text: str,
        namespace: str,
        tags=(),
        ttl_seconds=None,
        metadata=None,
        priority=1.0,
    ) -> int:
        return self._mind(address).remember(
            text,
            namespace=namespace,
            tags=tags,
            ttl_seconds=ttl_seconds,
            metadata=metadata,
            priority=priority,
        )

    def query(
        self,
        address: str,
        *,
        text: str,
        namespace: str,
        top_k: int = 3,
        tags=(),
        min_score=None,
    ):
        return self._mind(address).query(
            text,
            namespace=namespace,
            top_k=top_k,
            tags=tags,
            min_score=min_score,
        )

    def forget(
        self,
        address: str,
        *,
        namespace: str,
        id=None,
        text=None,
    ) -> int:
        return self._mind(address).forget(id=id, text=text, namespace=namespace)

    def export_namespace(
        self,
        address: str,
        *,
        namespace: str,
        limit: int = 1000,
        include_expired: bool = False,
        tags=(),
    ):
        records = self._mind(address).store.list(
            namespace=namespace,
            include_expired=include_expired,
            tags=tags,
        )[:limit]
        return [
            {
                "id": record.id,
                "text": record.text,
                "namespace": record.namespace,
                "tags": list(record.tags),
                "metadata": record.metadata,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "expires_at": record.expires_at,
                "priority": record.priority,
                "access_count": record.access_count,
            }
            for record in records
        ]

    def export_namespace_state(
        self,
        address: str,
        *,
        namespace: str,
        limit: int = 1000,
        include_expired: bool = False,
        tags=(),
        include_tombstones: bool = True,
    ):
        tombstones = []
        if include_tombstones:
            tombstones = [
                {
                    "record_keys": list(event.metadata.get("record_keys", [])),
                    "texts": list(event.metadata.get("texts", [])),
                }
                for event in self._mind(address).audit_events(
                    namespace=namespace,
                    action="distributed_tombstone",
                    limit=10_000,
                )
            ]
        return {
            "records": self.export_namespace(
                address,
                namespace=namespace,
                limit=limit,
                include_expired=include_expired,
                tags=tags,
            ),
            "tombstones": tombstones,
        }

    def log_tombstone(
        self,
        address: str,
        *,
        namespace: str,
        record_keys=(),
        texts=(),
    ) -> int:
        return self._mind(address).store.log_audit_event(
            "distributed_tombstone",
            namespace=namespace,
            metadata={
                "record_keys": sorted(record_keys),
                "texts": sorted(texts),
            },
        )

    def close(self):
        for mind in self.minds.values():
            mind.close()


def _two_namespaces_on_different_shards(router: NamespaceShardRouter) -> tuple[str, str]:
    first = "tenant:0"
    first_shard = router.shard_for(first)
    for index in range(1, 200):
        candidate = f"tenant:{index}"
        if router.shard_for(candidate) != first_shard:
            return first, candidate
    raise AssertionError("could not find two different shards")


def test_namespace_shard_router_is_stable_and_creates_safe_paths(tmp_path):
    router = NamespaceShardRouter(tmp_path, shard_count=8)

    assert router.shard_for("tenant:a") == router.shard_for("tenant:a")
    assert router.db_path("tenant:a").parent == tmp_path
    assert router.db_path("tenant:a").name.startswith("shard-")


def test_http_namespace_shard_client_bypasses_proxy_env_by_default():
    client = HTTPNamespaceShardClient()
    trusted = HTTPNamespaceShardClient(trust_env=True)

    assert client.trust_env is False
    assert client._opener is not None
    assert trusted.trust_env is True
    assert trusted._opener is None


def test_sharded_wavemind_routes_namespaces_to_isolated_databases(tmp_path):
    router = NamespaceShardRouter(tmp_path / "shards", shard_count=8)
    left, right = _two_namespaces_on_different_shards(router)
    memory = ShardedWaveMind(
        root_path=router.root_path,
        shard_count=router.shard_count,
        width=32,
        height=32,
        layers=2,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    try:
        memory.remember("left tenant billing preference", namespace=left)
        memory.remember("right tenant support preference", namespace=right)

        left_results = memory.query("billing preference", namespace=left, top_k=1)
        right_results = memory.query("support preference", namespace=right, top_k=1)

        assert left_results[0].text == "left tenant billing preference"
        assert right_results[0].text == "right tenant support preference"
        assert router.db_path(left).exists()
        assert router.db_path(right).exists()
        assert router.db_path(left) != router.db_path(right)
        assert memory.stats()["shard_files"] == 2
    finally:
        memory.close()


def test_sharded_wavemind_rejects_global_db_path(tmp_path):
    with pytest.raises(ValueError, match="db_path"):
        ShardedWaveMind(root_path=tmp_path, db_path=Path("single.sqlite3"))


def test_sharded_wavemind_can_backup_open_shards(tmp_path):
    backup_dir = tmp_path / "backup"
    memory = ShardedWaveMind(
        root_path=tmp_path / "shards",
        shard_count=4,
        width=32,
        height=32,
        layers=2,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    try:
        memory.remember("backup sharded memory", namespace="tenant:backup")
        backups = memory.save(backup_dir)

        assert len(backups) == 1
        assert backups[0].exists()
        assert backups[0].parent == backup_dir
    finally:
        memory.close()


def test_distributed_sharded_wavemind_routes_to_replicas_and_reads_after_primary_loss(tmp_path):
    client = LocalWaveMindServiceClient(tmp_path / "services")
    memory = DistributedShardedWaveMind(
        nodes=[
            ClusterNode(id="node-a", address="node-a", zone="zone-a"),
            ClusterNode(id="node-b", address="node-b", zone="zone-b"),
            ClusterNode(id="node-c", address="node-c", zone="zone-c"),
        ],
        replication_factor=2,
        client=client,
    )
    try:
        namespace = "tenant:distributed"
        write = memory.remember(
            "distributed shard keeps tenant memory",
            namespace=namespace,
        )

        assert write.ok
        assert len(write.writes) == 2
        assert set(write.writes) == set(memory.placement(namespace).replicas)

        memory.set_node_available(write.primary_node, False)
        results = memory.query("tenant memory", namespace=namespace, top_k=1)

        assert results[0].text == "distributed shard keeps tenant memory"
        assert results[0].metadata["_wavemind_node"] != write.primary_node
    finally:
        client.close()


def test_distributed_sharded_wavemind_enforces_write_quorum(tmp_path):
    client = LocalWaveMindServiceClient(tmp_path / "services")
    memory = DistributedShardedWaveMind(
        nodes=["node-a", "node-b", "node-c"],
        replication_factor=3,
        client=client,
    )
    namespace = "tenant:quorum"
    placement = memory.placement(namespace)
    memory.set_node_available(placement.replicas[0], False)
    memory.set_node_available(placement.replicas[1], False)

    try:
        with pytest.raises(DistributedWriteQuorumError):
            memory.remember("quorum protected memory", namespace=namespace)
    finally:
        client.close()


def test_distributed_sharded_wavemind_forget_replicates_delete(tmp_path):
    client = LocalWaveMindServiceClient(tmp_path / "services")
    memory = DistributedShardedWaveMind(
        nodes=["node-a", "node-b", "node-c"],
        replication_factor=2,
        client=client,
    )
    try:
        namespace = "tenant:forget"
        memory.remember("delete this distributed fact", namespace=namespace)
        deleted = memory.forget(
            namespace=namespace,
            text="delete this distributed fact",
        )

        assert deleted.ok
        assert deleted.deleted == 2
        assert memory.query("distributed fact", namespace=namespace, top_k=1) == []
    finally:
        client.close()


def test_distributed_sharded_wavemind_repairs_missing_replica_record(tmp_path):
    client = LocalWaveMindServiceClient(tmp_path / "services")
    memory = DistributedShardedWaveMind(
        nodes=["node-a", "node-b", "node-c"],
        replication_factor=2,
        client=client,
    )
    try:
        namespace = "tenant:repair"
        write = memory.remember(
            "repair missing distributed memory",
            namespace=namespace,
            tags=("ops",),
            metadata={"source": "test"},
            priority=3.0,
        )
        stale_node = next(node for node in write.writes if node != write.primary_node)
        client._mind(stale_node).forget(
            namespace=namespace,
            text="repair missing distributed memory",
        )

        memory.set_node_available(write.primary_node, False)
        assert memory.query("distributed memory", namespace=namespace, top_k=1) == []
        memory.set_node_available(write.primary_node, True)

        report = memory.repair_namespace(namespace, tags=("ops",))

        assert isinstance(report, DistributedRepairReport)
        assert report.ok
        assert report.canonical_records == 1
        assert report.missing_before_repair[stale_node] == 1
        assert report.repaired[stale_node] == 1
        memory.set_node_available(write.primary_node, False)
        repaired = memory.query("distributed memory", namespace=namespace, top_k=1)
        assert repaired[0].text == "repair missing distributed memory"
        assert repaired[0].metadata["source"] == "test"
    finally:
        client.close()


def test_distributed_sharded_wavemind_tombstone_repair_does_not_resurrect_delete(tmp_path):
    client = LocalWaveMindServiceClient(tmp_path / "services")
    memory = DistributedShardedWaveMind(
        nodes=["node-a", "node-b", "node-c"],
        replication_factor=3,
        client=client,
    )
    try:
        namespace = "tenant:service-tombstone"
        write = memory.remember(
            "service repair must not resurrect deleted memory",
            namespace=namespace,
        )
        missed_delete = next(node for node in write.writes if node != write.primary_node)
        memory.set_node_available(missed_delete, False)

        delete = memory.forget(
            namespace=namespace,
            text="service repair must not resurrect deleted memory",
        )

        assert delete.ok
        memory.set_node_available(missed_delete, True)
        assert client._mind(missed_delete).store.count(namespace=namespace) == 1
        assert memory.query("resurrect deleted memory", namespace=namespace, top_k=1) == []

        report = memory.repair_namespace(namespace)

        assert report.ok
        assert report.canonical_records == 0
        assert report.repaired_total == 0
        assert report.tombstone_texts == 1
        assert report.tombstone_deleted == 1
        assert client._mind(missed_delete).store.count(namespace=namespace) == 0
        assert memory.query("resurrect deleted memory", namespace=namespace, top_k=1) == []
    finally:
        client.close()
