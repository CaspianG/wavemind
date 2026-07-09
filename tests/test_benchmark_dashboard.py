import subprocess
import sys
from pathlib import Path


def test_benchmark_dashboard_renderer_writes_static_html(tmp_path):
    output = tmp_path / "benchmark-dashboard.html"
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "benchmarks/render_benchmark_dashboard.py",
            "--output",
            str(output),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    html = output.read_text(encoding="utf-8")

    assert html.startswith("<!doctype html>")
    assert "<title>WaveMind Living Benchmark Dashboard</title>" in html
    assert "WaveMind Living Benchmark Dashboard" in html
    assert "assets/benchmark-summary.svg" in html
    assert "Publication Contract" in html
    assert "claim-limited until strict production evidence passes" in html
    assert "weekly schedule: true" in html
    assert "github pages deploy: true" in html
    assert "no scheduled bot commit to main: true" in html
    assert "Agent Impact" in html
    assert "Behavioral evidence: task success" in html
    assert "WaveMind wins" in html
    assert "benchmarks/AGENT_IMPACT.md" in html
    assert "Structured Memory" in html
    assert "Typed memory evidence: image, audio, video, 3D, table, event, graph" in html
    assert "Cross-modal precision@1" in html
    assert "benchmarks/STRUCTURED_MEMORY.md" in html
    assert "Memory OS Intelligence" in html
    assert "Worker evidence: hot-query prewarm" in html
    assert "Predictive warmed" in html
    assert "benchmarks/MEMORY_OS_INTELLIGENCE.md" in html
    assert "Cluster Autoscale" in html
    assert "Cluster evidence: shard placement" in html
    assert "100M capacity nodes" in html
    assert "benchmarks/CLUSTER_AUTOSCALE.md" in html
    assert "Benchmark Leaderboard" in html
    assert "Evidence Source Status" in html
    assert "External HTTP active-active" in html
    assert "Production readiness gate" in html
    assert "Planned rows are not claimed wins" in html
    assert "benchmarks/benchmark_matrix_results.json" in html
    assert "data/leaderboard-status.json" in html
    assert "benchmarks/PRODUCTION_EVIDENCE.md" in html
