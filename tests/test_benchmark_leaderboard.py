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
    assert "| benchmark | category | primary metric |" in leaderboard
    assert "Dynamic memory policy" in leaderboard
    assert "Chroma static" in leaderboard
    assert "WaveMind leads on quality" in leaderboard
    assert "Quality tie; WaveMind slower" in leaderboard
    assert "Quality tie; WaveMind faster" in leaderboard
    assert "WaveMind-only check" in leaderboard
    assert "LongMemEval answer generation" in leaderboard
    assert "token F1" in leaderboard
    assert "extractive smoke: 0.024" not in leaderboard
    assert "WaveMind dynamic capacity" in leaderboard
