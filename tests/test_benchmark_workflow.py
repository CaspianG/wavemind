from pathlib import Path


def test_weekly_benchmark_workflow_refreshes_visual_leaderboard():
    workflow = Path(".github/workflows/benchmark-leaderboard.yml").read_text(
        encoding="utf-8"
    )

    assert "cron: \"17 4 * * 1\"" in workflow
    assert "workflow_dispatch" in workflow
    assert "contents: read" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "environment:" in workflow
    assert "name: github-pages" in workflow
    assert "url: ${{ steps.deployment.outputs.page_url }}" in workflow
    assert "benchmarks/render_benchmark_report.py" in workflow
    assert "benchmarks/render_benchmark_leaderboard.py" in workflow
    assert "benchmarks/render_benchmark_dashboard.py" in workflow
    assert "benchmarks/render_leaderboard_status.py" in workflow
    assert "benchmarks/render_benchmark_charts.py" in workflow
    assert "benchmarks/production_evidence_gate.py" in workflow
    assert "--output benchmarks/production_evidence_results.json" in workflow
    assert "--markdown-output benchmarks/PRODUCTION_EVIDENCE.md" in workflow
    assert "python -m wavemind production-scale-plan" in workflow
    assert "--output benchmarks/production_scale_run_plan.json" in workflow
    assert workflow.index("production-scale-plan") < workflow.index("production-evidence-bundle")
    assert workflow.count("benchmarks/benchmark_registry.py") == 2
    assert workflow.count("benchmarks/validate_benchmark_artifacts.py") == 2
    assert workflow.index("benchmarks/validate_benchmark_artifacts.py") < workflow.index(
        "benchmarks/production_readiness_gate.py"
    )
    assert "--output docs/assets/benchmark-summary.svg" in workflow
    assert "--output docs/benchmark-dashboard.html" in workflow
    assert "--output docs/data/leaderboard-status.json" in workflow
    assert "tests/test_benchmark_charts.py" in workflow
    assert "tests/test_leaderboard_status.py" in workflow
    assert "tests/test_production_evidence_gate.py" in workflow
    assert "tests/test_http_cluster_load_benchmark.py" in workflow
    assert "qdrant-0:" in workflow
    assert "qdrant-1:" in workflow
    assert "qdrant/qdrant:v1.15.1" in workflow
    assert "WAVEMIND_QDRANT_URLS=http://127.0.0.1:6333,http://127.0.0.1:6334" in workflow
    assert "--engines qdrant-sharded-service" in workflow
    assert "benchmarks/production_streaming_load_qdrant_sharded_smoke_results.json" in workflow
    assert "sharded Qdrant smoke SLO failed" in workflow
    assert "git diff --quiet -- benchmarks docs/assets/benchmark-summary.svg docs/benchmark-dashboard.html docs/data/leaderboard-status.json" in workflow
    assert "Benchmark artifacts changed" in workflow
    assert "commit the reviewed files from a maintainer account" in workflow
    assert "git push" not in workflow
    assert "Build GitHub Pages leaderboard" in workflow
    assert "cp docs/benchmark-dashboard.html site/index.html" in workflow
    assert "cp docs/data/leaderboard-status.json site/data/leaderboard-status.json" in workflow
    assert "cp benchmarks/benchmark_matrix_results.json site/data/benchmark_matrix_results.json" in workflow
    assert "actions/configure-pages@v5" in workflow
    assert "actions/upload-pages-artifact@v3" in workflow
    assert "actions/deploy-pages@v4" in workflow
    assert "docs/assets/benchmark-summary.svg" in workflow
    assert "docs/benchmark-dashboard.html" in workflow
    assert "docs/data/leaderboard-status.json" in workflow
    assert "benchmarks/production_evidence_results.json" in workflow
    assert "benchmarks/PRODUCTION_EVIDENCE.md" in workflow


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
    assert "benchmarks/render_benchmark_dashboard.py" in workflow
    assert "benchmarks/render_leaderboard_status.py" in workflow
    assert "benchmarks/production_readiness_gate.py" in workflow
    assert "benchmarks/production_evidence_gate.py" in workflow
    assert "docs/data/leaderboard-status.json" in workflow
    assert "git add benchmarks docs/assets/benchmark-summary.svg docs/benchmark-dashboard.html docs/data/leaderboard-status.json" in workflow
    assert "actions/upload-artifact@v7" in workflow


def test_production_streaming_load_workflow_runs_checkpointed_large_n_profiles():
    workflow_path = Path(".github/workflows/production-streaming-load.yml")
    workflow = workflow_path.read_text(encoding="utf-8")

    assert workflow_path.exists()
    assert "workflow_dispatch" in workflow
    assert "contents: write" in workflow
    assert "actions: read" in workflow
    assert "production_streaming_load_benchmark.py" in workflow
    assert "--checkpoint-path" in workflow
    assert "runner_storage_root" in workflow
    assert "RUNNER_STORAGE_ROOT" in workflow
    assert "runner_storage_root = Path" in workflow
    assert "production-streaming-load-state" in workflow
    assert "production-streaming-load-results" in workflow
    assert "production-streaming-runner-storage-root.txt" in workflow
    assert "${{ inputs.runner_storage_root }}/**" in workflow
    assert "resume_run_id" in workflow
    assert "gh run download" in workflow
    assert "qdrant-service" in workflow
    assert "qdrant-sharded-service" in workflow
    assert "pgvector-service" in workflow
    assert "faiss-ivfpq-persisted" in workflow
    assert "WAVEMIND_QDRANT_URL" in workflow
    assert "WAVEMIND_QDRANT_URLS" in workflow
    assert "WAVEMIND_PGVECTOR_DSN" in workflow
    assert "WAVEMIND_FAISS_IVFPQ_PATH" in workflow
    assert "production_streaming_load_qdrant_10m_results.json" in workflow
    assert "production_streaming_load_qdrant_sharded_10m_results.json" in workflow
    assert "production_streaming_load_qdrant_sharded_100m_results.json" in workflow
    assert "production_streaming_load_pgvector_10m_results.json" in workflow
    assert "production_streaming_load_ivfpq_50m_results.json" in workflow
    assert "benchmarks/production_evidence_gate.py" in workflow
    assert "if: ${{ inputs.commit_results }}" in workflow
    assert "benchmarks/render_leaderboard_status.py" in workflow
    assert "docs/data/leaderboard-status.json" in workflow
    assert "git add benchmarks docs/assets/benchmark-summary.svg docs/benchmark-dashboard.html docs/data/leaderboard-status.json" in workflow
    assert "actions/upload-artifact@v7" in workflow


def test_full_check_local_http_cluster_smoke_uses_ci_p99_ceiling():
    workflow = Path(".github/workflows/full-check.yml").read_text(encoding="utf-8")

    assert "local-http-cluster-smoke:" in workflow
    assert "benchmarks/local_http_cluster_smoke.py" in workflow
    assert "--read-fanout 1" in workflow
    assert "--p99-slo-ms 2000" in workflow
    assert "--fail-on-slo" in workflow


def test_external_http_active_active_workflow_runs_real_region_profile():
    workflow = Path(".github/workflows/external-http-active-active.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch" in workflow
    assert "contents: write" in workflow
    assert "WAVEMIND_ACTIVE_ACTIVE_REGIONS" in workflow
    assert "WAVEMIND_ACTIVE_ACTIVE_REGIONS_MANIFEST_JSON" in workflow
    assert "regions_manifest_json" in workflow
    assert "secrets.WAVEMIND_API_KEY" in workflow
    assert r"[\n,;]+" in workflow
    assert "benchmarks/local_http_active_active_smoke.py" in workflow
    assert "--regions-file" in workflow
    assert "--region" in workflow
    assert "--deployment-id" in workflow
    assert "--environment" in workflow
    assert "--source" in workflow
    assert "benchmarks/external_http_active_active_results.json" in workflow
    assert "--fail-on-slo" in workflow
    assert "external active-active benchmark requires at least three regions or regions_manifest_json" in workflow
    assert "benchmarks/benchmark_registry.py" in workflow
    assert "benchmarks/render_benchmark_report.py" in workflow
    assert "benchmarks/render_benchmark_leaderboard.py" in workflow
    assert "benchmarks/render_benchmark_charts.py" in workflow
    assert "benchmarks/render_benchmark_dashboard.py" in workflow
    assert "benchmarks/render_leaderboard_status.py" in workflow
    assert "benchmarks/validate_benchmark_artifacts.py" in workflow
    assert "benchmarks/production_readiness_gate.py" in workflow
    assert "benchmarks/production_evidence_gate.py" in workflow
    assert "if: ${{ inputs.commit_results }}" in workflow
    assert "docs/data/leaderboard-status.json" in workflow
    assert "git add benchmarks docs/assets/benchmark-summary.svg docs/benchmark-dashboard.html docs/data/leaderboard-status.json" in workflow
    assert "actions/upload-artifact@v7" in workflow


def test_serverless_observed_telemetry_workflow_runs_remote_node_profile():
    workflow = Path(".github/workflows/serverless-observed-telemetry.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch" in workflow
    assert "contents: write" in workflow
    assert "WAVEMIND_SERVERLESS_NODES" in workflow
    assert "secrets.WAVEMIND_API_KEY" in workflow
    assert "benchmarks/serverless_observed_telemetry_benchmark.py" in workflow
    assert "deploy/serverless/observed-telemetry.remote.json" in workflow
    assert r'[\n,;]+' in workflow
    assert "serverless observed telemetry requires at least one node URL" in workflow
    assert "--node" in workflow
    assert "--api-key" in workflow
    assert "--seed-mode" in workflow
    assert "--external-cold-start-ms" in workflow
    assert "--estimated-scale-out-seconds" in workflow
    assert "--source" in workflow
    assert "github-actions-serverless-observed-telemetry" in workflow
    assert "benchmarks/scale_readiness_benchmark.py" in workflow
    assert "benchmarks/benchmark_registry.py" in workflow
    assert "benchmarks/render_benchmark_report.py" in workflow
    assert "benchmarks/render_benchmark_leaderboard.py" in workflow
    assert "benchmarks/render_benchmark_charts.py" in workflow
    assert "benchmarks/render_benchmark_dashboard.py" in workflow
    assert "benchmarks/render_leaderboard_status.py" in workflow
    assert "benchmarks/validate_benchmark_artifacts.py" in workflow
    assert "benchmarks/production_readiness_gate.py" in workflow
    assert "benchmarks/production_evidence_gate.py" in workflow
    assert "if: ${{ inputs.commit_results }}" in workflow
    assert "docs/data/leaderboard-status.json" in workflow
    assert "git add benchmarks docs/assets/benchmark-summary.svg docs/benchmark-dashboard.html docs/data/leaderboard-status.json deploy/serverless/observed-telemetry.remote.json" in workflow
    assert "actions/upload-artifact@v7" in workflow


def test_full_check_blocks_stale_public_benchmark_artifacts():
    workflow = Path(".github/workflows/full-check.yml").read_text(encoding="utf-8")

    assert "benchmark-artifact-gate:" in workflow
    assert "local-http-cluster-smoke:" in workflow
    assert "local-http-active-active-smoke:" in workflow
    assert "qdrant-sharded-streaming-smoke:" in workflow
    assert "benchmarks/local_http_cluster_smoke.py" in workflow
    assert "benchmarks/local_http_active_active_smoke.py" in workflow
    assert "--read-fanout 1" in workflow
    assert "benchmarks/local_http_cluster_smoke_ci_results.json" in workflow
    assert "benchmarks/local_http_active_active_smoke_ci_results.json" in workflow
    assert "local-http-active-active-smoke-results" in workflow
    assert "qdrant/qdrant:v1.15.1" in workflow
    assert "WAVEMIND_QDRANT_URLS: http://127.0.0.1:6333,http://127.0.0.1:6334" in workflow
    assert "--engines qdrant-sharded-service" in workflow
    assert "benchmarks/production_streaming_load_qdrant_sharded_ci_results.json" in workflow
    assert "qdrant-sharded-streaming-smoke-results" in workflow
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
