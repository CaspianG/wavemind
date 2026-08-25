from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import file_sha256


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v9.json"


def test_v9_protocol_freezes_fresh_detective_qa_gate_and_transducer():
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
    negative = payload["immutable_negative_evidence"]
    assert negative["v8_status"] == "failed_development_gate_v8"
    assert negative["v8_outcome_sha256"] == file_sha256(
        ROOT / "benchmarks" / "scientific_v8_development_outcome.json"
    )
    transducer = payload["candidate"]["answer_transducer"]
    assert transducer["minimum_similarity"] == 0.5
    assert transducer["minimum_winner_margin"] == 0.1
    assert transducer["control_output_transformed"] is False
    metric = payload["metric_governance"]
    assert metric["memoryagentbench_gate_source"] == "detective_qa"
    assert metric["primary_metric"] == "exact_match"
    assert metric["generation_max_length"] == 2000
    gate = payload["frozen_development_gate"]
    assert len(gate["memoryagentbench_unit_ids"]) == 5
    assert all(
        unit_id.startswith("Long_Range_Understanding:")
        for unit_id in gate["memoryagentbench_unit_ids"]
    )
    assert len(gate["memops_subjects"]) == 5
    assert gate["required_reproducible_runs"] == 3
    assert gate["paired_cluster_bootstrap_ci_lower_strictly_greater_than"] == 0.0
