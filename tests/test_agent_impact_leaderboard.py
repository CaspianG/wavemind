import json
import subprocess
import sys
from pathlib import Path


def test_agent_impact_leaderboard_renderer_writes_json_and_markdown(tmp_path):
    output = tmp_path / "agent_impact_results.json"
    markdown = tmp_path / "AGENT_IMPACT.md"
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "benchmarks/agent_impact_leaderboard.py",
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

    assert payload["schema"] == "wavemind.agent_impact_leaderboard.v1"
    assert payload["summary"]["benchmark_count"] >= 6
    assert payload["summary"]["wavemind_row_count"] >= 6
    assert payload["summary"]["baseline_row_count"] >= 6
    assert payload["summary"]["wavemind_primary_wins"] == payload["summary"]["benchmark_count"]
    assert payload["summary"]["average_primary_lift"] > 0
    assert payload["summary"]["average_context_saved"] > 0.5
    assert payload["summary"]["average_stale_safety_score"] >= 0.95
    assert payload["load_errors"] == []

    groups = {row["benchmark"]: row for row in payload["benchmark_groups"]}
    assert groups["Agent coherence and token savings"]["primary_lift"] >= 0.5 - 1e-12
    assert groups["LongMemEval answer quality"]["primary_lift"] > 0.1

    wavemind_rows = {
        (row["benchmark"], row["engine"]): row
        for row in payload["wavemind_rankings"]
    }
    coherence = wavemind_rows[("Agent coherence and token savings", "WaveMind")]
    assert coherence["primary_label"] == "task success"
    assert coherence["primary_value"] > coherence["best_baseline_primary"]
    assert coherence["context_budget_saved"] > 0.9
    assert coherence["stale_safety_score"] == 1.0

    memory_os = wavemind_rows[("Agent coherence and token savings", "WaveMind + Memory OS")]
    assert memory_os["primary_value"] == coherence["primary_value"]
    assert memory_os["primary_lift_vs_best_baseline"] == coherence[
        "primary_lift_vs_best_baseline"
    ]

    assert report.startswith("# WaveMind Agent Impact Leaderboard")
    assert "WaveMind primary wins" in report
    assert "LongMemEval answer quality" in report
    assert "Answer-quality rows use the checked-in local Ollama" in report


def test_checked_in_agent_impact_artifact_is_machine_readable():
    payload = json.loads(
        Path("benchmarks/agent_impact_results.json").read_text(encoding="utf-8")
    )
    report = Path("benchmarks/AGENT_IMPACT.md").read_text(encoding="utf-8")

    assert payload["schema"] == "wavemind.agent_impact_leaderboard.v1"
    assert payload["summary"]["benchmark_count"] >= 6
    assert payload["summary"]["wavemind_primary_wins"] == payload["summary"][
        "benchmark_count"
    ]
    assert payload["summary"]["average_primary_lift"] > 0
    assert payload["load_errors"] == []
    assert "Agent-impact rows come from checked-in benchmark artifacts" in report
