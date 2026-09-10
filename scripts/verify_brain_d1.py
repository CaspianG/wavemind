"""Execute source-bound D1 engineering checks; never infer user/release evidence.

Run from a clean checkout. This invokes existing real service, HTTP, stdio MCP and
browser tests, including four synthetic P1/B1 journeys. Only sanitized execution
metadata belongs in the JSON artifact; pytest diagnostics stay in the local log.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
GATES = tuple(f"F{i:02d}" for i in range(1, 15))


def _case(module, name):
    return f"tests/brain/test_{module}.py::test_{name}"


REQUIRED_CASES = {
    "F01": [
        _case("store_access", "restart_membership_is_exact_and_readers_cannot_grant"),
        _case("source_citations", "actual_stdio_listing_and_startup_maintenance"),
    ],
    "F02": [
        _case("sources", "preview_commit_retry_and_exact_citation"),
        _case("experience_bridge", "crash_after_runtime_commit_is_idempotent"),
    ],
    "F03": [
        _case("reconcile", "correction_arrival_order_preserves_half_open_history"),
        _case(
            "experience_bridge",
            "corrected_basis_learns_after_three_new_runs_and_keeps_lineage",
        ),
    ],
    "F04": [_case("reconcile", "competing_values_do_not_choose_latest_import")],
    "F05": [_case("source_citations", "pages_versions_restart_and_live_authority")],
    "F06": [
        _case("store_access", "source_acl_is_exact_all_dependencies_required_and_live"),
        _case("mcp_cli", "two_live_mcp_connections_recheck_revoke_and_source_cap"),
    ],
    "F07": [
        _case(
            "experience_bridge",
            "lineage_also_ordinary_dependency_cannot_bypass_time_or_recheck",
        ),
        _case("source_citations", "actual_stdio_listing_and_startup_maintenance"),
        _case("maintenance", "retry_real_queued_outcome_and_await_inflight_shutdown"),
    ],
    "F08": [
        _case(
            "private_runtime",
            "private_reported_candidate_retains_identity_and_evidence",
        ),
        _case("experience_bridge", "owner_attestation_does_not_activate_one_run"),
        _case(
            "experience_bridge",
            "corrected_basis_learns_after_three_new_runs_and_keeps_lineage",
        ),
        _case("source_citations", "actual_stdio_listing_and_startup_maintenance"),
    ],
    "F09": [_case("experience_bridge", "delete_purges_every_private_copy")],
    "F10": [
        _case(
            "portability", "current_history_pending_gate_survives_restore_and_restart"
        ),
        _case("portability", "current_deletion_overrides_stale_backup"),
    ],
    "F11": [
        _case("sources", "literal_count_input_and_extracted_boundaries"),
        _case("mcp_cli", "cli_refuses_linked_profile_and_credential_file"),
    ],
    "F12": [
        _case("ui_scenarios", f"real_owner_browser_journey[{scenario}-{variant}]")
        for scenario in ("P1", "B1")
        for variant in (0, 1)
    ]
    + [
        _case("mcp_cli", "two_live_mcp_connections_recheck_revoke_and_source_cap"),
        _case("source_citations", "actual_stdio_listing_and_startup_maintenance"),
        _case(
            "ui_scenarios",
            "brain_transition_rejects_stale_mutation_and_waits_for_complete_reads[mutation]",
        ),
        _case(
            "ui_scenarios",
            "brain_transition_rejects_stale_mutation_and_waits_for_complete_reads[input]",
        ),
    ],
    "F13": [
        _case("private_runtime", "legacy_runtime_does_not_derive_reported_procedure"),
        "tests/test_api_process_persistence.py::test_api_persists_10_memories_across_process_restart",
        "tests/test_cli_smoke.py::test_module_cli_remember_query_stats_and_backup",
        "tests/test_mcp_server.py::test_mcp_stdio_persists_across_restart_and_isolates_namespaces",
    ],
    "F14": [
        _case(
            "experience_bridge", "reported_steps_are_state_events_never_tool_execution"
        ),
        _case("mcp_cli", "cli_init_restart_doctor_and_loopback_gate"),
    ],
}

# Every collected test in these files is required, not only the named sentinels.
GATE_MODULES = {
    "F01": "store_access sources portability maintenance source_citations ui_scenarios",
    "F02": "sources context experience_bridge maintenance",
    "F03": "reconcile experience_bridge ui_scenarios",
    "F04": "reconcile context ui_scenarios",
    "F05": "sources source_citations context http mcp_cli",
    "F06": "store_access sources reconcile context experience_bridge portability http mcp_cli source_citations ui_scenarios",
    "F07": "sources reconcile context experience_bridge maintenance source_citations ui_scenarios",
    "F08": "context experience_bridge private_runtime maintenance source_citations ui_scenarios",
    "F09": "sources reconcile experience_bridge portability ui_scenarios",
    "F10": "portability mcp_cli",
    "F11": "sources http mcp_cli ui_scenarios",
    "F12": "ui_scenarios mcp_cli source_citations",
    "F13": "private_runtime",
    "F14": "sources context experience_bridge http mcp_cli ui_scenarios",
}

# Closed baseline exceptions. Installed-but-broken distributions are NOT absent.
# Each omitted case remains unexecuted even when required compatibility passes.
OPTIONAL_SKIPS = {
    "tests/test_chroma_migration_example.py": ("chromadb", "chromadb"),
    "tests/test_scientific_memoryagentbench.py": ("pyarrow", "pyarrow"),
    "tests/test_scientific_splits.py": ("pyarrow", "pyarrow"),
    "tests/test_indexes_encoders.py::test_annoy_vector_index_returns_cosine_neighbors_with_filters": (
        "annoy",
        "annoy",
    ),
    "tests/test_multimodal_local.py::test_clip_3d_backend_encodes_xyz_rgb_pointclouds": (
        "torch",
        "torch",
    ),
    "tests/test_official_provider_contracts.py::test_openai_agents_runtime_session_protocol": (
        "openai-agents",
        "agents.memory",
    ),
    "tests/test_official_provider_contracts.py::test_anthropic_tool_definition_matches_official_typed_dict": (
        "anthropic",
        "anthropic.types.beta",
    ),
    "tests/test_official_provider_contracts.py::test_langgraph_compiles_and_invokes_experience_node": (
        "langgraph",
        "langgraph.graph",
    ),
    "tests/test_onboarding.py::test_docker_starter_has_valid_compose_config": (
        "docker_cli",
        "Docker CLI is not installed",
    ),
    "tests/test_production_streaming_load_benchmark.py::test_streaming_load_faiss_ivfpq_smoke": (
        "faiss-cpu",
        "faiss",
    ),
    "tests/test_production_streaming_load_benchmark.py::test_streaming_load_faiss_ivfpq_resumes_atomic_partial_snapshot": (
        "faiss-cpu",
        "faiss",
    ),
    "tests/test_public_memory_competitors.py::test_real_langgraph_store_adapter": (
        "langgraph",
        "langgraph.store.memory",
    ),
    "tests/test_scientific_baselines.py::test_real_baseline_backends_execute_same_embedding_contract": (
        "mem0ai",
        "mem0",
    ),
    "tests/test_scientific_baselines.py::test_real_mem0_import_is_pinned_to_installed_distribution": (
        "mem0ai",
        "mem0",
    ),
    "tests/test_vectordbbench_dataset.py::test_vectordbbench_dataset_writes_parquet_when_pyarrow_is_available": (
        "pyarrow",
        "pyarrow",
    ),
    "tests/test_workspace_experience.py::test_workspace_http_rejects_registry_file_and_symlink_escape": (
        "windows_symlink_privilege",
        "WinError 1314",
    ),
}

# Existing scientific decorators, absent on an ordinary CI checkout. These
# remain unexecuted scientific coverage, never a claim that research passed.
OPTIONAL_UPSTREAM_SKIPS = {
    "tests/test_scientific_frozen_lexical_index.py::test_indexed_prototype_matches_v31_backend_across_worker_threads": "longmemeval-v2",
    "tests/test_scientific_longmemeval_v2_backend.py::test_registered_backend_is_gold_blind_atomic_and_production_empty": "longmemeval-v2",
    "tests/test_scientific_memops_v6_validation.py::test_frozen_memops_validation_subjects_and_operation_matrix_are_untouched": "memops",
    "tests/test_scientific_v19_final_harnesses.py::test_v19_longmemeval_backend_registers_exact_candidate_without_gold": "longmemeval-v2",
    "tests/test_scientific_v31_final_harnesses.py::test_v31_longmemeval_backend_registers_exact_candidate_without_gold": "longmemeval-v2",
    "tests/test_scientific_v31_final_harnesses.py::test_v31_longmemeval_backend_serializes_shared_queries_and_keeps_metadata_local": "longmemeval-v2",
    "tests/test_scientific_v31_longmem_binary_judgement_compatibility.py::test_binary_compatibility_wraps_exact_official_parser_without_changing_existing_forms": "longmemeval-v2",
}


def upstream_absence():
    return {
        name: not (
            ROOT.parents[1] / "scientific-evidence" / "upstreams" / name
        ).exists()
        for name in ("longmemeval-v2", "memops")
    }


def classify_skip(nodeid, reason):
    if nodeid in OPTIONAL_UPSTREAM_SKIPS:
        upstream = OPTIONAL_UPSTREAM_SKIPS[nodeid]
        label = "LongMemEval v2" if upstream == "longmemeval-v2" else "MemOps"
        expected = f"official {label} upstream is not included in this repository"
        if expected in reason and upstream_absence()[upstream]:
            return f"missing_optional_upstream:{upstream}"
        return "unexpected_skip"
    dependency, marker = OPTIONAL_SKIPS.get(nodeid, (None, None))
    if dependency is None or marker not in reason:
        return "unexpected_skip"
    if dependency == "windows_symlink_privilege":
        return (
            dependency
            if os.name == "nt" and "symlink creation unavailable" in reason
            else "unexpected_skip"
        )
    if dependency == "docker_cli":
        return (
            "missing_docker_cli"
            if shutil.which("docker") is None
            else "unexpected_skip"
        )
    if f"could not import '{marker}'" not in reason:
        return "unexpected_skip"
    try:
        importlib.metadata.version(dependency)
    except importlib.metadata.PackageNotFoundError:
        return f"missing_optional_distribution:{dependency}"
    return "unexpected_skip"


def summarize_gates(gates):
    if any(
        key not in GATES or value not in ("pass", "fail", "unexecuted")
        for key, value in gates.items()
    ):
        raise ValueError("Invalid gate status")
    values = {key: gates.get(key, "unexecuted") for key in GATES}
    return {
        "gates": values,
        "d1_status": "pass"
        if all(value == "pass" for value in values.values())
        else "incomplete",
        "mass_release": "not_evaluated",
        "scientific_breakthrough": "not_established",
        "remaining_stages": dict.fromkeys(("D2", "D3", "D4"), "unexecuted"),
    }


def _matches(node, required):
    return node == required or node.startswith(required + "[")


def build_report(before, after, expected_sha, execution):
    collected = execution.get("collected", [])
    outcomes = execution.get("outcomes", {})
    skips = execution.get("skips", {})
    gates, mapping = {}, {}
    for gate in GATES:
        modules = {
            f"tests/brain/test_{name}.py" for name in GATE_MODULES.get(gate, "").split()
        }
        selected = [
            node
            for node in collected
            if (gate == "F13" and not node.startswith("tests/brain/"))
            or node.split("::")[0] in modules
        ]
        required = REQUIRED_CASES[gate]
        missing = [
            node
            for node in required
            if not any(_matches(item, node) for item in collected)
        ]
        values = [outcomes.get(node, "unexecuted") for node in selected]
        if gate == "F13":
            # Optional exceptions never excuse any named mandatory legacy case.
            values = [
                outcomes.get(node, "unexecuted")
                for node in selected
                if node not in skips
                or skips[node] == "unexpected_skip"
                or any(_matches(node, item) for item in required)
            ]
        status = (
            "fail"
            if "fail" in values
            else "unexecuted"
            if missing or not values or "unexecuted" in values
            else "pass"
        )
        if gate == "F13" and (
            not execution.get("full_suite")
            or any(reason == "unexpected_skip" for reason in skips.values())
        ):
            status = "unexecuted" if status != "fail" else status
        gates[gate] = status
        mapping[gate] = {
            "required_cases": required,
            "executed_cases": selected,
            "missing_cases": missing,
        }
    if execution.get("exit_code") != 0 or execution.get("collection_errors", 0):
        gates = {
            gate: "fail" if status != "unexecuted" else status
            for gate, status in gates.items()
        }
    bound = (
        before == after
        and before.get("clean") is True
        and before.get("sha") == expected_sha
        and len(expected_sha or "") == 40
    )
    report = {
        "schema": "wavemind.brain_d1_evidence.v1",
        "source_sha": before.get("sha"),
        "expected_source_sha": expected_sha,
        "source_binding": "pass" if bound else "fail",
        "source_before": before,
        "source_after": after,
        **summarize_gates(gates),
        "gate_evidence": mapping,
        "execution": execution,
        "optional_coverage": {
            "status": "partial" if skips else "executed",
            "unexecuted_count": len(skips),
            "classifications": dict(Counter(skips.values())),
        },
        "claim_boundary": "Synthetic nonsecret engineering examples; no connected model or measured user benefit. D1 is not CI/SAST, D2 installation, D3 deployment, or D4 user/scientific admission.",
    }
    if not bound:
        report["d1_status"] = "incomplete"
    return report


class ExecutionCollector:
    def __init__(self):
        self.collected = []
        self.outcomes = {}
        self.skips = {}
        self.phases = {}
        self.collection_errors = 0
        self.warning_categories = Counter()

    def pytest_collection_finish(self, session):
        self.collected.extend(item.nodeid for item in session.items)

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors += 1
        if report.skipped:
            self.collected.append(report.nodeid)
            self.outcomes[report.nodeid] = "unexecuted"
            self.skips[report.nodeid] = classify_skip(
                report.nodeid, str(report.longrepr)
            )

    def pytest_runtest_logreport(self, report):
        self.phases.setdefault(report.nodeid, {})[report.when] = (
            "fail" if report.failed else "unexecuted" if report.skipped else "pass"
        )
        if self.outcomes.get(report.nodeid) == "fail":
            return
        if report.failed:
            self.outcomes[report.nodeid] = "fail"
        elif report.skipped:
            self.outcomes[report.nodeid] = "unexecuted"
            self.skips[report.nodeid] = classify_skip(
                report.nodeid, str(report.longrepr)
            )
        elif report.when == "call":
            self.outcomes[report.nodeid] = "pass"

    def pytest_warning_recorded(self, warning_message, when, nodeid, location):
        self.warning_categories[warning_message.category.__name__] += 1


def source_snapshot():
    def git(*args):
        return subprocess.check_output(["git", "-C", str(ROOT), *args])

    manifest = {}
    for raw in git("ls-files", "-z").split(b"\0"):
        if raw:
            name = raw.decode("utf-8")
            path = ROOT / name
            manifest[name] = (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file()
                else "missing"
            )
    return {
        "sha": git("rev-parse", "HEAD").decode().strip(),
        "clean": not git("status", "--porcelain", "--untracked-files=normal").strip(),
        "manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest(),
        "tracked_files": manifest,
        "optional_upstream_absence": upstream_absence(),
    }


def runtime_versions():
    versions = {"python": platform.python_version(), "platform": platform.system()}
    for name in ("pytest", "mcp", "fastapi", "pydantic", "uvicorn"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "unavailable"
    node = os.environ.get("BRAIN_UI_NODE") or shutil.which("node")
    versions["node"] = "unavailable"
    versions["playwright"] = "unavailable"
    versions["browser"] = "unavailable"
    if node:
        script = """(async()=>{
          const path=process.env.BRAIN_UI_PLAYWRIGHT||'playwright';
          const p=require(path), version=require(path+'/package.json').version;
          const browser=await p.chromium.launch({headless:true,executablePath:process.env.BRAIN_UI_CHROME||undefined});
          try {console.log(JSON.stringify({node:process.version,playwright:version,browser:browser.version()}));}
          finally {await browser.close();}
        })().catch(()=>process.exitCode=1);"""
        try:
            result = subprocess.run(
                [node, "-e", script], capture_output=True, text=True, timeout=20
            )
            if result.returncode == 0:
                observed = json.loads(result.stdout)
                for key in ("node", "playwright", "browser"):
                    versions[key] = observed[key]
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
            pass
    return versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--brain-only",
        action="store_true",
        help="Diagnostic mode; F13 stays unexecuted",
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    # User pytest selection flags cannot silently turn this into a partial suite.
    os.environ.pop("PYTEST_ADDOPTS", None)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    before = source_snapshot()
    collector = ExecutionCollector()
    execution = {
        "collected": [],
        "outcomes": {},
        "skips": {},
        "exit_code": None,
        "full_suite": not args.brain_only,
    }
    started = time.monotonic()
    if before["clean"] and before["sha"] == args.expected_source_sha:
        import pytest

        temp = Path(tempfile.gettempdir()) / ("wmb-" + uuid.uuid4().hex)
        print(f"D1 owned test evidence: {temp}", flush=True)
        exit_code = int(
            pytest.main(
                [
                    "tests/brain" if args.brain_only else "tests",
                    "-q",
                    "-ra",
                    "--tb=short",
                    "-p",
                    "no:cacheprovider",
                    "--basetemp",
                    str(temp),
                ],
                plugins=[collector],
            )
        )
        execution.update(
            collected=sorted(collector.collected),
            outcomes=dict(sorted(collector.outcomes.items())),
            skips=dict(sorted(collector.skips.items())),
            exit_code=exit_code,
            collection_errors=collector.collection_errors,
            warning_categories=dict(collector.warning_categories),
            phases=collector.phases,
            counts=dict(Counter(collector.outcomes.values())),
        )
    after = source_snapshot()
    report = build_report(before, after, args.expected_source_sha, execution)
    report["versions"] = runtime_versions()
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "source_sha",
                    "source_binding",
                    "d1_status",
                    "gates",
                    "optional_coverage",
                )
            }
        )
    )
    return 0 if report["d1_status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
