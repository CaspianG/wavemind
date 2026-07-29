from pathlib import Path


def test_public_benchmark_brief_links_checked_in_artifacts_and_commands():
    brief = Path("docs/BENCHMARK_BRIEF.md").read_text(encoding="utf-8")
    artifacts = [
        "benchmarks/agent_coherence_results.json",
        "benchmarks/agent_memory_advantage_results.json",
        "benchmarks/agent_memory_advantage_admission_results.json",
        "benchmarks/AGENT_MEMORY_ADVANTAGE_ADMISSION.md",
        "benchmarks/experienced_work_agent_results.json",
        "benchmarks/EXPERIENCED_WORK_AGENT.md",
        "benchmarks/experience_quality_admission_results.json",
        "benchmarks/EXPERIENCE_QUALITY_ADMISSION.md",
        "benchmarks/developer_experience_admission_results.json",
        "benchmarks/DEVELOPER_EXPERIENCE_ADMISSION.md",
        "benchmarks/memory_safety_admission_results.json",
        "benchmarks/MEMORY_SAFETY_ADMISSION.md",
        "benchmarks/agent_impact_results.json",
        "benchmarks/AGENT_IMPACT.md",
        "benchmarks/structured_memory_results.json",
        "benchmarks/STRUCTURED_MEMORY.md",
        "benchmarks/memory_os_intelligence_results.json",
        "benchmarks/MEMORY_OS_INTELLIGENCE.md",
        "benchmarks/cluster_autoscale_results.json",
        "benchmarks/CLUSTER_AUTOSCALE.md",
        "benchmarks/dynamic_memory_results.json",
        "benchmarks/locomo_sentence_evidence_results.json",
        "benchmarks/locomo_memory_os_results.json",
        "benchmarks/longmemeval_evidence_results.json",
        "benchmarks/longmemeval_memory_os_results.json",
        "benchmarks/longmemeval_v2_small_memory_os_results.json",
        "benchmarks/longmemeval_v2_small_per_query.jsonl",
        "benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json",
        "benchmarks/open_retrieval_scifact_results.json",
        "benchmarks/nomiracl_russian_results.json",
        "benchmarks/production_index_profile_results.json",
        "benchmarks/production_pgvector_tuning_results.json",
        "benchmarks/production_streaming_load_qdrant_smoke_results.json",
        "benchmarks/production_streaming_load_qdrant_1m_results.json",
        "benchmarks/production_streaming_load_qdrant_1m_tuned_results.json",
        "benchmarks/production_streaming_load_qdrant_sharded_smoke_results.json",
        "benchmarks/production_streaming_load_qdrant_10m_plan.json",
        "benchmarks/production_streaming_load_qdrant_sharded_10m_plan.json",
        "benchmarks/production_streaming_load_qdrant_sharded_100m_plan.json",
        "benchmarks/production_streaming_load_pgvector_smoke_results.json",
        "benchmarks/production_streaming_load_pgvector_10m_plan.json",
        "benchmarks/production_streaming_load_pgvector_10m_results.json",
        "benchmarks/production_streaming_load_50m_plan.json",
        "benchmarks/production_admission_results.json",
    ]
    commands = [
        "python benchmarks/agent_coherence_benchmark.py",
        "python benchmarks/agent_memory_advantage_benchmark.py",
        "python benchmarks/experienced_work_agent_benchmark.py",
        "wavemind experience-quality-admission",
        "python benchmarks/developer_experience_admission.py --fail-on-blocked",
        "wavemind memory-safety-admission",
        "python benchmarks/agent_impact_leaderboard.py",
        "python benchmarks/structured_memory_report.py",
        "python benchmarks/memory_os_intelligence_report.py",
        "python benchmarks/cluster_autoscale_report.py",
        "python benchmarks/dynamic_memory_benchmark.py",
        "python benchmarks/locomo_memory_benchmark.py",
        "python benchmarks/longmemeval_memory_benchmark.py",
        "python benchmarks/longmemeval_answer_benchmark.py",
        "python benchmarks/open_retrieval_benchmark.py",
        "python benchmarks/nomiracl_russian_benchmark.py",
        "docker compose -f examples/production-index-profile/docker-compose.yml run --rm benchmark",
        "docker compose -f examples/qdrant-sharded-streaming/docker-compose.yml up -d",
        "python benchmarks/ann_index_curve_benchmark.py --sizes 10000 50000",
        "python benchmarks/production_streaming_load_benchmark.py --plan-only --runner-storage-root state/production-runs --disk-free-gb 0 --sizes 10000000",
        "wavemind production-admission --target-memories 100000000",
    ]

    for artifact in artifacts:
        assert artifact in brief
        assert Path(artifact).exists()
    for command in commands:
        assert command in brief

    assert "does not claim WaveMind is a faster static vector database" in brief
    assert "Agent impact leaderboard" in brief
    assert "8/8` primary wins" in brief
    assert "Experienced Work Agent" in brief
    assert "Developer experience admission" in brief
    assert "first cited Experience Packet" in brief
    assert "Memory safety admission" in brief
    assert "375 attacks and 25 benign controls" in brief
    assert "Structured memory report" in brief
    assert "7` modalities" in brief
    assert "Memory OS intelligence report" in brief
    assert "39/39` gate checks" in brief
    assert "admitted six-hour/two-worker production topology" in brief
    assert "Cluster autoscale report" in brief
    assert "53/53` gate checks" in brief
    assert "deterministic 100M capacity envelope" in brief
    assert "independently verified LoCoMo, LongMemEval, MTEB, MIRACL, RAGBench" in brief
    assert "Hacker News" in brief
    assert "Reddit" in brief
    assert "X Thread" in brief
    assert "$1.39` per 1M queries" in brief
    assert "$4.17` per 1M queries" in brief
    assert "iterative HNSW reaches `0.970`" in brief
    assert "39/39" in brief
    assert "Qdrant 1M streaming" in brief
    assert "two-service sharded Qdrant smoke" in brief
    assert "four-service 10M sharded Qdrant" in brief
    assert "completed pgvector 10M candidate-index SLO" in brief
