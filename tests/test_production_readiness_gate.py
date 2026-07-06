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
    assert payload["summary"]["action_required_count"] == 1
    assert payload["summary"]["fail_count"] == 0
    assert payload["overall_status"] == "action_required"
    assert criteria["production_100k_slo_cost"]["status"] == "pass"
    assert criteria["production_1m_slo"]["status"] == "pass"
    assert criteria["production_1m_query_depth"]["status"] == "pass"
    assert criteria["cluster_ha_placement"]["status"] == "pass"
    assert criteria["structured_multimodal_payloads"]["status"] == "pass"
    assert criteria["real_competitor_adapters"]["status"] == "action_required"
    assert criteria["ten_million_load_profile"]["status"] == "pass"


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

    assert "action_required" in completed.stdout
    assert payload["summary"]["total_criteria"] == 15
    assert "# WaveMind Production Readiness Gate" in report
    assert "100k service-backed load profile passes SLO and cost gate" in report
