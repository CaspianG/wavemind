from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import file_sha256


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v7.json"


def test_v7_protocol_is_frozen_and_firewalled_from_opened_validation():
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    expected_digest = payload.pop("protocol_digest")
    actual_digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    assert actual_digest == expected_digest
    assert payload["status"] == "preregistered"
    assert payload["immutable_negative_evidence"]["v6_status"] == (
        "failed_admission_v6"
    )
    assert payload["immutable_negative_evidence"]["v6_outcome_sha256"] == (
        file_sha256(ROOT / "benchmarks" / "scientific_v6_admission_outcome.json")
    )
    assert payload["candidate"]["slicing"] == {
        "maximum_characters": 1024,
        "overlap_characters": 256,
        "stride_characters": 768,
        "boundary_policy": (
            "normalize whitespace, prefer the last whitespace in the final 128 "
            "characters of a slice when present, and retain deterministic source "
            "offsets"
        ),
        "minimum_non_whitespace_characters": 1,
        "gold_or_answer_fields_permitted": False,
    }
    assert payload["frozen_parameters"]["source_recency_weight"] == 0.0
    gate = payload["frozen_development_gate"]
    assert len(gate["memoryagentbench_unit_ids"]) == 11
    assert len(gate["memops_subjects"]) == 5
    assert gate["required_reproducible_runs"] == 3
    assert gate["paired_cluster_bootstrap_ci_lower_strictly_greater_than"] == 0.0
    admission = payload["frozen_admission"]
    assert len(admission["memoryagentbench_final_unit_ids"]) == 5
    assert len(admission["memops_final_subjects"]) == 5
    assert admission["longmemeval_v2_question_count"] == 451
    assert admission["maximum_longmemeval_v2_logical_full_runs"] == 1

