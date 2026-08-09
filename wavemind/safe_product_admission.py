from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager, redirect_stderr
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, Mapping

from fastapi.testclient import TestClient

from .api import create_app
from .cli import build_parser, enforce_safe_serve_bind
from .core import WaveMind
from .encoders import HashingTextEncoder
from .evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    repository_commit,
    validate_artifact_integrity,
    validate_source_manifest,
)
from .experience import (
    ExperienceKind,
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    SQLiteExperienceStore,
    TrustClass,
)
from .product_backup import create_product_backup, restore_product_backup
from .product_persistence_admission import validate_product_persistence_artifact
from .quickstart_admission import validate_quickstart_artifact
from .safe_retrieval_admission import validate_safe_retrieval_artifact


SCHEMA = "wavemind.safe_product_admission.v1"
EXPECTED_CHECKS = {
    "evidence-truth",
    "benchmark-freshness-model",
    "local-safe-api-default",
    "public-bind-fail-closed",
    "identity-namespace-enforcement",
    "namespace-leakage-zero",
    "secret-leakage-zero",
    "container-recreate-persistence",
    "backup-restore-rollback",
    "false-memory-injection",
    "unverified-injection-zero",
    "python-quickstart",
    "mcp-quickstart",
    "docker-quickstart",
    "typescript-quickstart",
    "supported-python-matrix",
    "repository-sast",
    "exact-source-manifest",
}


def _load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return value


def _check(check_id: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": bool(passed),
        "status": "pass" if passed else "action_required",
        "evidence": evidence,
    }


@contextmanager
def _temporary_environment(updates: Mapping[str, str | None]) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in updates}
    try:
        for name, value in updates.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _benchmark_evidence_checks(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    from benchmarks.validate_benchmark_artifacts import validate_benchmark_artifacts

    future = datetime.now(timezone.utc) + timedelta(days=365)
    audit = validate_benchmark_artifacts(root, max_age_days=7, now=future)
    workflow = (root / ".github/workflows/benchmark-leaderboard.yml").read_text(
        encoding="utf-8"
    )
    truth = {
        "claim_status": audit["claim_status"],
        "claim_eligible": audit["claim_eligible"],
        "source_relation": audit["source_relation"],
        "errors": audit["errors"],
    }
    freshness = {
        "historical_snapshot_survives_future_clock": audit["status"] == "pass",
        "weekly_current_claim": "WAVEMIND_BENCHMARK_CLAIM_STATUS: current" in workflow,
        "requires_current": "--require-current" in workflow,
        "requires_exact_sha": "--expected-source-sha" in workflow,
    }
    return truth, freshness


def _serve_safety_checks() -> tuple[dict[str, Any], dict[str, Any]]:
    parsed = build_parser().parse_args(["serve"])
    local = {
        "default_host": parsed.host,
        "default_is_loopback": parsed.host == "127.0.0.1",
    }
    auth_names = (
        "WAVEMIND_API_PRINCIPALS",
        "WAVEMIND_API_KEYS",
        "WAVEMIND_READ_KEYS",
        "WAVEMIND_WRITE_KEYS",
        "WAVEMIND_ADMIN_KEYS",
    )
    with _temporary_environment({name: None for name in auth_names}):
        diagnostics = StringIO()
        with redirect_stderr(diagnostics):
            implicit = enforce_safe_serve_bind(
                SimpleNamespace(host="0.0.0.0", allow_public=False)
            )
            unauthenticated = enforce_safe_serve_bind(
                SimpleNamespace(host="0.0.0.0", allow_public=True)
            )
    public = {
        "implicit_public_exit": implicit,
        "unauthenticated_public_exit": unauthenticated,
        "diagnostics": diagnostics.getvalue().strip().splitlines(),
    }
    return local, public


def _api_isolation_and_secret_checks(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    principals = json.dumps(
        {
            "tenant-a-key": {
                "identity": "tenant-a-service",
                "role": "admin",
                "namespace_prefixes": ["tenant:a:"],
            }
        }
    )
    with tempfile.TemporaryDirectory(prefix="wavemind-safe-api-") as raw:
        mind = WaveMind(
            db_path=Path(raw) / "memory.sqlite3",
            encoder=HashingTextEncoder(vector_dim=64),
            audit_queries=True,
        )
        try:
            foreign_id = mind.remember(
                "tenant beta confidential memory", namespace="tenant:b:private"
            )
            with _temporary_environment({"WAVEMIND_API_PRINCIPALS": principals}):
                with TestClient(create_app(mind=mind)) as client:
                    headers = {"Authorization": "Bearer tenant-a-key"}
                    own = client.post(
                        "/remember",
                        headers=headers,
                        json={
                            "text": "tenant alpha deployment memory",
                            "namespace": "tenant:a:main",
                        },
                    )
                    foreign_query = client.post(
                        "/query",
                        headers=headers,
                        json={
                            "text": "confidential memory",
                            "namespace": "tenant:b:private",
                        },
                    )
                    foreign_explain = client.get(
                        f"/memories/{foreign_id}/explain",
                        headers=headers,
                        params={"namespace": "tenant:b:private"},
                    )
                    secret_query = client.post(
                        "/query",
                        headers=headers,
                        json={
                            "text": "deployment api_key=must-not-leak Bearer hidden-token",
                            "namespace": "tenant:a:main",
                        },
                    )
                    audit = client.get(
                        "/audit",
                        headers=headers,
                        params={"namespace": "tenant:a:main"},
                    )
        finally:
            mind.close()
    serialized = audit.text
    isolation = {
        "own_write": own.status_code,
        "foreign_query": foreign_query.status_code,
        "foreign_explain": foreign_explain.status_code,
        "foreign_error": foreign_query.json().get("detail"),
    }
    secrets = {
        "query_status": secret_query.status_code,
        "audit_status": audit.status_code,
        "secret_visible": "must-not-leak" in serialized or "hidden-token" in serialized,
        "redaction_present": "[REDACTED]" in serialized,
    }
    return isolation, secrets


def _backup_restore_rollback_check() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="wavemind-safe-backup-") as raw:
        root = Path(raw)
        core_path = root / "core.sqlite3"
        experience_path = root / "experience.sqlite3"
        mind = WaveMind(
            db_path=core_path,
            encoder=HashingTextEncoder(vector_dim=64),
        )
        try:
            memory_id = mind.remember(
                "backup preserves core memory", namespace="tenant:backup"
            )
            with SQLiteExperienceStore(experience_path) as store:
                experience = store.put(
                    ExperienceRecord.create(
                        kind=ExperienceKind.FACT,
                        title="Verified backup policy",
                        content="Restore both product databases together.",
                        source=ExperienceSource(
                            provider="safe-product-admission",
                            source_type="environment",
                            source_id="backup-proof",
                        ),
                        namespace="tenant:backup",
                        confidence=1.0,
                        trust=TrustClass.VERIFIED_OPERATOR,
                        status=ExperienceStatus.ACTIVE,
                    )
                )
                replacement = ExperienceRecord.create(
                    kind=ExperienceKind.CORRECTION,
                    title="Verified backup and restore policy",
                    content="Restore both product databases as one checked unit.",
                    source=ExperienceSource(
                        provider="safe-product-admission",
                        source_type="environment",
                        source_id="backup-proof-v2",
                    ),
                    namespace="tenant:backup",
                    confidence=1.0,
                    trust=TrustClass.VERIFIED_OPERATOR,
                    status=ExperienceStatus.ACTIVE,
                )
                promoted = store.supersede(
                    experience.id,
                    replacement,
                    reason="Prove that rollback preserves the version chain.",
                )
                archive = create_product_backup(mind, store, root / "product.zip")
                rolled_back = store.rollback(
                    promoted.id,
                    reason="safe product rollback proof",
                )
                rollback_target = store.get(promoted.id)
                core_after_rollback = mind.store.get(memory_id) is not None
        finally:
            mind.close()
        restored_core = root / "restored" / "core.sqlite3"
        restored_experience = root / "restored" / "experience.sqlite3"
        restore_product_backup(
            archive,
            core_destination=restored_core,
            experience_destination=restored_experience,
        )
        restored_mind = WaveMind(
            db_path=restored_core,
            encoder=HashingTextEncoder(vector_dim=64),
        )
        try:
            core_restored = restored_mind.store.get(memory_id) is not None
        finally:
            restored_mind.close()
        with SQLiteExperienceStore(restored_experience) as store:
            restored = store.get(promoted.id)
    return {
        "rollback_status": rollback_target.status.value,
        "restored_status": rolled_back.status.value,
        "core_survived_rollback": core_after_rollback,
        "core_restored": core_restored,
        "experience_restored": restored is not None,
        "experience_status": restored.status.value if restored else None,
        "experience_trust": restored.trust.value if restored else None,
    }


def _repository_confidence(root: Path, *, ci_matrix_passed: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    tests_workflow = (root / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    codeql = root / ".github/workflows/codeql.yml"
    versions = {
        version: version in tests_workflow
        for version in ("3.10", "3.11", "3.12", "3.13")
    }
    windows = "windows-latest" in tests_workflow
    matrix = {
        "configured_versions": versions,
        "windows_configured": windows,
        "dependency_jobs_passed": bool(ci_matrix_passed),
    }
    sast = {
        "workflow_present": codeql.is_file(),
        "codeql_v4": "github/codeql-action" in codeql.read_text(encoding="utf-8")
        and "@v4" in codeql.read_text(encoding="utf-8"),
    }
    return matrix, sast


def run_safe_product_admission(
    *,
    project_root: str | Path,
    safe_retrieval_artifact: str | Path,
    product_persistence_artifact: str | Path,
    quickstart_artifact: str | Path,
    ci_matrix_passed: bool,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    source_sha = repository_commit(root)
    safe_retrieval = _load_json(safe_retrieval_artifact)
    product_persistence = _load_json(product_persistence_artifact)
    quickstarts = _load_json(quickstart_artifact)
    safe_errors = validate_safe_retrieval_artifact(
        safe_retrieval,
        project_root=root,
        expected_source_sha=source_sha,
    )
    persistence_errors = validate_product_persistence_artifact(
        product_persistence,
        project_root=root,
        expected_source_sha=source_sha,
    )
    quickstart_errors = validate_quickstart_artifact(
        quickstarts,
        project_root=root,
        expected_source_sha=source_sha,
    )
    evidence_truth, freshness = _benchmark_evidence_checks(root)
    local_api, public_api = _serve_safety_checks()
    isolation, secrets = _api_isolation_and_secret_checks(root)
    backup = _backup_restore_rollback_check()
    python_matrix, sast = _repository_confidence(
        root, ci_matrix_passed=ci_matrix_passed
    )
    safe_metrics = safe_retrieval.get("metrics") or {}
    persistence_checks = product_persistence.get("checks") or {}
    quickstart_checks = {
        str(check.get("id")): check
        for check in quickstarts.get("checks") or []
        if isinstance(check, dict)
    }
    checks = [
        _check(
            "evidence-truth",
            evidence_truth["claim_status"] == "historical"
            and evidence_truth["claim_eligible"] is False
            and not evidence_truth["errors"],
            evidence_truth,
        ),
        _check("benchmark-freshness-model", all(freshness.values()), freshness),
        _check("local-safe-api-default", local_api["default_is_loopback"], local_api),
        _check(
            "public-bind-fail-closed",
            public_api["implicit_public_exit"] != 0
            and public_api["unauthenticated_public_exit"] != 0,
            public_api,
        ),
        _check(
            "identity-namespace-enforcement",
            isolation["own_write"] == 200
            and isolation["foreign_query"] == 403
            and isolation["foreign_explain"] == 403,
            isolation,
        ),
        _check(
            "namespace-leakage-zero",
            not safe_errors and int(safe_metrics.get("namespace_leakage", -1)) == 0,
            {"validator_errors": safe_errors, "count": safe_metrics.get("namespace_leakage")},
        ),
        _check(
            "secret-leakage-zero",
            secrets["secret_visible"] is False
            and secrets["redaction_present"] is True
            and persistence_checks.get("secret_leakage_zero") is True,
            {"api": secrets, "container": persistence_checks.get("secret_leakage_zero")},
        ),
        _check(
            "container-recreate-persistence",
            not persistence_errors and all(persistence_checks.values()),
            {"validator_errors": persistence_errors, "checks": persistence_checks},
        ),
        _check(
            "backup-restore-rollback",
            backup["rollback_status"] == ExperienceStatus.ROLLED_BACK.value
            and backup["core_survived_rollback"]
            and backup["core_restored"]
            and backup["experience_restored"]
            and backup["experience_status"] == ExperienceStatus.ACTIVE.value,
            backup,
        ),
        _check(
            "false-memory-injection",
            not safe_errors
            and float(safe_metrics.get("false_memory_injection_rate", 1.0)) <= 0.02,
            {"validator_errors": safe_errors, "rate": safe_metrics.get("false_memory_injection_rate")},
        ),
        _check(
            "unverified-injection-zero",
            not safe_errors and int(safe_metrics.get("unverified_injection", -1)) == 0,
            {"validator_errors": safe_errors, "count": safe_metrics.get("unverified_injection")},
        ),
    ]
    for check_id in (
        "python-quickstart",
        "mcp-quickstart",
        "docker-quickstart",
        "typescript-quickstart",
    ):
        component = quickstart_checks.get(check_id) or {}
        checks.append(
            _check(
                check_id,
                not quickstart_errors and component.get("passed") is True,
                {"validator_errors": quickstart_errors, "component": component},
            )
        )
    checks.extend(
        [
            _check(
                "supported-python-matrix",
                all(python_matrix["configured_versions"].values())
                and python_matrix["windows_configured"]
                and python_matrix["dependency_jobs_passed"],
                python_matrix,
            ),
            _check("repository-sast", all(sast.values()), sast),
        ]
    )
    manifest = build_source_manifest(
        root,
        [
            ".github/workflows/benchmark-leaderboard.yml",
            ".github/workflows/codeql.yml",
            ".github/workflows/tests.yml",
            "Dockerfile",
            "docker-compose.yml",
            "wavemind/api.py",
            "wavemind/cli.py",
            "wavemind/core.py",
            "wavemind/evidence.py",
            "wavemind/onboarding.py",
            "wavemind/product_backup.py",
            "wavemind/safe_product_admission.py",
        ],
    )
    checks.append(
        _check(
            "exact-source-manifest",
            not validate_source_manifest(root, manifest, require_current_files=True),
            {"source_sha": source_sha, "digest": manifest["digest"]},
        )
    )
    passed = sum(check["passed"] for check in checks)
    report = {
        "schema": SCHEMA,
        "status": "admitted" if passed == len(checks) else "blocked",
        "admitted": passed == len(checks),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha": source_sha,
        "summary": {"checks_passed": passed, "checks_total": len(checks)},
        "checks": checks,
        "component_artifacts": {
            "safe_retrieval": safe_retrieval.get("integrity", {}).get("payload_sha256"),
            "product_persistence": product_persistence.get("integrity", {}).get("payload_sha256"),
            "quickstarts": quickstarts.get("integrity", {}).get("payload_sha256"),
        },
        "source_manifest": manifest,
        "claim_boundary": (
            "Local and repository-controlled safe-product admission. It does not make "
            "remote scale, multi-region, GPU, or npm publication claims."
        ),
    }
    return attach_artifact_integrity(report)


def validate_safe_product_artifact(
    report: Mapping[str, Any],
    *,
    project_root: str | Path,
    expected_source_sha: str,
) -> list[str]:
    errors = validate_artifact_integrity(report)
    if report.get("schema") != SCHEMA:
        errors.append("safe product schema is invalid")
    if report.get("source_sha") != expected_source_sha:
        errors.append("safe product source SHA mismatch")
    manifest = report.get("source_manifest")
    if not isinstance(manifest, Mapping):
        errors.append("safe product source manifest is missing")
    else:
        errors.extend(
            validate_source_manifest(
                Path(project_root), manifest, require_current_files=True
            )
        )
    checks = report.get("checks")
    if not isinstance(checks, list):
        errors.append("safe product checks are missing")
        checks = []
    observed = {
        str(check.get("id"))
        for check in checks
        if isinstance(check, Mapping) and check.get("passed") is True
    }
    if observed != EXPECTED_CHECKS:
        errors.append("safe product mandatory checks are not all passing")
    if any(
        str(check.get("status")) in {"plan_only", "proxy"}
        for check in checks
        if isinstance(check, Mapping)
    ):
        errors.append("safe product checks contain plan-only or proxy evidence")
    if report.get("status") != "admitted" or report.get("admitted") is not True:
        errors.append("safe product status is not admitted")
    return errors


def render_safe_product_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Safe Product Admission",
        "",
        f"Status: **{report['status']}**",
        f"Source SHA: `{report['source_sha']}`",
        f"Checks: **{summary['checks_passed']}/{summary['checks_total']}**",
        "",
        "| Check | Status |",
        "|---|---:|",
    ]
    for check in report["checks"]:
        lines.append(f"| `{check['id']}` | `{check['status']}` |")
    lines.extend(["", f"> {report['claim_boundary']}", ""])
    return "\n".join(lines)
