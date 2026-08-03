from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = Path("benchmarks/goal4_quality_experiment_results.json")


class Goal4QualityArtifactError(RuntimeError):
    pass


def validate_goal4_quality_experiment(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    path = Path(root) / ARTIFACT_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise Goal4QualityArtifactError(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise Goal4QualityArtifactError("Goal 4 artifact must be a JSON object")

    errors: list[str] = []
    _require(payload.get("schema") == "wavemind.goal4_quality_experiment.v1", "invalid schema", errors)
    _require(payload.get("status") == "failed_experiment", "status must remain failed_experiment", errors)
    _require(payload.get("admitted") is False, "failed experiment cannot be admitted", errors)
    _require(_is_sha(payload.get("decision_sha")), "decision_sha must be a full commit SHA", errors)

    protocol = _mapping(payload, "protocol", errors)
    _require(int(protocol.get("development_questions") or 0) == 32, "development split must contain 32 questions", errors)
    _require(int(protocol.get("frozen_questions") or 0) == 419, "frozen split must contain 419 questions", errors)
    _require(int(protocol.get("full_questions") or 0) == 451, "full split must contain 451 questions", errors)
    _require(bool(protocol.get("thresholds_frozen")), "thresholds were not frozen", errors)
    _require(protocol.get("held_out_results_used_for_tuning") is False, "held-out results cannot be used for tuning", errors)
    _require(protocol.get("second_full_run_launched") is False, "artifact contradicts the final go/no-go decision", errors)

    gates = _mapping(payload, "required_gates", errors)
    full = _mapping(payload, "full451", errors)
    frozen = _mapping(payload, "untouched419", errors)
    final_dev = _mapping(payload, "final_dev32", errors)
    for label, row in (("full451", full), ("untouched419", frozen), ("final_dev32", final_dev)):
        expected = float(row.get("memory_os_task_success_rate") or 0.0) - float(row.get("core_task_success_rate") or 0.0)
        actual = float(row.get("task_success_uplift") or 0.0)
        _require(abs(expected - actual) <= 1e-12, f"{label} uplift arithmetic is inconsistent", errors)
        _require(int(row.get("execution_errors") or 0) == 0, f"{label} contains execution errors", errors)

    minimum_uplift = float(gates.get("minimum_task_success_uplift") or 0.0)
    minimum_categories = int(gates.get("minimum_improved_categories") or 0)
    _require(float(full.get("task_success_uplift") or 0.0) < minimum_uplift, "full451 unexpectedly satisfies uplift gate", errors)
    _require(int(full.get("improved_category_count") or 0) < minimum_categories, "full451 unexpectedly satisfies category gate", errors)
    _require(float(frozen.get("task_success_uplift") or 0.0) < minimum_uplift, "untouched419 unexpectedly satisfies uplift gate", errors)
    _require(float(final_dev.get("task_success_uplift") or 0.0) < minimum_uplift, "final dev32 unexpectedly satisfies uplift gate", errors)
    _require(int(final_dev.get("improved_category_count") or 0) < minimum_categories, "final dev32 unexpectedly satisfies category gate", errors)
    _require(float(full.get("context_token_reduction_vs_core") or 0.0) >= float(gates.get("minimum_context_token_reduction") or 1.0), "full451 context reduction control failed", errors)
    _require(float(full.get("p95_latency_delta_ms") or 1e9) <= float(gates.get("maximum_p95_latency_delta_ms") or 0.0), "full451 latency control failed", errors)

    expected_failed = {
        "full451_task_success_uplift",
        "full451_improved_categories",
        "untouched419_task_success_uplift",
        "final_dev32_task_success_uplift",
        "final_dev32_improved_categories",
    }
    _require(set(payload.get("failed_checks") or ()) == expected_failed, "failed_checks contradict measured gates", errors)
    _require("not be presented as agent-quality admission" in str(payload.get("claim_boundary") or ""), "claim boundary is missing", errors)

    report = {
        "schema": "wavemind.goal4_quality_experiment_validation.v1",
        "status": "fail" if errors else "pass",
        "experiment_status": payload.get("status"),
        "decision_sha": payload.get("decision_sha"),
        "errors": errors,
    }
    if errors:
        raise Goal4QualityArtifactError(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _mapping(payload: dict[str, Any], key: str, errors: list[str]) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        errors.append(f"{key} must be an object")
        return {}
    return value


def _is_sha(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(char in "0123456789abcdef" for char in text)


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    try:
        report = validate_goal4_quality_experiment(args.root)
    except Goal4QualityArtifactError as exc:
        try:
            report = json.loads(str(exc))
        except json.JSONDecodeError:
            report = {"schema": "wavemind.goal4_quality_experiment_validation.v1", "status": "fail", "errors": [str(exc)]}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
