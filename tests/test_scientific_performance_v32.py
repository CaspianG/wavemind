from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "benchmarks" / "scientific_performance_v32.py"
DEVELOPMENT = (
    ROOT / "benchmarks" / "scientific_performance_v32_development_results.json"
)
VALIDATION = (
    ROOT / "benchmarks" / "scientific_performance_v32_validation_results.json"
)


def _load_runner():
    name = "test_scientific_performance_v32_runner"
    spec = importlib.util.spec_from_file_location(name, RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_v32_runner_generators_follow_frozen_contract():
    runner = _load_runner()
    protocol = runner._load_protocol()
    for stage in ("development", "validation"):
        config = protocol["workloads"][stage]
        definitions = runner._definitions(config)
        queries = runner._queries(config)
        assert len(definitions) == config["definition_count"]
        assert len(queries) == config["query_count"]
        assert queries[0].startswith(
            f"Find account {config['query_start'] % config['account_modulus']} "
        )


def test_v32_validation_fails_closed_without_development(monkeypatch, tmp_path: Path):
    runner = _load_runner()
    monkeypatch.setitem(
        runner.OUTPUTS,
        "development",
        tmp_path / "missing-development.json",
    )
    with pytest.raises(RuntimeError, match="requires completed development"):
        runner._validate_stage_order("validation")


def test_v32_validation_rejects_failed_development(monkeypatch, tmp_path: Path):
    runner = _load_runner()
    path = tmp_path / "failed-development.json"
    path.write_text(json.dumps({"status": "failed_development_v32"}), encoding="utf-8")
    monkeypatch.setitem(runner.OUTPUTS, "development", path)
    with pytest.raises(RuntimeError, match="invalid v32 development integrity"):
        runner._validate_stage_order("validation")


def test_v32_development_outcome_passes_every_frozen_gate():
    payload = json.loads(DEVELOPMENT.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["stage"] == "development"
    assert payload["status"] == "passed_development_v32"
    assert payload["candidate_source_sha"] == (
        "d33163840ee2871f66cac3c585853aa031eb79ab"
    )
    assert payload["held_out_benchmark_rows_used"] is False
    assert payload["gate_pass"] is True
    assert all(payload["gate_checks"].values())
    assert len(payload["repeat_summaries"]) == 3
    assert len(payload["raw_rows"]) == 180
    assert all(row["exact_equal"] for row in payload["raw_rows"])
    assert all(
        row["reference_selection_sha256"] == row["indexed_selection_sha256"]
        for row in payload["raw_rows"]
    )
    assert all(
        row["indexed_p95_seconds"] <= 1.0
        and row["p95_speedup"] >= 5.0
        and row["exact_selection_equality"] is True
        for row in payload["repeat_summaries"]
    )
    assert payload["build"]["seconds"] <= 5.0
    assert payload["build"]["index_bytes_per_definition"] <= 2048
    for section in ("protocol", "runner"):
        record = payload[section]
        path = ROOT / record["path"]
        assert path.stat().st_size == record["bytes"]
        assert file_sha256(path) == record["sha256"]
    for record in payload["candidate_sources"]:
        path = ROOT / record["path"]
        assert path.stat().st_size == record["bytes"]
        assert file_sha256(path) == record["sha256"]


def test_v32_validation_outcome_passes_every_frozen_gate():
    payload = json.loads(VALIDATION.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["stage"] == "validation"
    assert payload["status"] == "passed_validation_v32"
    assert payload["candidate_source_sha"] == (
        "d33163840ee2871f66cac3c585853aa031eb79ab"
    )
    assert payload["held_out_benchmark_rows_used"] is False
    assert payload["gate_pass"] is True
    assert all(payload["gate_checks"].values())
    assert len(payload["repeat_summaries"]) == 3
    assert len(payload["raw_rows"]) == 240
    assert all(row["exact_equal"] for row in payload["raw_rows"])
    assert all(
        row["reference_selection_sha256"] == row["indexed_selection_sha256"]
        for row in payload["raw_rows"]
    )
    assert all(
        row["indexed_p95_seconds"] <= 1.0
        and row["p95_speedup"] >= 5.0
        and row["exact_selection_equality"] is True
        for row in payload["repeat_summaries"]
    )
    assert payload["build"]["seconds"] <= 5.0
    assert payload["build"]["index_bytes_per_definition"] <= 2048
    assert payload["build"]["retains_document_content_in_python"] is False
    assert payload["build"]["retains_per_document_token_sets_in_python"] is False
    for section in ("protocol", "runner"):
        record = payload[section]
        path = ROOT / record["path"]
        assert path.stat().st_size == record["bytes"]
        assert file_sha256(path) == record["sha256"]
    for record in payload["candidate_sources"]:
        path = ROOT / record["path"]
        assert path.stat().st_size == record["bytes"]
        assert file_sha256(path) == record["sha256"]
