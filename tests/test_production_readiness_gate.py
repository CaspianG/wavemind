import json
import subprocess
import sys
from pathlib import Path


def test_production_readiness_gate_reports_current_blockers():
    from benchmarks.production_readiness_gate import evaluate_production_readiness

    payload = evaluate_production_readiness()
    criteria = {row["id"]: row for row in payload["criteria"]}

    assert payload["schema"] == "wavemind.production_readiness.v1"
    assert payload["summary"]["pass_count"] >= 14
    assert payload["summary"]["action_required_count"] == 0
    assert payload["summary"]["fail_count"] == 0
    assert payload["overall_status"] == "pass"
    assert criteria["production_100k_slo_cost"]["status"] == "pass"
    assert criteria["production_1m_slo"]["status"] == "pass"
    assert criteria["production_1m_query_depth"]["status"] == "pass"
    assert criteria["cluster_ha_placement"]["status"] == "pass"
    assert criteria["memory_os_worker"]["status"] == "pass"
    assert "usage-pattern priority boosts" in criteria["memory_os_worker"]["requirement"]
    assert "priority predictions" in criteria["memory_os_worker"]["evidence"]
    assert criteria["redis_shared_cache_memory_os"]["status"] == "pass"
    assert "shareable across workers" in criteria["redis_shared_cache_memory_os"]["requirement"]
    assert criteria["api_cache_mutation_safety"]["status"] == "pass"
    assert "cannot leave stale cached recall" in criteria["api_cache_mutation_safety"]["requirement"]
    assert criteria["real_redis_api_load_ci"]["status"] == "pass"
    assert "multiple uvicorn workers" in criteria["real_redis_api_load_ci"]["requirement"]
    assert "success_rate 1.0" in criteria["real_redis_api_load_ci"]["evidence"]
    assert criteria["distributed_http_shard_transport"]["status"] == "pass"
    assert criteria["replicated_runtime_loss"]["status"] == "pass"
    assert "concurrent read/write traffic" in criteria["replicated_runtime_loss"]["requirement"]
    assert "concurrent hit rate" in criteria["replicated_runtime_loss"]["evidence"]
    assert criteria["structured_multimodal_payloads"]["status"] == "pass"
    assert criteria["ten_million_load_profile"]["status"] == "pass"
    assert payload["external_evidence"][0]["id"] == "memory_competitor_adapters"
    assert payload["external_evidence"][0]["status"] == "action_required"


def test_production_readiness_gate_cli_writes_json_and_markdown(tmp_path):
    output = tmp_path / "readiness.json"
    markdown = tmp_path / "readiness.md"
    project_root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [
            sys.executable,
            "benchmarks/production_readiness_gate.py",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    report = markdown.read_text(encoding="utf-8")

    assert "pass" in completed.stdout
    assert payload["summary"]["total_criteria"] == 19
    assert "# WaveMind Production Readiness Gate" in report
    assert "100k service-backed load profile passes SLO and cost gate" in report
    assert "Redis-compatible shared cache and Memory OS prewarm work" in report
    assert "API cache does not serve stale memory after mutations" in report
    assert "Real Redis multi-process API load passes SLO" in report
    assert "Non-Gating External Evidence" in report
