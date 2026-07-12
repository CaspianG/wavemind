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
    assert "benchmarks/agent_impact_leaderboard.py" in workflow
    assert "benchmarks/agent_impact_results.json" in workflow
    assert "benchmarks/AGENT_IMPACT.md" in workflow
    assert "benchmarks/structured_memory_report.py" in workflow
    assert "benchmarks/structured_memory_results.json" in workflow
    assert "benchmarks/STRUCTURED_MEMORY.md" in workflow
    assert "benchmarks/memory_os_intelligence_report.py" in workflow
    assert "benchmarks/memory_os_intelligence_results.json" in workflow
    assert "benchmarks/MEMORY_OS_INTELLIGENCE.md" in workflow
    assert "benchmarks/cluster_autoscale_report.py" in workflow
    assert "benchmarks/cluster_autoscale_results.json" in workflow
    assert "benchmarks/CLUSTER_AUTOSCALE.md" in workflow
    assert "benchmarks/cost_efficiency_leaderboard.py" in workflow
    assert "benchmarks/cost_efficiency_results.json" in workflow
    assert "benchmarks/COST_EFFICIENCY.md" in workflow
    assert "benchmarks/production_evidence_gate.py" in workflow
    assert "--output benchmarks/production_evidence_results.json" in workflow
    assert "--markdown-output benchmarks/PRODUCTION_EVIDENCE.md" in workflow
    assert "python -m wavemind production-scale-plan" in workflow
    assert "--output benchmarks/production_scale_run_plan.json" in workflow
    assert workflow.index("production-scale-plan") < workflow.index("production-evidence-bundle")
    assert "python -m wavemind production-evidence-env" in workflow
    assert "--output benchmarks/production_evidence_env_contract.json" in workflow
    assert "--markdown-output benchmarks/PRODUCTION_EVIDENCE_ENV.md" in workflow
    assert "--env-output deploy/cluster/production-evidence.env.example" in workflow
    assert "python -m wavemind production-evidence-dispatch" in workflow
    assert "--output benchmarks/production_evidence_dispatch_results.json" in workflow
    assert "--markdown-output benchmarks/PRODUCTION_EVIDENCE_DISPATCH.md" in workflow
    assert "benchmarks/strict_evidence_readiness_report.py" in workflow
    assert "--output benchmarks/strict_evidence_readiness_results.json" in workflow
    assert "--markdown-output benchmarks/STRICT_EVIDENCE_READINESS.md" in workflow
    assert workflow.index("production-evidence-dispatch") < workflow.index(
        "production-evidence-bundle"
    )
    assert "python -m wavemind production-admission" in workflow
    assert "--output benchmarks/production_admission_results.json" in workflow
    assert "--markdown-output benchmarks/PRODUCTION_ADMISSION.md" in workflow
    assert workflow.index("scale-gap") < workflow.index("production-admission")
    assert "python -m wavemind cluster-admission" in workflow
    assert "--output benchmarks/cluster_admission_results.json" in workflow
    assert "--markdown-output benchmarks/CLUSTER_ADMISSION.md" in workflow
    assert "python -m wavemind active-active-admission" in workflow
    assert "--output benchmarks/active_active_admission_results.json" in workflow
    assert "--markdown-output benchmarks/ACTIVE_ACTIVE_ADMISSION.md" in workflow
    assert "python -m wavemind serverless-admission" in workflow
    assert "--output benchmarks/serverless_admission_results.json" in workflow
    assert "--markdown-output benchmarks/SERVERLESS_ADMISSION.md" in workflow
    assert "python -m wavemind multimodal-admission" in workflow
    assert "--output benchmarks/multimodal_admission_results.json" in workflow
    assert "--markdown-output benchmarks/MULTIMODAL_ADMISSION.md" in workflow
    assert "python -m wavemind \\\n            --db .tmp-memory-os-canary.sqlite3" in workflow
    assert "memory-os-canary" in workflow
    assert "--output benchmarks/memory_os_canary_results.json" in workflow
    assert "--markdown-output benchmarks/MEMORY_OS_CANARY.md" in workflow
    assert "--fail-on-action-required" in workflow
    assert "python -m wavemind memory-os-admission" in workflow
    assert "--output benchmarks/memory_os_admission_results.json" in workflow
    assert "--markdown-output benchmarks/MEMORY_OS_ADMISSION.md" in workflow
    assert "python -m wavemind memory-os-policy-bundle" in workflow
    assert "--output benchmarks/memory_os_policy_bundle_results.json" in workflow
    assert "--markdown-output benchmarks/MEMORY_OS_POLICY_BUNDLE.md" in workflow
    assert workflow.index("production-admission") < workflow.index("memory-os-canary")
    assert workflow.index("production-admission") < workflow.index("cluster-admission")
    assert workflow.index("cluster-admission") < workflow.index("active-active-admission")
    assert workflow.index("cluster-admission") < workflow.index("memory-os-canary")
    assert workflow.index("production-admission") < workflow.index(
        "active-active-admission"
    )
    assert workflow.index("active-active-admission") < workflow.index("memory-os-canary")
    assert workflow.index("active-active-admission") < workflow.index(
        "serverless-admission"
    )
    assert workflow.index("serverless-admission") < workflow.index("memory-os-canary")
    assert workflow.index("serverless-admission") < workflow.index("multimodal-admission")
    assert workflow.index("multimodal-admission") < workflow.index("memory-os-canary")
    assert workflow.index("memory-os-canary") < workflow.index("memory-os-admission")
    assert workflow.index("memory-os-admission") < workflow.index("memory-os-policy-bundle")
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
    assert "tests/test_agent_impact_leaderboard.py" in workflow
    assert "tests/test_structured_memory_report.py" in workflow
    assert "tests/test_memory_os_intelligence_report.py" in workflow
    assert "tests/test_memory_os_policy_bundle.py" in workflow
    assert "tests/test_cluster_autoscale_report.py" in workflow
    assert "tests/test_cost_efficiency_leaderboard.py" in workflow
    assert "tests/test_production_evidence_gate.py" in workflow
    assert "tests/test_production_evidence_env.py" in workflow
    assert "tests/test_production_evidence_dispatch.py" in workflow
    assert "tests/test_strict_evidence_readiness_report.py" in workflow
    assert "tests/test_http_cluster_load_benchmark.py" in workflow
    assert "qdrant-0:" in workflow
    assert "qdrant-1:" in workflow
    assert "qdrant/qdrant:v1.18.2" in workflow
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
    assert "benchmarks/production_evidence_env_contract.json" in workflow
    assert "benchmarks/PRODUCTION_EVIDENCE_ENV.md" in workflow
    assert "deploy/cluster/production-evidence.env.example" in workflow
    assert "benchmarks/production_evidence_dispatch_results.json" in workflow
    assert "benchmarks/PRODUCTION_EVIDENCE_DISPATCH.md" in workflow
    assert "benchmarks/strict_evidence_readiness_results.json" in workflow
    assert "benchmarks/STRICT_EVIDENCE_READINESS.md" in workflow
    assert "cp benchmarks/PRODUCTION_ADMISSION.md site/benchmarks/PRODUCTION_ADMISSION.md" in workflow
    assert "cp benchmarks/production_admission_results.json site/data/production_admission_results.json" in workflow
    assert "cp benchmarks/ACTIVE_ACTIVE_ADMISSION.md site/benchmarks/ACTIVE_ACTIVE_ADMISSION.md" in workflow
    assert "cp benchmarks/active_active_admission_results.json site/data/active_active_admission_results.json" in workflow
    assert "cp benchmarks/SERVERLESS_ADMISSION.md site/benchmarks/SERVERLESS_ADMISSION.md" in workflow
    assert "cp benchmarks/serverless_admission_results.json site/data/serverless_admission_results.json" in workflow
    assert "cp benchmarks/MULTIMODAL_ADMISSION.md site/benchmarks/MULTIMODAL_ADMISSION.md" in workflow
    assert "cp benchmarks/multimodal_admission_results.json site/data/multimodal_admission_results.json" in workflow
    assert "cp benchmarks/AGENT_IMPACT.md site/benchmarks/AGENT_IMPACT.md" in workflow
    assert "cp benchmarks/agent_impact_results.json site/data/agent_impact_results.json" in workflow
    assert "cp benchmarks/STRUCTURED_MEMORY.md site/benchmarks/STRUCTURED_MEMORY.md" in workflow
    assert "cp benchmarks/structured_memory_results.json site/data/structured_memory_results.json" in workflow
    assert "cp benchmarks/MEMORY_OS_INTELLIGENCE.md site/benchmarks/MEMORY_OS_INTELLIGENCE.md" in workflow
    assert "cp benchmarks/memory_os_intelligence_results.json site/data/memory_os_intelligence_results.json" in workflow
    assert "cp benchmarks/CLUSTER_AUTOSCALE.md site/benchmarks/CLUSTER_AUTOSCALE.md" in workflow
    assert "cp benchmarks/cluster_autoscale_results.json site/data/cluster_autoscale_results.json" in workflow
    assert "cp benchmarks/COST_EFFICIENCY.md site/benchmarks/COST_EFFICIENCY.md" in workflow
    assert "cp benchmarks/cost_efficiency_results.json site/data/cost_efficiency_results.json" in workflow
    assert "cp benchmarks/MEMORY_OS_CANARY.md site/benchmarks/MEMORY_OS_CANARY.md" in workflow
    assert "cp benchmarks/memory_os_canary_results.json site/data/memory_os_canary_results.json" in workflow
    assert "cp benchmarks/MEMORY_OS_ADMISSION.md site/benchmarks/MEMORY_OS_ADMISSION.md" in workflow
    assert "cp benchmarks/memory_os_admission_results.json site/data/memory_os_admission_results.json" in workflow
    assert "cp benchmarks/MEMORY_OS_POLICY_BUNDLE.md site/benchmarks/MEMORY_OS_POLICY_BUNDLE.md" in workflow
    assert "cp benchmarks/memory_os_policy_bundle_results.json site/data/memory_os_policy_bundle_results.json" in workflow


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
    assert "python -m wavemind production-evidence-dispatch" in workflow
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
    assert "pull-requests: write" in workflow
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
    assert "WAVEMIND_PGVECTOR_DSNS" in workflow
    assert "pgvector_dsns" in workflow
    assert "provision_pgvector_shards" in workflow
    assert "pgvector_shard_count" in workflow
    assert "pgvector_profile" in workflow
    assert "hnsw-fast" in workflow
    assert "hnsw-quality" in workflow
    assert "ivfflat-balanced" in workflow
    assert "ivfflat-quality" in workflow
    assert "hnsw-binary-quality" in workflow
    assert "Provision isolated pgvector services" in workflow
    assert '"pgvector/pgvector:pg16"' in workflow
    assert "--shm-size 1g" in workflow
    assert "WAVEMIND_PGVECTOR_INDEX_BUILD_WORKERS" in workflow
    assert "pgvector_managed_profile" in workflow
    assert 'env["WAVEMIND_PGVECTOR_INDEX_TYPE"] = str(tuning["index_type"])' in workflow
    assert 'tuning["hnsw_ef_construction"]' in workflow
    assert 'tuning["hnsw_ef_search"]' in workflow
    assert 'tuning["ivfflat_lists"]' in workflow
    assert 'tuning["ivfflat_probes"]' in workflow
    assert 'tuning["binary_candidates"]' in workflow
    assert 'env["WAVEMIND_PGVECTOR_UNLOGGED"] = "1"' in workflow
    assert "max_wal_size=4GB" in workflow
    assert "pg_isready --username postgres --dbname wavemind" in workflow
    assert "pgvector-managed-dsns.txt" in workflow
    assert "github-hosted-isolated-service-processes" in workflow
    assert "pgvector shard row counts do not prove an exact balanced layout" in workflow
    assert "managed pgvector evidence must use namespace routing" in workflow
    assert "build independent shard indexes in parallel" in workflow
    assert "rebuildable unlogged candidate index" in workflow
    assert "isolated-service topology attestation" in workflow
    assert "Capture pgvector service diagnostics" in workflow
    assert "WAVEMIND_FAISS_IVFPQ_PATH" in workflow
    assert 'WAVEMIND_FAISS_IVFPQ_NPROBE: "1024"' in workflow
    assert 'WAVEMIND_FAISS_IVFPQ_NPROBE_SWEEP: "64,128,256,512,1024"' in workflow
    assert 'WAVEMIND_FAISS_CHECKPOINT_INTERVAL_BATCHES: "5"' in workflow
    assert 'python -m pip install -e ".[dev,bench,indexes,postgres]"' in workflow
    assert "Validate production streaming result" in workflow
    assert "expected exactly one {expected_engine!r} row" in workflow
    assert "production benchmark skipped:" in workflow
    assert "production benchmark missed its retrieval SLO" in workflow
    assert "production_streaming_load_qdrant_10m_results.json" in workflow
    assert "production_streaming_load_qdrant_sharded_10m_results.json" in workflow
    assert "production_streaming_load_qdrant_sharded_100m_results.json" in workflow
    assert "production_streaming_load_pgvector_10m_results.json" in workflow
    assert "production_streaming_load_ivfpq_50m_results.json" in workflow
    assert "benchmarks/production_evidence_gate.py" in workflow
    assert "python -m wavemind production-evidence-dispatch" in workflow
    assert "if: ${{ inputs.commit_results }}" in workflow
    assert "Publish production streaming result PR" in workflow
    assert 'branch="benchmark/production-streaming-${GITHUB_RUN_ID}"' in workflow
    assert 'git push --set-upstream origin "$branch"' in workflow
    assert "gh pr create" in workflow
    assert "repository settings prevented github-actions from opening the PR" in workflow
    assert "benchmarks/render_leaderboard_status.py" in workflow
    assert "docs/data/leaderboard-status.json" in workflow
    assert "git add benchmarks docs/assets/benchmark-summary.svg docs/benchmark-dashboard.html docs/data/leaderboard-status.json" in workflow
    assert "actions/upload-artifact@v7" in workflow
    dispatch_inputs = workflow.split("    inputs:\n", 1)[1].split("\npermissions:", 1)[0]
    input_names = [
        line.strip()[:-1]
        for line in dispatch_inputs.splitlines()
        if line.startswith("      ")
        and not line.startswith("        ")
        and line.rstrip().endswith(":")
    ]
    assert len(input_names) <= 25


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
    assert "python -m wavemind production-evidence-dispatch" in workflow
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
    assert "python -m wavemind production-evidence-dispatch" in workflow
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
    assert "qdrant/qdrant:v1.18.2" in workflow
    assert "WAVEMIND_QDRANT_URLS: http://127.0.0.1:6333,http://127.0.0.1:6334" in workflow
    assert "--engines qdrant-sharded-service" in workflow
    assert "benchmarks/production_streaming_load_qdrant_sharded_ci_results.json" in workflow
    assert "qdrant-sharded-streaming-smoke-results" in workflow
    assert "Block stale or unsynchronized public benchmark artifacts" in workflow
    assert "benchmarks/validate_benchmark_artifacts.py" in workflow
    assert "--max-age-days 8" in workflow
    assert "benchmarks/benchmark_artifact_audit_ci.json" in workflow
    assert "benchmarks/production_readiness_gate.py" in workflow
    assert "wavemind production-evidence-dispatch" in workflow


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
