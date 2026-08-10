from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from wavemind.quality_leadership_admission import (
    DEFAULT_PROTOCOL_PATH,
    GOAL4_ARTIFACT_PATH,
    QUALITY_THRESHOLDS,
    evaluate_quality_leadership_admission,
    quality_leadership_results_from_diagnostics,
    quality_leadership_protocol_manifest,
    validate_goal4_failure_artifact,
    write_quality_leadership_development_results,
)
from wavemind.evidence import (
    attach_artifact_integrity,
    canonical_json_bytes,
    sha256_bytes,
)
from benchmarks.quality_leadership_freeze_protocol import (
    CANDIDATE2_DATASET_REVISION,
    CANDIDATE2_LANE,
    build_frozen_protocol,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _copy_goal4_artifact(root: Path) -> None:
    target = root / GOAL4_ARTIFACT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (PROJECT_ROOT / GOAL4_ARTIFACT_PATH).read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _source_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def _agent_memory_payload(*, source_sha: str | None = None) -> dict:
    source = source_sha or _source_sha()
    return {
        "schema": "wavemind.agent_memory_advantage_benchmark.v1",
        "status": "pass",
        "source_sha": source,
        "protocol": {
            "measurement_trials": 5,
            "confidence_level": 0.95,
        },
        "results": [
            {
                "engine": "WaveMind Core",
                "status": "pass",
                "task_success_rate": 0.40,
                "stale_error_rate": 0.60,
                "context_budget_saved": 0.50,
                "p95_latency_ms": 10.0,
                "category_success": {
                    "knowledge_update": 0.40,
                    "preference_update": 1.0,
                    "state_tracking": 1.0,
                    "workflow_gotcha": 0.0,
                },
            },
            {
                "engine": "WaveMind + Memory OS",
                "status": "pass",
                "task_success_rate": 0.80,
                "task_success_ci95": {"lower": 0.70, "upper": 0.90},
                "stale_error_rate": 0.01,
                "stale_error_ci95": {"lower": 0.0, "upper": 0.02},
                "context_budget_saved": 0.40,
                "context_budget_saved_ci95": {"lower": 0.35, "upper": 0.45},
                "p95_latency_ms": 11.0,
                "category_success": {
                    "knowledge_update": 0.80,
                    "preference_update": 1.0,
                    "state_tracking": 1.0,
                    "workflow_gotcha": 1.0,
                },
            },
        ],
        "skipped": [
            {
                "engine": "Chroma static",
                "status": "skipped",
                "reason": "chromadb_not_installed",
            },
            {
                "engine": "Qdrant static",
                "status": "skipped",
                "reason": "qdrant_client_not_installed",
            },
            {
                "engine": "Mem0 OSS",
                "status": "skipped",
                "reason": "package_not_installed",
            },
            {
                "engine": "LangMem / LangGraph",
                "status": "skipped",
                "reason": "package_not_installed",
            },
        ],
        "paired_lift": {
            "overall_task_success": {"lower": 0.20, "upper": 0.60},
            "categories": {
                "knowledge_update": {"lower": 0.10, "upper": 0.50},
                "preference_update": {"lower": 0.0, "upper": 0.0},
                "workflow_gotcha": {"lower": 0.20, "upper": 0.80},
                "state_tracking": {"lower": 0.0, "upper": 0.10},
            },
        },
    }


def _mem0_runtime_proof() -> dict:
    return {
        "provider": "wavemind-shared",
        "kind": "hash",
        "vector_dim": 384,
        "matches_shared_encoder": True,
        "used_for_ingest_and_search": True,
        "embed_calls": 54,
        "expected_min_calls": 54,
    }


def _split_digest(split: dict) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                key: value
                for key, value in split.items()
                if key not in {"sha256", "digest", "generated_at"}
            }
        )
    )


def _frozen_protocol() -> dict:
    development_split = {
        "id": "quality-leadership-dev-controlled-sequential-v1",
        "role": "development",
        "view_status": "viewed_development_only",
        "case_count": 2,
        "categories": {
            "knowledge_update": 1,
            "workflow_gotcha": 1,
        },
        "primary_sources": [
            {
                "name": "WaveMind controlled sequential Memory OS dev fixture",
                "path": "benchmarks/memory_os_ab_benchmark.py",
                "license": "MIT",
                "revision": "quality-leadership-dev-v1",
            }
        ],
        "case_fingerprints": [
            "dev:knowledge_update:role-current-vs-stale",
            "dev:workflow_gotcha:backup-rule",
        ],
    }
    held_out_split = {
        "id": "quality-leadership-heldout-independent-v1",
        "role": "held_out",
        "view_status": "unopened",
        "case_count": 2,
        "categories": {
            "temporal_update": 1,
            "workflow_state": 1,
        },
        "primary_sources": [
            {
                "name": "Independent public quality hold-out manifest",
                "url": "https://example.invalid/dataset-card",
                "license": "dataset-specific-public-license",
                "revision": "independent-heldout-v1",
            }
        ],
        "case_fingerprints": [
            "heldout:temporal_update:reserved-001",
            "heldout:workflow_state:reserved-002",
        ],
    }
    protocol = quality_leadership_protocol_manifest(root=PROJECT_ROOT)
    protocol["status"] = "frozen_before_heldout"
    protocol["new_quality_dataset"] = {
        "schema": "wavemind.quality_leadership_split_manifest.v1",
        "state": "frozen_before_heldout",
        "revision": "quality-leadership-v1-test-freeze",
        "development_split": development_split,
        "held_out_split": held_out_split,
        "development_split_sha256": _split_digest(development_split),
        "held_out_split_sha256": _split_digest(held_out_split),
        "held_out_viewed": False,
        "licenses": {
            "development": "MIT",
            "held_out": "dataset-specific-public-license",
        },
        "dataset_revisions": {
            "development": "quality-leadership-dev-v1",
            "held_out": "independent-heldout-v1",
        },
    }
    return attach_artifact_integrity(protocol)


def _memory_agent_metadata() -> dict:
    return {
        "id": "ai-hyz/MemoryAgentBench",
        "sha": "7ea066982b140a19337e17e60d45d4076e042faf",
        "cardData": {
            "license": "mit",
            "dataset_info": {
                "splits": [
                    {"name": "Accurate_Retrieval", "num_examples": 22},
                    {"name": "Test_Time_Learning", "num_examples": 6},
                    {"name": "Long_Range_Understanding", "num_examples": 110},
                    {"name": "Conflict_Resolution", "num_examples": 8},
                ],
            },
        },
        "siblings": [
            {
                "rfilename": "data/Accurate_Retrieval-00000-of-00001.parquet",
                "blobId": "a" * 40,
                "size": 20024386,
                "lfs": {"sha256": "1" * 64, "size": 20024386},
            },
            {
                "rfilename": "data/Test_Time_Learning-00000-of-00001.parquet",
                "blobId": "b" * 40,
                "size": 3947476,
                "lfs": {"sha256": "2" * 64, "size": 3947476},
            },
            {
                "rfilename": "data/Long_Range_Understanding-00000-of-00001.parquet",
                "blobId": "c" * 40,
                "size": 49342452,
                "lfs": {"sha256": "3" * 64, "size": 49342452},
            },
            {
                "rfilename": "data/Conflict_Resolution-00000-of-00001.parquet",
                "blobId": "d" * 40,
                "size": 1491588,
                "lfs": {"sha256": "4" * 64, "size": 1491588},
            },
        ],
    }


def test_checked_in_quality_leadership_admission_blocks_without_new_evidence() -> None:
    payload = evaluate_quality_leadership_admission(root=PROJECT_ROOT)
    rows = {row["id"]: row for row in payload["rows"]}
    protocol = json.loads(
        (PROJECT_ROOT / DEFAULT_PROTOCOL_PATH).read_text(encoding="utf-8")
    )
    expected_freeze_status = (
        "implemented"
        if protocol.get("status") == "frozen_before_heldout"
        else "blocked"
    )

    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert rows["goal4-failure-preserved"]["status"] == "implemented"
    assert expected_freeze_status == "implemented"
    if protocol["source_sha"] == payload["source_sha"]:
        freeze_row = rows["protocol-frozen-before-heldout"]
        assert freeze_row["status"] == "blocked"
        assert any(
            "category improvement ceiling below threshold" in error
            for error in freeze_row["details"]["errors"]
        )
    else:
        assert rows["protocol-snapshot-current"]["status"] in {"blocked", "failed"}
        assert rows["protocol-frozen-before-heldout"]["status"] == "blocked"
        assert any(
            "protocol snapshot is not current" in error
            for error in rows["protocol-frozen-before-heldout"]["details"]["errors"]
        )
        assert rows["results-artifact-current"]["status"] == "blocked"
        for stale_results_row in (
            "memory-os-uplift-over-core",
            "context-reduction",
            "latency-budget",
            "real-local-competitors",
            "five-run-confidence-intervals",
        ):
            assert rows[stale_results_row]["status"] == "blocked"
            assert rows[stale_results_row]["details"]["artifact_errors"]
    assert rows["development-go-no-go"]["status"] == "blocked"
    assert rows["heldout-opened-once"]["status"] == "blocked"


def test_development_results_extract_metrics_but_keep_gate_blocked(tmp_path: Path) -> None:
    diagnostic = tmp_path / "agent.json"
    diagnostic.write_text(json.dumps(_agent_memory_payload()), encoding="utf-8")

    payload = quality_leadership_results_from_diagnostics(
        root=PROJECT_ROOT,
        agent_memory_path=diagnostic,
    )

    assert payload["status"] == "development_blocked"
    assert payload["development_gate"]["status"] == "blocked"
    assert payload["metrics"]["memory_os_uplift_over_core"] == pytest.approx(0.40)
    assert payload["metrics"]["improved_category_count"] == 2
    analysis = payload["metrics"]["category_improvement_analysis"]
    assert analysis["improvement_ceiling_over_core"] == 2
    assert analysis["baseline_ceiling_categories"] == [
        "preference_update",
        "state_tracking",
    ]
    assert (
        analysis["methodology_status"]
        == "blocked_unsatisfiable_without_split_change_or_baseline_degradation"
    )
    taxonomy = payload["blocker_taxonomy"]
    assert taxonomy["candidate_status"] == "failed"
    assert taxonomy["failed_candidates"] == [
        {
            "id": "candidate-1",
            "status": "failed",
            "reason": (
                "bounded development evidence on the preregistered 18-case "
                "split cannot reach the four-category improvement gate"
            ),
            "frozen_split_sha256": (
                "e4345094922637414bec7f69a15cea9207380b1795b39eb53270da99b89965a2"
            ),
            "improvement_ceiling_over_core": 2,
            "target": QUALITY_THRESHOLDS["improved_categories_min"],
            "held_out_policy": "not_opened",
        }
    ]
    assert taxonomy["held_out_policy"].startswith("not_opened")
    assert taxonomy["blockers"][0]["id"] == "category_improvement_ceiling"
    assert "category_improvement_ceiling below threshold" in " ".join(
        payload["development_gate"]["errors"]
    )
    assert "missing real local competitors" in " ".join(
        payload["development_gate"]["errors"]
    )


def test_development_results_refreshes_per_query_header(tmp_path: Path) -> None:
    diagnostic = tmp_path / "agent.json"
    diagnostic.write_text(json.dumps(_agent_memory_payload()), encoding="utf-8")
    per_query = tmp_path / "quality_leadership_per_query.jsonl"
    per_query.write_text(
        json.dumps(
            {
                "schema": "wavemind.quality_leadership_per_query.v1",
                "status": "not_run",
                "source_sha": "0" * 40,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    payload = write_quality_leadership_development_results(
        root=PROJECT_ROOT,
        agent_memory_path=diagnostic,
        results_output=tmp_path / "results.json",
        per_query_output=per_query,
        admission_output=tmp_path / "admission.json",
        markdown_output=tmp_path / "admission.md",
    )

    header = json.loads(per_query.read_text(encoding="utf-8").splitlines()[0])
    assert header["source_sha"] == _source_sha()
    assert {row["id"]: row for row in payload["rows"]}["per-query-artifact"][
        "status"
    ] == "implemented"


def test_development_results_reject_wrong_source_diagnostic(tmp_path: Path) -> None:
    diagnostic = tmp_path / "agent.json"
    diagnostic.write_text(
        json.dumps(_agent_memory_payload(source_sha="0" * 40)),
        encoding="utf-8",
    )

    payload = quality_leadership_results_from_diagnostics(
        root=PROJECT_ROOT,
        agent_memory_path=diagnostic,
    )

    assert payload["development_gate"]["status"] == "blocked"
    assert any(
        "source SHA mismatch" in error
        for error in payload["development_gate"]["errors"]
    )


def test_development_results_recognizes_real_competitor_families(tmp_path: Path) -> None:
    source = _agent_memory_payload()
    source["results"].extend(
        [
            {
                "engine": "Chroma static",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "task_success_rate": 0.40,
                "p95_latency_ms": 2.0,
            },
            {
                "engine": "Mem0 OSS",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "embedding_runtime_proof": _mem0_runtime_proof(),
                "task_success_rate": 0.35,
                "p95_latency_ms": 5.0,
            },
            {
                "engine": "LangGraph persistent memory",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "task_success_rate": 0.30,
                "p95_latency_ms": 3.0,
            },
        ]
    )
    diagnostic = tmp_path / "agent.json"
    diagnostic.write_text(json.dumps(source), encoding="utf-8")

    payload = quality_leadership_results_from_diagnostics(
        root=PROJECT_ROOT,
        agent_memory_path=diagnostic,
    )

    assert "missing real local competitors" not in " ".join(
        payload["development_gate"]["errors"]
    )


def test_development_results_rejects_competitor_without_same_embedding_proof(
    tmp_path: Path,
) -> None:
    source = _agent_memory_payload()
    source["results"].extend(
        [
            {
                "engine": "Chroma static",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "task_success_rate": 0.40,
                "p95_latency_ms": 2.0,
            },
            {
                "engine": "Mem0 OSS",
                "status": "pass",
                "task_success_rate": 0.35,
                "p95_latency_ms": 5.0,
            },
            {
                "engine": "LangGraph persistent memory",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "task_success_rate": 0.30,
                "p95_latency_ms": 3.0,
            },
        ]
    )
    diagnostic = tmp_path / "agent.json"
    diagnostic.write_text(json.dumps(source), encoding="utf-8")

    payload = quality_leadership_results_from_diagnostics(
        root=PROJECT_ROOT,
        agent_memory_path=diagnostic,
    )

    errors = " ".join(payload["development_gate"]["errors"])
    assert "missing real local competitors" in errors
    assert "mem0_oss" in payload["competitor_runs"][1]["family"]
    assert payload["competitor_runs"][1]["embedding_comparable"] is False


def test_development_results_rejects_mem0_without_runtime_embedding_proof(
    tmp_path: Path,
) -> None:
    source = _agent_memory_payload()
    source["results"].extend(
        [
            {
                "engine": "Chroma static",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "task_success_rate": 0.40,
                "p95_latency_ms": 2.0,
            },
            {
                "engine": "Mem0 OSS",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "task_success_rate": 0.35,
                "p95_latency_ms": 5.0,
            },
            {
                "engine": "LangGraph persistent memory",
                "status": "pass",
                "eligible_for_comparison": True,
                "embedding_comparable": True,
                "same_embedding_as_wavemind": True,
                "task_success_rate": 0.30,
                "p95_latency_ms": 3.0,
            },
        ]
    )
    diagnostic = tmp_path / "agent.json"
    diagnostic.write_text(json.dumps(source), encoding="utf-8")

    payload = quality_leadership_results_from_diagnostics(
        root=PROJECT_ROOT,
        agent_memory_path=diagnostic,
    )

    errors = " ".join(payload["development_gate"]["errors"])
    assert "missing real local competitors" in errors
    mem0 = next(row for row in payload["competitor_runs"] if row["engine"] == "Mem0 OSS")
    assert mem0["embedding_comparable"] is False
    assert "runtime proof" in mem0["reason"]


def test_in_repo_development_diagnostic_path_stays_relative() -> None:
    payload = quality_leadership_results_from_diagnostics(
        root=PROJECT_ROOT,
        agent_memory_path="benchmarks/quality_leadership_agent_memory_advantage_dev.json",
    )

    assert (
        payload["development_gate"]["diagnostic"]
        == "benchmarks/quality_leadership_agent_memory_advantage_dev.json"
    )
    assert (
        payload["runs"][0]["artifact"]
        == "benchmarks/quality_leadership_agent_memory_advantage_dev.json"
    )


def test_goal4_failure_validation_rejects_false_success() -> None:
    payload = json.loads(
        (PROJECT_ROOT / GOAL4_ARTIFACT_PATH).read_text(encoding="utf-8")
    )
    payload["status"] = "admitted"
    payload["admitted"] = True

    errors = validate_goal4_failure_artifact(payload)

    assert any("failed_experiment" in error for error in errors)


def test_protocol_threshold_weakening_blocks_admission(tmp_path: Path) -> None:
    protocol = quality_leadership_protocol_manifest(root=PROJECT_ROOT)
    protocol["thresholds"]["memory_os_uplift_over_core_min"] = 0.0
    protocol = attach_artifact_integrity(protocol)
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
        results_path=tmp_path / "missing-results.json",
    )

    row = {row["id"]: row for row in result["rows"]}["protocol-snapshot-current"]
    assert row["status"] == "failed"
    assert any("threshold changed" in error for error in row["details"]["errors"])


def test_frozen_protocol_requires_real_split_manifest(tmp_path: Path) -> None:
    protocol = _frozen_protocol()
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
        results_path=tmp_path / "missing-results.json",
    )

    row = {row["id"]: row for row in result["rows"]}["protocol-frozen-before-heldout"]
    assert row["status"] == "implemented"
    assert row["details"]["errors"] == []


def test_freeze_builder_reserves_memory_agent_bench_without_opening_rows(tmp_path: Path) -> None:
    protocol = build_frozen_protocol(
        root=PROJECT_ROOT,
        memory_agent_metadata=_memory_agent_metadata(),
    )
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
        results_path=tmp_path / "missing-results.json",
    )

    dataset = protocol["new_quality_dataset"]
    held_out = dataset["held_out_split"]
    design = dataset["development_gate_design_analysis"]
    row = {row["id"]: row for row in result["rows"]}["protocol-frozen-before-heldout"]
    assert row["status"] == "implemented"
    assert dataset["development_split"]["case_count"] == 18
    assert dataset["development_split"]["categories"] == {
        "knowledge_update": 9,
        "preference_update": 1,
        "state_tracking": 2,
        "workflow_gotcha": 6,
    }
    assert dataset["development_split_sha256"] == (
        "e4345094922637414bec7f69a15cea9207380b1795b39eb53270da99b89965a2"
    )
    assert design["target_improved_categories"] == 4
    assert design["development_category_count"] == 4
    assert design["requires_runtime_ceiling_check"] is True
    assert design["ceiling_risk"] == "no_spare_categories_for_strict_lift_gate"
    assert held_out["view_status"] == "unopened"
    assert held_out["case_count"] == 146
    assert len(held_out["case_fingerprints"]) == 146
    assert "row contents are not opened" in " ".join(held_out["leakage_controls"])
    assert result["status"] == "blocked"
    assert result["admitted"] is False


def test_freeze_builder_preregisters_candidate2_memoryagentbench_lane(
    tmp_path: Path,
) -> None:
    protocol = build_frozen_protocol(
        root=PROJECT_ROOT,
        memory_agent_metadata=_memory_agent_metadata(),
        lane=CANDIDATE2_LANE,
    )
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
        results_path=tmp_path / "missing-results.json",
    )

    dataset = protocol["new_quality_dataset"]
    development = dataset["development_split"]
    held_out = dataset["held_out_split"]
    development_ids = set(development["case_fingerprints"])
    held_out_ids = set(held_out["case_fingerprints"])
    split_identity = json.dumps(
        {
            "development": development["case_fingerprints"],
            "held_out": held_out["case_fingerprints"],
            "development_sources": development["primary_sources"],
            "held_out_sources": held_out["primary_sources"],
        },
        sort_keys=True,
    )
    row = {row["id"]: row for row in result["rows"]}["protocol-frozen-before-heldout"]

    assert dataset["revision"] == CANDIDATE2_DATASET_REVISION
    assert dataset["lane"] == CANDIDATE2_LANE
    assert dataset["development_split_sha256"] == _split_digest(development)
    assert dataset["held_out_split_sha256"] == _split_digest(held_out)
    assert development["id"] == "memoryagentbench-balanced-development-v2"
    assert development["role"] == "development"
    assert development["view_status"] == "reserved_unopened_until_bounded_development"
    assert development["case_count"] == 8
    assert development["categories"] == {
        "Accurate_Retrieval": 2,
        "Conflict_Resolution": 2,
        "Long_Range_Understanding": 2,
        "Test_Time_Learning": 2,
    }
    assert held_out["id"] == "memoryagentbench-balanced-heldout-v2"
    assert held_out["view_status"] == "unopened"
    assert held_out["case_count"] == 138
    assert held_out["categories"] == {
        "Accurate_Retrieval": 20,
        "Conflict_Resolution": 6,
        "Long_Range_Understanding": 108,
        "Test_Time_Learning": 4,
    }
    assert development_ids.isdisjoint(held_out_ids)
    assert all("memoryagentbench:" in fingerprint for fingerprint in development_ids)
    assert all("memoryagentbench:" in fingerprint for fingerprint in held_out_ids)
    assert "full451" not in split_identity
    assert "untouched419" not in split_identity
    assert "wavemind-dev:" not in split_identity
    assert "row contents are not opened" in " ".join(development["leakage_controls"])
    assert "held-out rows are disjoint" in " ".join(held_out["leakage_controls"])
    assert row["status"] == "implemented"
    assert result["status"] == "blocked"
    assert result["admitted"] is False


def test_freeze_cli_can_write_candidate2_lane(tmp_path: Path) -> None:
    metadata = tmp_path / "memoryagentbench_metadata.json"
    output = tmp_path / "candidate2_protocol.json"
    metadata.write_text(json.dumps(_memory_agent_metadata()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "benchmarks/quality_leadership_freeze_protocol.py",
            "--metadata-json",
            str(metadata),
            "--output",
            str(output),
            "--lane",
            CANDIDATE2_LANE,
            "--expected-source-sha",
            _source_sha(),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["new_quality_dataset"]["lane"] == CANDIDATE2_LANE
    assert payload["new_quality_dataset"]["revision"] == CANDIDATE2_DATASET_REVISION
    assert payload["new_quality_dataset"]["development_split"]["case_count"] == 8
    assert payload["new_quality_dataset"]["held_out_split"]["case_count"] == 138


def test_frozen_v1_protocol_rejects_post_result_development_refreeze(
    tmp_path: Path,
) -> None:
    protocol = build_frozen_protocol(
        root=PROJECT_ROOT,
        memory_agent_metadata=_memory_agent_metadata(),
    )
    dataset = protocol["new_quality_dataset"]
    development_split = dataset["development_split"]
    development_split["case_count"] = 24
    development_split["categories"] = {
        "knowledge_update": 9,
        "preference_update": 3,
        "state_tracking": 6,
        "workflow_gotcha": 6,
    }
    development_split["case_fingerprints"] = [
        *development_split["case_fingerprints"],
        *[f"wavemind-dev:post-result-added-{index}" for index in range(6)],
    ]
    dataset["development_split_sha256"] = _split_digest(development_split)
    protocol = attach_artifact_integrity(protocol)
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
    )

    row = {row["id"]: row for row in result["rows"]}["protocol-frozen-before-heldout"]
    assert row["status"] == "blocked"
    errors = " ".join(row["details"]["errors"])
    assert "frozen v1 development_split_sha256 differs" in errors
    assert "frozen v1 development split content differs" in errors
    assert "frozen v1 development split case_count changed" in errors
    assert "frozen v1 development split categories changed" in errors


def test_current_development_ceiling_blocks_frozen_protocol_before_heldout(
    tmp_path: Path,
) -> None:
    protocol = _frozen_protocol()
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    diagnostic = tmp_path / "agent.json"
    diagnostic.write_text(json.dumps(_agent_memory_payload()), encoding="utf-8")
    results = quality_leadership_results_from_diagnostics(
        root=PROJECT_ROOT,
        agent_memory_path=diagnostic,
    )
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
        results_path=results_path,
    )

    row = {row["id"]: row for row in result["rows"]}["protocol-frozen-before-heldout"]
    assert row["status"] == "blocked"
    assert any(
        "category improvement ceiling below threshold" in error
        for error in row["details"]["errors"]
    )


def test_freeze_builder_requires_file_level_huggingface_lfs_hashes() -> None:
    metadata = _memory_agent_metadata()
    metadata["siblings"][0].pop("lfs")

    with pytest.raises(ValueError, match="no LFS SHA"):
        build_frozen_protocol(
            root=PROJECT_ROOT,
            memory_agent_metadata=metadata,
        )


def test_frozen_protocol_rejects_viewed_heldout(tmp_path: Path) -> None:
    protocol = _frozen_protocol()
    protocol["new_quality_dataset"]["held_out_viewed"] = True
    protocol["new_quality_dataset"]["held_out_split"]["view_status"] = "viewed"
    protocol = attach_artifact_integrity(protocol)
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
    )

    row = {row["id"]: row for row in result["rows"]}["protocol-frozen-before-heldout"]
    assert row["status"] == "blocked"
    errors = " ".join(row["details"]["errors"])
    assert "held-out split must be unviewed" in errors
    assert "held_out_split is not unopened" in errors


def test_frozen_protocol_rejects_split_overlap(tmp_path: Path) -> None:
    protocol = _frozen_protocol()
    held_out = protocol["new_quality_dataset"]["held_out_split"]
    held_out["case_fingerprints"][0] = protocol["new_quality_dataset"][
        "development_split"
    ]["case_fingerprints"][0]
    protocol["new_quality_dataset"]["held_out_split_sha256"] = _split_digest(held_out)
    protocol = attach_artifact_integrity(protocol)
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
    )

    row = {row["id"]: row for row in result["rows"]}["protocol-frozen-before-heldout"]
    assert row["status"] == "blocked"
    assert any("development/held-out overlap" in error for error in row["details"]["errors"])


def test_frozen_protocol_rejects_split_digest_tampering(tmp_path: Path) -> None:
    protocol = _frozen_protocol()
    protocol["new_quality_dataset"]["development_split_sha256"] = "0" * 64
    protocol = attach_artifact_integrity(protocol)
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
    )

    row = {row["id"]: row for row in result["rows"]}["protocol-frozen-before-heldout"]
    assert row["status"] == "blocked"
    assert any("development_split_sha256 mismatch" in error for error in row["details"]["errors"])


def test_frozen_protocol_rejects_goal4_as_new_heldout(tmp_path: Path) -> None:
    protocol = _frozen_protocol()
    held_out = protocol["new_quality_dataset"]["held_out_split"]
    held_out["primary_sources"][0]["path"] = "benchmarks/goal4_quality_experiment_results.json"
    held_out["case_fingerprints"][0] = "full451"
    protocol["new_quality_dataset"]["held_out_split_sha256"] = _split_digest(held_out)
    protocol = attach_artifact_integrity(protocol)
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
    )

    row = {row["id"]: row for row in result["rows"]}["protocol-frozen-before-heldout"]
    assert row["status"] == "blocked"
    assert any("historical Goal 4 evidence" in error for error in row["details"]["errors"])


def test_historical_goal4_cannot_be_declared_tuning_data(tmp_path: Path) -> None:
    protocol = quality_leadership_protocol_manifest(root=PROJECT_ROOT)
    protocol["historical_regression_evidence"]["role"] = "development"
    protocol = attach_artifact_integrity(protocol)
    protocol_path = tmp_path / DEFAULT_PROTOCOL_PATH
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")

    result = evaluate_quality_leadership_admission(
        root=PROJECT_ROOT,
        protocol_path=protocol_path,
    )

    row = {row["id"]: row for row in result["rows"]}["protocol-snapshot-current"]
    assert row["status"] == "failed"
    assert any("historical Goal 4 evidence" in error for error in row["details"]["errors"])


def test_cli_writes_quality_leadership_artifacts_and_blocks(tmp_path: Path) -> None:
    output = tmp_path / "admission.json"
    markdown = tmp_path / "admission.md"
    protocol = tmp_path / "protocol.json"
    results = tmp_path / "results.json"
    per_query = tmp_path / "per_query.jsonl"
    command = [
        sys.executable,
        "-m",
        "wavemind.cli",
        "quality-leadership-admission",
        "--root",
        str(PROJECT_ROOT),
        "--write-artifacts",
        "--fail-on-blocked",
        "--protocol-output",
        str(protocol),
        "--results-output",
        str(results),
        "--per-query-output",
        str(per_query),
        "--output",
        str(output),
        "--markdown-output",
        str(markdown),
        "--json",
    ]

    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["status"] == "blocked"
    assert json.loads(output.read_text(encoding="utf-8"))["admitted"] is False
    assert "# Quality Leadership Admission" in markdown.read_text(encoding="utf-8")
    assert json.loads(protocol.read_text(encoding="utf-8"))["thresholds"] == QUALITY_THRESHOLDS
    assert per_query.read_text(encoding="utf-8").splitlines()[0]


def test_benchmark_wrapper_requires_admitted_exit_code(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "benchmarks/quality_leadership_admission.py",
            "--output",
            str(tmp_path / "admission.json"),
            "--markdown-output",
            str(tmp_path / "admission.md"),
            "--protocol-output",
            str(tmp_path / "protocol.json"),
            "--results-output",
            str(tmp_path / "results.json"),
            "--per-query-output",
            str(tmp_path / "per_query.jsonl"),
            "--require-admitted",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["status"] == "blocked"
