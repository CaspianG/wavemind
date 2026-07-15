import json
import copy
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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


def _remote_runtime_evidence() -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema": "wavemind.memory_os_remote_worker_soak.v1",
        "status": "pass",
        "environment": "remote_worker_cluster",
        "source_ref": "a" * 40,
        "started_at": now,
        "finished_at": now,
        "config": {
            "min_duration_seconds": 21_600,
            "min_worker_cycles": 500,
        },
        "metrics": {
            "duration_seconds": 21_600,
            "worker_cycles": 500,
            "completed_runs": 500,
            "duplicate_retries": 500,
            "job_request_attempts": 2_500,
            "job_request_failures": 0,
            "error_rate": 0.0,
            "lock_breach_count": 0,
            "duplicate_mutation_count": 0,
            "state_corruption_count": 0,
        },
        "preflight": {
            "status": "pass",
            "topology": {
                "worker_count": 2,
                "distinct_worker_count": 2,
                "worker_https": True,
                "redis_tls": True,
            },
        },
        "checks": [
            {"id": check_id, "passed": True}
            for check_id in [
                "remote-topology",
                "worker-health",
                "worker-version",
                "worker-commit",
                "worker-plan",
                "remote-redis-semantics",
                "soak-duration",
                "worker-cycles",
                "cross-worker-single-flight",
                "cross-worker-retry",
                "error-rate",
                "lock-safety",
                "duplicate-mutation-safety",
                "state-integrity",
                "no-in-doubt-jobs",
                "cleanup",
            ]
        ],
    }


def _quality_evidence() -> dict:
    return json.loads(
        (Path(__file__).resolve().parents[1] / "benchmarks" / "memory_os_quality_results.json").read_text(
            encoding="utf-8"
        )
    )


def _legacy_remote_redis_evidence() -> dict:
    return {
        "schema": "wavemind.memory_os_runtime_soak.v1",
        "status": "pass",
        "environment": "remote_redis",
        "checks": [
            {"id": "single-flight", "passed": True},
            {"id": "duplicate-job-no-mutation", "passed": True},
            {"id": "lease-heartbeat", "passed": True},
        ],
    }


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
            runtime_evidence=_remote_runtime_evidence(),
            quality_evidence=_quality_evidence(),
            expected_commit_sha="a" * 40,
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


@pytest.mark.parametrize(
    ("mutation", "detail_key"),
    [
        (lambda evidence: evidence["metrics"].update(duration_seconds=21_599), "duration_ok"),
        (lambda evidence: evidence["metrics"].update(worker_cycles=499), "worker_cycles_ok"),
        (lambda evidence: evidence["metrics"].update(error_rate=0.001), "integrity_metrics_ok"),
        (lambda evidence: evidence["metrics"].update(lock_breach_count=1), "integrity_metrics_ok"),
        (lambda evidence: evidence["metrics"].update(duplicate_mutation_count=1), "integrity_metrics_ok"),
        (lambda evidence: evidence["metrics"].update(state_corruption_count=1), "integrity_metrics_ok"),
        (lambda evidence: evidence.update(source_ref="b" * 40), "commit_matches"),
        (
            lambda evidence: evidence.update(
                finished_at=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
            ),
            "evidence_fresh",
        ),
    ],
)
def test_memory_os_admission_rejects_invalid_remote_evidence(tmp_path, mutation, detail_key):
    mind = _seed_hot_memory(tmp_path)
    try:
        plan = MemoryOSScheduler(mind).plan(
            namespace="tenant:admission",
            deployment="production",
            target_memories=1_000,
            namespace_count=8,
            node_count=3,
            target_qps=20,
            cache_mode="auto",
        )
        evidence = copy.deepcopy(_remote_runtime_evidence())
        mutation(evidence)
        payload = evaluate_memory_os_admission(
            plan,
            redis_url="redis://redis.example.internal:6379/0",
            lock_redis_url="redis://redis.example.internal:6379/1",
            runtime_evidence=evidence,
            quality_evidence=_quality_evidence(),
            expected_commit_sha="a" * 40,
        )
    finally:
        mind.close()

    assert payload["admitted"] is False
    runtime = next(item for item in payload["requirements"] if item["id"] == "runtime-soak")
    assert runtime["details"][detail_key] is False


def test_memory_os_admission_rejects_quality_non_improvement(tmp_path):
    mind = _seed_hot_memory(tmp_path)
    try:
        plan = MemoryOSScheduler(mind).plan(
            namespace="tenant:admission",
            deployment="production",
            target_memories=1_000,
            namespace_count=8,
            node_count=3,
            target_qps=20,
            cache_mode="auto",
        )
        quality = copy.deepcopy(_quality_evidence())
        quality["metrics"]["task_success_uplift"] = 0.0
        payload = evaluate_memory_os_admission(
            plan,
            redis_url="redis://redis.example.internal:6379/0",
            lock_redis_url="redis://redis.example.internal:6379/1",
            runtime_evidence=_remote_runtime_evidence(),
            quality_evidence=quality,
            expected_commit_sha="a" * 40,
        )
    finally:
        mind.close()

    assert payload["admitted"] is False
    assert "quality-uplift" in payload["summary"]["blocker_ids"]


def test_memory_os_admission_keeps_local_soak_as_only_runtime_blocker(tmp_path):
    mind = _seed_hot_memory(tmp_path)
    try:
        plan = MemoryOSScheduler(mind).plan(
            namespace="tenant:admission",
            deployment="production",
            target_memories=50_000,
            namespace_count=32,
            node_count=3,
            target_qps=50,
            cache_mode="redis",
        )
        evidence = _legacy_remote_redis_evidence()
        evidence["environment"] = "local_redis"
        payload = evaluate_memory_os_admission(
            plan,
            redis_url="redis://127.0.0.1:6379/0",
            lock_redis_url="redis://127.0.0.1:6379/1",
            runtime_evidence=evidence,
            quality_evidence=_quality_evidence(),
        )
    finally:
        mind.close()

    assert payload["status"] == "blocked"
    assert payload["summary"]["blocker_ids"] == ["runtime-soak"]


def test_memory_os_admission_rejects_legacy_remote_redis_without_workers(tmp_path):
    mind = _seed_hot_memory(tmp_path)
    try:
        plan = MemoryOSScheduler(mind).plan(
            namespace="tenant:admission",
            deployment="production",
            target_memories=50_000,
            namespace_count=32,
            node_count=3,
            target_qps=50,
            cache_mode="redis",
        )
        payload = evaluate_memory_os_admission(
            plan,
            redis_url="redis://redis.example.internal:6379/0",
            lock_redis_url="redis://redis.example.internal:6379/1",
            runtime_evidence=_legacy_remote_redis_evidence(),
            quality_evidence=_quality_evidence(),
        )
    finally:
        mind.close()

    assert payload["status"] == "blocked"
    assert payload["summary"]["blocker_ids"] == ["runtime-soak"]
    runtime_requirement = next(
        item for item in payload["requirements"] if item["id"] == "runtime-soak"
    )
    assert runtime_requirement["details"]["runtime_evidence_valid"] is False


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
            runtime_evidence=_remote_runtime_evidence(),
            quality_evidence=_quality_evidence(),
            expected_commit_sha="a" * 40,
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
