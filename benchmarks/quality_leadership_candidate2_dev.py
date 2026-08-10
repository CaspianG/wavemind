from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.long_memory_evidence_benchmark import (
    EvidenceDataset,
    EvidenceMetrics,
    EvidenceQuery,
    LongMemory,
    cache_encoder_for_dataset,
    create_benchmark_encoder,
    run_static_vector,
    run_wavemind,
    run_wavemind_memory_os,
)
from benchmarks.quality_leadership_freeze_protocol import CANDIDATE2_LANE


ROWS_API = "https://datasets-server.huggingface.co/rows"
FINGERPRINT_RE = re.compile(
    r"^memoryagentbench:(?P<revision>[0-9a-f]{40}):(?P<split>[^:]+):row:(?P<index>\d{4})$"
)
DEFAULT_PROTOCOL = Path("benchmarks/quality_leadership_protocol.json")
DEFAULT_OUTPUT = Path(
    "benchmarks/quality_leadership_agent_memory_advantage_dev_candidate2.json"
)
DEFAULT_PER_QUERY = Path(
    "benchmarks/quality_leadership_candidate2_dev_per_query.jsonl"
)
MEASUREMENT_TRIALS = 5
BOOTSTRAP_SAMPLES = 4000
BOOTSTRAP_SEED = 20260811


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _source_ref() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _bootstrap_ci(values: list[float], *, seed: int) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "lower": 0.0, "upper": 0.0, "observations": 0}
    generator = random.Random(seed)
    means = sorted(
        statistics.mean(generator.choice(values) for _ in values)
        for _ in range(BOOTSTRAP_SAMPLES)
    )
    lower_index = min(len(means) - 1, int(len(means) * 0.025))
    upper_index = min(len(means) - 1, int(len(means) * 0.975))
    return {
        "mean": statistics.mean(values),
        "lower": means[lower_index],
        "upper": means[upper_index],
        "observations": len(values),
    }


def _paired_ci(
    left: list[float],
    right: list[float],
    *,
    seed_offset: int,
) -> dict[str, float]:
    if len(left) != len(right) or not left:
        return {"mean": 0.0, "lower": 0.0, "upper": 0.0, "observations": 0}
    return _bootstrap_ci(
        [float(a) - float(b) for a, b in zip(left, right)],
        seed=BOOTSTRAP_SEED + seed_offset,
    )


def _load_protocol(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    dataset = payload.get("new_quality_dataset")
    if not isinstance(dataset, Mapping):
        raise ValueError("quality leadership protocol has no dataset manifest")
    if dataset.get("lane") != CANDIDATE2_LANE:
        raise ValueError(f"protocol lane must be {CANDIDATE2_LANE}")
    if dataset.get("held_out_viewed") is not False:
        raise ValueError("candidate2 held-out must remain unopened")
    held_out = dataset.get("held_out_split")
    if not isinstance(held_out, Mapping) or held_out.get("view_status") != "unopened":
        raise ValueError("candidate2 held-out split must be unopened")
    return payload


def development_rows_from_protocol(protocol: Mapping[str, Any]) -> dict[str, list[int]]:
    dataset = protocol.get("new_quality_dataset")
    if not isinstance(dataset, Mapping):
        raise ValueError("protocol dataset missing")
    development = dataset.get("development_split")
    held_out = dataset.get("held_out_split")
    if not isinstance(development, Mapping) or not isinstance(held_out, Mapping):
        raise ValueError("protocol split manifests missing")
    development_rows = _rows_by_split(development)
    held_out_rows = _rows_by_split(held_out)
    overlap = {
        split: sorted(set(rows) & set(held_out_rows.get(split, ())))
        for split, rows in development_rows.items()
    }
    overlap = {split: rows for split, rows in overlap.items() if rows}
    if overlap:
        raise ValueError(f"development/held-out row overlap: {overlap}")
    for split, rows in development_rows.items():
        expected = list(range(len(rows)))
        if rows != expected:
            raise ValueError(
                "candidate2 dev rows must be contiguous from zero before "
                f"row-content access: {split}={rows}"
            )
    return development_rows


def _rows_by_split(split_manifest: Mapping[str, Any]) -> dict[str, list[int]]:
    rows: dict[str, list[int]] = {}
    for fingerprint in split_manifest.get("case_fingerprints") or []:
        if not isinstance(fingerprint, str):
            continue
        match = FINGERPRINT_RE.match(fingerprint)
        if not match:
            raise ValueError(f"invalid MemoryAgentBench fingerprint: {fingerprint}")
        split = match.group("split")
        rows.setdefault(split, []).append(int(match.group("index")))
    return {split: sorted(indices) for split, indices in sorted(rows.items())}


def fetch_memory_agent_bench_development_rows(
    *,
    dataset_revision: str,
    development_rows: Mapping[str, list[int]],
    timeout_seconds: float = 60.0,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split, indices in sorted(development_rows.items()):
        if not indices:
            continue
        offset = min(indices)
        length = max(indices) - offset + 1
        if indices != list(range(offset, offset + length)):
            raise ValueError(f"non-contiguous development rows for {split}: {indices}")
        query = urllib.parse.urlencode(
            {
                "dataset": "ai-hyz/MemoryAgentBench",
                "config": "default",
                "split": split,
                "offset": offset,
                "length": length,
                "revision": dataset_revision,
            }
        )
        started = time.perf_counter()
        with urllib.request.urlopen(f"{ROWS_API}?{query}", timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        fetch_ms = (time.perf_counter() - started) * 1000.0
        if payload.get("partial") is True:
            raise ValueError(f"HF rows API returned partial data for {split}")
        fetched = payload.get("rows")
        if not isinstance(fetched, list):
            raise ValueError(f"HF rows API returned no rows for {split}")
        fetched_indices = [int(row.get("row_idx")) for row in fetched]
        if fetched_indices != indices:
            raise ValueError(
                f"HF rows API returned unexpected rows for {split}: {fetched_indices}"
            )
        for item in fetched:
            if item.get("truncated_cells"):
                raise ValueError(f"HF rows API truncated dev row for {split}")
            row = item.get("row")
            if not isinstance(row, Mapping):
                raise ValueError(f"HF rows API row payload missing for {split}")
            rows.append(
                {
                    "split": split,
                    "row_idx": int(item["row_idx"]),
                    "row": dict(row),
                    "fetch_ms": fetch_ms,
                }
            )
    return rows


def build_candidate2_dataset(
    rows: list[Mapping[str, Any]],
    *,
    questions_per_row: int,
) -> tuple[EvidenceDataset, list[dict[str, Any]], dict[str, Any]]:
    memories: list[LongMemory] = []
    queries: list[EvidenceQuery] = []
    per_query: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for item in rows:
        split = str(item["split"])
        row_idx = int(item["row_idx"])
        row = item["row"]
        namespace = f"mab-dev::{split}::{row_idx:04d}"
        chunks = _context_chunks(str(row.get("context") or ""))
        chunk_ids: list[str] = []
        for chunk_index, chunk in enumerate(chunks):
            memory_id = f"{namespace}::chunk::{chunk_index:04d}"
            chunk_ids.append(memory_id)
            memories.append(
                LongMemory(
                    id=memory_id,
                    text=chunk,
                    namespace=namespace,
                    tags=("memoryagentbench", split),
                )
            )
        questions = row.get("questions") or []
        answers = row.get("answers") or []
        if not isinstance(questions, list) or not isinstance(answers, list):
            skipped["invalid_question_answer_payload"] += 1
            continue
        selected = 0
        for question_index, question in enumerate(questions):
            if selected >= questions_per_row:
                break
            answer_values = _answer_values(
                answers[question_index] if question_index < len(answers) else []
            )
            expected = tuple(
                memory_id
                for memory_id, chunk in zip(chunk_ids, chunks)
                if _contains_any_answer(chunk, answer_values)
            )
            if not expected:
                skipped["answer_not_literal_in_context"] += 1
                continue
            query_id = f"{namespace}::q::{question_index:04d}"
            queries.append(
                EvidenceQuery(
                    id=query_id,
                    text=str(question),
                    namespace=namespace,
                    expected_evidence_ids=expected,
                    category=split,
                )
            )
            per_query.append(
                {
                    "id": query_id,
                    "split": split,
                    "row_idx": row_idx,
                    "question_index": question_index,
                    "expected_evidence_count": len(expected),
                    "answer_values": answer_values[:5],
                }
            )
            selected += 1
    if not memories:
        raise ValueError("candidate2 dev dataset produced no memories")
    if not queries:
        raise ValueError("candidate2 dev dataset produced no literal-answer queries")
    metadata = {
        "rows": len(rows),
        "memories": len(memories),
        "queries": len(queries),
        "questions_per_row": questions_per_row,
        "skipped": dict(sorted(skipped.items())),
        "category_query_counts": dict(
            sorted(Counter(query.category for query in queries).items())
        ),
    }
    return (
        EvidenceDataset(
            name="memoryagentbench-candidate2-development-v2",
            memories=memories,
            queries=queries,
        ),
        per_query,
        metadata,
    )


def _context_chunks(context: str) -> list[str]:
    lines = [line.strip() for line in context.splitlines() if line.strip()]
    chunks: list[str] = []
    current: list[str] = []
    for line in lines:
        if len(line) > 1200:
            if current:
                chunks.append(" ".join(current))
                current = []
            chunks.extend(_split_long_line(line, max_length=900))
            continue
        current.append(line)
        if sum(len(part) for part in current) >= 700:
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks.append(" ".join(current))
    return chunks or [context]


def _split_long_line(line: str, *, max_length: int) -> list[str]:
    words = line.split()
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for word in words:
        if current and current_length + len(word) + 1 > max_length:
            chunks.append(" ".join(current))
            current = []
            current_length = 0
        current.append(word)
        current_length += len(word) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks


def _answer_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        values.append(value)
    elif isinstance(value, list):
        for item in value:
            values.extend(_answer_values(item))
    return [item.strip() for item in values if item and item.strip()]


def _contains_any_answer(chunk: str, answers: list[str]) -> bool:
    normalized = _normalize(chunk)
    return any(_normalize(answer) in normalized for answer in answers)


def _normalize(value: str) -> str:
    return " ".join(str(value).casefold().split())


def _run_engine_trials(
    dataset: EvidenceDataset,
    *,
    top_k: int,
    measurement_trials: int,
) -> dict[str, list[EvidenceMetrics]]:
    base_encoder = create_benchmark_encoder("hash-token", vector_dim=384)
    cached_encoder = cache_encoder_for_dataset(dataset, base_encoder)
    engines = {
        "WaveMind Core": run_wavemind,
        "WaveMind + Memory OS": run_wavemind_memory_os,
        "Static vector": run_static_vector,
    }
    trials: dict[str, list[EvidenceMetrics]] = {name: [] for name in engines}
    for _ in range(measurement_trials):
        for name, runner in engines.items():
            metrics = runner(dataset, cached_encoder, top_k)
            trials[name].append(_rename_engine(metrics, name))
    return trials


def _rename_engine(metrics: EvidenceMetrics, engine: str) -> EvidenceMetrics:
    payload = asdict(metrics)
    payload["engine"] = engine
    return EvidenceMetrics(**payload)


def _aggregate_engine(
    engine: str,
    trials: list[EvidenceMetrics],
    category_counts: Mapping[str, int],
) -> dict[str, Any]:
    task_values = [_task_success(metric, category_counts) for metric in trials]
    stale_values = [1.0 - float(metric.stale_suppression) for metric in trials]
    context_values = [float(metric.context_budget_saved) for metric in trials]
    result = {
        "engine": engine,
        "status": "pass",
        "eligible_for_comparison": engine == "Static vector",
        "embedding_comparable": True,
        "same_embedding_as_wavemind": True,
        "measurement_trials": len(trials),
        "task_success_rate": statistics.mean(task_values),
        "task_success_ci95": _bootstrap_ci(task_values, seed=BOOTSTRAP_SEED + 1),
        "stale_error_rate": statistics.mean(stale_values),
        "stale_error_ci95": _bootstrap_ci(stale_values, seed=BOOTSTRAP_SEED + 2),
        "context_budget_saved": statistics.mean(context_values),
        "context_budget_saved_ci95": _bootstrap_ci(
            context_values,
            seed=BOOTSTRAP_SEED + 3,
        ),
        "category_success": {
            category: statistics.mean(
                float(metric.category_success.get(category, 0.0))
                for metric in trials
            )
            for category in sorted(category_counts)
        },
        "context_tokens_returned": sum(
            int(metric.context_tokens_returned) for metric in trials
        ),
        "queries": sum(int(metric.queries) for metric in trials),
        "p50_latency_ms": statistics.median(
            float(metric.p50_latency_ms) for metric in trials
        ),
        "p95_latency_ms": statistics.median(
            float(metric.p95_latency_ms) for metric in trials
        ),
        "p99_latency_ms": statistics.median(
            float(metric.p99_latency_ms) for metric in trials
        ),
        "cache_hits": sum(int(metric.cache_hits) for metric in trials),
        "cache_misses": sum(int(metric.cache_misses) for metric in trials),
        "worker_runs": sum(int(metric.worker_runs) for metric in trials),
    }
    if engine == "Static vector":
        result["family"] = "static_vector_reference_not_required_competitor"
    return result


def _task_success(
    metric: EvidenceMetrics,
    category_counts: Mapping[str, int],
) -> float:
    total = sum(int(value) for value in category_counts.values())
    if total <= 0:
        return 0.0
    return sum(
        float(metric.category_success.get(category, 0.0)) * int(count)
        for category, count in category_counts.items()
    ) / total


def _paired_lift(
    core_trials: list[EvidenceMetrics],
    memory_os_trials: list[EvidenceMetrics],
    *,
    category_counts: Mapping[str, int],
) -> dict[str, Any]:
    core_task = [_task_success(metric, category_counts) for metric in core_trials]
    memory_task = [_task_success(metric, category_counts) for metric in memory_os_trials]
    categories = {}
    for index, category in enumerate(sorted(category_counts), start=1):
        categories[category] = _paired_ci(
            [
                float(metric.category_success.get(category, 0.0))
                for metric in memory_os_trials
            ],
            [
                float(metric.category_success.get(category, 0.0))
                for metric in core_trials
            ],
            seed_offset=10 + index,
        )
    return {
        "overall_task_success": _paired_ci(
            memory_task,
            core_task,
            seed_offset=50,
        ),
        "categories": categories,
    }


def _optional_competitor_skips() -> list[dict[str, Any]]:
    return [
        {
            "engine": "Chroma static",
            "status": "skipped",
            "reason": "not_run_in_candidate2_bounded_dev; use same protocol before admission",
        },
        {
            "engine": "Qdrant static",
            "status": "skipped",
            "reason": "not_run_in_candidate2_bounded_dev; use same protocol before admission",
        },
        {
            "engine": "Mem0 OSS",
            "status": "skipped",
            "reason": "not_run_in_candidate2_bounded_dev; equal-embedding adapter required",
        },
        {
            "engine": "LangMem / LangGraph",
            "status": "skipped",
            "reason": "not_run_in_candidate2_bounded_dev; same-protocol run required",
        },
    ]


def run_candidate2_development(
    *,
    protocol_path: Path,
    questions_per_row: int = 8,
    top_k: int = 3,
    measurement_trials: int = MEASUREMENT_TRIALS,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if measurement_trials < MEASUREMENT_TRIALS:
        raise ValueError(f"measurement_trials must be >= {MEASUREMENT_TRIALS}")
    protocol = _load_protocol(protocol_path)
    dataset_manifest = protocol["new_quality_dataset"]
    revision = str(
        dataset_manifest["dataset_revisions"].get("development_huggingface")
        or dataset_manifest["dataset_revisions"].get("held_out_huggingface")
        or ""
    )
    if not revision:
        raise ValueError("candidate2 protocol has no Hugging Face revision")
    development_rows = development_rows_from_protocol(protocol)
    fetched_rows = fetch_memory_agent_bench_development_rows(
        dataset_revision=revision,
        development_rows=development_rows,
    )
    dataset, per_query, dataset_info = build_candidate2_dataset(
        fetched_rows,
        questions_per_row=questions_per_row,
    )
    category_counts = Counter(query.category for query in dataset.queries)
    trials = _run_engine_trials(
        dataset,
        top_k=top_k,
        measurement_trials=measurement_trials,
    )
    results = [
        _aggregate_engine(engine, values, category_counts)
        for engine, values in trials.items()
    ]
    paired = _paired_lift(
        trials["WaveMind Core"],
        trials["WaveMind + Memory OS"],
        category_counts=category_counts,
    )
    payload = {
        "schema": "wavemind.agent_memory_advantage_benchmark.v1",
        "status": "pass",
        "source_sha": _source_ref(),
        "generated_at": _utc_now(),
        "protocol": {
            "dataset": "ai-hyz/MemoryAgentBench",
            "lane": CANDIDATE2_LANE,
            "dataset_revision": dataset_manifest["revision"],
            "huggingface_revision": revision,
            "development_split_sha256": dataset_manifest["development_split_sha256"],
            "held_out_split_sha256": dataset_manifest["held_out_split_sha256"],
            "held_out_viewed": False,
            "measurement_trials": measurement_trials,
            "confidence_level": 0.95,
            "top_k": top_k,
            "questions_per_row": questions_per_row,
            "row_access": "huggingface_rows_api_development_rows_only",
        },
        "dataset_summary": dataset_info,
        "results": results,
        "skipped": _optional_competitor_skips(),
        "paired_lift": paired,
        "claim_boundary": (
            "Candidate2 bounded development diagnostic only. It opens only "
            "preregistered MemoryAgentBench development rows through the rows API. "
            "Held-out rows remain unopened and no public quality claim is allowed."
        ),
    }
    return payload, per_query


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--per-query-output", type=Path, default=DEFAULT_PER_QUERY)
    parser.add_argument("--questions-per-row", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--measurement-trials", type=int, default=MEASUREMENT_TRIALS)
    args = parser.parse_args()

    payload, per_query = run_candidate2_development(
        protocol_path=args.protocol,
        questions_per_row=args.questions_per_row,
        top_k=args.top_k,
        measurement_trials=args.measurement_trials,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.per_query_output.parent.mkdir(parents=True, exist_ok=True)
    with args.per_query_output.open("w", encoding="utf-8") as handle:
        header = {
            "schema": "wavemind.quality_leadership_candidate2_dev_per_query.v1",
            "source_sha": payload["source_sha"],
            "protocol": payload["protocol"],
            "query_count": len(per_query),
            "claim_boundary": payload["claim_boundary"],
        }
        handle.write(json.dumps(header, ensure_ascii=False, sort_keys=True) + "\n")
        for row in per_query:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
