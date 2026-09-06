from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import file_sha256


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v8.json"


def test_v8_protocol_is_frozen_before_implementation_and_uses_fresh_gate_units():
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
    assert negative["v7_status"] == "failed_development_gate_v7"
    assert negative["v7_outcome_sha256"] == file_sha256(
        ROOT / "benchmarks" / "scientific_v7_development_outcome.json"
    )
    assert negative["v7_opened_development_units_may_be_reused_for_v8_gate"] is False
    assert payload["metric_governance"]["primary_metric"] == (
        "substring_exact_match"
    )
    gate = payload["frozen_development_gate"]
    assert len(gate["memoryagentbench_unit_ids"]) == 5
    assert all(
        unit_id.startswith("Accurate_Retrieval:")
        for unit_id in gate["memoryagentbench_unit_ids"]
    )
    assert len(gate["memops_subjects"]) == 5
    assert gate["required_reproducible_runs"] == 3
    assert gate["paired_cluster_bootstrap_ci_lower_strictly_greater_than"] == 0.0
    assert gate["stop_on_first_failed_required_run"] is True
    admission = payload["frozen_admission"]
    assert len(admission["memoryagentbench_final_unit_ids"]) == 5
    assert len(admission["memops_final_subjects"]) == 5
    assert admission["longmemeval_v2_question_count"] == 451
    assert admission["maximum_longmemeval_v2_logical_full_runs"] == 1
