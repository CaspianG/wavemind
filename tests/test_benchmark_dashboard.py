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
    assert "Benchmark Leaderboard" in html
    assert "Evidence Source Status" in html
    assert "External HTTP active-active" in html
    assert "Production readiness gate" in html
    assert "Planned rows are not claimed wins" in html
    assert "benchmarks/benchmark_matrix_results.json" in html
