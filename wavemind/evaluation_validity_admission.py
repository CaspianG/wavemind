from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .evaluation_contracts import backend_query_view, validate_dataset_manifest
from .evidence import (
    attach_artifact_integrity,
    build_source_manifest,
    execution_environment,
    repository_commit,
    utc_now,
)


SCHEMA = "wavemind.evaluation_validity_admission.v1"
EXPECTED_ROWS = (
    "dataset-provenance",
    "split-isolation",
    "native-metric-mapping",
    "positive-controls",
    "negative-controls",
    "control-ordering",
    "metric-range",
    "power-and-mde",
    "paired-clustered-statistics",
    "multiple-comparison-policy",
    "judge-calibration",
    "deterministic-verdict",
    "per-case-completeness",
    "backend-blinding",
    "exact-sha-integrity",
    "safety-admissions-preserved",
)
SOURCE_PATHS = (
    "README.md",
    "wavemind/evaluation_contracts.py",
    "wavemind/evaluation_validity_admission.py",
    "benchmarks/evaluation_dataset_manifest_v1.json",
    "benchmarks/evaluation_salvage_manifest.json",
    "benchmarks/evaluation_validity_admission.py",
    "docs/adr/0001-task-native-evaluation-science.md",
    "docs/ROADMAP.md",
    "tests/test_evaluation_validity_admission.py",
)


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return payload


def _row(row_id: str, passed: bool, evidence: Any, requirement: str) -> dict[str, Any]:
    return {
        "id": row_id,
        "status": "implemented" if passed else "blocked",
        "requirement": requirement,
        "evidence": evidence,
    }


def _evidence_passed(evidence: Mapping[str, Any], key: str) -> tuple[bool, Any]:
    value = evidence.get(key)
    if not isinstance(value, Mapping):
        return False, {"missing_artifact": key}
    return bool(value.get("passed")), dict(value)


def run_evaluation_validity_admission(
    *,
    project_root: str | Path,
    dataset_manifest_path: str | Path,
    validity_evidence_path: str | Path | None = None,
    expected_source_sha: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    source_sha = repository_commit(root)
    expected_sha = expected_source_sha or source_sha
    dataset_manifest = _load_json(dataset_manifest_path)
    dataset_errors = validate_dataset_manifest(dataset_manifest)
    evidence = _load_json(validity_evidence_path) if validity_evidence_path else {}

    contract = dataset_manifest.get("backend_query_contract", {})
    blind_probe = {
        "query": "allowed query",
        "namespace": "tenant:a",
        "gold_answer": "must-not-leak",
        "gold_evidence": ["must-not-leak"],
        "question_type": "must-not-leak",
        "case_id": "must-not-leak",
        "split": "must-not-leak",
    }
    try:
        backend_view = backend_query_view(blind_probe, contract)
        blinding_passed = not any(
            "must-not-leak" in str(value) for value in backend_view.values()
        )
        blinding_evidence: Any = {"backend_view_fields": sorted(backend_view)}
    except ValueError as exc:
        blinding_passed = False
        blinding_evidence = {"error": str(exc)}

    statistics = dataset_manifest.get("statistics_policy", {})
    correction_passed = (
        isinstance(statistics, Mapping)
        and statistics.get("multiple_primary_correction") == "holm"
        and statistics.get("primary_metrics_frozen_before_product_run") is True
    )

    requirements = {
        "dataset-provenance": "Dataset revisions, licenses, and checksums are pinned.",
        "split-isolation": "Dev, validation, and final splits have zero row, conversation, trajectory, or derived-fingerprint overlap.",
        "native-metric-mapping": "Every task uses its native scorer and semantic coercion is rejected.",
        "positive-controls": "Oracle evidence or correct-state controls are executed.",
        "negative-controls": "Random, no-memory, stale, wrong-namespace, and deleted-evidence controls are executed.",
        "control-ordering": "Oracle is above a strong valid baseline, which is above random and no-memory; poison affects only its safety target.",
        "metric-range": "Primary metrics have no floor or ceiling that makes preregistered improvement impossible.",
        "power-and-mde": "Sample size, minimum detectable effect, and cluster unit are preregistered per primary metric.",
        "paired-clustered-statistics": "Paired confidence intervals cluster by conversation, task, or trajectory.",
        "multiple-comparison-policy": "Multiple primary comparisons use the preregistered Holm correction.",
        "judge-calibration": "Every required LLM judge is pinned, calibrated, and has inter-run agreement evidence.",
        "deterministic-verdict": "Three deterministic repeats produce one verdict fingerprint.",
        "per-case-completeness": "Raw evidence includes every pass, failure, error, and skipped row.",
        "backend-blinding": "Backend input excludes gold, IDs, task type, split, and evaluator metadata.",
        "exact-sha-integrity": "Admission is tied to the exact source SHA and a current source manifest.",
        "safety-admissions-preserved": "Safe Product and Workspace Experience are admitted on the same exact SHA.",
    }

    rows: list[dict[str, Any]] = []
    rows.append(
        _row(
            "dataset-provenance",
            not dataset_errors,
            {"errors": dataset_errors},
            requirements["dataset-provenance"],
        )
    )
    for row_id, evidence_key in (
        ("split-isolation", "split_isolation"),
        ("positive-controls", "positive_controls"),
        ("negative-controls", "negative_controls"),
        ("control-ordering", "control_ordering"),
        ("metric-range", "metric_range"),
        ("power-and-mde", "power_and_mde"),
        ("paired-clustered-statistics", "paired_clustered_statistics"),
    ):
        passed, detail = _evidence_passed(evidence, evidence_key)
        rows.append(_row(row_id, passed, detail, requirements[row_id]))
    rows.append(
        _row(
            "native-metric-mapping",
            not dataset_errors,
            {"errors": dataset_errors},
            requirements["native-metric-mapping"],
        )
    )
    rows.append(
        _row(
            "multiple-comparison-policy",
            correction_passed,
            dict(statistics) if isinstance(statistics, Mapping) else {},
            requirements["multiple-comparison-policy"],
        )
    )
    for row_id, evidence_key in (
        ("judge-calibration", "judge_calibration"),
        ("deterministic-verdict", "deterministic_verdict"),
        ("per-case-completeness", "per_case_completeness"),
    ):
        passed, detail = _evidence_passed(evidence, evidence_key)
        rows.append(_row(row_id, passed, detail, requirements[row_id]))
    rows.append(
        _row(
            "backend-blinding",
            blinding_passed,
            blinding_evidence,
            requirements["backend-blinding"],
        )
    )
    rows.append(
        _row(
            "exact-sha-integrity",
            source_sha == expected_sha,
            {
                "source_sha": source_sha,
                "expected_source_sha": expected_sha,
                "source_manifest": build_source_manifest(root, SOURCE_PATHS),
            },
            requirements["exact-sha-integrity"],
        )
    )
    safety_passed, safety_detail = _evidence_passed(
        evidence, "safety_admissions_preserved"
    )
    rows.append(
        _row(
            "safety-admissions-preserved",
            safety_passed,
            safety_detail,
            requirements["safety-admissions-preserved"],
        )
    )
    rows_by_id = {row["id"]: row for row in rows}
    ordered_rows = [rows_by_id[row_id] for row_id in EXPECTED_ROWS]
    admitted = all(row["status"] == "implemented" for row in ordered_rows)
    return attach_artifact_integrity(
        {
            "schema": SCHEMA,
            "generated_at": utc_now(),
            "source_sha": source_sha,
            "expected_source_sha": expected_sha,
            "status": "admitted" if admitted else "blocked",
            "admitted": admitted,
            "implemented_rows": sum(
                row["status"] == "implemented" for row in ordered_rows
            ),
            "required_rows": len(ordered_rows),
            "rows": ordered_rows,
            "environment": execution_environment(profile="evaluation-validity-local"),
            "claim_boundary": (
                "Measurement-validity admission only. Product tuning, benchmark quality, "
                "generalization, leaderboard, and production claims remain prohibited until admitted."
            ),
        }
    )


def render_evaluation_validity_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Evaluation Validity Admission",
        "",
        f"Status: **{report.get('status', 'unknown')}**",
        "",
        f"Source SHA: `{report.get('source_sha', 'unknown')}`",
        "",
        f"Rows: `{report.get('implemented_rows', 0)}/{report.get('required_rows', 0)}` implemented",
        "",
        "| Row | Status | Requirement |",
        "|---|---|---|",
    ]
    for row in report.get("rows", []):
        lines.append(f"| `{row['id']}` | `{row['status']}` | {row['requirement']} |")
    lines.extend(["", f"> {report.get('claim_boundary', '')}", ""])
    return "\n".join(lines)
