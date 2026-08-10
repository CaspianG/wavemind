from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKSPACE_EXPERIENCE_ADMISSION_SCHEMA = "wavemind.workspace_experience_admission.v1"
WORKSPACE_EXPERIENCE_PROTOCOL_REVISION = "workspace-experience-v1-frozen-20260810"
WORKSPACE_EXPERIENCE_PROTOCOL_SHA256 = "fa2ebc36799b44ff54e74120da7dab3a475d40461a4963872069f5905beeb590"
V4_INVALID_REASONS = [
    "clean_onboarding_seconds was hardcoded instead of measured from a clean subprocess flow",
    "static baseline can collapse to zero positive success and is not the strongest static comparator",
    "positive task success accepts outcome-kind matches without exact case/procedure validation",
    "cross-client parity reopens the same Python manager instead of cross-surface client A to restart to client B replay",
]


def workspace_experience_protocol_manifest() -> dict[str, Any]:
    manifest = {
        "revision": WORKSPACE_EXPERIENCE_PROTOCOL_REVISION,
        "dataset": {
            "repositories": 3,
            "technology_stacks_min": 2,
            "workflow_gotcha_cases_min": 60,
            "negative_conflict_stale_controls_min": 20,
            "development_split": "predeclared and allowed for implementation tuning",
            "held_out_split": "untouched after protocol freeze",
            "answer_leakage": "ids, filenames, metadata, and prebuilt packets forbidden",
        },
        "thresholds": {
            "task_success_lift_pp_min": 15.0,
            "repeated_known_error_reduction_min": 0.50,
            "context_reduction_min": 0.30,
            "false_procedure_injection_max": 0.01,
            "unverified_injection": 0,
            "workspace_namespace_leakage": 0,
            "mandatory_event_capture_min": 0.99,
            "cross_client_citation_state_parity": 1.00,
            "packet_selection_p95_ms_max": 100.0,
            "packet_selection_p99_ms_max": 250.0,
            "clean_onboarding_seconds_max": 300.0,
        },
        "comparison_modes": [
            "no_experience",
            "static_raw_trace_retrieval",
            "wavemind_verified_workspace_experience",
        ],
        "claim_boundary": (
            "Local, provider-neutral workspace experience proof. No GPU, paid API, "
            "private client history, universal model-quality, or external service claim."
        ),
    }
    digest = _sha256(manifest)
    if digest != WORKSPACE_EXPERIENCE_PROTOCOL_SHA256:
        raise RuntimeError(
            "workspace experience protocol manifest changed without updating the frozen hash"
        )
    return {**manifest, "sha256": digest}


def evaluate_workspace_experience_admission_matrix(
    *,
    root: str | Path = ".",
    baseline_source_sha: str | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    benchmark_status, benchmark_details = _benchmark_status(root_path)
    v5_status, v5_details = _v5_benchmark_status(root_path)
    admission_status = "blocked" if benchmark_status == "failed" else "missing"
    rows = [
        _row(
            "baseline-gap-audit",
            "Gap audit, protocol manifest, and source manifest exist before metric tuning.",
            "implemented",
            "benchmarks/workspace_experience_admission_matrix.json",
            "tests/test_workspace_experience_admission.py",
        ),
        _row(
            "workspace-identity-isolation",
            "Stable workspace identity and tenant/user/workspace isolation.",
            "implemented",
            "tests/test_workspace_experience.py",
            "tests/test_workspace_experience.py",
        ),
        _row(
            "provider-neutral-capture-contract",
            "Python, HTTP, MCP, retries, ordering, redaction, and crash/restart recovery.",
            "implemented",
            "tests/test_workspace_experience.py",
            "tests/test_workspace_experience.py",
        ),
        _row(
            "verified-runbook-compiler",
            "Versioned procedure/workflow/gotcha runbook JSON and Markdown with provenance.",
            "implemented",
            "wavemind/workspace_experience.py",
            "tests/test_workspace_experience.py",
        ),
        _row(
            "human-review-control",
            "Candidate queue, diff, approve, reject, rollback, protected deletion, audit trail.",
            "implemented",
            "wavemind/workspace_experience.py",
            "tests/test_workspace_experience.py",
        ),
        _row(
            "cross-agent-portability",
            "Client A to restart to client B replay and checksummed portable bundle parity.",
            "implemented",
            "wavemind/workspace_experience.py",
            "tests/test_workspace_experience.py",
        ),
        _row(
            "useful-experience-packet",
            "Minimal cited packet with abstain and stale/conflict/unverified exclusion reasons.",
            "implemented",
            "wavemind/workspace_experience.py",
            "tests/test_workspace_experience.py",
        ),
        _row(
            "workspace-onboarding",
            "workspace init, doctor, status, review, packet, export/import, MCP config.",
            "implemented",
            "docs/WORKSPACE_EXPERIENCE_QUICKSTART.md",
            "tests/test_workspace_experience.py",
        ),
        _row(
            "historical-v3-checksum-selection-experiment",
            "Historical failed v3 checksum-selection experiment; not real-work proof.",
            benchmark_status,
            "benchmarks/workspace_experience_benchmark_results.json",
            "tests/test_workspace_experience_benchmark.py",
            details=benchmark_details,
        ),
        _row(
            "frozen-real-work-benchmark-v4",
            "Historical invalid v4 protocol; not admission evidence.",
            "failed",
            "benchmarks/workspace_experience_v4_manifest.json",
            "tests/test_workspace_experience_v4_benchmark.py",
            details={
                "methodology_status": "historical_invalid_not_admission_evidence",
                "source_sha": _git_sha(root_path),
                "protocol_commit": "8214d58",
                "invalid_reasons": V4_INVALID_REASONS,
                "heldout_status": "viewed_invalid_not_untouched",
                "next_protocol": "v5",
            },
        ),
        _row(
            "frozen-real-work-benchmark-v5",
            "New independent real workflow benchmark with exact case/procedure success, strongest static baseline, measured onboarding, and cross-surface replay.",
            v5_status,
            "benchmarks/workspace_experience_v5_benchmark_results.json",
            "tests/test_workspace_experience_v5_benchmark.py",
            details=v5_details,
        ),
        _row(
            "workspace-experience-admission",
            "Exact-SHA JSON/Markdown admission with all mandatory rows green.",
            admission_status,
            "benchmarks/workspace_experience_admission_results.json",
            "tests/test_workspace_experience_admission.py",
        ),
        _row(
            "safe-product-regression",
            "Safe Product admission remains admitted on the same final source SHA.",
            "required_current",
            "benchmarks/safe_product_admission_results.json",
            ".github/workflows/safe-product.yml",
        ),
    ]
    complete = all(row["status"] == "implemented" for row in rows)
    failed = any(row["status"] == "failed" for row in rows)
    return {
        "schema": WORKSPACE_EXPERIENCE_ADMISSION_SCHEMA,
        "status": "admitted" if complete else ("blocked" if failed else "gap_audit"),
        "admitted": complete,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_source_sha": baseline_source_sha,
        "source_sha": _git_sha(root_path),
        "protocol": workspace_experience_protocol_manifest(),
        "source_manifest": _source_manifest(root_path),
        "summary": {
            "implemented": sum(row["status"] == "implemented" for row in rows),
            "partial": sum(row["status"] == "partial" for row in rows),
            "missing": sum(row["status"] == "missing" for row in rows),
            "failed": sum(row["status"] == "failed" for row in rows),
            "blocked": sum(row["status"] == "blocked" for row in rows),
            "required_current": sum(row["status"] == "required_current" for row in rows),
            "total": len(rows),
        },
        "rows": rows,
        "claim_boundary": (
            "This matrix is a Goal 7 gap audit, not final production admission."
        ),
    }


def render_workspace_experience_admission_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Workspace Experience Admission Matrix",
        "",
        f"- Status: `{payload['status']}`",
        f"- Source SHA: `{payload.get('source_sha')}`",
        f"- Protocol: `{payload['protocol']['revision']}`",
        f"- Protocol SHA-256: `{payload['protocol']['sha256']}`",
        "",
        "| Row | Status | Artifact | Test |",
        "|---|---|---|---|",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| `{row['id']}` | `{row['status']}` | `{row['artifact']}` | `{row['test']}` |"
        )
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            payload["claim_boundary"],
        ]
    )
    return "\n".join(lines) + "\n"


def write_workspace_experience_admission_matrix(
    *,
    root: str | Path = ".",
    output: str | Path = "benchmarks/workspace_experience_admission_matrix.json",
    markdown_output: str | Path = "benchmarks/WORKSPACE_EXPERIENCE_ADMISSION_MATRIX.md",
    baseline_source_sha: str | None = None,
) -> dict[str, Any]:
    payload = evaluate_workspace_experience_admission_matrix(
        root=root,
        baseline_source_sha=baseline_source_sha,
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path = Path(markdown_output)
    markdown_path.write_text(
        render_workspace_experience_admission_markdown(payload),
        encoding="utf-8",
    )
    return payload


def _row(
    row_id: str,
    requirement: str,
    status: str,
    artifact: str,
    test: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "id": row_id,
        "requirement": requirement,
        "status": status,
        "artifact": artifact,
        "test": test,
    }
    if details:
        row["details"] = details
    return row


def _benchmark_status(root: Path) -> tuple[str, dict[str, Any]]:
    path = root / "benchmarks" / "workspace_experience_benchmark_results.json"
    if not path.exists():
        return "missing", {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("split") != "heldout":
        return "failed", {"reason": "benchmark result is not held-out evidence"}
    metrics = payload.get("metrics", {}).get("admission", {})
    thresholds = workspace_experience_protocol_manifest()["thresholds"]
    failed_gates: list[str] = []
    if float(metrics.get("task_success_lift_pp", -1.0)) < thresholds["task_success_lift_pp_min"]:
        failed_gates.append("task_success_lift_pp")
    if (
        float(metrics.get("repeated_known_error_reduction", -1.0))
        < thresholds["repeated_known_error_reduction_min"]
    ):
        failed_gates.append("repeated_known_error_reduction")
    if float(metrics.get("context_reduction", -1.0)) < thresholds["context_reduction_min"]:
        failed_gates.append("context_reduction")
    if (
        float(metrics.get("false_procedure_injection", 1.0))
        > thresholds["false_procedure_injection_max"]
    ):
        failed_gates.append("false_procedure_injection")
    if int(metrics.get("unverified_injection", -1)) != thresholds["unverified_injection"]:
        failed_gates.append("unverified_injection")
    if (
        int(metrics.get("workspace_namespace_leakage", -1))
        != thresholds["workspace_namespace_leakage"]
    ):
        failed_gates.append("workspace_namespace_leakage")
    if (
        float(metrics.get("mandatory_event_capture", -1.0))
        < thresholds["mandatory_event_capture_min"]
    ):
        failed_gates.append("mandatory_event_capture")
    if (
        float(metrics.get("cross_client_citation_state_parity", -1.0))
        != thresholds["cross_client_citation_state_parity"]
    ):
        failed_gates.append("cross_client_citation_state_parity")
    if (
        float(metrics.get("packet_selection_p95_ms", 999999.0))
        > thresholds["packet_selection_p95_ms_max"]
    ):
        failed_gates.append("packet_selection_p95_ms")
    if (
        float(metrics.get("packet_selection_p99_ms", 999999.0))
        > thresholds["packet_selection_p99_ms_max"]
    ):
        failed_gates.append("packet_selection_p99_ms")
    if (
        float(metrics.get("clean_onboarding_seconds", 999999.0))
        > thresholds["clean_onboarding_seconds_max"]
    ):
        failed_gates.append("clean_onboarding_seconds")
    details = {
        "result_status": payload.get("status"),
        "split": payload.get("split"),
        "source_sha": payload.get("source_sha"),
        "methodology_status": "historical_failed_checksum_selection_not_real_work",
        "not_admission_evidence_reason": (
            "v3 task success uses source_sha256_check, not reproduced workflow, "
            "test, CI, or environment outcomes"
        ),
        "manifest_sha256": payload.get("manifest", {}).get("sha256"),
        "failed_gates": failed_gates,
        "metrics": {
            "task_success_lift_pp": metrics.get("task_success_lift_pp"),
            "repeated_known_error_reduction": metrics.get(
                "repeated_known_error_reduction"
            ),
            "context_reduction": metrics.get("context_reduction"),
            "false_procedure_injection": metrics.get("false_procedure_injection"),
            "workspace_namespace_leakage": metrics.get("workspace_namespace_leakage"),
            "packet_selection_p95_ms": metrics.get("packet_selection_p95_ms"),
        },
    }
    if payload.get("status") == "passed" and not failed_gates:
        return "implemented", details
    return "failed", details


def _v5_benchmark_status(root: Path) -> tuple[str, dict[str, Any]]:
    path = root / "benchmarks" / "workspace_experience_v5_benchmark_results.json"
    if not path.exists():
        return "missing", {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics", {}).get("admission", {})
    thresholds = workspace_experience_protocol_manifest()["thresholds"]
    failed_gates = _admission_gate_failures(metrics, thresholds)
    details = {
        "result_status": payload.get("status"),
        "split": payload.get("split"),
        "source_sha": payload.get("source_sha"),
        "manifest_sha256": payload.get("manifest", {}).get("sha256"),
        "failed_gates": failed_gates,
        "metrics": {
            "task_success_lift_pp": metrics.get("task_success_lift_pp"),
            "repeated_known_error_reduction": metrics.get("repeated_known_error_reduction"),
            "context_reduction": metrics.get("context_reduction"),
            "false_procedure_injection": metrics.get("false_procedure_injection"),
            "workspace_namespace_leakage": metrics.get("workspace_namespace_leakage"),
            "packet_selection_p95_ms": metrics.get("packet_selection_p95_ms"),
            "packet_selection_p99_ms": metrics.get("packet_selection_p99_ms"),
            "clean_onboarding_seconds": metrics.get("clean_onboarding_seconds"),
        },
    }
    if payload.get("split") != "heldout":
        details["not_admission_evidence_reason"] = "v5 result is a development diagnostic, not untouched held-out evidence"
        return "blocked", details
    if payload.get("status") == "passed" and not failed_gates:
        return "implemented", details
    return "failed", details


def _admission_gate_failures(metrics: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    failed_gates: list[str] = []
    if float(metrics.get("task_success_lift_pp", -1.0)) < thresholds["task_success_lift_pp_min"]:
        failed_gates.append("task_success_lift_pp")
    if (
        float(metrics.get("repeated_known_error_reduction", -1.0))
        < thresholds["repeated_known_error_reduction_min"]
    ):
        failed_gates.append("repeated_known_error_reduction")
    if float(metrics.get("context_reduction", -1.0)) < thresholds["context_reduction_min"]:
        failed_gates.append("context_reduction")
    if (
        float(metrics.get("false_procedure_injection", 1.0))
        > thresholds["false_procedure_injection_max"]
    ):
        failed_gates.append("false_procedure_injection")
    if int(metrics.get("unverified_injection", -1)) != thresholds["unverified_injection"]:
        failed_gates.append("unverified_injection")
    if (
        int(metrics.get("workspace_namespace_leakage", -1))
        != thresholds["workspace_namespace_leakage"]
    ):
        failed_gates.append("workspace_namespace_leakage")
    if (
        float(metrics.get("mandatory_event_capture", -1.0))
        < thresholds["mandatory_event_capture_min"]
    ):
        failed_gates.append("mandatory_event_capture")
    if (
        float(metrics.get("cross_client_citation_state_parity", -1.0))
        != thresholds["cross_client_citation_state_parity"]
    ):
        failed_gates.append("cross_client_citation_state_parity")
    if (
        float(metrics.get("packet_selection_p95_ms", 999999.0))
        > thresholds["packet_selection_p95_ms_max"]
    ):
        failed_gates.append("packet_selection_p95_ms")
    if (
        float(metrics.get("packet_selection_p99_ms", 999999.0))
        > thresholds["packet_selection_p99_ms_max"]
    ):
        failed_gates.append("packet_selection_p99_ms")
    if (
        float(metrics.get("clean_onboarding_seconds", 999999.0))
        > thresholds["clean_onboarding_seconds_max"]
    ):
        failed_gates.append("clean_onboarding_seconds")
    return failed_gates


def _source_manifest(root: Path) -> dict[str, Any]:
    files = [
        "wavemind/workspace_experience.py",
        "wavemind/experience_runtime.py",
        "wavemind/experience_compiler.py",
        "wavemind/experience.py",
        "wavemind/workspace_experience_admission.py",
        "wavemind/cli.py",
        "wavemind/api.py",
        "wavemind/integrations/mcp_experience.py",
        "sdk/typescript/src/index.ts",
        "docs/WORKSPACE_EXPERIENCE_QUICKSTART.md",
        "benchmarks/workspace_experience_manifest.json",
        "benchmarks/workspace_experience_benchmark.py",
        "benchmarks/workspace_experience_v4_manifest.json",
        "benchmarks/workspace_experience_v4_benchmark.py",
        "benchmarks/workspace_experience_v5_manifest.json",
        "benchmarks/workspace_experience_v5_manifest_builder.py",
        "benchmarks/workspace_experience_v5_benchmark.py",
        "tests/test_workspace_experience.py",
        "tests/test_workspace_experience_benchmark.py",
        "tests/test_workspace_experience_v4_benchmark.py",
        "tests/test_workspace_experience_v5_benchmark.py",
        "tests/test_experience_runtime_contracts.py",
    ]
    entries = []
    for relative in files:
        path = root / relative
        if not path.exists():
            continue
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return {
        "schema": "wavemind.workspace_experience_source_manifest.v1",
        "algorithm": "sha256",
        "files": entries,
        "digest": _sha256(entries),
    }


def _git_sha(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
