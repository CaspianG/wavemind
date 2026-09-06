from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "benchmarks" / "scientific_v31_longmem_fallback_probe_results.json"


def test_v31_fallback_probe_passes_without_outcome_access():
    payload = json.loads(RESULT.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "passed_first_batch_digest_only_fallback_probe"
    assert payload["candidate_source_sha"] == "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    assert payload["fallback_harness_commit"] == "0dd456e1100a6beb5e60bdf94ddf5ffa071b2965"
    assert payload["input"]["question_count"] == 4
    assert payload["input"]["answer_or_gold_read_by_probe"] is False
    boundary = payload["scientific_boundary"]
    assert boundary["question_text_emitted"] is False
    assert boundary["answer_or_gold_read"] is False
    assert boundary["model_calls_made"] == 0
    assert boundary["scores_opened"] is False
    assert boundary["gate_evaluated"] is False


def test_v31_fallback_probe_completes_first_batch_inside_resource_gate():
    measurements = json.loads(RESULT.read_text(encoding="utf-8"))["measurements"]

    assert len(measurements["rows"]) == 4
    assert [row["shuffled_position"] for row in measurements["rows"]] == [0, 1, 2, 3]
    assert all(len(row["question_sha256"]) == 64 for row in measurements["rows"])
    assert all(len(row["context_sha256"]) == 64 for row in measurements["rows"])
    assert measurements["maximum_recall_seconds"] < 30.0
    assert measurements["chain_errors"] == []
    assert measurements["private_gib_after_probe"] < 3.0
