import pytest

from wavemind import (
    HashingTextEncoder,
    ReadQuorumError,
    ReplicatedWaveMind,
    ReplicationError,
    WriteQuorumError,
)


def _cluster(tmp_path, **kwargs):
    return ReplicatedWaveMind(
        root_path=tmp_path / "replicas",
        nodes=[
            {"id": "node-a", "address": "127.0.0.1:8101", "zone": "zone-a"},
            {"id": "node-b", "address": "127.0.0.1:8102", "zone": "zone-b"},
            {"id": "node-c", "address": "127.0.0.1:8103", "zone": "zone-c"},
        ],
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
        **kwargs,
    )


def _region(tmp_path, name: str, **kwargs):
    return ReplicatedWaveMind(
        root_path=tmp_path / name,
        nodes=[
            {"id": f"{name}-a", "address": "127.0.0.1:8101", "zone": "zone-a"},
            {"id": f"{name}-b", "address": "127.0.0.1:8102", "zone": "zone-b"},
            {"id": f"{name}-c", "address": "127.0.0.1:8103", "zone": "zone-c"},
        ],
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
        **kwargs,
    )


def test_replicated_wavemind_writes_to_all_replicas_and_reads_after_node_loss(tmp_path):
    memory = _cluster(tmp_path, replication_factor=3)
    try:
        write = memory.remember(
            "Andrey prefers short trading summaries",
            namespace="tenant:andrey",
            tags=["profile"],
        )
        placement = memory.placement("tenant:andrey")

        assert write.ok
        assert set(write.writes) == set(placement.replicas)
        assert all(memory.node_db_path(node_id).exists() for node_id in placement.replicas)

        memory.set_node_available(placement.primary, False)
        results = memory.query("short trading summaries", namespace="tenant:andrey", top_k=1)

        assert results[0].text == "Andrey prefers short trading summaries"
        assert results[0].metadata["_replica_node"] != placement.primary
    finally:
        memory.close()


def test_replicated_wavemind_requires_write_quorum(tmp_path):
    memory = _cluster(tmp_path, replication_factor=3)
    try:
        placement = memory.placement("tenant:blocked")
        memory.set_node_available(placement.replicas[0], False)
        memory.set_node_available(placement.replicas[1], False)

        with pytest.raises(WriteQuorumError):
            memory.remember("this write cannot reach quorum", namespace="tenant:blocked")
    finally:
        memory.close()


def test_replicated_wavemind_enforces_read_quorum(tmp_path):
    memory = _cluster(tmp_path, replication_factor=3, read_quorum=2)
    try:
        memory.remember("read quorum memory", namespace="tenant:read")
        placement = memory.placement("tenant:read")
        memory.set_node_available(placement.replicas[0], False)
        memory.set_node_available(placement.replicas[1], False)

        with pytest.raises(ReadQuorumError):
            memory.query("read quorum", namespace="tenant:read", top_k=1)
    finally:
        memory.close()


def test_replicated_wavemind_repairs_recovered_replica(tmp_path):
    memory = _cluster(tmp_path, replication_factor=3, write_quorum=1)
    try:
        placement = memory.placement("tenant:repair")
        recovering = placement.replicas[-1]
        memory.set_node_available(recovering, False)
        memory.remember("repair missing namespace record", namespace="tenant:repair")

        memory.set_node_available(recovering, True)
        before = memory._mind(recovering).store.count(namespace="tenant:repair")
        report = memory.repair_namespace("tenant:repair")
        after = memory._mind(recovering).store.count(namespace="tenant:repair")

        assert before == 0
        assert after == 1
        assert report.copied_records == 1
        assert report.repaired_nodes[recovering] == 1
        results = memory.query("missing namespace record", namespace="tenant:repair", top_k=1)
        assert results[0].text == "repair missing namespace record"
    finally:
        memory.close()


def test_replicated_wavemind_repair_does_not_resurrect_forgotten_memory(tmp_path):
    memory = _cluster(tmp_path, replication_factor=3)
    try:
        namespace = "tenant:tombstone"
        memory.remember("stale replicated memory should stay deleted", namespace=namespace)
        placement = memory.placement(namespace)
        missed_delete = placement.replicas[-1]

        memory.set_node_available(missed_delete, False)
        delete = memory.forget(
            text="stale replicated memory should stay deleted",
            namespace=namespace,
        )
        assert delete.ok

        memory.set_node_available(missed_delete, True)
        assert memory._mind(missed_delete).store.count(namespace=namespace) == 1
        assert memory.query("stale replicated memory", namespace=namespace, top_k=1) == []

        report = memory.repair_namespace(namespace)

        assert report.deleted_records == 1
        assert report.copied_records == 0
        assert report.tombstone_keys == 1
        assert memory._mind(missed_delete).store.count(namespace=namespace) == 0
        assert memory.query("stale replicated memory", namespace=namespace, top_k=1) == []
    finally:
        memory.close()


def test_replicated_wavemind_forget_by_id_deletes_replicas_with_different_local_ids(tmp_path):
    memory = _cluster(tmp_path, replication_factor=3, write_quorum=2)
    try:
        namespace = "tenant:id-delete"
        placement = memory.placement(namespace)
        lagging = next(node_id for node_id in placement.replicas if node_id != placement.primary)
        memory.set_node_available(lagging, False)
        memory.remember("advance ids on two replicas", namespace=namespace)
        memory.set_node_available(lagging, True)

        write = memory.remember("delete this record by primary id", namespace=namespace)
        lagging_ids = [
            record.id
            for record in memory._mind(lagging).store.list(namespace=namespace)
            if record.text == "delete this record by primary id"
        ]

        assert write.primary_id is not None
        assert lagging_ids == [1]
        assert write.primary_id != lagging_ids[0]

        delete = memory.forget(id=write.primary_id, namespace=namespace)

        assert delete.ok
        assert all(
            result.text != "delete this record by primary id"
            for result in memory.query("delete this record by primary id", namespace=namespace, top_k=3)
        )
        for node_id in placement.replicas:
            texts = [
                record.text
                for record in memory._mind(node_id).store.list(namespace=namespace)
            ]
            assert "delete this record by primary id" not in texts
    finally:
        memory.close()


def test_replicated_wavemind_stores_stable_replica_metadata(tmp_path):
    memory = _cluster(tmp_path, replication_factor=3)
    try:
        namespace = "tenant:metadata"
        write = memory.remember(
            "metadata replicated memory",
            namespace=namespace,
            tags=["profile"],
            metadata={"source": "test"},
        )
        keys = set()
        operation_ids = set()
        for node_id in write.writes:
            records = memory._mind(node_id).store.list(namespace=namespace)
            assert len(records) == 1
            keys.add(records[0].metadata["_wavemind_replica_key"])
            operation_ids.add(records[0].metadata["_wavemind_operation_id"])

        assert len(keys) == 1
        assert len(operation_ids) == 1
    finally:
        memory.close()


def test_replicated_wavemind_namespace_delta_converges_two_regions(tmp_path):
    region_a = _region(tmp_path, "region-a", replication_factor=3)
    region_b = _region(tmp_path, "region-b", replication_factor=3)
    try:
        namespace = "tenant:active-active"
        region_a.remember("region a remembers billing preference", namespace=namespace)
        region_b.remember("region b remembers support preference", namespace=namespace)

        report_b = region_b.import_namespace_delta(region_a.export_namespace_delta(namespace))
        report_a = region_a.import_namespace_delta(region_b.export_namespace_delta(namespace))

        assert report_b.imported_records == 3
        assert report_a.imported_records == 3
        assert region_a.query("support preference", namespace=namespace, top_k=1)[0].text == (
            "region b remembers support preference"
        )
        assert region_b.query("billing preference", namespace=namespace, top_k=1)[0].text == (
            "region a remembers billing preference"
        )
    finally:
        region_a.close()
        region_b.close()


def test_replicated_wavemind_delta_import_is_idempotent(tmp_path):
    region_a = _region(tmp_path, "region-a", replication_factor=3)
    region_b = _region(tmp_path, "region-b", replication_factor=3)
    try:
        namespace = "tenant:idempotent"
        region_a.remember("idempotent active active memory", namespace=namespace)
        delta = region_a.export_namespace_delta(namespace)

        first = region_b.import_namespace_delta(delta)
        second = region_b.import_namespace_delta(delta)
        placement = region_b.placement(namespace)

        assert first.imported_records == 3
        assert second.imported_records == 0
        assert second.skipped_records == 3
        for node_id in placement.replicas:
            records = region_b._mind(node_id).store.list(namespace=namespace)
            assert [record.text for record in records] == ["idempotent active active memory"]
    finally:
        region_a.close()
        region_b.close()


def test_replicated_wavemind_tombstone_delta_beats_stale_record_delta(tmp_path):
    region_a = _region(tmp_path, "region-a", replication_factor=3)
    region_b = _region(tmp_path, "region-b", replication_factor=3)
    try:
        namespace = "tenant:tombstone-delta"
        region_a.remember("delete wins over stale region export", namespace=namespace)
        region_b.import_namespace_delta(region_a.export_namespace_delta(namespace))
        stale_delta = region_b.export_namespace_delta(namespace)

        region_a.forget(text="delete wins over stale region export", namespace=namespace)
        region_a.import_namespace_delta(stale_delta)

        assert region_a.query("stale region export", namespace=namespace, top_k=1) == []

        tombstone_delta = region_a.export_namespace_delta(namespace)
        report = region_b.import_namespace_delta(tombstone_delta)

        assert report.deleted_records == 3
        assert report.imported_tombstones == 3
        assert region_b.query("stale region export", namespace=namespace, top_k=1) == []
    finally:
        region_a.close()
        region_b.close()


def test_replicated_wavemind_snapshot_restore_survives_node_loss(tmp_path):
    memory = _cluster(tmp_path, replication_factor=3)
    restored = None
    try:
        namespace = "tenant:snapshot"
        write = memory.remember(
            "snapshot restore keeps replicated memory available",
            namespace=namespace,
        )

        report = memory.snapshot(tmp_path / "snapshots")
        health = ReplicatedWaveMind.verify_snapshot(report.snapshot_path)
        restored, restore_report = ReplicatedWaveMind.restore_snapshot(
            report.snapshot_path,
            tmp_path / "restored",
            width=16,
            height=16,
            layers=1,
            encoder=HashingTextEncoder(vector_dim=64),
        )
        placement = restored.placement(namespace)
        restored.set_node_available(placement.primary, False)
        results = restored.query("replicated memory available", namespace=namespace, top_k=1)

        assert report.ok
        assert set(report.nodes) == set(write.writes)
        assert health["healthy"] is True
        assert set(health["verified_nodes"]) == set(write.writes)
        assert set(restore_report.restored_files) == set(write.writes)
        assert results[0].text == "snapshot restore keeps replicated memory available"
    finally:
        memory.close()
        if restored is not None:
            restored.close()


def test_replicated_wavemind_snapshot_verify_detects_checksum_drift(tmp_path):
    memory = _cluster(tmp_path, replication_factor=3)
    try:
        memory.remember("checksum protected snapshot", namespace="tenant:snapshot")
        report = memory.snapshot(tmp_path / "snapshots")
        first_node = report.nodes[0]
        with (report.snapshot_path / f"{first_node}.sqlite3").open("ab") as handle:
            handle.write(b"corruption")

        health = ReplicatedWaveMind.verify_snapshot(report.snapshot_path)

        assert health["healthy"] is False
        assert health["failed_nodes"] == {first_node: "sha256 mismatch"}
        with pytest.raises(ReplicationError, match="Snapshot verification failed"):
            ReplicatedWaveMind.restore_snapshot(report.snapshot_path, tmp_path / "restored")
    finally:
        memory.close()


def test_replicated_wavemind_restore_requires_overwrite_for_nonempty_root(tmp_path):
    memory = _cluster(tmp_path, replication_factor=3)
    restored = None
    try:
        memory.remember("restore overwrite guard", namespace="tenant:snapshot")
        report = memory.snapshot(tmp_path / "snapshots")
        destination = tmp_path / "existing"
        destination.mkdir()
        (destination / "marker.txt").write_text("keep", encoding="utf-8")

        with pytest.raises(FileExistsError):
            ReplicatedWaveMind.restore_snapshot(report.snapshot_path, destination)

        restored, restore_report = ReplicatedWaveMind.restore_snapshot(
            report.snapshot_path,
            destination,
            overwrite=True,
            width=16,
            height=16,
            layers=1,
            encoder=HashingTextEncoder(vector_dim=64),
        )

        assert not (destination / "marker.txt").exists()
        assert len(restore_report.restored_files) == 3
    finally:
        memory.close()
        if restored is not None:
            restored.close()


def test_replicated_wavemind_rejects_global_db_path(tmp_path):
    with pytest.raises(ValueError, match="db_path"):
        ReplicatedWaveMind(
            root_path=tmp_path,
            nodes=["node-a", "node-b", "node-c"],
            db_path=tmp_path / "single.sqlite3",
        )
