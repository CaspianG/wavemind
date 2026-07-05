import pytest

from wavemind import (
    HashingTextEncoder,
    ReadQuorumError,
    ReplicatedWaveMind,
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


def test_replicated_wavemind_rejects_global_db_path(tmp_path):
    with pytest.raises(ValueError, match="db_path"):
        ReplicatedWaveMind(
            root_path=tmp_path,
            nodes=["node-a", "node-b", "node-c"],
            db_path=tmp_path / "single.sqlite3",
        )
