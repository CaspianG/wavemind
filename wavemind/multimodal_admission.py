from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STRUCTURED_REPORT = "benchmarks/structured_memory_results.json"
EXTERNAL_EVIDENCE = "benchmarks/multimodal_external_encoder_results.json"
REQUIRED_ENCODER_MODALITIES = ("text", "image", "audio", "video", "3d")
REQUIRED_CROSS_MODAL_PAIRS = (
    ("text", "image"),
    ("image", "text"),
    ("text", "audio"),
    ("audio", "text"),
    ("text", "video"),
    ("video", "text"),
    ("text", "3d"),
    ("3d", "text"),
)
DEFAULT_ENCODING_BUDGETS_MS = {
    "text": 250.0,
    "image": 250.0,
    "audio": 1_000.0,
    "video": 2_000.0,
    "3d": 1_000.0,
}
_DISALLOWED_ENCODER_TOKENS = (
    "descriptor",
    "filename",
    "metadata",
    "ocr",
    "precomputed",
    "synthetic",
    "hash",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


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


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "pass", "passed"}
    return bool(value)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _evidence_check(
    name: str,
    value: Any,
    target: Any,
    passed: bool,
    issue: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "target": target,
        "op": "evidence",
        "pass": bool(passed),
        "issue": "" if passed else issue,
    }


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
    min_modalities: int = 5,
    min_payloads: int = 1_000,
    min_queries: int = 200,
    min_precision_at_1: float = 0.90,
    min_cross_modal_precision_at_1: float = 0.90,
    max_query_p99_ms: float = 250.0,
    max_encode_p95_ms: float | None = None,
    min_assets_per_modality: int = 100,
    min_queries_per_modality: int = 20,
    min_modality_precision_at_1: float = 0.85,
    require_object_store: bool = True,
) -> dict[str, Any]:
    """Validate real local/open-source multimodal benchmark evidence.

    Admission is deliberately content-based, not deployment-based. A local
    run is valid when it uses real or publicly licensed assets, real media
    encoders, explicit shared embedding spaces, an S3-compatible lifecycle
    (local MinIO is supported), and reproducible quality/latency evidence.
    Descriptor, metadata, OCR-only, synthetic-vector, and precomputed-vector
    shortcuts are rejected.
    """

    if payload is None:
        return {
            "status": "action_required",
            "evidence": "missing real multimodal encoder evidence",
            "issues": [
                f"missing required artifact: {EXTERNAL_EVIDENCE}",
            ],
            "checks": [],
        }

    modalities = [str(value).strip().lower() for value in _list(payload.get("modalities"))]
    modality_set = set(modalities)
    modality_count = _as_int(
        payload.get("modality_count") or _metric(payload, "modality_count"),
        default=len(modalities),
    )
    payload_count = _as_int(payload.get("payload_count") or _metric(payload, "payload_count"))
    query_count = _as_int(payload.get("query_count") or _metric(payload, "query_count"))
    environment = str(payload.get("environment") or payload.get("node_mode") or "")
    source = str(payload.get("source") or "")
    object_store = str(payload.get("object_store") or payload.get("asset_store") or "")
    dataset = _mapping(payload.get("dataset"))
    modality_metrics = _mapping(payload.get("modality_metrics"))
    lifecycle = _mapping(payload.get("lifecycle"))
    leakage = _mapping(payload.get("leakage_checks"))
    repeatability = _mapping(payload.get("repeatability"))
    evidence_files = _mapping(payload.get("evidence_files"))
    source_sha = str(payload.get("source_sha") or "")
    environment_fingerprint = _mapping(payload.get("environment_fingerprint"))

    asset_source = str(
        payload.get("asset_source")
        or dataset.get("asset_source")
        or dataset.get("source_type")
        or ""
    ).strip().lower()
    real_asset_source = asset_source in {
        "real",
        "real_assets",
        "public",
        "public_dataset",
        "publicly_licensed",
        "real_public_assets",
    }
    object_store_kind = str(
        payload.get("object_store_backend")
        or lifecycle.get("object_store_backend")
        or object_store
    ).lower()
    s3_compatible = any(
        token in object_store_kind for token in ("minio", "s3", "s3-compatible")
    )
    object_store_verified = _as_bool(
        lifecycle.get("object_store_pass")
        if "object_store_pass" in lifecycle
        else _metric(payload, "object_store_pass", "object_store_verified")
    )

    space_registry: dict[str, set[str]] = {}
    raw_spaces = payload.get("shared_spaces")
    if isinstance(raw_spaces, dict):
        space_rows = [
            {"id": key, **(_mapping(value))}
            for key, value in raw_spaces.items()
        ]
    else:
        space_rows = [row for row in _list(raw_spaces) if isinstance(row, dict)]
    for row in space_rows:
        space_id = str(row.get("id") or row.get("space_id") or "").strip()
        members = {
            str(value).strip().lower()
            for value in _list(row.get("modalities"))
            if str(value).strip()
        }
        if space_id:
            space_registry[space_id] = members

    pair_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _list(payload.get("cross_modal_pairs")):
        if not isinstance(row, dict):
            continue
        query_modality = str(row.get("query_modality") or row.get("from") or "").lower()
        target_modality = str(row.get("target_modality") or row.get("to") or "").lower()
        if query_modality and target_modality:
            pair_rows[(query_modality, target_modality)] = row

    checks: list[dict[str, Any]] = [
        _evidence_check(
            "real_public_assets",
            asset_source,
            "real or publicly licensed assets",
            real_asset_source,
            "asset_source must identify real or publicly licensed assets",
        ),
        _evidence_check(
            "dataset_identity",
            {
                "name": dataset.get("name"),
                "revision": dataset.get("revision"),
                "license": dataset.get("license"),
            },
            "name + pinned revision + license",
            all(str(dataset.get(key) or "").strip() for key in ("name", "revision", "license")),
            "dataset name, revision, and license must be pinned",
        ),
        _evidence_check(
            "dataset_checksums",
            {
                "manifest": dataset.get("manifest_sha256"),
                "ground_truth": dataset.get("ground_truth_sha256"),
            },
            "two SHA-256 checksums",
            bool(_SHA256_RE.fullmatch(str(dataset.get("manifest_sha256") or "")))
            and bool(_SHA256_RE.fullmatch(str(dataset.get("ground_truth_sha256") or ""))),
            "dataset manifest and ground-truth SHA-256 checksums are required",
        ),
        _evidence_check(
            "source_sha",
            source_sha,
            "exact 40-character git SHA",
            bool(_GIT_SHA_RE.fullmatch(source_sha)),
            "source_sha must be an exact 40-character git SHA",
        ),
        _evidence_check(
            "environment_fingerprint",
            sorted(environment_fingerprint),
            "python, platform, hardware, dependency lock",
            all(
                str(environment_fingerprint.get(key) or "").strip()
                for key in ("python", "platform", "hardware", "dependency_lock_sha256")
            )
            and bool(
                _SHA256_RE.fullmatch(
                    str(environment_fingerprint.get("dependency_lock_sha256") or "")
                )
            ),
            "environment fingerprint must pin Python, platform, hardware, and dependency lock",
        ),
        _check(
            "modalities",
            modality_count,
            int(min_modalities),
            ">=",
            f"modality_count must be >= {int(min_modalities)}",
        ),
        _evidence_check(
            "required_encoder_modalities",
            sorted(modality_set),
            list(REQUIRED_ENCODER_MODALITIES),
            set(REQUIRED_ENCODER_MODALITIES).issubset(modality_set),
            "text, image, audio, video, and 3d encoder evidence is required",
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
            _metric(payload, "precision_at_1", "macro_precision_at_1"),
            float(min_precision_at_1),
            ">=",
            f"macro precision_at_1 must be >= {float(min_precision_at_1):.3f}",
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
            "mixed_multimodal_precision_at_1",
            _metric(payload, "mixed_multimodal_precision_at_1"),
            float(min_cross_modal_precision_at_1),
            ">=",
            "mixed multimodal precision_at_1 must satisfy the cross-modal threshold",
        ),
        _check(
            "persisted_vector_parity",
            _metric(payload, "persisted_vector_parity", "vector_persistence_rate"),
            1.0,
            ">=",
            "persisted-vector parity must be 1.000",
        ),
        _check(
            "retrieval_p99_ms",
            _metric(payload, "retrieval_p99_ms"),
            float(max_query_p99_ms),
            "<=",
            f"retrieval_p99_ms must be <= {float(max_query_p99_ms):.3f}",
        ),
        _check(
            "error_rate",
            _metric(payload, "error_rate"),
            0.0,
            "<=",
            "error_rate must be zero",
        ),
        _check(
            "batch_throughput",
            _metric(payload, "batch_throughput_assets_per_second"),
            0.000001,
            ">=",
            "batch throughput must be measured",
        ),
        _evidence_check(
            "shared_space_registry",
            sorted(space_registry),
            "explicit non-empty shared-space registry",
            bool(space_registry),
            "shared embedding spaces must be explicitly registered",
        ),
        _evidence_check(
            "leakage_checks",
            leakage,
            "pass with filename/caption/id/metadata leakage disabled",
            _as_bool(leakage.get("pass"))
            and all(
                not _as_bool(leakage.get(key))
                for key in (
                    "filename_leakage",
                    "caption_leakage",
                    "id_leakage",
                    "metadata_leakage",
                )
            ),
            "leakage audit must pass without filename, caption, ID, or metadata leakage",
        ),
        _evidence_check(
            "repeatability",
            repeatability,
            "at least 3 runs with one stable verdict",
            _as_int(repeatability.get("run_count")) >= 3
            and _as_bool(repeatability.get("stable_verdict"))
            and len(
                {
                    str(value)
                    for value in _list(repeatability.get("verdicts"))
                    if str(value)
                }
            )
            == 1,
            "three sequential runs on one SHA must produce the same verdict",
        ),
        _evidence_check(
            "evidence_files",
            sorted(evidence_files),
            "per-query and per-asset files with SHA-256",
            all(
                isinstance(evidence_files.get(key), dict)
                and str(evidence_files[key].get("path") or "").strip()
                and bool(
                    _SHA256_RE.fullmatch(
                        str(evidence_files[key].get("sha256") or "")
                    )
                )
                for key in ("per_query", "per_asset")
            ),
            "per-query and per-asset evidence files with checksums are required",
        ),
    ]

    if require_object_store:
        checks.extend(
            [
                _evidence_check(
                    "object_store_backend",
                    object_store_kind,
                    "verified S3-compatible store (local MinIO allowed)",
                    s3_compatible,
                    "object store must be S3-compatible; local MinIO is supported",
                ),
                _evidence_check(
                    "object_store_verified",
                    object_store_verified,
                    True,
                    object_store_verified,
                    "object-store lifecycle verification must pass",
                ),
            ]
        )

    lifecycle_requirements = (
        "ingest_pass",
        "checksum_pass",
        "reload_pass",
        "persistence_pass",
        "namespace_isolation_pass",
        "ttl_pass",
        "physical_delete_pass",
        "tombstone_pass",
        "backup_restore_pass",
        "orphan_cleanup_pass",
    )
    for name in lifecycle_requirements:
        value = _as_bool(lifecycle.get(name))
        checks.append(
            _evidence_check(
                f"lifecycle_{name}",
                value,
                True,
                value,
                f"lifecycle check {name} must pass",
            )
        )

    for modality in REQUIRED_ENCODER_MODALITIES:
        row = _mapping(modality_metrics.get(modality))
        backend = str(row.get("encoder_backend") or row.get("backend") or "").strip()
        model_revision = str(row.get("model_revision") or "").strip()
        space_ids = {
            str(value).strip()
            for value in _list(row.get("shared_space_ids"))
            if str(value).strip()
        }
        single_space = str(row.get("shared_space_id") or "").strip()
        if single_space:
            space_ids.add(single_space)
        backend_allowed = bool(backend) and not any(
            token in backend.lower() for token in _DISALLOWED_ENCODER_TOKENS
        )
        spaces_valid = bool(space_ids) and all(
            space_id in space_registry
            and modality in space_registry[space_id]
            for space_id in space_ids
        )
        encode_p95 = _as_float(row.get("encode_p95_ms"))
        budget = (
            float(max_encode_p95_ms)
            if max_encode_p95_ms is not None
            else DEFAULT_ENCODING_BUDGETS_MS[modality]
        )
        checks.extend(
            [
                _check(
                    f"{modality}_asset_count",
                    _as_int(row.get("asset_count")),
                    int(min_assets_per_modality),
                    ">=",
                    f"{modality} asset_count must be >= {int(min_assets_per_modality)}",
                ),
                _check(
                    f"{modality}_query_count",
                    _as_int(row.get("query_count")),
                    int(min_queries_per_modality),
                    ">=",
                    f"{modality} query_count must be >= {int(min_queries_per_modality)}",
                ),
                _check(
                    f"{modality}_precision_at_1",
                    _as_float(row.get("precision_at_1")),
                    float(min_modality_precision_at_1),
                    ">=",
                    f"{modality} precision_at_1 must be >= {float(min_modality_precision_at_1):.3f}",
                ),
                _check(
                    f"{modality}_encode_p95_ms",
                    encode_p95,
                    budget,
                    "<=",
                    f"{modality} encode p95 must be <= {budget:.3f} ms",
                ),
                _evidence_check(
                    f"{modality}_real_encoder",
                    backend,
                    "real local encoder backend",
                    backend_allowed,
                    f"{modality} backend must be real and may not use descriptor/precomputed fallbacks",
                ),
                _evidence_check(
                    f"{modality}_model_revision",
                    model_revision,
                    "pinned model revision",
                    bool(model_revision),
                    f"{modality} model revision must be pinned",
                ),
                _evidence_check(
                    f"{modality}_shared_spaces",
                    sorted(space_ids),
                    "registered compatible shared space",
                    spaces_valid,
                    f"{modality} shared-space identifiers are missing or incompatible",
                ),
            ]
        )

    for pair in REQUIRED_CROSS_MODAL_PAIRS:
        row = pair_rows.get(pair, {})
        space_id = str(row.get("shared_space_id") or "").strip()
        compatible = (
            bool(space_id)
            and space_id in space_registry
            and set(pair).issubset(space_registry[space_id])
        )
        prefix = f"{pair[0]}_to_{pair[1]}"
        checks.extend(
            [
                _check(
                    f"{prefix}_query_count",
                    _as_int(row.get("query_count")),
                    int(min_queries_per_modality),
                    ">=",
                    f"{prefix} query_count must be >= {int(min_queries_per_modality)}",
                ),
                _check(
                    f"{prefix}_precision_at_1",
                    _as_float(row.get("precision_at_1")),
                    float(min_modality_precision_at_1),
                    ">=",
                    f"{prefix} precision_at_1 must be >= {float(min_modality_precision_at_1):.3f}",
                ),
                _evidence_check(
                    f"{prefix}_shared_space",
                    space_id,
                    "registered space containing both modalities",
                    compatible,
                    f"{prefix} must use one explicit compatible shared space",
                ),
            ]
        )

    issues = [str(check["issue"]) for check in checks if not check["pass"]]
    return {
        "status": "pass" if not issues else "fail",
        "evidence": "real local/open-source multimodal encoder evidence"
        if not issues
        else "multimodal evidence does not satisfy production admission",
        "issues": issues,
        "checks": checks,
        "modality_count": modality_count,
        "payload_count": payload_count,
        "query_count": query_count,
        "modalities": modalities,
        "environment": environment,
        "source": source,
        "object_store": object_store,
        "asset_source": asset_source,
        "shared_space_count": len(space_registry),
        "cross_modal_pair_count": len(pair_rows),
    }


def evaluate_multimodal_admission(
    root: Path = PROJECT_ROOT,
    *,
    deployment: str = "production",
    min_modalities: int = 5,
    min_payloads: int = 1_000,
    min_queries: int = 200,
    min_precision_at_1: float = 0.90,
    min_cross_modal_precision_at_1: float = 0.90,
    max_query_p99_ms: float = 250.0,
    max_encode_p95_ms: float | None = None,
    min_assets_per_modality: int = 100,
    min_queries_per_modality: int = 20,
    min_modality_precision_at_1: float = 0.85,
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
        min_assets_per_modality=min_assets_per_modality,
        min_queries_per_modality=min_queries_per_modality,
        min_modality_precision_at_1=min_modality_precision_at_1,
        require_object_store=require_object_store,
    )
    requested_status = str(requested.get("status") or "missing")

    issues: list[str] = []
    warnings: list[str] = []
    if not structured_pass:
        issues.append(f"structured_memory contract is not pass: status={structured_status}")
    if requested_status != "pass":
        issues.append(
            "real_multimodal_encoder artifact does not satisfy requested rollout: "
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
        issues.append("max_retrieval_p99_ms must be positive.")
    if max_encode_p95_ms is not None and float(max_encode_p95_ms) <= 0:
        issues.append("max_encode_p95_ms must be positive.")
    if int(min_assets_per_modality) < 1:
        issues.append("min_assets_per_modality must be positive.")
    if int(min_queries_per_modality) < 1:
        issues.append("min_queries_per_modality must be positive.")
    if not 0 < float(min_modality_precision_at_1) <= 1:
        issues.append("min_modality_precision_at_1 must be in (0, 1].")

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
            "Proceed with multimodal rollout while monitoring per-modality quality, shared-space compatibility, lifecycle safety, retrieval p99, and encoding budgets."
        )
    elif status == "plan_only":
        next_actions.append(
            "Do not claim production multimodal quality yet; run the local open-source benchmark against real public assets and verified MinIO-backed payloads first."
        )
    else:
        next_actions.append(
            "Keep production multimodal claims locked until structured memory and real local encoder evidence both pass."
        )
    next_actions.append(
        "Commit benchmarks/multimodal_external_encoder_results.json only after the real-asset benchmark and lifecycle checks pass."
    )

    requested_issues = list(requested.get("issues") or [])
    return {
        "schema": "wavemind.multimodal_admission.v2",
        "generated_at": _utc_now(),
        "status": status,
        "admitted": admitted,
        "deployment": str(deployment),
        "allow_plan_only": bool(allow_plan_only),
        "claim_boundary": "real_multimodal_encoder_and_lifecycle_evidence_required",
        "min_modalities": int(min_modalities),
        "min_payloads": int(min_payloads),
        "min_queries": int(min_queries),
        "min_precision_at_1": float(min_precision_at_1),
        "min_cross_modal_precision_at_1": float(min_cross_modal_precision_at_1),
        "max_retrieval_p99_ms": float(max_query_p99_ms),
        "max_query_p99_ms": float(max_query_p99_ms),
        "max_encode_p95_ms": (
            None if max_encode_p95_ms is None else float(max_encode_p95_ms)
        ),
        "encoding_budgets_ms": {
            key: (
                float(max_encode_p95_ms)
                if max_encode_p95_ms is not None
                else value
            )
            for key, value in DEFAULT_ENCODING_BUDGETS_MS.items()
        },
        "min_assets_per_modality": int(min_assets_per_modality),
        "min_queries_per_modality": int(min_queries_per_modality),
        "min_modality_precision_at_1": float(min_modality_precision_at_1),
        "require_object_store": bool(require_object_store),
        "summary": {
            "status": status,
            "admitted": admitted,
            "structured_status": structured_status,
            "structured_pass": structured_pass,
            "requested_evidence_status": requested_status,
            "required_artifact": EXTERNAL_EVIDENCE,
            "structured_modality_count": structured_summary.get("modality_count", 0),
            "evidence_modality_count": requested.get("modality_count", 0),
            "evidence_payload_count": requested.get("payload_count", 0),
            "evidence_query_count": requested.get("query_count", 0),
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
            "id": "real_multimodal_encoder",
            "title": "Real local multimodal encoder and MinIO lifecycle benchmark",
            "status": requested_status,
            "artifact": EXTERNAL_EVIDENCE,
            "evidence": requested.get("evidence")
            or "missing real multimodal encoder evidence",
            "issues": requested_issues,
            "claim_unlocked": (
                "Production multimodal encoder quality, cross-modal recall, "
                "MinIO lifecycle safety, reproducibility, and latency SLO."
            ),
        },
        "requested_evidence": {
            **requested,
            "min_modalities": int(min_modalities),
            "min_payloads": int(min_payloads),
            "min_queries": int(min_queries),
            "min_precision_at_1": float(min_precision_at_1),
            "min_cross_modal_precision_at_1": float(min_cross_modal_precision_at_1),
            "max_retrieval_p99_ms": float(max_query_p99_ms),
            "max_query_p99_ms": float(max_query_p99_ms),
            "max_encode_p95_ms": (
                None if max_encode_p95_ms is None else float(max_encode_p95_ms)
            ),
            "encoding_budgets_ms": {
                key: (
                    float(max_encode_p95_ms)
                    if max_encode_p95_ms is not None
                    else value
                )
                for key, value in DEFAULT_ENCODING_BUDGETS_MS.items()
            },
            "min_assets_per_modality": int(min_assets_per_modality),
            "min_queries_per_modality": int(min_queries_per_modality),
            "min_modality_precision_at_1": float(min_modality_precision_at_1),
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
        "local open-source encoder run against real text/image/audio/video/3D",
        "assets and a verified S3-compatible lifecycle. Local MinIO is valid;",
        "descriptor, metadata, OCR-only, synthetic, and precomputed shortcuts are not.",
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
        f"| max retrieval p99 ms | `{payload['max_retrieval_p99_ms']}` |",
        f"| per-modality encode budgets ms | `{payload['encoding_budgets_ms']}` |",
        f"| min assets per modality | `{payload['min_assets_per_modality']}` |",
        f"| min queries per modality | `{payload['min_queries_per_modality']}` |",
        f"| min modality precision@1 | `{payload['min_modality_precision_at_1']}` |",
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
