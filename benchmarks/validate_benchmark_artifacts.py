from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wavemind.evidence import (
    GIT_SHA_RE,
    commit_relation,
    repository_commit,
    validate_artifact_integrity,
    validate_source_manifest,
)

try:
    from benchmarks.render_benchmark_leaderboard import render_leaderboard
    from benchmarks.render_benchmark_report import render_report
    from benchmarks.render_leaderboard_status import render_leaderboard_status
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from render_benchmark_leaderboard import render_leaderboard
    from render_benchmark_report import render_report
    from render_leaderboard_status import render_leaderboard_status


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BenchmarkArtifactError(RuntimeError):
    pass


def validate_benchmark_artifacts(
    root: Path = PROJECT_ROOT,
    *,
    max_age_days: float | None = None,
    now: datetime | None = None,
    expected_source_sha: str | None = None,
    require_current: bool = False,
) -> dict[str, Any]:
    root = Path(root)
    matrix_path = root / "benchmarks" / "benchmark_matrix_results.json"
    report_path = root / "benchmarks" / "BENCHMARK_REPORT.md"
    leaderboard_path = root / "benchmarks" / "BENCHMARK_LEADERBOARD.md"
    leaderboard_status_path = root / "docs" / "data" / "leaderboard-status.json"

    errors: list[str] = []
    matrix = _load_json(matrix_path, errors)
    errors.extend(validate_artifact_integrity(matrix))
    benchmarks = matrix.get("benchmarks") if isinstance(matrix, dict) else None
    if matrix.get("schema") != "wavemind.benchmark_matrix.v1":
        errors.append("benchmark matrix schema is not wavemind.benchmark_matrix.v1")
    if not isinstance(benchmarks, list) or not benchmarks:
        errors.append("benchmark matrix has no benchmarks")
        benchmarks = []

    provenance = matrix.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("benchmark matrix provenance block is missing")
        provenance = {}
    if provenance.get("schema") != "wavemind.benchmark_snapshot_provenance.v1":
        errors.append("benchmark matrix provenance schema is invalid")
    claim_status = provenance.get("claim_status")
    if claim_status not in {"current", "historical"}:
        errors.append("benchmark matrix claim_status must be current or historical")
    source_sha = str(provenance.get("source_sha") or "")
    if not GIT_SHA_RE.fullmatch(source_sha):
        errors.append("benchmark matrix source_sha is not an exact 40-character git SHA")
    if matrix.get("source_ref") != source_sha:
        errors.append("benchmark matrix source_ref differs from provenance source_sha")

    expected_sha = expected_source_sha or repository_commit(root)
    relation = commit_relation(root, source_sha, expected_sha)
    current_relation = relation in {"exact", "ancestor"}
    if claim_status == "current" and not current_relation:
        errors.append(
            f"current benchmark matrix source SHA is not in current history: {relation}"
        )
    if require_current and claim_status != "current":
        errors.append("benchmark matrix is historical but a current snapshot is required")

    source_manifest = provenance.get("source_manifest")
    if not isinstance(source_manifest, dict):
        errors.append("benchmark matrix source manifest is missing")
        source_manifest = {}
    manifest_errors = validate_source_manifest(
        root,
        source_manifest,
        require_current_files=claim_status == "current",
    )
    errors.extend(manifest_errors)

    generated_at = _parse_generated_at(matrix.get("generated_at"), errors)
    age_days: float | None = None
    fresh: bool | None = None
    if generated_at is not None:
        current_time = now or datetime.now(timezone.utc)
        age_days = max(0.0, (current_time - generated_at).total_seconds() / 86400.0)
        fresh = max_age_days is None or age_days <= max_age_days
        if claim_status == "current" and not fresh:
            errors.append(
                f"benchmark matrix is stale: age {age_days:.2f} days exceeds {max_age_days:.2f}"
            )

    claim_eligible = bool(
        claim_status == "current"
        and current_relation
        and not manifest_errors
        and (fresh is not False)
    )

    implemented = [
        entry for entry in benchmarks
        if isinstance(entry, dict) and entry.get("status") == "implemented"
    ]
    planned = [
        entry for entry in benchmarks
        if isinstance(entry, dict) and entry.get("status") == "planned"
    ]
    runner_ready = [
        entry for entry in benchmarks
        if isinstance(entry, dict) and entry.get("status") == "runner-ready"
    ]

    for entry in implemented:
        bench_id = str(entry.get("id") or entry.get("name") or "<unknown>")
        current = entry.get("current")
        if not isinstance(current, dict) or not current:
            errors.append(f"implemented benchmark has no current result: {bench_id}")
        source = entry.get("source")
        if not isinstance(source, str) or not source:
            errors.append(f"implemented benchmark has no local source: {bench_id}")
        elif not source.startswith(("http://", "https://")) and not (root / source).exists():
            errors.append(f"implemented benchmark source is missing: {bench_id}: {source}")

    _assert_rendered_file(
        path=report_path,
        expected=render_report(root),
        label="benchmark report",
        errors=errors,
    )
    _assert_rendered_file(
        path=leaderboard_path,
        expected=render_leaderboard(root),
        label="benchmark leaderboard",
        errors=errors,
    )
    _assert_rendered_file(
        path=leaderboard_status_path,
        expected=json.dumps(render_leaderboard_status(root), ensure_ascii=False, indent=2) + "\n",
        label="leaderboard status",
        errors=errors,
    )

    report = {
        "schema": "wavemind.benchmark_artifact_audit.v1",
        "status": "fail" if errors else "pass",
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "generated_at": matrix.get("generated_at"),
        "source_ref": matrix.get("source_ref"),
        "expected_source_sha": expected_sha,
        "source_relation": relation,
        "claim_status": claim_status,
        "claim_eligible": claim_eligible,
        "workflow_run_id": matrix.get("workflow_run_id"),
        "refresh_profile": matrix.get("refresh_profile"),
        "max_age_days": max_age_days,
        "age_days": age_days,
        "implemented_count": len(implemented),
        "runner_ready_count": len(runner_ready),
        "planned_count": len(planned),
        "errors": errors,
    }
    if errors:
        raise BenchmarkArtifactError(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"cannot read {path}: {exc}")
        return {}


def _parse_generated_at(value: Any, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value:
        errors.append("benchmark matrix has no generated_at timestamp")
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        errors.append(f"benchmark matrix generated_at is not ISO-8601: {value}")
        return None
    if parsed.tzinfo is None:
        errors.append("benchmark matrix generated_at must include timezone")
        return None
    return parsed.astimezone(timezone.utc)


def _assert_rendered_file(
    *,
    path: Path,
    expected: str,
    label: str,
    errors: list[str],
) -> None:
    try:
        actual = path.read_text(encoding="utf-8")
    except Exception as exc:
        errors.append(f"cannot read {label}: {exc}")
        return
    if actual != expected:
        errors.append(f"{label} is not synchronized with benchmark matrix")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-days", type=float)
    parser.add_argument("--expected-source-sha")
    parser.add_argument("--require-current", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/benchmark_artifact_audit.json"),
    )
    args = parser.parse_args()

    try:
        report = validate_benchmark_artifacts(
            max_age_days=args.max_age_days,
            expected_source_sha=args.expected_source_sha,
            require_current=args.require_current,
        )
    except BenchmarkArtifactError as exc:
        report = json.loads(str(exc))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
