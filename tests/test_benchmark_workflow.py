from pathlib import Path


def test_weekly_benchmark_workflow_refreshes_visual_leaderboard():
    workflow = Path(".github/workflows/benchmark-leaderboard.yml").read_text(
        encoding="utf-8"
    )

    assert "cron: \"17 4 * * 1\"" in workflow
    assert "workflow_dispatch" in workflow
    assert "contents: write" in workflow
    assert "benchmarks/render_benchmark_report.py" in workflow
    assert "benchmarks/render_benchmark_leaderboard.py" in workflow
    assert "benchmarks/render_benchmark_charts.py" in workflow
    assert "--output docs/assets/benchmark-summary.svg" in workflow
    assert "tests/test_benchmark_charts.py" in workflow
    assert "git diff --quiet -- benchmarks docs/assets/benchmark-summary.svg" in workflow
    assert "git add benchmarks docs/assets/benchmark-summary.svg" in workflow
    assert "docs/assets/benchmark-summary.svg" in workflow
