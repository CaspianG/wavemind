from __future__ import annotations

import json
from pathlib import Path

from wavemind.evidence import canonical_json_bytes, sha256_bytes


ROOT = Path(__file__).resolve().parents[1]


def test_v24_protocol_freezes_fresh_development_and_untouched_final_reserves():
    protocol = json.loads(
        (ROOT / "benchmarks" / "scientific_memory_protocol_v24.json").read_text(
            encoding="utf-8"
        )
    )
    digest = protocol.pop("protocol_digest")
    assert sha256_bytes(canonical_json_bytes(protocol)) == digest
    assert protocol["candidate"]["frozen_before_first_v24_outcome"] is True
    assert protocol["frozen_parameters"]["memops_question_selection"] == (
        "causal-application-v2"
    )
    families = protocol["frozen_development_gate"]["families"]
    assert len(families["memoryagentbench_summarization"]["unit_ids"]) == 10
    assert families["memops_longitudinal_operation"]["subjects"] == [
        "A04",
        "B30",
        "C02",
        "D01",
        "E07",
    ]
    assert len(protocol["frozen_admission"]["memoryagentbench_fresh_final_unit_ids"]) == 10
    assert protocol["frozen_admission"]["memops_final_subjects"] == [
        "B23",
        "C11",
        "D20",
        "E08",
        "E11",
    ]
    assert protocol["immutable_v20_development_evidence"]["failed_run_may_be_rerun"] is False
    assert [item["diagnostic_gate_pass"] for item in protocol["opened_v21_v23_diagnostics"]] == [
        False,
        False,
        True,
    ]


def test_v24_memops_wrapper_has_no_blind_sequence_coverage():
    source = (ROOT / "benchmarks" / "scientific_memops_v24_development.py").read_text(
        encoding="utf-8"
    )
    assert 'runner.QUESTION_SELECTION = "causal-application-v2"' in source
    assert "runner.TRAJECTORY_SEQUENCE_COVERAGE = False" in source
    assert "runner.UPDATE_SEQUENCE_COVERAGE = False" in source
