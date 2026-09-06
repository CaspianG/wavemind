from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "benchmarks" / "scientific_v31_longmem_streaming_probe_results.json"


def test_v31_streaming_probe_passes_full_scratch_without_outcome_access():
    payload = json.loads(RESULT.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "passed_synthetic_full_scratch_resource_probe"
    assert payload["query_kind"] == "synthetic_non_held_out"
    assert payload["candidate_source_sha"] == (
        "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    )
    assert payload["streaming_harness_commit"] == (
        "404c6b127e580d8531176d9e79cd1782bbacc79b"
    )
    assert payload["scratch"]["event_count"] == 28768
    assert payload["scratch"]["event_json_bytes"] == 97046543
    boundary = payload["scientific_boundary"]
    assert boundary["held_out_question_text_used"] is False
    assert boundary["model_calls_made"] == 0
    assert boundary["answers_generated"] == 0
    assert boundary["scores_opened"] is False
    assert boundary["gate_evaluated"] is False


def test_v31_streaming_probe_meets_resource_and_integrity_rule():
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    measurements = payload["measurements"]

    assert measurements["open_seconds"] < 30.0
    assert measurements["recall_seconds"] < 30.0
    assert measurements["chain_validation_seconds"] < 30.0
    assert measurements["selected_count"] > 0
    assert measurements["estimated_tokens"] <= 8192
    assert measurements["chain_errors"] == []
    assert measurements["process_memory_after_validation"]["private_gib"] < 2.0
