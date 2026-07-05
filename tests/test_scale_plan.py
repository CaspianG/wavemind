import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from wavemind import HashingTextEncoder, ProductionSLOTarget, WaveMind, evaluate_production_slo
from wavemind.scale import build_scale_plan, scale_status_meets_or_exceeds


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


def test_scale_plan_keeps_small_memory_on_simple_local_path():
    plan = build_scale_plan(
        current_memories=250,
        target_memories=750,
        index="numpy",
    )

    assert plan.tier == "small"
    assert plan.status == "ok"
    assert plan.recommended_index == "numpy"
    assert not plan.warnings
    assert any("NumPy exact" in action for action in plan.actions)


def test_wave_mind_exposes_scale_plan_for_python_integrations(tmp_path):
    mind = WaveMind(
        db_path=tmp_path / "scale.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        mind.remember("python integration can inspect scale readiness", namespace="ops")
        plan = mind.scale_plan(namespace="ops", target_memories=50_000)

        assert plan.current_memories == 1
        assert plan.namespace == "ops"
        assert plan.tier == "large-local"
        assert plan.status == "action_required"
    finally:
        mind.close()


def test_scale_plan_warns_when_numpy_is_used_past_local_watch_limit():
    plan = build_scale_plan(
        current_memories=5_001,
        target_memories=50_000,
        index="numpy",
        latency_target_ms=10.0,
    )

    assert plan.tier == "large-local"
    assert plan.status == "action_required"
    assert plan.recommended_index == "faiss-persisted or qdrant"
    assert any("Do not use NumPy exact" in warning for warning in plan.warnings)
    assert any("Current index is NumPy exact" in warning for warning in plan.warnings)
    assert any("WAVEMIND_FAISS_PATH" in action for action in plan.actions)
    assert any("index-health" in action for action in plan.actions)


def test_scale_status_threshold_helper_supports_deploy_gates():
    assert scale_status_meets_or_exceeds("action_required", "watch") is True
    assert scale_status_meets_or_exceeds("watch", "action_required") is False


def test_production_slo_api_estimates_autoscaling_capacity():
    target = ProductionSLOTarget(
        target_recall_at_k=0.95,
        target_p99_ms=100.0,
        target_qps=100.0,
        replicas=3,
        autoscaling_max_replicas=24,
        capacity_headroom=0.70,
    )

    passing = evaluate_production_slo(
        engine="Qdrant service",
        recall_at_k=1.0,
        avg_latency_ms=10.0,
        p99_latency_ms=25.0,
        target=target,
    )

    assert passing.status == "pass"
    assert passing.required_replicas == 2
    assert passing.autoscaled_capacity_qps > 1000
    assert passing.blocking_reasons == ()
    assert passing.as_dict()["status"] == "pass"

    failing = evaluate_production_slo(
        engine="Qdrant service",
        recall_at_k=0.984,
        avg_latency_ms=116.80,
        p99_latency_ms=209.28,
        target=target,
    )

    assert failing.status == "fail"
    assert failing.required_replicas == 17
    assert failing.blocking_reasons == ("p99_above_target",)

    with pytest.raises(ValueError, match="autoscaling_max_replicas"):
        ProductionSLOTarget(replicas=4, autoscaling_max_replicas=3)


def test_scale_plan_requires_service_architecture_for_million_plus_memory():
    plan = build_scale_plan(
        current_memories=100_000,
        target_memories=2_000_000,
        index="qdrant",
    )

    assert plan.tier == "million-plus"
    assert plan.status == "architecture_required"
    assert "external vector database" in plan.recommended_index
    assert any("memory-policy layer" in warning for warning in plan.warnings)
    assert any("Partition memory" in action for action in plan.actions)


def test_cli_scale_plan_reports_json_from_current_database(tmp_path):
    db_path = tmp_path / "scale.sqlite3"
    run_cli("--db", str(db_path), "remember", "scale readiness memory", "--namespace", "ops")

    result = run_cli(
        "--db",
        str(db_path),
        "scale-plan",
        "--namespace",
        "ops",
        "--target-memories",
        "50000",
        "--json",
    )
    payload = json.loads(result.stdout)

    assert payload["current_memories"] == 1
    assert payload["target_memories"] == 50000
    assert payload["namespace"] == "ops"
    assert payload["tier"] == "large-local"
    assert payload["recommended_index"] == "faiss-persisted or qdrant"


def test_cli_scale_plan_can_run_without_loading_optional_index_backend(tmp_path):
    result = run_cli(
        "--db",
        str(tmp_path / "missing.sqlite3"),
        "--index",
        "faiss",
        "scale-plan",
        "--current-memories",
        "10000",
        "--target-memories",
        "50000",
        "--json",
    )
    payload = json.loads(result.stdout)

    assert payload["index"] == "faiss"
    assert payload["current_memories"] == 10000
    assert payload["tier"] == "large-local"
    assert any("FAISS" in action for action in payload["actions"])


def test_cli_scale_plan_fail_on_returns_nonzero_for_deploy_preflight(tmp_path):
    result = run_cli_unchecked(
        "--db",
        str(tmp_path / "scale.sqlite3"),
        "scale-plan",
        "--current-memories",
        "10000",
        "--target-memories",
        "50000",
        "--fail-on",
        "action_required",
        "--json",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 3
    assert payload["status"] == "action_required"
