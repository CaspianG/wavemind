from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .evidence import (
    attach_artifact_integrity,
    validate_artifact_integrity,
    validate_source_manifest,
)
from .safe_product_admission import validate_safe_product_artifact


WORKSPACE_EXPERIENCE_ADMISSION_SCHEMA = "wavemind.workspace_experience_admission.v1"
WORKSPACE_OPERATIONAL_EVIDENCE_SCHEMA = "wavemind.workspace_experience_operational.v1"
WORKSPACE_EXPERIENCE_PROTOCOL_REVISION = "workspace-experience-v1-frozen-20260810"
WORKSPACE_EXPERIENCE_PROTOCOL_SHA256 = (
    "fa2ebc36799b44ff54e74120da7dab3a475d40461a4963872069f5905beeb590"
)
V4_INVALID_REASONS = [
    "clean_onboarding_seconds was hardcoded instead of measured from a clean subprocess flow",
    "static baseline can collapse to zero positive success and is not the strongest static comparator",
    "positive task success accepts outcome-kind matches without exact case/procedure validation",
    "cross-client parity reopens the same Python manager instead of cross-surface client A to restart to client B replay",
]
FROZEN_V5_QUALITY_SOURCE_SHA = "eb27a54c001a9169e7baf4bc299ee49fa86468bd"
FROZEN_V5_RESULT_BLOB = "2ed5b4f9d20c68ed2f24d1d92cd69ff1bc70baaf"
FROZEN_V5_MANIFEST_SHA256 = (
    "9fa1d31b4085b723baf2e4dacd6ea4be8b894e734ecc475329fdc53d5cd888b8"
)
QUALITY_CRITICAL_BLOBS = {
    "wavemind/experience_compiler.py": "e5c6281f1f3968937243d23d45f2d622472b184a",
    "wavemind/experience_runtime.py": "4ef356bd7ee78a2d20648675c6596f9ba9764d16",
    "wavemind/workspace_experience.py": "6cf07bb1a8fad1cc6c73143590d90aac3ba52991",
    "wavemind/experience.py": "e66d6cbfba2b42f767380790484bab947f870f90",
    "wavemind/memory_firewall.py": "ea9c9fb8968eb11fe597a406beec7c16596927df",
    "benchmarks/workspace_experience_v5_manifest.json": "9597ae4f24a6e06b675adbbe78245dbcf26c4ab6",
    "benchmarks/workspace_experience_v5_manifest_builder.py": "84c638469fd5b8e8f0971fd811ba56afe34441f2",
    "benchmarks/workspace_experience_v5_benchmark.py": "4b0fc7cf78df9499114f9e4da3bea54a4a3babcc",
    "tests/test_workspace_experience_v5_benchmark.py": "2a86995c02f7eca57a82283b37be4294b9e2be8b",
}
QUALITY_FRESHNESS_ALLOWLIST = {
    (
        "wavemind/experience_compiler.py",
        "e5c6281f1f3968937243d23d45f2d622472b184a",
        "f4af608e1cbec0b9ded232236010b96d369ce7d2",
    ): "optional compact rendering only; default packet selection, scoring, provenance, firewall behavior, and frozen v5 protocol are unchanged",
    (
        "wavemind/experience_runtime.py",
        "4ef356bd7ee78a2d20648675c6596f9ba9764d16",
        "95bc7e47af03b086c4bdc6646880ab6e780d4528",
    ): "optional compact-rendering passthrough only; default intervention selection, scoring, safety behavior, and frozen v5 protocol are unchanged",
    (
        "wavemind/workspace_experience.py",
        "6cf07bb1a8fad1cc6c73143590d90aac3ba52991",
        "527c070dc3a528dcda559779098ad5659e841d82",
    ): "workspace config path hardening only; packet selection, compiler, runtime, firewall, and v5 protocol are unchanged",
    (
        "wavemind/experience.py",
        "e66d6cbfba2b42f767380790484bab947f870f90",
        "9a6811c7caa87ca4c65c46558664d30aeb8bff22",
    ): "upgrade schema-ledger initialization and runtime compatibility validation only; candidate selection, scoring, compiler, runtime, firewall, and v5 protocol are unchanged",
}


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
    safe_product_path: str | Path | None = None,
    operational_evidence_path: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    _, benchmark_details = _benchmark_status(root_path)
    v5_status, v5_details = _v5_benchmark_status(root_path)
    operational_status, operational_details = _operational_evidence_status(
        root_path,
        operational_evidence_path,
    )
    safe_product_status, safe_product_details = _safe_product_status(
        root_path,
        safe_product_path,
    )
    admission_status = (
        "implemented"
        if (
            v5_status == "implemented"
            and operational_status == "implemented"
            and safe_product_status == "implemented"
        )
        else "blocked"
    )
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
            "historical",
            "benchmarks/workspace_experience_benchmark_results.json",
            "tests/test_workspace_experience_benchmark.py",
            details=benchmark_details,
        ),
        _row(
            "frozen-real-work-benchmark-v4",
            "Historical invalid v4 protocol; not admission evidence.",
            "historical",
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
            "Frozen real workflow quality benchmark with exact case/procedure success, strongest static baseline, measured onboarding, and cross-surface replay.",
            v5_status,
            "benchmarks/workspace_experience_v5_benchmark_results.json",
            "tests/test_workspace_experience_v5_benchmark.py",
            details=v5_details,
        ),
        _row(
            "current-workspace-operational-evidence",
            "Current-SHA HTTP workspace registry, authenticated namespace, restart persistence, and cross-surface replay evidence.",
            operational_status,
            "benchmarks/workspace_experience_operational_results.json",
            "tests/test_workspace_experience_admission.py",
            details=operational_details,
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
            safe_product_status,
            "benchmarks/safe_product_admission_results.json",
            ".github/workflows/safe-product.yml",
            details=safe_product_details,
        ),
    ]
    mandatory_rows = [row for row in rows if row["status"] != "historical"]
    complete = all(row["status"] == "implemented" for row in mandatory_rows)
    failed = any(row["status"] == "failed" for row in mandatory_rows)
    blocked = any(
        row["status"] in {"blocked", "required_current"} for row in mandatory_rows
    )
    return attach_artifact_integrity(
        {
            "schema": WORKSPACE_EXPERIENCE_ADMISSION_SCHEMA,
            "status": "admitted"
            if complete
            else ("blocked" if failed or blocked else "gap_audit"),
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
                "historical": sum(row["status"] == "historical" for row in rows),
                "required_current": sum(
                    row["status"] == "required_current" for row in rows
                ),
                "total": len(rows),
            },
            "rows": rows,
            "claim_boundary": (
                "This checked-in payload is a Goal 7 evidence snapshot. It is not an exact-current "
                "PR or main admission; exact verdicts are produced by CI artifacts on the current SHA. "
                "The goal remains blocked while current operational evidence or Safe Product is required_current."
            ),
        }
    )


def render_workspace_experience_admission_markdown(
    payload: dict[str, Any],
    *,
    title: str = "Workspace Experience Admission Matrix",
) -> str:
    lines = [
        f"# {title}",
        "",
        f"- Status: `{payload['status']}`",
        f"- Evidence Snapshot Source SHA: `{payload.get('source_sha')}`",
        "- Exact Current Verdict: CI artifact on the current PR/main SHA",
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


def write_workspace_experience_admission_artifacts(
    *,
    root: str | Path = ".",
    matrix_output: str | Path = "benchmarks/workspace_experience_admission_matrix.json",
    matrix_markdown_output: str
    | Path = "benchmarks/WORKSPACE_EXPERIENCE_ADMISSION_MATRIX.md",
    result_output: str
    | Path = "benchmarks/workspace_experience_admission_results.json",
    report_output: str | Path = "benchmarks/WORKSPACE_EXPERIENCE_ADMISSION.md",
    baseline_source_sha: str | None = None,
    safe_product_path: str | Path | None = None,
    operational_evidence_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = evaluate_workspace_experience_admission_matrix(
        root=root,
        baseline_source_sha=baseline_source_sha,
        safe_product_path=safe_product_path,
        operational_evidence_path=operational_evidence_path,
    )
    _write_json(Path(matrix_output), payload)
    _write_json(Path(result_output), payload)
    _write_text(
        Path(matrix_markdown_output),
        render_workspace_experience_admission_markdown(
            payload,
            title="Workspace Experience Admission Matrix",
        ),
    )
    _write_text(
        Path(report_output),
        render_workspace_experience_admission_markdown(
            payload,
            title="Workspace Experience Admission",
        ),
    )
    return payload


def write_workspace_experience_admission_matrix(
    *,
    root: str | Path = ".",
    output: str | Path = "benchmarks/workspace_experience_admission_matrix.json",
    markdown_output: str | Path = "benchmarks/WORKSPACE_EXPERIENCE_ADMISSION_MATRIX.md",
    baseline_source_sha: str | None = None,
    safe_product_path: str | Path | None = None,
    operational_evidence_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = evaluate_workspace_experience_admission_matrix(
        root=root,
        baseline_source_sha=baseline_source_sha,
        safe_product_path=safe_product_path,
        operational_evidence_path=operational_evidence_path,
    )
    _write_json(Path(output), payload)
    _write_text(
        Path(markdown_output),
        render_workspace_experience_admission_markdown(
            payload,
            title="Workspace Experience Admission Matrix",
        ),
    )
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


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
    if (
        float(metrics.get("task_success_lift_pp", -1.0))
        < thresholds["task_success_lift_pp_min"]
    ):
        failed_gates.append("task_success_lift_pp")
    if (
        float(metrics.get("repeated_known_error_reduction", -1.0))
        < thresholds["repeated_known_error_reduction_min"]
    ):
        failed_gates.append("repeated_known_error_reduction")
    if (
        float(metrics.get("context_reduction", -1.0))
        < thresholds["context_reduction_min"]
    ):
        failed_gates.append("context_reduction")
    if (
        float(metrics.get("false_procedure_injection", 1.0))
        > thresholds["false_procedure_injection_max"]
    ):
        failed_gates.append("false_procedure_injection")
    if (
        int(metrics.get("unverified_injection", -1))
        != thresholds["unverified_injection"]
    ):
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
    freshness = _quality_freshness_status(root)
    details = {
        "result_status": payload.get("status"),
        "split": payload.get("split"),
        "source_sha": payload.get("source_sha"),
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
            "packet_selection_p99_ms": metrics.get("packet_selection_p99_ms"),
            "clean_onboarding_seconds": metrics.get("clean_onboarding_seconds"),
        },
        "evidence_scope": "frozen_quality",
        "freshness": freshness,
    }
    if payload.get("split") != "heldout":
        details["not_admission_evidence_reason"] = (
            "v5 result is a development diagnostic, not untouched held-out evidence"
        )
        return "blocked", details
    if payload.get("source_sha") != FROZEN_V5_QUALITY_SOURCE_SHA:
        details["not_admission_evidence_reason"] = (
            "v5 source SHA is not the frozen accepted quality source"
        )
        return "blocked", details
    if payload.get("manifest", {}).get("sha256") != FROZEN_V5_MANIFEST_SHA256:
        details["not_admission_evidence_reason"] = (
            "v5 manifest hash differs from the frozen accepted quality manifest"
        )
        return "blocked", details
    if not freshness["quality_fresh"]:
        details["not_admission_evidence_reason"] = (
            "quality-critical source changed; new independent quality evidence required"
        )
        return "blocked", details
    if payload.get("status") == "passed" and not failed_gates:
        return "implemented", details
    return "failed", details


def _operational_evidence_status(
    root: Path,
    operational_evidence_path: str | Path | None,
) -> tuple[str, dict[str, Any]]:
    path = (
        Path(operational_evidence_path)
        if operational_evidence_path is not None
        else root / "benchmarks" / "workspace_experience_operational_results.json"
    )
    if not path.is_absolute():
        path = root / path
    current_sha = _git_sha(root)
    if not path.exists():
        return "required_current", {
            "reason": "current workspace operational evidence artifact missing",
            "current_source_sha": current_sha,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = _validate_operational_evidence_payload(
        payload,
        root=root,
        expected_source_sha=current_sha,
    )
    details = {
        "result_status": payload.get("status"),
        "source_sha": payload.get("source_sha"),
        "current_source_sha": current_sha,
        "summary": payload.get("summary"),
        "metrics": payload.get("metrics"),
        "validator_errors": errors,
    }
    if errors:
        return "failed", details
    return "implemented", details


def _safe_product_status(
    root: Path,
    safe_product_path: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
    path = (
        Path(safe_product_path)
        if safe_product_path is not None
        else root / "benchmarks" / "safe_product_admission_results.json"
    )
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        return "required_current", {"reason": "safe product artifact missing"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    current_sha = _git_sha(root)
    details = {
        "result_status": payload.get("status"),
        "source_sha": payload.get("source_sha"),
        "current_source_sha": current_sha,
        "summary": payload.get("summary"),
    }
    validation_errors = validate_safe_product_artifact(
        payload,
        project_root=root,
        expected_source_sha=current_sha,
    )
    details["validator_errors"] = validation_errors
    if not validation_errors:
        return "implemented", details
    details["reason"] = (
        "safe product admission is not current or failed validation for this source SHA"
    )
    return "required_current", details


def _validate_operational_evidence_payload(
    payload: Mapping[str, Any],
    *,
    root: Path,
    expected_source_sha: str,
) -> list[str]:
    errors = validate_artifact_integrity(payload)
    if payload.get("schema") != WORKSPACE_OPERATIONAL_EVIDENCE_SCHEMA:
        errors.append("workspace operational schema is invalid")
    if payload.get("status") != "admitted" or payload.get("admitted") is not True:
        errors.append("workspace operational evidence is not admitted")
    if payload.get("source_sha") != expected_source_sha:
        errors.append("workspace operational source SHA mismatch")
    checks = {
        str(check.get("id")): check
        for check in payload.get("checks") or []
        if isinstance(check, Mapping)
    }
    required_checks = {
        "python-write-http-restart-replay",
        "registered-workspace-http-packet",
        "namespace-auth-denies-cross-workspace",
        "arbitrary-workspace-id-denied",
        "root-field-without-workspace-id-denied",
        "missing-registry-denied",
        "registry-escape-denied",
        "mandatory-events-captured-idempotently",
        "secrets-redacted",
    }
    missing = sorted(required_checks - set(checks))
    if missing:
        errors.append(f"workspace operational checks missing: {', '.join(missing)}")
    failed = sorted(
        check_id
        for check_id, check in checks.items()
        if check.get("passed") is not True
    )
    if failed:
        errors.append(f"workspace operational checks failed: {', '.join(failed)}")
    metrics = payload.get("metrics") or {}
    if int(metrics.get("workspace_namespace_leakage", -1)) != 0:
        errors.append("workspace operational namespace leakage is not zero")
    if float(metrics.get("mandatory_event_capture", 0.0)) < 0.99:
        errors.append(
            "workspace operational mandatory event capture is below threshold"
        )
    if float(metrics.get("cross_client_citation_state_parity", 0.0)) != 1.0:
        errors.append("workspace operational cross-client parity is not 1.0")
    if float(metrics.get("packet_selection_p95_ms", 999999.0)) > 100.0:
        errors.append("workspace operational p95 latency exceeds threshold")
    if float(metrics.get("packet_selection_p99_ms", 999999.0)) > 250.0:
        errors.append("workspace operational p99 latency exceeds threshold")
    manifest = payload.get("source_manifest")
    if not isinstance(manifest, Mapping):
        errors.append("workspace operational source manifest is missing")
    else:
        errors.extend(
            validate_source_manifest(root, manifest, require_current_files=True)
        )
    return errors


def _quality_freshness_status(root: Path) -> dict[str, Any]:
    current_sha = _git_sha(root)
    changed: list[dict[str, Any]] = []
    allowed: list[dict[str, Any]] = []
    dirty: list[str] = []
    for relative, frozen_blob in QUALITY_CRITICAL_BLOBS.items():
        current_blob = _git_blob_id(root, current_sha, relative)
        if _git_worktree_dirty(root, relative):
            dirty.append(relative)
        if current_blob == frozen_blob:
            continue
        allow_reason = QUALITY_FRESHNESS_ALLOWLIST.get(
            (relative, frozen_blob, current_blob)
        )
        item = {
            "path": relative,
            "frozen_blob": frozen_blob,
            "current_blob": current_blob,
        }
        if allow_reason:
            allowed.append({**item, "reason": allow_reason})
        else:
            changed.append(item)
    result_blob = _git_blob_id(
        root,
        current_sha,
        "benchmarks/workspace_experience_v5_benchmark_results.json",
    )
    if _git_worktree_dirty(
        root,
        "benchmarks/workspace_experience_v5_benchmark_results.json",
    ):
        dirty.append("benchmarks/workspace_experience_v5_benchmark_results.json")
    result_ok = result_blob == FROZEN_V5_RESULT_BLOB
    protocol_ok = (
        workspace_experience_protocol_manifest()["sha256"]
        == WORKSPACE_EXPERIENCE_PROTOCOL_SHA256
    )
    quality_fresh = not changed and not dirty and result_ok and protocol_ok
    return {
        "quality_fresh": quality_fresh,
        "status": "fresh"
        if quality_fresh
        else "blocked_new_independent_quality_evidence_required",
        "frozen_source_sha": FROZEN_V5_QUALITY_SOURCE_SHA,
        "current_source_sha": current_sha,
        "critical_files": [
            {"path": path, "frozen_blob": blob}
            for path, blob in QUALITY_CRITICAL_BLOBS.items()
        ],
        "allowed_operational_changes": allowed,
        "unallowed_quality_changes": changed,
        "dirty_quality_files": dirty,
        "v5_result_blob": result_blob,
        "frozen_v5_result_blob": FROZEN_V5_RESULT_BLOB,
        "v5_result_blob_ok": result_ok,
        "protocol_sha256": WORKSPACE_EXPERIENCE_PROTOCOL_SHA256,
        "protocol_ok": protocol_ok,
    }


def _git_blob_id(root: Path, source_sha: str, relative: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", f"{source_sha}:{relative}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_worktree_dirty(root: Path, relative: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "diff", "--quiet", "--", relative],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return result.returncode != 0


def _admission_gate_failures(
    metrics: dict[str, Any], thresholds: dict[str, Any]
) -> list[str]:
    failed_gates: list[str] = []
    if (
        float(metrics.get("task_success_lift_pp", -1.0))
        < thresholds["task_success_lift_pp_min"]
    ):
        failed_gates.append("task_success_lift_pp")
    if (
        float(metrics.get("repeated_known_error_reduction", -1.0))
        < thresholds["repeated_known_error_reduction_min"]
    ):
        failed_gates.append("repeated_known_error_reduction")
    if (
        float(metrics.get("context_reduction", -1.0))
        < thresholds["context_reduction_min"]
    ):
        failed_gates.append("context_reduction")
    if (
        float(metrics.get("false_procedure_injection", 1.0))
        > thresholds["false_procedure_injection_max"]
    ):
        failed_gates.append("false_procedure_injection")
    if (
        int(metrics.get("unverified_injection", -1))
        != thresholds["unverified_injection"]
    ):
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
        "tests/test_workspace_experience_admission.py",
        "tests/test_experience_compiler.py",
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
