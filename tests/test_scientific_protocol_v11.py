from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v11.json"


def _canonical_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def test_v11_protocol_freezes_fresh_development_and_admission_evidence():
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    expected_digest = payload.pop("protocol_digest")
    assert _canonical_digest(payload) == expected_digest
    assert payload["status"] == "preregistered"

    negative = payload["immutable_negative_evidence"]
    negative_path = ROOT / negative["v10_outcome_path"]
    outcome = json.loads(negative_path.read_text(encoding="utf-8"))
    assert validate_artifact_integrity(outcome) == []
    assert file_sha256(negative_path) == negative["v10_outcome_file_sha256"]
    assert outcome["integrity"]["payload_sha256"] == negative[
        "v10_outcome_payload_sha256"
    ]
    assert negative["opened_v10_final_cases_may_inform_v11_tuning"] is False

    for diagnostic in payload["opened_development_diagnostics"].values():
        if not isinstance(diagnostic, dict) or "path" not in diagnostic:
            continue
        path = ROOT / diagnostic["path"]
        artifact = json.loads(path.read_text(encoding="utf-8"))
        assert validate_artifact_integrity(artifact) == []
        assert file_sha256(path) == diagnostic["file_sha256"]
        assert artifact["integrity"]["payload_sha256"] == diagnostic[
            "payload_sha256"
        ]

    mab_manifest = json.loads(
        (ROOT / "benchmarks" / "memoryagentbench_split_manifest_results.json")
        .read_text(encoding="utf-8")
    )
    units = {unit["unit_id"]: unit for unit in mab_manifest["units"]}
    development_ids = payload["frozen_development_gate"]["families"][
        "memoryagentbench_cross_family"
    ]["unit_ids"]
    assert len(development_ids) == 10
    assert all(units[unit_id]["split"] == "development" for unit_id in development_ids)
    assert len({units[unit_id]["context_sha256"] for unit_id in development_ids}) == 10

    final_ids = payload["frozen_admission"][
        "memoryagentbench_fresh_final_unit_ids"
    ]
    assert len(final_ids) == 10
    assert all(units[unit_id]["split"] == "final" for unit_id in final_ids)
    assert len({units[unit_id]["context_sha256"] for unit_id in final_ids}) == 10
    assert set(final_ids).isdisjoint(negative["opened_v10_final_unit_ids"])

    gate = payload["frozen_development_gate"]
    assert gate["required_reproducible_runs"] == 3
    assert gate["required_independent_families"] == 2
    assert gate["minimum_independent_clusters_per_family"] == 5
    assert gate[
        "paired_cluster_bootstrap_ci_lower_strictly_greater_than"
    ] == 0.0
    assert gate["minimum_intervention_coverage"] == 0.8
    assert gate["stop_on_first_failed_required_run"] is True
