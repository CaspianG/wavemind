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
    assert "Agent coherence and token savings" in leaderboard
    assert "task success" in leaderboard
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
    assert "## Evidence Source Status" in leaderboard
    assert "| area | current source | claim status | next action |" in leaderboard
    assert "Artifact freshness" in leaderboard
    assert "Serverless telemetry" in leaderboard
    assert "loopback evidence, not a managed-serverless claim" in leaderboard
    assert "serverless-observed-telemetry.yml" in leaderboard
    assert "External HTTP cluster load" in leaderboard
    assert "local loopback service-node evidence" in leaderboard
    assert "External HTTP active-active" in leaderboard
    assert "no checked-in remote region artifact" in leaderboard
    assert "pgvector tuning" in leaderboard
    assert "iterative recall `0.97`" in leaderboard
    assert "Qdrant streaming" in leaderboard
    assert "Qdrant sharded streaming" in leaderboard
    assert "real two-service fanout smoke" in leaderboard
    assert "Qdrant 1M streaming" in leaderboard
    assert "tuned p99" in leaderboard
    assert "pgvector streaming" in leaderboard
    assert "10M preflight `action_required`" in leaderboard
    assert "10M streaming load" in leaderboard
    assert "50M streaming preflight" in leaderboard
    assert "production_streaming_load_ivfpq_50m_results.json" in leaderboard
    assert "missing_env:WAVEMIND_FAISS_IVFPQ_PATH" in leaderboard
    assert "Production readiness gate" in leaderboard
    assert "Competitor adapters" in leaderboard
    assert "skipped `Zep`" in leaderboard


def test_benchmark_leaderboard_workflow_reruns_core_artifacts():
    workflow = Path(".github/workflows/benchmark-leaderboard.yml").read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "contents: write" in workflow
    assert "agent_coherence_benchmark.py" in workflow
    assert "benchmarks/agent_coherence_results.json" in workflow
    assert "tests/test_agent_coherence_benchmark.py" in workflow
    assert "dynamic_memory_benchmark.py" in workflow
    assert "field_memory_dynamics_benchmark.py" in workflow
    assert "scale_readiness_benchmark.py" in workflow
    assert "production_streaming_load_benchmark.py" in workflow
    assert "qdrant-0:" in workflow
    assert "qdrant-1:" in workflow
    assert "qdrant/qdrant:v1.15.1" in workflow
    assert "WAVEMIND_QDRANT_URLS=http://127.0.0.1:6333,http://127.0.0.1:6334" in workflow
    assert "benchmarks/production_streaming_load_qdrant_sharded_smoke_results.json" in workflow
    assert "--engines qdrant-sharded-service" in workflow
    assert "benchmarks/local_http_active_active_smoke.py" in workflow
    assert "benchmarks/local_http_active_active_smoke_results.json" in workflow
    assert "tests/test_local_http_active_active_smoke.py" in workflow
    assert "production_readiness_gate.py" in workflow
    assert "benchmark_registry.py" in workflow
    assert "render_benchmark_report.py" in workflow
    assert "render_benchmark_leaderboard.py" in workflow
    assert "render_benchmark_dashboard.py" in workflow
    assert "docs/benchmark-dashboard.html" in workflow
    assert "tests/test_benchmark_dashboard.py" in workflow
    assert "validate_benchmark_artifacts.py" in workflow
    assert "--max-age-days 8" in workflow
    assert "WAVEMIND_BENCHMARK_REFRESH_PROFILE: weekly-fast" in workflow
    assert "benchmark_artifact_audit.json" in workflow
    assert "production_readiness_results.json" in workflow
    assert "production_streaming_load_smoke_results.json" in workflow
    assert "production_streaming_load_qdrant_sharded_smoke_results.json" in workflow
    assert "PRODUCTION_READINESS.md" in workflow
    assert "git commit -m \"Refresh benchmark leaderboard\"" in workflow
