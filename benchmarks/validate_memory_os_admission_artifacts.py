from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REMOTE_EVIDENCE_PATH = Path("benchmarks/memory_os_remote_worker_soak_results.json")
ADMISSION_PATH = Path("benchmarks/memory_os_admission_results.json")


class MemoryOSAdmissionArtifactError(RuntimeError):
    pass


def validate_memory_os_admission_artifacts(
    root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    root = Path(root)
    remote = _load_json(root / REMOTE_EVIDENCE_PATH)
    admission = _load_json(root / ADMISSION_PATH)
    errors: list[str] = []

    metrics = remote.get("metrics") if isinstance(remote.get("metrics"), dict) else {}
    health = remote.get("health") if isinstance(remote.get("health"), list) else []
    remote_checks = remote.get("checks") if isinstance(remote.get("checks"), list) else []
    requirements = (
        admission.get("requirements")
        if isinstance(admission.get("requirements"), list)
        else []
    )
    runtime_requirement = next(
        (
            row
            for row in requirements
            if isinstance(row, dict) and row.get("id") == "runtime-soak"
        ),
        {},
    )
    runtime_details = (
        runtime_requirement.get("details")
        if isinstance(runtime_requirement.get("details"), dict)
        else {}
    )
    embedded_remote = (
        runtime_details.get("runtime_evidence")
        if isinstance(runtime_details.get("runtime_evidence"), dict)
        else {}
    )
    source_ref = str(remote.get("source_ref") or "")

    _require(
        remote.get("schema") == "wavemind.memory_os_remote_worker_soak.v1",
        "remote evidence schema is invalid",
        errors,
    )
    _require(remote.get("status") == "pass", "remote evidence did not pass", errors)
    _require(
        remote.get("environment") == "remote_worker_cluster",
        "remote evidence is not from a remote worker cluster",
        errors,
    )
    _require(bool(source_ref), "remote evidence has no source_ref", errors)
    _require(float(metrics.get("duration_seconds") or 0) >= 21_600, "soak is shorter than six hours", errors)
    _require(int(metrics.get("worker_cycles") or 0) >= 500, "soak has fewer than 500 worker cycles", errors)
    _require(int(metrics.get("worker_count") or 0) >= 2, "soak has fewer than two workers", errors)
    for key in (
        "job_request_failures",
        "lock_breach_count",
        "duplicate_mutation_count",
        "state_corruption_count",
        "error_count",
    ):
        _require(int(metrics.get(key) or 0) == 0, f"remote evidence {key} is non-zero", errors)
    _require(float(metrics.get("error_rate") or 0) == 0.0, "remote evidence error_rate is non-zero", errors)
    _require(bool(remote_checks), "remote evidence has no checks", errors)
    _require(
        bool(remote_checks) and all(bool(row.get("passed")) for row in remote_checks if isinstance(row, dict)),
        "one or more remote evidence checks failed",
        errors,
    )
    _require(len(health) >= 2, "remote evidence has fewer than two worker health records", errors)
    _require(
        bool(health)
        and all(
            isinstance(row, dict)
            and row.get("status") == "ok"
            and row.get("commit_sha") == source_ref
            for row in health
        ),
        "worker health does not match the tested commit",
        errors,
    )

    summary = admission.get("summary") if isinstance(admission.get("summary"), dict) else {}
    _require(
        admission.get("schema") == "wavemind.memory_os_admission.v1",
        "admission schema is invalid",
        errors,
    )
    _require(admission.get("status") == "admitted", "admission status is not admitted", errors)
    _require(admission.get("admitted") is True, "admission flag is false", errors)
    _require(int(summary.get("requirement_count") or 0) == 13, "admission does not contain 13 requirements", errors)
    _require(int(summary.get("passed_count") or 0) == 13, "not all admission requirements passed", errors)
    _require(int(summary.get("blocker_count") or 0) == 0, "admission contains blockers", errors)
    _require(int(summary.get("warning_count") or 0) == 0, "admission contains warnings", errors)
    _require(
        len(requirements) == 13 and all(bool(row.get("passed")) for row in requirements if isinstance(row, dict)),
        "one or more admission requirements failed",
        errors,
    )
    _require(runtime_requirement.get("passed") is True, "runtime-soak admission requirement failed", errors)
    _require(runtime_details.get("runtime_evidence_valid") is True, "runtime evidence was not valid at admission", errors)
    _require(runtime_details.get("remote_runtime_evidence") is True, "admission did not use remote evidence", errors)
    _require(runtime_details.get("evidence_fresh") is True, "runtime evidence was stale at admission", errors)
    _require(runtime_details.get("commit_matches") is True, "tested commit did not match at admission", errors)
    _require(
        runtime_details.get("expected_commit_sha") == source_ref,
        "admission expected commit differs from remote evidence",
        errors,
    )
    _require(
        float(runtime_details.get("evidence_age_seconds") or 0) <= 86_400,
        "runtime evidence exceeded the admission freshness window",
        errors,
    )
    _require(
        embedded_remote == remote,
        "embedded admission evidence differs from the checked-in remote artifact",
        errors,
    )
    _require(
        _parse_time(admission.get("generated_at")) >= _parse_time(remote.get("finished_at")),
        "admission predates completion of the remote soak",
        errors,
    )

    report = {
        "schema": "wavemind.memory_os_admission_artifact_validation.v1",
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "fail" if errors else "pass",
        "tested_commit": source_ref or None,
        "admission_status": admission.get("status"),
        "duration_seconds": metrics.get("duration_seconds"),
        "worker_cycles": metrics.get("worker_cycles"),
        "worker_count": metrics.get("worker_count"),
        "errors": errors,
    }
    if errors:
        raise MemoryOSAdmissionArtifactError(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MemoryOSAdmissionArtifactError(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MemoryOSAdmissionArtifactError(f"{path} does not contain a JSON object")
    return payload


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = validate_memory_os_admission_artifacts()
    except MemoryOSAdmissionArtifactError as exc:
        try:
            report = json.loads(str(exc))
        except json.JSONDecodeError:
            report = {
                "schema": "wavemind.memory_os_admission_artifact_validation.v1",
                "status": "fail",
                "errors": [str(exc)],
            }
        if args.output:
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
