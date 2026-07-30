from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CORE_ENGINE = "WaveMind"
MEMORY_OS_ENGINE = "WaveMind + Memory OS"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number} must contain a JSON object")
        rows.append(row)
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _result_by_engine(
    payload: dict[str, Any],
    engine: str,
) -> dict[str, Any]:
    for result in payload.get("results", []):
        if result.get("engine") == engine:
            return result
    raise ValueError(f"missing result for engine {engine!r}")


def _rows_by_engine(
    rows: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("engine"))].append(row)
    return dict(grouped)


def _row_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot compute metrics for an empty row set")
    categories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        categories[str(row.get("category"))].append(row)
    return {
        "rows": len(rows),
        "unique_questions": len({str(row.get("question_id")) for row in rows}),
        "task_success_rate": sum(bool(row.get("passed")) for row in rows)
        / len(rows),
        "errors": sum(bool(row.get("error")) for row in rows),
        "category_success": {
            category: sum(bool(row.get("passed")) for row in category_rows)
            / len(category_rows)
            for category, category_rows in sorted(categories.items())
        },
    }


def _comparison(
    core: dict[str, Any],
    memory_os: dict[str, Any],
) -> dict[str, Any]:
    core_categories = dict(core.get("category_success") or {})
    memory_os_categories = dict(memory_os.get("category_success") or {})
    improved = [
        category
        for category, value in sorted(memory_os_categories.items())
        if float(value) > float(core_categories.get(category, 0.0))
    ]
    return {
        "task_success_uplift": float(memory_os["task_success_rate"])
        - float(core["task_success_rate"]),
        "improved_categories": improved,
        "improved_category_count": len(improved),
    }


def _check(
    check_id: str,
    passed: bool,
    *,
    actual: Any,
    requirement: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "actual": actual,
        "requirement": requirement,
    }


def build_analysis(
    *,
    full_payload: dict[str, Any],
    full_rows: list[dict[str, Any]],
    development_payload: dict[str, Any],
    development_rows: list[dict[str, Any]],
    input_checksums: dict[str, str],
) -> dict[str, Any]:
    source_sha = str(full_payload.get("source_sha") or "")
    if not source_sha or development_payload.get("source_sha") != source_sha:
        raise ValueError("full and development artifacts must use one source_sha")

    full_grouped = _rows_by_engine(full_rows)
    development_grouped = _rows_by_engine(development_rows)
    required_engines = {CORE_ENGINE, MEMORY_OS_ENGINE}
    if set(full_grouped) != required_engines:
        raise ValueError("full rows must contain exactly Core and Memory OS")
    if set(development_grouped) != required_engines:
        raise ValueError(
            "development rows must contain exactly Core and Memory OS"
        )

    development_ids = {
        str(row.get("question_id")) for row in development_rows
    }
    full_ids = {str(row.get("question_id")) for row in full_rows}
    if not development_ids <= full_ids:
        raise ValueError("development question ids must be a subset of full ids")
    remaining_rows = [
        row
        for row in full_rows
        if str(row.get("question_id")) not in development_ids
    ]
    remaining_grouped = _rows_by_engine(remaining_rows)

    full_core = _result_by_engine(full_payload, CORE_ENGINE)
    full_memory_os = _result_by_engine(full_payload, MEMORY_OS_ENGINE)
    development_core = _result_by_engine(development_payload, CORE_ENGINE)
    development_memory_os = _result_by_engine(
        development_payload,
        MEMORY_OS_ENGINE,
    )
    remaining_core = _row_metrics(remaining_grouped[CORE_ENGINE])
    remaining_memory_os = _row_metrics(
        remaining_grouped[MEMORY_OS_ENGINE]
    )

    full_comparison = _comparison(full_core, full_memory_os)
    development_comparison = _comparison(
        development_core,
        development_memory_os,
    )
    remaining_comparison = _comparison(
        remaining_core,
        remaining_memory_os,
    )
    context_saving = 1.0 - (
        float(full_memory_os["context_tokens"])
        / float(full_core["context_tokens"])
    )
    latency_delta_ms = float(full_memory_os["end_to_end_p95_ms"]) - float(
        full_core["end_to_end_p95_ms"]
    )
    latency_ratio = latency_delta_ms / float(
        full_core["end_to_end_p95_ms"]
    )
    scenario = dict(full_payload.get("scenario") or {})
    aggregate_errors = sum(
        int(result.get("errors") or 0)
        for result in full_payload.get("results", [])
    )
    worker_errors = sum(
        int(result.get("worker_errors") or 0)
        for result in full_payload.get("results", [])
    )
    zero_errors = (
        sum(bool(row.get("error")) for row in full_rows) == 0
        and aggregate_errors == 0
        and worker_errors == 0
    )
    protocol_complete = (
        scenario.get("queries") == 451
        and scenario.get("question_selection") == "full"
        and scenario.get("full_small_run") is True
        and scenario.get("official_question_haystacks") is True
        and scenario.get("isolated_ab_stores") is True
        and scenario.get("image_questions")
        == scenario.get("image_questions_included")
        and len(full_rows) == 902
        and len(development_ids) == 32
        and len(full_ids - development_ids) == 419
    )
    checks = [
        _check(
            "full_protocol_complete",
            protocol_complete,
            actual={
                "full_questions": len(full_ids),
                "rows": len(full_rows),
                "development_questions": len(development_ids),
                "untouched_questions": len(full_ids - development_ids),
            },
            requirement=(
                "451 full questions, 902 rows, official haystacks, isolated "
                "A/B stores, all images, dev32 and untouched419"
            ),
        ),
        _check(
            "zero_execution_errors",
            zero_errors,
            actual={
                "row_errors": sum(
                    bool(row.get("error")) for row in full_rows
                ),
                "aggregate_errors": aggregate_errors,
                "worker_errors": worker_errors,
            },
            requirement="zero row, aggregate, and worker errors",
        ),
        _check(
            "full_memory_os_quality",
            float(full_memory_os["task_success_rate"]) >= 0.18,
            actual=float(full_memory_os["task_success_rate"]),
            requirement=">= 0.18",
        ),
        _check(
            "full_memory_os_uplift",
            full_comparison["task_success_uplift"] >= 0.01,
            actual=full_comparison["task_success_uplift"],
            requirement=">= Core + 0.01 absolute",
        ),
        _check(
            "full_improved_categories",
            full_comparison["improved_category_count"] >= 4,
            actual=full_comparison["improved_category_count"],
            requirement=">= 4",
        ),
        _check(
            "full_context_saving",
            context_saving >= 0.35,
            actual=context_saving,
            requirement=">= 0.35 versus Core",
        ),
        _check(
            "full_p95_latency_delta",
            latency_delta_ms <= 5.0,
            actual=latency_delta_ms,
            requirement="<= 5 ms",
        ),
        _check(
            "full_p95_latency_ratio",
            latency_ratio <= 0.20,
            actual=latency_ratio,
            requirement="<= 20%",
        ),
        _check(
            "untouched419_memory_os_uplift",
            remaining_comparison["task_success_uplift"] >= 0.01,
            actual=remaining_comparison["task_success_uplift"],
            requirement=">= Core + 0.01 absolute",
        ),
    ]
    failed_checks = [
        check["id"] for check in checks if check["status"] != "pass"
    ]
    return {
        "schema": "wavemind.longmemeval_v2_split_analysis.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha": source_sha,
        "status": "pass" if not failed_checks else "failed_experiment",
        "experiment": {
            "name": "hybrid1150_trajectory_and_source_context",
            "frozen_before_held_out_evaluation": True,
            "thresholds_frozen": True,
            "held_out_results_used_for_tuning": False,
        },
        "dataset": {
            "repo": scenario.get("dataset_repo"),
            "revision": scenario.get("dataset_revision"),
            "official_repo_revision": scenario.get(
                "official_repo_revision"
            ),
            "checksums": full_payload.get("dataset_checksums"),
        },
        "inputs": input_checksums,
        "development_split": {
            "selection": development_payload.get("scenario", {}).get(
                "question_selection"
            ),
            "seed": development_payload.get("scenario", {}).get(
                "question_sample_seed"
            ),
            "questions": len(development_ids),
            "core": {
                "task_success_rate": development_core[
                    "task_success_rate"
                ],
                "category_success": development_core["category_success"],
            },
            "memory_os": {
                "task_success_rate": development_memory_os[
                    "task_success_rate"
                ],
                "category_success": development_memory_os[
                    "category_success"
                ],
            },
            "comparison": development_comparison,
        },
        "full451": {
            "questions": len(full_ids),
            "rows": len(full_rows),
            "core": {
                "task_success_rate": full_core["task_success_rate"],
                "context_tokens": full_core["context_tokens"],
                "end_to_end_p95_ms": full_core["end_to_end_p95_ms"],
                "category_success": full_core["category_success"],
            },
            "memory_os": {
                "task_success_rate": full_memory_os["task_success_rate"],
                "context_tokens": full_memory_os["context_tokens"],
                "end_to_end_p95_ms": full_memory_os[
                    "end_to_end_p95_ms"
                ],
                "category_success": full_memory_os["category_success"],
            },
            "comparison": {
                **full_comparison,
                "context_saving": context_saving,
                "p95_latency_delta_ms": latency_delta_ms,
                "p95_latency_regression_ratio": latency_ratio,
            },
        },
        "untouched419": {
            "questions": len(full_ids - development_ids),
            "rows": len(remaining_rows),
            "development_overlap": 0,
            "core": remaining_core,
            "memory_os": remaining_memory_os,
            "comparison": remaining_comparison,
            "metric_boundary": (
                "Per-query rows prove quality, categories, and errors. "
                "Context and latency are reported only for full451 because "
                "the per-query artifact does not carry token or latency data."
            ),
        },
        "checks": checks,
        "failed_checks": failed_checks,
        "claim_boundary": (
            "This is a failed frozen experiment, not admission evidence. "
            "It passes execution, context, and latency controls but does not "
            "prove Memory OS quality uplift. The held-out result must not be "
            "used to tune this architecture."
        ),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    full = payload["full451"]
    remaining = payload["untouched419"]
    lines = [
        "# LongMemEval-V2 Frozen Split Analysis",
        "",
        f"Status: `{payload['status']}`",
        "",
        "This report separates the 32-question development split from the "
        "untouched remaining 419 questions. The full result was evaluated "
        "only after the architecture and thresholds were frozen.",
        "",
        "## Results",
        "",
        "| Split | Core success | Memory OS success | Uplift | Improved categories |",
        "|---|---:|---:|---:|---:|",
        (
            f"| Full 451 | {full['core']['task_success_rate']:.4f} | "
            f"{full['memory_os']['task_success_rate']:.4f} | "
            f"{full['comparison']['task_success_uplift']:+.4f} | "
            f"{full['comparison']['improved_category_count']} |"
        ),
        (
            f"| Untouched 419 | {remaining['core']['task_success_rate']:.4f} | "
            f"{remaining['memory_os']['task_success_rate']:.4f} | "
            f"{remaining['comparison']['task_success_uplift']:+.4f} | "
            f"{remaining['comparison']['improved_category_count']} |"
        ),
        "",
        (
            f"Full-context saving: "
            f"`{full['comparison']['context_saving']:.2%}`. "
            f"Full p95 delta: "
            f"`{full['comparison']['p95_latency_delta_ms']:+.3f} ms`."
        ),
        "",
        "## Gates",
        "",
        "| Gate | Status | Actual | Requirement |",
        "|---|---|---|---|",
    ]
    for check in payload["checks"]:
        actual = json.dumps(
            check["actual"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        lines.append(
            f"| `{check['id']}` | `{check['status']}` | `{actual}` | "
            f"{check['requirement']} |"
        )
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            payload["claim_boundary"],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-results", type=Path, required=True)
    parser.add_argument("--full-per-query", type=Path, required=True)
    parser.add_argument("--development-results", type=Path, required=True)
    parser.add_argument("--development-per-query", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    input_paths = {
        "full_results": args.full_results,
        "full_per_query": args.full_per_query,
        "development_results": args.development_results,
        "development_per_query": args.development_per_query,
    }
    payload = build_analysis(
        full_payload=_load_json(args.full_results),
        full_rows=_load_jsonl(args.full_per_query),
        development_payload=_load_json(args.development_results),
        development_rows=_load_jsonl(args.development_per_query),
        input_checksums={
            name: _sha256(path) for name, path in input_paths.items()
        },
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(
            render_markdown(payload),
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
