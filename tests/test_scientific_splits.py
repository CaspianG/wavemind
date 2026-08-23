from __future__ import annotations

import copy
from pathlib import Path

import pytest

from wavemind.scientific_splits import (
    build_memoryagentbench_split_manifest,
    validate_memoryagentbench_split_manifest,
)


pyarrow = pytest.importorskip("pyarrow")
parquet = pytest.importorskip("pyarrow.parquet")
ROOT = Path(__file__).resolve().parents[1]


def _write_family(path: Path, rows: int) -> None:
    table = pyarrow.table(
        {
            "context": [f"context-{index}" for index in range(rows)],
            "questions": [[f"question-{index}"] for index in range(rows)],
            "metadata": [
                {"question_ids": [f"question-id-{index}"]} for index in range(rows)
            ],
        }
    )
    parquet.write_table(table, path)


def test_memoryagentbench_split_is_deterministic_and_context_isolated(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write_family(data / "Accurate_Retrieval-00000-of-00001.parquet", 10)
    _write_family(data / "Conflict_Resolution-00000-of-00001.parquet", 8)

    first = build_memoryagentbench_split_manifest(
        project_root=ROOT,
        dataset_root=tmp_path,
    )
    second = build_memoryagentbench_split_manifest(
        project_root=ROOT,
        dataset_root=tmp_path,
    )

    assert first["units"] == second["units"]
    assert sum(first["counts"]["Accurate_Retrieval"].values()) == 10
    assert all(
        count > 0
        for family_counts in first["counts"].values()
        for count in family_counts.values()
    )
    assert first["context_split_breaches"] == []
    assert validate_memoryagentbench_split_manifest(
        first,
        project_root=ROOT,
        expected_source_sha=first["source_sha"],
    ) == []


def test_memoryagentbench_split_validator_detects_cross_split_context(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write_family(data / "Accurate_Retrieval-00000-of-00001.parquet", 6)
    payload = build_memoryagentbench_split_manifest(
        project_root=ROOT,
        dataset_root=tmp_path,
    )
    changed = copy.deepcopy(payload)
    changed["units"][1]["context_sha256"] = changed["units"][0]["context_sha256"]
    changed["units"][1]["split"] = (
        "final" if changed["units"][0]["split"] != "final" else "development"
    )

    errors = validate_memoryagentbench_split_manifest(
        changed,
        project_root=ROOT,
        expected_source_sha=payload["source_sha"],
    )

    assert "artifact payload digest mismatch" in errors
    assert "MemoryAgentBench context breach summary mismatch" in errors
    assert "MemoryAgentBench context crosses splits" in errors
