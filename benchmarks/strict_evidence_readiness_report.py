from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STRICT_REQUIREMENT_IDS = {
    "external_http_cluster",
    "external_http_active_active",
    "serverless_remote_telemetry",
    "qdrant_10m_service",
    "qdrant_sharded_10m_service",
    "pgvector_10m_service",
    "faiss_ivfpq_50m",
    "hundred_million_remote_load",
}
SCALE_REQUIREMENT_IDS = {
    "qdrant_10m_service",
    "qdrant_sharded_10m_service",
    "pgvector_10m_service",
    "faiss_ivfpq_50m",
    "hundred_million_remote_load",
}
SENSITIVE_MARKERS = ("sk-", "ghp_", "github_pat_", "postgresql://", "://user:pass@")


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _by_id(rows: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("id")): row
        for row in rows
        if isinstance(row, dict) and row.get("id") is not None
    }


def _scale_gap_by_requirement(rows: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("requirement_id")): row
        for row in rows
        if isinstance(row, dict) and row.get("requirement_id") is not None
    }


def _scale_plan_by_artifact(rows: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("output_artifact")).replace("\\", "/"): row
        for row in rows
        if isinstance(row, dict) and row.get("output_artifact") is not None
    }


def _locked_claim_for(
    requirement_id: str,
    artifact: str,
    release_claims: dict[str, Any],
) -> str:
    artifact = artifact.replace("\\", "/")
    for row in release_claims.get("locked_claims", []):
        if not isinstance(row, dict):
            continue
        evidence = str(row.get("evidence") or "")
        if evidence == artifact:
            return str(row.get("claim") or "")
        if requirement_id in SCALE_REQUIREMENT_IDS and "large-N" in evidence:
            return str(row.get("claim") or "")
    return ""


def _blocker_category(row: dict[str, Any]) -> str:
    if row.get("strict_status") == "pass":
        return "complete"
    missing_env = row.get("missing_env") or []
    issues = " ".join(str(item).lower() for item in row.get("issues") or [])
    artifact_exists = bool(row.get("artifact_exists"))
    if missing_env:
        return "missing_env"
    if not artifact_exists:
        return "missing_artifact"
    if "remote" in issues or "staging" in issues or "production" in issues:
        return "remote_required"
    if row.get("target_memories") and row.get("target_memories") >= 10_000_000:
        return "large_n_run_required"
    return "validation_required"


def _strict_validation_command() -> str:
    return (
        "python benchmarks/production_evidence_gate.py "
        "--output benchmarks/production_evidence_results.json "
        "--markdown-output benchmarks/PRODUCTION_EVIDENCE.md --strict"
    )


def _post_ingest_refresh_command() -> str:
    return (
        "python benchmarks/strict_evidence_readiness_report.py "
        "--output benchmarks/strict_evidence_readiness_results.json "
        "--markdown-output benchmarks/STRICT_EVIDENCE_READINESS.md"
    )


def _safe_command(value: Any) -> str:
    return str(value or "").replace("\\", "/")


def _contains_secret_material(payload: dict[str, Any]) -> bool:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    lowered = serialized.lower()
    return any(marker.lower() in lowered for marker in SENSITIVE_MARKERS)


def build_strict_evidence_readiness_report(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(root)
    strict = _load_json(root / "benchmarks" / "production_evidence_results.json")
    preflight = _load_json(root / "benchmarks" / "production_evidence_preflight_results.json")
    dispatch = _load_json(root / "benchmarks" / "production_evidence_dispatch_results.json")
    scale_plan = _load_json(root / "benchmarks" / "production_scale_run_plan.json")
    scale_gap = _load_json(root / "benchmarks" / "scale_gap_results.json")
    release_claims = _load_json(root / "benchmarks" / "release_claims_results.json")
    leaderboard_status = _load_json(root / "docs" / "data" / "leaderboard-status.json")

    preflight_by_id = _by_id(preflight.get("checks"))
    dispatch_by_id = _by_id(dispatch.get("jobs"))
    scale_gap_by_id = _scale_gap_by_requirement(scale_gap.get("profile_gaps"))
    scale_plan_by_artifact = _scale_plan_by_artifact(scale_plan.get("profiles"))

    rows: list[dict[str, Any]] = []
    for requirement in strict.get("requirements", []):
        if not isinstance(requirement, dict):
            continue
        requirement_id = str(requirement.get("id") or "unknown")
        artifact = _safe_command(requirement.get("artifact"))
        preflight_row = preflight_by_id.get(requirement_id, {})
        dispatch_row = dispatch_by_id.get(requirement_id, {})
        gap_row = scale_gap_by_id.get(requirement_id, {})
        plan_row = scale_plan_by_artifact.get(artifact, {})

        target_memories = int(
            gap_row.get("target_memories")
            or plan_row.get("target_memories")
            or 0
        )
        target_recall = gap_row.get("target_recall_at_k") or plan_row.get("target_recall_at_k")
        target_p99_ms = gap_row.get("target_p99_ms") or plan_row.get("target_p99_ms")
        target_qps = gap_row.get("target_qps") or plan_row.get("target_qps")
        artifact_exists = (root / artifact).exists() if artifact else False

        row = {
            "id": requirement_id,
            "title": str(requirement.get("title") or requirement_id),
            "strict_status": str(requirement.get("status") or "missing"),
            "preflight_status": str(preflight_row.get("status") or "missing"),
            "dispatch_status": str(dispatch_row.get("status") or "missing"),
            "scale_gap_status": str(gap_row.get("status") or ""),
            "workflow": str(dispatch_row.get("workflow") or ""),
            "wave": str(dispatch_row.get("wave") or ""),
            "artifact": artifact,
            "artifact_exists": artifact_exists,
            "output_artifact": _safe_command(
                preflight_row.get("output_artifact") or gap_row.get("output_artifact") or artifact
            ),
            "claim_unlocked": str(requirement.get("claim_unlocked") or ""),
            "locked_claim": _locked_claim_for(requirement_id, artifact, release_claims)
            or str(requirement.get("claim_unlocked") or ""),
            "target_memories": target_memories,
            "target_recall_at_k": target_recall,
            "target_p99_ms": target_p99_ms,
            "target_qps": target_qps,
            "required_env": list(dispatch_row.get("required_env") or preflight_row.get("required_env") or []),
            "missing_env": list(dispatch_row.get("missing_env") or preflight_row.get("missing_env") or []),
            "required_secrets": list(dispatch_row.get("required_secrets") or []),
            "issues": list(dispatch_row.get("issues") or preflight_row.get("issues") or requirement.get("issues") or []),
            "warnings": list(dispatch_row.get("warnings") or preflight_row.get("warnings") or []),
            "local_profile_command": _safe_command(gap_row.get("command") or plan_row.get("command")),
            "safe_dispatch_command": _safe_command(dispatch_row.get("safe_launch_command")),
            "publish_dispatch_command": _safe_command(dispatch_row.get("publish_launch_command")),
            "download_command": _safe_command(dispatch_row.get("download_command")),
            "ingest_command": _safe_command(dispatch_row.get("ingest_command")),
            "strict_validation_command": _strict_validation_command(),
            "post_ingest_refresh_command": _post_ingest_refresh_command(),
            "ready_for_safe_dispatch": str(dispatch_row.get("status") or "") == "ready_to_dispatch",
            "can_auto_run_now": (
                str(dispatch_row.get("status") or "") == "ready_to_dispatch"
                and not list(dispatch_row.get("missing_env") or preflight_row.get("missing_env") or [])
                and not list(dispatch_row.get("required_secrets") or [])
            ),
            "next_action": str(
                gap_row.get("next_action")
                or "Provision prerequisites, run the safe dispatch command, download the artifact, ingest it, then rerun strict validation."
            ),
        }
        if row["can_auto_run_now"]:
            row["next_action"] = (
                "Run the safe dispatch command now, download the resulting artifact, "
                "ingest it, then rerun strict validation."
            )
        row["blocker_category"] = _blocker_category(row)
        rows.append(row)

    represented_ids = {row["id"] for row in rows}
    action_rows = [row for row in rows if row["strict_status"] != "pass"]
    missing_command_rows = [
        row["id"]
        for row in action_rows
        if not row["safe_dispatch_command"] or not row["workflow"]
    ]
    missing_promotion_rows = [
        row["id"]
        for row in action_rows
        if not row["download_command"] or not row["ingest_command"]
    ]
    missing_validation_rows = [
        row["id"]
        for row in action_rows
        if not row["strict_validation_command"] or not row["post_ingest_refresh_command"]
    ]
    scale_plan_rows = scale_plan.get("profiles") if isinstance(scale_plan.get("profiles"), list) else []
    plan_only_boundaries_ok = all(
        str(row.get("claim_boundary") or "").startswith("plan_only")
        for row in scale_plan_rows
        if isinstance(row, dict)
    )
    scale_summary = scale_plan.get("summary") if isinstance(scale_plan.get("summary"), dict) else {}
    target_memories_total = int(scale_summary.get("target_memories_total") or 0)
    freshness_status = (
        leaderboard_status.get("freshness_gate", {}).get("status")
        if isinstance(leaderboard_status.get("freshness_gate"), dict)
        else "missing"
    )
    claim_status = str(release_claims.get("summary", {}).get("claim_status") or release_claims.get("claim_status") or "missing")

    checks = [
        {
            "id": "all_strict_requirements_represented",
            "status": "pass" if represented_ids == STRICT_REQUIREMENT_IDS else "fail",
            "detail": f"{len(represented_ids)}/{len(STRICT_REQUIREMENT_IDS)} strict requirements represented",
        },
        {
            "id": "every_action_required_has_safe_dispatch",
            "status": "pass" if not missing_command_rows else "fail",
            "detail": "missing commands: " + ", ".join(missing_command_rows) if missing_command_rows else "all action-required rows have workflow dispatch commands",
        },
        {
            "id": "every_action_required_has_promotion",
            "status": "pass" if not missing_promotion_rows else "fail",
            "detail": "missing promotion: " + ", ".join(missing_promotion_rows) if missing_promotion_rows else "all action-required rows have download and ingest commands",
        },
        {
            "id": "every_action_required_has_validation",
            "status": "pass" if not missing_validation_rows else "fail",
            "detail": "missing validation: " + ", ".join(missing_validation_rows) if missing_validation_rows else "all action-required rows have strict validation and refresh commands",
        },
        {
            "id": "plan_only_rows_do_not_unlock_claims",
            "status": "pass" if plan_only_boundaries_ok and claim_status == "claims_limited" else "fail",
            "detail": f"claim_status={claim_status}; plan_only_boundaries_ok={plan_only_boundaries_ok}",
        },
        {
            "id": "scale_plan_target_memories_covered",
            "status": "pass" if target_memories_total >= 180_000_000 else "fail",
            "detail": f"target_memories_total={target_memories_total}",
        },
        {
            "id": "source_freshness_gate_passes",
            "status": "pass" if freshness_status == "pass" else "fail",
            "detail": f"leaderboard freshness status={freshness_status}",
        },
    ]
    provisional_payload = {
        "rows": rows,
        "checks": checks,
    }
    checks.append(
        {
            "id": "secret_values_not_serialized",
            "status": "pass" if not _contains_secret_material(provisional_payload) else "fail",
            "detail": "payload contains placeholders and secret names only",
        }
    )

    check_counts: dict[str, int] = {}
    for check in checks:
        status = str(check.get("status") or "unknown")
        check_counts[status] = check_counts.get(status, 0) + 1

    readiness_counts: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    for row in rows:
        readiness_counts[row["dispatch_status"]] = readiness_counts.get(row["dispatch_status"], 0) + 1
        blocker_counts[row["blocker_category"]] = blocker_counts.get(row["blocker_category"], 0) + 1

    status = "pass" if check_counts.get("fail", 0) == 0 else "fail"
    readiness_status = "complete" if not action_rows else (
        "ready_to_dispatch" if all(row["ready_for_safe_dispatch"] for row in action_rows) else "action_required"
    )

    return {
        "schema": "wavemind.strict_evidence_readiness.v1",
        "generated_at": _utc_now(),
        "status": status,
        "readiness_status": readiness_status,
        "claim_status": claim_status,
        "summary": {
            "status": status,
            "readiness_status": readiness_status,
            "claim_status": claim_status,
            "total_requirements": len(rows),
            "action_required_count": len(action_rows),
            "complete_count": len(rows) - len(action_rows),
            "ready_for_safe_dispatch_count": sum(1 for row in rows if row["ready_for_safe_dispatch"]),
            "can_auto_run_now_count": sum(1 for row in rows if row["can_auto_run_now"]),
            "target_memories_total": target_memories_total,
            "check_counts": dict(sorted(check_counts.items())),
            "dispatch_status_counts": dict(sorted(readiness_counts.items())),
            "blocker_counts": dict(sorted(blocker_counts.items())),
        },
        "checks": checks,
        "requirements": rows,
        "source_artifacts": {
            "strict_evidence": "benchmarks/production_evidence_results.json",
            "preflight": "benchmarks/production_evidence_preflight_results.json",
            "dispatch": "benchmarks/production_evidence_dispatch_results.json",
            "scale_run_plan": "benchmarks/production_scale_run_plan.json",
            "scale_gap": "benchmarks/scale_gap_results.json",
            "release_claims": "benchmarks/release_claims_results.json",
            "leaderboard_status": "docs/data/leaderboard-status.json",
        },
        "claim_boundary": (
            "Readiness report only. It does not itself unlock any production claim; "
            "only a matching strict evidence artifact that passes validation does."
        ),
    }


def render_strict_evidence_readiness_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Strict Evidence Readiness",
        "",
        "This report joins the strict evidence gate, environment preflight, GitHub",
        "Actions dispatch plan, large-N scale plan, scale-gap report, release",
        "claim contract, and leaderboard freshness gate. It is a runbook, not",
        "production evidence by itself.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| report status | `{payload['status']}` |",
        f"| readiness status | `{payload['readiness_status']}` |",
        f"| claim status | `{payload['claim_status']}` |",
        f"| total requirements | `{summary['total_requirements']}` |",
        f"| action required | `{summary['action_required_count']}` |",
        f"| ready for safe dispatch | `{summary['ready_for_safe_dispatch_count']}` |",
        f"| can auto-run now | `{summary['can_auto_run_now_count']}` |",
        f"| planned target memories | `{summary['target_memories_total']}` |",
        "",
        "## Integrity Checks",
        "",
        "| check | status | detail |",
        "|---|---|---|",
    ]
    for check in payload.get("checks", []):
        detail = str(check["detail"]).replace("|", "\\|")
        lines.append(
            f"| {check['id']} | `{check['status']}` | {detail} |"
        )

    lines.extend(
        [
            "",
            "## Requirement Runbook",
            "",
            "| requirement | blocker | dispatch | target | artifact | missing env | locked claim |",
            "|---|---|---|---:|---|---|---|",
        ]
    )
    for row in payload.get("requirements", []):
        missing_env = ", ".join(row.get("missing_env") or [])
        locked_claim = str(row.get("locked_claim") or "").replace("|", "\\|")
        lines.append(
            f"| {row['title']} | `{row['blocker_category']}` | `{row['dispatch_status']}` | "
            f"{row.get('target_memories') or ''} | `{row['artifact']}` | `{missing_env}` | {locked_claim} |"
        )

    lines.extend(["", "## Safe Dispatch Commands", ""])
    for row in payload.get("requirements", []):
        command = str(row.get("safe_dispatch_command") or "").replace("|", "\\|")
        lines.append(f"- `{row['id']}`: `{command}`")

    lines.extend(["", "## Promote And Validate", ""])
    if payload.get("requirements"):
        sample = payload["requirements"][0]
        lines.append(f"- Download: `{sample.get('download_command', '')}`")
        lines.append(f"- Ingest: `{sample.get('ingest_command', '')}`")
        lines.append(f"- Strict validation: `{sample.get('strict_validation_command', '')}`")
        lines.append(f"- Refresh readiness: `{sample.get('post_ingest_refresh_command', '')}`")
    lines.append("")
    lines.append(f"Boundary: {payload['claim_boundary']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/strict_evidence_readiness_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/STRICT_EVIDENCE_READINESS.md"),
    )
    args = parser.parse_args()

    payload = build_strict_evidence_readiness_report(PROJECT_ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(
        render_strict_evidence_readiness_markdown(payload),
        encoding="utf-8",
    )
    print(f"strict evidence readiness: {payload['status']} / {payload['readiness_status']}")
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
