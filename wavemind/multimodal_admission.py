from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STRUCTURED_REPORT = "benchmarks/structured_memory_results.json"
EXTERNAL_EVIDENCE = "benchmarks/multimodal_external_encoder_results.json"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _metric(payload: dict[str, Any], name: str, *aliases: str) -> Any:
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    for key in (name, *aliases):
        if key in metrics:
            return metrics[key]
        if key in summary:
            return summary[key]
        if key in payload:
            return payload[key]
    return None


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _check(
    name: str,
    value: Any,
    target: Any,
    op: str,
    issue: str,
) -> dict[str, Any]:
    passed = False
    if op == ">=":
        value_f = _as_float(value)
        target_f = _as_float(target)
        passed = value_f is not None and target_f is not None and value_f >= target_f
    elif op == "<=":
        value_f = _as_float(value)
        target_f = _as_float(target)
        passed = value_f is not None and target_f is not None and value_f <= target_f
    elif op == "is":
        passed = value is target
    elif op == "not-in":
        passed = str(value).strip().lower() not in {str(item).lower() for item in target}
    return {
        "name": name,
        "value": value,
        "target": target,
        "op": op,
        "pass": bool(passed),
        "issue": "" if passed else issue,
    }


def validate_external_multimodal_evidence(
    payload: dict[str, Any] | None,
    *,
    min_modalities: int = 7,
    min_payloads: int = 1_000,
    min_queries: int = 200,
    min_precision_at_1: float = 0.90,
    min_cross_modal_precision_at_1: float = 0.90,
    max_query_p99_ms: float = 250.0,
    max_encode_p95_ms: float = 100.0,
    require_object_store: bool = True,
) -> dict[str, Any]:
    """Validate real external multimodal backend evidence.

    The deterministic structured-memory fixture proves the API contract. This
    validator is intentionally stricter: production admission needs external
    encoder evidence, object-store-backed assets, enough payloads/queries, and
    latency/quality bounds.
    """

    if payload is None:
        return {
            "status": "action_required",
            "evidence": "missing external multimodal encoder evidence",
            "issues": [
                f"missing required artifact: {EXTERNAL_EVIDENCE}",
            ],
            "checks": [],
        }

    modalities = payload.get("modalities")
    if not isinstance(modalities, list):
        modalities = []
    modality_count = _as_int(
        payload.get("modality_count") or _metric(payload, "modality_count"),
        default=len(modalities),
    )
    payload_count = _as_int(payload.get("payload_count") or _metric(payload, "payload_count"))
    query_count = _as_int(payload.get("query_count") or _metric(payload, "query_count"))
    environment = str(payload.get("environment") or payload.get("node_mode") or "")
    source = str(payload.get("source") or "")
    object_store = str(payload.get("object_store") or payload.get("asset_store") or "")
    external_source = (
        "external" in source.lower()
        or str(payload.get("node_mode") or "").lower() == "external"
        or str(payload.get("deployment") or "").lower() in {"staging", "production", "prod"}
    )
    local_environments = {"", "local", "loopback", "fixture", "test", "unit"}
    local_stores = {"", "local", "filesystem", "memory", "in-memory", "fixture"}

    checks = [
        _check(
            "external_source",
            external_source,
            True,
            "is",
            "source must identify an external/staging/production encoder run",
        ),
        _check(
            "environment",
            environment,
            local_environments,
            "not-in",
            "environment must not be local/loopback/fixture",
        ),
        _check(
            "object_store",
            object_store,
            local_stores,
            "not-in",
            "object_store must be a remote durable store such as s3/gcs/azure",
        )
        if require_object_store
        else _check("object_store", True, True, "is", ""),
        _check(
            "modalities",
            modality_count,
            int(min_modalities),
            ">=",
            f"modality_count must be >= {int(min_modalities)}",
        ),
        _check(
            "payload_count",
            payload_count,
            int(min_payloads),
            ">=",
            f"payload_count must be >= {int(min_payloads)}",
        ),
        _check(
            "query_count",
            query_count,
            int(min_queries),
            ">=",
            f"query_count must be >= {int(min_queries)}",
        ),
        _check(
            "precision_at_1",
            _metric(payload, "precision_at_1", "target_precision_at_1"),
            float(min_precision_at_1),
            ">=",
            f"precision_at_1 must be >= {float(min_precision_at_1):.3f}",
        ),
        _check(
            "cross_modal_precision_at_1",
            _metric(payload, "cross_modal_precision_at_1"),
            float(min_cross_modal_precision_at_1),
            ">=",
            "cross_modal_precision_at_1 must be >= "
            f"{float(min_cross_modal_precision_at_1):.3f}",
        ),
        _check(
            "target_modality_routing_rate",
            _metric(payload, "target_modality_routing_rate"),
            0.95,
            ">=",
            "target_modality_routing_rate must be >= 0.950",
        ),
        _check(
            "vector_persistence_rate",
            _metric(payload, "vector_persistence_rate", "vectors_persisted_rate"),
            0.99,
            ">=",
            "vector_persistence_rate must be >= 0.990",
        ),
        _check(
            "provenance_rate",
            _metric(payload, "provenance_rate"),
            0.99,
            ">=",
            "provenance_rate must be >= 0.990",
        ),
        _check(
            "dimension_match_rate",
            _metric(payload, "dimension_match_rate"),
            1.0,
            ">=",
            "dimension_match_rate must be >= 1.000",
        ),
        _check(
            "finite_vector_rate",
            _metric(payload, "finite_vector_rate"),
            1.0,
            ">=",
            "finite_vector_rate must be >= 1.000",
        ),
        _check(
            "normalized_vector_rate",
            _metric(payload, "normalized_vector_rate"),
            0.95,
            ">=",
            "normalized_vector_rate must be >= 0.950",
        ),
        _check(
            "query_p99_ms",
            _metric(payload, "query_p99_ms", "p99_latency_ms", "retrieval_p99_ms"),
            float(max_query_p99_ms),
            "<=",
            f"query_p99_ms must be <= {float(max_query_p99_ms):.3f}",
        ),
        _check(
            "encode_p95_ms",
            max(
                _as_float(_metric(payload, "payload_encode_p95_ms"), 0.0) or 0.0,
                _as_float(_metric(payload, "query_encode_p95_ms"), 0.0) or 0.0,
            ),
            float(max_encode_p95_ms),
            "<=",
            f"payload/query encode p95 must be <= {float(max_encode_p95_ms):.3f}",
        ),
        _check(
            "error_rate",
            _metric(payload, "error_rate"),
            0.01,
            "<=",
            "error_rate must be <= 0.010",
        ),
    ]

    issues = [str(check["issue"]) for check in checks if not check["pass"]]
    return {
        "status": "pass" if not issues else "fail",
        "evidence": "external multimodal encoder evidence"
        if not issues
        else "external multimodal evidence does not satisfy rollout",
        "issues": issues,
        "checks": checks,
        "modality_count": modality_count,
        "payload_count": payload_count,
        "query_count": query_count,
        "modalities": modalities,
        "environment": environment,
        "source": source,
        "object_store": object_store,
    }


def evaluate_multimodal_admission(
    root: Path = PROJECT_ROOT,
    *,
    deployment: str = "production",
    min_modalities: int = 7,
    min_payloads: int = 1_000,
    min_queries: int = 200,
    min_precision_at_1: float = 0.90,
    min_cross_modal_precision_at_1: float = 0.90,
    max_query_p99_ms: float = 250.0,
    max_encode_p95_ms: float = 100.0,
    require_object_store: bool = True,
    allow_plan_only: bool = False,
) -> dict[str, Any]:
    root = Path(root)
    structured = _load_optional_json(root / STRUCTURED_REPORT) or {}
    structured_summary = (
        structured.get("summary") if isinstance(structured.get("summary"), dict) else {}
    )
    structured_checks = (
        structured.get("checks") if isinstance(structured.get("checks"), list) else []
    )
    structured_status = str(structured_summary.get("status") or "missing")
    structured_pass = structured_status == "pass" and all(
        bool(check.get("pass")) for check in structured_checks if isinstance(check, dict)
    )

    external_payload = _load_optional_json(root / EXTERNAL_EVIDENCE)
    requested = validate_external_multimodal_evidence(
        external_payload,
        min_modalities=min_modalities,
        min_payloads=min_payloads,
        min_queries=min_queries,
        min_precision_at_1=min_precision_at_1,
        min_cross_modal_precision_at_1=min_cross_modal_precision_at_1,
        max_query_p99_ms=max_query_p99_ms,
        max_encode_p95_ms=max_encode_p95_ms,
        require_object_store=require_object_store,
    )
    requested_status = str(requested.get("status") or "missing")

    issues: list[str] = []
    warnings: list[str] = []
    if not structured_pass:
        issues.append(f"structured_memory contract is not pass: status={structured_status}")
    if requested_status != "pass":
        issues.append(
            "external_multimodal_encoder artifact does not satisfy requested rollout: "
            f"requested_evidence_status={requested_status}"
        )
    if int(min_modalities) < 1:
        issues.append("min_modalities must be positive.")
    if int(min_payloads) < 1:
        issues.append("min_payloads must be positive.")
    if int(min_queries) < 1:
        issues.append("min_queries must be positive.")
    if not 0 < float(min_precision_at_1) <= 1:
        issues.append("min_precision_at_1 must be in (0, 1].")
    if not 0 < float(min_cross_modal_precision_at_1) <= 1:
        issues.append("min_cross_modal_precision_at_1 must be in (0, 1].")
    if float(max_query_p99_ms) <= 0:
        issues.append("max_query_p99_ms must be positive.")
    if float(max_encode_p95_ms) <= 0:
        issues.append("max_encode_p95_ms must be positive.")

    admitted = structured_pass and requested_status == "pass" and not issues
    if admitted:
        status = "admitted"
    elif allow_plan_only and structured_pass:
        status = "plan_only"
    else:
        status = "blocked"

    next_actions: list[str] = []
    if admitted:
        next_actions.append(
            "Proceed with multimodal rollout while monitoring modality routing, vector persistence, provenance, p99 query latency, encode p95, and error rate."
        )
    elif status == "plan_only":
        next_actions.append(
            "Do not claim production multimodal quality yet; run the external encoder benchmark against real assets and object-store-backed payloads first."
        )
    else:
        next_actions.append(
            "Keep production multimodal claims locked until structured memory and external encoder evidence both pass."
        )
    next_actions.append(
        "Commit benchmarks/multimodal_external_encoder_results.json after the external encoder run passes."
    )

    requested_issues = list(requested.get("issues") or [])
    return {
        "schema": "wavemind.multimodal_admission.v1",
        "generated_at": _utc_now(),
        "status": status,
        "admitted": admitted,
        "deployment": str(deployment),
        "allow_plan_only": bool(allow_plan_only),
        "claim_boundary": "external_multimodal_encoder_evidence_required",
        "min_modalities": int(min_modalities),
        "min_payloads": int(min_payloads),
        "min_queries": int(min_queries),
        "min_precision_at_1": float(min_precision_at_1),
        "min_cross_modal_precision_at_1": float(min_cross_modal_precision_at_1),
        "max_query_p99_ms": float(max_query_p99_ms),
        "max_encode_p95_ms": float(max_encode_p95_ms),
        "require_object_store": bool(require_object_store),
        "summary": {
            "status": status,
            "admitted": admitted,
            "structured_status": structured_status,
            "structured_pass": structured_pass,
            "requested_evidence_status": requested_status,
            "required_artifact": EXTERNAL_EVIDENCE,
            "structured_modality_count": structured_summary.get("modality_count", 0),
            "external_modality_count": requested.get("modality_count", 0),
            "external_payload_count": requested.get("payload_count", 0),
            "external_query_count": requested.get("query_count", 0),
            "blocking_issue_count": len(dict.fromkeys(issues + requested_issues)),
            "warning_count": len(warnings),
        },
        "structured_contract": {
            "status": structured_status,
            "passed": structured_pass,
            "schema": structured.get("schema"),
            "artifact": STRUCTURED_REPORT,
            "claim_boundary": structured.get("claim_boundary", ""),
            "summary": structured_summary,
        },
        "required_evidence": {
            "id": "external_multimodal_encoder",
            "title": "External multimodal encoder and object-store benchmark",
            "status": requested_status,
            "artifact": EXTERNAL_EVIDENCE,
            "evidence": requested.get("evidence")
            or "missing external multimodal encoder evidence",
            "issues": requested_issues,
            "claim_unlocked": (
                "Production multimodal encoder quality, cross-modal recall, "
                "object-store persistence, and latency SLO."
            ),
        },
        "requested_evidence": {
            **requested,
            "min_modalities": int(min_modalities),
            "min_payloads": int(min_payloads),
            "min_queries": int(min_queries),
            "min_precision_at_1": float(min_precision_at_1),
            "min_cross_modal_precision_at_1": float(min_cross_modal_precision_at_1),
            "max_query_p99_ms": float(max_query_p99_ms),
            "max_encode_p95_ms": float(max_encode_p95_ms),
            "require_object_store": bool(require_object_store),
        },
        "issues": list(dict.fromkeys(issues + requested_issues)),
        "warnings": warnings,
        "next_actions": list(dict.fromkeys(next_actions)),
        "source_artifacts": {
            "structured_contract": STRUCTURED_REPORT,
            "required_result": EXTERNAL_EVIDENCE,
        },
    }


def render_multimodal_admission_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    required = payload["required_evidence"]
    requested = payload.get("requested_evidence") or {}
    lines = [
        "# WaveMind Multimodal Admission",
        "",
        "This gate decides whether multimodal memory is safe to describe as",
        "production-ready. The deterministic structured-memory report proves the",
        "API and persistence contract; production claims require a separate",
        "external encoder run against real image/audio/video/3D assets and a",
        "remote object store.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| status | `{payload['status']}` |",
        f"| admitted | `{str(payload['admitted']).lower()}` |",
        f"| deployment | `{payload['deployment']}` |",
        f"| structured status | `{summary['structured_status']}` |",
        f"| requested evidence | `{summary['requested_evidence_status']}` |",
        f"| min modalities | `{payload['min_modalities']}` |",
        f"| min payloads | `{payload['min_payloads']}` |",
        f"| min queries | `{payload['min_queries']}` |",
        f"| min precision@1 | `{payload['min_precision_at_1']}` |",
        f"| min cross-modal precision@1 | `{payload['min_cross_modal_precision_at_1']}` |",
        f"| max query p99 ms | `{payload['max_query_p99_ms']}` |",
        f"| max encode p95 ms | `{payload['max_encode_p95_ms']}` |",
        "",
        "## Required Evidence",
        "",
        "| id | status | artifact | evidence |",
        "|---|---|---|---|",
        "| {id} | `{status}` | `{artifact}` | {evidence} |".format(
            id=required["id"],
            status=required["status"],
            artifact=required["artifact"],
            evidence=str(required.get("evidence") or "").replace("|", "\\|"),
        ),
        "",
        "## Requested Evidence",
        "",
        "| check | value |",
        "|---|---:|",
        f"| status | `{requested.get('status')}` |",
        f"| modalities | `{requested.get('modality_count', 0)}` |",
        f"| payloads | `{requested.get('payload_count', 0)}` |",
        f"| queries | `{requested.get('query_count', 0)}` |",
        f"| environment | `{requested.get('environment', '')}` |",
        f"| object store | `{requested.get('object_store', '')}` |",
        "",
        "## Checks",
        "",
        "| check | status | value | target |",
        "|---|---|---:|---:|",
    ]
    for check in requested.get("checks", []):
        status = "pass" if check.get("pass") else "action_required"
        lines.append(
            f"| {check.get('name')} | `{status}` | `{check.get('value')}` | `{check.get('op')} {check.get('target')}` |"
        )
    lines.extend(["", "## Issues", ""])
    for issue in payload.get("issues", []):
        lines.append(f"- {issue}")
    lines.extend(["", "## Next Actions", ""])
    for action in payload.get("next_actions", []):
        lines.append(f"- {action}")
    return "\n".join(lines) + "\n"
