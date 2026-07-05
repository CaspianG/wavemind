import subprocess
import sys
import json
import os
from pathlib import Path

from wavemind import HashingTextEncoder, ReplicatedWaveMind


def run_cli(*args, cwd=None):
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "wavemind", *args],
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )


def test_module_cli_remember_query_stats_and_backup(tmp_path):
    db_path = tmp_path / "cli.sqlite3"
    backup_path = tmp_path / "backup.sqlite3"

    remembered = run_cli(
        "--db",
        str(db_path),
        "remember",
        "кошка спит на окне",
        "--namespace",
        "cli",
        "--tag",
        "animal",
    )
    assert "remembered id=" in remembered.stdout

    queried = run_cli("--db", str(db_path), "query", "кошка", "--namespace", "cli")
    assert "кошка спит на окне" in queried.stdout

    stats = run_cli("--db", str(db_path), "stats", "--namespace", "cli")
    assert "active_memories: 1" in stats.stdout
    assert "audit_events: 1" in stats.stdout
    assert "index_healthy: True" in stats.stdout

    index_health = run_cli("--db", str(db_path), "index-health", "--json")
    health = json.loads(index_health.stdout)
    assert health["healthy"] is True
    assert health["expected_count"] == 1

    rebuilt = run_cli("--db", str(db_path), "rebuild-index", "--json")
    rebuild_health = json.loads(rebuilt.stdout)
    assert rebuild_health["healthy"] is True

    audit = run_cli("--db", str(db_path), "audit", "--namespace", "cli", "--json")
    audit_events = json.loads(audit.stdout)
    assert audit_events[0]["action"] == "remember"
    assert audit_events[0]["namespace"] == "cli"

    global_audit = run_cli("--db", str(db_path), "audit", "--json")
    global_events = json.loads(global_audit.stdout)
    assert global_events[0]["action"] == "index_rebuild"

    backup = run_cli("--db", str(db_path), "backup", "--out", str(backup_path))
    assert "backup:" in backup.stdout
    assert backup_path.exists()


def test_cli_timestamped_backup_retention_and_restore(tmp_path):
    db_path = tmp_path / "cli.sqlite3"
    backup_dir = tmp_path / "backups"
    restored_path = tmp_path / "restored.sqlite3"

    run_cli("--db", str(db_path), "remember", "backup restore cli memory")
    for _ in range(3):
        run_cli(
            "--db",
            str(db_path),
            "backup",
            "--out",
            str(backup_dir),
            "--keep-last",
            "2",
            "--prefix",
            "cli",
        )

    backups = sorted(backup_dir.glob("cli-*.sqlite3"))
    assert len(backups) == 2

    restored = run_cli(
        "--db",
        str(restored_path),
        "restore",
        "--from",
        str(backups[-1]),
        "--overwrite",
    )
    assert "restored:" in restored.stdout

    queried = run_cli(
        "--db",
        str(restored_path),
        "query",
        "backup restore",
    )
    assert "backup restore cli memory" in queried.stdout


def test_legacy_script_delegates_to_new_cli(tmp_path):
    result = subprocess.run(
        [sys.executable, "wavemind_v2.py", "--help"],
        cwd=".",
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    assert "WaveMind" in result.stdout
    assert "studio" in result.stdout


def test_cli_benchmark_seeds_all_synthetic_cases(tmp_path):
    db_path = tmp_path / "bench.sqlite3"

    result = run_cli("--db", str(db_path), "benchmark")
    report = json.loads(result.stdout)

    assert report["capacity"] == 4
    assert report["recall_at_k"] == 1.0


def test_cli_maintenance_runs_one_job(tmp_path):
    db_path = tmp_path / "maintenance.sqlite3"
    run_cli(
        "--db",
        str(db_path),
        "remember",
        "temporary memory",
        "--namespace",
        "ops",
        "--ttl-seconds",
        "-1",
    )

    result = run_cli(
        "--db",
        str(db_path),
        "maintenance",
        "--namespace",
        "ops",
        "--json",
    )
    payload = json.loads(result.stdout)

    assert payload["expired_purged"] == 1
    assert payload["index_rebuilt"] in {True, False}


def test_cli_replicated_snapshot_and_restore(tmp_path):
    root = tmp_path / "replicas"
    nodes = ["node-a", "node-b", "node-c"]
    memory = ReplicatedWaveMind(
        root_path=root,
        nodes=nodes,
        replication_factor=3,
        width=16,
        height=16,
        layers=1,
        encoder=HashingTextEncoder(vector_dim=64),
    )
    restored = None
    try:
        memory.remember("cli replicated snapshot memory", namespace="tenant:cli")
    finally:
        memory.close()

    snapshot = run_cli(
        "replicated-snapshot",
        "--root",
        str(root),
        "--node",
        "node-a",
        "--node",
        "node-b",
        "--node",
        "node-c",
        "--out",
        str(tmp_path / "snapshots"),
        "--offsite",
        str(tmp_path / "offsite"),
        "--archive",
        str(tmp_path / "archives"),
        "--json",
    )
    snapshot_payload = json.loads(snapshot.stdout)
    restore = run_cli(
        "replicated-restore",
        "--from",
        snapshot_payload["archive_path"],
        "--to",
        str(tmp_path / "restored"),
        "--json",
    )
    restore_payload = json.loads(restore.stdout)

    try:
        restored = ReplicatedWaveMind(
            root_path=restore_payload["root_path"],
            nodes=nodes,
            replication_factor=3,
            width=16,
            height=16,
            layers=1,
            encoder=HashingTextEncoder(vector_dim=64),
        )
        assert snapshot_payload["ok"] is True
        assert snapshot_payload["offsite_verified"] is True
        assert snapshot_payload["archive_verified"] is True
        assert snapshot_payload["archive_path"].endswith(".tar.gz")
        assert len(restore_payload["restored_files"]) == 3
        assert restored.query("snapshot memory", namespace="tenant:cli", top_k=1)[0].text == (
            "cli replicated snapshot memory"
        )
    finally:
        if restored is not None:
            restored.close()


def test_cli_replicated_snapshot_and_restore_help_mentions_s3_flags():
    snapshot_help = run_cli("replicated-snapshot", "--help")
    restore_help = run_cli("replicated-restore", "--help")

    assert "--s3" in snapshot_help.stdout
    assert "--s3-endpoint-url" in snapshot_help.stdout
    assert "--s3-region" in snapshot_help.stdout
    assert "--s3-endpoint-url" in restore_help.stdout
    assert "--s3-region" in restore_help.stdout


def test_cli_consolidate_creates_concept_memory(tmp_path):
    db_path = tmp_path / "concepts.sqlite3"

    run_cli(
        "--db",
        str(db_path),
        "remember",
        "User likes Rust systems programming",
        "--namespace",
        "agent",
        "--tag",
        "systems",
    )
    run_cli(
        "--db",
        str(db_path),
        "remember",
        "User studies compiler systems internals",
        "--namespace",
        "agent",
        "--tag",
        "systems",
    )

    consolidated = run_cli(
        "--db",
        str(db_path),
        "consolidate",
        "--namespace",
        "agent",
        "--seed",
        "Rust compiler systems",
        "--min-energy",
        "0.01",
        "--json",
    )
    payload = json.loads(consolidated.stdout)

    assert len(payload["concepts"]) == 1
    assert payload["concepts"][0]["metadata"]["source"] == "wavemind_consolidation"

    concept_query = run_cli(
        "--db",
        str(db_path),
        "query",
        "systems programming",
        "--namespace",
        "agent",
        "--tag",
        "concept",
    )
    assert "Consolidated memory:" in concept_query.stdout


def test_cli_default_database_is_created_in_working_directory(tmp_path):
    result = run_cli("remember", "portable default database memory", cwd=tmp_path)

    assert "remembered id=" in result.stdout
    assert (tmp_path / "wavemind.sqlite3").exists()
    assert not (tmp_path / "data").exists()


def test_cli_quickstart_prints_first_run_commands():
    result = run_cli("quickstart")

    assert "WaveMind quickstart" in result.stdout
    assert "python -m pip install wavemind" in result.stdout
    assert 'wavemind remember "Andrey is a trader" --namespace demo' in result.stdout
    assert 'wavemind query "What does Andrey do?" --namespace demo' in result.stdout
    assert "wavemind studio" in result.stdout


def test_cli_version_prints_package_version():
    result = run_cli("--version")

    assert result.stdout.strip().startswith("wavemind ")
