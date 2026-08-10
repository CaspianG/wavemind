from __future__ import annotations

import copy

import pytest

from benchmarks import workspace_experience_v5_benchmark as bench


def test_v5_manifest_accepts_frozen_real_work_cases_without_checkout() -> None:
    payload = bench.load_manifest()

    assert bench.validate_manifest(payload, require_checkout=False) == {
        "positive": 60,
        "controls": 24,
        "dev": 42,
        "heldout": 42,
        "semantic_families": 60,
    }


def test_v5_manifest_rejects_checksum_only_task_success() -> None:
    payload = _manifest()
    payload["cases"][0]["expected_outcome"]["kind"] = "source_sha256_check"
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceV5BenchmarkError, match="checksum-only"):
        bench.validate_manifest(payload, require_checkout=False)


def test_v5_manifest_rejects_split_family_overlap() -> None:
    payload = _manifest()
    heldout = next(case for case in payload["cases"] if case["split"] == "heldout" and case["kind"] == "positive")
    dev = next(case for case in payload["cases"] if case["split"] == "dev" and case["kind"] == "positive")
    heldout["semantic_family"] = dev["semantic_family"]
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceV5BenchmarkError, match="duplicate semantic_family"):
        bench.validate_manifest(payload, require_checkout=False)


def test_v5_manifest_rejects_query_case_and_procedure_leakage() -> None:
    payload = _manifest()
    payload["cases"][0]["query"] = f"Use {payload['cases'][0]['procedure_id']} now"
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceV5BenchmarkError, match="query leaks"):
        bench.validate_manifest(payload, require_checkout=False)


def test_v5_manifest_rejects_historical_heldout_overlap() -> None:
    payload = _manifest()
    heldout = next(
        case
        for case in payload["cases"]
        if case["split"] == "heldout" and case["kind"] == "positive" and case["repo"] == "requests"
    )
    heldout["source_path"] = ".github/workflows/zizmor.yml"
    heldout["expected_outcome"]["path"] = ".github/workflows/zizmor.yml"
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceV5BenchmarkError, match="historical observed"):
        bench.validate_manifest(payload, require_checkout=False)


def test_v5_manifest_rejects_historical_heldout_control_overlap() -> None:
    payload = _manifest()
    heldout = next(case for case in payload["cases"] if case["split"] == "heldout" and case["kind"] != "positive")
    heldout["semantic_family"] = "flask:app-core-import"
    heldout["source_family"] = "flask:app-core-import"
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceV5BenchmarkError, match="historical observed"):
        bench.validate_manifest(payload, require_checkout=False)


def test_v5_static_context_counts_selected_payload_only(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    selected = {
        "citation": "static:c1",
        "case_id": "case-1",
        "procedure_id": "proc-1",
        "context": "selected packet",
    }
    traces = [
        selected,
        {"citation": "static:c2", "case_id": "case-2", "procedure_id": "proc-2", "context": "ignored " * 50},
    ]
    monkeypatch.setattr(bench, "_rank_static", lambda query, corpus: selected)

    result = bench._static_raw_trace(  # noqa: SLF001 - regression for benchmark fairness metric.
        {"query": "anything", "expected_behavior": "abstain"},
        traces,
        tmp_path,
    )

    assert result["context_chars"] == len(selected["context"])


def test_v5_result_rejects_hardcoded_onboarding_metric() -> None:
    manifest = _manifest()
    payload = _result(manifest)
    payload["metrics"]["admission"]["clean_onboarding_seconds"] = 0.0

    with pytest.raises(bench.WorkspaceV5BenchmarkError, match="hardcoded zero"):
        bench.validate_benchmark_results(payload, manifest)


def test_v5_result_rejects_zero_positive_static_baseline() -> None:
    manifest = _manifest()
    payload = _result(manifest)
    payload["metrics"]["modes"]["static_raw_trace_retrieval"]["positive_success_rate"] = 0.0

    with pytest.raises(bench.WorkspaceV5BenchmarkError, match="zero positive"):
        bench.validate_benchmark_results(payload, manifest)


def test_v5_result_rejects_kind_only_task_success() -> None:
    manifest = _manifest()
    payload = _result(manifest)
    row = payload["rows"][0]
    row["wavemind_verified_workspace_experience"]["task_success"] = True
    row["wavemind_verified_workspace_experience"]["selected_case_id"] = "wrong-case"
    row["wavemind_verified_workspace_experience"]["selected_procedure_id"] = row["case"]["procedure_id"]
    row["wavemind_verified_workspace_experience"]["command"] = {"passed": True}

    with pytest.raises(bench.WorkspaceV5BenchmarkError, match="exact case"):
        bench.validate_benchmark_results(payload, manifest)


def test_v5_heldout_requires_explicit_allowance() -> None:
    with pytest.raises(bench.WorkspaceV5BenchmarkError, match="explicit"):
        bench.run_benchmark(split="heldout")


def _manifest() -> dict:
    return bench.load_manifest()


def _result(manifest: dict) -> dict:
    positive = next(case for case in manifest["cases"] if case["kind"] == "positive")
    return {
        "schema": bench.RESULT_SCHEMA,
        "status": "failed",
        "source_sha": "test",
        "split": "dev",
        "manifest": {"sha256": manifest["sha256"]},
        "protocol": {
            "measurement_provenance": {
                "clean_onboarding_seconds": "subprocess_workspace_demo",
                "cross_client_citation_state_parity": "python_write_http_replay",
            }
        },
        "metrics": {
            "modes": {
                "static_raw_trace_retrieval": {
                    "positive_success_rate": 0.5,
                    "task_success_rate": 0.5,
                },
                "wavemind_verified_workspace_experience": {
                    "positive_success_rate": 0.5,
                    "task_success_rate": 0.5,
                },
            },
            "admission": {
                "clean_onboarding_seconds": 1.0,
            },
        },
        "rows": [
            {
                "case": positive,
                "static_raw_trace_retrieval": {
                    "task_success": False,
                    "selected_case_id": None,
                    "selected_procedure_id": None,
                    "command": {"passed": False},
                },
                "wavemind_verified_workspace_experience": {
                    "task_success": False,
                    "selected_case_id": None,
                    "selected_procedure_id": None,
                    "command": {"passed": False},
                },
            }
        ],
    }


def _refresh_checksum(payload: dict) -> dict:
    refreshed = copy.deepcopy(payload)
    refreshed["sha256"] = bench._sha256(  # noqa: SLF001 - benchmark checksum guard.
        {key: value for key, value in refreshed.items() if key != "sha256"}
    )
    return refreshed
