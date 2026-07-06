import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from wavemind import (
    HashingTextEncoder,
    WaveMind,
    advice_status_meets_or_exceeds,
    advise_memory_architecture,
)
from wavemind.api import create_app


def run_cli_unchecked(*args, cwd=None):
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
        check=False,
    )


def test_architecture_advisor_requires_service_index_and_sharding():
    advice = advise_memory_architecture(
        {
            "active_memories": 25_000,
            "total_memories": 25_000,
            "expired_memories": 0,
            "audit_events": 0,
            "index": "numpy",
            "index_healthy": True,
            "vector_dim": 384,
        },
        target_memories=10_000_000,
        namespace_count=4096,
        node_count=2,
        replication_factor=3,
        read_quorum=1,
        read_fanout=3,
        deployment="production",
        observed_p99_ms=180.0,
        target_p99_ms=100.0,
        multimodal=True,
    )
    payload = advice.as_dict()
    ids = {item["id"] for item in payload["recommendations"]}

    assert advice.status == "architecture_required"
    assert payload["production_ready"] is False
    assert payload["read_quorum"] == 1
    assert payload["read_fanout"] == 3
    assert "ann-candidate-index" in ids
    assert "bounded-read-fanout" in ids
    assert "service-index" in ids
    assert "namespace-sharding" in ids
    assert "replication-capacity" in ids
    assert "latency-slo" in ids
    assert "multimodal-payloads" in ids
    assert any("http_cluster_load_benchmark.py" in command for command in advice.next_commands)
    assert any("--read-fanout 1" in command for command in advice.next_commands)


def test_architecture_advisor_rejects_impossible_read_fanout():
    advice = advise_memory_architecture(
        {
            "active_memories": 1000,
            "total_memories": 1000,
            "expired_memories": 0,
            "audit_events": 1,
            "index": "faiss-persisted",
            "index_healthy": True,
            "vector_dim": 384,
        },
        target_memories=1000,
        replication_factor=2,
        read_quorum=1,
        read_fanout=3,
        deployment="staging",
    )
    ids = {item.id for item in advice.recommendations}

    assert advice.status == "architecture_required"
    assert advice.replication_factor == 2
    assert advice.read_fanout == 3
    assert "invalid-read-quorum" in ids


def test_architecture_advisor_flags_unhealthy_index_and_expired_pressure():
    advice = advise_memory_architecture(
        {
            "active_memories": 100,
            "total_memories": 140,
            "expired_memories": 40,
            "audit_events": 10,
            "index": "faiss-persisted",
            "index_healthy": False,
            "vector_dim": 384,
        },
        target_memories=500,
    )
    ids = {item.id for item in advice.recommendations}

    assert advice.status == "architecture_required"
    assert "index-health" in ids
    assert "expired-memory-pressure" in ids
    assert advice_status_meets_or_exceeds(advice.status, "action_required") is True


def test_cli_advise_json_and_fail_on_threshold(tmp_path):
    result = run_cli_unchecked(
        "--db",
        str(tmp_path / "advisor.sqlite3"),
        "advise",
        "--current-memories",
        "10000",
        "--target-memories",
        "2000000",
        "--namespace-count",
        "4096",
        "--node-count",
        "2",
        "--read-quorum",
        "1",
        "--read-fanout",
        "3",
        "--deployment",
        "production",
        "--fail-on",
        "architecture_required",
        "--json",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 3
    assert payload["status"] == "architecture_required"
    assert payload["read_quorum"] == 1
    assert payload["read_fanout"] == 3
    assert payload["scale_plan"]["tier"] == "million-plus"
    assert any(item["id"] == "bounded-read-fanout" for item in payload["recommendations"])
    assert any(item["id"] == "namespace-sharding" for item in payload["recommendations"])


def test_api_architecture_advice_uses_live_stats(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "advisor-api.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        mind.remember("architecture advisor live memory", namespace="ops")
        with TestClient(create_app(mind=mind)) as client:
            response = client.get(
                "/architecture/advice",
                params={
                    "namespace": "ops",
                    "target_memories": 2_000_000,
                    "namespace_count": 4096,
                    "node_count": 2,
                    "read_quorum": 1,
                    "read_fanout": 3,
                    "deployment": "production",
                    "multimodal": "true",
                },
            )
        payload = response.json()
    finally:
        mind.close()

    assert response.status_code == 200
    assert payload["current_memories"] == 1
    assert payload["target_memories"] == 2_000_000
    assert payload["read_quorum"] == 1
    assert payload["read_fanout"] == 3
    assert payload["status"] == "architecture_required"
    ids = {item["id"] for item in payload["recommendations"]}
    assert "bounded-read-fanout" in ids
    assert "namespace-sharding" in ids
    assert "production-controls" in ids
    assert "multimodal-payloads" in ids
