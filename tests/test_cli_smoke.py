import subprocess
import sys
import json
import os
from pathlib import Path


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

    audit = run_cli("--db", str(db_path), "audit", "--namespace", "cli", "--json")
    audit_events = json.loads(audit.stdout)
    assert audit_events[0]["action"] == "remember"
    assert audit_events[0]["namespace"] == "cli"

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


def test_cli_benchmark_seeds_all_synthetic_cases(tmp_path):
    db_path = tmp_path / "bench.sqlite3"

    result = run_cli("--db", str(db_path), "benchmark")
    report = json.loads(result.stdout)

    assert report["capacity"] == 4
    assert report["recall_at_k"] == 1.0


def test_cli_default_database_is_created_in_working_directory(tmp_path):
    result = run_cli("remember", "portable default database memory", cwd=tmp_path)

    assert "remembered id=" in result.stdout
    assert (tmp_path / "wavemind.sqlite3").exists()
    assert not (tmp_path / "data").exists()
