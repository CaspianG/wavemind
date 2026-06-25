import json
import os
import subprocess
import sys
from pathlib import Path


def test_benchmark_matrix_contains_implemented_and_public_benchmarks():
    from benchmarks.benchmark_registry import build_benchmark_matrix

    payload = build_benchmark_matrix()
    entries = {entry["id"]: entry for entry in payload["benchmarks"]}

    assert payload["schema"] == "wavemind.benchmark_matrix.v1"
    assert entries["agent_memory_static_chroma"]["status"] == "implemented"
    assert entries["dynamic_memory_policy"]["status"] == "implemented"
    assert entries["field_memory_dynamics"]["status"] == "implemented"
    assert entries["long_memory_evidence_synthetic"]["status"] == "implemented"
    assert "Static vector" in entries["long_memory_evidence_synthetic"]["competitors"]
    assert entries["beir_style_open_retrieval"]["status"] == "implemented"
    assert "Qdrant" in entries["beir_style_open_retrieval"]["competitors"]
    assert entries["beir_style_open_retrieval"]["current"]["WaveMind"]["ndcg_at_k"] > 0
    assert entries["locomo_evidence_retrieval"]["status"] == "implemented"
    assert entries["locomo_evidence_retrieval"]["current"]["WaveMind"]["evidence_recall_at_k"] > 0
    assert entries["beir"]["status"] == "planned"
    assert entries["miracl_ru"]["category"] == "multilingual-retrieval"
    assert entries["vectordbbench"]["category"] == "vector-db"
    assert entries["longmemeval_evidence_retrieval"]["status"] == "implemented"
    assert entries["ann_index_curve"]["status"] == "implemented"
    assert entries["longmemeval_answer_generation"]["status"] == "runner-ready"
    assert entries["lmeb"]["source_url"].startswith("https://")


def test_benchmark_registry_cli_writes_machine_readable_json(tmp_path):
    output = tmp_path / "benchmark-matrix.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/benchmark_registry.py",
            "--output",
            str(output),
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["schema"] == "wavemind.benchmark_matrix.v1"
    assert any(entry["id"] == "ragbench" for entry in payload["benchmarks"])
    assert any(entry["status"] == "implemented" for entry in payload["benchmarks"])
    assert any(entry["status"] == "planned" for entry in payload["benchmarks"])
