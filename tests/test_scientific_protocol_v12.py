from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v12.json"


def test_v12_protocol_freezes_metric_routing_and_fresh_evidence():
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    digest = payload.pop("protocol_digest")
    assert hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest() == digest
    invalid = payload["immutable_v11_evidence"]
    record_path = ROOT / invalid["terminal_record_path"]
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert validate_artifact_integrity(record) == []
    assert file_sha256(record_path) == invalid["terminal_record_file_sha256"]
    assert invalid["complete_gate_decisions"] == 0
    assert invalid["opened_development_units_may_be_reused"] is False

    assert payload["candidate"]["official_primary_metric_routing"] == {
        "detective_qa": "exact_match",
        "recsys_*": "recsys_recall@10",
        "ruler_*": "ruler_recall",
        "all_other_sources": "substring_exact_match",
    }
    manifest = json.loads(
        (ROOT / "benchmarks" / "memoryagentbench_split_manifest_results.json")
        .read_text(encoding="utf-8")
    )
    units = {unit["unit_id"]: unit for unit in manifest["units"]}
    development = payload["frozen_development_gate"]["families"][
        "memoryagentbench_cross_family"
    ]["unit_ids"]
    assert len(development) == 10
    assert all(units[unit_id]["split"] == "development" for unit_id in development)
    assert len({units[unit_id]["context_sha256"] for unit_id in development}) == 10
    final = payload["frozen_admission"]["memoryagentbench_fresh_final_unit_ids"]
    assert len(final) == 10
    assert all(units[unit_id]["split"] == "final" for unit_id in final)
    assert set(final).isdisjoint(development)
    gate = payload["frozen_development_gate"]
    assert gate["required_reproducible_runs"] == 3
    assert gate["paired_cluster_bootstrap_ci_lower_strictly_greater_than"] == 0.0
    assert gate["minimum_intervention_coverage"] == 0.8
