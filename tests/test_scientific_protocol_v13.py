from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def test_v13_protocol_freezes_official_summarization_metric_and_fresh_units():
    path = ROOT / "benchmarks" / "scientific_memory_protocol_v13.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    digest = payload.pop("protocol_digest")
    assert hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest() == digest
    previous = payload["immutable_v12_evidence"]
    outcome_path = ROOT / previous["outcome_path"]
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    assert validate_artifact_integrity(outcome) == []
    assert file_sha256(outcome_path) == previous["outcome_file_sha256"]
    assert payload["candidate"]["official_primary_metric_routing"][
        "infbench_sum_eng_shots2"
    ] == "rougeL_recall"
    manifest = json.loads(
        (ROOT / "benchmarks" / "memoryagentbench_split_manifest_results.json")
        .read_text(encoding="utf-8")
    )
    units = {unit["unit_id"]: unit for unit in manifest["units"]}
    ids = payload["frozen_development_gate"]["families"][
        "memoryagentbench_summarization"
    ]["unit_ids"]
    assert len(ids) == 10
    assert all(units[unit_id]["split"] == "development" for unit_id in ids)
    assert len({units[unit_id]["context_sha256"] for unit_id in ids}) == 10
    gate = payload["frozen_development_gate"]
    assert gate["required_reproducible_runs"] == 3
    assert gate["paired_cluster_bootstrap_ci_lower_strictly_greater_than"] == 0.0
