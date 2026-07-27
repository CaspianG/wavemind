from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADVANTAGE_ARTIFACT = "benchmarks/agent_memory_advantage_results.json"
PUBLIC_ARTIFACTS = {
    "locomo": ("benchmarks/locomo_memory_os_results.json", 1_977),
    "longmemeval": ("benchmarks/longmemeval_memory_os_results.json", 470),
    "longmemeval_v2_small": (
        "benchmarks/longmemeval_v2_small_memory_os_results.json",
        451,
    ),
}
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _repository_commit(root: Path) -> str | None:
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None
    return value if _GIT_SHA_RE.fullmatch(value) else None


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _result_by_engine(payload: dict[str, Any], engine: str) -> dict[str, Any]:
    for row in payload.get("results") or []:
        if isinstance(row, dict) and str(row.get("engine")) == engine:
            return row
    return {}


def _check(
    check_id: str,
    passed: bool,
    *,
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


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _validate_advantage(
    payload: dict[str, Any] | None,
    *,
    expected_source_sha: str | None,
) -> list[dict[str, Any]]:
    if payload is None:
        return [
            _check(
                "advantage-artifact",
                False,
                evidence="missing",
                target=ADVANTAGE_ARTIFACT,
                issue=f"missing required artifact: {ADVANTAGE_ARTIFACT}",
            )
        ]

    protocol = payload.get("protocol") if isinstance(payload.get("protocol"), dict) else {}
    memory_os = _result_by_engine(payload, "WaveMind + Memory OS")
    core = _result_by_engine(payload, "WaveMind Core")
    paired = payload.get("paired_lift") if isinstance(payload.get("paired_lift"), dict) else {}
    categories = (
        paired.get("categories")
        if isinstance(paired.get("categories"), dict)
        else {}
    )
    significant_categories = sorted(
        category
        for category, interval in categories.items()
        if isinstance(interval, dict) and _as_float(interval.get("lower")) > 0.0
    )
    strongest = (
        payload.get("strongest_local_baseline")
        if isinstance(payload.get("strongest_local_baseline"), dict)
        else {}
    )
    real_static = {
        str(row.get("engine"))
        for row in payload.get("results") or []
        if isinstance(row, dict)
        and row.get("status") == "pass"
        and row.get("engine") in {"Chroma static", "Qdrant static"}
    }
    source_sha = str(payload.get("source_sha") or "")
    source_matches = bool(_GIT_SHA_RE.fullmatch(source_sha)) and (
        expected_source_sha is None or source_sha == expected_source_sha
    )
    core_task = _as_float(core.get("task_success_rate"))
    memory_os_task = _as_float(memory_os.get("task_success_rate"))
    core_p95 = _as_float(core.get("p95_latency_ms"))
    memory_os_p95 = _as_float(memory_os.get("p95_latency_ms"))
    latency_delta = memory_os_p95 - core_p95
    latency_ratio = latency_delta / core_p95 if core_p95 > 0 else float("inf")

    return [
        _check(
            "advantage-schema",
            payload.get("schema") == "wavemind.agent_memory_advantage_benchmark.v1"
            and payload.get("status") == "pass",
            evidence={"schema": payload.get("schema"), "status": payload.get("status")},
            target="passing v1 artifact",
            issue="agent-memory advantage artifact must be a passing v1 artifact",
        ),
        _check(
            "advantage-source-sha",
            source_matches,
            evidence=source_sha,
            target=expected_source_sha or "exact 40-character git SHA",
            issue="advantage artifact source_sha is missing or does not match",
        ),
        _check(
            "fair-protocol",
            _as_int(protocol.get("measurement_trials")) >= 5
            and _as_int(protocol.get("bootstrap_samples")) >= 10_000
            and _as_float(protocol.get("confidence_level")) == 0.95
            and all(
                protocol.get(name) is True
                for name in ("same_memories", "same_queries", "same_embeddings", "same_top_k")
            ),
            evidence={
                "measurement_trials": protocol.get("measurement_trials"),
                "bootstrap_samples": protocol.get("bootstrap_samples"),
                "confidence_level": protocol.get("confidence_level"),
            },
            target=">=5 trials, 10000 bootstrap samples, 95% paired CI, same protocol",
            issue="fair repeated protocol or confidence evidence is incomplete",
        ),
        _check(
            "real-static-baseline",
            bool(real_static),
            evidence=sorted(real_static),
            target="Chroma static or Qdrant static",
            issue="a real Chroma or Qdrant same-protocol baseline is required",
        ),
        _check(
            "two-significant-dynamic-categories",
            len(significant_categories) >= 2,
            evidence=significant_categories,
            target="at least two categories with paired CI lower bound > 0",
            issue="Memory OS lift is not statistically positive in two dynamic categories",
        ),
        _check(
            "positive-combined-lift",
            _as_float(strongest.get("combined_lift"), default=-1.0) > 0.0,
            evidence=strongest,
            target="combined lift > 0 over strongest local baseline",
            issue="Memory OS does not beat the strongest local baseline on combined score",
        ),
        _check(
            "task-success-non-regression",
            memory_os_task - core_task >= -0.01,
            evidence={
                "memory_os": memory_os_task,
                "core": core_task,
                "delta": memory_os_task - core_task,
            },
            target="delta >= -0.01",
            issue="Memory OS task success regressed by more than one percentage point",
        ),
        _check(
            "stale-error",
            _as_float(memory_os.get("stale_error_rate"), default=1.0) <= 0.02,
            evidence=memory_os.get("stale_error_rate"),
            target="<= 0.02",
            issue="Memory OS stale error exceeds two percent",
        ),
        _check(
            "context-saving",
            _as_float(memory_os.get("context_budget_saved")) >= 0.30,
            evidence=memory_os.get("context_budget_saved"),
            target=">= 0.30 versus full context",
            issue="Memory OS does not save at least 30% of full-context tokens",
        ),
        _check(
            "latency",
            latency_delta <= 5.0 and latency_ratio <= 0.20,
            evidence={
                "memory_os_p95_ms": memory_os_p95,
                "core_p95_ms": core_p95,
                "delta_ms": latency_delta,
                "regression_ratio": latency_ratio,
            },
            target="p95 delta <= 5 ms and regression ratio <= 20%",
            issue="Memory OS p95 latency regression exceeds the admission budget",
        ),
    ]


def _validate_public_artifact(
    name: str,
    payload: dict[str, Any] | None,
    *,
    artifact: str,
    min_queries: int,
    expected_source_sha: str | None,
) -> dict[str, Any]:
    if payload is None:
        return _check(
            f"public-{name}",
            False,
            evidence="missing",
            target=artifact,
            issue=f"missing required direct Memory OS artifact: {artifact}",
        )
    scenario = payload.get("scenario") if isinstance(payload.get("scenario"), dict) else {}
    memory_os = _result_by_engine(payload, "WaveMind + Memory OS")
    core = _result_by_engine(payload, "WaveMind")
    if not core:
        core = _result_by_engine(payload, "WaveMind Core")
    source_sha = str(payload.get("source_sha") or "")
    query_count = _as_int(scenario.get("queries") or scenario.get("query_count"))
    memory_os_quality = _as_float(
        memory_os.get("precision_at_1"),
        default=_as_float(memory_os.get("evidence_recall_at_k"), default=-1.0),
    )
    core_quality = _as_float(
        core.get("precision_at_1"),
        default=_as_float(core.get("evidence_recall_at_k"), default=-1.0),
    )
    worker_errors = _as_int(memory_os.get("worker_errors"))
    passed = (
        bool(_GIT_SHA_RE.fullmatch(source_sha))
        and (expected_source_sha is None or source_sha == expected_source_sha)
        and query_count >= min_queries
        and str(memory_os.get("execution_mode") or "").startswith("memory_os_direct")
        and _as_int(memory_os.get("worker_runs")) > 0
        and worker_errors == 0
        and memory_os_quality >= core_quality - 0.01
    )
    return _check(
        f"public-{name}",
        passed,
        evidence={
            "artifact": artifact,
            "source_sha": source_sha,
            "query_count": query_count,
            "execution_mode": memory_os.get("execution_mode"),
            "worker_runs": memory_os.get("worker_runs"),
            "worker_errors": worker_errors,
            "memory_os_quality": memory_os_quality,
            "core_quality": core_quality,
        },
        target={
            "min_queries": min_queries,
            "direct_memory_os": True,
            "worker_runs": "> 0",
            "worker_errors": 0,
            "quality_regression": "<= 0.01",
        },
        issue=f"{name} does not contain complete direct Memory OS evidence",
    )


def evaluate_agent_memory_advantage_admission(
    root: Path | str = PROJECT_ROOT,
    *,
    expected_source_sha: str | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    expected_sha = expected_source_sha or _repository_commit(root_path)
    advantage = _load_json(root_path / ADVANTAGE_ARTIFACT)
    checks = _validate_advantage(advantage, expected_source_sha=expected_sha)
    public_evidence: dict[str, dict[str, Any]] = {}
    for name, (artifact, min_queries) in PUBLIC_ARTIFACTS.items():
        check = _validate_public_artifact(
            name,
            _load_json(root_path / artifact),
            artifact=artifact,
            min_queries=min_queries,
            expected_source_sha=expected_sha,
        )
        public_evidence[name] = check
        checks.append(check)
    passed = sum(1 for check in checks if check["passed"])
    admitted = passed == len(checks)
    issues = [str(check["issue"]) for check in checks if not check["passed"]]
    return {
        "schema": "wavemind.agent_memory_advantage_admission.v1",
        "generated_at": _utc_now(),
        "source_sha": expected_sha,
        "status": "admitted" if admitted else "blocked",
        "admitted": admitted,
        "summary": {
            "checks_passed": passed,
            "checks_total": len(checks),
            "public_benchmarks_passed": sum(
                1 for check in public_evidence.values() if check["passed"]
            ),
            "public_benchmarks_total": len(public_evidence),
        },
        "checks": checks,
        "public_evidence": public_evidence,
        "issues": issues,
        "claim_boundary": (
            "Admission requires controlled paired advantage evidence and direct "
            "Memory OS execution on all three public memory benchmarks."
        ),
    }


def render_agent_memory_advantage_admission_markdown(
    payload: dict[str, Any],
) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# WaveMind Agent Memory Advantage Admission",
        "",
        f"- Status: **{payload.get('status')}**",
        f"- Source SHA: `{payload.get('source_sha')}`",
        (
            f"- Checks: **{summary.get('checks_passed', 0)}/"
            f"{summary.get('checks_total', 0)}**"
        ),
        (
            f"- Direct public benchmarks: **"
            f"{summary.get('public_benchmarks_passed', 0)}/"
            f"{summary.get('public_benchmarks_total', 0)}**"
        ),
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    for check in payload.get("checks") or []:
        lines.append(
            f"| `{check.get('id')}` | "
            f"{'pass' if check.get('passed') else 'action required'} |"
        )
    if payload.get("issues"):
        lines.extend(["", "## Blocking Issues", ""])
        lines.extend(f"- {issue}" for issue in payload["issues"])
    lines.extend(["", f"> {payload.get('claim_boundary')}", ""])
    return "\n".join(lines)
