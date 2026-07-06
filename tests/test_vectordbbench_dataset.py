import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


def test_exact_neighbor_lists_are_ordered_by_cosine_score():
    from benchmarks.vectordbbench_dataset import exact_neighbor_lists

    vectors = np.asarray(
        [
            [1.0, 0.0],
            [0.9, 0.1],
            [0.0, 1.0],
        ],
        dtype=np.float32,
    )
    queries = np.asarray([[1.0, 0.0]], dtype=np.float32)

    assert exact_neighbor_lists(vectors, queries, top_k=2) == [[1, 2]]


def test_vectordbbench_manifest_can_report_missing_parquet_engine(tmp_path, monkeypatch):
    from benchmarks import vectordbbench_dataset as module

    monkeypatch.setattr(module, "_module_available", lambda name: name != "pyarrow")

    manifest = module.generate_dataset(
        output_dir=tmp_path / "dataset",
        manifest_path=tmp_path / "manifest.json",
        vectors=16,
        queries=4,
        dim=8,
        top_k=3,
        require_parquet=False,
    )

    assert manifest["benchmark"] == "VectorDBBench custom dataset"
    assert manifest["status"] == "skipped"
    assert "pyarrow" in manifest["reason"]
    assert manifest["dataset"]["vectors"] == 16
    assert (tmp_path / "manifest.json").exists()


def test_vectordbbench_dataset_writes_parquet_when_pyarrow_is_available(tmp_path):
    pytest.importorskip("pyarrow")
    pytest.importorskip("pandas")

    from benchmarks.vectordbbench_dataset import generate_dataset

    manifest = generate_dataset(
        output_dir=tmp_path / "dataset",
        manifest_path=tmp_path / "manifest.json",
        vectors=32,
        queries=5,
        dim=8,
        top_k=4,
    )

    assert manifest["status"] == "ready"
    for key in ("train", "test", "neighbors", "scalar_labels"):
        assert Path(manifest["files"][key]).exists()


def test_vectordbbench_dataset_cli_writes_manifest_without_parquet(tmp_path):
    output = tmp_path / "manifest.json"
    project_root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [
            sys.executable,
            "benchmarks/vectordbbench_dataset.py",
            "--vectors",
            "16",
            "--queries",
            "4",
            "--dim",
            "8",
            "--top-k",
            "3",
            "--output-dir",
            str(tmp_path / "dataset"),
            "--manifest",
            str(output),
            "--allow-missing-parquet",
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert completed.returncode in {0, 2}
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["dataset"]["queries"] == 4
    assert payload["status"] in {"ready", "skipped"}
