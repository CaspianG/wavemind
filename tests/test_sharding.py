from pathlib import Path

import pytest

from wavemind import HashingTextEncoder, NamespaceShardRouter, ShardedWaveMind


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
