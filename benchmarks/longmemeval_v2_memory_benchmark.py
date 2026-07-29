from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import random
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind
from wavemind.encoders import (
    DEFAULT_TOKEN_STOPWORDS,
    HashingTextEncoder,
    OllamaTextEncoder,
    TextVectorEncoder,
    encode_document_batch,
    encode_document_text,
    encode_query_text,
    is_stopword_token,
    normalize_token,
)
from wavemind.jobs import HotMemoryCache, MemoryOSWorker, query_with_cache
from wavemind.trajectory_consolidation import TrajectoryDeltaConsolidator


DATASET_REPO = "xiaowu0162/longmemeval-v2"
DATASET_REVISION = "f152293e235517d504809563c833d7190b8c713b"
OFFICIAL_REPO = "https://github.com/xiaowu0162/longmemeval-v2"
OFFICIAL_REPO_REVISION = "6f020ac2fc3275e46c706d3406e02c3ed79b7be2"
BOXED_RE = re.compile(r"\\boxed\{([^}]*)\}", re.IGNORECASE | re.DOTALL)
LLM_EVALUATORS = {"llm_abstention_checker", "llm_gotchas_checker"}
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {"correct": {"type": "boolean"}},
    "required": ["correct"],
    "additionalProperties": False,
}
RETRIEVAL_INSTRUCTION_STOPWORDS = frozenset(
    {
        "all",
        "am",
        "answer",
        "boxed",
        "each",
        "final",
        "had",
        "has",
        "have",
        "i",
        "in",
        "mark",
        "me",
        "more",
        "most",
        "my",
        "no",
        "not",
        "on",
        "one",
        "only",
        "our",
        "ours",
        "phrases",
        "short",
        "some",
        "than",
        "then",
        "them",
        "their",
        "they",
        "us",
        "was",
        "we",
        "were",
        "when",
        "working",
        "you",
        "your",
    }
)


@dataclass(frozen=True)
class V2Question:
    id: str
    domain: str
    environment: str
    question_type: str
    question: str
    image: str | None
    answer: str
    eval_function: str


@dataclass(frozen=True)
class V2Memory:
    id: str
    namespace: str
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class V2Dataset:
    questions: list[V2Question]
    memories: list[V2Memory]
    haystacks: dict[str, tuple[str, ...]]
    source_files: dict[str, str]


class Reader(Protocol):
    model: str
    supports_images: bool

    def answer(
        self,
        *,
        question: V2Question,
        context: list[str],
    ) -> str: ...

    def judge(
        self,
        *,
        evaluator: str,
        question: V2Question,
        response: str,
    ) -> bool: ...


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path} must contain JSON objects")
                rows.append(value)
    return rows


def _state_text(trajectory: dict[str, Any], state: dict[str, Any]) -> str:
    header = [
        f"Environment: {trajectory.get('environment', '')}",
        f"Trajectory goal: {trajectory.get('goal', '')}",
        f"Trajectory outcome: {trajectory.get('outcome', '')}",
        f"State index: {state.get('state_index', '')}",
        f"URL: {state.get('url', '')}",
        f"Action: {state.get('action', '')}",
        f"Thought: {state.get('thought', '')}",
        "Observed page:",
        str(state.get("accessibility_tree") or ""),
    ]
    return "\n".join(value for value in header if value.strip())


def _stratified_question_sample(
    rows: list[dict[str, Any]],
    *,
    sample_size: int,
    seed: int,
) -> list[dict[str, Any]]:
    if sample_size <= 0:
        raise ValueError("question_sample_size must be positive")
    if sample_size >= len(rows):
        return list(rows)
    buckets: dict[tuple[str, str, bool], list[int]] = {}
    for index, row in enumerate(rows):
        key = (
            str(row.get("domain") or ""),
            str(row.get("question_type") or ""),
            bool(row.get("image")),
        )
        buckets.setdefault(key, []).append(index)

    counts = {key: 0 for key in buckets}
    if sample_size >= len(buckets):
        for key in counts:
            counts[key] = 1
    targets = {
        key: sample_size * len(indices) / len(rows)
        for key, indices in buckets.items()
    }
    while sum(counts.values()) < sample_size:
        eligible = [
            key
            for key, indices in buckets.items()
            if counts[key] < len(indices)
        ]
        selected_key = max(
            eligible,
            key=lambda key: (
                targets[key] - counts[key],
                len(buckets[key]) - counts[key],
                key,
            ),
        )
        counts[selected_key] += 1

    rng = random.Random(seed)
    selected_indices: list[int] = []
    for key in sorted(buckets):
        indices = list(buckets[key])
        rng.shuffle(indices)
        selected_indices.extend(indices[: counts[key]])
    return [rows[index] for index in sorted(selected_indices)]


def load_longmemeval_v2_small(
    data_root: str | Path,
    *,
    limit_questions: int | None = None,
    question_sample_size: int | None = None,
    question_sample_seed: int = 20260728,
) -> V2Dataset:
    root = Path(data_root)
    questions_path = root / "questions.jsonl"
    trajectories_path = root / "trajectories.jsonl"
    haystack_path = root / "haystacks" / "lme_v2_small.json"
    for path in (questions_path, trajectories_path, haystack_path):
        if not path.exists():
            raise FileNotFoundError(path)

    raw_questions = _read_jsonl(questions_path)
    if limit_questions is not None and question_sample_size is not None:
        raise ValueError(
            "limit_questions and question_sample_size are mutually exclusive"
        )
    if limit_questions is not None:
        if limit_questions <= 0:
            raise ValueError("limit_questions must be positive")
        raw_questions = raw_questions[:limit_questions]
    elif question_sample_size is not None:
        raw_questions = _stratified_question_sample(
            raw_questions,
            sample_size=question_sample_size,
            seed=question_sample_seed,
        )
    questions = [
        V2Question(
            id=str(row["id"]),
            domain=str(row["domain"]),
            environment=str(row["environment"]),
            question_type=str(row["question_type"]),
            question=str(row["question"]),
            image=(
                str((root / str(row["image"])).resolve())
                if row.get("image")
                else None
            ),
            answer=str(row["answer"]),
            eval_function=str(row["eval_function"]),
        )
        for row in raw_questions
    ]
    haystacks = json.loads(haystack_path.read_text(encoding="utf-8"))
    selected_ids: set[str] = set()
    selected_haystacks: dict[str, tuple[str, ...]] = {}
    for question in questions:
        ids = haystacks.get(question.id)
        if not isinstance(ids, list) or len(ids) != 100:
            raise ValueError(
                f"small haystack for {question.id} must contain 100 trajectories"
            )
        selected = tuple(str(value) for value in ids)
        selected_haystacks[question.id] = selected
        selected_ids.update(selected)

    memories: list[V2Memory] = []
    found: set[str] = set()
    with trajectories_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            trajectory = json.loads(line)
            trajectory_id = str(trajectory.get("id") or "")
            if trajectory_id not in selected_ids:
                continue
            found.add(trajectory_id)
            namespace = f"longmemeval-v2-small:{trajectory.get('domain')}"
            for state in trajectory.get("states") or []:
                if not isinstance(state, dict):
                    continue
                state_index = int(state.get("state_index") or 0)
                text = _state_text(trajectory, state)
                if not text.strip():
                    continue
                memories.append(
                    V2Memory(
                        id=f"{trajectory_id}:state:{state_index}",
                        namespace=namespace,
                        text=text,
                        metadata={
                            "trajectory_id": trajectory_id,
                            "state_index": state_index,
                            "domain": trajectory.get("domain"),
                            "environment": trajectory.get("environment"),
                            "outcome": trajectory.get("outcome"),
                            "source": DATASET_REPO,
                        },
                    )
                )
    missing = selected_ids - found
    if missing:
        raise ValueError(f"missing {len(missing)} selected trajectories")
    for question in questions:
        if question.image and not Path(question.image).exists():
            raise FileNotFoundError(question.image)
    return V2Dataset(
        questions=questions,
        memories=memories,
        haystacks=selected_haystacks,
        source_files={
            "questions_sha256": _sha256(questions_path),
            "trajectories_sha256": _sha256(trajectories_path),
            "small_haystack_sha256": _sha256(haystack_path),
        },
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * percentile))
    return float(ordered[index])


def _token_estimate(text: str) -> int:
    return max(1, math.ceil(len(text.split()) * 1.25))


def _query_snippet(
    text: str,
    query: str,
    *,
    max_chars: int = 2_800,
    chunk_chars: int = 800,
    chunk_overlap: int = 160,
) -> str:
    if len(text) <= max_chars:
        return text
    if chunk_chars <= 0 or chunk_overlap < 0 or chunk_overlap >= chunk_chars:
        raise ValueError("snippet chunking requires 0 <= overlap < chunk size")
    query_terms = {
        token
        for token in re.findall(r"\w+", query.lower())
        if len(token) >= 3
    }
    chunks: list[str] = []
    for line in (line.strip() for line in text.splitlines() if line.strip()):
        if len(line) <= chunk_chars:
            chunks.append(line)
            continue
        step = chunk_chars - chunk_overlap
        chunks.extend(
            line[offset : offset + chunk_chars]
            for offset in range(0, len(line), step)
            if line[offset : offset + chunk_chars].strip()
        )
    def relevance(item: tuple[int, str]) -> tuple[float, int, int]:
        index, value = item
        matched = sum(term in value.lower() for term in query_terms)
        token_count = max(1, len(re.findall(r"\w+", value)))
        density = matched / math.sqrt(token_count)
        return (-density, -matched, index)

    ranked = sorted(enumerate(chunks), key=relevance)
    selected_indices: set[int] = set()
    total = 0
    for index, line in ranked:
        window = range(
            max(0, index - 2),
            min(len(chunks), index + 3),
        )
        additions = [
            neighbor
            for neighbor in window
            if neighbor not in selected_indices
        ]
        addition_size = sum(len(chunks[neighbor]) + 1 for neighbor in additions)
        if total + addition_size > max_chars:
            additions = [index] if index not in selected_indices else []
            addition_size = len(line) + 1 if additions else 0
        if total + addition_size > max_chars:
            continue
        selected_indices.update(additions)
        total += addition_size
        if total >= max_chars * 0.85:
            break
    return "\n".join(chunks[index] for index in sorted(selected_indices))


def _retrieval_query(text: str) -> str:
    semantic_text = re.split(
        r"\n+\s*Mark your final answer\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    tokens: list[str] = []
    for raw in re.findall(r"[\w]+", semantic_text.lower(), flags=re.UNICODE):
        normalized = normalize_token(raw)
        if (
            normalized in DEFAULT_TOKEN_STOPWORDS
            or normalized in RETRIEVAL_INSTRUCTION_STOPWORDS
            or is_stopword_token(raw)
        ):
            continue
        tokens.append(normalized)
    return " ".join(tokens) or semantic_text.strip()


class OllamaReader:
    def __init__(
        self,
        *,
        model: str,
        vision_model: str | None = None,
        base_url: str = "http://127.0.0.1:11434",
        supports_images: bool = False,
        timeout_seconds: float = 180.0,
        text_context_window: int = 8192,
        image_context_window: int = 4096,
        image_context_items: int = 1,
        image_context_chars: int = 4000,
        enable_thinking: bool = False,
        seed: int = 20260728,
    ) -> None:
        self.model = model
        self.vision_model = vision_model
        self.base_url = base_url.rstrip("/")
        self.supports_images = bool(supports_images or vision_model)
        self.timeout_seconds = float(timeout_seconds)
        self.text_context_window = int(text_context_window)
        if self.text_context_window < 4096:
            raise ValueError("text_context_window must be at least 4096")
        self.image_context_window = int(image_context_window)
        if self.image_context_window < 4096:
            raise ValueError("image_context_window must be at least 4096")
        self.image_context_items = int(image_context_items)
        if self.image_context_items <= 0:
            raise ValueError("image_context_items must be positive")
        self.image_context_chars = int(image_context_chars)
        if self.image_context_chars < 1000:
            raise ValueError("image_context_chars must be at least 1000")
        self.enable_thinking = bool(enable_thinking)
        self.structured_outputs = True
        self.seed = int(seed)
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

    def _generate(
        self,
        prompt: str,
        *,
        image: str | None = None,
        max_tokens: int = 256,
        system: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> str:
        selected_model = (
            self.vision_model
            if image is not None and self.vision_model
            else self.model
        )
        payload: dict[str, Any] = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
            "think": self.enable_thinking,
            "options": {
                "temperature": 0,
                "presence_penalty": 0,
                "top_k": 1,
                "seed": self.seed,
                "num_predict": int(max_tokens),
                "num_ctx": self.text_context_window,
            },
        }
        if system is not None:
            payload["system"] = system
        if output_schema is not None:
            payload["format"] = output_schema
        if image is not None:
            if not self.supports_images:
                raise RuntimeError(
                    f"reader {self.model} does not support question images"
                )
            payload["images"] = [
                base64.b64encode(Path(image).read_bytes()).decode("ascii")
            ]
            payload["options"]["num_ctx"] = self.image_context_window
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Ollama HTTP {exc.code} for model {selected_model}: {detail}"
            ) from exc
        return str(body.get("response") or "").strip()

    def answer(
        self,
        *,
        question: V2Question,
        context: list[str],
    ) -> str:
        selected_context = context
        if question.image is not None:
            selected_context = [
                _bounded_evidence(value, self.image_context_chars)
                for value in context[: self.image_context_items]
            ]
        prompt = (
            f"Question:\n{question.question}\n\n"
            "Memory evidence:\n"
            + "\n\n---\n\n".join(selected_context)
        )
        raw = self._generate(
            prompt,
            image=question.image,
            system=(
                "You are a precise benchmark evidence reader. Fill only the "
                "answer field with one concise final answer. Copy labels, "
                "numbers, and ordered phrases verbatim from the evidence. Do "
                "not explain or repeat the evidence. If the premise conflicts "
                "with the evidence, answer with only the concise correction."
            ),
            output_schema=ANSWER_SCHEMA,
        )
        try:
            answer = str(json.loads(raw)["answer"]).strip()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return raw
        return f"\\boxed{{{answer}}}"

    def judge(
        self,
        *,
        evaluator: str,
        question: V2Question,
        response: str,
    ) -> bool:
        criterion = (
            "The answer must correctly identify the flawed premise and must not "
            "follow that premise."
            if evaluator == "llm_abstention_checker"
            else (
                "The answer must include at least one correct environment gotcha "
                "from the reference and must not contradict it."
            )
        )
        prompt = (
            f"Criterion: {criterion}\n"
            f"Question: {question.question}\n"
            f"Reference: {question.answer}\n"
            f"Candidate: {response}\n"
        )
        value = self._generate(
            prompt,
            max_tokens=16,
            system=(
                "You are a strict binary evaluator. Set correct to true only "
                "when the candidate satisfies the criterion and reference."
            ),
            output_schema=JUDGMENT_SCHEMA,
        )
        try:
            return json.loads(value).get("correct") is True
        except (TypeError, ValueError, json.JSONDecodeError):
            return value.strip().startswith("1")


def _normalize_phrase(text: str) -> str:
    text = text.lower().replace("-", " ").replace("_", " ")
    text = re.sub(r"[,;]", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _bounded_evidence(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    separator = "\n...[middle truncated for reader context budget]...\n"
    remaining = max_chars - len(separator)
    head = remaining // 2
    tail = remaining - head
    return value[:head] + separator + value[-tail:]


def _eval_options(spec: str) -> tuple[str, dict[str, str]]:
    parts = [part.strip() for part in spec.split("|")]
    options: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            options[key.strip()] = value.strip()
    return parts[0], options


def score_response(
    question: V2Question,
    response: str,
    *,
    reader: Reader,
) -> bool:
    evaluator, options = _eval_options(question.eval_function)
    if evaluator in LLM_EVALUATORS:
        return reader.judge(
            evaluator=evaluator,
            question=question,
            response=response,
        )
    boxed = BOXED_RE.search(response)
    prediction = boxed.group(1).strip() if boxed else response.strip()
    if evaluator == "mc_choice_match":
        return prediction.strip(" .").upper() == question.answer.strip().upper()
    if evaluator == "mc_choice_set_match":
        predicted = set(re.findall(r"[A-Z]", prediction.upper()))
        expected = set(re.findall(r"[A-Z]", question.answer.upper()))
        return bool(expected) and predicted == expected
    separators = options.get("separators", ",;")
    answer_parts = [
        _normalize_phrase(part)
        for part in re.split(
            "|".join(re.escape(value) for value in separators),
            question.answer,
        )
        if _normalize_phrase(part)
    ]
    normalized = _normalize_phrase(prediction)
    if evaluator == "norm_phrase_set_match":
        return bool(answer_parts) and all(
            re.search(rf"\b{re.escape(part)}\b", normalized)
            for part in answer_parts
        )
    if evaluator == "norm_phrase_set_match_ordered":
        offset = 0
        for part in answer_parts:
            match = re.search(rf"\b{re.escape(part)}\b", normalized[offset:])
            if match is None:
                return False
            offset += match.end()
        return bool(answer_parts)
    raise ValueError(f"unsupported evaluator: {evaluator}")


def _query_memory(
    memory: WaveMind,
    dataset: V2Dataset,
    *,
    top_k: int,
    use_memory_os: bool,
    semantic_reranker: TextVectorEncoder | None = None,
    semantic_rerank_k: int = 20,
    semantic_rerank_weight: float = 0.70,
    tags: tuple[str, ...] | None = None,
    dereference_trajectory_evidence: bool = False,
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    if semantic_rerank_k < top_k:
        raise ValueError("semantic_rerank_k must be at least top_k")
    if not 0.0 <= semantic_rerank_weight <= 1.0:
        raise ValueError("semantic_rerank_weight must be between 0 and 1")
    cache = HotMemoryCache(
        capacity=max(1_024, len(dataset.questions) * 2),
        ttl_seconds=600.0,
    )
    latencies: list[float] = []
    end_to_end: list[float] = []
    contexts: dict[str, list[str]] = {}
    worker_reports: list[dict[str, Any]] = []
    maintenance_latencies: list[float] = []
    maintenance_ms = 0.0
    seen: Counter[str] = Counter()
    totals = Counter(
        f"longmemeval-v2-small:{question.domain}"
        for question in dataset.questions
    )
    memory.audit_queries = bool(use_memory_os)
    query_top_k = semantic_rerank_k if semantic_reranker is not None else top_k
    candidate_top_k = max(query_top_k, min(50, query_top_k * 10))
    trajectory_view = (
        TrajectoryDeltaConsolidator(memory)
        if dereference_trajectory_evidence
        else None
    )
    for question in dataset.questions:
        namespace = f"longmemeval-v2-small:{question.domain}"
        retrieval_query = _retrieval_query(question.question)
        metadata_filters = {
            "trajectory_id": dataset.haystacks[question.id],
        }
        started = time.perf_counter()
        if use_memory_os:
            results = query_with_cache(
                memory,
                cache,
                retrieval_query,
                namespace=namespace,
                top_k=query_top_k,
                tags=tags,
                metadata_filters=metadata_filters,
                candidate_top_k=candidate_top_k,
                diversity_metadata_key="trajectory_id",
                max_results_per_diversity_group=2,
            )
        else:
            results = memory.query(
                retrieval_query,
                namespace=namespace,
                top_k=query_top_k,
                tags=tags,
                metadata_filters=metadata_filters,
                candidate_top_k=candidate_top_k,
                diversity_metadata_key="trajectory_id",
                max_results_per_diversity_group=2,
            )
        snippets = [
            _query_snippet(
                (
                    trajectory_view.source_text(result)
                    if trajectory_view is not None
                    else result.text
                ),
                retrieval_query,
            )
            for result in results
        ]
        if semantic_reranker is not None and results:
            query_vector = np.asarray(
                encode_query_text(semantic_reranker, retrieval_query),
                dtype=np.float32,
            )
            document_vectors = np.asarray(
                encode_document_batch(semantic_reranker, snippets),
                dtype=np.float32,
            )
            semantic_scores = document_vectors @ query_vector
            semantic_order = np.argsort(-semantic_scores, kind="stable")
            semantic_ranks = {
                int(result_index): rank
                for rank, result_index in enumerate(semantic_order, start=1)
            }
            base_weight = 1.0 - semantic_rerank_weight
            ordered = sorted(
                range(len(results)),
                key=lambda index: (
                    -(
                        base_weight / (60.0 + index + 1)
                        + semantic_rerank_weight
                        / (60.0 + semantic_ranks[index])
                    ),
                    index,
                ),
            )[:top_k]
            snippets = [snippets[index] for index in ordered]
        else:
            snippets = snippets[:top_k]
        retrieval_ms = (time.perf_counter() - started) * 1_000.0
        latencies.append(retrieval_ms)
        contexts[question.id] = snippets
        current_maintenance = 0.0
        if use_memory_os:
            seen[namespace] += 1
            if seen[namespace] % 32 == 0 or seen[namespace] == totals[namespace]:
                maintenance_started = time.perf_counter()
                report = MemoryOSWorker(memory, cache).run_once(
                    namespace=namespace,
                    min_frequency=1,
                    max_hot_queries=8,
                    top_k=top_k,
                    consolidate_steps=0,
                    consolidate_concepts=False,
                    predict_priorities=False,
                    adaptive_forgetting=False,
                    predictive_prefetch=True,
                    architecture_advice=False,
                )
                current_maintenance = (
                    time.perf_counter() - maintenance_started
                ) * 1_000.0
                maintenance_latencies.append(current_maintenance)
                worker_reports.append(report.as_dict())
                maintenance_ms += current_maintenance
        # Maintenance runs between requests in this sequential harness and is
        # deployed on background workers in production. Keep its cost visible,
        # but do not attribute a worker cycle to the preceding request latency.
        end_to_end.append(retrieval_ms)
    stats = cache.stats()
    return contexts, {
        "execution_mode": (
            "memory_os_direct_feedback_free_trajectory_delta"
            if use_memory_os
            else "wavemind_core"
        ),
        "retrieval_view": (
            "trajectory_delta" if tags else "raw_trajectory_state"
        ),
        "retrieval_tags": list(tags or ()),
        "reader_evidence_view": (
            "dereferenced_source_state"
            if dereference_trajectory_evidence
            else "retrieved_record"
        ),
        "worker_runs": len(worker_reports),
        "worker_errors": sum(
            int(dict(row.get("prewarm") or {}).get("errors") or 0)
            + int(dict(row.get("predictive_prefetch") or {}).get("errors") or 0)
            for row in worker_reports
        ),
        "maintenance_interval_queries": 32 if use_memory_os else 0,
        "candidate_top_k": candidate_top_k,
        "semantic_reranker_enabled": semantic_reranker is not None,
        "semantic_rerank_k": (
            semantic_rerank_k if semantic_reranker is not None else 0
        ),
        "semantic_rerank_weight": (
            semantic_rerank_weight if semantic_reranker is not None else 0.0
        ),
        "diversity_metadata_key": "trajectory_id",
        "max_results_per_diversity_group": 2,
        "memory_os_policy_mode": (
            "feedback_free_safe" if use_memory_os else "disabled"
        ),
        "query_count": len(latencies),
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "p99_latency_ms": _percentile(latencies, 0.99),
        "end_to_end_p95_ms": _percentile(end_to_end, 0.95),
        "request_path_excludes_background_maintenance": True,
        "maintenance_p95_ms": _percentile(maintenance_latencies, 0.95),
        "maintenance_total_ms": maintenance_ms,
        "maintenance_amortized_ms_per_query": (
            maintenance_ms / len(latencies) if latencies else 0.0
        ),
        "cache_hits": stats.hits,
        "cache_misses": stats.misses,
        "context_tokens": sum(
            _token_estimate(value)
            for values in contexts.values()
            for value in values
        ),
    }


def _retrieval_answer_recoverability(
    dataset: V2Dataset,
    contexts: dict[str, list[str]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for question in dataset.questions:
        evaluator, options = _eval_options(question.eval_function)
        if evaluator not in {
            "norm_phrase_set_match",
            "norm_phrase_set_match_ordered",
        }:
            continue
        separators = options.get("separators", ",;")
        answer_parts = [
            _normalize_phrase(part)
            for part in re.split(
                "|".join(re.escape(value) for value in separators),
                question.answer,
            )
            if _normalize_phrase(part)
        ]
        normalized_context = _normalize_phrase(
            "\n".join(contexts.get(question.id, ()))
        )
        offset = 0
        recoverable = bool(answer_parts)
        for part in answer_parts:
            match = re.search(
                rf"\b{re.escape(part)}\b",
                normalized_context[offset:],
            )
            if match is None:
                recoverable = False
                break
            if evaluator == "norm_phrase_set_match_ordered":
                offset += match.end()
        rows.append(
            {
                "question_id": question.id,
                "category": question.question_type,
                "recoverable": recoverable,
            }
        )
    category_rates = {
        category: statistics.mean(
            1.0 if row["recoverable"] else 0.0
            for row in rows
            if row["category"] == category
        )
        for category in sorted({row["category"] for row in rows})
    }
    return {
        "expected_answer_recoverable_rate": (
            statistics.mean(
                1.0 if row["recoverable"] else 0.0
                for row in rows
            )
            if rows
            else None
        ),
        "eligible_queries": len(rows),
        "category_rates": category_rates,
        "claim_boundary": (
            "Diagnostic label-presence check for deterministic phrase questions. "
            "It is not the official LongMemEval-V2 answer-quality score and is "
            "never used for admission."
        ),
    }


def _evaluate_contexts(
    dataset: V2Dataset,
    contexts: dict[str, list[str]],
    *,
    reader: Reader | None,
    reuse_rows: dict[str, list[dict[str, Any]]] | None = None,
    reuse_source: str = "matching checkpoint",
    on_row: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if reader is None:
        return (
            {
                "evaluation_mode": "retrieval_only",
                "task_success_rate": None,
                "scored_queries": 0,
                "image_questions_supported": False,
            },
            [],
        )
    per_query: list[dict[str, Any]] = []
    answer_latencies: list[float] = []
    reused_answers = 0
    for question in dataset.questions:
        context_sha = hashlib.sha256(
            json.dumps(
                contexts[question.id],
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        reusable = next(
            (
                row
                for row in (reuse_rows or {}).get(question.id, [])
                if row.get("context_sha256") == context_sha
                and not row.get("error")
            ),
            None,
        )
        if reusable:
            row = {
                **{
                    key: value
                    for key, value in reusable.items()
                    if key not in {"engine", "response_reused_from"}
                },
                "response_reused_from": reuse_source,
            }
            per_query.append(row)
            if on_row is not None:
                on_row(row)
            answer_latencies.append(0.0)
            reused_answers += 1
            continue
        started = time.perf_counter()
        try:
            response = reader.answer(
                question=question,
                context=contexts[question.id],
            )
            passed = score_response(question, response, reader=reader)
            error = ""
        except Exception as exc:
            response = ""
            passed = False
            error = f"{type(exc).__name__}: {exc}"
        answer_latencies.append((time.perf_counter() - started) * 1_000.0)
        row = {
            "question_id": question.id,
            "domain": question.domain,
            "category": question.question_type,
            "has_image": question.image is not None,
            "passed": passed,
            "response": response,
            "error": error,
            "context_sha256": context_sha,
        }
        per_query.append(row)
        if on_row is not None:
            on_row(row)
    scored = len(per_query)
    category_success = {
        category: statistics.mean(
            1.0 if row["passed"] else 0.0
            for row in per_query
            if row["category"] == category
        )
        for category in sorted({row["category"] for row in per_query})
    }
    return (
        {
            "evaluation_mode": "official_answer_local_reader",
            "reader_model": reader.model,
            "reader_vision_model": getattr(reader, "vision_model", None),
            "task_success_rate": (
                statistics.mean(1.0 if row["passed"] else 0.0 for row in per_query)
                if per_query
                else 0.0
            ),
            "category_success": category_success,
            "scored_queries": scored,
            "answer_p50_latency_ms": _percentile(answer_latencies, 0.50),
            "answer_p95_latency_ms": _percentile(answer_latencies, 0.95),
            "answer_p99_latency_ms": _percentile(answer_latencies, 0.99),
            "image_questions_supported": reader.supports_images,
            "errors": sum(1 for row in per_query if row["error"]),
            "generated_answers": scored - reused_answers,
            "reused_answers": reused_answers,
        },
        per_query,
    )


class PersistentCachedTextEncoder:
    """Resume-safe SQLite cache for deterministic benchmark embeddings."""

    def __init__(
        self,
        base_encoder: TextVectorEncoder,
        path: str | Path,
    ) -> None:
        self.base_encoder = base_encoder
        self.vector_dim = int(base_encoder.vector_dim)
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_key = getattr(
            base_encoder,
            "cache_key",
            f"{type(base_encoder).__name__}|{self.vector_dim}",
        )
        self._connection = sqlite3.connect(self.path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                cache_key TEXT NOT NULL,
                role TEXT NOT NULL,
                text_sha256 TEXT NOT NULL,
                vector BLOB NOT NULL,
                vector_dim INTEGER NOT NULL,
                PRIMARY KEY (cache_key, role, text_sha256)
            )
            """
        )
        self._connection.commit()
        self.hits = 0
        self.misses = 0
        self.writes = 0

    def close(self) -> None:
        self._connection.close()

    def encode_vector(self, text: str) -> np.ndarray:
        return self.encode_query_vector(text)

    def encode_vectors(self, texts) -> np.ndarray:
        return self.encode_document_vectors(texts)

    def encode_query_vector(self, text: str) -> np.ndarray:
        cached = self._get("query", text)
        if cached is not None:
            return cached
        vector = np.asarray(
            encode_query_text(self.base_encoder, text),
            dtype=np.float32,
        )
        self._put("query", text, vector)
        return vector

    def encode_document_vector(self, text: str) -> np.ndarray:
        cached = self._get("document", text)
        if cached is not None:
            return cached
        vector = np.asarray(
            encode_document_text(self.base_encoder, text),
            dtype=np.float32,
        )
        self._put("document", text, vector)
        return vector

    def encode_document_vectors(self, texts) -> np.ndarray:
        values = list(texts)
        if not values:
            return np.zeros((0, self.vector_dim), dtype=np.float32)
        vectors: list[np.ndarray | None] = [None] * len(values)
        missing: list[int] = []
        for index, text in enumerate(values):
            cached = self._get("document", text)
            if cached is None:
                missing.append(index)
            else:
                vectors[index] = cached
        batch_size = max(
            1,
            int(getattr(self.base_encoder, "batch_size", 32)),
        )
        for offset in range(0, len(missing), batch_size):
            indexes = missing[offset : offset + batch_size]
            batch_texts = [values[index] for index in indexes]
            batch_vectors = np.asarray(
                encode_document_batch(self.base_encoder, batch_texts),
                dtype=np.float32,
            )
            expected_shape = (len(indexes), self.vector_dim)
            if batch_vectors.shape != expected_shape:
                raise RuntimeError(
                    "cached encoder batch shape "
                    f"{batch_vectors.shape}, expected {expected_shape}"
                )
            with self._connection:
                for index, text, vector in zip(
                    indexes,
                    batch_texts,
                    batch_vectors,
                    strict=True,
                ):
                    normalized = np.asarray(vector, dtype=np.float32)
                    vectors[index] = normalized
                    self._put("document", text, normalized, commit=False)
        if any(vector is None for vector in vectors):
            raise RuntimeError("persistent embedding cache left an incomplete batch")
        return np.stack(
            [
                np.asarray(vector, dtype=np.float32)
                for vector in vectors
            ]
        ).astype(np.float32)

    def stats(self) -> dict[str, Any]:
        entries = int(
            self._connection.execute(
                "SELECT COUNT(*) FROM embeddings WHERE cache_key = ?",
                (self.cache_key,),
            ).fetchone()[0]
        )
        return {
            "enabled": True,
            "schema": "wavemind.benchmark_embedding_cache.v1",
            "path": str(self.path),
            "entries": entries,
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
        }

    def _get(self, role: str, text: str) -> np.ndarray | None:
        row = self._connection.execute(
            """
            SELECT vector, vector_dim
            FROM embeddings
            WHERE cache_key = ? AND role = ? AND text_sha256 = ?
            """,
            (self.cache_key, role, self._text_sha(text)),
        ).fetchone()
        if row is None:
            self.misses += 1
            return None
        vector = np.frombuffer(row[0], dtype=np.float32).copy()
        if int(row[1]) != self.vector_dim or vector.shape != (self.vector_dim,):
            raise RuntimeError("persistent embedding cache contains an invalid vector")
        self.hits += 1
        return vector

    def _put(
        self,
        role: str,
        text: str,
        vector: np.ndarray,
        *,
        commit: bool = True,
    ) -> None:
        normalized = np.asarray(vector, dtype=np.float32)
        if normalized.shape != (self.vector_dim,):
            raise RuntimeError(
                f"embedding shape {normalized.shape}, expected {(self.vector_dim,)}"
            )
        self._connection.execute(
            """
            INSERT OR REPLACE INTO embeddings (
                cache_key, role, text_sha256, vector, vector_dim
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                self.cache_key,
                role,
                self._text_sha(text),
                normalized.tobytes(),
                self.vector_dim,
            ),
        )
        self.writes += 1
        if commit:
            self._connection.commit()

    @staticmethod
    def _text_sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _encoder_metadata(encoder: TextVectorEncoder) -> dict[str, Any]:
    if isinstance(encoder, PersistentCachedTextEncoder):
        encoder = encoder.base_encoder
    metadata: dict[str, Any] = {
        "kind": "custom",
        "class": type(encoder).__name__,
        "vector_dim": int(encoder.vector_dim),
    }
    if isinstance(encoder, HashingTextEncoder):
        metadata.update(
            {
                "kind": "hash-token",
                "char_ngram_weight": encoder.char_ngram_weight,
            }
        )
    elif isinstance(encoder, OllamaTextEncoder):
        metadata.update(
            {
                "kind": "ollama",
                "model": encoder.model_name,
                "base_url": encoder.base_url,
                "batch_size": encoder.batch_size,
                "query_instruction": encoder.query_instruction,
                "normalized": True,
                "query_document_asymmetric": True,
            }
        )
    return metadata


def _resume_reranker_config(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("semantic_reranker")
    if raw is None:
        return {
            "enabled": False,
            "embedding": None,
            "candidate_window": 0,
            "rrf_weight": 0.0,
        }
    if not isinstance(raw, dict):
        raise ValueError("resume semantic reranker configuration must be an object")
    return {
        "enabled": bool(raw.get("enabled")),
        "embedding": raw.get("embedding"),
        "candidate_window": int(raw.get("candidate_window") or 0),
        "rrf_weight": float(raw.get("rrf_weight") or 0.0),
    }


def run_benchmark(
    data_root: str | Path,
    *,
    reader: Reader | None = None,
    encoder: TextVectorEncoder | None = None,
    semantic_reranker: TextVectorEncoder | None = None,
    semantic_rerank_k: int = 20,
    semantic_rerank_weight: float = 0.70,
    top_k: int = 5,
    limit_questions: int | None = None,
    question_sample_size: int | None = None,
    question_sample_seed: int = 20260728,
    work_dir: str | Path | None = None,
    resume_rows: list[dict[str, Any]] | None = None,
    resume_metadata: dict[str, Any] | None = None,
    on_row: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dataset = load_longmemeval_v2_small(
        data_root,
        limit_questions=limit_questions,
        question_sample_size=question_sample_size,
        question_sample_seed=question_sample_seed,
    )
    if encoder is None:
        encoder = HashingTextEncoder(
            vector_dim=384,
            char_ngram_weight=0.0,
        )
    temp_parent = None
    if work_dir is not None:
        temp_parent_path = Path(work_dir)
        temp_parent_path.mkdir(parents=True, exist_ok=True)
        temp_parent = str(temp_parent_path)
    with tempfile.TemporaryDirectory(dir=temp_parent) as temp_dir:
        temp_path = Path(temp_dir)
        base_path = temp_path / "longmemeval-v2-base.sqlite3"

        def open_memory(path: Path) -> WaveMind:
            return WaveMind(
                db_path=path,
                encoder=encoder,
                width=32,
                height=32,
                layers=2,
                index_kind="numpy",
                score_threshold=0.0,
                evolve_on_feed=0,
                vector_weight=0.60,
                field_weight=0.06,
                priority_weight=0.16,
                lexical_weight=1.0,
                short_query_lexical_weight=1.5,
                max_lexical_token_frequency=512,
                lexical_idf_normalization=False,
                rerank_k=max(top_k, 30),
                persist_access_on_query=False,
                query_feedback_strength=0.0,
                audit_queries=False,
            )

        seed_memory = open_memory(base_path)
        try:
            seed_memory.remember_batch(
                {
                    "text": item.text,
                    "namespace": item.namespace,
                    "tags": ("longmemeval-v2", "trajectory-state"),
                    "metadata": {"evidence_id": item.id, **item.metadata},
                }
                for item in dataset.memories
            )
        finally:
            seed_memory.close()

        core_path = temp_path / "longmemeval-v2-core.sqlite3"
        os_path = temp_path / "longmemeval-v2-memory-os.sqlite3"
        shutil.copy2(base_path, core_path)
        shutil.copy2(base_path, os_path)

        core_memory = open_memory(core_path)
        try:
            core_contexts, core_metrics = _query_memory(
                core_memory,
                dataset,
                top_k=top_k,
                use_memory_os=False,
                semantic_reranker=semantic_reranker,
                semantic_rerank_k=semantic_rerank_k,
                semantic_rerank_weight=semantic_rerank_weight,
            )
        finally:
            core_memory.close()

        os_memory = open_memory(os_path)
        try:
            consolidation_started = time.perf_counter()
            consolidation = TrajectoryDeltaConsolidator(
                os_memory
            ).run_once(
                input_tag="trajectory-state",
                output_tag="trajectory-delta",
                max_summary_chars=2_800,
            )
            consolidation_ms = (
                time.perf_counter() - consolidation_started
            ) * 1_000.0
            if not consolidation.ok:
                raise RuntimeError(
                    "trajectory consolidation failed: "
                    + "; ".join(consolidation.errors)
                )
            os_contexts, os_metrics = _query_memory(
                os_memory,
                dataset,
                top_k=top_k,
                use_memory_os=True,
                semantic_reranker=semantic_reranker,
                semantic_rerank_k=semantic_rerank_k,
                semantic_rerank_weight=semantic_rerank_weight,
                tags=("trajectory-delta",),
                dereference_trajectory_evidence=True,
            )
            os_metrics["trajectory_consolidation"] = (
                consolidation.as_dict()
            )
            os_metrics["trajectory_consolidation_ms"] = consolidation_ms
        finally:
            os_memory.close()
    core_metrics["retrieval_answer_recoverability"] = (
        _retrieval_answer_recoverability(dataset, core_contexts)
    )
    os_metrics["retrieval_answer_recoverability"] = (
        _retrieval_answer_recoverability(dataset, os_contexts)
    )
    prior_core: dict[str, list[dict[str, Any]]] = {}
    prior_os: dict[str, list[dict[str, Any]]] = {}
    for row in resume_rows or []:
        target = (
            prior_core
            if row.get("engine") == "WaveMind"
            else prior_os
            if row.get("engine") == "WaveMind + Memory OS"
            else None
        )
        if target is not None and row.get("question_id"):
            target.setdefault(str(row["question_id"]), []).append(row)
    core_quality, core_rows = _evaluate_contexts(
        dataset,
        core_contexts,
        reader=reader,
        reuse_rows=prior_core,
        reuse_source="WaveMind checkpoint",
        on_row=(
            (lambda row: on_row({"engine": "WaveMind", **row}))
            if on_row is not None
            else None
        ),
    )
    os_reuse: dict[str, list[dict[str, Any]]] = {}
    for row in core_rows:
        os_reuse.setdefault(str(row["question_id"]), []).append(row)
    for question_id, rows in prior_os.items():
        os_reuse.setdefault(question_id, []).extend(rows)
    os_quality, os_rows = _evaluate_contexts(
        dataset,
        os_contexts,
        reader=reader,
        reuse_rows=os_reuse,
        reuse_source="matching Core or Memory OS checkpoint",
        on_row=(
            (lambda row: on_row({"engine": "WaveMind + Memory OS", **row}))
            if on_row is not None
            else None
        ),
    )
    results = [
        {"engine": "WaveMind", **core_metrics, **core_quality},
        {"engine": "WaveMind + Memory OS", **os_metrics, **os_quality},
    ]
    per_query = [
        {"engine": "WaveMind", **row} for row in core_rows
    ] + [
        {"engine": "WaveMind + Memory OS", **row} for row in os_rows
    ]
    image_questions = sum(
        1 for question in dataset.questions if question.image is not None
    )
    return (
        {
            "schema": "wavemind.longmemeval_v2_small.v1",
            "generated_at": _utc_now(),
            "source_sha": _source_ref(),
            "status": "pass",
            "scenario": {
                "name": "longmemeval_v2_small",
                "dataset_repo": DATASET_REPO,
                "dataset_revision": DATASET_REVISION,
                "official_repo": OFFICIAL_REPO,
                "official_repo_revision": OFFICIAL_REPO_REVISION,
                "tier": "small",
                "queries": len(dataset.questions),
                "question_selection": (
                    "stratified"
                    if question_sample_size is not None
                    else "prefix"
                    if limit_questions is not None
                    else "full"
                ),
                "question_sample_size": question_sample_size,
                "question_sample_seed": (
                    question_sample_seed
                    if question_sample_size is not None
                    else None
                ),
                "memories": len(dataset.memories),
                "trajectories": len(
                    {
                        item.metadata["trajectory_id"]
                        for item in dataset.memories
                    }
                ),
                "top_k": top_k,
                "image_questions": image_questions,
                "image_questions_included": image_questions,
                "question_images_supported": bool(
                    reader is not None and reader.supports_images
                ),
                "official_question_haystacks": True,
                "isolated_ab_stores": True,
                "full_small_run": (
                    limit_questions is None
                    and question_sample_size is None
                    and len(dataset.questions) == 451
                ),
            },
            "dataset_checksums": dataset.source_files,
            "embedding": _encoder_metadata(encoder),
            "embedding_cache": (
                encoder.stats()
                if isinstance(encoder, PersistentCachedTextEncoder)
                else {"enabled": False}
            ),
            "semantic_reranker": {
                "enabled": semantic_reranker is not None,
                "embedding": (
                    _encoder_metadata(semantic_reranker)
                    if semantic_reranker is not None
                    else None
                ),
                "candidate_window": (
                    semantic_rerank_k
                    if semantic_reranker is not None
                    else 0
                ),
                "rrf_weight": (
                    semantic_rerank_weight
                    if semantic_reranker is not None
                    else 0.0
                ),
                "cache": (
                    semantic_reranker.stats()
                    if isinstance(
                        semantic_reranker,
                        PersistentCachedTextEncoder,
                    )
                    else {"enabled": False}
                ),
            },
            "retrieval": {
                "vector_weight": 0.60,
                "lexical_weight": 1.0,
                "priority_weight": 0.16,
                "field_weight": 0.06,
                "max_lexical_token_frequency": 512,
                "lexical_idf_normalization": False,
                "candidate_top_k": max(top_k, min(50, top_k * 10)),
                "diversity_metadata_key": "trajectory_id",
                "max_results_per_diversity_group": 2,
                "query_instruction_normalization": True,
                "snippet_max_chars": 2_800,
                "snippet_neighbor_lines": 2,
                "memory_os_view": {
                    "kind": "extractive_trajectory_delta",
                    "input_tag": "trajectory-state",
                    "output_tag": "trajectory-delta",
                    "max_summary_chars": 2_800,
                    "source_states_preserved": True,
                    "reader_evidence": "dereferenced_source_state",
                    "answer_labels_used": False,
                },
            },
            "field": {"width": 32, "height": 32, "layers": 2},
            "reader": {
                "kind": "ollama" if reader is not None else "none",
                "model": reader.model if reader is not None else None,
                "vision_model": (
                    getattr(reader, "vision_model", None)
                    if reader is not None
                    else None
                ),
                "supports_images": (
                    reader.supports_images if reader is not None else False
                ),
                "text_context_window": (
                    getattr(reader, "text_context_window", None)
                    if reader is not None
                    else None
                ),
                "image_context_window": (
                    getattr(reader, "image_context_window", None)
                    if reader is not None
                    else None
                ),
                "image_context_items": (
                    getattr(reader, "image_context_items", None)
                    if reader is not None
                    else None
                ),
                "image_context_chars": (
                    getattr(reader, "image_context_chars", None)
                    if reader is not None
                    else None
                ),
                "thinking_enabled": (
                    getattr(reader, "enable_thinking", None)
                    if reader is not None
                    else None
                ),
                "structured_outputs": bool(
                    getattr(reader, "structured_outputs", False)
                ),
                "cost_per_query_usd": 0.0,
            },
            "resume": resume_metadata or {
                "used": False,
                "source_sha": None,
                "rows": 0,
            },
            "results": results,
            "per_query_count": len(per_query),
            "claim_boundary": (
                "Local-reader profile on the pinned official Small dataset. "
                "This is not an official leaderboard submission."
            ),
        },
        per_query,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit-questions", type=int)
    parser.add_argument("--question-sample-size", type=int)
    parser.add_argument("--question-sample-seed", type=int, default=20260728)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--ollama-model")
    parser.add_argument("--ollama-vision-model")
    parser.add_argument(
        "--ollama-base-url",
        default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
    )
    parser.add_argument("--reader-supports-images", action="store_true")
    parser.add_argument("--ollama-text-context-window", type=int, default=8192)
    parser.add_argument("--ollama-image-context-window", type=int, default=4096)
    parser.add_argument("--ollama-image-context-items", type=int, default=1)
    parser.add_argument("--ollama-image-context-chars", type=int, default=4000)
    parser.add_argument("--ollama-enable-thinking", action="store_true")
    parser.add_argument("--ollama-embedding-model")
    parser.add_argument(
        "--ollama-embedding-base-url",
        default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
    )
    parser.add_argument("--ollama-embedding-vector-dim", type=int, default=1024)
    parser.add_argument("--ollama-embedding-batch-size", type=int, default=32)
    parser.add_argument(
        "--ollama-embedding-timeout-seconds",
        type=float,
        default=600.0,
    )
    parser.add_argument(
        "--embedding-cache",
        type=Path,
        help="Persistent SQLite embedding cache for restart-safe benchmark runs.",
    )
    parser.add_argument("--semantic-rerank-model")
    parser.add_argument(
        "--semantic-rerank-base-url",
        default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
    )
    parser.add_argument("--semantic-rerank-vector-dim", type=int, default=1024)
    parser.add_argument("--semantic-rerank-batch-size", type=int, default=8)
    parser.add_argument(
        "--semantic-rerank-timeout-seconds",
        type=float,
        default=600.0,
    )
    parser.add_argument("--semantic-rerank-cache", type=Path)
    parser.add_argument("--semantic-rerank-k", type=int, default=20)
    parser.add_argument("--semantic-rerank-weight", type=float, default=0.70)
    parser.add_argument("--resume-result", type=Path)
    parser.add_argument("--resume-per-query", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/longmemeval_v2_small_memory_os_results.json"),
    )
    parser.add_argument(
        "--per-query-output",
        type=Path,
        default=Path("benchmarks/longmemeval_v2_small_per_query.jsonl"),
    )
    args = parser.parse_args()
    if args.limit_questions is not None and args.question_sample_size is not None:
        parser.error(
            "--limit-questions and --question-sample-size are mutually exclusive"
        )
    if bool(args.resume_result) != bool(args.resume_per_query):
        parser.error("--resume-result and --resume-per-query must be supplied together")
    encoder: TextVectorEncoder | None = None
    if args.ollama_embedding_model:
        encoder = OllamaTextEncoder(
            model_name=args.ollama_embedding_model,
            base_url=args.ollama_embedding_base_url,
            vector_dim=args.ollama_embedding_vector_dim,
            batch_size=args.ollama_embedding_batch_size,
            timeout_seconds=args.ollama_embedding_timeout_seconds,
        )
    if args.embedding_cache:
        if encoder is None:
            parser.error("--embedding-cache requires an explicit embedding model")
        encoder = PersistentCachedTextEncoder(encoder, args.embedding_cache)
    semantic_reranker: TextVectorEncoder | None = None
    if args.semantic_rerank_model:
        semantic_reranker = OllamaTextEncoder(
            model_name=args.semantic_rerank_model,
            base_url=args.semantic_rerank_base_url,
            vector_dim=args.semantic_rerank_vector_dim,
            batch_size=args.semantic_rerank_batch_size,
            timeout_seconds=args.semantic_rerank_timeout_seconds,
        )
    if args.semantic_rerank_cache:
        if semantic_reranker is None:
            parser.error(
                "--semantic-rerank-cache requires --semantic-rerank-model"
            )
        semantic_reranker = PersistentCachedTextEncoder(
            semantic_reranker,
            args.semantic_rerank_cache,
        )
    resume_rows: list[dict[str, Any]] | None = None
    resume_metadata: dict[str, Any] | None = None
    if args.resume_result:
        resume_payload = json.loads(
            args.resume_result.read_text(encoding="utf-8")
        )
        resume_rows = _read_jsonl(args.resume_per_query)
        expected_reader = resume_payload.get("reader") or {}
        expected_embedding = resume_payload.get("embedding") or {}
        expected_scenario = resume_payload.get("scenario") or {}
        if resume_payload.get("schema") != "wavemind.longmemeval_v2_small.v1":
            parser.error("resume result has an unsupported schema")
        if expected_scenario.get("top_k") != args.top_k:
            parser.error("resume result top_k does not match this run")
        if expected_reader.get("model") != args.ollama_model:
            parser.error("resume reader model does not match this run")
        if expected_reader.get("vision_model") != args.ollama_vision_model:
            parser.error("resume vision model does not match this run")
        if bool(expected_reader.get("thinking_enabled")) != bool(
            args.ollama_enable_thinking
        ):
            parser.error("resume reader thinking mode does not match this run")
        current_embedding = _encoder_metadata(
            encoder
            or HashingTextEncoder(vector_dim=384, char_ngram_weight=0.0)
        )
        if expected_embedding != current_embedding:
            parser.error("resume embedding configuration does not match this run")
        current_reranker = {
            "enabled": semantic_reranker is not None,
            "embedding": (
                _encoder_metadata(semantic_reranker)
                if semantic_reranker is not None
                else None
            ),
            "candidate_window": (
                args.semantic_rerank_k
                if semantic_reranker is not None
                else 0
            ),
            "rrf_weight": (
                args.semantic_rerank_weight
                if semantic_reranker is not None
                else 0.0
            ),
        }
        try:
            expected_reranker_config = _resume_reranker_config(
                resume_payload
            )
        except (TypeError, ValueError) as exc:
            parser.error(str(exc))
        if expected_reranker_config != current_reranker:
            parser.error("resume semantic reranker does not match this run")
        resume_metadata = {
            "used": True,
            "source_sha": resume_payload.get("source_sha"),
            "rows": len(resume_rows),
            "result_sha256": _sha256(args.resume_result),
            "per_query_sha256": _sha256(args.resume_per_query),
        }
    reader = (
        OllamaReader(
            model=args.ollama_model,
            vision_model=args.ollama_vision_model,
            base_url=args.ollama_base_url,
            supports_images=args.reader_supports_images,
            text_context_window=args.ollama_text_context_window,
            image_context_window=args.ollama_image_context_window,
            image_context_items=args.ollama_image_context_items,
            image_context_chars=args.ollama_image_context_chars,
            enable_thinking=args.ollama_enable_thinking,
        )
        if args.ollama_model
        else None
    )
    args.per_query_output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_rows = list(resume_rows or [])
    checkpoint_keys = {
        (
            str(row.get("engine") or ""),
            str(row.get("question_id") or ""),
            str(row.get("context_sha256") or ""),
        )
        for row in checkpoint_rows
    }
    args.per_query_output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in checkpoint_rows
        ),
        encoding="utf-8",
    )

    def checkpoint(row: dict[str, Any]) -> None:
        key = (
            str(row.get("engine") or ""),
            str(row.get("question_id") or ""),
            str(row.get("context_sha256") or ""),
        )
        if key in checkpoint_keys:
            return
        with args.per_query_output.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
            handle.flush()
        checkpoint_keys.add(key)

    try:
        payload, rows = run_benchmark(
            args.data_root,
            reader=reader,
            encoder=encoder,
            semantic_reranker=semantic_reranker,
            semantic_rerank_k=args.semantic_rerank_k,
            semantic_rerank_weight=args.semantic_rerank_weight,
            top_k=args.top_k,
            limit_questions=args.limit_questions,
            question_sample_size=args.question_sample_size,
            question_sample_seed=args.question_sample_seed,
            work_dir=args.work_dir,
            resume_rows=resume_rows,
            resume_metadata=resume_metadata,
            on_row=checkpoint,
        )
    finally:
        if isinstance(encoder, PersistentCachedTextEncoder):
            encoder.close()
        if isinstance(semantic_reranker, PersistentCachedTextEncoder):
            semantic_reranker.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.per_query_output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "queries": payload["scenario"]["queries"],
                "memories": payload["scenario"]["memories"],
                "results": payload["results"],
                "output": str(args.output),
                "per_query_output": str(args.per_query_output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
