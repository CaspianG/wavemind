import json
import subprocess
import sys
from pathlib import Path

from wavemind import WaveMind
from wavemind.encoders import HashingTextEncoder
from wavemind.memory_os_canary import (
    CANARY_SCHEMA,
    render_memory_os_canary_markdown,
    run_memory_os_canary,
)


def test_memory_os_canary_passes_with_representative_traffic(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "memory-os-canary.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
        score_threshold=0.0,
    )
    try:
        payload = run_memory_os_canary(
            memory,
            namespace="tenant:canary",
            target_memories=100_000,
            namespace_count=64,
            node_count=3,
            target_qps=100,
            query_repetitions=2,
        )
    finally:
        memory.close()

    assert payload["schema"] == CANARY_SCHEMA
    assert payload["status"] == "pass"
    assert payload["ok"] is True
    assert payload["summary"]["admitted"] is True
    assert payload["summary"]["hot_query_count"] >= 1
    assert payload["summary"]["prewarm_warmed"] >= 1
    assert payload["summary"]["predictive_warmed"] >= 1
    assert payload["summary"]["priority_predictions"] >= 1
    assert payload["summary"]["expired_purged"] >= 1
    assert payload["failed_check_ids"] == []
    assert "staging_canary" in payload["claim_boundary"]
    assert payload["admission"]["status"] == "admitted"
    assert payload["schedule_plan"]["effective_cache_mode"] == "redis"


def test_memory_os_canary_markdown_includes_admission_detail(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "memory-os-canary-md.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
        score_threshold=0.0,
    )
    try:
        payload = run_memory_os_canary(memory, namespace="tenant:canary-md")
    finally:
        memory.close()

    markdown = render_memory_os_canary_markdown(payload)

    assert "# WaveMind Memory OS Canary" in markdown
    assert "Representative query audit created hot queries" in markdown
    assert "Memory OS scheduler passes staging admission" in markdown
    assert "# WaveMind Memory OS Admission" in markdown
    assert "`admitted`" in markdown


def test_memory_os_canary_cli_writes_artifacts(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    db = tmp_path / "cli-canary.sqlite3"
    output = tmp_path / "memory_os_canary_results.json"
    markdown = tmp_path / "MEMORY_OS_CANARY.md"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "--db",
            str(db),
            "memory-os-canary",
            "--namespace",
            "tenant:cli-canary",
            "--target-memories",
            "100000",
            "--namespace-count",
            "64",
            "--query-repetitions",
            "2",
            "--write-artifacts",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
            "--json",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    stdout_payload = json.loads(result.stdout)
    assert payload["schema"] == CANARY_SCHEMA
    assert payload["status"] == "pass"
    assert stdout_payload["status"] == "pass"
    assert "WaveMind Memory OS Canary" in markdown.read_text(encoding="utf-8")


def test_memory_os_canary_cli_fail_gate_passes_when_canary_is_green(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    db = tmp_path / "cli-canary-fail-gate.sqlite3"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "--db",
            str(db),
            "memory-os-canary",
            "--namespace",
            "tenant:cli-canary-gate",
            "--target-memories",
            "100000",
            "--fail-on-action-required",
            "--json",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "pass"
