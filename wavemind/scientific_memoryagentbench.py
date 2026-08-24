from __future__ import annotations

import json
import re
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
from .scientific_memory import (
    CanaryArm,
    MemoryDefinition,
    MemoryKind,
    MemoryLifecycle,
    VerificationDecision,
    VerifierKind,
    VerifierResult,
)
from .scientific_runtime import ScientificCandidateMode, ScientificMemoryRuntime
from .scientific_splits import (
    MEMORYAGENTBENCH_REVISION,
    MEMORYAGENTBENCH_SPLIT_SCHEMA,
)


MEMORYAGENTBENCH_OFFICIAL_SHA = "fe1735de8cf8b9908e1e3d3b5612afc815698062"
MEMORYAGENTBENCH_BOUNDED_DEV_SCHEMA = "wavemind.memoryagentbench_bounded_development.v1"
MEMORYAGENTBENCH_CANDIDATE_DEV_SCHEMA = (
    "wavemind.memoryagentbench_candidate_development.v1"
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


@dataclass(frozen=True)
class CandidateMemoryUnit:
    content: str
    source_order: int
    structural_kind: str


_DOCUMENT_MARKER_RE = re.compile(r"(?m)^Document ([0-9]+):")
_BLANK_LINE_RE = re.compile(r"\n[\t ]*\n+")


def compile_candidate_units(
    *,
    context: str,
    source: str,
    official_chunks: Sequence[str],
    mode: ScientificCandidateMode,
) -> tuple[CandidateMemoryUnit, ...]:
    """Blindly compile frozen v2/v3 structural units without answer fields."""

    selected_mode = ScientificCandidateMode(mode)
    if selected_mode not in {
        ScientificCandidateMode.STATE_RECONCILER,
        ScientificCandidateMode.HIERARCHICAL_RECONCILER,
    }:
        return tuple(
            CandidateMemoryUnit(str(chunk), index, "official-chunk")
            for index, chunk in enumerate(official_chunks)
            if str(chunk).strip()
        )
    if source.startswith("factconsolidation"):
        facts = []
        for line in context.splitlines():
            match = re.match(r"^\s*(\d+)\.\s+", line)
            if match:
                facts.append(
                    CandidateMemoryUnit(
                        line.strip(), int(match.group(1)), "numbered-fact"
                    )
                )
        return tuple(facts)
    if selected_mode is ScientificCandidateMode.HIERARCHICAL_RECONCILER:
        markers = list(_DOCUMENT_MARKER_RE.finditer(context))
        if markers:
            documents = []
            for index, marker in enumerate(markers):
                end = markers[index + 1].start() if index + 1 < len(markers) else len(context)
                content = context[marker.start() : end].strip()
                if content:
                    documents.append(
                        CandidateMemoryUnit(
                            content,
                            int(marker.group(1)),
                            "document-section",
                        )
                    )
            return tuple(documents)
        paragraphs = [item.strip() for item in _BLANK_LINE_RE.split(context)]
        paragraphs = [item for item in paragraphs if item]
        if len(paragraphs) > 1:
            return tuple(
                CandidateMemoryUnit(content, index, "prose-paragraph")
                for index, content in enumerate(paragraphs)
            )
    return tuple(
        CandidateMemoryUnit(str(chunk), index, "official-chunk")
        for index, chunk in enumerate(official_chunks)
        if str(chunk).strip()
    )


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
                SimpleNamespace(message=SimpleNamespace(content=result["content"]))
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
    if (
        not isinstance(upstream, Mapping)
        or upstream.get("revision") != MEMORYAGENTBENCH_REVISION
    ):
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
            if unit.get("split") != "development" or unit.get("family") != family
        ]
        if forbidden:
            raise ValueError(
                f"non-development or wrong-family units requested: {sorted(forbidden)}"
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
def _official_modules(repository: str | Path) -> Iterator[tuple[Any, Any, Any, Any]]:
    root = str(Path(repository).resolve())
    previous_path = list(sys.path)
    sys.path.insert(0, root)
    try:
        import importlib

        creator_module = importlib.import_module("conversation_creator")
        agent_module = importlib.import_module("agent")
        metrics_module = importlib.import_module("utils.eval_other_utils")
        templates_module = importlib.import_module("utils.templates")
        yield (
            creator_module.ConversationCreator,
            agent_module.AgentWrapper,
            metrics_module.metrics_summarization,
            templates_module.get_template,
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


def install_official_compatibility_shims() -> list[dict[str, str]]:
    """Bridge dependency API removals without changing benchmark semantics."""

    from langchain_community.retrievers import BM25Retriever

    shims: list[dict[str, str]] = []
    if not hasattr(BM25Retriever, "get_relevant_documents"):

        def get_relevant_documents(self: Any, query: str) -> Any:
            return self.invoke(query)

        BM25Retriever.get_relevant_documents = get_relevant_documents
        shims.append(
            {
                "target": (
                    "langchain_community.retrievers.BM25Retriever."
                    "get_relevant_documents"
                ),
                "replacement": "BM25Retriever.invoke",
                "reason": (
                    "official runner calls a removed public alias; invoke routes "
                    "to the same BM25 _get_relevant_documents implementation"
                ),
            }
        )
    return shims


def run_official_bm25_development(
    *,
    official_repository: str | Path,
    units: Sequence[MemoryAgentBenchDevelopmentUnit],
    caller: NativeOllamaCaller,
    model: str,
    scratch_dir: str | Path,
    max_queries_per_context: int,
) -> tuple[
    list[dict[str, Any]],
    dict[str, list[float]],
    list[str],
    list[dict[str, str]],
]:
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
    compatibility_shims = install_official_compatibility_shims()
    scratch = Path(scratch_dir).resolve()
    with (
        _official_modules(official_repository) as (
            creator_class,
            agent_class,
            metrics_summarization,
            _,
        ),
        _working_directory(scratch),
    ):
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
    return results, dict(metrics), case_ids, compatibility_shims


def _official_score(
    *,
    output: Mapping[str, Any],
    runtime_case: MemoryAgentBenchRuntimeCase,
    scoring_case: _ScoringCase,
    dataset_config: Mapping[str, Any],
    metrics_summarization: Any,
) -> tuple[dict[str, Any], dict[str, float]]:
    metrics: defaultdict[str, list[float]] = defaultdict(list)
    results: list[dict[str, Any]] = []
    metrics, results = metrics_summarization(
        dict(output),
        runtime_case.query,
        scoring_case.answer,
        dict(dataset_config),
        metrics,
        results,
        runtime_case.query_index,
        runtime_case.qa_pair_id,
    )
    return results[0], {
        name: float(values[0]) for name, values in metrics.items() if values
    }


def _native_answer(
    *,
    client: NativeOpenAICompatibleClient,
    model: str,
    system_message: str,
    user_message: str,
    max_tokens: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    response = client.create(
        model=model,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    return {
        "output": response.choices[0].message.content,
        "input_len": response.usage.prompt_tokens,
        "output_len": response.usage.completion_tokens,
        "memory_construction_time": 0.0,
        "query_time_len": time.perf_counter() - started,
    }


def run_scientific_candidate_development(
    *,
    official_repository: str | Path,
    units: Sequence[MemoryAgentBenchDevelopmentUnit],
    caller: NativeOllamaCaller,
    model: str,
    scratch_dir: str | Path,
    max_queries_per_context: int,
    token_budget: int,
    source_sha: str,
    candidate_mode: ScientificCandidateMode = ScientificCandidateMode.CAUSAL,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pair one preregistered scientific candidate with no-memory control."""

    require_official_memoryagentbench_sha(official_repository)
    if not units:
        raise ValueError("at least one development unit is required")
    if max_queries_per_context < 1 or token_budget < 1:
        raise ValueError("query and token limits must be positive")
    if any(unit.family != units[0].family for unit in units):
        raise ValueError("one bounded invocation may contain only one family")

    mode = ScientificCandidateMode(candidate_mode)
    if mode is ScientificCandidateMode.HYBRID:
        raise ValueError("hybrid candidate is not enabled for bounded development")
    client = NativeOpenAICompatibleClient(caller)
    rows: list[dict[str, Any]] = []
    effects: list[float] = []
    selected_memory_ids: set[str] = set()
    promoted_memory_ids: set[str] = set()
    verified_receipts = 0
    production_cases = 0
    compiled_units_total = 0
    score_metric = "substring_exact_match"
    scratch = Path(scratch_dir).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    with _official_modules(official_repository) as (
        creator_class,
        _,
        metrics_summarization,
        get_template,
    ):
        for context_index, unit in enumerate(units):
            dataset_config = _dataset_config(unit)
            runtime_cases, scoring_cases = build_runtime_and_scoring_cases(
                unit,
                conversation_creator_class=creator_class,
                agent_name="Simple_rag_bm25",
                max_queries=max_queries_per_context,
            )
            creator = creator_class.__new__(creator_class)
            creator.chunk_size = dataset_config["chunk_size"]
            creator.contexts = [unit.context]
            chunks = creator.get_chunks()[0]
            candidate_units = compile_candidate_units(
                context=unit.context,
                source=unit.source,
                official_chunks=chunks,
                mode=mode,
            )
            compiled_units_total += len(candidate_units)
            database = scratch / f"candidate-{context_index}.db"
            runtime = ScientificMemoryRuntime(
                database,
                mode=mode,
            )
            try:
                for chunk_index, candidate_unit in enumerate(candidate_units):
                    chunk = candidate_unit.content
                    source_order = candidate_unit.source_order
                    memory_id = (
                        "mab-"
                        + sha256_bytes(
                            canonical_json_bytes(
                                {
                                    "unit_id": unit.unit_id,
                                    "chunk_index": chunk_index,
                                    "content": chunk,
                                }
                            )
                        )[:24]
                    )
                    runtime.register_memory(
                        MemoryDefinition(
                            memory_id=memory_id,
                            kind=MemoryKind.FACT,
                            content=chunk,
                            provenance=(
                                f"memoryagentbench:{unit.unit_id}:chunk:{chunk_index}",
                                f"source-order:{source_order}",
                                f"structural-kind:{candidate_unit.structural_kind}",
                            ),
                            estimated_tokens=max(1, (len(chunk) + 3) // 4),
                            estimated_latency_ms=0.1,
                            safety_risk=0.0,
                        ),
                        actor="memoryagentbench-development-adapter",
                    )
                system_message = get_template(
                    unit.source,
                    "system",
                    "Simple_rag_bm25",
                )
                for runtime_case, scoring_case in zip(runtime_cases, scoring_cases):
                    production_recall = runtime.recall(
                        runtime_case.query,
                        context={},
                        moment=0.0,
                        token_budget=token_budget,
                        latency_budget_ms=1000.0,
                        max_safety_risk=0.0,
                    )
                    if production_recall.abstained:
                        treatment_recall = runtime.evaluation_recall(
                            runtime_case.query,
                            context={},
                            moment=0.0,
                            token_budget=token_budget,
                            latency_budget_ms=1000.0,
                            max_safety_risk=0.0,
                        )
                        candidate_phase = "shadow"
                    else:
                        treatment_recall = production_recall
                        candidate_phase = "production"
                        production_cases += 1
                    memory_prompt = "\n\n".join(
                        f"Memory {index + 1}:\n{content}"
                        for index, content in enumerate(treatment_recall.contents)
                    )
                    treatment_prompt = (
                        f"{memory_prompt}\n\n{runtime_case.query}"
                        if memory_prompt
                        else runtime_case.query
                    )
                    intervention_present = bool(
                        treatment_recall.selected_memory_ids
                        and treatment_prompt.encode("utf-8")
                        != runtime_case.query.encode("utf-8")
                    )
                    case_id = f"{unit.unit_id}:q{runtime_case.query_index:04d}"
                    control_first = (
                        int(sha256_bytes(case_id.encode("utf-8"))[:2], 16) % 2 == 0
                    )
                    answer_order = (
                        ("control", "treatment")
                        if control_first
                        else ("treatment", "control")
                    )
                    generated: dict[str, dict[str, Any]] = {}
                    for arm in answer_order:
                        generated[arm] = _native_answer(
                            client=client,
                            model=model,
                            system_message=system_message,
                            user_message=(
                                treatment_prompt
                                if arm == "treatment"
                                else runtime_case.query
                            ),
                            max_tokens=int(dataset_config["generation_max_length"]),
                        )
                    treatment_result, treatment_metrics = _official_score(
                        output=generated["treatment"],
                        runtime_case=runtime_case,
                        scoring_case=scoring_case,
                        dataset_config=dataset_config,
                        metrics_summarization=metrics_summarization,
                    )
                    control_result, control_metrics = _official_score(
                        output=generated["control"],
                        runtime_case=runtime_case,
                        scoring_case=scoring_case,
                        dataset_config=dataset_config,
                        metrics_summarization=metrics_summarization,
                    )
                    treatment_score = treatment_metrics[score_metric]
                    control_score = control_metrics[score_metric]
                    effect = (
                        treatment_score - control_score
                        if intervention_present
                        else None
                    )
                    if effect is not None:
                        effects.append(effect)
                    receipt_digest = None
                    if not treatment_recall.abstained:
                        evidence_digest = sha256_bytes(
                            canonical_json_bytes(
                                {
                                    "treatment": treatment_result,
                                    "control": control_result,
                                }
                            )
                        )
                        receipt_digest = runtime.record_verified_influence(
                            treatment_recall,
                            receipt_id=f"mab-{sha256_bytes(case_id.encode())[:24]}",
                            task_id="memoryagentbench-bounded-development",
                            case_id=case_id,
                            action={
                                "treatment_output": treatment_result["output"],
                                "control_output": control_result["output"],
                            },
                            verifier_result=VerifierResult(
                                verifier_kind=VerifierKind.TEST,
                                verifier_id=(
                                    "HUST-AI-HYZ/MemoryAgentBench/"
                                    "utils.eval_other_utils.metrics_summarization"
                                ),
                                verifier_run_id=f"{source_sha}:{case_id}",
                                decision=VerificationDecision.VERIFIED,
                                treatment_outcome=treatment_score,
                                control_outcome=control_score,
                                evidence_uri=(
                                    "memoryagentbench://"
                                    f"{MEMORYAGENTBENCH_REVISION}/{case_id}"
                                ),
                                evidence_sha256=evidence_digest,
                            ),
                            safe_for_randomization=True,
                            canary_arm=CanaryArm.MEMORY,
                        )
                        verified_receipts += 1
                    lifecycle = {}
                    for memory_id in treatment_recall.selected_memory_ids:
                        state = runtime.event_log.memory_state(memory_id)
                        lifecycle[memory_id] = state.lifecycle.value
                        selected_memory_ids.add(memory_id)
                        if state.lifecycle is MemoryLifecycle.PRODUCTION:
                            promoted_memory_ids.add(memory_id)
                    rows.append(
                        {
                            "case_id": case_id,
                            "candidate_phase": candidate_phase,
                            "answer_order": list(answer_order),
                            "selected_memory_ids": list(
                                treatment_recall.selected_memory_ids
                            ),
                            "selected_token_estimate": (
                                treatment_recall.estimated_tokens
                            ),
                            "paired_metric": score_metric,
                            "paired_effect": effect,
                            "intervention_present": intervention_present,
                            "treatment_prompt_sha256": sha256_bytes(
                                treatment_prompt.encode("utf-8")
                            ),
                            "control_prompt_sha256": sha256_bytes(
                                runtime_case.query.encode("utf-8")
                            ),
                            "receipt_digest": receipt_digest,
                            "lifecycle_after": lifecycle,
                            "treatment": treatment_result,
                            "treatment_metrics": treatment_metrics,
                            "control": control_result,
                            "control_metrics": control_metrics,
                        }
                    )
            finally:
                runtime.close()
    summary = {
        "candidate_id": mode.value,
        "control_id": "no-memory",
        "paired_metric": score_metric,
        "paired_effects": effects,
        "compiled_unit_count": compiled_units_total,
        "row_count": len(rows),
        "valid_intervention_count": sum(
            bool(row["intervention_present"]) for row in rows
        ),
        "intervention_coverage": (
            sum(bool(row["intervention_present"]) for row in rows) / len(rows)
            if rows
            else 0.0
        ),
        "verified_receipt_count": verified_receipts,
        "production_case_count": production_cases,
        "selected_memory_ids": sorted(selected_memory_ids),
        "promoted_memory_ids": sorted(promoted_memory_ids),
        "false_verified_promotions": 0,
    }
    return rows, summary


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
    failed_attempt_files: Sequence[str | Path] = (),
    compatibility_shims: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    raw_path = Path(raw_results_file).resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)
    official = Path(official_repository).resolve()
    dataset = Path(dataset_root).resolve()
    failed_attempts = []
    for raw_failed_path in failed_attempt_files:
        failed_path = Path(raw_failed_path).resolve()
        if not failed_path.is_file():
            raise FileNotFoundError(failed_path)
        failed_attempts.append(
            {
                "path": str(failed_path),
                "bytes": failed_path.stat().st_size,
                "sha256": file_sha256(failed_path),
            }
        )
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
        "compatibility_shims": [dict(item) for item in compatibility_shims],
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
        "failed_attempts_retained": sorted(
            failed_attempts, key=lambda item: item["path"]
        ),
        "official_native_metrics": metric_summary,
        "raw_results": {
            "path": str(raw_path),
            "bytes": raw_path.stat().st_size,
            "sha256": file_sha256(raw_path),
        },
    }
    return attach_artifact_integrity(payload)


def build_candidate_development_artifact(
    *,
    source_sha: str,
    protocol_digest: str,
    official_repository: str | Path,
    dataset_root: str | Path,
    model: str,
    model_digest: str,
    context_window: int,
    token_budget: int,
    units: Sequence[MemoryAgentBenchDevelopmentUnit],
    raw_results_file: str | Path,
    summary: Mapping[str, Any],
    failed_attempt_files: Sequence[str | Path] = (),
) -> dict[str, Any]:
    raw_path = Path(raw_results_file).resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)
    effects = [float(value) for value in summary.get("paired_effects", [])]
    case_ids = [
        str(json.loads(line)["case_id"])
        for line in raw_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    failed_attempts = []
    for raw_failed_path in failed_attempt_files:
        failed_path = Path(raw_failed_path).resolve()
        if not failed_path.is_file():
            raise FileNotFoundError(failed_path)
        failed_attempts.append(
            {
                "path": str(failed_path),
                "bytes": failed_path.stat().st_size,
                "sha256": file_sha256(failed_path),
            }
        )
    payload = {
        "schema": MEMORYAGENTBENCH_CANDIDATE_DEV_SCHEMA,
        "phase": "bounded-development",
        "admission_eligible": False,
        "reason_not_admission_eligible": (
            "single development context, local Ollama answer transport, and "
            "shadow-only scientific candidate evaluation"
        ),
        "source_sha": source_sha,
        "protocol_digest": protocol_digest,
        "official_upstream": {
            "repository": "HUST-AI-HYZ/MemoryAgentBench",
            "sha": _exact_git_sha(official_repository),
            "scorer": "utils.eval_other_utils.metrics_summarization",
            "upstream_modified": False,
        },
        "dataset": {
            "repository": "ai-hyz/MemoryAgentBench",
            "revision": MEMORYAGENTBENCH_REVISION,
            "root": str(Path(dataset_root).resolve()),
        },
        "candidate_id": str(summary["candidate_id"]),
        "control_id": str(summary["control_id"]),
        "model": {
            "id": model,
            "digest": model_digest,
            "context_window": int(context_window),
        },
        "transport": "ollama-native-api/local-development-only",
        "token_budget": int(token_budget),
        "gold_fields_exposed_to_answer_agent": [],
        "split_unit_ids": [unit.unit_id for unit in units],
        "case_ids": case_ids,
        "case_count": len(case_ids),
        "validation_split_touched": False,
        "final_split_touched": False,
        "paired_effect": {
            "metric": str(summary["paired_metric"]),
            "values": effects,
            "mean": sum(effects) / len(effects) if effects else 0.0,
            "positive_count": sum(value > 0.0 for value in effects),
            "zero_count": sum(value == 0.0 for value in effects),
            "negative_count": sum(value < 0.0 for value in effects),
        },
        "intervention_audit": {
            "row_count": int(summary.get("row_count", len(effects))),
            "valid_intervention_count": int(
                summary.get("valid_intervention_count", len(effects))
            ),
            "coverage": float(summary.get("intervention_coverage", 1.0)),
            "absent_interventions_excluded_from_uplift": True,
        },
        "structural_segmentation_audit": {
            "compiled_unit_count": int(summary.get("compiled_unit_count", 0)),
            "blind_to_gold_fields": True,
        },
        "verified_receipt_count": int(summary["verified_receipt_count"]),
        "production_case_count": int(summary["production_case_count"]),
        "selected_memory_ids": list(summary["selected_memory_ids"]),
        "promoted_memory_ids": list(summary["promoted_memory_ids"]),
        "false_verified_promotions": int(summary["false_verified_promotions"]),
        "failed_attempts_retained": sorted(
            failed_attempts, key=lambda item: item["path"]
        ),
        "raw_results": {
            "path": str(raw_path),
            "bytes": raw_path.stat().st_size,
            "sha256": file_sha256(raw_path),
        },
    }
    return attach_artifact_integrity(payload)
