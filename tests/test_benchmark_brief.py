from pathlib import Path


def test_public_benchmark_brief_links_checked_in_artifacts_and_commands():
    brief = Path("docs/BENCHMARK_BRIEF.md").read_text(encoding="utf-8")
    artifacts = [
        "benchmarks/agent_coherence_results.json",
        "benchmarks/dynamic_memory_results.json",
        "benchmarks/locomo_sentence_evidence_results.json",
        "benchmarks/longmemeval_evidence_results.json",
        "benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json",
        "benchmarks/open_retrieval_scifact_results.json",
        "benchmarks/nomiracl_russian_results.json",
        "benchmarks/production_index_profile_results.json",
        "benchmarks/production_pgvector_tuning_results.json",
        "benchmarks/production_streaming_load_pgvector_smoke_results.json",
        "benchmarks/production_streaming_load_pgvector_10m_plan.json",
        "benchmarks/production_streaming_load_50m_plan.json",
    ]
    commands = [
        "python benchmarks/agent_coherence_benchmark.py",
        "python benchmarks/dynamic_memory_benchmark.py",
        "python benchmarks/locomo_memory_benchmark.py",
        "python benchmarks/longmemeval_memory_benchmark.py",
        "python benchmarks/longmemeval_answer_benchmark.py",
        "python benchmarks/open_retrieval_benchmark.py",
        "python benchmarks/nomiracl_russian_benchmark.py",
        "docker compose -f examples/production-index-profile/docker-compose.yml run --rm benchmark",
        "python benchmarks/ann_index_curve_benchmark.py --sizes 10000 50000",
        "python benchmarks/production_streaming_load_benchmark.py --plan-only --sizes 10000000",
    ]

    for artifact in artifacts:
        assert artifact in brief
        assert Path(artifact).exists()
    for command in commands:
        assert command in brief

    assert "does not claim WaveMind is a faster static vector database" in brief
    assert "official LoCoMo, LongMemEval, MTEB, MIRACL, RAGBench, or VectorDBBench" in brief
    assert "Hacker News" in brief
    assert "Reddit" in brief
    assert "X Thread" in brief
    assert "$1.39` per 1M queries" in brief
    assert "$4.17` per 1M queries" in brief
    assert "iterative HNSW reaches `0.970`" in brief
    assert "33/33" in brief
    assert "pgvector 10M service profile is complete" in brief
