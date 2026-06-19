import subprocess
import sys
from pathlib import Path


def test_benchmark_report_renderer_writes_status_report(tmp_path):
    output = tmp_path / "BENCHMARK_REPORT.md"
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "benchmarks/render_benchmark_report.py",
            "--output",
            str(output),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    report = output.read_text(encoding="utf-8")

    assert report.startswith("# WaveMind Benchmark Report")
    assert "## Completed Runs" in report
    assert "## Public Benchmark Roadmap" in report
    assert "VectorDBBench" in report
    assert "LoCoMo evidence retrieval runner" in report
    assert "Planned rows are not claimed wins." in report
