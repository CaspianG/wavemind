import subprocess
import sys
from pathlib import Path


def test_benchmark_leaderboard_renderer_writes_compact_leaderboard(tmp_path):
    output = tmp_path / "BENCHMARK_LEADERBOARD.md"
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "benchmarks/render_benchmark_leaderboard.py",
            "--output",
            str(output),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    leaderboard = output.read_text(encoding="utf-8")

    assert leaderboard.startswith("# WaveMind Benchmark Leaderboard")
    assert "Last refresh:" in leaderboard
    assert "| benchmark | category | primary metric |" in leaderboard
    assert "Dynamic memory policy" in leaderboard
    assert "Chroma static" in leaderboard
    assert "WaveMind leads on quality" in leaderboard
    assert "Quality tie; WaveMind slower" in leaderboard
    assert "Quality tie; WaveMind faster" in leaderboard
    assert "WaveMind-only check" in leaderboard
    assert "LongMemEval answer generation" in leaderboard
    assert "Production index profile" in leaderboard
    assert "Production readiness gate" in leaderboard
    assert "readiness score" in leaderboard
    assert "Qdrant service" in leaderboard
    assert "production SLO pass: Qdrant service" in leaderboard
    assert "production SLO miss" in leaderboard
    assert "cost: Qdrant service $1.39/1M queries" in leaderboard
    assert "cost if SLO fixed:" in leaderboard
    assert "token F1" in leaderboard
    assert "extractive smoke: 0.024" not in leaderboard
    assert "WaveMind dynamic capacity" in leaderboard


def test_benchmark_leaderboard_workflow_reruns_core_artifacts():
    workflow = Path(".github/workflows/benchmark-leaderboard.yml").read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "contents: write" in workflow
    assert "dynamic_memory_benchmark.py" in workflow
    assert "field_memory_dynamics_benchmark.py" in workflow
    assert "scale_readiness_benchmark.py" in workflow
    assert "production_streaming_load_benchmark.py" in workflow
    assert "production_readiness_gate.py" in workflow
    assert "benchmark_registry.py" in workflow
    assert "render_benchmark_report.py" in workflow
    assert "render_benchmark_leaderboard.py" in workflow
    assert "validate_benchmark_artifacts.py" in workflow
    assert "--max-age-days 8" in workflow
    assert "WAVEMIND_BENCHMARK_REFRESH_PROFILE: weekly-fast" in workflow
    assert "benchmark_artifact_audit.json" in workflow
    assert "production_readiness_results.json" in workflow
    assert "production_streaming_load_smoke_results.json" in workflow
    assert "PRODUCTION_READINESS.md" in workflow
    assert "git commit -m \"Refresh benchmark leaderboard\"" in workflow
