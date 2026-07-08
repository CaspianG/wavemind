import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from wavemind import (
    HashingTextEncoder,
    ProductionCostTarget,
    ProductionSLOTarget,
    WaveMind,
    build_production_scale_run_plan,
    estimate_production_cost,
    evaluate_production_slo,
    production_scale_profile_names,
)
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


def test_production_cost_api_estimates_compute_and_storage_costs():
    slo = evaluate_production_slo(
        engine="Qdrant service",
        recall_at_k=1.0,
        avg_latency_ms=10.0,
        p99_latency_ms=25.0,
        target=ProductionSLOTarget(target_qps=100.0, replicas=3),
    )

    cost = estimate_production_cost(
        slo=slo,
        memory_count=100_000,
        vector_dim=128,
        target=ProductionCostTarget(
            replica_hourly_cost_usd=0.25,
            storage_gb_monthly_cost_usd=0.10,
            memory_payload_kb=2.0,
            vector_dtype_bytes=4,
        ),
    )

    assert cost.cost_status == "valid_slo"
    assert cost.required_replicas == 2
    assert cost.compute_cost_per_1m_queries_usd == pytest.approx(1.3888888889)
    assert cost.total_storage_gb > 0
    assert cost.monthly_total_cost_at_target_qps_usd > cost.monthly_storage_cost_usd


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


def test_production_scale_run_plan_reports_missing_service_env():
    payload = build_production_scale_run_plan(
        profiles=["qdrant-10m"],
        env={},
        disk_free_gb=1000.0,
    )
    summary = payload["summary"]
    row = payload["profiles"][0]

    assert payload["generated_at"].endswith("Z")
    assert summary["generated_at"] == payload["generated_at"]
    assert summary["overall_status"] == "action_required"
    assert summary["total_profiles"] == 1
    assert row["profile"] == "qdrant-10m"
    assert row["target_memories"] == 10_000_000
    assert row["output_artifact"].endswith("production_streaming_load_qdrant_10m_results.json")
    assert row["checkpoint_path"].endswith("qdrant-service-10000000.checkpoint.json")
    assert "WAVEMIND_QDRANT_URL" in row["required_env"]
    assert row["missing_env"] == ("WAVEMIND_QDRANT_URL",)
    assert "missing_env:WAVEMIND_QDRANT_URL" in row["blockers"]
    assert "--checkpoint-path" in row["command"]
    assert row["claim_boundary"].startswith("plan_only")


def test_production_scale_run_plan_can_mark_profile_ready(monkeypatch):
    monkeypatch.setattr("wavemind.scale._module_available", lambda name: True)

    payload = build_production_scale_run_plan(
        profiles=["pgvector-10m"],
        env={"WAVEMIND_PGVECTOR_DSN": "postgresql://example/wavemind"},
        disk_free_gb=1000.0,
    )
    row = payload["profiles"][0]

    assert payload["summary"]["overall_status"] == "ready"
    assert row["status"] == "ready"
    assert row["missing_env"] == ()
    assert row["blockers"] == ()
    assert row["slo_capacity_envelope"]["status"] in {"pass", "scale_required"}
    assert row["slo_capacity_envelope"]["required_replicas"] <= row["autoscaling_max_replicas"]
    assert row["cost_envelope"]["memory_count"] == 10_000_000
    assert row["estimated_application_storage_gb"] > 20


def test_production_scale_run_plan_all_profiles_and_known_names():
    names = production_scale_profile_names()
    assert "qdrant-sharded-100m" in names
    assert "faiss-ivfpq-50m" in names

    payload = build_production_scale_run_plan(
        profiles=["all"],
        env={},
        disk_free_gb=0.0,
    )

    assert payload["summary"]["total_profiles"] == len(names)
    assert payload["summary"]["target_memories_total"] >= 180_000_000
    assert payload["summary"]["overall_status"] == "action_required"
    profiles = {row["profile"]: row for row in payload["profiles"]}
    assert profiles["faiss-ivfpq-50m"]["estimated_index_gb"] > 1.0
    assert profiles["faiss-ivfpq-50m"]["required_local_free_gb"] > 1.0
    assert profiles["qdrant-sharded-100m"]["target_qps"] == 500.0


def test_cli_production_scale_plan_writes_deterministic_artifact(tmp_path):
    output = tmp_path / "production-scale-plan.json"
    result = run_cli(
        "production-scale-plan",
        "--profile",
        "qdrant-10m",
        "--disk-free-gb",
        "0",
        "--write-artifact",
        "--output",
        str(output),
        "--json",
    )
    payload = json.loads(result.stdout)
    written = json.loads(output.read_text(encoding="utf-8"))

    assert payload == written
    assert payload["generated_at"].endswith("Z")
    assert payload["summary"]["overall_status"] == "action_required"
    assert payload["profiles"][0]["profile"] == "qdrant-10m"
    assert payload["profiles"][0]["disk_free_gb"] == 0.0


def test_cli_production_scale_plan_fail_on_action_required(tmp_path):
    result = run_cli_unchecked(
        "production-scale-plan",
        "--profile",
        "qdrant-10m",
        "--disk-free-gb",
        "0",
        "--fail-on-action-required",
        "--json",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 3
    assert payload["summary"]["overall_status"] == "action_required"
