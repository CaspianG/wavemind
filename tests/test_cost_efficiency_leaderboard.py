import json
import subprocess
import sys
from pathlib import Path


def test_cost_efficiency_leaderboard_renderer_writes_json_and_markdown(tmp_path):
    output = tmp_path / "cost_efficiency_results.json"
    markdown = tmp_path / "COST_EFFICIENCY.md"
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "benchmarks/cost_efficiency_leaderboard.py",
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

    assert payload["schema"] == "wavemind.cost_efficiency_leaderboard.v1"
    assert payload["summary"]["measured_row_count"] >= 10
    assert payload["summary"]["planned_row_count"] == 5
    assert payload["summary"]["measured_slo_pass_count"] >= 1
    assert payload["summary"]["measured_valid_cost_count"] >= 1
    assert payload["summary"]["planned_valid_cost_count"] == 5
    assert "1m" in payload["summary"]["best_measured_by_target_class"]
    assert payload["summary"]["best_planned_by_target_class"]["50m"] == "faiss-ivfpq-50m"
    assert "qdrant-sharded-100m" in payload["summary"]["planned_frontier_profiles"]
    assert payload["load_errors"] == []

    measured = {row["profile"]: row for row in payload["measured_rows"]}
    planned = {row["profile"]: row for row in payload["planned_rows"]}

    qdrant_1m = payload["summary"]["best_measured_by_target_class"]["1m"]
    assert measured[qdrant_1m]["evidence_level"] == "measured"
    assert measured[qdrant_1m]["memory_count"] == 1_000_000
    assert measured[qdrant_1m]["valid_cost"] is True
    assert measured[qdrant_1m]["compute_cost_per_1m_queries_usd"] > 0

    qdrant_10m = next(
        row
        for row in payload["measured_rows"]
        if row["source_file"] == "benchmarks/production_streaming_load_qdrant_10m_results.json"
    )
    assert qdrant_10m["memory_count"] == 10_000_000
    assert qdrant_10m["recall_at_k"] >= 0.95
    assert qdrant_10m["p99_latency_ms"] < 100.0
    assert qdrant_10m["valid_cost"] is True

    qdrant_sharded_10m = next(
        row
        for row in payload["measured_rows"]
        if row["source_file"]
        == "benchmarks/production_streaming_load_qdrant_sharded_10m_results.json"
    )
    assert qdrant_sharded_10m["memory_count"] == 10_000_000
    assert qdrant_sharded_10m["recall_at_k"] >= 0.95
    assert qdrant_sharded_10m["p99_latency_ms"] < 100.0
    assert qdrant_sharded_10m["valid_cost"] is True

    assert planned["faiss-ivfpq-50m"]["evidence_level"] == "planned"
    assert planned["faiss-ivfpq-50m"]["memory_count"] == 50_000_000
    assert planned["faiss-ivfpq-50m"]["claim_status"] == "plan_only"
    assert "production_streaming_load_ivfpq_50m_results.json" in (
        planned["faiss-ivfpq-50m"]["output_artifact"]
    )

    assert report.startswith("# WaveMind Cost Efficiency Leaderboard")
    assert "Measured Cost Frontier" in report
    assert "Planned Cost Frontier" in report
    assert "Qdrant service streaming" in report
    assert "qdrant-sharded-100m" in report
    assert "planned rows are capacity/cost contracts only" in report


def test_checked_in_cost_efficiency_artifact_is_machine_readable():
    payload = json.loads(
        Path("benchmarks/cost_efficiency_results.json").read_text(encoding="utf-8")
    )

    assert payload["schema"] == "wavemind.cost_efficiency_leaderboard.v1"
    assert payload["summary"]["measured_row_count"] >= 10
    assert payload["summary"]["planned_row_count"] == 5
    assert payload["summary"]["best_planned_by_target_class"]["100m_plus"] == (
        "qdrant-sharded-100m"
    )
