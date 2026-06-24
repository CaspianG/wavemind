import subprocess
import sys
from pathlib import Path


def test_benchmark_chart_renderer_writes_svg(tmp_path):
    output = tmp_path / "benchmark-summary.svg"
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "benchmarks/render_benchmark_charts.py",
            "--output",
            str(output),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    svg = output.read_text(encoding="utf-8")

    assert svg.startswith("<svg")
    assert "WaveMind Benchmark Summary" in svg
    assert "Static agent-memory retrieval" in svg
    assert "Dynamic memory policy" in svg
    assert "Long-term memory evidence" in svg
    assert "Capacity and latency curve" in svg
    assert "Public benchmark roadmap" in svg
    assert "VectorDBBench" in svg
    assert "WaveMind evidence recall@5" in svg
    assert "0.94 at 5000 memories" in svg
