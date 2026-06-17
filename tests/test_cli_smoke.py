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

    backup = run_cli("--db", str(db_path), "backup", "--out", str(backup_path))
    assert "backup:" in backup.stdout
    assert backup_path.exists()


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
