from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import (
    attach_artifact_integrity,
    canonical_json_bytes,
    file_sha256,
    sha256_bytes,
)
from .scientific_memory import MemoryDefinition, MemoryKind
from .scientific_runtime import (
    ScientificCandidateMode,
    ScientificMemoryRuntime,
    ScientificRecall,
)


MEMOPS_BOUNDED_DEV_SCHEMA = "wavemind.memops_bounded_development.v1"
MEMOPS_CANDIDATE_DEV_SCHEMA = "wavemind.memops_candidate_development.v1"


class ScientificMemOpsRetriever:
    """Leakage-safe adapter from an official MemOps corpus to a candidate runtime."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        corpus: Sequence[Mapping[str, Any]],
        mode: ScientificCandidateMode,
    ) -> None:
        self.runtime = ScientificMemoryRuntime(db_path, mode=mode)
        self._corpus_by_memory_id: dict[str, dict[str, Any]] = {}
        self._register_corpus(corpus)

    def _register_corpus(self, corpus: Sequence[Mapping[str, Any]]) -> None:
        seen_corpus_ids: set[str] = set()
        for item in corpus:
            corpus_id = str(item.get("corpus_id") or "").strip()
            content = str(item.get("text") or "").strip()
            if not corpus_id or not content:
                raise ValueError("MemOps corpus items require corpus_id and text")
            if corpus_id in seen_corpus_ids:
                raise ValueError(f"duplicate MemOps corpus_id: {corpus_id}")
            seen_corpus_ids.add(corpus_id)
            memory_id = "memops-" + sha256_bytes(
                canonical_json_bytes({"corpus_id": corpus_id, "text": content})
            )[:24]
            definition = MemoryDefinition(
                memory_id=memory_id,
                kind=MemoryKind.FACT,
                content=content,
                provenance=(corpus_id,),
                estimated_tokens=max(1, (len(content) + 3) // 4),
                estimated_latency_ms=0.1,
                safety_risk=0.0,
            )
            self.runtime.register_memory(definition, actor="memops-development-adapter")
            # The untouched official item is retained only for official prompt/scorer
            # compatibility. Retrieval decisions above cannot inspect its gold flags.
            self._corpus_by_memory_id[memory_id] = dict(item)

    def close(self) -> None:
        self.runtime.close()

    def __enter__(self) -> "ScientificMemOpsRetriever":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def retrieve(
        self,
        query: str,
        *,
        token_budget: int,
        top_k_context: int,
        evaluation_only: bool,
    ) -> tuple[list[dict[str, Any]], ScientificRecall]:
        if top_k_context < 1:
            raise ValueError("top_k_context must be positive")
        recall_method = (
            self.runtime.shadow_recall if evaluation_only else self.runtime.recall
        )
        recall = recall_method(
            query,
            context={},
            moment=0.0,
            token_budget=token_budget,
            latency_budget_ms=1000.0,
            max_safety_risk=0.0,
        )
        visible_ids = recall.selected_memory_ids[:top_k_context]
        ranked_items: list[dict[str, Any]] = []
        for rank, memory_id in enumerate(visible_ids, start=1):
            item = dict(self._corpus_by_memory_id[memory_id])
            item["score"] = float(recall.relevance[memory_id])
            item["rank"] = rank
            ranked_items.append(item)
        if visible_ids == recall.selected_memory_ids:
            return ranked_items, recall
        definitions = self.runtime.event_log.definitions()
        visible_recall = ScientificRecall(
            query=recall.query,
            selected_memory_ids=tuple(visible_ids),
            contents=tuple(definitions[memory_id].content for memory_id in visible_ids),
            relevance={memory_id: recall.relevance[memory_id] for memory_id in visible_ids},
            abstained=not bool(visible_ids),
            reason=recall.reason,
            estimated_tokens=sum(
                definitions[memory_id].estimated_tokens for memory_id in visible_ids
            ),
            estimated_latency_ms=sum(
                definitions[memory_id].estimated_latency_ms for memory_id in visible_ids
            ),
            evaluation_only=recall.evaluation_only,
        )
        return ranked_items, visible_recall


@dataclass(frozen=True)
class NativeOllamaCaller:
    """MemOps-compatible caller using Ollama's native HTTP API.

    This avoids OpenAI SDK/httpx transport behavior without changing the
    official MemOps runner. It is deliberately limited to bounded development
    evidence and is not an admission transport.
    """

    endpoint: str
    timeout_seconds: float = 300.0
    context_window: int = 32768

    def __call__(
        self,
        prompt: str,
        model: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {
                "temperature": float(temperature),
                "num_predict": int(max_tokens),
                "num_ctx": int(self.context_window),
            },
        }
        request = urllib.request.Request(
            self.endpoint.rstrip("/") + "/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"Ollama native API returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama native API request failed: {exc}") from exc

        message = result.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str):
            raise RuntimeError("Ollama native API response has no message content")
        prompt_tokens = int(result.get("prompt_eval_count") or 0)
        completion_tokens = int(result.get("eval_count") or 0)
        return {
            "content": content,
            "model": str(result.get("model") or model),
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }


def exact_git_sha(repository: str | Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(repository),
        text=True,
        encoding="utf-8",
    ).strip()


def require_exact_upstream_sha(repository: str | Path, expected_sha: str) -> None:
    actual_sha = exact_git_sha(repository)
    if actual_sha != expected_sha:
        raise RuntimeError(
            f"MemOps upstream SHA mismatch: expected {expected_sha}, got {actual_sha}"
        )


def build_bounded_dev_artifact(
    *,
    source_sha: str,
    memops_sha: str,
    model: str,
    model_digest: str,
    context_window: int,
    endpoint_kind: str,
    split_unit_ids: Sequence[str],
    case_ids: Sequence[str],
    output_files: Sequence[str | Path],
    failed_attempt_files: Sequence[str | Path],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    def file_rows(paths: Sequence[str | Path]) -> list[dict[str, Any]]:
        rows = []
        for raw_path in paths:
            path = Path(raw_path).resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            rows.append(
                {
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
        return sorted(rows, key=lambda row: row["path"])

    payload = {
        "schema": MEMOPS_BOUNDED_DEV_SCHEMA,
        "phase": "bounded-development",
        "admission_eligible": False,
        "reason_not_admission_eligible": (
            "local Ollama transport and development split; official held-out "
            "credentials and locked admission models were not used"
        ),
        "source_sha": source_sha,
        "official_upstream": {
            "repository": "MemTensor/MemOps",
            "sha": memops_sha,
            "runners": [
                "5-test_operation_metrics.py:run_pipeline",
                "5.5-evaluate_operation_metrics.py:run_pipeline",
            ],
            "upstream_modified": False,
        },
        "model": {
            "id": model,
            "digest": model_digest,
            "context_window": int(context_window),
        },
        "transport": endpoint_kind,
        "split_unit_ids": sorted(set(split_unit_ids)),
        "case_ids": list(case_ids),
        "case_count": len(case_ids),
        "final_split_touched": False,
        "failed_attempts_retained": file_rows(failed_attempt_files),
        "outputs": file_rows(output_files),
        "official_summary": dict(summary),
    }
    return attach_artifact_integrity(payload)


def build_candidate_dev_artifact(
    *,
    source_sha: str,
    protocol_digest: str,
    memops_sha: str,
    candidate_id: str,
    model: str,
    model_digest: str,
    context_window: int,
    raw_output_file: str | Path,
    case_ids: Sequence[str],
    paired_effects: Sequence[float],
    production_case_count: int,
    promoted_memory_ids: Sequence[str],
) -> dict[str, Any]:
    raw_path = Path(raw_output_file).resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)
    effects = [float(value) for value in paired_effects]
    payload = {
        "schema": MEMOPS_CANDIDATE_DEV_SCHEMA,
        "phase": "bounded-development",
        "admission_eligible": False,
        "reason_not_admission_eligible": (
            "single development split, local answer model and local judge; "
            "held-out admission arms were not executed"
        ),
        "source_sha": source_sha,
        "protocol_digest": protocol_digest,
        "official_upstream": {
            "repository": "MemTensor/MemOps",
            "sha": memops_sha,
            "runners": [
                "5-test_operation_metrics.py:run_gpt_rag",
                "5.5-evaluate_operation_metrics.py:evaluate_entry",
            ],
            "upstream_modified": False,
        },
        "candidate_id": candidate_id,
        "control_id": "no-memory",
        "model": {
            "id": model,
            "digest": model_digest,
            "context_window": int(context_window),
        },
        "case_ids": list(case_ids),
        "case_count": len(case_ids),
        "final_split_touched": False,
        "paired_effect": {
            "values": effects,
            "mean": sum(effects) / len(effects) if effects else 0.0,
            "positive_count": sum(value > 0.0 for value in effects),
            "zero_count": sum(value == 0.0 for value in effects),
            "negative_count": sum(value < 0.0 for value in effects),
        },
        "production_case_count": int(production_case_count),
        "promoted_memory_ids": sorted(set(promoted_memory_ids)),
        "raw_output": {
            "path": str(raw_path),
            "bytes": raw_path.stat().st_size,
            "sha256": file_sha256(raw_path),
        },
    }
    return attach_artifact_integrity(payload)
