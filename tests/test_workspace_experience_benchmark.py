from __future__ import annotations

import copy

import pytest

from benchmarks import workspace_experience_benchmark as bench


def _manifest() -> dict:
    return bench.load_manifest()


def _refresh_checksum(payload: dict) -> dict:
    refreshed = copy.deepcopy(payload)
    refreshed["sha256"] = bench._sha256(  # noqa: SLF001 - benchmark checksum guard.
        {key: value for key, value in refreshed.items() if key != "sha256"}
    )
    return refreshed


def test_workspace_experience_manifest_is_frozen_and_structural() -> None:
    counts = bench.validate_manifest(_manifest(), require_checkout=False)

    assert counts == {"positive": 60, "controls": 24, "dev": 24, "heldout": 60}


def test_manifest_rejects_synthetic_repository_remote() -> None:
    payload = _manifest()
    first_repo = next(iter(payload["repositories"].values()))
    first_repo["remote"] = "file:///tmp/synthetic-workspace"
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceBenchmarkError, match="GitHub primary source"):
        bench.validate_manifest(payload, require_checkout=False)


def test_manifest_rejects_duplicate_source_cases() -> None:
    payload = _manifest()
    payload["procedures"][1]["repo"] = payload["procedures"][0]["repo"]
    payload["procedures"][1]["source_path"] = payload["procedures"][0]["source_path"]
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceBenchmarkError, match="duplicate source path"):
        bench.validate_manifest(payload, require_checkout=False)


def test_manifest_rejects_tampered_checksum() -> None:
    payload = _manifest()
    payload["procedures"][0]["source_sha256"] = "0" * 64

    with pytest.raises(bench.WorkspaceBenchmarkError, match="manifest checksum"):
        bench.validate_manifest(payload, require_checkout=False)


def test_result_validator_rejects_citation_only_success() -> None:
    manifest = _manifest()
    case = next(
        item
        for item in manifest["cases"]
        if item["expected_behavior"] == "execute_verified_outcome"
    )
    row = _row(case)
    row["wavemind_verified_workspace_experience"]["task_success"] = True
    row["wavemind_verified_workspace_experience"]["command"]["passed"] = False
    payload = _payload(manifest, row)

    with pytest.raises(bench.WorkspaceBenchmarkError, match="citation-only success"):
        bench.validate_benchmark_results(payload, manifest)


def test_result_validator_rejects_hardcoded_admission_metrics() -> None:
    manifest = _manifest()
    case = next(
        item
        for item in manifest["cases"]
        if item["expected_behavior"] == "execute_verified_outcome"
    )
    row = _row(case)
    row["static_raw_trace_retrieval"]["task_success"] = True
    row["static_raw_trace_retrieval"]["command"]["passed"] = True
    row["wavemind_verified_workspace_experience"]["task_success"] = True
    row["wavemind_verified_workspace_experience"]["command"]["passed"] = True
    payload = _payload(manifest, row)
    payload["metrics"]["admission"]["task_success_lift_pp"] = 999.0

    with pytest.raises(bench.WorkspaceBenchmarkError, match="metrics do not match"):
        bench.validate_benchmark_results(payload, manifest)


def test_result_validator_rejects_control_success_with_citation() -> None:
    manifest = _manifest()
    case = next(item for item in manifest["cases"] if item["expected_behavior"] == "abstain")
    row = _row(case)
    row["wavemind_verified_workspace_experience"]["selected_citations"] = [
        "experience:wrong@v1"
    ]
    row["wavemind_verified_workspace_experience"]["task_success"] = True
    payload = _payload(manifest, row)

    with pytest.raises(bench.WorkspaceBenchmarkError, match="control success"):
        bench.validate_benchmark_results(payload, manifest)


def _row(case: dict) -> dict:
    base_result = {
        "selected_citations": [],
        "abstain": True,
        "context_chars": 100,
        "latency_ms": 1.0,
        "command": {"passed": False, "returncode": 7},
        "task_success": False,
    }
    return {
        "case": case,
        "expected_citation": "experience:expected@v1",
        "no_experience": copy.deepcopy(base_result),
        "static_raw_trace_retrieval": copy.deepcopy(base_result),
        "wavemind_verified_workspace_experience": copy.deepcopy(base_result),
    }


def _payload(manifest: dict, row: dict) -> dict:
    rows = [row]
    latencies = {
        mode: [float(row[mode]["latency_ms"])]
        for mode in (
            "no_experience",
            "static_raw_trace_retrieval",
            "wavemind_verified_workspace_experience",
        )
    }
    metrics = bench._compute_metrics(  # noqa: SLF001 - validator fixture.
        rows,
        latencies,
        capture_expected=1,
        capture_actual=1,
        cross_client_parity=1.0,
        onboarding_seconds=1.0,
    )
    return {
        "schema": bench.RESULT_SCHEMA,
        "manifest": {"sha256": manifest["sha256"]},
        "metrics": metrics,
        "rows": rows,
    }
