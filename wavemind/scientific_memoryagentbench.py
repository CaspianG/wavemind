from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, Mapping, Sequence

from .evidence import (
    attach_artifact_integrity,
    canonical_json_bytes,
    file_sha256,
    sha256_bytes,
    validate_artifact_integrity,
)
from .scientific_memops import NativeOllamaCaller
from .scientific_splits import (
    MEMORYAGENTBENCH_REVISION,
    MEMORYAGENTBENCH_SPLIT_SCHEMA,
)


MEMORYAGENTBENCH_OFFICIAL_SHA = "fe1735de8cf8b9908e1e3d3b5612afc815698062"
MEMORYAGENTBENCH_BOUNDED_DEV_SCHEMA = (
    "wavemind.memoryagentbench_bounded_development.v1"
)


@dataclass(frozen=True)
class MemoryAgentBenchRuntimeCase:
    """The complete, deliberately gold-free view exposed to an answer agent."""

    unit_id: str
    family: str
    source: str
    query_index: int
    query: str
    qa_pair_id: str | None


@dataclass(frozen=True)
class _ScoringCase:
    runtime: MemoryAgentBenchRuntimeCase
    answer: Any


@dataclass(frozen=True)
class MemoryAgentBenchDevelopmentUnit:
    unit_id: str
    family: str
    source: str
    row_index: int
    context: str
    row: Mapping[str, Any]


class NativeOpenAICompatibleClient:
    """Small OpenAI-shape facade over the native Ollama development transport."""

    def __init__(self, caller: NativeOllamaCaller) -> None:
        self._caller = caller
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        **_: Any,
    ) -> Any:
        prompt = "\n\n".join(
            f"{str(message.get('role') or 'user').upper()}:\n"
            f"{str(message.get('content') or '')}"
            for message in messages
        )
        result = self._caller(
            prompt,
            model,
            temperature=temperature,
            max_tokens=max_tokens or 256,
        )
        usage = result["usage"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=result["content"])
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=int(usage["prompt_tokens"]),
                completion_tokens=int(usage["completion_tokens"]),
            ),
        )


def _exact_git_sha(repository: str | Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(repository),
        text=True,
        encoding="utf-8",
    ).strip()


def require_official_memoryagentbench_sha(repository: str | Path) -> None:
    actual = _exact_git_sha(repository)
    if actual != MEMORYAGENTBENCH_OFFICIAL_SHA:
        raise RuntimeError(
            "MemoryAgentBench upstream SHA mismatch: expected "
            f"{MEMORYAGENTBENCH_OFFICIAL_SHA}, got {actual}"
        )


def _safe_dataset_path(dataset_root: Path, relative_path: str) -> Path:
    relative = Path(relative_path.replace("/", os.sep))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("MemoryAgentBench source path escapes the dataset root")
    resolved = (dataset_root / relative).resolve()
    try:
        resolved.relative_to(dataset_root.resolve())
    except ValueError as exc:
        raise ValueError(
            "MemoryAgentBench source path escapes the dataset root"
        ) from exc
    return resolved


def load_development_units(
    *,
    dataset_root: str | Path,
    split_manifest: Mapping[str, Any],
    family: str,
    unit_ids: Sequence[str] | None = None,
    max_contexts: int | None = None,
) -> list[MemoryAgentBenchDevelopmentUnit]:
    """Load only preregistered development rows and verify their frozen hashes."""

    integrity_errors = validate_artifact_integrity(split_manifest)
    if integrity_errors:
        raise ValueError(
            "MemoryAgentBench split manifest integrity failed: "
            + "; ".join(integrity_errors)
        )
    if split_manifest.get("schema") != MEMORYAGENTBENCH_SPLIT_SCHEMA:
        raise ValueError("MemoryAgentBench split manifest schema mismatch")
    upstream = split_manifest.get("upstream")
    if not isinstance(upstream, Mapping) or upstream.get(
        "revision"
    ) != MEMORYAGENTBENCH_REVISION:
        raise ValueError("MemoryAgentBench dataset revision mismatch")
    if max_contexts is not None and max_contexts < 1:
        raise ValueError("max_contexts must be positive")

    raw_units = split_manifest.get("units")
    if not isinstance(raw_units, list):
        raise ValueError("MemoryAgentBench split units are missing")
    by_id = {
        str(unit.get("unit_id")): unit
        for unit in raw_units
        if isinstance(unit, Mapping)
    }
    if unit_ids is None:
        selected = [
            unit
            for unit in raw_units
            if isinstance(unit, Mapping)
            and unit.get("family") == family
            and unit.get("split") == "development"
        ]
    else:
        missing = sorted(set(unit_ids) - set(by_id))
        if missing:
            raise ValueError(f"unknown MemoryAgentBench unit IDs: {missing}")
        selected = [by_id[unit_id] for unit_id in unit_ids]
        forbidden = [
            str(unit.get("unit_id"))
            for unit in selected
            if unit.get("split") != "development"
            or unit.get("family") != family
        ]
        if forbidden:
            raise ValueError(
                "non-development or wrong-family units requested: "
                f"{sorted(forbidden)}"
            )
    selected = sorted(selected, key=lambda unit: str(unit.get("unit_id")))
    if max_contexts is not None:
        selected = selected[:max_contexts]
    if not selected:
        raise ValueError(f"no development units selected for {family}")

    import pyarrow.parquet as parquet

    root = Path(dataset_root).resolve()
    table_cache: dict[Path, list[dict[str, Any]]] = {}
    file_hash_cache: dict[Path, str] = {}
    loaded: list[MemoryAgentBenchDevelopmentUnit] = []
    for unit in selected:
        unit_id = str(unit["unit_id"])
        source_path = _safe_dataset_path(root, str(unit["source_file"]))
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        actual_file_hash = file_hash_cache.setdefault(
            source_path, file_sha256(source_path)
        )
        if actual_file_hash != unit.get("source_file_sha256"):
            raise ValueError(f"dataset file hash mismatch for {unit_id}")
        rows = table_cache.setdefault(
            source_path, parquet.read_table(source_path).to_pylist()
        )
        row_index = int(unit["row_index"])
        if row_index < 0 or row_index >= len(rows):
            raise ValueError(f"row index is invalid for {unit_id}")
        row = rows[row_index]
        context = str(row.get("context") or "")
        if sha256_bytes(context.encode("utf-8")) != unit.get("context_sha256"):
            raise ValueError(f"context hash mismatch for {unit_id}")
        metadata = row.get("metadata") or {}
        question_ids = list(metadata.get("question_ids") or [])
        if sha256_bytes(canonical_json_bytes(question_ids)) != unit.get(
            "question_ids_sha256"
        ):
            raise ValueError(f"question ID hash mismatch for {unit_id}")
        loaded.append(
            MemoryAgentBenchDevelopmentUnit(
                unit_id=unit_id,
                family=family,
                source=str(metadata.get("source") or ""),
                row_index=row_index,
                context=context,
                row=row,
            )
        )
    return loaded


def build_runtime_and_scoring_cases(
    unit: MemoryAgentBenchDevelopmentUnit,
    *,
    conversation_creator_class: type,
    agent_name: str,
    max_queries: int,
) -> tuple[list[MemoryAgentBenchRuntimeCase], list[_ScoringCase]]:
    """Use the official formatter, then separate runtime and scorer views."""

    if max_queries < 1:
        raise ValueError("max_queries must be positive")
    creator = conversation_creator_class.__new__(conversation_creator_class)
    creator.sub_dataset = unit.source
    creator.agent_name = agent_name
    _, official_pairs = creator._process_dataset_item(dict(unit.row))
    runtime_cases: list[MemoryAgentBenchRuntimeCase] = []
    scoring_cases: list[_ScoringCase] = []
    for query_index, (query, answer, qa_pair_id) in enumerate(
        official_pairs[:max_queries]
    ):
        runtime = MemoryAgentBenchRuntimeCase(
            unit_id=unit.unit_id,
            family=unit.family,
            source=unit.source,
            query_index=query_index,
            query=str(query),
            qa_pair_id=str(qa_pair_id) if qa_pair_id is not None else None,
        )
        runtime_cases.append(runtime)
        scoring_cases.append(_ScoringCase(runtime=runtime, answer=answer))
    return runtime_cases, scoring_cases


@contextmanager
def _official_modules(repository: str | Path) -> Iterator[tuple[Any, Any, Any]]:
    root = str(Path(repository).resolve())
    previous_path = list(sys.path)
    sys.path.insert(0, root)
    try:
        import importlib

        creator_module = importlib.import_module("conversation_creator")
        agent_module = importlib.import_module("agent")
        metrics_module = importlib.import_module("utils.eval_other_utils")
        yield (
            creator_module.ConversationCreator,
            agent_module.AgentWrapper,
            metrics_module.metrics_summarization,
        )
    finally:
        sys.path[:] = previous_path


@contextmanager
def _working_directory(path: str | Path) -> Iterator[None]:
    previous = Path.cwd()
    target = Path(path).resolve()
    target.mkdir(parents=True, exist_ok=True)
    os.chdir(target)
    try:
        yield
    finally:
        os.chdir(previous)


def _agent_config(*, model: str, output_dir: Path) -> dict[str, Any]:
    return {
        "agent_name": "Simple_rag_bm25",
        "model": model,
        "temperature": 0.0,
        "input_length_limit": 10_000_000,
        "buffer_length": 200,
        "output_dir": str(output_dir),
        "retrieve_num": 10,
    }


def _dataset_config(unit: MemoryAgentBenchDevelopmentUnit) -> dict[str, Any]:
    return {
        "dataset": unit.family,
        "chunk_size": 4096,
        "debug": False,
        "seed": 42,
        "context_max_length": 10_000_000,
        "sub_dataset": unit.source,
        "generation_max_length": 256,
        "max_test_samples": 1,
    }


def run_official_bm25_development(
    *,
    official_repository: str | Path,
    units: Sequence[MemoryAgentBenchDevelopmentUnit],
    caller: NativeOllamaCaller,
    model: str,
    scratch_dir: str | Path,
    max_queries_per_context: int,
) -> tuple[list[dict[str, Any]], dict[str, list[float]], list[str]]:
    """Run official formatter, BM25 agent logic, and native official metrics."""

    require_official_memoryagentbench_sha(official_repository)
    if not units:
        raise ValueError("at least one development unit is required")
    if max_queries_per_context < 1:
        raise ValueError("max_queries_per_context must be positive")
    if any(unit.family != units[0].family for unit in units):
        raise ValueError("one bounded invocation may contain only one family")

    metrics: defaultdict[str, list[float]] = defaultdict(list)
    results: list[dict[str, Any]] = []
    case_ids: list[str] = []
    native_client = NativeOpenAICompatibleClient(caller)
    scratch = Path(scratch_dir).resolve()
    with _official_modules(official_repository) as (
        creator_class,
        agent_class,
        metrics_summarization,
    ), _working_directory(scratch):
        for context_index, unit in enumerate(units):
            agent_config = _agent_config(model=model, output_dir=scratch / "outputs")
            dataset_config = _dataset_config(unit)
            runtime_cases, scoring_cases = build_runtime_and_scoring_cases(
                unit,
                conversation_creator_class=creator_class,
                agent_name=agent_config["agent_name"],
                max_queries=max_queries_per_context,
            )
            creator = creator_class.__new__(creator_class)
            creator.chunk_size = dataset_config["chunk_size"]
            creator.contexts = [unit.context]
            chunks = creator.get_chunks()[0]
            agent = agent_class(
                agent_config,
                dataset_config,
                load_agent_from=str(scratch / "agents" / unit.unit_id),
            )
            agent._create_oai_client = lambda: native_client
            for chunk in chunks:
                agent.send_message(
                    chunk,
                    memorizing=True,
                    context_id=context_index,
                )
            for runtime, scoring in zip(runtime_cases, scoring_cases):
                started = time.perf_counter()
                output = agent.send_message(
                    runtime.query,
                    memorizing=False,
                    query_id=runtime.query_index,
                    context_id=context_index,
                )
                elapsed = time.perf_counter() - started
                output["adapter_wall_seconds"] = elapsed
                metrics, results = metrics_summarization(
                    output,
                    runtime.query,
                    scoring.answer,
                    dataset_config,
                    metrics,
                    results,
                    runtime.query_index,
                    runtime.qa_pair_id,
                )
                case_id = f"{unit.unit_id}:q{runtime.query_index:04d}"
                results[-1]["scientific_case_id"] = case_id
                results[-1]["scientific_unit_id"] = unit.unit_id
                case_ids.append(case_id)
    return results, dict(metrics), case_ids


def write_raw_results(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    output = Path(path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return output


def build_bounded_development_artifact(
    *,
    source_sha: str,
    official_repository: str | Path,
    dataset_root: str | Path,
    model: str,
    model_digest: str,
    context_window: int,
    units: Sequence[MemoryAgentBenchDevelopmentUnit],
    case_ids: Sequence[str],
    raw_results_file: str | Path,
    metrics: Mapping[str, Sequence[float]],
) -> dict[str, Any]:
    raw_path = Path(raw_results_file).resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)
    official = Path(official_repository).resolve()
    dataset = Path(dataset_root).resolve()
    metric_summary = {
        name: {
            "count": len(values),
            "mean": sum(float(value) for value in values) / len(values)
            if values
            else 0.0,
            "values": [float(value) for value in values],
        }
        for name, values in sorted(metrics.items())
    }
    payload = {
        "schema": MEMORYAGENTBENCH_BOUNDED_DEV_SCHEMA,
        "phase": "bounded-development",
        "admission_eligible": False,
        "reason_not_admission_eligible": (
            "development split and local Ollama answer transport; no held-out "
            "validation/final context was loaded"
        ),
        "source_sha": source_sha,
        "official_upstream": {
            "repository": "HUST-AI-HYZ/MemoryAgentBench",
            "sha": _exact_git_sha(official),
            "main_py_sha256": file_sha256(official / "main.py"),
            "execution": (
                "split-enforcing in-process adapter over official "
                "ConversationCreator, AgentWrapper BM25, and "
                "metrics_summarization"
            ),
            "upstream_modified": False,
        },
        "dataset": {
            "repository": "ai-hyz/MemoryAgentBench",
            "revision": MEMORYAGENTBENCH_REVISION,
            "root": str(dataset),
        },
        "model": {
            "id": model,
            "digest": model_digest,
            "context_window": int(context_window),
        },
        "transport": "ollama-native-api/local-development-only",
        "runtime_case_fields": [
            "unit_id",
            "family",
            "source",
            "query_index",
            "query",
            "qa_pair_id",
        ],
        "gold_fields_exposed_to_answer_agent": [],
        "split_unit_ids": [unit.unit_id for unit in units],
        "case_ids": list(case_ids),
        "case_count": len(case_ids),
        "validation_split_touched": False,
        "final_split_touched": False,
        "official_native_metrics": metric_summary,
        "raw_results": {
            "path": str(raw_path),
            "bytes": raw_path.stat().st_size,
            "sha256": file_sha256(raw_path),
        },
    }
    return attach_artifact_integrity(payload)
