from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def render_leaderboard_status(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(root)
    load_errors: list[str] = []

    matrix = _load_json(root / "benchmarks" / "benchmark_matrix_results.json", load_errors)
    audit = _load_json(root / "benchmarks" / "benchmark_artifact_audit.json", load_errors)
    readiness = _load_json(root / "benchmarks" / "production_readiness_results.json", load_errors)
    evidence = _load_json(root / "benchmarks" / "production_evidence_results.json", load_errors)
    evidence_bundle = _load_json(
        root / "benchmarks" / "production_evidence_bundle_results.json",
        load_errors,
        required=False,
    )
    scale_run_plan = _load_json(
        root / "benchmarks" / "production_scale_run_plan.json",
        load_errors,
        required=False,
    )
    preflight = _load_json(
        root / "benchmarks" / "production_evidence_preflight_results.json",
        load_errors,
        required=False,
    )

    benchmarks = matrix.get("benchmarks") if isinstance(matrix.get("benchmarks"), list) else []
    status_counts = Counter(
        str(entry.get("status", "unknown"))
        for entry in benchmarks
        if isinstance(entry, dict)
    )
    category_counts = Counter(
        str(entry.get("category", "unknown"))
        for entry in benchmarks
        if isinstance(entry, dict)
    )

    audit_status = str(audit.get("status", "missing"))
    readiness_status = str(readiness.get("overall_status", "missing"))
    evidence_status = str(evidence.get("overall_status", "missing"))
    preflight_status = str(preflight.get("overall_status", "missing"))
    publishing_status = _publishing_status(
        audit_status=audit_status,
        readiness_status=readiness_status,
        evidence_status=evidence_status,
        load_errors=load_errors,
    )

    action_required = [
        {
            "id": str(requirement.get("id", "unknown")),
            "title": str(requirement.get("title", "unknown")),
            "artifact": str(requirement.get("artifact", "")),
            "claim_unlocked": str(requirement.get("claim_unlocked", "")),
            "issues": requirement.get("issues", []),
        }
        for requirement in evidence.get("requirements", [])
        if isinstance(requirement, dict)
        and str(requirement.get("status", "")) == "action_required"
    ]

    return {
        "schema": "wavemind.leaderboard_status.v1",
        "generated_at": _status_timestamp(matrix, audit, readiness, evidence),
        "source_ref": matrix.get("source_ref"),
        "workflow_run_id": matrix.get("workflow_run_id"),
        "refresh_profile": matrix.get("refresh_profile"),
        "public_url": "https://caspiang.github.io/wavemind/",
        "publishing_status": publishing_status,
        "benchmark_matrix": {
            "schema": matrix.get("schema"),
            "generated_at": matrix.get("generated_at"),
            "implemented_count": status_counts.get("implemented", 0),
            "runner_ready_count": status_counts.get("runner-ready", 0),
            "planned_count": status_counts.get("planned", 0),
            "total_count": sum(status_counts.values()),
            "status_counts": dict(sorted(status_counts.items())),
            "category_counts": dict(sorted(category_counts.items())),
        },
        "artifact_audit": {
            "schema": audit.get("schema"),
            "status": audit_status,
            "checked_at": audit.get("checked_at"),
            "age_days": audit.get("age_days"),
            "max_age_days": audit.get("max_age_days"),
            "errors": audit.get("errors", []),
        },
        "production_readiness": {
            "schema": readiness.get("schema"),
            "overall_status": readiness_status,
            "readiness_score": readiness.get("readiness_score"),
            "summary": readiness.get("summary", {}),
        },
        "strict_production_evidence": {
            "schema": evidence.get("schema"),
            "overall_status": evidence_status,
            "summary": evidence.get("summary", {}),
            "action_required": action_required,
        },
        "production_evidence_bundle": {
            "schema": evidence_bundle.get("schema"),
            "claim_status": evidence_bundle.get("claim_status", "missing"),
            "summary": evidence_bundle.get("summary", {}),
            "next_action_count": len(evidence_bundle.get("next_actions", []))
            if isinstance(evidence_bundle.get("next_actions"), list)
            else 0,
            "production_scale_run_contract": evidence_bundle.get(
                "production_scale_run_contract", {}
            ),
        },
        "production_scale_run_plan": {
            "schema": scale_run_plan.get("schema"),
            "overall_status": (scale_run_plan.get("summary") or {}).get("overall_status", "missing"),
            "ready_count": (scale_run_plan.get("summary") or {}).get("ready_count", 0),
            "action_required_count": (scale_run_plan.get("summary") or {}).get("action_required_count", 0),
            "total_profiles": (scale_run_plan.get("summary") or {}).get("total_profiles", 0),
            "target_memories_total": (scale_run_plan.get("summary") or {}).get(
                "target_memories_total", 0
            ),
            "profiles": (scale_run_plan.get("summary") or {}).get("profiles", []),
        },
        "production_evidence_preflight": {
            "schema": preflight.get("schema"),
            "overall_status": preflight_status,
            "summary": preflight.get("summary", {}),
        },
        "source_files": [
            "benchmarks/benchmark_matrix_results.json",
            "benchmarks/benchmark_artifact_audit.json",
            "benchmarks/production_readiness_results.json",
            "benchmarks/production_evidence_results.json",
            "benchmarks/production_evidence_preflight_results.json",
            "benchmarks/production_evidence_bundle_results.json",
            "benchmarks/production_scale_run_plan.json",
        ],
        "load_errors": load_errors,
    }


def _load_json(path: Path, errors: list[str], *, required: bool = True) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            errors.append(f"missing {path.as_posix()}")
        return {}
    except Exception as exc:
        errors.append(f"cannot read {path.as_posix()}: {exc}")
        return {}


def _publishing_status(
    *,
    audit_status: str,
    readiness_status: str,
    evidence_status: str,
    load_errors: list[str],
) -> str:
    if load_errors:
        return "blocked"
    if audit_status != "pass":
        return "blocked"
    if readiness_status != "pass":
        return "blocked"
    if evidence_status == "fail":
        return "blocked"
    if evidence_status == "action_required":
        return "publishable_with_claim_limits"
    if evidence_status == "pass":
        return "publishable"
    return "publishable_with_unknown_evidence"


def _status_timestamp(*payloads: dict[str, Any]) -> str | None:
    for key in ("checked_at", "generated_at"):
        values = [
            str(payload.get(key))
            for payload in payloads
            if isinstance(payload.get(key), str) and payload.get(key)
        ]
        if values:
            return max(values)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/data/leaderboard-status.json"))
    args = parser.parse_args()

    payload = render_leaderboard_status()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
