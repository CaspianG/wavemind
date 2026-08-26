from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "benchmarks" / "scientific_v31_longmem_processor_probe_results.json"


def test_v31_processor_probe_passes_without_outcome_access():
    payload = json.loads(RESULT.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "passed_official_processor_dependency_probe"
    assert payload["candidate_source_sha"] == (
        "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    )
    dependency = payload["dependency_receipt"]
    assert dependency["torch_version"] == "2.13.0+cpu"
    assert dependency["torchvision_version"] == "0.28.0+cpu"
    assert dependency["torch_cuda"] is None
    boundary = payload["scientific_boundary"]
    assert boundary["question_text_emitted"] is False
    assert boundary["answer_or_gold_read"] is False
    assert boundary["model_calls_made"] == 0
    assert boundary["scores_opened"] is False
    assert boundary["gate_evaluated"] is False


def test_v31_processor_probe_completes_exact_phases_inside_resource_limit():
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    measurements = payload["measurements"]

    assert measurements["runtime_open_seconds"] < 30.0
    assert measurements["optimized_recall_seconds"] < 30.0
    assert measurements["chain_validation_seconds"] < 30.0
    assert measurements["official_processor_seconds"] < 60.0
    assert measurements["context_items"] == 15
    assert measurements["context_chars"] == 32364
    assert measurements["context_estimated_tokens"] == 8095
    assert measurements["processor_original_tokens"] > 0
    assert measurements["processor_truncated_tokens"] <= 8192
    assert measurements["processor_truncated_items"] <= 15
    assert measurements["chain_errors"] == []
    assert measurements["private_gib_after_processor"] < 3.0
