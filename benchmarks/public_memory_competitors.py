from __future__ import annotations

import gc
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from benchmarks.long_memory_evidence_benchmark import (
    EvidenceDataset,
    EvidenceMetrics,
    compute_evidence_metrics,
)


MEM0_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
HINDSIGHT_EXTRACTION_MODE = "chunks"
_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "",
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        )
    )
    if name
}
_LOCOMO_TIMESTAMP = re.compile(
    r"^\s*(\d{1,2}):(\d{2})\s*(am|pm)\s+on\s+"
    r"(\d{1,2})\s+([A-Za-z]+),\s*(\d{4})\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExternalEvidenceMetrics(EvidenceMetrics):
    system_version: str = ""
    embedding_profile: str = ""
    provenance_mode: str = ""


class JsonTransport(Protocol):
    def __call__(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        ...


def _estimate_tokens(text: str) -> int:
    words = [word for word in text.replace("\n", " ").split(" ") if word]
    return max(1, int(len(words) * 1.25 + 0.999))


def _external_metrics(
    dataset: EvidenceDataset,
    rankings: dict[str, list[str]],
    texts: dict[str, list[str]],
    latencies: list[float],
    top_k: int,
    engine: str,
    *,
    ingest_total_ms: float,
    system_version: str,
    embedding_profile: str,
    provenance_mode: str,
    ingest_scope: str = "end_to_end_native_embedding_and_persistence",
) -> ExternalEvidenceMetrics:
    base = compute_evidence_metrics(
        dataset.queries,
        rankings,
        texts,
        latencies,
        sum(_estimate_tokens(memory.text) for memory in dataset.memories),
        top_k,
        engine,
    )
    values = asdict(base)
    values.update(
        ingest_total_ms=ingest_total_ms,
        ingest_avg_ms=ingest_total_ms / max(1, len(dataset.memories)),
        ingest_scope=ingest_scope,
        system_version=system_version,
        embedding_profile=embedding_profile,
        provenance_mode=provenance_mode,
    )
    return ExternalEvidenceMetrics(**values)


class _BenchmarkEmbeddings:
    """Expose the shared benchmark encoder through LangGraph's embedding API."""

    def __init__(self, encoder: Any) -> None:
        self.encoder = encoder

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.encoder.encode_vectors(texts).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.encoder.encode_vector(text).tolist()


def _store_item_value(item: Any) -> dict[str, Any]:
    value = getattr(item, "value", None)
    if value is None and isinstance(item, dict):
        value = item.get("value")
    return dict(value or {})


def run_langgraph_store_evidence(
    dataset: EvidenceDataset,
    encoder: Any,
    top_k: int,
    *,
    store_factory: Callable[[dict[str, Any]], Any] | None = None,
) -> ExternalEvidenceMetrics:
    """Run LangGraph BaseStore semantic retrieval on the shared protocol.

    This is deliberately labeled as a BaseStore baseline, not LangMem: it
    measures framework-native storage, namespace isolation, semantic search,
    and source provenance without claiming memory formation or optimization.
    """

    vector_dim = int(getattr(encoder, "vector_dim"))
    index = {
        "embed": _BenchmarkEmbeddings(encoder),
        "dims": vector_dim,
        "fields": ["text"],
    }
    if store_factory is None:
        if importlib.util.find_spec("langgraph") is None:
            raise RuntimeError(
                "Install the real LangGraph benchmark dependency: "
                'pip install "langgraph>=1.2,<2".'
            )
        from langgraph.store.memory import InMemoryStore

        store = InMemoryStore(index=index)
    else:
        store = store_factory(index)

    ingest_started = time.perf_counter()
    try:
        for item in dataset.memories:
            store.put(
                (item.namespace, "memories"),
                item.id,
                {
                    "text": item.text,
                    "evidence_id": item.id,
                    "timestamp": item.timestamp or "",
                },
                index=["text"],
            )
        ingest_total_ms = (time.perf_counter() - ingest_started) * 1000.0

        rankings: dict[str, list[str]] = {}
        texts: dict[str, list[str]] = {}
        latencies: list[float] = []
        for query in dataset.queries:
            started = time.perf_counter()
            rows = store.search(
                (query.namespace, "memories"),
                query=query.text,
                limit=top_k,
            )
            latencies.append((time.perf_counter() - started) * 1000.0)
            values = [_store_item_value(row) for row in rows]
            rankings[query.id] = [
                str(value.get("evidence_id") or "") for value in values
            ][:top_k]
            texts[query.id] = [
                str(value.get("text") or "") for value in values
            ][:top_k]
    finally:
        close_store = getattr(store, "close", None)
        if callable(close_store):
            close_store()

    return _external_metrics(
        dataset,
        rankings,
        texts,
        latencies,
        top_k,
        "LangGraph BaseStore",
        ingest_total_ms=ingest_total_ms,
        system_version=_package_version("langgraph"),
        embedding_profile=f"shared:{type(encoder).__name__}",
        provenance_mode="value.evidence_id",
        ingest_scope="end_to_end_shared_embedding_and_in_memory_persistence",
    )


def _package_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _hindsight_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    try:
        return datetime.fromisoformat(
            candidate.replace("Z", "+00:00")
        ).isoformat()
    except ValueError:
        pass
    match = _LOCOMO_TIMESTAMP.match(candidate)
    if match is None:
        return None
    hour, minute, meridiem, day, month_name, year = match.groups()
    month = _MONTHS.get(month_name.lower())
    if month is None:
        return None
    hour_value = int(hour) % 12
    if meridiem.lower() == "pm":
        hour_value += 12
    return datetime(
        int(year),
        month,
        int(day),
        hour_value,
        int(minute),
    ).isoformat()


def _mem0_rows(response: Any) -> list[dict[str, Any]]:
    rows = response.get("results") if isinstance(response, dict) else response
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _close_mem0(memory: Any) -> None:
    vector_store = getattr(memory, "vector_store", None)
    client = getattr(vector_store, "client", None)
    close_client = getattr(client, "close", None)
    if callable(close_client):
        close_client()
    close_memory = getattr(memory, "close", None)
    if callable(close_memory):
        close_memory()


def run_mem0_evidence(
    dataset: EvidenceDataset,
    _encoder: Any,
    top_k: int,
    *,
    memory_factory: Callable[[dict[str, Any]], Any] | None = None,
    embedding_model: str = MEM0_EMBEDDING_MODEL,
) -> ExternalEvidenceMetrics:
    """Run the real Mem0 OSS library with inference disabled.

    Disabling inference preserves the public benchmark's source memories instead
    of introducing an extra LLM extraction variable. Mem0 still owns embedding,
    persistence, namespace filtering, and retrieval.
    """

    os.environ.setdefault("MEM0_TELEMETRY", "False")
    if memory_factory is None:
        missing = [
            module
            for module in ("mem0", "fastembed", "qdrant_client")
            if importlib.util.find_spec(module) is None
        ]
        if missing:
            raise RuntimeError(
                "Install the real Mem0 benchmark dependencies: "
                'pip install "mem0ai" "fastembed" "qdrant-client". '
                f"Missing: {', '.join(missing)}"
            )
        from mem0 import Memory

        memory_factory = Memory.from_config

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = {
            "llm": {
                "provider": "openai",
                "config": {"api_key": "unused-infer-false"},
            },
            "embedder": {
                "provider": "fastembed",
                "config": {"model": embedding_model},
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": str(root / "qdrant"),
                    "collection_name": "wavemind_public_memory_benchmark",
                    "embedding_model_dims": 384,
                },
            },
            "history_db_path": str(root / "history.db"),
        }
        memory = memory_factory(config)
        ingest_started = time.perf_counter()
        try:
            for item in dataset.memories:
                memory.add(
                    item.text,
                    user_id=item.namespace,
                    metadata={
                        "evidence_id": item.id,
                        "timestamp": item.timestamp or "",
                    },
                    infer=False,
                )
            ingest_total_ms = (time.perf_counter() - ingest_started) * 1000.0

            rankings: dict[str, list[str]] = {}
            texts: dict[str, list[str]] = {}
            latencies: list[float] = []
            for query in dataset.queries:
                started = time.perf_counter()
                response = memory.search(
                    query.text,
                    filters={"user_id": query.namespace},
                    top_k=top_k,
                    threshold=0.0,
                    show_expired=False,
                )
                latencies.append((time.perf_counter() - started) * 1000.0)
                rows = _mem0_rows(response)
                rankings[query.id] = [
                    str(dict(row.get("metadata") or {}).get("evidence_id") or "")
                    for row in rows
                ][:top_k]
                texts[query.id] = [
                    str(row.get("memory") or row.get("text") or "")
                    for row in rows
                ][:top_k]
        finally:
            _close_mem0(memory)
            del memory
            gc.collect()

    return _external_metrics(
        dataset,
        rankings,
        texts,
        latencies,
        top_k,
        "Mem0 OSS",
        ingest_total_ms=ingest_total_ms,
        system_version=_package_version("mem0ai"),
        embedding_profile=f"fastembed:{embedding_model}",
        provenance_mode="metadata.evidence_id",
    )


class HindsightHttpTransport:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = float(timeout_seconds)
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

    def __call__(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Hindsight {method} {path} failed with HTTP {exc.code}: {body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Hindsight {method} {path} failed: {exc.reason}"
            ) from exc
        if not body:
            return {}
        decoded = json.loads(body.decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {"value": decoded}


def _bank_id(prefix: str, namespace: str) -> str:
    digest = hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def run_hindsight_evidence(
    dataset: EvidenceDataset,
    _encoder: Any,
    top_k: int,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    transport: JsonTransport | None = None,
    bank_prefix: str = "wavemind-benchmark",
    cleanup_banks: bool = True,
    batch_size: int = 64,
    system_version: str | None = None,
    embedding_profile: str | None = None,
) -> ExternalEvidenceMetrics:
    """Run a real Hindsight service in official chunks/no-LLM mode.

    Every source memory is retained with its public evidence ID as document_id.
    Recall results are scored only through that returned provenance field.
    """

    if transport is None:
        resolved_url = base_url or os.environ.get("HINDSIGHT_BASE_URL")
        if not resolved_url:
            raise RuntimeError(
                "Set HINDSIGHT_BASE_URL to a running local Hindsight service."
            )
        transport = HindsightHttpTransport(
            resolved_url,
            api_key=api_key or os.environ.get("HINDSIGHT_API_KEY"),
        )
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    namespace_banks = {
        namespace: _bank_id(bank_prefix, namespace)
        for namespace in sorted({memory.namespace for memory in dataset.memories})
    }
    memories_by_namespace: dict[str, list[Any]] = {}
    for memory in dataset.memories:
        memories_by_namespace.setdefault(memory.namespace, []).append(memory)

    ingest_started = time.perf_counter()
    created_banks: list[str] = []
    try:
        for namespace, bank_id in namespace_banks.items():
            transport(
                "PUT",
                f"/v1/default/banks/{urllib.parse.quote(bank_id, safe='')}",
                {
                    "name": f"WaveMind benchmark {namespace}",
                    "retain_extraction_mode": HINDSIGHT_EXTRACTION_MODE,
                    "enable_observations": False,
                },
            )
            created_banks.append(bank_id)
            memories = memories_by_namespace.get(namespace, [])
            for offset in range(0, len(memories), batch_size):
                batch = memories[offset : offset + batch_size]
                transport(
                    "POST",
                    (
                        f"/v1/default/banks/"
                        f"{urllib.parse.quote(bank_id, safe='')}/memories"
                    ),
                    {
                        "items": [
                            dict(
                                {
                                    "content": item.text,
                                    "context": "public benchmark evidence",
                                    "metadata": {"evidence_id": item.id},
                                    "document_id": item.id,
                                    "tags": ["wavemind-public-benchmark"],
                                },
                                **(
                                    {
                                        "timestamp": normalized_timestamp
                                    }
                                    if (
                                        normalized_timestamp
                                        := _hindsight_timestamp(item.timestamp)
                                    )
                                    else {}
                                ),
                            )
                            for item in batch
                        ],
                        "async": False,
                    },
                )
        ingest_total_ms = (time.perf_counter() - ingest_started) * 1000.0

        rankings: dict[str, list[str]] = {}
        texts: dict[str, list[str]] = {}
        latencies: list[float] = []
        for query in dataset.queries:
            bank_id = namespace_banks[query.namespace]
            started = time.perf_counter()
            response = transport(
                "POST",
                (
                    f"/v1/default/banks/{urllib.parse.quote(bank_id, safe='')}"
                    "/memories/recall"
                ),
                {
                    "query": query.text,
                    "types": ["world", "experience"],
                    "prefer_observations": False,
                    "budget": "low",
                    "max_tokens": max(128, top_k * 96),
                    "tags": ["wavemind-public-benchmark"],
                    "tags_match": "all_strict",
                },
            )
            latencies.append((time.perf_counter() - started) * 1000.0)
            rows = [
                row
                for row in response.get("results", [])
                if isinstance(row, dict)
            ][:top_k]
            rankings[query.id] = [
                str(
                    row.get("document_id")
                    or dict(row.get("metadata") or {}).get("evidence_id")
                    or ""
                )
                for row in rows
            ]
            texts[query.id] = [str(row.get("text") or "") for row in rows]
    finally:
        if cleanup_banks:
            for bank_id in reversed(created_banks):
                transport(
                    "DELETE",
                    f"/v1/default/banks/{urllib.parse.quote(bank_id, safe='')}",
                    None,
                )

    return _external_metrics(
        dataset,
        rankings,
        texts,
        latencies,
        top_k,
        "Hindsight OSS",
        ingest_total_ms=ingest_total_ms,
        system_version=system_version or _package_version("hindsight-client"),
        embedding_profile=(
            embedding_profile
            or "service-configured; record in benchmark environment"
        ),
        provenance_mode="document_id",
    )

