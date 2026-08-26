from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import canonical_json_bytes, sha256_bytes


ROOT = Path(__file__).resolve().parents[1]


def test_v20_protocol_freezes_fresh_development_and_final_reserves():
    protocol = json.loads(
        (ROOT / "benchmarks" / "scientific_memory_protocol_v20.json").read_text(
            encoding="utf-8"
        )
    )
    digest = protocol.pop("protocol_digest")
    assert sha256_bytes(canonical_json_bytes(protocol)) == digest
    assert protocol["candidate"]["frozen_before_first_v20_outcome"] is True
    assert protocol["frozen_parameters"]["memops_question_selection"] == (
        "memory-dependence-v5"
    )
    assert protocol["frozen_parameters"][
        "memops_operation_trace_operation_only_sequence_coverage"
    ] is True
    families = protocol["frozen_development_gate"]["families"]
    assert len(families["memoryagentbench_summarization"]["unit_ids"]) == 10
    assert families["memops_longitudinal_operation"]["subjects"] == [
        "C23",
        "C28",
        "E03",
        "F01",
        "F13",
    ]
    assert len(protocol["frozen_admission"]["memoryagentbench_fresh_final_unit_ids"]) == 10
    assert protocol["frozen_admission"]["memops_final_subjects"] == [
        "B23",
        "C11",
        "D20",
        "E08",
        "E11",
    ]
    assert protocol["immutable_v19_admission_evidence"][
        "opened_v19_final_cases_may_be_reused"
    ] is False
    assert protocol["opened_v20_diagnostic"]["official_gate_decision"] is False
