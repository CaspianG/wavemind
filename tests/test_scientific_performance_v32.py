from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "benchmarks" / "scientific_performance_v32.py"


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
