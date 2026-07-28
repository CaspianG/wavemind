from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = "benchmarks/experienced_work_agent_results.json"
DATASET_REVISION = "experienced-work-agent-v1-frozen-20260728"
DATASET_FINGERPRINT = (
    "0d8a6b2de3e18f6273f3b148e6fb4b1fbfb7fa0b79dd82c42efb3973caf41225"
)
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def evaluate_experience_quality_admission(
    root: Path = PROJECT_ROOT,
    *,
    expected_source_sha: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    payload = _load_json(root / ARTIFACT)
    checks: list[dict[str, Any]] = []
    if payload is None:
        checks.append(
            _check(
                "artifact",
                False,
                "missing",
                ARTIFACT,
                f"missing required artifact: {ARTIFACT}",
            )
        )
        return _result(checks, source_sha="")

    dataset = _mapping(payload.get("dataset"))
    protocol = _mapping(payload.get("protocol"))
    training = _mapping(payload.get("training"))
    uplift = _mapping(payload.get("uplift"))
    source_sha = str(payload.get("source_sha") or "")
    source_ok = bool(_GIT_SHA_RE.fullmatch(source_sha)) and (
        expected_source_sha is None or source_sha == expected_source_sha
    )

    checks.extend(
        [
            _check(
                "artifact-schema",
                payload.get("schema")
                == "wavemind.experienced_work_agent_benchmark.v1"
                and payload.get("status") == "pass",
                {
                    "schema": payload.get("schema"),
                    "status": payload.get("status"),
                },
                "passing experienced-work-agent v1 artifact",
                "benchmark artifact schema or status is invalid",
            ),
            _check(
                "source-sha",
                source_ok,
                source_sha,
                expected_source_sha or "exact 40-character git SHA",
                "artifact source_sha is missing or does not match",
            ),
            _check(
                "frozen-split",
                dataset.get("revision") == DATASET_REVISION
                and dataset.get("fingerprint_sha256") == DATASET_FINGERPRINT
                and _as_int(dataset.get("training_trajectories")) == 60
                and _as_int(dataset.get("held_out_tasks")) == 30
                and dataset.get("split_frozen_before_training") is True
                and dataset.get("metadata_leakage") is False,
                {
                    "revision": dataset.get("revision"),
                    "fingerprint_sha256": dataset.get("fingerprint_sha256"),
                    "training_trajectories": dataset.get(
                        "training_trajectories"
                    ),
                    "held_out_tasks": dataset.get("held_out_tasks"),
                    "metadata_leakage": dataset.get("metadata_leakage"),
                },
                "frozen 60/30 split with exact fingerprint and no leakage",
                "frozen split provenance is incomplete or changed",
            ),
            _check(
                "fair-protocol",
                all(
                    protocol.get(name) is True
                    for name in (
                        "same_held_out_tasks",
                        "same_runtime_verifiers",
                        "same_tool_implementations",
                        "no_paid_api",
                        "experience_promotion_gates",
                        "paired_latency_samples",
                    )
                )
                and _as_int(protocol.get("core_top_k")) == 3
                and _as_int(protocol.get("latency_repetitions_per_case")) >= 3,
                protocol,
                (
                    "same tasks, runtimes, tools, gated experience promotion, "
                    "and at least three paired latency samples per case"
                ),
                "benchmark protocol is not comparable across engines",
            ),
            _check(
                "training-evidence",
                _as_int(training.get("successful")) == 48
                and _as_int(training.get("failed")) == 12
                and _as_int(training.get("active_strategies")) == 6,
                training,
                "48 verified successes, 12 observed failures, 6 active strategies",
                "training evidence does not match the frozen protocol",
            ),
            _uplift_check(
                "task-success-uplift",
                uplift,
                "task_success_absolute",
                minimum=0.15,
            ),
            _uplift_check(
                "repeated-error-reduction",
                uplift,
                "repeated_error_relative_reduction",
                minimum=0.50,
            ),
            _uplift_check(
                "tool-step-reduction",
                uplift,
                "tool_step_relative_reduction",
                minimum=0.25,
            ),
            _uplift_check(
                "context-token-reduction",
                uplift,
                "context_token_relative_reduction",
                minimum=0.35,
            ),
            _check(
                "p95-latency",
                _as_float(
                    uplift.get("p95_latency_regression"),
                    default=float("inf"),
                )
                <= 0.20,
                uplift.get("p95_latency_regression"),
                "<= 0.20 relative regression",
                "p95 latency regression exceeds twenty percent",
            ),
            _held_out_parity_check(payload),
            _check(
                "embedded-checks",
                bool(payload.get("checks"))
                and all(
                    isinstance(item, dict) and item.get("passed") is True
                    for item in payload.get("checks") or []
                ),
                len(payload.get("checks") or []),
                "all embedded benchmark checks pass",
                "one or more embedded benchmark checks failed",
            ),
        ]
    )
    return _result(checks, source_sha=source_sha)


def render_experience_quality_admission_markdown(
    payload: dict[str, Any],
) -> str:
    summary = _mapping(payload.get("summary"))
    lines = [
        "# Experienced Work Agent Admission",
        "",
        f"Status: **{payload.get('status', 'blocked')}**",
        "",
        f"Source SHA: `{payload.get('source_sha') or 'missing'}`",
        "",
        (
            f"Checks: **{summary.get('checks_passed', 0)}/"
            f"{summary.get('checks_total', 0)}**"
        ),
        "",
        "| check | status | evidence | target |",
        "|---|---|---|---|",
    ]
    for check in payload.get("checks") or []:
        lines.append(
            f"| {check['id']} | {check['status']} | "
            f"`{_compact(check['evidence'])}` | {check['target']} |"
        )
    if payload.get("issues"):
        lines.extend(["", "## Required actions", ""])
        lines.extend(f"- {issue}" for issue in payload["issues"])
    return "\n".join(lines) + "\n"


def _held_out_parity_check(payload: dict[str, Any]) -> dict[str, Any]:
    dataset = _mapping(payload.get("dataset"))
    expected = tuple(str(value) for value in dataset.get("held_out_ids") or [])
    results = _mapping(payload.get("held_out_results"))
    observed: dict[str, list[str]] = {}
    for engine in ("cold", "core", "experience"):
        rows = results.get(engine) if isinstance(results.get(engine), list) else []
        observed[engine] = [str(row.get("request_id")) for row in rows]
    passed = (
        len(expected) == 30
        and len(set(expected)) == 30
        and all(tuple(ids) == expected for ids in observed.values())
    )
    return _check(
        "held-out-parity",
        passed,
        {name: len(ids) for name, ids in observed.items()},
        "same 30 ordered held-out IDs for all engines",
        "held-out rows differ across compared engines",
    )


def _uplift_check(
    check_id: str,
    uplift: dict[str, Any],
    key: str,
    *,
    minimum: float,
) -> dict[str, Any]:
    value = _as_float(uplift.get(key), default=float("-inf"))
    return _check(
        check_id,
        value >= minimum,
        uplift.get(key),
        f">= {minimum:.2f}",
        f"{key} does not meet the frozen admission threshold",
    )


def _result(
    checks: list[dict[str, Any]],
    *,
    source_sha: str,
) -> dict[str, Any]:
    passed = sum(bool(check["passed"]) for check in checks)
    issues = [str(check["issue"]) for check in checks if not check["passed"]]
    admitted = bool(checks) and passed == len(checks)
    return {
        "schema": "wavemind.experience_quality_admission.v1",
        "status": "admitted" if admitted else "blocked",
        "admitted": admitted,
        "evaluated_at": _utc_now(),
        "source_sha": source_sha,
        "artifact": ARTIFACT,
        "checks": checks,
        "summary": {
            "checks_passed": passed,
            "checks_total": len(checks),
            "blocker_count": len(issues),
        },
        "issues": issues,
    }


def _check(
    check_id: str,
    passed: bool,
    evidence: Any,
    target: Any,
    issue: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": bool(passed),
        "status": "pass" if passed else "action_required",
        "evidence": evidence,
        "target": target,
        "issue": "" if passed else issue,
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace(
        "|", "/"
    )


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
