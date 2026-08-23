from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import (
    attach_artifact_integrity,
    canonical_json_bytes,
    file_sha256,
    sha256_bytes,
)
from .scientific_baselines import (
    SCIENTIFIC_BASELINE_MATRIX_SCHEMA,
    BaselineCorpusItem,
    build_baseline_retrievers,
    close_baseline_retrievers,
    common_embedding_metadata,
    deterministic_arm_order,
    fresh_scratch_directory,
    frozen_baseline_configs,
    hardware_inventory,
    preload_real_baseline_modules,
    real_baseline_package_metadata,
    runtime_dependency_metadata,
)
from .scientific_memoryagentbench import (
    MEMORYAGENTBENCH_OFFICIAL_SHA,
    MemoryAgentBenchDevelopmentUnit,
    NativeOllamaCaller,
    NativeOpenAICompatibleClient,
    _dataset_config,
    _exact_git_sha,
    _native_answer,
    _official_modules,
    _official_score,
    build_runtime_and_scoring_cases,
    require_official_memoryagentbench_sha,
)
from .scientific_protocol import REQUIRED_BASELINES
from .scientific_splits import MEMORYAGENTBENCH_REVISION


def _context_prompt(contents: Sequence[str], query: str) -> str:
    memories = "\n\n".join(
        f"Memory {index + 1}:\n{content}" for index, content in enumerate(contents)
    )
    return f"{memories}\n\n{query}" if memories else query


def _prompt_sha256(
    *,
    model: str,
    system_message: str,
    user_message: str,
    max_tokens: int,
) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.0,
                "max_tokens": max_tokens,
            }
        )
    )


def _corpus_for_unit(
    unit: MemoryAgentBenchDevelopmentUnit,
    chunks: Sequence[str],
) -> list[BaselineCorpusItem]:
    return [
        BaselineCorpusItem(
            memory_id="mab-"
            + sha256_bytes(
                canonical_json_bytes(
                    {
                        "unit_id": unit.unit_id,
                        "chunk_index": index,
                        "content": chunk,
                    }
                )
            )[:24],
            text=chunk,
        )
        for index, chunk in enumerate(chunks)
    ]


def run_baseline_matrix_development(
    *,
    project_root: str | Path,
    protocol: Mapping[str, Any],
    official_repository: str | Path,
    units: Sequence[MemoryAgentBenchDevelopmentUnit],
    caller: NativeOllamaCaller,
    model: str,
    scratch_dir: str | Path,
    max_queries_per_context: int,
    token_budget: int,
    top_k: int,
    seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Execute every frozen baseline through real backends on bounded dev cases."""

    require_official_memoryagentbench_sha(official_repository)
    frozen_baseline_configs(protocol)
    real_baseline_package_metadata()
    preload_real_baseline_modules()
    if not units:
        raise ValueError("at least one development unit is required")
    if max_queries_per_context < 1 or token_budget < 1 or top_k < 1:
        raise ValueError("query, retrieval, and token limits must be positive")
    if any(unit.family != units[0].family for unit in units):
        raise ValueError("one baseline invocation may contain only one family")

    root_scratch = fresh_scratch_directory(scratch_dir)
    client = NativeOpenAICompatibleClient(caller)
    answer_cache: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    case_orders: dict[str, list[str]] = {}
    score_metric = "substring_exact_match"
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
            chunks = [str(chunk) for chunk in creator.get_chunks()[0]]
            corpus = _corpus_for_unit(unit, chunks)
            retrievers = build_baseline_retrievers(
                corpus=corpus,
                scratch_dir=root_scratch / f"context-{context_index:04d}",
                protocol=protocol,
                seed=seed,
            )
            try:
                system_message = get_template(
                    unit.source,
                    "system",
                    "Simple_rag_bm25",
                )
                for runtime_case, scoring_case in zip(runtime_cases, scoring_cases):
                    case_id = f"{unit.unit_id}:q{runtime_case.query_index:04d}"
                    arm_order = deterministic_arm_order(seed=seed, case_id=case_id)
                    case_orders[case_id] = arm_order
                    for arm_index, arm_id in enumerate(arm_order):
                        retrieval = retrievers[arm_id].retrieve(
                            runtime_case.query,
                            top_k=top_k,
                            token_budget=token_budget,
                        )
                        user_message = _context_prompt(
                            retrieval.contents,
                            runtime_case.query,
                        )
                        max_tokens = int(dataset_config["generation_max_length"])
                        prompt_digest = _prompt_sha256(
                            model=model,
                            system_message=system_message,
                            user_message=user_message,
                            max_tokens=max_tokens,
                        )
                        cache_hit = prompt_digest in answer_cache
                        if cache_hit:
                            generated = copy.deepcopy(answer_cache[prompt_digest])
                        else:
                            generated = _native_answer(
                                client=client,
                                model=model,
                                system_message=system_message,
                                user_message=user_message,
                                max_tokens=max_tokens,
                            )
                            answer_cache[prompt_digest] = copy.deepcopy(generated)
                        result, metrics = _official_score(
                            output=generated,
                            runtime_case=runtime_case,
                            scoring_case=scoring_case,
                            dataset_config=dataset_config,
                            metrics_summarization=metrics_summarization,
                        )
                        rows.append(
                            {
                                "case_id": case_id,
                                "unit_id": unit.unit_id,
                                "arm_id": arm_id,
                                "arm_index": arm_index,
                                "arm_order": list(arm_order),
                                "retrieval": {
                                    "memory_ids": list(retrieval.memory_ids),
                                    "content_sha256": retrieval.content_sha256,
                                    "content_item_sha256": [
                                        sha256_bytes(content.encode("utf-8"))
                                        for content in retrieval.contents
                                    ],
                                    "scores": list(retrieval.scores),
                                    "context_tokens": retrieval.context_tokens,
                                    "retrieval_ms": retrieval.retrieval_ms,
                                    "backend": dict(retrieval.backend),
                                },
                                "prompt_sha256": prompt_digest,
                                "prompt": {
                                    "encoding": "utf-8",
                                    "system_message": system_message,
                                    "user_message": user_message,
                                    "system_message_sha256": sha256_bytes(
                                        system_message.encode("utf-8")
                                    ),
                                    "user_message_sha256": sha256_bytes(
                                        user_message.encode("utf-8")
                                    ),
                                    "bytes": len(system_message.encode("utf-8"))
                                    + len(user_message.encode("utf-8")),
                                },
                                "answer_cache_hit": cache_hit,
                                "answer_cache_policy": (
                                    "exact complete prompt bytes only; bounded-development "
                                    "generation economy; cached timings excluded from admission"
                                ),
                                "official_result": result,
                                "official_metrics": metrics,
                            }
                        )
            finally:
                close_baseline_retrievers(retrievers)

    per_arm: dict[str, dict[str, Any]] = {}
    for arm_id in sorted(REQUIRED_BASELINES):
        selected = [row for row in rows if row["arm_id"] == arm_id]
        values = [float(row["official_metrics"][score_metric]) for row in selected]
        per_arm[arm_id] = {
            "case_count": len(selected),
            "metric": score_metric,
            "values": values,
            "mean": sum(values) / len(values) if values else 0.0,
            "mean_context_tokens": (
                sum(float(row["retrieval"]["context_tokens"]) for row in selected)
                / len(selected)
                if selected
                else 0.0
            ),
        }
    summary = {
        "score_metric": score_metric,
        "per_arm": per_arm,
        "case_orders": case_orders,
        "unique_prompt_count": len(answer_cache),
        "answer_invocation_count": len(answer_cache),
        "logical_arm_case_count": len(rows),
    }
    return rows, summary


def _ablation_pairs(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    configs = frozen_baseline_configs(protocol)
    pairs = [
        ("field-on-vs-field-off", "wavemind-no-field", "wavemind-wavefield"),
        ("graph-on-vs-graph-off", "wavemind-no-field", "wavemind-graph"),
        ("memory-os-on-vs-memory-os-off", "wavemind-wavefield", "wavemind-memory-os"),
        (
            "full-frozen-vs-memory-os",
            "wavemind-memory-os",
            "wavemind-full-frozen-pipeline",
        ),
    ]
    output: list[dict[str, Any]] = []
    for ablation_id, control_id, treatment_id in pairs:
        control = configs[control_id]
        treatment = configs[treatment_id]
        differences = {
            key: {"control": control.get(key), "treatment": treatment.get(key)}
            for key in sorted(set(control) | set(treatment))
            if control.get(key) != treatment.get(key)
        }
        output.append(
            {
                "id": ablation_id,
                "control_id": control_id,
                "treatment_id": treatment_id,
                "config_differences": differences,
                "single_factor": len(differences) == 1,
            }
        )
    return output


def summarize_raw_baseline_rows(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    expected_pairs = {(str(row["case_id"]), str(row["arm_id"])) for row in rows}
    case_ids = sorted({str(row["case_id"]) for row in rows})
    required_pairs = {
        (case_id, arm_id) for case_id in case_ids for arm_id in REQUIRED_BASELINES
    }
    if expected_pairs != required_pairs or len(rows) != len(required_pairs):
        raise ValueError("raw baseline rows are incomplete or duplicated")
    metric = "substring_exact_match"
    per_arm: dict[str, dict[str, Any]] = {}
    for arm_id in sorted(REQUIRED_BASELINES):
        selected = [row for row in rows if row["arm_id"] == arm_id]
        values = [float(row["official_metrics"][metric]) for row in selected]
        per_arm[arm_id] = {
            "case_count": len(selected),
            "metric": metric,
            "values": values,
            "mean": sum(values) / len(values),
            "mean_context_tokens": sum(
                float(row["retrieval"]["context_tokens"]) for row in selected
            )
            / len(selected),
        }
    prompt_digests = {str(row["prompt_sha256"]) for row in rows}
    return {
        "score_metric": metric,
        "per_arm": per_arm,
        "case_orders": {
            case_id: list(
                next(row for row in rows if row["case_id"] == case_id)["arm_order"]
            )
            for case_id in case_ids
        },
        "unique_prompt_count": len(prompt_digests),
        "answer_invocation_count": sum(
            not bool(row["answer_cache_hit"]) for row in rows
        ),
        "logical_arm_case_count": len(rows),
    }


def build_baseline_matrix_artifact(
    *,
    project_root: str | Path,
    source_sha: str,
    protocol: Mapping[str, Any],
    official_repository: str | Path,
    dataset_root: str | Path,
    model: str,
    model_digest: str,
    context_window: int,
    token_budget: int,
    top_k: int,
    seed: int,
    units: Sequence[MemoryAgentBenchDevelopmentUnit],
    raw_results_file: str | Path,
    summary: Mapping[str, Any],
    failed_attempt_files: Sequence[str | Path] = (),
) -> dict[str, Any]:
    raw_path = Path(raw_results_file).resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)
    official = Path(official_repository).resolve()
    dataset = Path(dataset_root).resolve()
    failed_attempts = []
    for value in failed_attempt_files:
        path = Path(value).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        failed_attempts.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    payload = {
        "schema": SCIENTIFIC_BASELINE_MATRIX_SCHEMA,
        "phase": "bounded-development",
        "admission_eligible": False,
        "reason_not_admission_eligible": (
            "development split, local Ollama transport, and exact-prompt answer "
            "cache; cached generation timings are excluded from admission"
        ),
        "source_sha": source_sha,
        "protocol_digest": protocol["protocol_digest"],
        "official_upstream": {
            "repository": "HUST-AI-HYZ/MemoryAgentBench",
            "expected_sha": MEMORYAGENTBENCH_OFFICIAL_SHA,
            "observed_sha": _exact_git_sha(official),
            "main_py_sha256": file_sha256(official / "main.py"),
            "upstream_modified": False,
        },
        "dataset": {
            "repository": "ai-hyz/MemoryAgentBench",
            "revision": MEMORYAGENTBENCH_REVISION,
            "root": str(dataset),
            "split_unit_ids": [unit.unit_id for unit in units],
            "validation_split_touched": False,
            "final_split_touched": False,
        },
        "controls": {
            "model": {
                "id": model,
                "digest": model_digest,
                "context_window": context_window,
                "temperature": 0.0,
            },
            "prompt": "official MemoryAgentBench system template and one common memory wrapper",
            "embedding": common_embedding_metadata(project_root),
            "seed": seed,
            "token_budget": token_budget,
            "top_k": top_k,
            "case_order": list(summary["case_orders"]),
            "hardware_inventory": hardware_inventory(),
        },
        "gold_fields_exposed_to_retrievers_or_answer_agent": [],
        "baselines_executed": sorted(REQUIRED_BASELINES),
        "frozen_baseline_configs": frozen_baseline_configs(protocol),
        "real_package_metadata": real_baseline_package_metadata(),
        "preloaded_real_package_modules": preload_real_baseline_modules(),
        "runtime_dependency_lock": runtime_dependency_metadata(),
        "real_package_execution": {
            "mem0-oss": "mem0.Memory.add(infer=False)/search with real local Qdrant",
            "langgraph": "langgraph.store.memory.InMemoryStore.put/search",
            "chroma": "chromadb.PersistentClient collection.add/query",
            "qdrant-local": "qdrant_client.QdrantClient local upsert/query_points",
        },
        "answer_cache": {
            "policy": "complete prompt sha256 equality only",
            "unique_prompt_count": summary["unique_prompt_count"],
            "answer_invocation_count": summary["answer_invocation_count"],
            "logical_arm_case_count": summary["logical_arm_case_count"],
            "timing_admission_eligible": False,
        },
        "official_metric_summary": dict(summary["per_arm"]),
        "ablation_pairs": _ablation_pairs(protocol),
        "failed_attempts_retained": sorted(
            failed_attempts, key=lambda row: row["path"]
        ),
        "raw_results": {
            "path": str(raw_path),
            "bytes": raw_path.stat().st_size,
            "sha256": file_sha256(raw_path),
        },
        "claim_boundary": (
            "Bounded development evidence only. This matrix cannot satisfy scientific "
            "admission and does not authorize held-out or public superiority claims."
        ),
    }
    return attach_artifact_integrity(payload)


def write_raw_baseline_rows(
    path: str | Path,
    rows: Sequence[Mapping[str, Any]],
) -> Path:
    output = Path(path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return output


def append_failed_attempt(
    path: str | Path,
    *,
    source_sha: str,
    stage: str,
    error: BaseException,
) -> Path:
    output = Path(path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "recorded_at_unix": time.time(),
        "source_sha": source_sha,
        "stage": stage,
        "error_type": type(error).__name__,
        "error": str(error),
    }
    with output.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return output
