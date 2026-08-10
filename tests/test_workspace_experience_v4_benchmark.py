from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from benchmarks import workspace_experience_v4_benchmark as bench


def test_v4_manifest_accepts_real_command_outcomes_without_checkout() -> None:
    payload = _manifest()

    assert bench.validate_manifest(payload, require_checkout=False) == {
        "positive": 60,
        "controls": 20,
        "dev": 24,
        "heldout": 56,
    }


def test_v4_manifest_rejects_checksum_only_task_success() -> None:
    payload = _manifest()
    payload["cases"][0]["expected_outcome"]["kind"] = "source_sha256_check"
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceV4BenchmarkError, match="checksum-only"):
        bench.validate_manifest(payload, require_checkout=False)


def test_v4_manifest_rejects_duplicate_semantic_cases() -> None:
    payload = _manifest()
    payload["cases"][1]["semantic_key"] = payload["cases"][0]["semantic_key"]
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceV4BenchmarkError, match="duplicate semantic"):
        bench.validate_manifest(payload, require_checkout=False)


def test_v4_manifest_rejects_duplicate_query_workflow_outcome_fingerprint() -> None:
    payload = _manifest()
    payload["cases"][1]["query"] = payload["cases"][0]["query"]
    payload["cases"][1]["workflow_group"] = payload["cases"][0]["workflow_group"]
    payload["cases"][1]["expected_outcome"]["kind"] = payload["cases"][0]["expected_outcome"]["kind"]
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceV4BenchmarkError, match="duplicate normalized"):
        bench.validate_manifest(payload, require_checkout=False)


def test_v4_manifest_rejects_source_family_overlap_between_splits() -> None:
    payload = _manifest()
    payload["cases"][40]["source_family"] = payload["cases"][0]["source_family"]
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceV4BenchmarkError, match="cannot overlap"):
        bench.validate_manifest(payload, require_checkout=False)


def test_v4_manifest_rejects_query_source_path_leakage() -> None:
    payload = _manifest()
    payload["cases"][0]["query"] = (
        "Before touching package/module_000.py, which workspace verification applies?"
    )
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceV4BenchmarkError, match="source path leaks"):
        bench.validate_manifest(payload, require_checkout=False)


def test_v4_manifest_rejects_query_filename_stem_leakage() -> None:
    payload = _manifest()
    payload["cases"][0]["query"] = "Which verification applies to module_000 changes?"
    payload = _refresh_checksum(payload)

    with pytest.raises(bench.WorkspaceV4BenchmarkError, match="filename stem leaks"):
        bench.validate_manifest(payload, require_checkout=False)


def test_v4_cross_client_replay_reopens_workspace_config_path(monkeypatch) -> None:
    opened_paths: list[str] = []

    class FakeManager:
        def __init__(self, path: str) -> None:
            self.config = SimpleNamespace(config_path=path)

        def close(self) -> None:
            return None

    def fake_open(path: str) -> FakeManager:
        opened_paths.append(path)
        return FakeManager(path)

    def fake_verified(case, manager, repo_root, citation_to_case):  # noqa: ANN001
        return {"selected_citations": [f"citation:{case['case_id']}"]}

    monkeypatch.setattr(bench.WorkspaceExperienceManager, "open", fake_open)
    monkeypatch.setattr(bench, "_wavemind_verified", fake_verified)

    parity = bench._cross_client_parity(  # noqa: SLF001 - regression target.
        {"repo-a": FakeManager("repo-a/.wavemind/workspace.json")},
        {"repo-a": object()},
        [
            {
                "case_id": "case-a",
                "repo": "repo-a",
                "expected_behavior": "execute_verified_outcome",
            }
        ],
        {},
    )

    assert parity == 1.0
    assert opened_paths == ["repo-a/.wavemind/workspace.json"]


def test_v4_static_raw_trace_fails_on_unverified_control(tmp_path) -> None:
    case = {
        "case_id": "control-a",
        "kind": "unverified",
        "query": "Control unverified workspace request should abstain.",
        "expected_behavior": "abstain",
    }
    result = bench._static_raw_trace(  # noqa: SLF001 - baseline protocol guard.
        case,
        [
            {
                "citation": "raw-trace:control-a",
                "outcome_kind": "unverified_raw_trace",
                "workflow_group": "unverified",
                "context": "RAW_TRACE unverified workspace request should abstain.",
            }
        ],
        tmp_path,
    )

    assert result["selected_citations"] == ["raw-trace:control-a"]
    assert result["task_success"] is False


def test_v4_heldout_requires_explicit_allowance() -> None:
    with pytest.raises(bench.WorkspaceV4BenchmarkError, match="explicit"):
        bench.run_benchmark(split="heldout", allow_invalid_protocol=True)


def test_v4_run_is_historical_diagnostic_only() -> None:
    with pytest.raises(bench.WorkspaceV4BenchmarkError, match="historical_invalid"):
        bench.run_benchmark(split="dev")


def _manifest() -> dict:
    payload = {
        "schema": bench.MANIFEST_SCHEMA,
        "revision": "test-v4",
        "repositories": {
            "repo-a": _repo("python"),
            "repo-b": _repo("python"),
            "repo-c": _repo("javascript"),
        },
        "cases": [],
        "sha256": "",
    }
    for index in range(60):
        repo_id = ("repo-a", "repo-b", "repo-c")[index % 3]
        payload["cases"].append(
            {
                "case_id": f"positive-{index:03d}",
                "kind": "positive",
                "split": "dev" if index < 20 else "heldout",
                "repo": repo_id,
                "semantic_key": f"{repo_id}:syntax:{index:03d}",
                "semantic_family": f"{repo_id}:syntax:{index:03d}",
                "source_family": f"{repo_id}:syntax:{index:03d}",
                "workflow_group": f"{repo_id}-syntax-{index:03d}",
                "source_path": f"package/module_{index:03d}.py",
                "source_url": "https://github.com/example/project/blob/abc/package/module.py",
                "source_sha256": "a" * 64,
                "license": "MIT",
                "query": f"Which verification applies to Python source change {index:03d}?",
                "expected_behavior": "execute_verified_outcome",
                "expected_outcome": {
                    "kind": "python_py_compile",
                    "path": f"package/module_{index:03d}.py",
                    "expected_exit_code": 0,
                },
            }
        )
    for index in range(20):
        payload["cases"].append(
            {
                "case_id": f"control-{index:03d}",
                "kind": "wrong_workspace",
                "split": "dev" if index < 4 else "heldout",
                "repo": "repo-a",
                "query": f"Control query {index:03d} should abstain.",
                "expected_behavior": "abstain",
            }
        )
    return _refresh_checksum(payload)


def _repo(stack: str) -> dict:
    return {
        "remote": "https://github.com/example/project",
        "commit": "a" * 40,
        "license": "MIT",
        "stack": stack,
    }


def _refresh_checksum(payload: dict) -> dict:
    refreshed = copy.deepcopy(payload)
    refreshed["sha256"] = bench._sha256(  # noqa: SLF001 - benchmark checksum guard.
        {key: value for key, value in refreshed.items() if key != "sha256"}
    )
    return refreshed
