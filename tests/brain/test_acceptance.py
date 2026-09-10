"""D1 evidence must preserve missing execution and exact source boundaries."""

import pytest


def test_acceptance_report_does_not_admit_unexecuted_user_pilots():
    from scripts.verify_brain_d1 import summarize_gates

    report = summarize_gates({"F01": "pass", "F12": "fail"})
    assert report["d1_status"] == "incomplete"
    assert report["mass_release"] == "not_evaluated"
    assert report["scientific_breakthrough"] == "not_established"
    assert report["gates"]["F02"] == "unexecuted"
    assert set(report["gates"]) == {f"F{i:02d}" for i in range(1, 15)}
    assert report["remaining_stages"] == {
        "D2": "unexecuted",
        "D3": "unexecuted",
        "D4": "unexecuted",
    }


@pytest.mark.parametrize("missing", [f"F{i:02d}" for i in range(1, 15)])
def test_each_required_gate_is_load_bearing(missing):
    from scripts.verify_brain_d1 import summarize_gates

    gates = {f"F{i:02d}": "pass" for i in range(1, 15)}
    assert summarize_gates(gates)["d1_status"] == "pass"
    for state in ("fail", "unexecuted"):
        assert summarize_gates({**gates, missing: state})["d1_status"] == "incomplete"
    with pytest.raises(ValueError):
        summarize_gates({**gates, missing: True})


def _execution():
    from scripts.verify_brain_d1 import REQUIRED_CASES

    cases = sorted({case for values in REQUIRED_CASES.values() for case in values})
    cases += ["tests/test_api.py::test_legacy_example"]
    return {
        "collected": cases,
        "outcomes": dict.fromkeys(cases, "pass"),
        "exit_code": 0,
        "full_suite": True,
    }


@pytest.mark.parametrize("change", ["sha", "dirty", "manifest", "expected"])
def test_same_sha_binding_rejects_changed_or_dirty_source(change):
    from scripts.verify_brain_d1 import build_report

    before = {"sha": "a" * 40, "clean": True, "manifest_sha256": "b" * 64}
    after = dict(before)
    expected = before["sha"]
    if change == "sha":
        after["sha"] = "c" * 40
    elif change == "dirty":
        after["clean"] = False
    elif change == "manifest":
        after["manifest_sha256"] = "c" * 64
    else:
        expected = "c" * 40
    report = build_report(before, after, expected, _execution())
    assert report["source_binding"] == "fail"
    assert report["d1_status"] == "incomplete"


def test_browser_variation_and_mcp_cannot_skip_into_acceptance():
    from scripts.verify_brain_d1 import REQUIRED_CASES, build_report

    source = {"sha": "a" * 40, "clean": True, "manifest_sha256": "b" * 64}
    for case in REQUIRED_CASES["F12"]:
        execution = _execution()
        execution["outcomes"][case] = "unexecuted"
        report = build_report(source, source, source["sha"], execution)
        assert report["gates"]["F12"] == "unexecuted"
        assert report["d1_status"] == "incomplete"


def test_missing_result_failure_and_partial_suite_are_not_passes():
    from scripts.verify_brain_d1 import REQUIRED_CASES, build_report

    source = {"sha": "a" * 40, "clean": True, "manifest_sha256": "b" * 64}
    execution = _execution()
    case = REQUIRED_CASES["F01"][0]
    del execution["outcomes"][case]
    assert (
        build_report(source, source, source["sha"], execution)["gates"]["F01"]
        == "unexecuted"
    )
    execution = _execution()
    execution["outcomes"][case] = "fail"
    assert (
        build_report(source, source, source["sha"], execution)["gates"]["F01"] == "fail"
    )
    execution = _execution()
    execution["full_suite"] = False
    assert (
        build_report(source, source, source["sha"], execution)["gates"]["F13"]
        == "unexecuted"
    )


@pytest.mark.parametrize(
    "gate,case",
    [
        ("F08", "test_private_reported_candidate_retains_identity_and_evidence"),
        ("F13", "test_legacy_runtime_does_not_derive_reported_procedure"),
    ],
)
def test_private_candidate_identity_is_required_evidence(gate, case):
    from scripts.verify_brain_d1 import build_report

    source = {"sha": "a" * 40, "clean": True, "manifest_sha256": "b" * 64}
    execution = _execution()
    case = "tests/brain/test_private_runtime.py::" + case
    execution["outcomes"][case] = "fail"
    assert (
        build_report(source, source, source["sha"], execution)["gates"][gate] == "fail"
    )
    execution["collected"] = [node for node in execution["collected"] if node != case]
    execution["outcomes"].pop(case, None)
    assert (
        build_report(source, source, source["sha"], execution)["gates"][gate]
        == "unexecuted"
    )


def test_pytest_collector_keeps_teardown_failure_and_never_serializes_failure_text():
    from types import SimpleNamespace
    from scripts.verify_brain_d1 import ExecutionCollector

    collector = ExecutionCollector()
    for phase, failed, skipped in [("call", False, False), ("teardown", True, False)]:
        collector.pytest_runtest_logreport(
            SimpleNamespace(
                nodeid="tests/example.py::test_one",
                when=phase,
                failed=failed,
                skipped=skipped,
                longrepr="SECRET fixture text",
            )
        )
    assert collector.outcomes == {"tests/example.py::test_one": "fail"}
    assert "SECRET" not in repr(collector.__dict__)


def test_optional_skip_allowlist_requires_actual_absence_and_exact_case(monkeypatch):
    import importlib.metadata
    from scripts.verify_brain_d1 import classify_skip

    case = "tests/test_chroma_migration_example.py"
    reason = "could not import 'chromadb': No module named 'chromadb'"
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "installed")
    assert classify_skip(case, reason) == "unexpected_skip"

    def absent(_):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", absent)
    assert classify_skip(case, reason) == "missing_optional_distribution:chromadb"
    assert classify_skip(case, "broken native binary") == "unexpected_skip"
    assert classify_skip("tests/brain/test_new.py", reason) == "unexpected_skip"


def test_protected_owner_key_is_mandatory_in_each_relevant_gate():
    from scripts.verify_brain_d1 import GATE_MODULES, REQUIRED_CASES

    case = (
        "tests/brain/test_credential_file.py::"
        "test_owner_key_has_native_private_permissions"
    )
    for gate in ("F10", "F11", "F14"):
        assert "credential_file" in GATE_MODULES[gate].split()
        assert case in REQUIRED_CASES[gate]


def test_collection_skip_and_error_are_retained_without_raw_messages(monkeypatch):
    from types import SimpleNamespace
    from scripts.verify_brain_d1 import ExecutionCollector

    collector = ExecutionCollector()
    collector.pytest_collectreport(
        SimpleNamespace(
            nodeid="tests/missing.py",
            failed=False,
            skipped=True,
            longrepr="SECRET unsupported omission",
        )
    )
    collector.pytest_collectreport(
        SimpleNamespace(nodeid="tests/broken.py", failed=True, skipped=False)
    )
    assert collector.collected == ["tests/missing.py"]
    assert collector.skips == {"tests/missing.py": "unexpected_skip"}
    assert collector.collection_errors == 1
    assert "SECRET" not in repr(collector.__dict__)


def test_optional_skip_remains_partial_unknown_skip_blocks_compatibility():
    from scripts.verify_brain_d1 import build_report

    source = {"sha": "a" * 40, "clean": True, "manifest_sha256": "b" * 64}
    execution = _execution()
    node = "tests/test_chroma_migration_example.py"
    execution["collected"].append(node)
    execution["outcomes"][node] = "unexecuted"
    execution["skips"] = {node: "missing_optional_distribution:chromadb"}
    report = build_report(source, source, source["sha"], execution)
    assert report["gates"]["F13"] == "pass"
    assert report["optional_coverage"]["status"] == "partial"
    assert report["optional_coverage"]["unexecuted_count"] == 1
    execution["skips"][node] = "unexpected_skip"
    assert (
        build_report(source, source, source["sha"], execution)["gates"]["F13"]
        == "unexecuted"
    )


def test_collection_error_cannot_be_hidden_by_zero_exit_code():
    from scripts.verify_brain_d1 import build_report

    source = {"sha": "a" * 40, "clean": True, "manifest_sha256": "b" * 64}
    execution = _execution()
    execution["collection_errors"] = 1
    assert (
        build_report(source, source, source["sha"], execution)["d1_status"]
        == "incomplete"
    )


def test_cli_rejects_mismatched_actual_source_without_executing_tests(tmp_path):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "rejected.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_brain_d1.py",
            "--expected-source-sha",
            "0" * 40,
            "--output",
            str(output),
        ],
        cwd=root,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(output.read_text())
    assert report["source_binding"] == "fail"
    assert report["execution"]["collected"] == []
    assert report["d1_status"] == "incomplete"


def test_upstream_exception_requires_exact_node_reason_and_absent_path(
    tmp_path, monkeypatch
):
    from scripts import verify_brain_d1 as runner

    root = tmp_path / "work" / "checkout"
    root.mkdir(parents=True)
    monkeypatch.setattr(runner, "ROOT", root)
    node = "tests/test_scientific_memops_v6_validation.py::test_frozen_memops_validation_subjects_and_operation_matrix_are_untouched"
    reason = "official MemOps upstream is not included in this repository"
    assert runner.classify_skip(node, reason) == "missing_optional_upstream:memops"
    assert runner.classify_skip(node, "corrupt checkout") == "unexpected_skip"
    assert runner.classify_skip(node + "[extra]", reason) == "unexpected_skip"
    upstream = tmp_path / "scientific-evidence" / "upstreams" / "memops"
    upstream.mkdir(parents=True)
    assert runner.classify_skip(node, reason) == "unexpected_skip"
