from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import random
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from unittest.mock import patch

import numpy as np

from .core import WaveMind
from .encoders import HashingTextEncoder
from .evidence import canonical_json_bytes, file_sha256, sha256_bytes
from .scientific_protocol import REQUIRED_BASELINES


SCIENTIFIC_BASELINE_MATRIX_SCHEMA = "wavemind.scientific_baseline_matrix.v1"
COMMON_EMBEDDING_ID = "wavemind-hashing-text-encoder-384"
COMMON_EMBEDDING_DIMENSIONS = 384
REAL_BASELINE_PACKAGE_PINS: Mapping[str, Mapping[str, str | None]] = {
    "mem0-oss": {
        "package": "mem0ai",
        "version": "2.0.18",
        "source_revision": "c427a453a89c5a3fee73cdb2e4c4df6a651e1692",
    },
    "langgraph": {
        "package": "langgraph",
        "version": "1.2.11",
        "source_revision": "644815f9e5bc52ad8f7a5227a456227e9c3e639b",
    },
    "chroma": {
        "package": "chromadb",
        "version": "1.5.9",
        "source_revision": None,
    },
    "qdrant-local": {
        "package": "qdrant-client",
        "version": "1.19.0",
        "source_revision": None,
    },
}
WAVEMIND_BASELINE_IDS = frozenset(
    {
        "static-vector-retrieval",
        "wavemind-no-field",
        "wavemind-wavefield",
        "wavemind-graph",
        "wavemind-memory-os",
        "wavemind-full-frozen-pipeline",
    }
)


@dataclass(frozen=True)
class BaselineCorpusItem:
    memory_id: str
    text: str


@dataclass(frozen=True)
class BaselineRetrieval:
    arm_id: str
    memory_ids: tuple[str, ...]
    contents: tuple[str, ...]
    scores: tuple[float, ...]
    context_tokens: int
    retrieval_ms: float
    backend: Mapping[str, Any]

    @property
    def content_sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(list(self.contents)))


class BaselineRetriever(Protocol):
    arm_id: str

    def retrieve(
        self,
        query: str,
        *,
        top_k: int,
        token_budget: int,
    ) -> BaselineRetrieval: ...

    def close(self) -> None: ...


def estimate_tokens(text: str) -> int:
    """Frozen, provider-independent context estimate used by every baseline."""

    return max(1, (len(text.encode("utf-8")) + 3) // 4)


def _budget_hits(
    hits: Sequence[tuple[str, str, float]],
    *,
    token_budget: int,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[float, ...], int]:
    if token_budget < 1:
        raise ValueError("token_budget must be positive")
    memory_ids: list[str] = []
    contents: list[str] = []
    scores: list[float] = []
    used = 0
    for memory_id, content, score in hits:
        cost = estimate_tokens(content)
        if used + cost > token_budget:
            continue
        memory_ids.append(str(memory_id))
        contents.append(str(content))
        scores.append(float(score))
        used += cost
    return tuple(memory_ids), tuple(contents), tuple(scores), used


def common_embedding_metadata(project_root: str | Path) -> dict[str, Any]:
    encoder_path = Path(project_root).resolve() / "wavemind" / "encoders.py"
    return {
        "id": COMMON_EMBEDDING_ID,
        "dimensions": COMMON_EMBEDDING_DIMENSIONS,
        "implementation": "wavemind.encoders.HashingTextEncoder",
        "source_file": "wavemind/encoders.py",
        "source_file_sha256": file_sha256(encoder_path),
    }


def real_baseline_package_metadata() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for arm_id, expected in REAL_BASELINE_PACKAGE_PINS.items():
        package = str(expected["package"])
        try:
            distribution = importlib.metadata.distribution(package)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(
                f"required real baseline package is missing: {package}"
            ) from exc
        version = distribution.version
        if version != expected["version"]:
            raise RuntimeError(
                f"{arm_id} package version changed: expected "
                f"{expected['version']}, got {version}"
            )
        rows[arm_id] = {
            "package": package,
            "version": version,
            "pinned_source_revision": expected["source_revision"],
            "source_revision_observable_from_installed_wheel": False,
            "installed_record_sha256": sha256_bytes(
                (distribution.read_text("RECORD") or "").encode("utf-8")
            ),
        }
    return rows


def runtime_dependency_metadata() -> dict[str, Any]:
    versions: dict[str, str | None] = {}
    for package in (
        "numpy",
        "tiktoken",
        "rouge-score",
        "langchain-community",
        "torch",
        "transformers",
        "datasets",
    ):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
        "packages": versions,
        "real_baseline_packages": real_baseline_package_metadata(),
    }


def frozen_baseline_configs(protocol: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = protocol.get("baselines")
    if not isinstance(rows, list):
        raise ValueError("scientific protocol baselines are missing")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("scientific protocol baseline row is invalid")
        arm_id = str(row.get("id") or "")
        if not arm_id or arm_id in by_id:
            raise ValueError(
                "scientific protocol baseline IDs are missing or duplicated"
            )
        by_id[arm_id] = dict(row.get("config") or {})
    if set(by_id) != REQUIRED_BASELINES:
        raise ValueError("baseline matrix must use the exact frozen baseline set")
    return by_id


class _NoMemoryRetriever:
    arm_id = "no-memory"

    def retrieve(
        self,
        query: str,
        *,
        top_k: int,
        token_budget: int,
    ) -> BaselineRetrieval:
        if top_k < 1 or token_budget < 1:
            raise ValueError("retrieval limits must be positive")
        return BaselineRetrieval(
            arm_id=self.arm_id,
            memory_ids=(),
            contents=(),
            scores=(),
            context_tokens=0,
            retrieval_ms=0.0,
            backend={"implementation": "memory writes and reads disabled"},
        )

    def close(self) -> None:
        return None


class _WaveMindRetriever:
    def __init__(
        self,
        *,
        arm_id: str,
        corpus: Sequence[BaselineCorpusItem],
        scratch_dir: Path,
        config: Mapping[str, Any],
        seed: int,
    ) -> None:
        self.arm_id = arm_id
        self._config = dict(config)
        np.random.seed(seed)
        self._memory = WaveMind(
            db_path=scratch_dir / "wavemind.db",
            encoder=HashingTextEncoder(vector_dim=COMMON_EMBEDDING_DIMENSIONS),
            vector_weight=float(config["vector_weight"]),
            field_weight=float(config["field_weight"]),
            priority_weight=float(config["priority_weight"]),
            lexical_weight=float(config["lexical_weight"]),
            graph_weight=float(config["graph_weight"]),
            confidence_gate=False,
        )
        ids = self._memory.remember_batch(
            {
                "text": item.text,
                "namespace": "scientific-baseline",
                "metadata": {"scientific_memory_id": item.memory_id},
            }
            for item in corpus
        )
        self._id_map = {
            int(memory_id): item.memory_id for memory_id, item in zip(ids, corpus)
        }
        self._memory_os_report: dict[str, Any] | None = None
        if bool(config.get("memory_os")):
            from .jobs import MemoryOSWorker

            report = MemoryOSWorker(self._memory).run_once(
                namespace="scientific-baseline",
                predictive_prefetch=False,
                architecture_advice=False,
            )
            if hasattr(report, "as_dict"):
                self._memory_os_report = report.as_dict()
            else:
                self._memory_os_report = json.loads(
                    json.dumps(
                        report,
                        default=lambda value: getattr(value, "__dict__", str(value)),
                    )
                )

    def retrieve(
        self,
        query: str,
        *,
        top_k: int,
        token_budget: int,
    ) -> BaselineRetrieval:
        started = time.perf_counter_ns()
        results = self._memory.query(
            query,
            namespace="scientific-baseline",
            top_k=top_k,
            min_score=float("-inf"),
        )
        elapsed = (time.perf_counter_ns() - started) / 1_000_000.0
        hits = [
            (
                self._id_map[result.id],
                result.text,
                result.score,
            )
            for result in results
        ]
        ids, contents, scores, used = _budget_hits(hits, token_budget=token_budget)
        backend: dict[str, Any] = {
            "implementation": "wavemind.core.WaveMind",
            "config": dict(self._config),
            "real_memory_os_worker_executed": bool(self._config.get("memory_os")),
        }
        if self._memory_os_report is not None:
            backend["memory_os_report_sha256"] = sha256_bytes(
                canonical_json_bytes(self._memory_os_report)
            )
        return BaselineRetrieval(
            arm_id=self.arm_id,
            memory_ids=ids,
            contents=contents,
            scores=scores,
            context_tokens=used,
            retrieval_ms=elapsed,
            backend=backend,
        )

    def close(self) -> None:
        self._memory.close()


class _LangGraphRetriever:
    arm_id = "langgraph"

    def __init__(self, corpus: Sequence[BaselineCorpusItem]) -> None:
        from langgraph.store.memory import InMemoryStore

        self._encoder = HashingTextEncoder(vector_dim=COMMON_EMBEDDING_DIMENSIONS)
        self._store = InMemoryStore(
            index={
                "dims": COMMON_EMBEDDING_DIMENSIONS,
                "embed": self._embed,
                "fields": ["text"],
            }
        )
        for item in corpus:
            self._store.put(
                ("scientific-baseline",),
                item.memory_id,
                {"text": item.text},
            )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return self._encoder.encode_vectors(texts).astype(float).tolist()

    def retrieve(
        self,
        query: str,
        *,
        top_k: int,
        token_budget: int,
    ) -> BaselineRetrieval:
        started = time.perf_counter_ns()
        results = self._store.search(("scientific-baseline",), query=query, limit=top_k)
        elapsed = (time.perf_counter_ns() - started) / 1_000_000.0
        hits = [
            (result.key, str(result.value["text"]), float(result.score or 0.0))
            for result in results
        ]
        ids, contents, scores, used = _budget_hits(hits, token_budget=token_budget)
        return BaselineRetrieval(
            arm_id=self.arm_id,
            memory_ids=ids,
            contents=contents,
            scores=scores,
            context_tokens=used,
            retrieval_ms=elapsed,
            backend={"implementation": "langgraph.store.memory.InMemoryStore"},
        )

    def close(self) -> None:
        return None


class _ChromaRetriever:
    arm_id = "chroma"

    def __init__(self, corpus: Sequence[BaselineCorpusItem], scratch_dir: Path) -> None:
        import chromadb

        self._encoder = HashingTextEncoder(vector_dim=COMMON_EMBEDDING_DIMENSIONS)
        self._client = chromadb.PersistentClient(path=str(scratch_dir))
        self._collection = self._client.get_or_create_collection("scientific_baseline")
        self._collection.add(
            ids=[item.memory_id for item in corpus],
            embeddings=self._encoder.encode_vectors([item.text for item in corpus])
            .astype(float)
            .tolist(),
            documents=[item.text for item in corpus],
        )

    def retrieve(
        self,
        query: str,
        *,
        top_k: int,
        token_budget: int,
    ) -> BaselineRetrieval:
        started = time.perf_counter_ns()
        response = self._collection.query(
            query_embeddings=[
                self._encoder.encode_vector(query).astype(float).tolist()
            ],
            n_results=top_k,
            include=["documents", "distances"],
        )
        elapsed = (time.perf_counter_ns() - started) / 1_000_000.0
        ids_row = (response.get("ids") or [[]])[0]
        docs_row = (response.get("documents") or [[]])[0]
        distances_row = (response.get("distances") or [[]])[0]
        hits = [
            (memory_id, content, 1.0 - float(distance))
            for memory_id, content, distance in zip(ids_row, docs_row, distances_row)
        ]
        ids, contents, scores, used = _budget_hits(hits, token_budget=token_budget)
        return BaselineRetrieval(
            arm_id=self.arm_id,
            memory_ids=ids,
            contents=contents,
            scores=scores,
            context_tokens=used,
            retrieval_ms=elapsed,
            backend={"implementation": "chromadb.PersistentClient"},
        )

    def close(self) -> None:
        clear = getattr(self._client, "clear_system_cache", None)
        if callable(clear):
            clear()


class _QdrantRetriever:
    arm_id = "qdrant-local"

    def __init__(self, corpus: Sequence[BaselineCorpusItem], scratch_dir: Path) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        self._encoder = HashingTextEncoder(vector_dim=COMMON_EMBEDDING_DIMENSIONS)
        self._client = QdrantClient(path=str(scratch_dir))
        self._collection_name = "scientific_baseline"
        self._client.create_collection(
            self._collection_name,
            vectors_config=VectorParams(
                size=COMMON_EMBEDDING_DIMENSIONS,
                distance=Distance.COSINE,
            ),
        )
        vectors = self._encoder.encode_vectors([item.text for item in corpus])
        self._client.upsert(
            self._collection_name,
            points=[
                PointStruct(
                    id=index,
                    vector=vector.astype(float).tolist(),
                    payload={"memory_id": item.memory_id, "text": item.text},
                )
                for index, (item, vector) in enumerate(zip(corpus, vectors))
            ],
            wait=True,
        )

    def retrieve(
        self,
        query: str,
        *,
        top_k: int,
        token_budget: int,
    ) -> BaselineRetrieval:
        started = time.perf_counter_ns()
        response = self._client.query_points(
            self._collection_name,
            query=self._encoder.encode_vector(query),
            limit=top_k,
            with_payload=True,
        )
        elapsed = (time.perf_counter_ns() - started) / 1_000_000.0
        hits = [
            (
                str((point.payload or {})["memory_id"]),
                str((point.payload or {})["text"]),
                float(point.score),
            )
            for point in response.points
        ]
        ids, contents, scores, used = _budget_hits(hits, token_budget=token_budget)
        return BaselineRetrieval(
            arm_id=self.arm_id,
            memory_ids=ids,
            contents=contents,
            scores=scores,
            context_tokens=used,
            retrieval_ms=elapsed,
            backend={"implementation": "qdrant_client.QdrantClient(path=...)"},
        )

    def close(self) -> None:
        self._client.close()


class _Mem0HashingEmbedding:
    def __init__(self) -> None:
        self._encoder = HashingTextEncoder(vector_dim=COMMON_EMBEDDING_DIMENSIONS)

    def embed(self, text: str, memory_action: str | None = None) -> list[float]:
        del memory_action
        return self._encoder.encode_vector(text).astype(float).tolist()

    def embed_batch(
        self, texts: list[str], memory_action: str = "add"
    ) -> list[list[float]]:
        del memory_action
        return self._encoder.encode_vectors(texts).astype(float).tolist()


class _UnusedMem0LLM:
    """Construction dependency only; infer=False forbids invoking this object."""

    config: Mapping[str, Any] = {}

    def generate_response(self, *_: Any, **__: Any) -> Any:
        raise RuntimeError("Mem0 LLM use is forbidden for the retrieval-only baseline")


class _Mem0Retriever:
    arm_id = "mem0-oss"

    def __init__(self, corpus: Sequence[BaselineCorpusItem], scratch_dir: Path) -> None:
        import mem0.memory.main as mem0_main
        from mem0 import Memory

        mem0_main.MEM0_TELEMETRY = False
        mem0_main.capture_event = lambda *_args, **_kwargs: None
        self._run_id = "scientific-baseline"
        config = {
            "version": "v1.1",
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": "unused-controlled-hashing-encoder",
                    "embedding_dims": COMMON_EMBEDDING_DIMENSIONS,
                    "ollama_base_url": "http://127.0.0.1:1",
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": "scientific_baseline",
                    "embedding_model_dims": COMMON_EMBEDDING_DIMENSIONS,
                    "path": str(scratch_dir / "qdrant"),
                },
            },
            "llm": {
                "provider": "ollama",
                "config": {
                    "model": "unused-infer-false",
                    "ollama_base_url": "http://127.0.0.1:1",
                },
            },
            "history_db_path": str(scratch_dir / "history.db"),
        }
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    mem0_main.EmbedderFactory,
                    "create",
                    return_value=_Mem0HashingEmbedding(),
                )
            )
            stack.enter_context(
                patch.object(
                    mem0_main.LlmFactory,
                    "create",
                    return_value=_UnusedMem0LLM(),
                )
            )
            self._memory = Memory.from_config(config)
        for item in corpus:
            self._memory.add(
                item.text,
                run_id=self._run_id,
                metadata={"scientific_memory_id": item.memory_id},
                infer=False,
            )

    def retrieve(
        self,
        query: str,
        *,
        top_k: int,
        token_budget: int,
    ) -> BaselineRetrieval:
        started = time.perf_counter_ns()
        response = self._memory.search(
            query,
            top_k=top_k,
            filters={"run_id": self._run_id},
            threshold=0.0,
            rerank=False,
        )
        elapsed = (time.perf_counter_ns() - started) / 1_000_000.0
        hits = [
            (
                str(
                    result.get("metadata", {}).get("scientific_memory_id")
                    or result["id"]
                ),
                str(result["memory"]),
                float(result.get("score") or 0.0),
            )
            for result in response.get("results", [])
        ]
        ids, contents, scores, used = _budget_hits(hits, token_budget=token_budget)
        return BaselineRetrieval(
            arm_id=self.arm_id,
            memory_ids=ids,
            contents=contents,
            scores=scores,
            context_tokens=used,
            retrieval_ms=elapsed,
            backend={
                "implementation": "mem0.Memory.from_config with real Qdrant store",
                "infer": False,
                "constructor_dependencies_injected": [
                    "common HashingTextEncoder",
                    "fail-closed unused LLM",
                ],
                "telemetry_disabled": True,
                "real_mem0_add_and_search_executed": True,
            },
        )

    def close(self) -> None:
        client = getattr(self._memory.vector_store, "client", None)
        close = getattr(client, "close", None)
        if callable(close):
            close()


def build_baseline_retrievers(
    *,
    corpus: Sequence[BaselineCorpusItem],
    scratch_dir: str | Path,
    protocol: Mapping[str, Any],
    seed: int,
) -> dict[str, BaselineRetriever]:
    if not corpus:
        raise ValueError("baseline corpus must not be empty")
    if len({item.memory_id for item in corpus}) != len(corpus):
        raise ValueError("baseline corpus memory IDs must be unique")
    real_baseline_package_metadata()
    configs = frozen_baseline_configs(protocol)
    root = Path(scratch_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    retrievers: dict[str, BaselineRetriever] = {"no-memory": _NoMemoryRetriever()}
    try:
        for arm_id in sorted(WAVEMIND_BASELINE_IDS):
            target = root / arm_id
            target.mkdir(parents=True, exist_ok=True)
            retrievers[arm_id] = _WaveMindRetriever(
                arm_id=arm_id,
                corpus=corpus,
                scratch_dir=target,
                config=configs[arm_id],
                seed=seed,
            )
        retrievers["langgraph"] = _LangGraphRetriever(corpus)
        chroma_dir = root / "chroma"
        chroma_dir.mkdir(parents=True, exist_ok=True)
        retrievers["chroma"] = _ChromaRetriever(corpus, chroma_dir)
        qdrant_dir = root / "qdrant-local"
        qdrant_dir.mkdir(parents=True, exist_ok=True)
        retrievers["qdrant-local"] = _QdrantRetriever(corpus, qdrant_dir)
        mem0_dir = root / "mem0-oss"
        mem0_dir.mkdir(parents=True, exist_ok=True)
        retrievers["mem0-oss"] = _Mem0Retriever(corpus, mem0_dir)
    except Exception:
        close_baseline_retrievers(retrievers)
        raise
    if set(retrievers) != REQUIRED_BASELINES:
        close_baseline_retrievers(retrievers)
        raise RuntimeError("constructed baseline set differs from frozen protocol")
    return retrievers


def close_baseline_retrievers(retrievers: Mapping[str, BaselineRetriever]) -> None:
    for retriever in reversed(list(retrievers.values())):
        try:
            retriever.close()
        except Exception:
            pass


def fresh_scratch_directory(path: str | Path) -> Path:
    """Create a fresh directory without deleting or overwriting prior evidence."""

    target = Path(path).resolve()
    if target == target.anchor or len(target.parts) < 4:
        raise ValueError("refusing broad baseline scratch directory")
    if target.exists():
        raise FileExistsError(
            f"baseline scratch directory already exists and is retained: {target}"
        )
    target.mkdir(parents=True)
    return target


def deterministic_arm_order(*, seed: int, case_id: str) -> list[str]:
    order = sorted(REQUIRED_BASELINES)
    random.Random(f"{seed}:{case_id}").shuffle(order)
    return order


def hardware_inventory() -> dict[str, Any]:
    inventory: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "python": platform.python_version(),
    }
    try:
        import psutil

        inventory["physical_cpu_count"] = psutil.cpu_count(logical=False)
        inventory["memory_bytes"] = int(psutil.virtual_memory().total)
    except ImportError:
        inventory["physical_cpu_count"] = None
        inventory["memory_bytes"] = None
    try:
        import torch

        inventory["torch_version"] = torch.__version__
        inventory["cuda_available"] = bool(torch.cuda.is_available())
        inventory["cuda_device"] = (
            torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
        )
    except ImportError:
        inventory["torch_version"] = None
        inventory["cuda_available"] = False
        inventory["cuda_device"] = None
    return inventory
