from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import file_sha256


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v10.json"


def test_v10_protocol_freezes_two_disjoint_memops_development_families():
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
    assert negative["v9_status"] == "failed_development_gate_v9"
    assert negative["v9_outcome_sha256"] == file_sha256(
        ROOT / "benchmarks" / "scientific_v9_development_outcome.json"
    )
    gate = payload["frozen_development_gate"]
    adjacent = gate["families"]["memops_adjacent_operation"]["subjects"]
    longitudinal = gate["families"]["memops_longitudinal_operation"]["subjects"]
    assert len(adjacent) == len(longitudinal) == 5
    assert set(adjacent).isdisjoint(longitudinal)
    assert gate["required_reproducible_runs"] == 3
    assert gate["required_independent_families"] == 2
    assert gate["minimum_independent_subject_clusters_per_family"] == 5
    assert (
        gate["paired_subject_cluster_bootstrap_ci_lower_strictly_greater_than"]
        == 0.0
    )
