import json
import subprocess
import sys
from pathlib import Path

from wavemind import WaveMind
from wavemind.encoders import HashingTextEncoder
from wavemind.jobs import MemoryOSScheduler
from wavemind.memory_os_admission import (
    evaluate_memory_os_admission,
    render_memory_os_admission_markdown,
)


def _seed_hot_memory(tmp_path: Path) -> WaveMind:
    mind = WaveMind(
        db_path=tmp_path / "memory-os-admission.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
        score_threshold=0.0,
    )
    for text in [
        "Tenant prefers a two thousand dollar budget.",
        "Tenant has strict risk limits.",
        "Tenant likes short operational answers.",
    ]:
        mind.remember(text, namespace="tenant:admission")
    for _ in range(3):
        mind.query("budget recall", namespace="tenant:admission", top_k=2)
    return mind


def test_memory_os_admission_blocks_without_audit_and_runtime_env(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "empty.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        audit_queries=True,
    )
    try:
        plan = MemoryOSScheduler(mind).plan(
            deployment="production",
            target_memories=10_000_000,
            namespace_count=4096,
            target_qps=1200,
            target_p99_ms=80,
            cache_mode="auto",
            multimodal=True,
        )
        payload = evaluate_memory_os_admission(plan)
    finally:
        mind.close()

    assert payload["schema"] == "wavemind.memory_os_admission.v1"
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["claim_boundary"] == "strict_memory_os_evidence_required"
    assert "hot-query-signal" in payload["summary"]["blocker_ids"]
    assert "shared-cache-configured" in payload["summary"]["blocker_ids"]
    assert "distributed-lock-configured" in payload["summary"]["blocker_ids"]
    assert "scale-boundary" in payload["summary"]["blocker_ids"]
    assert "WAVEMIND_REDIS_URL" in payload["summary"]["missing_runtime_env"]
    assert "WAVEMIND_MEMORY_OS_LOCK_REDIS_URL" in payload["summary"]["missing_runtime_env"]


def test_memory_os_admission_admits_hot_runtime_plan(tmp_path):
    mind = _seed_hot_memory(tmp_path)
    try:
        plan = MemoryOSScheduler(mind).plan(
            namespace="tenant:admission",
            deployment="production",
            target_memories=1_000,
            namespace_count=8,
            node_count=3,
            replication_factor=3,
            read_quorum=1,
            read_fanout=1,
            target_qps=20,
            target_p99_ms=100,
            cache_mode="auto",
        )
        payload = evaluate_memory_os_admission(
            plan,
            redis_url="redis://redis.example.internal:6379/0",
            lock_redis_url="redis://redis.example.internal:6379/1",
        )
    finally:
        mind.close()

    assert payload["status"] == "admitted"
    assert payload["admitted"] is True
    assert payload["summary"]["blocker_ids"] == []
    assert payload["hot_query_count"] >= 1
    assert "cache-prewarm" in payload["summary"]["enabled_task_ids"]
    assert "predictive-prefetch" in payload["summary"]["enabled_task_ids"]
    assert "consolidation" in payload["summary"]["enabled_task_ids"]
    assert payload["execution_plan"]["safe_to_run"] is True


def test_render_memory_os_admission_markdown_includes_requirements(tmp_path):
    mind = _seed_hot_memory(tmp_path)
    try:
        plan = MemoryOSScheduler(mind).plan(
            namespace="tenant:admission",
            deployment="production",
            target_memories=1_000,
            namespace_count=8,
            node_count=3,
            read_fanout=1,
            target_qps=20,
            cache_mode="auto",
        )
        payload = evaluate_memory_os_admission(
            plan,
            redis_url="redis://redis.example.internal:6379/0",
            lock_redis_url="redis://redis.example.internal:6379/1",
        )
    finally:
        mind.close()

    markdown = render_memory_os_admission_markdown(payload)

    assert "# WaveMind Memory OS Admission" in markdown
    assert "Query audit traffic enables prewarm and predictive workers" in markdown
    assert "`admitted`" in markdown
    assert "`cache-prewarm`" in markdown


def test_memory_os_admission_cli_writes_artifacts(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    db = tmp_path / "cli.sqlite3"
    output = tmp_path / "memory_os_admission_results.json"
    markdown = tmp_path / "MEMORY_OS_ADMISSION.md"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "--db",
            str(db),
            "memory-os-admission",
            "--target-memories",
            "10000000",
            "--namespace-count",
            "4096",
            "--target-qps",
            "1200",
            "--deployment",
            "production",
            "--allow-plan-only",
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
    assert payload["schema"] == "wavemind.memory_os_admission.v1"
    assert payload["status"] == "plan_only"
    assert payload["admitted"] is False
    assert "WaveMind Memory OS Admission" in markdown.read_text(encoding="utf-8")


def test_memory_os_admission_cli_fail_on_blocked_exits_nonzero(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    db = tmp_path / "blocked.sqlite3"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "--db",
            str(db),
            "memory-os-admission",
            "--target-memories",
            "10000000",
            "--namespace-count",
            "4096",
            "--deployment",
            "production",
            "--fail-on-blocked",
            "--json",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
