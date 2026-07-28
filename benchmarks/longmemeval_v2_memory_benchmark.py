from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
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
from typing import Any, Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind
from wavemind.encoders import HashingTextEncoder
from wavemind.jobs import HotMemoryCache, MemoryOSWorker, query_with_cache


DATASET_REPO = "xiaowu0162/longmemeval-v2"
DATASET_REVISION = "f152293e235517d504809563c833d7190b8c713b"
OFFICIAL_REPO = "https://github.com/xiaowu0162/longmemeval-v2"
OFFICIAL_REPO_REVISION = "6f020ac2fc3275e46c706d3406e02c3ed79b7be2"
BOXED_RE = re.compile(r"\\boxed\{([^}]*)\}", re.IGNORECASE | re.DOTALL)
LLM_EVALUATORS = {"llm_abstention_checker", "llm_gotchas_checker"}


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


def load_longmemeval_v2_small(
    data_root: str | Path,
    *,
    limit_questions: int | None = None,
) -> V2Dataset:
    root = Path(data_root)
    questions_path = root / "questions.jsonl"
    trajectories_path = root / "trajectories.jsonl"
    haystack_path = root / "haystacks" / "lme_v2_small.json"
    for path in (questions_path, trajectories_path, haystack_path):
        if not path.exists():
            raise FileNotFoundError(path)

    raw_questions = _read_jsonl(questions_path)
    if limit_questions is not None:
        if limit_questions <= 0:
            raise ValueError("limit_questions must be positive")
        raw_questions = raw_questions[:limit_questions]
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
    for question in questions:
        ids = haystacks.get(question.id)
        if not isinstance(ids, list) or len(ids) != 100:
            raise ValueError(
                f"small haystack for {question.id} must contain 100 trajectories"
            )
        selected_ids.update(str(value) for value in ids)

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


def _query_snippet(text: str, query: str, *, max_chars: int = 4_000) -> str:
    if len(text) <= max_chars:
        return text
    query_terms = {
        token
        for token in re.findall(r"\w+", query.lower())
        if len(token) >= 3
    }
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    ranked = sorted(
        enumerate(lines),
        key=lambda item: (
            -sum(term in item[1].lower() for term in query_terms),
            item[0],
        ),
    )
    selected: list[tuple[int, str]] = []
    total = 0
    for index, line in ranked:
        if total + len(line) + 1 > max_chars:
            continue
        selected.append((index, line))
        total += len(line) + 1
        if total >= max_chars * 0.85:
            break
    return "\n".join(line for _, line in sorted(selected))


class OllamaReader:
    def __init__(
        self,
        *,
        model: str,
        vision_model: str | None = None,
        base_url: str = "http://127.0.0.1:11434",
        supports_images: bool = False,
        timeout_seconds: float = 180.0,
        image_context_window: int = 8192,
        seed: int = 20260728,
    ) -> None:
        self.model = model
        self.vision_model = vision_model
        self.base_url = base_url.rstrip("/")
        self.supports_images = bool(supports_images or vision_model)
        self.timeout_seconds = float(timeout_seconds)
        self.image_context_window = int(image_context_window)
        if self.image_context_window < 4096:
            raise ValueError("image_context_window must be at least 4096")
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
            "options": {
                "temperature": 0,
                "seed": self.seed,
                "num_predict": int(max_tokens),
            },
        }
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
        prompt = (
            "Answer only from the past agent trajectory evidence below. "
            "If the premise conflicts with the evidence, say exactly what is wrong. "
            "End with one concise final answer inside \\boxed{...}.\n\n"
            f"Question:\n{question.question}\n\n"
            "Memory evidence:\n"
            + "\n\n---\n\n".join(context)
        )
        return self._generate(prompt, image=question.image)

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
            "You are a strict binary evaluator. Return only 1 or 0.\n"
            f"Criterion: {criterion}\n"
            f"Question: {question.question}\n"
            f"Reference: {question.answer}\n"
            f"Candidate: {response}\n"
        )
        value = self._generate(prompt, max_tokens=8)
        return value.strip().startswith("1")


def _normalize_phrase(text: str) -> str:
    text = text.lower().replace("-", " ").replace("_", " ")
    text = re.sub(r"[,;]", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


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
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    cache = HotMemoryCache(
        capacity=max(1_024, len(dataset.questions) * 2),
        ttl_seconds=600.0,
    )
    latencies: list[float] = []
    end_to_end: list[float] = []
    contexts: dict[str, list[str]] = {}
    worker_reports: list[dict[str, Any]] = []
    maintenance_ms = 0.0
    seen: Counter[str] = Counter()
    totals = Counter(
        f"longmemeval-v2-small:{question.domain}"
        for question in dataset.questions
    )
    memory.audit_queries = bool(use_memory_os)
    for question in dataset.questions:
        namespace = f"longmemeval-v2-small:{question.domain}"
        started = time.perf_counter()
        if use_memory_os:
            results = query_with_cache(
                memory,
                cache,
                question.question,
                namespace=namespace,
                top_k=top_k,
            )
        else:
            results = memory.query(
                question.question,
                namespace=namespace,
                top_k=top_k,
            )
        retrieval_ms = (time.perf_counter() - started) * 1_000.0
        latencies.append(retrieval_ms)
        contexts[question.id] = [
            _query_snippet(result.text, question.question)
            for result in results
        ]
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
                worker_reports.append(report.as_dict())
                maintenance_ms += current_maintenance
        end_to_end.append(retrieval_ms + current_maintenance)
    stats = cache.stats()
    return contexts, {
        "execution_mode": (
            "memory_os_direct_feedback_free"
            if use_memory_os
            else "wavemind_core"
        ),
        "worker_runs": len(worker_reports),
        "worker_errors": sum(
            int(dict(row.get("prewarm") or {}).get("errors") or 0)
            + int(dict(row.get("predictive_prefetch") or {}).get("errors") or 0)
            for row in worker_reports
        ),
        "maintenance_interval_queries": 32 if use_memory_os else 0,
        "memory_os_policy_mode": (
            "feedback_free_safe" if use_memory_os else "disabled"
        ),
        "query_count": len(latencies),
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "p99_latency_ms": _percentile(latencies, 0.99),
        "end_to_end_p95_ms": _percentile(end_to_end, 0.95),
        "maintenance_total_ms": maintenance_ms,
        "cache_hits": stats.hits,
        "cache_misses": stats.misses,
        "context_tokens": sum(
            _token_estimate(value)
            for values in contexts.values()
            for value in values
        ),
    }


def _evaluate_contexts(
    dataset: V2Dataset,
    contexts: dict[str, list[str]],
    *,
    reader: Reader | None,
    reuse_rows: dict[str, list[dict[str, Any]]] | None = None,
    reuse_source: str = "matching checkpoint",
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
            per_query.append(
                {
                    **{
                        key: value
                        for key, value in reusable.items()
                        if key not in {"engine", "response_reused_from"}
                    },
                    "response_reused_from": reuse_source,
                }
            )
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
        per_query.append(
            {
                "question_id": question.id,
                "domain": question.domain,
                "category": question.question_type,
                "has_image": question.image is not None,
                "passed": passed,
                "response": response,
                "error": error,
                "context_sha256": context_sha,
            }
        )
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


def run_benchmark(
    data_root: str | Path,
    *,
    reader: Reader | None = None,
    top_k: int = 5,
    limit_questions: int | None = None,
    work_dir: str | Path | None = None,
    resume_rows: list[dict[str, Any]] | None = None,
    resume_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dataset = load_longmemeval_v2_small(
        data_root,
        limit_questions=limit_questions,
    )
    encoder = HashingTextEncoder(
        vector_dim=384,
        char_ngram_weight=0.0,
    )
    temp_parent = str(work_dir) if work_dir is not None else None
    with tempfile.TemporaryDirectory(dir=temp_parent) as temp_dir:
        memory = WaveMind(
            db_path=Path(temp_dir) / "longmemeval-v2-small.sqlite3",
            encoder=encoder,
            width=32,
            height=32,
            layers=2,
            index_kind="numpy",
            score_threshold=0.0,
            evolve_on_feed=0,
            vector_weight=0.78,
            field_weight=0.06,
            priority_weight=0.16,
            lexical_weight=0.35,
            short_query_lexical_weight=1.5,
            rerank_k=max(top_k, 30),
            persist_access_on_query=False,
            query_feedback_strength=0.0,
            audit_queries=False,
        )
        try:
            memory.remember_batch(
                {
                    "text": item.text,
                    "namespace": item.namespace,
                    "tags": ("longmemeval-v2", "trajectory-state"),
                    "metadata": {"evidence_id": item.id, **item.metadata},
                }
                for item in dataset.memories
            )
            core_contexts, core_metrics = _query_memory(
                memory,
                dataset,
                top_k=top_k,
                use_memory_os=False,
            )
            os_contexts, os_metrics = _query_memory(
                memory,
                dataset,
                top_k=top_k,
                use_memory_os=True,
            )
        finally:
            memory.close()
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
                "full_small_run": (
                    limit_questions is None and len(dataset.questions) == 451
                ),
            },
            "dataset_checksums": dataset.source_files,
            "embedding": {
                "kind": "hash-token",
                "class": type(encoder).__name__,
                "vector_dim": int(encoder.vector_dim),
                "char_ngram_weight": encoder.char_ngram_weight,
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
                "image_context_window": (
                    getattr(reader, "image_context_window", None)
                    if reader is not None
                    else None
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
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--ollama-model")
    parser.add_argument("--ollama-vision-model")
    parser.add_argument(
        "--ollama-base-url",
        default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
    )
    parser.add_argument("--reader-supports-images", action="store_true")
    parser.add_argument("--ollama-image-context-window", type=int, default=8192)
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
    if bool(args.resume_result) != bool(args.resume_per_query):
        parser.error("--resume-result and --resume-per-query must be supplied together")
    resume_rows: list[dict[str, Any]] | None = None
    resume_metadata: dict[str, Any] | None = None
    if args.resume_result:
        resume_payload = json.loads(
            args.resume_result.read_text(encoding="utf-8")
        )
        resume_rows = _read_jsonl(args.resume_per_query)
        expected_reader = resume_payload.get("reader") or {}
        expected_scenario = resume_payload.get("scenario") or {}
        if resume_payload.get("schema") != "wavemind.longmemeval_v2_small.v1":
            parser.error("resume result has an unsupported schema")
        if expected_scenario.get("top_k") != args.top_k:
            parser.error("resume result top_k does not match this run")
        if expected_reader.get("model") != args.ollama_model:
            parser.error("resume reader model does not match this run")
        if expected_reader.get("vision_model") != args.ollama_vision_model:
            parser.error("resume vision model does not match this run")
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
            image_context_window=args.ollama_image_context_window,
        )
        if args.ollama_model
        else None
    )
    payload, rows = run_benchmark(
        args.data_root,
        reader=reader,
        top_k=args.top_k,
        limit_questions=args.limit_questions,
        work_dir=args.work_dir,
        resume_rows=resume_rows,
        resume_metadata=resume_metadata,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.per_query_output.parent.mkdir(parents=True, exist_ok=True)
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
