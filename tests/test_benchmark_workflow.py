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
    assert workflow.count("benchmarks/benchmark_registry.py") == 2
    assert workflow.count("benchmarks/validate_benchmark_artifacts.py") == 2
    assert workflow.index("benchmarks/validate_benchmark_artifacts.py") < workflow.index(
        "benchmarks/production_readiness_gate.py"
    )
    assert "--output docs/assets/benchmark-summary.svg" in workflow
    assert "tests/test_benchmark_charts.py" in workflow
    assert "tests/test_http_cluster_load_benchmark.py" in workflow
    assert "git diff --quiet -- benchmarks docs/assets/benchmark-summary.svg" in workflow
    assert "git add benchmarks docs/assets/benchmark-summary.svg" in workflow
    assert "docs/assets/benchmark-summary.svg" in workflow


def test_external_http_cluster_workflow_runs_real_node_load_profile():
    workflow = Path(".github/workflows/external-http-cluster-load.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch" in workflow
    assert "contents: write" in workflow
    assert "WAVEMIND_CLUSTER_NODES" in workflow
    assert "WAVEMIND_CLUSTER_NODES_MANIFEST_JSON" in workflow
    assert "nodes_manifest_json" in workflow
    assert "re.split" in workflow
    assert r'[\n,;]+' in workflow
    assert "secrets.WAVEMIND_API_KEY" in workflow
    assert "read_quorum:" in workflow
    assert "read_fanout:" in workflow
    assert "READ_QUORUM" in workflow
    assert "READ_FANOUT" in workflow
    assert "benchmarks/http_cluster_load_benchmark.py" in workflow
    assert "--read-quorum" in workflow
    assert "--read-fanout" in workflow
    assert "--nodes-file" in workflow
    assert "--deployment-id" in workflow
    assert "--environment" in workflow
    assert "--source" in workflow
    assert "benchmarks/http_cluster_load_results.json" in workflow
    assert "--fail-on-slo" in workflow
    assert "external cluster load benchmark requires at least four nodes or nodes_manifest_json" in workflow
    assert "benchmarks/benchmark_registry.py" in workflow
    assert "benchmarks/render_benchmark_report.py" in workflow
    assert "benchmarks/render_benchmark_leaderboard.py" in workflow
    assert "benchmarks/render_benchmark_charts.py" in workflow
    assert "benchmarks/validate_benchmark_artifacts.py" in workflow
    assert "if: ${{ inputs.commit_results }}" in workflow
    assert "git add benchmarks docs/assets/benchmark-summary.svg" in workflow
    assert "actions/upload-artifact@v7" in workflow


def test_full_check_blocks_stale_public_benchmark_artifacts():
    workflow = Path(".github/workflows/full-check.yml").read_text(encoding="utf-8")

    assert "benchmark-artifact-gate:" in workflow
    assert "local-http-cluster-smoke:" in workflow
    assert "benchmarks/local_http_cluster_smoke.py" in workflow
    assert "--read-fanout 1" in workflow
    assert "benchmarks/local_http_cluster_smoke_ci_results.json" in workflow
    assert "Block stale or unsynchronized public benchmark artifacts" in workflow
    assert "benchmarks/validate_benchmark_artifacts.py" in workflow
    assert "--max-age-days 8" in workflow
    assert "benchmarks/benchmark_artifact_audit_ci.json" in workflow
    assert "benchmarks/production_readiness_gate.py" in workflow


def test_release_blocks_stale_public_benchmark_artifacts():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "Validate benchmark freshness gate" in workflow
    assert "benchmarks/validate_benchmark_artifacts.py" in workflow
    assert "--max-age-days 8" in workflow
    assert "benchmarks/benchmark_artifact_audit_ci.json" in workflow
    assert "benchmarks/production_readiness_gate.py" in workflow
    assert workflow.index("Validate benchmark freshness gate") < workflow.index(
        "Build and verify package"
    )
