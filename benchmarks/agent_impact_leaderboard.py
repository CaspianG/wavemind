from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]


IMPACT_ARTIFACTS = (
    {
        "path": "benchmarks/agent_coherence_results.json",
        "benchmark": "Agent coherence and token savings",
        "category": "agent_behavior",
        "primary_metric": "task_success_rate",
        "primary_label": "task success",
    },
    {
        "path": "benchmarks/dynamic_memory_results.json",
        "benchmark": "Dynamic memory policy",
        "category": "memory_policy",
        "primary_metric": "precision_at_1",
        "primary_label": "precision@1",
    },
    {
        "path": "benchmarks/long_memory_evidence_results.json",
        "benchmark": "Long-term memory evidence",
        "category": "memory_policy",
        "primary_metric": "precision_at_1",
        "primary_label": "precision@1",
    },
    {
        "path": "benchmarks/locomo_sentence_evidence_results.json",
        "benchmark": "LoCoMo sentence evidence retrieval",
        "category": "long_memory_retrieval",
        "primary_metric": "evidence_recall_at_k",
        "primary_label": "evidence recall@k",
    },
    {
        "path": "benchmarks/longmemeval_evidence_results.json",
        "benchmark": "LongMemEval evidence retrieval",
        "category": "long_memory_retrieval",
        "primary_metric": "evidence_recall_at_k",
        "primary_label": "evidence recall@k",
    },
    {
        "path": "benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json",
        "benchmark": "LongMemEval answer quality",
        "category": "answer_quality",
        "primary_metric": "token_f1",
        "primary_label": "token F1",
    },
)


def build_agent_impact_leaderboard(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(root)
    load_errors: list[str] = []
    benchmark_groups = _benchmark_groups(root, load_errors)
    rows = [row for group in benchmark_groups for row in group["rows"]]
    wavemind_rows = [row for row in rows if row["is_wavemind"]]
    baseline_rows = [row for row in rows if not row["is_wavemind"]]
    ranked_wavemind = _apply_ranks(sorted(wavemind_rows, key=_impact_ranking_key))

    summary = _summary(benchmark_groups, ranked_wavemind, baseline_rows)
    return {
        "schema": "wavemind.agent_impact_leaderboard.v1",
        "generated_at": _generated_at(root),
        "source_ref": _source_ref(root),
        "claim_boundary": (
            "Agent-impact rows come from checked-in benchmark artifacts. They show "
            "behavioral lift on the configured tasks; they do not claim general "
            "agent success outside the listed scenarios."
        ),
        "summary": summary,
        "benchmark_groups": benchmark_groups,
        "wavemind_rankings": ranked_wavemind,
        "baseline_rows": baseline_rows,
        "load_errors": load_errors,
    }


def render_agent_impact_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    rows = _table_rows(payload.get("wavemind_rankings", []), limit=12)
    groups = _group_rows(payload.get("benchmark_groups", []))
    return "\n".join(
        [
            "# WaveMind Agent Impact Leaderboard",
            "",
            f"Generated: `{payload.get('generated_at', 'unknown')}`.",
            "",
            str(payload.get("claim_boundary", "")),
            "",
            "## Summary",
            "",
            f"- Benchmarks covered: `{summary.get('benchmark_count', 0)}`.",
            f"- WaveMind rows: `{summary.get('wavemind_row_count', 0)}`.",
            f"- Baseline rows: `{summary.get('baseline_row_count', 0)}`.",
            f"- WaveMind primary wins: `{summary.get('wavemind_primary_wins', 0)}`.",
            f"- Average primary lift: `{_fmt(summary.get('average_primary_lift'))}`.",
            f"- Average context saved: `{_fmt(summary.get('average_context_saved'))}`.",
            f"- Average stale-safety score: `{_fmt(summary.get('average_stale_safety_score'))}`.",
            f"- Best impact profile: `{summary.get('best_impact_profile', '-')}`.",
            "",
            "## WaveMind Impact Ranking",
            "",
            "| rank | benchmark | engine | primary metric | value | best baseline | lift | stale safety | context saved | avg latency | source |",
            "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|",
            *rows,
            "",
            "## Benchmark Groups",
            "",
            "| benchmark | category | best WaveMind | best baseline | primary lift | source |",
            "|---|---|---:|---:|---:|---|",
            *groups,
            "",
            "## Reading Rules",
            "",
            "- Primary lift compares the best WaveMind variant with the best non-WaveMind baseline inside the same artifact.",
            "- Stale safety is `1 - stale_error_rate` when the benchmark reports stale errors, otherwise `stale_suppression` or `suppression_rate`.",
            "- Context saved measures prompt/context reduction where the artifact reports `context_budget_saved`.",
            "- Answer-quality rows use the checked-in local Ollama LongMemEval smoke artifact, not a full independent LLM benchmark.",
            "",
        ]
    )


def _benchmark_groups(root: Path, load_errors: list[str]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for spec in IMPACT_ARTIFACTS:
        source_file = str(spec["path"])
        payload = _load_json(root / source_file, load_errors)
        if not payload:
            continue
        result_rows = [
            _row_from_result(spec, source_file, result)
            for result in _iter_results(payload)
        ]
        result_rows = [row for row in result_rows if row is not None]
        if not result_rows:
            continue
        wavemind_rows = [row for row in result_rows if row["is_wavemind"]]
        baseline_rows = [row for row in result_rows if not row["is_wavemind"]]
        best_wavemind = max(
            (row["primary_value"] for row in wavemind_rows),
            default=None,
        )
        best_baseline = max(
            (row["primary_value"] for row in baseline_rows),
            default=None,
        )
        groups.append(
            {
                "benchmark": str(spec["benchmark"]),
                "category": str(spec["category"]),
                "primary_metric": str(spec["primary_metric"]),
                "primary_label": str(spec["primary_label"]),
                "source_file": source_file,
                "best_wavemind_primary": best_wavemind,
                "best_baseline_primary": best_baseline,
                "primary_lift": _lift(best_wavemind, best_baseline),
                "wavemind_win": best_wavemind is not None
                and best_baseline is not None
                and best_wavemind > best_baseline,
                "rows": _apply_group_context(result_rows, best_baseline),
            }
        )
    return groups


def _row_from_result(
    spec: Mapping[str, Any],
    source_file: str,
    result: Mapping[str, Any],
) -> dict[str, Any] | None:
    engine = str(result.get("engine") or "")
    if not engine:
        return None
    primary_metric = str(spec["primary_metric"])
    primary_value = _float_value(result.get(primary_metric))
    if primary_value is None:
        return None
    stale_safety = _stale_safety(result)
    context_saved = _float_value(result.get("context_budget_saved"))
    answer_faithfulness = _float_value(
        result.get("faithfulness_rate") or result.get("supported_answer_rate")
    )
    row = {
        "benchmark": str(spec["benchmark"]),
        "category": str(spec["category"]),
        "engine": engine,
        "is_wavemind": engine.startswith("WaveMind"),
        "source_file": source_file,
        "primary_metric": primary_metric,
        "primary_label": str(spec["primary_label"]),
        "primary_value": primary_value,
        "stale_safety_score": stale_safety,
        "context_budget_saved": context_saved,
        "avg_latency_ms": _float_value(
            result.get("avg_latency_ms") or result.get("avg_retrieval_ms")
        ),
        "p95_latency_ms": _float_value(result.get("p95_latency_ms")),
        "evidence_recall_at_k": _float_value(result.get("evidence_recall_at_k")),
        "precision_at_1": _float_value(result.get("precision_at_1")),
        "token_f1": _float_value(result.get("token_f1")),
        "answer_faithfulness_rate": answer_faithfulness,
        "unsupported_answer_rate": _float_value(result.get("unsupported_answer_rate")),
        "queries_or_tasks": _int_value(result.get("queries") or result.get("tasks") or result.get("checks")),
    }
    row["impact_score"] = _impact_score(row)
    return row


def _apply_group_context(
    rows: list[dict[str, Any]],
    best_baseline: float | None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        with_context = dict(row)
        with_context["best_baseline_primary"] = best_baseline
        with_context["primary_lift_vs_best_baseline"] = _lift(
            with_context["primary_value"],
            best_baseline,
        )
        enriched.append(with_context)
    return enriched


def _summary(
    benchmark_groups: list[dict[str, Any]],
    ranked_wavemind: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    wavemind_lifts = [
        float(row["primary_lift_vs_best_baseline"])
        for row in ranked_wavemind
        if row.get("primary_lift_vs_best_baseline") is not None
    ]
    context_saved = [
        float(row["context_budget_saved"])
        for row in ranked_wavemind
        if row.get("context_budget_saved") is not None
    ]
    stale_safety = [
        float(row["stale_safety_score"])
        for row in ranked_wavemind
        if row.get("stale_safety_score") is not None
    ]
    return {
        "benchmark_count": len(benchmark_groups),
        "wavemind_row_count": len(ranked_wavemind),
        "baseline_row_count": len(baseline_rows),
        "wavemind_primary_wins": sum(1 for group in benchmark_groups if group["wavemind_win"]),
        "average_primary_lift": _avg(wavemind_lifts),
        "average_context_saved": _avg(context_saved),
        "average_stale_safety_score": _avg(stale_safety),
        "best_impact_profile": ranked_wavemind[0]["profile"] if ranked_wavemind else None,
        "benchmarks_with_context_savings": sum(1 for value in context_saved if value > 0),
        "benchmarks_with_stale_safety": sum(1 for value in stale_safety if value >= 0.95),
        "source_files": [group["source_file"] for group in benchmark_groups],
    }


def _impact_score(row: Mapping[str, Any]) -> float:
    primary = float(row.get("primary_value") or 0.0)
    stale = float(row.get("stale_safety_score") or 0.0)
    context = float(row.get("context_budget_saved") or 0.0)
    faithfulness = float(row.get("answer_faithfulness_rate") or 0.0)
    latency = max(float(row.get("avg_latency_ms") or 0.0), 0.0)
    latency_penalty = min(latency / 1000.0, 0.25)
    return primary + 0.2 * stale + 0.15 * context + 0.15 * faithfulness - latency_penalty


def _stale_safety(result: Mapping[str, Any]) -> float | None:
    if result.get("stale_error_rate") is not None:
        return max(0.0, 1.0 - float(result.get("stale_error_rate") or 0.0))
    for key in ("stale_suppression", "suppression_rate"):
        if result.get(key) is not None:
            return _float_value(result.get(key))
    return None


def _iter_results(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    results = payload.get("results")
    if isinstance(results, list):
        for result in results:
            if isinstance(result, dict):
                yield result


def _apply_ranks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for index, row in enumerate(rows, start=1):
        with_rank = dict(row)
        with_rank["rank"] = index
        with_rank["profile"] = _profile_name(row)
        ranked.append(with_rank)
    return ranked


def _impact_ranking_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -float(row.get("primary_lift_vs_best_baseline") or 0.0),
        -float(row.get("impact_score") or 0.0),
        -float(row.get("primary_value") or 0.0),
        float(row.get("avg_latency_ms") or 1_000_000_000.0),
        str(row.get("benchmark") or ""),
        str(row.get("engine") or ""),
    )


def _table_rows(rows: Any, *, limit: int) -> list[str]:
    if not isinstance(rows, list):
        return []
    ranked = sorted((row for row in rows if isinstance(row, dict)), key=_impact_ranking_key)[
        :limit
    ]
    return [
        (
            f"| {int(row.get('rank') or index)} | {row.get('benchmark', '-')} | "
            f"{row.get('engine', '-')} | {row.get('primary_label', '-')} | "
            f"{_fmt(row.get('primary_value'))} | "
            f"{_fmt(row.get('best_baseline_primary'))} | "
            f"{_fmt(row.get('primary_lift_vs_best_baseline'))} | "
            f"{_fmt(row.get('stale_safety_score'))} | "
            f"{_fmt(row.get('context_budget_saved'))} | "
            f"{_fmt(row.get('avg_latency_ms'))} | "
            f"`{row.get('source_file', '-')}` |"
        )
        for index, row in enumerate(ranked, start=1)
    ]


def _group_rows(groups: Any) -> list[str]:
    if not isinstance(groups, list):
        return []
    return [
        (
            f"| {group.get('benchmark', '-')} | {group.get('category', '-')} | "
            f"{_fmt(group.get('best_wavemind_primary'))} | "
            f"{_fmt(group.get('best_baseline_primary'))} | "
            f"{_fmt(group.get('primary_lift'))} | "
            f"`{group.get('source_file', '-')}` |"
        )
        for group in groups
        if isinstance(group, dict)
    ]


def _profile_name(row: Mapping[str, Any]) -> str:
    benchmark = str(row.get("benchmark") or "benchmark").lower()
    engine = str(row.get("engine") or "engine").lower()
    for old, new in ((" ", "-"), ("/", "-"), ("+", "plus"), ("@", "at")):
        benchmark = benchmark.replace(old, new)
        engine = engine.replace(old, new)
    return f"{benchmark}-{engine}"


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing {path.as_posix()}")
        return {}
    except Exception as exc:
        errors.append(f"cannot read {path.as_posix()}: {exc}")
        return {}


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _lift(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    return value - baseline


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) >= 1000:
        return f"{number:,.2f}".rstrip("0").rstrip(".")
    if abs(number) >= 10:
        return f"{number:.2f}".rstrip("0").rstrip(".")
    return f"{number:.3f}".rstrip("0").rstrip(".")


def _generated_at(root: Path) -> str:
    value = os.environ.get("WAVEMIND_BENCHMARK_GENERATED_AT")
    if value:
        return value
    matrix = _load_json(root / "benchmarks" / "benchmark_matrix_results.json", [])
    matrix_time = matrix.get("generated_at")
    if isinstance(matrix_time, str) and matrix_time:
        return matrix_time
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_ref(root: Path) -> str:
    value = os.environ.get("GITHUB_SHA") or os.environ.get("WAVEMIND_BENCHMARK_SOURCE_REF")
    if value:
        return value
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/agent_impact_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/AGENT_IMPACT.md"),
    )
    args = parser.parse_args()

    payload = build_agent_impact_leaderboard()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_agent_impact_markdown(payload), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Wrote {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
