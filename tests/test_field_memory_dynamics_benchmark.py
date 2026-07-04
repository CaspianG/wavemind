from benchmarks import field_memory_dynamics_benchmark as benchmark


def test_field_memory_benchmark_reports_dynamic_metrics(tmp_path):
    result = benchmark.run_benchmark(tmp_path / "field-benchmark")

    assert result["scenario"] == "field_memory_dynamics"
    assert result["wave_graph"]["precision@1"] > result["wave_static"]["precision@1"]
    assert result["wave_graph"]["stale_suppression"] > result["wave_static"]["stale_suppression"]
    assert result["wave_graph"]["concept_formation"] == 1.0
    assert result["wave_graph"]["concept_consolidation"] == 1.0
    assert result["wave_static"]["concept_consolidation"] == 0.0
    assert result["wave_graph"]["avg_latency_ms"] >= 0.0


def test_field_memory_benchmark_cli_writes_json(tmp_path):
    output_path = tmp_path / "results.json"

    exit_code = benchmark.main(["--output", str(output_path), "--workdir", str(tmp_path / "run")])

    assert exit_code == 0
    assert output_path.exists()
    assert "field_memory_dynamics" in output_path.read_text(encoding="utf-8")
