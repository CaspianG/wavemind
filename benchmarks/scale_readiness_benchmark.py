from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import (
    CachePrewarmWorker,
    ClusterNode,
    DistributedRepairWorker,
    DistributedShardedWaveMind,
    HashingTextEncoder,
    HotMemoryCache,
    QueryResult,
    ReplicatedObjectStoreDrillWorker,
    ReplicatedWaveMind,
    ReplicatedSnapshotWorker,
    S3SnapshotStore,
    WaveMind,
    audio_payload,
    build_cluster_plan,
    event_payload,
    image_payload,
    query_with_cache,
    remember_payload,
    table_payload,
)


class InMemoryS3Client:
    def __init__(self):
        self.objects: dict[tuple[str, str], dict[str, object]] = {}
        self.counter = 0

    def upload_file(self, filename: str, bucket: str, key: str, ExtraArgs=None):
        self.counter += 1
        self.objects[(bucket, key)] = {
            "Body": Path(filename).read_bytes(),
            "Metadata": dict((ExtraArgs or {}).get("Metadata") or {}),
            "LastModified": f"2026-01-01T00:00:{self.counter:02d}Z",
        }

    def head_object(self, Bucket: str, Key: str) -> dict[str, object]:
        payload = self.objects[(Bucket, Key)]
        body = payload["Body"]
        return {
            "ContentLength": len(body),
            "Metadata": dict(payload["Metadata"]),
            "ETag": '"benchmark-etag"',
        }

    def list_objects_v2(
        self,
        Bucket: str,
        Prefix: str = "",
        ContinuationToken: str | None = None,
    ) -> dict[str, object]:
        contents = []
        for (bucket, key), payload in self.objects.items():
            if bucket == Bucket and key.startswith(Prefix):
                body = payload["Body"]
                contents.append(
                    {
                        "Key": key,
                        "Size": len(body),
                        "LastModified": payload["LastModified"],
                        "ETag": '"benchmark-etag"',
                    }
                )
        return {"Contents": sorted(contents, key=lambda item: item["Key"])}

    def delete_objects(self, Bucket: str, Delete: dict[str, object]) -> dict[str, object]:
        deleted = []
        for item in Delete["Objects"]:
            key = item["Key"]
            self.objects.pop((Bucket, key), None)
            deleted.append({"Key": key})
        return {"Deleted": deleted}

    def get_object(self, Bucket: str, Key: str) -> dict[str, object]:
        return {"Body": BytesIO(self.objects[(Bucket, Key)]["Body"])}


class LocalWaveMindServiceClient:
    def __init__(self, root: Path):
        self.root = root
        self.minds: dict[str, WaveMind] = {}

    def remember(
        self,
        address: str,
        *,
        text: str,
        namespace: str,
        tags: tuple[str, ...] = (),
        ttl_seconds: float | None = None,
        metadata: dict[str, object] | None = None,
        priority: float = 1.0,
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
        tags: tuple[str, ...] = (),
        min_score: float | None = None,
    ) -> list[QueryResult]:
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
        id: int | None = None,
        text: str | None = None,
    ) -> int:
        return self._mind(address).forget(
            id=id,
            text=text,
            namespace=namespace,
        )

    def export_namespace(
        self,
        address: str,
        *,
        namespace: str,
        limit: int = 1000,
        include_expired: bool = False,
        tags: tuple[str, ...] = (),
    ) -> list[dict[str, object]]:
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
        tags: tuple[str, ...] = (),
        include_tombstones: bool = True,
    ) -> dict[str, object]:
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
        record_keys: tuple[str, ...] = (),
        texts: tuple[str, ...] = (),
    ) -> int:
        return self._mind(address).store.log_audit_event(
            "distributed_tombstone",
            namespace=namespace,
            metadata={
                "record_keys": sorted(record_keys),
                "texts": sorted(texts),
            },
        )

    def close(self) -> None:
        for mind in self.minds.values():
            mind.close()
        self.minds.clear()

    def _mind(self, address: str) -> WaveMind:
        mind = self.minds.get(address)
        if mind is None:
            mind = WaveMind(
                db_path=self.root / f"{address}.sqlite3",
                width=16,
                height=16,
                layers=1,
                encoder=HashingTextEncoder(vector_dim=64),
            )
            self.minds[address] = mind
        return mind


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[index]


def run_cluster_profile(
    *,
    namespace_count: int,
    node_count: int,
    replication_factor: int,
    simulated_memories: int,
) -> dict[str, object]:
    namespaces = [f"tenant:{index}" for index in range(namespace_count)]
    nodes = [
        ClusterNode(
            id=f"node-{index}",
            address=f"wavemind-{index}.wavemind.svc.cluster.local:8000",
            zone=f"zone-{index % 3}",
        )
        for index in range(node_count)
    ]
    started = time.perf_counter()
    plan = build_cluster_plan(
        namespaces=namespaces,
        nodes=nodes,
        replication_factor=replication_factor,
    )
    placement_ms = (time.perf_counter() - started) * 1000.0
    loads = list(plan.node_load.values())
    primary_loads = list(plan.primary_load.values())
    losses = [plan.simulate_node_loss(node.id) for node in nodes]
    min_availability = min(float(loss["availability_ratio"]) for loss in losses)
    quorum = plan.quorum_report()
    repair_cronjob = plan.kubernetes_repair_cronjob(api_key_secret="wavemind-api-key")
    repair_container = repair_cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    repair_args = list(repair_container["args"])
    return {
        "engine": "WaveMind cluster planner",
        "simulated_memories": simulated_memories,
        "namespaces": namespace_count,
        "nodes": node_count,
        "replication_factor": replication_factor,
        "placement_ms": placement_ms,
        "max_replica_load": max(loads) if loads else 0,
        "min_replica_load": min(loads) if loads else 0,
        "replica_load_stdev": statistics.pstdev(loads) if len(loads) > 1 else 0.0,
        "max_primary_load": max(primary_loads) if primary_loads else 0,
        "min_primary_load": min(primary_loads) if primary_loads else 0,
        "node_loss_min_availability": min_availability,
        "zone_loss_min_availability": quorum["zone_loss_min_availability"],
        "read_quorum": quorum["read_quorum"],
        "write_quorum": quorum["write_quorum"],
        "kubernetes_manifest_kind": plan.kubernetes_manifest()["kind"],
        "kubernetes_repair_cronjob_kind": repair_cronjob["kind"],
        "kubernetes_repair_cronjob_namespaces": repair_args.count("--namespace"),
    }


def run_cache_profile(*, queries: int, capacity: int) -> dict[str, object]:
    cache = HotMemoryCache(capacity=capacity, ttl_seconds=120)
    latencies: list[float] = []
    hot_queries = [
        "budget preference",
        "support escalation",
        "trading profile",
        "security requirements",
        "reporting cadence",
    ]
    namespace_mod = max(1, min(32, capacity // max(1, len(hot_queries))))
    namespaces = [f"tenant:{index % namespace_mod}" for index in range(queries)]
    result = [
        QueryResult(
            id=1,
            text="cached hot memory",
            score=1.0,
            vector_score=1.0,
            field_score=0.0,
            graph_score=0.0,
            namespace="tenant:0",
        )
    ]
    for index, namespace in enumerate(namespaces):
        query = hot_queries[index % len(hot_queries)]
        started = time.perf_counter()
        cached = cache.get(namespace, query, top_k=3)
        if cached is None:
            cache.put(namespace, query, result, top_k=3)
        latencies.append((time.perf_counter() - started) * 1000.0)
    stats = cache.stats()
    prewarm_report_warmed = 0
    prewarm_hit = False
    with tempfile.TemporaryDirectory() as directory:
        memory = WaveMind(
            db_path=Path(directory) / "prewarm.sqlite3",
            encoder=HashingTextEncoder(vector_dim=64),
            width=16,
            height=16,
            layers=1,
            audit_queries=True,
        )
        prewarm_cache = HotMemoryCache(capacity=32, ttl_seconds=120)
        try:
            memory.remember("hot cached budget preference", namespace="tenant:prewarm")
            memory.query("budget preference", namespace="tenant:prewarm", top_k=1)
            memory.query("budget preference", namespace="tenant:prewarm", top_k=1)
            prewarm = CachePrewarmWorker(memory, prewarm_cache).run_once(
                namespace="tenant:prewarm",
                audit_limit=16,
                max_queries=4,
                min_frequency=2,
                top_k=1,
            )
            prewarm_report_warmed = prewarm.warmed
            cached = query_with_cache(
                memory,
                prewarm_cache,
                "budget preference",
                namespace="tenant:prewarm",
                top_k=1,
            )
            prewarm_hit = bool(cached) and prewarm_cache.stats().hits > 0
        finally:
            memory.close()
    return {
        "engine": "WaveMind hot cache",
        "queries": queries,
        "capacity": capacity,
        "hit_rate": stats.hit_rate,
        "evictions": stats.evictions,
        "prewarm_warmed": prewarm_report_warmed,
        "prewarm_hit": prewarm_hit,
        "avg_lookup_ms": statistics.mean(latencies) if latencies else 0.0,
        "p99_lookup_ms": percentile(latencies, 99),
    }


def run_distributed_sharding_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        client = LocalWaveMindServiceClient(Path(directory) / "services")
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
            started = time.perf_counter()
            write = memory.remember(
                "distributed service shard keeps tenant memory",
                namespace=namespace,
            )
            write_ms = (time.perf_counter() - started) * 1000.0
            placement = memory.placement(namespace)
            memory.set_node_available(placement.primary, False)
            query_started = time.perf_counter()
            results = memory.query("tenant memory", namespace=namespace, top_k=1)
            query_after_primary_loss_ms = (time.perf_counter() - query_started) * 1000.0
            recalled_after_primary_loss = bool(results) and results[0].text == (
                "distributed service shard keeps tenant memory"
            )
            memory.set_node_available(placement.primary, True)
            stale_node = next(node for node in placement.replicas if node != placement.primary)
            client._mind(stale_node).forget(
                namespace=namespace,
                text="distributed service shard keeps tenant memory",
            )
            memory.set_node_available(placement.primary, False)
            missing_before_repair = (
                memory.query("tenant memory", namespace=namespace, top_k=1) == []
            )
            memory.set_node_available(placement.primary, True)
            repair = memory.repair_namespace(namespace)
            memory.set_node_available(placement.primary, False)
            repaired_results = memory.query("tenant memory", namespace=namespace, top_k=1)
            recalled_after_repair = bool(repaired_results) and repaired_results[0].text == (
                "distributed service shard keeps tenant memory"
            )
            memory.set_node_available(placement.primary, True)
            forget = memory.forget(
                namespace=namespace,
                text="distributed service shard keeps tenant memory",
            )

            tombstone_memory = DistributedShardedWaveMind(
                nodes=[
                    ClusterNode(id="node-a", address="node-a", zone="zone-a"),
                    ClusterNode(id="node-b", address="node-b", zone="zone-b"),
                    ClusterNode(id="node-c", address="node-c", zone="zone-c"),
                ],
                replication_factor=3,
                client=client,
            )
            tombstone_namespace = "tenant:distributed-tombstone"
            tombstone_text = "service repair must not resurrect deleted memory"
            tombstone_memory.remember(tombstone_text, namespace=tombstone_namespace)
            tombstone_placement = tombstone_memory.placement(tombstone_namespace)
            missed_delete = tombstone_placement.replicas[-1]
            tombstone_memory.set_node_available(missed_delete, False)
            tombstone_memory.forget(namespace=tombstone_namespace, text=tombstone_text)
            tombstone_memory.set_node_available(missed_delete, True)
            tombstone_stale_records_before = client._mind(missed_delete).store.count(
                namespace=tombstone_namespace
            )
            tombstone_suppressed_before_repair = (
                tombstone_memory.query(
                    "resurrect deleted memory",
                    namespace=tombstone_namespace,
                    top_k=1,
                )
                == []
            )
            tombstone_repair = tombstone_memory.repair_namespace(tombstone_namespace)
            tombstone_stale_records_after = client._mind(missed_delete).store.count(
                namespace=tombstone_namespace
            )
            tombstone_suppressed_after_repair = (
                tombstone_memory.query(
                    "resurrect deleted memory",
                    namespace=tombstone_namespace,
                    top_k=1,
                )
                == []
            )

            worker_memory = DistributedShardedWaveMind(
                nodes=[
                    ClusterNode(id="node-a", address="node-a", zone="zone-a"),
                    ClusterNode(id="node-b", address="node-b", zone="zone-b"),
                    ClusterNode(id="node-c", address="node-c", zone="zone-c"),
                ],
                replication_factor=3,
                client=client,
            )
            worker_repair_namespace = "tenant:distributed-worker-repair"
            worker_repair_write = worker_memory.remember(
                "anti entropy worker copies missing service replica",
                namespace=worker_repair_namespace,
            )
            worker_missing_node = next(
                node
                for node in worker_repair_write.writes
                if node != worker_repair_write.primary_node
            )
            client._mind(worker_missing_node).forget(
                namespace=worker_repair_namespace,
                text="anti entropy worker copies missing service replica",
            )
            worker_tombstone_namespace = "tenant:distributed-worker-tombstone"
            worker_tombstone_text = "anti entropy worker removes stale deleted memory"
            worker_memory.remember(worker_tombstone_text, namespace=worker_tombstone_namespace)
            worker_tombstone_placement = worker_memory.placement(worker_tombstone_namespace)
            worker_missed_delete = worker_tombstone_placement.replicas[-1]
            worker_memory.set_node_available(worker_missed_delete, False)
            worker_memory.forget(
                namespace=worker_tombstone_namespace,
                text=worker_tombstone_text,
            )
            worker_memory.set_node_available(worker_missed_delete, True)
            worker_report = DistributedRepairWorker(worker_memory).run_once(
                namespaces=(worker_repair_namespace, worker_tombstone_namespace)
            )
            return {
                "engine": "WaveMind distributed sharding",
                "nodes": len(memory.nodes),
                "replication_factor": memory.replication_factor,
                "write_quorum": memory.write_quorum,
                "read_quorum": memory.read_quorum,
                "writes": len(write.writes),
                "primary_node": placement.primary,
                "replica_nodes": list(placement.replicas),
                "recalled_after_primary_loss": recalled_after_primary_loss,
                "repair_missing_before": missing_before_repair,
                "repair_repaired_total": repair.repaired_total,
                "repair_ok": repair.ok,
                "recalled_after_repair": recalled_after_repair,
                "forget_replicated_deletes": forget.deleted,
                "tombstone_replication_factor": tombstone_memory.replication_factor,
                "tombstone_write_quorum": tombstone_memory.write_quorum,
                "tombstone_missed_delete_replica_records": tombstone_stale_records_before,
                "tombstone_suppressed_before_repair": tombstone_suppressed_before_repair,
                "tombstone_repair_canonical_records": tombstone_repair.canonical_records,
                "tombstone_repair_deleted_records": tombstone_repair.tombstone_deleted,
                "tombstone_stale_records_after_repair": tombstone_stale_records_after,
                "tombstone_suppressed_after_repair": tombstone_suppressed_after_repair,
                "anti_entropy_worker_ok": worker_report.ok,
                "anti_entropy_worker_repaired_total": worker_report.repaired_total,
                "anti_entropy_worker_tombstone_deleted": worker_report.tombstone_deleted,
                "write_ms": write_ms,
                "query_after_primary_loss_ms": query_after_primary_loss_ms,
            }
        finally:
            client.close()


def run_replication_runtime_profile() -> dict[str, object]:
    latencies: list[float] = []
    with tempfile.TemporaryDirectory() as directory:
        memory = ReplicatedWaveMind(
            root_path=Path(directory) / "replicas",
            nodes=[
                {"id": "node-a", "address": "127.0.0.1:8101", "zone": "zone-a"},
                {"id": "node-b", "address": "127.0.0.1:8102", "zone": "zone-b"},
                {"id": "node-c", "address": "127.0.0.1:8103", "zone": "zone-c"},
            ],
            replication_factor=3,
            width=16,
            height=16,
            layers=1,
            encoder=HashingTextEncoder(vector_dim=64),
        )
        try:
            namespace = "tenant:replicated"
            write = memory.remember(
                "replicated user memory survives one node loss",
                namespace=namespace,
            )
            placement = memory.placement(namespace)
            lost_node = placement.primary
            memory.set_node_available(lost_node, False)
            started = time.perf_counter()
            results = memory.query("survives node loss", namespace=namespace, top_k=1)
            latencies.append((time.perf_counter() - started) * 1000.0)
            recalled_after_loss = bool(results) and results[0].text == (
                "replicated user memory survives one node loss"
            )

            partial = ReplicatedWaveMind(
                root_path=Path(directory) / "partial",
                nodes=[
                    {"id": "node-a", "address": "127.0.0.1:8101", "zone": "zone-a"},
                    {"id": "node-b", "address": "127.0.0.1:8102", "zone": "zone-b"},
                    {"id": "node-c", "address": "127.0.0.1:8103", "zone": "zone-c"},
                ],
                replication_factor=3,
                write_quorum=1,
                width=16,
                height=16,
                layers=1,
                encoder=HashingTextEncoder(vector_dim=64),
            )
            try:
                partial_placement = partial.placement(namespace)
                recovering_node = partial_placement.replicas[-1]
                partial.set_node_available(recovering_node, False)
                partial.remember("repair copies missing replica state", namespace=namespace)
                partial.set_node_available(recovering_node, True)
                repair = partial.repair_namespace(namespace)
            finally:
                partial.close()

            tombstone = ReplicatedWaveMind(
                root_path=Path(directory) / "tombstone",
                nodes=[
                    {"id": "node-a", "address": "127.0.0.1:8101", "zone": "zone-a"},
                    {"id": "node-b", "address": "127.0.0.1:8102", "zone": "zone-b"},
                    {"id": "node-c", "address": "127.0.0.1:8103", "zone": "zone-c"},
                ],
                replication_factor=3,
                width=16,
                height=16,
                layers=1,
                encoder=HashingTextEncoder(vector_dim=64),
            )
            try:
                tombstone_placement = tombstone.placement(namespace)
                missed_delete = tombstone_placement.replicas[-1]
                tombstone.remember("repair must not resurrect deleted memory", namespace=namespace)
                tombstone.set_node_available(missed_delete, False)
                tombstone.forget(
                    text="repair must not resurrect deleted memory",
                    namespace=namespace,
                )
                tombstone.set_node_available(missed_delete, True)
                suppressed_before_repair = (
                    tombstone.query("resurrect deleted memory", namespace=namespace, top_k=1)
                    == []
                )
                tombstone_repair = tombstone.repair_namespace(namespace)
                suppressed_after_repair = (
                    tombstone.query("resurrect deleted memory", namespace=namespace, top_k=1)
                    == []
                )
            finally:
                tombstone.close()

            return {
                "engine": "WaveMind replicated runtime",
                "nodes": 3,
                "replication_factor": 3,
                "write_quorum": memory.write_quorum,
                "read_quorum": memory.read_quorum,
                "writes": len(write.writes),
                "recalled_after_node_loss": recalled_after_loss,
                "repair_copied_records": repair.copied_records,
                "tombstone_suppressed_before_repair": suppressed_before_repair,
                "tombstone_suppressed_after_repair": suppressed_after_repair,
                "tombstone_repair_deleted_records": tombstone_repair.deleted_records,
                "avg_query_after_loss_ms": statistics.mean(latencies),
                "p99_query_after_loss_ms": percentile(latencies, 99),
            }
        finally:
            memory.close()


def run_active_active_delta_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        kwargs = {
            "replication_factor": 3,
            "width": 16,
            "height": 16,
            "layers": 1,
            "encoder": HashingTextEncoder(vector_dim=64),
        }
        region_a = ReplicatedWaveMind(
            root_path=Path(directory) / "region-a",
            nodes=[
                {"id": "region-a-1", "address": "127.0.0.1:8101", "zone": "zone-a"},
                {"id": "region-a-2", "address": "127.0.0.1:8102", "zone": "zone-b"},
                {"id": "region-a-3", "address": "127.0.0.1:8103", "zone": "zone-c"},
            ],
            **kwargs,
        )
        region_b = ReplicatedWaveMind(
            root_path=Path(directory) / "region-b",
            nodes=[
                {"id": "region-b-1", "address": "127.0.0.1:8201", "zone": "zone-a"},
                {"id": "region-b-2", "address": "127.0.0.1:8202", "zone": "zone-b"},
                {"id": "region-b-3", "address": "127.0.0.1:8203", "zone": "zone-c"},
            ],
            **kwargs,
        )
        try:
            namespace = "tenant:active-active"
            region_a.remember("region a billing preference", namespace=namespace)
            region_b.remember("region b support preference", namespace=namespace)
            sync_started = time.perf_counter()
            import_b = region_b.import_namespace_delta(
                region_a.export_namespace_delta(namespace)
            )
            import_a = region_a.import_namespace_delta(
                region_b.export_namespace_delta(namespace)
            )
            sync_ms = (time.perf_counter() - sync_started) * 1000.0
            converged = (
                region_a.query("support preference", namespace=namespace, top_k=1)
                and region_b.query("billing preference", namespace=namespace, top_k=1)
            )

            stale_delta = region_b.export_namespace_delta(namespace)
            region_a.forget(text="region a billing preference", namespace=namespace)
            region_a.import_namespace_delta(stale_delta)
            suppressed_stale_import = all(
                result.text != "region a billing preference"
                for result in region_a.query("billing preference", namespace=namespace, top_k=3)
            )
            tombstone_delta = region_a.export_namespace_delta(namespace)
            tombstone_report = region_b.import_namespace_delta(tombstone_delta)
            tombstone_converged = all(
                result.text != "region a billing preference"
                for result in region_b.query("billing preference", namespace=namespace, top_k=3)
            )
            return {
                "engine": "WaveMind active-active delta sync",
                "regions": 2,
                "replication_factor_per_region": 3,
                "records_imported": import_a.imported_records + import_b.imported_records,
                "converged_after_bidirectional_sync": bool(converged),
                "sync_ms": sync_ms,
                "suppressed_stale_import_after_delete": suppressed_stale_import,
                "tombstone_deleted_records": tombstone_report.deleted_records,
                "tombstone_converged": tombstone_converged,
            }
        finally:
            region_a.close()
            region_b.close()


def run_replicated_snapshot_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        memory = ReplicatedWaveMind(
            root_path=root / "replicas",
            nodes=[
                {"id": "node-a", "address": "127.0.0.1:8101", "zone": "zone-a"},
                {"id": "node-b", "address": "127.0.0.1:8102", "zone": "zone-b"},
                {"id": "node-c", "address": "127.0.0.1:8103", "zone": "zone-c"},
            ],
            replication_factor=3,
            width=16,
            height=16,
            layers=1,
            encoder=HashingTextEncoder(vector_dim=64),
        )
        try:
            namespace = "tenant:snapshot"
            memory.remember(
                "replicated snapshot restore survives node loss",
                namespace=namespace,
            )
            snapshot_started = time.perf_counter()
            object_store = S3SnapshotStore.from_uri(
                "s3://wavemind-benchmark/replicated",
                client=InMemoryS3Client(),
            )
            for index in range(2):
                old_archive = root / f"old-object-archive-{index}.tar.gz"
                old_archive.write_bytes(f"old-object-archive-{index}".encode("utf-8"))
                object_store.upload_archive(old_archive)
            snapshot_job = ReplicatedSnapshotWorker(memory).run_once(
                destination=root / "snapshots",
                offsite_destination=root / "offsite",
                archive_destination=root / "archives",
                object_store_destination="s3://wavemind-benchmark/replicated",
                object_store=object_store,
                keep_last=2,
                object_store_keep_last=1,
            )
            snapshot_ms = (time.perf_counter() - snapshot_started) * 1000.0
            health = ReplicatedWaveMind.verify_snapshot(snapshot_job.snapshot_path)
            latest_object_archive = object_store.latest_archive()

            restore_started = time.perf_counter()
            drill = ReplicatedObjectStoreDrillWorker(object_store).run_once(
                source="s3://wavemind-benchmark/replicated",
                destination=root / "restored",
                download_destination=root / "object-store-downloads",
                namespace=namespace,
                query="snapshot restore node loss",
                expected_text="replicated snapshot restore survives node loss",
                width=16,
                height=16,
                layers=1,
                encoder=HashingTextEncoder(vector_dim=64),
            )
            restore_ms = (time.perf_counter() - restore_started) * 1000.0
            return {
                "engine": "WaveMind replicated snapshot",
                "nodes": len(snapshot_job.nodes),
                "manifest_healthy": health["healthy"],
                "offsite_verified": snapshot_job.offsite_verified,
                "archive_verified": snapshot_job.archive_verified,
                "object_store_verified": bool(
                    snapshot_job.object_store_upload
                    and snapshot_job.object_store_upload.verified
                ),
                "object_store_latest_verified": bool(
                    latest_object_archive and latest_object_archive.verified
                ),
                "object_store_pruned": len(snapshot_job.pruned_object_store),
                "object_store_download_verified": (
                    drill.download_matches_object and drill.archive_verified
                ),
                "object_store_drill_ok": drill.ok,
                "total_bytes": snapshot_job.total_bytes,
                "snapshot_ms": snapshot_ms,
                "restore_ms": restore_ms,
                "restored_files": drill.restored_files,
                "recalled_after_restore_node_loss": bool(
                    drill.recalled_after_primary_loss
                ),
            }
        finally:
            memory.close()


def run_multimodal_profile() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        memory = WaveMind(
            db_path=Path(directory) / "payloads.sqlite3",
            encoder=HashingTextEncoder(vector_dim=64),
            width=16,
            height=16,
            layers=1,
        )
        try:
            expected = {
                "enterprise expansion chart": remember_payload(
                    memory,
                    image_payload(
                        "s3://demo/revenue-chart.png",
                        caption="enterprise expansion revenue chart",
                        tags=["report"],
                    ),
                    namespace="scale",
                ),
                "SSO audit log call": remember_payload(
                    memory,
                    audio_payload(
                        "support-call.wav",
                        transcript="customer requested SSO and audit log export",
                        tags=["call"],
                    ),
                    namespace="scale",
                ),
                "ARR enterprise table": remember_payload(
                    memory,
                    table_payload(
                        [{"segment": "enterprise", "arr": 2000}],
                        title="ARR by segment",
                        tags=["table"],
                    ),
                    namespace="scale",
                ),
                "upgraded enterprise plan": remember_payload(
                    memory,
                    event_payload(
                        "account upgraded to enterprise plan",
                        actor="tenant:acme",
                        properties={"plan": "enterprise"},
                        tags=["event"],
                    ),
                    namespace="scale",
                ),
            }
            latencies = []
            correct = 0
            for query, expected_id in expected.items():
                started = time.perf_counter()
                results = memory.query(query, namespace="scale", top_k=1)
                latencies.append((time.perf_counter() - started) * 1000.0)
                if results and results[0].id == expected_id:
                    correct += 1
            return {
                "engine": "WaveMind structured payloads",
                "modalities": ["image", "audio", "table", "event"],
                "queries": len(expected),
                "precision_at_1": correct / len(expected),
                "avg_latency_ms": statistics.mean(latencies),
                "p99_latency_ms": percentile(latencies, 99),
            }
        finally:
            memory.close()


def run_benchmark(
    *,
    simulated_memories: int = 1_000_000,
    namespace_count: int = 4096,
    node_count: int = 4,
    replication_factor: int = 2,
    cache_queries: int = 2000,
    cache_capacity: int = 512,
) -> dict[str, object]:
    results = [
        run_cluster_profile(
            namespace_count=namespace_count,
            node_count=node_count,
            replication_factor=replication_factor,
            simulated_memories=simulated_memories,
        ),
        run_cache_profile(queries=cache_queries, capacity=cache_capacity),
        run_distributed_sharding_profile(),
        run_replication_runtime_profile(),
        run_active_active_delta_profile(),
        run_replicated_snapshot_profile(),
        run_multimodal_profile(),
    ]
    return {
        "scenario": {
            "name": "scale_readiness",
            "simulated_memories": simulated_memories,
            "namespace_count": namespace_count,
            "node_count": node_count,
            "replication_factor": replication_factor,
            "description": (
                "Deterministic scale-readiness profile for cluster placement, "
                "node/zone loss simulation, quorum-replicated runtime behavior, "
                "service-mode distributed namespace sharding, active-active delta sync, replicated snapshot/offsite/archive "
                "restore, S3-compatible object-store upload/latest-metadata/"
                "download/retention/DR-drill verification, hot-cache behavior, and structured payload retrieval. "
                "This is not a 10M-vector database load test."
            ),
        },
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulated-memories", type=int, default=1_000_000)
    parser.add_argument("--namespace-count", type=int, default=4096)
    parser.add_argument("--node-count", type=int, default=4)
    parser.add_argument("--replication-factor", type=int, default=2)
    parser.add_argument("--cache-queries", type=int, default=2000)
    parser.add_argument("--cache-capacity", type=int, default=512)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/scale_readiness_results.json"))
    args = parser.parse_args()

    payload = run_benchmark(
        simulated_memories=args.simulated_memories,
        namespace_count=args.namespace_count,
        node_count=args.node_count,
        replication_factor=args.replication_factor,
        cache_queries=args.cache_queries,
        cache_capacity=args.cache_capacity,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("| profile | key metric | value |")
    print("|---|---|---:|")
    for result in payload["results"]:
        if result["engine"] == "WaveMind cluster planner":
            print(f"| cluster | node_loss_min_availability | {result['node_loss_min_availability']:.3f} |")
            zone_loss = result["zone_loss_min_availability"]
            print(f"| cluster | zone_loss_min_availability | {zone_loss:.3f} |")
        elif result["engine"] == "WaveMind hot cache":
            print(f"| hot cache | hit_rate | {result['hit_rate']:.3f} |")
            print(f"| hot cache | prewarm_warmed | {result['prewarm_warmed']} |")
            print(f"| hot cache | prewarm_hit | {result['prewarm_hit']} |")
        elif result["engine"] == "WaveMind distributed sharding":
            print(f"| distributed sharding | writes | {result['writes']} |")
            print(f"| distributed sharding | recalled_after_primary_loss | {result['recalled_after_primary_loss']} |")
            print(f"| distributed sharding | repair_repaired_total | {result['repair_repaired_total']} |")
            print(f"| distributed sharding | recalled_after_repair | {result['recalled_after_repair']} |")
            print(f"| distributed sharding | forget_replicated_deletes | {result['forget_replicated_deletes']} |")
            print(f"| distributed sharding | tombstone_suppressed_before_repair | {result['tombstone_suppressed_before_repair']} |")
            print(f"| distributed sharding | tombstone_repair_deleted_records | {result['tombstone_repair_deleted_records']} |")
            print(f"| distributed sharding | tombstone_suppressed_after_repair | {result['tombstone_suppressed_after_repair']} |")
            print(f"| distributed sharding | anti_entropy_worker_ok | {result['anti_entropy_worker_ok']} |")
        elif result["engine"] == "WaveMind replicated runtime":
            print(f"| replicated runtime | recalled_after_node_loss | {result['recalled_after_node_loss']} |")
            print(f"| replicated runtime | repair_copied_records | {result['repair_copied_records']} |")
            print(f"| replicated runtime | tombstone_repair_deleted_records | {result['tombstone_repair_deleted_records']} |")
        elif result["engine"] == "WaveMind active-active delta sync":
            print(f"| active-active delta | converged | {result['converged_after_bidirectional_sync']} |")
            print(f"| active-active delta | tombstone_converged | {result['tombstone_converged']} |")
        elif result["engine"] == "WaveMind replicated snapshot":
            print(f"| replicated snapshot | manifest_healthy | {result['manifest_healthy']} |")
            print(f"| replicated snapshot | offsite_verified | {result['offsite_verified']} |")
            print(f"| replicated snapshot | archive_verified | {result['archive_verified']} |")
            print(f"| replicated snapshot | object_store_verified | {result['object_store_verified']} |")
            print(f"| replicated snapshot | object_store_latest_verified | {result['object_store_latest_verified']} |")
            print(f"| replicated snapshot | object_store_pruned | {result['object_store_pruned']} |")
            print(f"| replicated snapshot | object_store_download_verified | {result['object_store_download_verified']} |")
            print(f"| replicated snapshot | object_store_drill_ok | {result['object_store_drill_ok']} |")
            print(f"| replicated snapshot | recalled_after_restore_node_loss | {result['recalled_after_restore_node_loss']} |")
        else:
            print(f"| structured payloads | precision@1 | {result['precision_at_1']:.3f} |")
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
