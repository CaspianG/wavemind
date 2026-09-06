from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wavemind.evidence import file_sha256, validate_artifact_integrity


ROOT = Path(__file__).resolve().parents[1]


def test_v14_protocol_binds_new_contexts_algorithm_and_unchanged_gate():
    path = ROOT / "benchmarks" / "scientific_memory_protocol_v14.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    digest = payload.pop("protocol_digest")
    assert hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest() == digest

    failed = payload["immutable_v13_evidence"]
    failed_path = ROOT / failed["outcome_path"]
    failed_payload = json.loads(failed_path.read_text(encoding="utf-8"))
    assert validate_artifact_integrity(failed_payload) == []
    assert file_sha256(failed_path) == failed["outcome_file_sha256"]

    diagnostic = payload["opened_diagnostic_evidence"]
    diagnostic_path = ROOT / diagnostic["outcome_path"]
    diagnostic_payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert validate_artifact_integrity(diagnostic_payload) == []
    assert file_sha256(diagnostic_path) == diagnostic["outcome_file_sha256"]
    assert diagnostic["official_gate_decision"] is False

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
    assert min(units[unit_id]["row_index"] for unit_id in ids) > 45
    assert len({units[unit_id]["context_sha256"] for unit_id in ids}) == 10

    parameters = payload["frozen_parameters"]
    assert parameters["sequence_coverage_points"] == 28
    assert parameters["plot_plan_max_tokens"] == 800
    assert parameters["draft_word_rewrite_threshold"] == 700
    assert parameters["maximum_length_rewrites"] == 1
    gate = payload["frozen_development_gate"]
    assert gate["required_reproducible_runs"] == 3
    assert gate["paired_cluster_bootstrap_ci_lower_strictly_greater_than"] == 0.0
    assert gate["stop_on_first_failed_required_run"] is True
