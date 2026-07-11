from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.production_load_benchmark import add_slo_evaluation, preflight


CHECKPOINT_SCHEMA = "wavemind.production_streaming_checkpoint.v1"


def _normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms <= 1e-12, 1.0, norms)
    return (matrix / norms).astype(np.float32)


def _normalize_one(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        return vector
    return (vector / norm).astype(np.float32)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, int(round((pct / 100.0) * (len(ordered) - 1)))),
    )
    return ordered[index]


def _optional_int_env(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return int(value)


def _optional_float_env(name: str) -> float | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return float(value)


def _optional_bool_env(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value.lower() in {"1", "true", "yes", "on"}


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return bool(default)
    return value.lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return int(default)
    return int(value)


def _positive_int_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _positive_int_list_env(name: str, default: Iterable[int]) -> list[int]:
    raw = os.environ.get(name)
    values = [int(value) for value in _split_env_list(raw)] if raw else list(default)
    if not values or any(value <= 0 for value in values):
        raise ValueError(f"{name} must contain positive integers")
    return sorted(set(values))


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _split_env_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in re.split(r"[,;\n]+", value) if part.strip()]


def _safe_identifier(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"{label} must be a simple SQL identifier")
    return value


def _vector_literal(vector: np.ndarray) -> str:
    normalized = _normalize_one(vector)
    return json.dumps([float(value) for value in normalized], separators=(",", ":"))


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _git_source_ref() -> str | None:
    configured = (os.environ.get("GITHUB_SHA") or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{40}", configured):
        return configured.lower()
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip()
    return value.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", value) else None


def _benchmark_provenance() -> dict[str, Any]:
    generated_at = _utc_now()
    source_ref = _git_source_ref()
    workflow_run_id = (os.environ.get("GITHUB_RUN_ID") or "").strip() or None
    repository = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    server_url = (os.environ.get("GITHUB_SERVER_URL") or "").strip()
    workflow_run_url = None
    if workflow_run_id and repository and server_url:
        workflow_run_url = (
            f"{server_url.rstrip('/')}/{repository}/actions/runs/{workflow_run_id}"
        )
    github_actions = (os.environ.get("GITHUB_ACTIONS") or "").lower() == "true"
    evidence_source = (
        os.environ.get("WAVEMIND_BENCHMARK_EVIDENCE_SOURCE")
        or ("github-actions" if github_actions else "local-service")
    ).strip()
    environment = (
        os.environ.get("WAVEMIND_BENCHMARK_ENVIRONMENT")
        or ("github-actions" if github_actions else "local-service")
    ).strip()
    execution_id = (
        os.environ.get("WAVEMIND_BENCHMARK_RUN_ID")
        or workflow_run_id
        or f"local-{generated_at.replace(':', '').replace('-', '')}-{(source_ref or 'unknown')[:12]}"
    ).strip()
    return {
        "schema": "wavemind.production_streaming_load.v1",
        "generated_at": generated_at,
        "source_ref": source_ref,
        "execution_id": execution_id,
        "execution_environment": environment,
        "evidence_source": evidence_source,
        "workflow_run_id": workflow_run_id,
        "workflow_run_url": workflow_run_url,
    }


def _checkpoint_path_from_env() -> Path | None:
    value = os.environ.get("WAVEMIND_STREAMING_CHECKPOINT_PATH")
    if value is None or value == "":
        return None
    return Path(value).expanduser()


def _checkpoint_signature(
    *,
    engine: str,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "engine": engine,
        "vectors": int(count),
        "vector_dim": int(dim),
        "queries": min(int(query_count), int(count)),
        "top_k": int(top_k),
        "seed": int(seed),
        "noise": float(noise),
        "batch_size": int(batch_size),
        "extra": extra or {},
    }


def _new_checkpoint(signature: dict[str, Any]) -> dict[str, Any]:
    now = _utc_now()
    return {
        "schema": CHECKPOINT_SCHEMA,
        "created_at": now,
        "updated_at": now,
        "signature": signature,
        "metadata": {},
        "completed_batch_starts": [],
        "source_vectors": {},
    }


def _load_checkpoint(path: Path | None, signature: dict[str, Any]) -> dict[str, Any]:
    if path is None or not path.exists():
        return _new_checkpoint(signature)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != CHECKPOINT_SCHEMA:
        raise ValueError(f"checkpoint {path} has unsupported schema")
    if payload.get("signature") != signature:
        raise ValueError(f"checkpoint {path} does not match this streaming run")
    payload.setdefault("metadata", {})
    payload.setdefault("completed_batch_starts", [])
    payload.setdefault("source_vectors", {})
    return payload


def _load_faiss_ivfpq_checkpoint(
    path: Path | None,
    signature: dict[str, Any],
    *,
    legacy_nprobe: int,
) -> dict[str, Any]:
    try:
        return _load_checkpoint(path, signature)
    except ValueError:
        if path is None or not path.exists():
            raise
        payload = json.loads(path.read_text(encoding="utf-8"))
        legacy_signature = dict(signature)
        legacy_extra = dict(signature.get("extra", {}))
        legacy_extra["nprobe"] = int(legacy_nprobe)
        legacy_signature["extra"] = legacy_extra
        if payload.get("signature") != legacy_signature:
            raise
        payload["signature"] = signature
        payload.setdefault("metadata", {})["signature_migrated_from_nprobe"] = int(
            legacy_nprobe
        )
        _write_checkpoint(path, payload)
        return payload


def _load_pgvector_checkpoint(
    path: Path | None,
    signature: dict[str, Any],
) -> dict[str, Any]:
    try:
        return _load_checkpoint(path, signature)
    except ValueError:
        if path is None or not path.exists():
            raise
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload_signature = dict(payload.get("signature", {}))
        payload_extra = dict(payload_signature.get("extra", {}))
        migrated_keys = []
        for key in (
            "create_hnsw",
            "hnsw_m",
            "hnsw_ef_construction",
            "exact",
            "iterative_scan",
            "index_type",
            "ivfflat_lists",
        ):
            if key in payload_extra:
                migrated_keys.append(key)
                payload_extra.pop(key)
        payload_signature["extra"] = payload_extra
        if payload.get("schema") != CHECKPOINT_SCHEMA or payload_signature != signature:
            raise
        payload["signature"] = signature
        payload.setdefault("metadata", {})["signature_migrated_index_keys"] = migrated_keys
        payload.setdefault("completed_batch_starts", [])
        payload.setdefault("source_vectors", {})
        _write_checkpoint(path, payload)
        return payload


def _write_checkpoint(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = _utc_now()
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    retry_count = max(
        1,
        int(os.environ.get("WAVEMIND_CHECKPOINT_REPLACE_RETRIES", "8")),
    )
    retry_delay_seconds = max(
        0.0,
        float(os.environ.get("WAVEMIND_CHECKPOINT_REPLACE_DELAY_SECONDS", "0.025")),
    )
    for attempt in range(retry_count):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt + 1 >= retry_count:
                raise
            time.sleep(retry_delay_seconds * (attempt + 1))


def _checkpoint_source_vectors(payload: dict[str, Any]) -> dict[int, np.ndarray]:
    return {
        int(source_id): np.asarray(vector, dtype=np.float32)
        for source_id, vector in payload.get("source_vectors", {}).items()
    }


def _checkpoint_completed_batches(payload: dict[str, Any]) -> set[int]:
    return {int(value) for value in payload.get("completed_batch_starts", [])}


def _checkpoint_complete_for_run(
    payload: dict[str, Any],
    *,
    count: int,
    batch_size: int,
    source_ids: Iterable[int],
) -> bool:
    expected_batch_starts = set(range(1, int(count) + 1, int(batch_size)))
    completed_batches = _checkpoint_completed_batches(payload)
    stored_source_ids = {
        int(source_id) for source_id in payload.get("source_vectors", {})
    }
    return completed_batches == expected_batch_starts and all(
        int(source_id) in stored_source_ids for source_id in source_ids
    )


def _record_checkpoint_batch(
    *,
    path: Path | None,
    payload: dict[str, Any],
    batch_start: int,
    captured: dict[int, np.ndarray],
) -> None:
    completed = _checkpoint_completed_batches(payload)
    completed.add(int(batch_start))
    payload["completed_batch_starts"] = sorted(completed)
    source_vectors = payload.setdefault("source_vectors", {})
    for source_id, vector in captured.items():
        source_vectors[str(int(source_id))] = [
            float(value) for value in np.asarray(vector, dtype=np.float32)
        ]
    _write_checkpoint(path, payload)


def _checkpoint_extra(
    checkpoint_path: Path | None,
    checkpoint: dict[str, Any],
    completed_batches: set[int],
) -> dict[str, Any]:
    if checkpoint_path is None:
        return {"checkpoint_enabled": False}
    return {
        "checkpoint_enabled": True,
        "checkpoint_path": artifact_index_path(checkpoint_path),
        "checkpoint_completed_batches": len(completed_batches),
        "checkpoint_source_vectors": len(checkpoint.get("source_vectors", {})),
    }


@dataclass(frozen=True)
class QdrantShardTarget:
    index: int
    url: str
    collection_name: str
    api_key: str | None = None
    grpc_port: int | None = None


def _qdrant_shard_index(point_id: int, shard_count: int) -> int:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    return (int(point_id) - 1) % int(shard_count)


def _qdrant_shard_targets_from_env(base_collection_name: str) -> list[QdrantShardTarget]:
    urls = _split_env_list(os.environ.get("WAVEMIND_QDRANT_URLS"))
    if not urls:
        url = os.environ.get("WAVEMIND_QDRANT_URL")
        if url:
            urls = [url]
    api_keys = _split_env_list(os.environ.get("WAVEMIND_QDRANT_API_KEYS"))
    default_api_key = os.environ.get("WAVEMIND_QDRANT_API_KEY")
    grpc_ports = _split_env_list(os.environ.get("WAVEMIND_QDRANT_GRPC_PORTS"))
    default_grpc_port = _optional_int_env("WAVEMIND_QDRANT_GRPC_PORT")
    targets: list[QdrantShardTarget] = []
    for index, url in enumerate(urls):
        api_key = api_keys[index] if index < len(api_keys) else default_api_key
        grpc_port = (
            int(grpc_ports[index]) if index < len(grpc_ports) else default_grpc_port
        )
        targets.append(
            QdrantShardTarget(
                index=index,
                url=url,
                collection_name=f"{base_collection_name}_s{index:03d}",
                api_key=api_key,
                grpc_port=grpc_port,
            )
        )
    return targets


def _merge_scored_hits(hits_by_shard: Iterable[Iterable[Any]], top_k: int) -> list[int]:
    scored: list[tuple[float, int]] = []
    for hits in hits_by_shard:
        for hit in hits:
            scored.append((float(getattr(hit, "score", 0.0)), int(hit.id)))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [point_id for _, point_id in scored[: int(top_k)]]


def _upsert_qdrant_points(
    *,
    executor: concurrent.futures.Executor,
    client: Any,
    collection_name: str,
    points: list[Any],
    upsert_batch_size: int,
) -> int:
    return _upsert_qdrant_point_chunks(
        executor=executor,
        client=client,
        collection_name=collection_name,
        point_chunks=_chunks(points, upsert_batch_size),
        max_in_flight=1,
    )


def _upsert_qdrant_point_chunks(
    *,
    executor: concurrent.futures.Executor,
    client: Any,
    collection_name: str,
    point_chunks: Iterable[list[Any]],
    max_in_flight: int,
) -> int:
    if max_in_flight <= 0:
        raise ValueError("max_in_flight must be positive")

    def upsert_chunk(point_chunk: list[Any]) -> int:
        client.upsert(collection_name=collection_name, points=point_chunk)
        return len(point_chunk)

    inserted = 0
    pending: set[concurrent.futures.Future[int]] = set()
    chunks = iter(point_chunks)
    exhausted = False
    while pending or not exhausted:
        while len(pending) < max_in_flight and not exhausted:
            try:
                point_chunk = next(chunks)
            except StopIteration:
                exhausted = True
                break
            pending.add(executor.submit(upsert_chunk, point_chunk))
        if pending:
            completed, pending = concurrent.futures.wait(
                pending,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            inserted += sum(future.result() for future in completed)
    return inserted


def _iter_qdrant_point_chunks(
    ids: np.ndarray,
    vectors: np.ndarray,
    *,
    point_type: Any,
    chunk_size: int,
) -> Iterable[list[Any]]:
    if chunk_size <= 0:
        raise ValueError("chunk size must be positive")
    for start in range(0, len(ids), chunk_size):
        stop = min(len(ids), start + chunk_size)
        yield [
            point_type(id=int(point_id), vector=vector.tolist())
            for point_id, vector in zip(ids[start:stop], vectors[start:stop])
        ]


def _iter_qdrant_shard_point_chunks(
    ids: np.ndarray,
    vectors: np.ndarray,
    *,
    shard_index: int,
    shard_count: int,
    point_type: Any,
    chunk_size: int,
) -> Iterable[list[Any]]:
    if chunk_size <= 0:
        raise ValueError("chunk size must be positive")
    point_chunk: list[Any] = []
    for point_id, vector in zip(ids, vectors):
        if _qdrant_shard_index(int(point_id), shard_count) != shard_index:
            continue
        point_chunk.append(point_type(id=int(point_id), vector=vector.tolist()))
        if len(point_chunk) >= chunk_size:
            yield point_chunk
            point_chunk = []
    if point_chunk:
        yield point_chunk


def _upsert_qdrant_shards(
    *,
    executor: concurrent.futures.Executor,
    clients: list[Any],
    targets: list[QdrantShardTarget],
    point_chunks_by_shard: dict[int, Iterable[list[Any]]],
) -> int:
    active_shards = list(point_chunks_by_shard)

    def upsert_shard(shard_index: int) -> int:
        client = clients[shard_index]
        collection_name = targets[shard_index].collection_name
        inserted = 0
        for point_chunk in point_chunks_by_shard[shard_index]:
            client.upsert(collection_name=collection_name, points=point_chunk)
            inserted += len(point_chunk)
        return inserted

    return sum(executor.map(upsert_shard, active_shards))


def _qdrant_model_value(payload: Any, key: str, default: Any = None) -> Any:
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _qdrant_status_text(value: Any) -> str:
    if value is None:
        return "missing"
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        value = enum_value
    if isinstance(value, dict):
        if value.get("ok") is not None:
            return "ok" if bool(value.get("ok")) else "error"
        value = value.get("status", value)
    return str(value).strip().lower()


def _wait_for_qdrant_index_ready(
    client: Any,
    collection_name: str,
    *,
    expected_vectors: int,
    timeout_seconds: float,
    poll_interval_seconds: float = 5.0,
    require_full_index: bool = False,
) -> dict[str, Any]:
    if timeout_seconds < 0:
        raise ValueError("WAVEMIND_QDRANT_INDEX_READY_TIMEOUT_SECONDS must be non-negative")
    if poll_interval_seconds < 0:
        raise ValueError("WAVEMIND_QDRANT_INDEX_READY_POLL_SECONDS must be non-negative")

    started = time.perf_counter()
    attempts = 0
    last: dict[str, Any] = {}
    while True:
        attempts += 1
        info = client.get_collection(collection_name=collection_name)
        points = int(_qdrant_model_value(info, "points_count", 0) or 0)
        indexed = int(_qdrant_model_value(info, "indexed_vectors_count", 0) or 0)
        collection_status = _qdrant_status_text(
            _qdrant_model_value(info, "status")
        )
        optimizer_status = _qdrant_status_text(
            _qdrant_model_value(info, "optimizer_status")
        )
        ready = (
            points >= int(expected_vectors)
            and (not require_full_index or indexed >= int(expected_vectors))
            and collection_status == "green"
            and optimizer_status == "ok"
        )
        elapsed = time.perf_counter() - started
        last = {
            "collection_name": collection_name,
            "expected_vectors": int(expected_vectors),
            "points_count": points,
            "indexed_vectors_count": indexed,
            "collection_status": collection_status,
            "optimizer_status": optimizer_status,
            "ready": ready,
            "attempts": attempts,
            "wait_ms": elapsed * 1000.0,
            "timeout_seconds": float(timeout_seconds),
            "poll_interval_seconds": float(poll_interval_seconds),
            "require_full_index": bool(require_full_index),
        }
        if ready or timeout_seconds <= 0:
            return last
        if elapsed >= timeout_seconds:
            raise TimeoutError(
                f"Qdrant collection {collection_name!r} did not become index-ready "
                f"within {timeout_seconds:g}s: points={points}, indexed={indexed}, "
                f"status={collection_status}, optimizer={optimizer_status}"
            )
        time.sleep(poll_interval_seconds)


def _pgvector_config_from_env() -> dict[str, Any]:
    storage_type = os.environ.get("WAVEMIND_PGVECTOR_STORAGE_TYPE", "vector").strip().lower()
    if storage_type not in {"vector", "halfvec"}:
        raise ValueError("WAVEMIND_PGVECTOR_STORAGE_TYPE must be vector or halfvec")
    insert_mode = os.environ.get("WAVEMIND_PGVECTOR_INSERT_MODE", "copy").strip().lower()
    if insert_mode not in {"copy", "upsert"}:
        raise ValueError("WAVEMIND_PGVECTOR_INSERT_MODE must be copy or upsert")
    index_type = os.environ.get("WAVEMIND_PGVECTOR_INDEX_TYPE", "hnsw").strip().lower()
    if index_type not in {"hnsw", "ivfflat"}:
        raise ValueError("WAVEMIND_PGVECTOR_INDEX_TYPE must be hnsw or ivfflat")
    return {
        "table": _safe_identifier(
            os.environ.get("WAVEMIND_PGVECTOR_TABLE", "wavemind_streaming_vectors"),
            "WAVEMIND_PGVECTOR_TABLE",
        ),
        "collection": os.environ.get("WAVEMIND_PGVECTOR_COLLECTION")
        or f"streaming_load_{time.time_ns()}",
        "storage_type": storage_type,
        "insert_mode": insert_mode,
        "index_type": index_type,
        "create_hnsw": _bool_env("WAVEMIND_PGVECTOR_CREATE_HNSW", True),
        "hnsw_m": _optional_int_env("WAVEMIND_PGVECTOR_HNSW_M"),
        "hnsw_ef_construction": _optional_int_env("WAVEMIND_PGVECTOR_HNSW_EF_CONSTRUCTION"),
        "ef_search": _optional_int_env("WAVEMIND_PGVECTOR_EF_SEARCH"),
        "ivfflat_lists": _optional_int_env("WAVEMIND_PGVECTOR_IVFFLAT_LISTS"),
        "ivfflat_probes": _optional_int_env("WAVEMIND_PGVECTOR_IVFFLAT_PROBES"),
        "exact": _bool_env("WAVEMIND_PGVECTOR_EXACT", False),
        "iterative_scan": os.environ.get("WAVEMIND_PGVECTOR_ITERATIVE_SCAN"),
        "max_scan_tuples": _optional_int_env("WAVEMIND_PGVECTOR_MAX_SCAN_TUPLES"),
        "scan_mem_multiplier": _optional_int_env("WAVEMIND_PGVECTOR_SCAN_MEM_MULTIPLIER"),
        "prewarm_index": _bool_env("WAVEMIND_PGVECTOR_PREWARM_INDEX", False),
        "keep_collection": _bool_env("WAVEMIND_PGVECTOR_KEEP_COLLECTION", False),
    }


def _pgvector_operator_class(storage_type: str) -> str:
    return "halfvec_cosine_ops" if storage_type == "halfvec" else "vector_cosine_ops"


def _pgvector_insert_batch(
    cursor: Any,
    *,
    table: str,
    collection: str,
    ids: np.ndarray,
    vectors: np.ndarray,
    storage_type: str,
    insert_mode: str,
) -> None:
    if len(ids) == 0:
        return
    if insert_mode == "copy":
        # A missing checkpoint after a committed COPY is safe to resume: the
        # uncheckpointed id range is replaced before it is copied again.
        cursor.execute(
            f"DELETE FROM {table} WHERE collection = %s AND memory_id BETWEEN %s AND %s",
            (collection, int(ids[0]), int(ids[-1])),
        )
        with cursor.copy(
            f"COPY {table} (collection, memory_id, embedding) FROM STDIN"
        ) as copy:
            for memory_id, vector in zip(ids, vectors):
                copy.write_row(
                    (collection, int(memory_id), _vector_literal(vector))
                )
        return

    insert_sql = (
        f"INSERT INTO {table} (collection, memory_id, embedding, updated_at) "
        f"VALUES (%s, %s, %s::{storage_type}, now()) "
        f"ON CONFLICT (collection, memory_id) "
        f"DO UPDATE SET embedding = EXCLUDED.embedding, updated_at = now()"
    )
    cursor.executemany(
        insert_sql,
        [
            (collection, int(memory_id), _vector_literal(vector))
            for memory_id, vector in zip(ids, vectors)
        ],
    )


def _qdrant_collection_config_from_env() -> dict[str, Any]:
    hnsw = _without_none(
        {
            "m": _optional_int_env("WAVEMIND_QDRANT_HNSW_M"),
            "ef_construct": _optional_int_env("WAVEMIND_QDRANT_HNSW_EF_CONSTRUCT"),
            "full_scan_threshold": _optional_int_env("WAVEMIND_QDRANT_HNSW_FULL_SCAN_THRESHOLD"),
            "max_indexing_threads": _optional_int_env("WAVEMIND_QDRANT_HNSW_MAX_INDEXING_THREADS"),
            "on_disk": _optional_bool_env("WAVEMIND_QDRANT_HNSW_ON_DISK"),
            "payload_m": _optional_int_env("WAVEMIND_QDRANT_HNSW_PAYLOAD_M"),
            "inline_storage": _optional_bool_env("WAVEMIND_QDRANT_HNSW_INLINE_STORAGE"),
        }
    )
    optimizers = _without_none(
        {
            "default_segment_number": _optional_int_env("WAVEMIND_QDRANT_OPTIMIZER_DEFAULT_SEGMENT_NUMBER"),
            "max_segment_size": _optional_int_env("WAVEMIND_QDRANT_OPTIMIZER_MAX_SEGMENT_SIZE"),
            "memmap_threshold": _optional_int_env("WAVEMIND_QDRANT_OPTIMIZER_MEMMAP_THRESHOLD"),
            "indexing_threshold": _optional_int_env("WAVEMIND_QDRANT_OPTIMIZER_INDEXING_THRESHOLD"),
            "flush_interval_sec": _optional_int_env("WAVEMIND_QDRANT_OPTIMIZER_FLUSH_INTERVAL_SEC"),
            "max_optimization_threads": _optional_int_env("WAVEMIND_QDRANT_OPTIMIZER_MAX_THREADS"),
        }
    )
    scalar_quantization = None
    if _bool_env("WAVEMIND_QDRANT_SCALAR_QUANTIZATION", False):
        quantile = float(
            os.environ.get("WAVEMIND_QDRANT_SCALAR_QUANTILE", "0.99")
        )
        if not 0.0 < quantile <= 1.0:
            raise ValueError("WAVEMIND_QDRANT_SCALAR_QUANTILE must be in (0, 1]")
        scalar_quantization = {
            "type": "int8",
            "quantile": quantile,
            "always_ram": _bool_env(
                "WAVEMIND_QDRANT_SCALAR_ALWAYS_RAM", True
            ),
        }
    return {
        "hnsw": hnsw,
        "optimizers": optimizers,
        "vector_on_disk": _optional_bool_env("WAVEMIND_QDRANT_VECTOR_ON_DISK"),
        "on_disk_payload": _optional_bool_env("WAVEMIND_QDRANT_ON_DISK_PAYLOAD"),
        "shard_number": _optional_int_env("WAVEMIND_QDRANT_SHARD_NUMBER"),
        "scalar_quantization": scalar_quantization,
    }


def _qdrant_deferred_indexing_config_from_env() -> dict[str, Any]:
    enabled = _bool_env("WAVEMIND_QDRANT_DEFER_INDEXING", False)
    deferred_threshold_kb = _positive_int_env(
        "WAVEMIND_QDRANT_DEFERRED_INDEXING_THRESHOLD_KB",
        1_000_000_000,
    )
    final_threshold_kb = _positive_int_env(
        "WAVEMIND_QDRANT_FINAL_INDEXING_THRESHOLD_KB",
        20_000,
    )
    if enabled and deferred_threshold_kb <= final_threshold_kb:
        raise ValueError(
            "WAVEMIND_QDRANT_DEFERRED_INDEXING_THRESHOLD_KB must be greater "
            "than WAVEMIND_QDRANT_FINAL_INDEXING_THRESHOLD_KB"
        )
    return {
        "enabled": enabled,
        "deferred_threshold_kb": deferred_threshold_kb,
        "final_threshold_kb": final_threshold_kb,
    }


@contextmanager
def _local_no_proxy(url: str):
    if not any(host in url for host in ("127.0.0.1", "localhost", "::1")):
        yield
        return
    original_no_proxy = os.environ.get("NO_PROXY")
    original_no_proxy_lower = os.environ.get("no_proxy")
    local_hosts = "127.0.0.1,localhost,::1"
    os.environ["NO_PROXY"] = (
        f"{original_no_proxy},{local_hosts}" if original_no_proxy else local_hosts
    )
    os.environ["no_proxy"] = (
        f"{original_no_proxy_lower},{local_hosts}" if original_no_proxy_lower else local_hosts
    )
    try:
        yield
    finally:
        if original_no_proxy is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = original_no_proxy
        if original_no_proxy_lower is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = original_no_proxy_lower


def choose_source_ids(count: int, query_count: int, seed: int) -> list[int]:
    if count <= 0:
        return []
    capped = min(int(query_count), int(count))
    rng = np.random.default_rng(seed + 4049)
    return [int(id) + 1 for id in rng.choice(count, size=capped, replace=False)]


def iter_vector_batches(
    *,
    count: int,
    dim: int,
    seed: int,
    batch_size: int,
    source_ids: Iterable[int],
) -> Iterable[tuple[np.ndarray, np.ndarray, dict[int, np.ndarray]]]:
    rng = np.random.default_rng(seed)
    source_set = set(int(id) for id in source_ids)
    for start in range(0, count, batch_size):
        size = min(batch_size, count - start)
        ids = np.arange(start + 1, start + size + 1, dtype=np.int64)
        vectors = _normalize(rng.normal(size=(size, dim)).astype(np.float32))
        captured: dict[int, np.ndarray] = {}
        end = start + size
        for source_id in source_set:
            if start < source_id <= end:
                captured[source_id] = vectors[source_id - start - 1].copy()
        yield ids, vectors, captured


def make_queries(
    *,
    source_ids: list[int],
    source_vectors: dict[int, np.ndarray],
    seed: int,
    noise: float,
) -> list[tuple[int, np.ndarray]]:
    missing = [id for id in source_ids if id not in source_vectors]
    if missing:
        sample = ", ".join(str(id) for id in missing[:5])
        raise RuntimeError(f"Missing source vectors for query ids: {sample}")
    rng = np.random.default_rng(seed + 1009)
    queries = []
    for source_id in source_ids:
        source = source_vectors[source_id]
        perturbation = rng.normal(scale=noise, size=source.shape[0]).astype(np.float32)
        queries.append((source_id, _normalize_one(source + perturbation)))
    return queries


def training_sample(*, dim: int, seed: int, sample_size: int) -> np.ndarray:
    rng = np.random.default_rng(seed + 7919)
    return _normalize(rng.normal(size=(int(sample_size), int(dim))).astype(np.float32))


def _metrics_from_hits(
    *,
    engine: str,
    vector_count: int,
    dim: int,
    batch_size: int,
    top_k: int,
    build_ms: float,
    query_rows: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latencies = [float(row["latency_ms"]) for row in query_rows]
    target_hits = [bool(row["target_hit"]) for row in query_rows]
    target_hit_at_1 = [bool(row["target_hit_at_1"]) for row in query_rows]
    result = {
        "engine": engine,
        "vectors": int(vector_count),
        "vector_dim": int(dim),
        "batch_size": int(batch_size),
        "recall_at_k": statistics.mean(target_hits) if target_hits else 0.0,
        "target_recall_at_k": statistics.mean(target_hits) if target_hits else 0.0,
        "target_recall_at_1": statistics.mean(target_hit_at_1) if target_hit_at_1 else 0.0,
        "avg_latency_ms": statistics.mean(latencies) if latencies else 0.0,
        "p50_latency_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_latency_ms": _percentile(latencies, 95),
        "p99_latency_ms": _percentile(latencies, 99),
        "max_latency_ms": max(latencies) if latencies else 0.0,
        "build_ms": float(build_ms),
        "queries": len(query_rows),
        "recall_definition": "source vector id appears in top_k for a noisy copy of that vector",
    }
    if extra:
        result.update(extra)
    return result


def skipped_result(engine: str, reason: str) -> dict[str, Any]:
    return {
        "engine": engine,
        "skipped": True,
        "reason": reason,
    }


def _bytes_to_gb(value: float) -> float:
    return float(value) / float(1024**3)


def _round_gb(value: float) -> float:
    return round(float(value), 3)


def _disk_usage_path(path: Path) -> Path:
    current = path.resolve()
    while not current.exists():
        parent = current.parent
        if parent == current:
            break
        current = parent
    return current


def _disk_free_gb(path: Path) -> float:
    try:
        return _bytes_to_gb(float(shutil.disk_usage(_disk_usage_path(path)).free))
    except OSError:
        return 0.0


def _env_ready(names: Iterable[str]) -> tuple[bool, list[str]]:
    missing = [name for name in names if not os.environ.get(name)]
    return not missing, missing


def _streaming_plan_row(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
    engine: str,
    output_path: Path | None,
    planned_result_output_path: Path | None,
    target_recall: float,
    target_p99_ms: float,
    target_qps: float,
    replicas: int,
    autoscaling_max_replicas: int,
    capacity_headroom: float,
    memory_payload_kb: float,
    vector_dtype_bytes: int,
    disk_free_gb: float,
    safety_factor: float,
    runner_storage_root: Path | None,
) -> dict[str, Any]:
    key = engine.lower()
    canonical = {
        "numpy-streaming": "WaveMind numpy-streaming",
        "faiss-persisted": "WaveMind faiss-persisted streaming",
        "faiss-ivfpq-persisted": "WaveMind faiss-ivfpq-persisted streaming",
        "qdrant-service": "Qdrant service streaming",
        "qdrant-sharded": "Qdrant sharded service streaming",
        "qdrant-sharded-service": "Qdrant sharded service streaming",
        "qdrant-sharded-streaming": "Qdrant sharded service streaming",
        "pgvector-service": "WaveMind pgvector streaming",
        "pgvector-streaming": "WaveMind pgvector streaming",
    }.get(key, engine)
    vector_bytes = int(count) * int(dim) * int(vector_dtype_bytes)
    payload_bytes = int(count) * float(memory_payload_kb) * 1024.0
    source_vector_bytes = min(int(query_count), int(count)) * int(dim) * int(vector_dtype_bytes)
    batch_bytes = min(int(batch_size), int(count)) * int(dim) * int(vector_dtype_bytes)
    blockers: list[str] = []
    required_env: list[str] = []
    module_requirements: list[str] = []
    index_bytes = vector_bytes
    transient_bytes = batch_bytes + source_vector_bytes
    index_mode = "full matrix"
    command_env: dict[str, str] = {}
    runner_root = runner_storage_root or Path("state")
    runner_root_arg = str(runner_root).replace("\\", "/")

    if key == "numpy-streaming":
        index_mode = "full float32 matrix; smoke/testing only at large N"
        if count > 1_000_000:
            blockers.append("numpy_streaming_not_large_n_production_path")
    elif key == "faiss-persisted":
        module_requirements = ["faiss"]
        required_env = ["WAVEMIND_FAISS_PATH"]
        index_bytes = vector_bytes + int(count) * 8
        index_mode = "persisted FAISS flat index plus int64 ids"
        command_env = {"WAVEMIND_FAISS_PATH": f"{runner_root_arg}/wavemind-faiss-50m.faiss"}
    elif key == "faiss-ivfpq-persisted":
        module_requirements = ["faiss"]
        required_env = ["WAVEMIND_FAISS_IVFPQ_PATH"]
        nlist = _int_env("WAVEMIND_FAISS_IVFPQ_NLIST", 4096)
        pq_m = _int_env("WAVEMIND_FAISS_IVFPQ_M", 16)
        nbits = _int_env("WAVEMIND_FAISS_IVFPQ_NBITS", 8)
        nprobe = _int_env("WAVEMIND_FAISS_IVFPQ_NPROBE", min(1024, nlist))
        training_size = _int_env("WAVEMIND_FAISS_IVFPQ_TRAINING_SIZE", max(200_000, nlist * 40))
        if dim % pq_m != 0:
            blockers.append(f"vector_dim_not_divisible_by_ivfpq_m:{dim}%{pq_m}")
        code_bytes = int(count) * int(math.ceil((pq_m * nbits) / 8.0))
        id_bytes = int(count) * 8
        centroid_bytes = int(nlist) * int(dim) * int(vector_dtype_bytes)
        training_bytes = int(training_size) * int(dim) * int(vector_dtype_bytes)
        index_bytes = code_bytes + id_bytes + centroid_bytes
        transient_bytes += training_bytes
        index_mode = "persisted FAISS IVF-PQ compressed codes plus int64 ids"
        command_env = {
            "WAVEMIND_FAISS_IVFPQ_PATH": f"{runner_root_arg}/wavemind-faiss-ivfpq-50m.faiss",
            "WAVEMIND_FAISS_IVFPQ_NLIST": str(nlist),
            "WAVEMIND_FAISS_IVFPQ_M": str(pq_m),
            "WAVEMIND_FAISS_IVFPQ_NBITS": str(nbits),
            "WAVEMIND_FAISS_IVFPQ_NPROBE": str(nprobe),
            "WAVEMIND_FAISS_IVFPQ_NPROBE_SWEEP": "64,128,256,512,1024",
            "WAVEMIND_FAISS_IVFPQ_TRAINING_SIZE": str(training_size),
            "WAVEMIND_FAISS_CHECKPOINT_INTERVAL_BATCHES": "5",
        }
    elif key == "qdrant-service":
        module_requirements = ["qdrant_client"]
        required_env = ["WAVEMIND_QDRANT_URL"]
        index_bytes = 0
        index_mode = "remote Qdrant service storage; local runner stores only generated batches"
        command_env = {
            "WAVEMIND_QDRANT_URL": "http://qdrant.example:6333",
            "WAVEMIND_QDRANT_PREFER_GRPC": "1",
            "WAVEMIND_QDRANT_GRPC_PORT": "6334",
            "WAVEMIND_QDRANT_VECTOR_ON_DISK": "1",
            "WAVEMIND_QDRANT_HNSW_ON_DISK": "0",
            "WAVEMIND_QDRANT_SCALAR_QUANTIZATION": "1",
            "WAVEMIND_QDRANT_SCALAR_QUANTILE": "0.99",
            "WAVEMIND_QDRANT_SCALAR_ALWAYS_RAM": "1",
            "WAVEMIND_QDRANT_QUANTIZATION_RESCORE": "0",
            "WAVEMIND_QDRANT_INDEX_READY_TIMEOUT_SECONDS": "1800",
            "WAVEMIND_QDRANT_REQUIRE_FULL_INDEX": "1",
            "WAVEMIND_QDRANT_DEFER_INDEXING": "1",
            "WAVEMIND_QDRANT_DEFERRED_INDEXING_THRESHOLD_KB": "1000000000",
            "WAVEMIND_QDRANT_FINAL_INDEXING_THRESHOLD_KB": "20000",
        }
    elif key in {"qdrant-sharded", "qdrant-sharded-service", "qdrant-sharded-streaming"}:
        module_requirements = ["qdrant_client"]
        required_env = ["WAVEMIND_QDRANT_URLS"]
        index_bytes = 0
        shard_count = max(2, _int_env("WAVEMIND_QDRANT_SHARD_COUNT", 4))
        index_mode = (
            "remote horizontally sharded Qdrant storage; local runner routes ids "
            "across service URLs and fanout-merges top-k"
        )
        command_env = {
            "WAVEMIND_QDRANT_URLS": ",".join(
                f"http://qdrant-{index}.example:6333" for index in range(shard_count)
            ),
            "WAVEMIND_QDRANT_COLLECTION_PREFIX": "wavemind_streaming_load_10m",
            "WAVEMIND_QDRANT_UPSERT_BATCH_SIZE": "2000",
            "WAVEMIND_QDRANT_FANOUT_WORKERS": str(shard_count),
            "WAVEMIND_QDRANT_PREFER_GRPC": "1",
            "WAVEMIND_QDRANT_GRPC_PORT": "6334",
            "WAVEMIND_QDRANT_QUERY_TIMEOUT_SECONDS": "60",
            "WAVEMIND_QDRANT_WAIT_AFTER_BUILD_SECONDS": "30",
            "WAVEMIND_QDRANT_WARMUP_QUERIES": "100",
            "WAVEMIND_QDRANT_VECTOR_ON_DISK": "1",
            "WAVEMIND_QDRANT_HNSW_ON_DISK": "0",
            "WAVEMIND_QDRANT_SCALAR_QUANTIZATION": "1",
            "WAVEMIND_QDRANT_SCALAR_QUANTILE": "0.99",
            "WAVEMIND_QDRANT_SCALAR_ALWAYS_RAM": "1",
            "WAVEMIND_QDRANT_QUANTIZATION_RESCORE": "0",
            "WAVEMIND_QDRANT_INDEX_READY_TIMEOUT_SECONDS": "1800",
            "WAVEMIND_QDRANT_REQUIRE_FULL_INDEX": "1",
            "WAVEMIND_QDRANT_DEFER_INDEXING": "1",
            "WAVEMIND_QDRANT_DEFERRED_INDEXING_THRESHOLD_KB": "1000000000",
            "WAVEMIND_QDRANT_FINAL_INDEXING_THRESHOLD_KB": "20000",
        }
    elif key in {"pgvector", "pgvector-service", "pgvector-streaming"}:
        module_requirements = ["psycopg"]
        required_env = ["WAVEMIND_PGVECTOR_DSN"]
        index_bytes = 0
        index_mode = "remote PostgreSQL/pgvector storage; local runner stores only generated batches"
        command_env = {
            "WAVEMIND_PGVECTOR_DSN": "postgresql://user:password@postgres.example:5432/wavemind",
            "WAVEMIND_PGVECTOR_CREATE_HNSW": "1",
            "WAVEMIND_PGVECTOR_STORAGE_TYPE": "halfvec",
            "WAVEMIND_PGVECTOR_INSERT_MODE": "copy",
            "WAVEMIND_PGVECTOR_INDEX_TYPE": "ivfflat",
            "WAVEMIND_PGVECTOR_IVFFLAT_LISTS": "4096",
            "WAVEMIND_PGVECTOR_IVFFLAT_PROBES": "256",
            "WAVEMIND_PGVECTOR_PREWARM_INDEX": "1",
        }
    else:
        raise ValueError(f"Unknown engine: {engine}")

    module_status = {
        name: _module_available(name)
        for name in module_requirements
        if name in module_requirements
    }
    missing_modules = [name for name, ok in module_status.items() if not ok]
    if missing_modules:
        blockers.extend(f"missing_module:{name}" for name in missing_modules)
    env_ok, missing_env = _env_ready(required_env)
    if not env_ok:
        blockers.extend(f"missing_env:{name}" for name in missing_env)

    required_local_free_gb = _bytes_to_gb((index_bytes + transient_bytes) * safety_factor)
    if disk_free_gb < required_local_free_gb:
        blockers.append("insufficient_local_disk_for_index_and_transient_batches")

    command_output_path = planned_result_output_path or output_path or Path("benchmarks/production_streaming_load_results.json")
    checkpoint_slug = re.sub(r"[^a-z0-9]+", "-", key).strip("-") or "streaming"
    checkpoint_path = runner_root / f"{checkpoint_slug}-{int(count)}.checkpoint.json"
    checkpoint_arg = str(checkpoint_path).replace("\\", "/")
    command_parts = [
        "python",
        "benchmarks/production_streaming_load_benchmark.py",
        "--sizes",
        str(int(count)),
        "--dim",
        str(int(dim)),
        "--queries",
        str(int(query_count)),
        "--top-k",
        str(int(top_k)),
        "--seed",
        str(int(seed)),
        "--noise",
        str(float(noise)),
        "--batch-size",
        str(int(batch_size)),
        "--engines",
        engine,
        "--target-recall",
        str(float(target_recall)),
        "--target-p99-ms",
        str(float(target_p99_ms)),
        "--target-qps",
        str(float(target_qps)),
        "--replicas",
        str(int(replicas)),
        "--autoscaling-max-replicas",
        str(int(autoscaling_max_replicas)),
        "--capacity-headroom",
        str(float(capacity_headroom)),
        "--output",
        str(command_output_path),
        "--checkpoint-path",
        checkpoint_arg,
    ]
    return {
        "engine": canonical,
        "vectors": int(count),
        "vector_dim": int(dim),
        "queries": min(int(query_count), int(count)),
        "top_k": int(top_k),
        "batch_size": int(batch_size),
        "index_mode": index_mode,
        "estimated_index_gb": _round_gb(_bytes_to_gb(index_bytes)),
        "estimated_transient_runner_gb": _round_gb(_bytes_to_gb(transient_bytes)),
        "estimated_payload_storage_gb": _round_gb(_bytes_to_gb(payload_bytes)),
        "estimated_float_vector_storage_gb": _round_gb(_bytes_to_gb(vector_bytes)),
        "estimated_application_storage_gb": _round_gb(_bytes_to_gb(vector_bytes + payload_bytes)),
        "required_local_free_gb": _round_gb(required_local_free_gb),
        "disk_free_gb": round(float(disk_free_gb), 3),
        "runner_storage_root": runner_root_arg,
        "disk_free_path": str(_disk_usage_path(runner_root)).replace("\\", "/"),
        "safety_factor": float(safety_factor),
        "module_requirements": module_status,
        "required_env": required_env,
        "missing_env": missing_env,
        "command_env": command_env,
        "checkpoint_path": checkpoint_arg,
        "resume_mode": "batch checkpoint; safe to rerun after interrupted ingest",
        "command": " ".join(command_parts),
        "status": "ready" if not blockers else "action_required",
        "blockers": blockers,
        "claim_boundary": "preflight only; this is not a completed latency or recall benchmark",
    }


def plan_streaming_load(
    *,
    sizes: Iterable[int],
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
    engines: Iterable[str],
    output_path: Path | None = None,
    planned_result_output_path: Path | None = None,
    target_recall: float = 0.95,
    target_p99_ms: float = 100.0,
    target_qps: float = 100.0,
    replicas: int = 3,
    autoscaling_max_replicas: int = 24,
    capacity_headroom: float = 0.70,
    memory_payload_kb: float = 2.0,
    vector_dtype_bytes: int = 4,
    safety_factor: float = 1.25,
    runner_storage_root: Path | None = None,
    disk_free_gb_override: float | None = None,
) -> dict[str, Any]:
    preflight_payload = preflight(output_path=output_path)
    disk_free_gb = (
        float(disk_free_gb_override)
        if disk_free_gb_override is not None
        else _disk_free_gb(runner_storage_root)
        if runner_storage_root is not None
        else float(preflight_payload.get("disk", {}).get("free_gb", 0.0))
    )
    effective_runner_root = runner_storage_root or Path("state")
    disk_free_path = _disk_usage_path(effective_runner_root)
    size_list = [int(size) for size in sizes]
    rows = [
        _streaming_plan_row(
            count=size,
            dim=dim,
            query_count=query_count,
            top_k=top_k,
            seed=seed,
            noise=noise,
            batch_size=batch_size,
            engine=engine,
            output_path=output_path,
            planned_result_output_path=planned_result_output_path,
            target_recall=target_recall,
            target_p99_ms=target_p99_ms,
            target_qps=target_qps,
            replicas=replicas,
            autoscaling_max_replicas=autoscaling_max_replicas,
            capacity_headroom=capacity_headroom,
            memory_payload_kb=memory_payload_kb,
            vector_dtype_bytes=vector_dtype_bytes,
            disk_free_gb=disk_free_gb,
            safety_factor=safety_factor,
            runner_storage_root=runner_storage_root,
        )
        for size in size_list
        for engine in engines
    ]
    return {
        "schema": "wavemind.production_streaming_load_plan.v1",
        "status": "ready" if rows and all(row["status"] == "ready" for row in rows) else "action_required",
        "scenario": {
            "name": "production_streaming_load_plan",
            "description": "Plan-only preflight for large-N streaming load runs. It estimates local index/transient storage, application storage, required environment, and the exact reproduction command without generating vectors.",
            "sizes": size_list,
            "vector_dim": int(dim),
            "queries_per_size": int(query_count),
            "top_k": int(top_k),
            "seed": int(seed),
            "noise": float(noise),
            "batch_size": int(batch_size),
            "engines": list(engines),
            "target_recall_at_k": float(target_recall),
            "target_p99_ms": float(target_p99_ms),
            "target_qps": float(target_qps),
            "replicas": int(replicas),
            "autoscaling_max_replicas": int(autoscaling_max_replicas),
            "capacity_headroom": float(capacity_headroom),
            "plan_only": True,
            "runner_storage_root": str(effective_runner_root).replace("\\", "/"),
            "disk_free_path": str(disk_free_path).replace("\\", "/"),
            "disk_free_gb": round(float(disk_free_gb), 3),
        },
        "preflight": preflight_payload,
        "plans": rows,
    }


def artifact_index_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return path.name


def run_numpy_streaming(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
) -> dict[str, Any]:
    source_ids = choose_source_ids(count, query_count, seed)
    source_vectors: dict[int, np.ndarray] = {}
    matrix_batches: list[np.ndarray] = []
    id_batches: list[np.ndarray] = []
    started = time.perf_counter()
    for ids, vectors, captured in iter_vector_batches(
        count=count,
        dim=dim,
        seed=seed + count,
        batch_size=batch_size,
        source_ids=source_ids,
    ):
        id_batches.append(ids)
        matrix_batches.append(vectors)
        source_vectors.update(captured)
    ids = np.concatenate(id_batches) if id_batches else np.zeros((0,), dtype=np.int64)
    matrix = np.vstack(matrix_batches).astype(np.float32) if matrix_batches else np.zeros((0, dim), dtype=np.float32)
    build_ms = (time.perf_counter() - started) * 1000.0
    queries = make_queries(source_ids=source_ids, source_vectors=source_vectors, seed=seed + count, noise=noise)
    rows: list[dict[str, Any]] = []
    k = min(top_k, len(ids))
    for source_id, query in queries:
        started = time.perf_counter()
        scores = matrix @ query
        if k <= 0:
            top_ids = np.zeros((0,), dtype=np.int64)
        else:
            positions = np.argpartition(scores, -k)[-k:]
            positions = positions[np.argsort(scores[positions])[::-1]]
            top_ids = ids[positions]
        latency_ms = (time.perf_counter() - started) * 1000.0
        top = [int(id) for id in top_ids]
        rows.append(
            {
                "source_id": int(source_id),
                "target_hit": int(source_id) in top,
                "target_hit_at_1": bool(top and top[0] == int(source_id)),
                "latency_ms": latency_ms,
            }
        )
    return _metrics_from_hits(
        engine="WaveMind numpy-streaming",
        vector_count=count,
        dim=dim,
        batch_size=batch_size,
        top_k=top_k,
        build_ms=build_ms,
        query_rows=rows,
        extra={"memory_mode": "stores full matrix; smoke/testing only"},
    )


def run_faiss_streaming(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
) -> dict[str, Any]:
    path = os.environ.get("WAVEMIND_FAISS_PATH")
    if not path:
        return skipped_result("WaveMind faiss-persisted streaming", "Set WAVEMIND_FAISS_PATH to run streaming FAISS")
    try:
        import faiss
    except ImportError as exc:
        return skipped_result("WaveMind faiss-persisted streaming", f"Install faiss-cpu: {exc}")
    output = Path(path).expanduser()
    checkpoint_path = _checkpoint_path_from_env()
    signature = _checkpoint_signature(
        engine="WaveMind faiss-persisted streaming",
        count=count,
        dim=dim,
        query_count=query_count,
        top_k=top_k,
        seed=seed,
        noise=noise,
        batch_size=batch_size,
        extra={"index_path": str(output)},
    )
    try:
        checkpoint = _load_checkpoint(checkpoint_path, signature)
    except ValueError as exc:
        return skipped_result("WaveMind faiss-persisted streaming", str(exc))
    completed_batches = _checkpoint_completed_batches(checkpoint)
    if completed_batches and not output.exists():
        return skipped_result(
            "WaveMind faiss-persisted streaming",
            f"checkpoint {checkpoint_path} exists but persisted FAISS index {output} is missing",
        )
    source_ids = choose_source_ids(count, query_count, seed)
    source_vectors: dict[int, np.ndarray] = _checkpoint_source_vectors(checkpoint)
    index = (
        faiss.read_index(str(output))
        if completed_batches
        else faiss.IndexIDMap2(faiss.IndexFlatIP(int(dim)))
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    for ids, vectors, captured in iter_vector_batches(
        count=count,
        dim=dim,
        seed=seed + count,
        batch_size=batch_size,
        source_ids=source_ids,
    ):
        batch_start = int(ids[0]) if len(ids) else 0
        if batch_start not in completed_batches:
            index.add_with_ids(vectors.astype(np.float32), ids.astype(np.int64))
            if checkpoint_path is not None:
                faiss.write_index(index, str(output))
        source_vectors.update(captured)
        _record_checkpoint_batch(
            path=checkpoint_path,
            payload=checkpoint,
            batch_start=batch_start,
            captured=captured,
        )
        completed_batches.add(batch_start)
    faiss.write_index(index, str(output))
    build_ms = (time.perf_counter() - started) * 1000.0
    queries = make_queries(source_ids=source_ids, source_vectors=source_vectors, seed=seed + count, noise=noise)
    rows: list[dict[str, Any]] = []
    for source_id, query in queries:
        started = time.perf_counter()
        _, labels = index.search(query.reshape(1, -1).astype(np.float32), top_k)
        latency_ms = (time.perf_counter() - started) * 1000.0
        top = [int(id) for id in labels[0] if int(id) >= 0]
        rows.append(
            {
                "source_id": int(source_id),
                "target_hit": int(source_id) in top,
                "target_hit_at_1": bool(top and top[0] == int(source_id)),
                "latency_ms": latency_ms,
            }
        )
    return _metrics_from_hits(
        engine="WaveMind faiss-persisted streaming",
        vector_count=count,
        dim=dim,
        batch_size=batch_size,
        top_k=top_k,
        build_ms=build_ms,
        query_rows=rows,
        extra={
            "index_path": artifact_index_path(output),
            "memory_mode": "streaming add_with_ids; query source vectors only",
            **_checkpoint_extra(checkpoint_path, checkpoint, completed_batches),
        },
    )


def run_faiss_ivfpq_streaming(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
    target_recall: float = 0.95,
    target_p99_ms: float = 100.0,
) -> dict[str, Any]:
    path = os.environ.get("WAVEMIND_FAISS_IVFPQ_PATH") or os.environ.get("WAVEMIND_FAISS_PATH")
    engine = "WaveMind faiss-ivfpq-persisted streaming"
    if not path:
        return skipped_result(engine, "Set WAVEMIND_FAISS_IVFPQ_PATH to run streaming FAISS IVF-PQ")
    try:
        import faiss
    except ImportError as exc:
        return skipped_result(engine, f"Install faiss-cpu: {exc}")

    nlist = _int_env("WAVEMIND_FAISS_IVFPQ_NLIST", 4096)
    pq_m = _int_env("WAVEMIND_FAISS_IVFPQ_M", 16)
    nbits = _int_env("WAVEMIND_FAISS_IVFPQ_NBITS", 8)
    nprobe = _int_env("WAVEMIND_FAISS_IVFPQ_NPROBE", min(64, nlist))
    training_size = _int_env("WAVEMIND_FAISS_IVFPQ_TRAINING_SIZE", max(100_000, nlist * 40))
    try:
        checkpoint_interval_batches = _positive_int_env(
            "WAVEMIND_FAISS_CHECKPOINT_INTERVAL_BATCHES",
            1,
        )
    except ValueError as exc:
        return skipped_result(engine, str(exc))
    try:
        nprobe_candidates = _positive_int_list_env(
            "WAVEMIND_FAISS_IVFPQ_NPROBE_SWEEP",
            [nprobe],
        )
    except ValueError as exc:
        return skipped_result(engine, str(exc))
    if any(candidate > nlist for candidate in nprobe_candidates):
        return skipped_result(
            engine,
            "WAVEMIND_FAISS_IVFPQ_NPROBE_SWEEP values must not exceed nlist",
        )

    if dim % pq_m != 0:
        return skipped_result(engine, f"vector dim {dim} must be divisible by WAVEMIND_FAISS_IVFPQ_M={pq_m}")
    if nlist <= 0 or pq_m <= 0 or nbits <= 0:
        return skipped_result(engine, "IVF-PQ parameters nlist, M, and nbits must be positive")

    output = Path(path).expanduser()
    checkpoint_path = _checkpoint_path_from_env()
    signature = _checkpoint_signature(
        engine=engine,
        count=count,
        dim=dim,
        query_count=query_count,
        top_k=top_k,
        seed=seed,
        noise=noise,
        batch_size=batch_size,
        extra={
            "index_path": str(output),
            "nlist": int(nlist),
            "pq_m": int(pq_m),
            "nbits": int(nbits),
            "training_size": int(training_size),
        },
    )
    try:
        checkpoint = _load_faiss_ivfpq_checkpoint(
            checkpoint_path,
            signature,
            legacy_nprobe=nprobe,
        )
    except ValueError as exc:
        return skipped_result(engine, str(exc))
    completed_batches = _checkpoint_completed_batches(checkpoint)
    checkpoint_metadata = checkpoint.setdefault("metadata", {})
    snapshot_value = checkpoint_metadata.get("faiss_snapshot_path")
    snapshot_path = (
        Path(str(snapshot_value)).expanduser() if snapshot_value else output
    )
    if completed_batches and not snapshot_path.exists():
        return skipped_result(
            engine,
            f"checkpoint {checkpoint_path} exists but persisted FAISS IVF-PQ snapshot {snapshot_path} is missing",
        )
    source_ids = choose_source_ids(count, query_count, seed)
    source_vectors: dict[int, np.ndarray] = _checkpoint_source_vectors(checkpoint)
    if completed_batches:
        index = faiss.read_index(str(snapshot_path))
        expected_ntotal = sum(
            min(int(batch_size), int(count) - (int(batch_start) - 1))
            for batch_start in completed_batches
            if 1 <= int(batch_start) <= int(count)
        )
        if int(index.ntotal) != int(expected_ntotal):
            return skipped_result(
                engine,
                f"checkpoint/index mismatch: snapshot has {int(index.ntotal)} vectors, "
                f"checkpoint describes {int(expected_ntotal)}",
            )
    else:
        quantizer = faiss.IndexFlatIP(int(dim))
        index = faiss.IndexIVFPQ(
            quantizer,
            int(dim),
            int(nlist),
            int(pq_m),
            int(nbits),
            faiss.METRIC_INNER_PRODUCT,
        )
    index.nprobe = int(nprobe_candidates[0])
    output.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    if not completed_batches:
        sample = training_sample(dim=dim, seed=seed + count, sample_size=training_size)
        index.train(sample)
    pending_checkpoint_batches: list[tuple[int, dict[int, np.ndarray]]] = []
    checkpoint_write_count = 0

    def persist_checkpoint(*, final: bool) -> None:
        nonlocal checkpoint_write_count, snapshot_path
        if checkpoint_path is None:
            return
        target = (
            output
            if final
            else output.with_name(f"{output.name}.checkpoint-{int(index.ntotal)}")
        )
        temp = target.with_name(f"{target.name}.tmp")
        faiss.write_index(index, str(temp))
        temp.replace(target)
        previous_snapshot = snapshot_path if completed_batches else None
        for pending_start, pending_captured in pending_checkpoint_batches:
            _record_checkpoint_batch(
                path=None,
                payload=checkpoint,
                batch_start=pending_start,
                captured=pending_captured,
            )
            completed_batches.add(int(pending_start))
        pending_checkpoint_batches.clear()
        checkpoint_metadata["faiss_snapshot_path"] = str(target)
        checkpoint_metadata["faiss_snapshot_ntotal"] = int(index.ntotal)
        checkpoint_metadata["faiss_checkpoint_interval_batches"] = int(
            checkpoint_interval_batches
        )
        _write_checkpoint(checkpoint_path, checkpoint)
        checkpoint_write_count += 1
        if (
            previous_snapshot is not None
            and previous_snapshot != target
            and previous_snapshot.exists()
        ):
            previous_snapshot.unlink()
        snapshot_path = target

    complete_resume = _checkpoint_complete_for_run(
        checkpoint,
        count=count,
        batch_size=batch_size,
        source_ids=source_ids,
    )
    if not complete_resume:
        for ids, vectors, captured in iter_vector_batches(
            count=count,
            dim=dim,
            seed=seed + count,
            batch_size=batch_size,
            source_ids=source_ids,
        ):
            batch_start = int(ids[0]) if len(ids) else 0
            if batch_start in completed_batches:
                source_vectors.update(captured)
                continue
            index.add_with_ids(vectors.astype(np.float32), ids.astype(np.int64))
            source_vectors.update(captured)
            pending_checkpoint_batches.append((batch_start, captured))
            if (
                checkpoint_path is not None
                and len(pending_checkpoint_batches) >= checkpoint_interval_batches
            ):
                persist_checkpoint(final=False)
    if checkpoint_path is not None:
        persist_checkpoint(final=True)
    else:
        faiss.write_index(index, str(output))
    build_ms = (time.perf_counter() - started) * 1000.0

    queries = make_queries(source_ids=source_ids, source_vectors=source_vectors, seed=seed + count, noise=noise)
    measured: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    selection_reason = ""
    for candidate in nprobe_candidates:
        index.nprobe = int(candidate)
        rows: list[dict[str, Any]] = []
        for source_id, query in queries:
            query_started = time.perf_counter()
            _, labels = index.search(query.reshape(1, -1).astype(np.float32), top_k)
            latency_ms = (time.perf_counter() - query_started) * 1000.0
            top = [int(id) for id in labels[0] if int(id) >= 0]
            rows.append(
                {
                    "source_id": int(source_id),
                    "target_hit": int(source_id) in top,
                    "target_hit_at_1": bool(top and top[0] == int(source_id)),
                    "latency_ms": latency_ms,
                }
            )
        candidate_result = _metrics_from_hits(
            engine=engine,
            vector_count=count,
            dim=dim,
            batch_size=batch_size,
            top_k=top_k,
            build_ms=build_ms,
            query_rows=rows,
            extra={"ivfpq_nprobe": int(candidate)},
        )
        measured.append(candidate_result)
        if (
            float(candidate_result["recall_at_k"]) >= float(target_recall)
            and float(candidate_result["p99_latency_ms"]) <= float(target_p99_ms)
        ):
            selected = candidate_result
            selection_reason = "first_candidate_meeting_recall_and_p99"
            break
    if selected is None:
        selected = max(
            measured,
            key=lambda row: (
                float(row["recall_at_k"]),
                -float(row["p99_latency_ms"]),
            ),
        )
        selection_reason = "best_recall_then_latency_no_candidate_met_both_targets"
    selected_nprobe = int(selected["ivfpq_nprobe"])
    index.nprobe = selected_nprobe
    selected.update(
        {
            "index_path": artifact_index_path(output),
            "memory_mode": "streaming IVF-PQ; compressed codes plus query source vectors only",
            "faiss_index": "IndexIVFPQ",
            "ivfpq_nlist": int(nlist),
            "ivfpq_m": int(pq_m),
            "ivfpq_nbits": int(nbits),
            "ivfpq_nprobe": selected_nprobe,
            "ivfpq_nprobe_candidates": nprobe_candidates,
            "ivfpq_nprobe_selection_reason": selection_reason,
            "ivfpq_nprobe_target_recall": float(target_recall),
            "ivfpq_nprobe_target_p99_ms": float(target_p99_ms),
            "ivfpq_nprobe_sweep": [
                {
                    "nprobe": int(row["ivfpq_nprobe"]),
                    "recall_at_k": float(row["recall_at_k"]),
                    "recall_at_1": float(row["target_recall_at_1"]),
                    "avg_latency_ms": float(row["avg_latency_ms"]),
                    "p95_latency_ms": float(row["p95_latency_ms"]),
                    "p99_latency_ms": float(row["p99_latency_ms"]),
                }
                for row in measured
            ],
            "ivfpq_training_size": int(training_size),
            "faiss_checkpoint_interval_batches": int(checkpoint_interval_batches),
            "faiss_checkpoint_write_count": int(checkpoint_write_count),
            "faiss_checkpoint_complete_resume": bool(complete_resume),
            "compression_note": "adaptive approximate target-recall sweep; selected nprobe is the lowest measured candidate meeting recall and p99 when available",
            **_checkpoint_extra(checkpoint_path, checkpoint, completed_batches),
        }
    )
    return selected


def run_qdrant_streaming(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
) -> dict[str, Any]:
    url = os.environ.get("WAVEMIND_QDRANT_URL")
    if not url:
        return skipped_result("Qdrant service streaming", "Set WAVEMIND_QDRANT_URL to run streaming Qdrant")
    try:
        upsert_batch_size = _positive_int_env("WAVEMIND_QDRANT_UPSERT_BATCH_SIZE", 5000)
        upsert_workers = _positive_int_env("WAVEMIND_QDRANT_UPSERT_WORKERS", 1)
    except ValueError as exc:
        return skipped_result("Qdrant service streaming", str(exc))
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import (
            Distance,
            HnswConfigDiff,
            OptimizersConfigDiff,
            PointStruct,
            QuantizationSearchParams,
            ScalarQuantization,
            ScalarQuantizationConfig,
            ScalarType,
            SearchParams,
            VectorParams,
        )
    except ImportError as exc:
        return skipped_result("Qdrant service streaming", f"Install qdrant-client: {exc}")

    collection_config = _qdrant_collection_config_from_env()
    deferred_indexing = _qdrant_deferred_indexing_config_from_env()
    checkpoint_path = _checkpoint_path_from_env()
    signature = _checkpoint_signature(
        engine="Qdrant service streaming",
        count=count,
        dim=dim,
        query_count=query_count,
        top_k=top_k,
        seed=seed,
        noise=noise,
        batch_size=batch_size,
        extra={"collection_config": collection_config},
    )
    try:
        checkpoint = _load_checkpoint(checkpoint_path, signature)
    except ValueError as exc:
        return skipped_result("Qdrant service streaming", str(exc))
    checkpoint_metadata = checkpoint.setdefault("metadata", {})
    configured_collection = os.environ.get("WAVEMIND_QDRANT_COLLECTION")
    checkpoint_collection = checkpoint_metadata.get("collection_name")
    if configured_collection and checkpoint_collection and configured_collection != checkpoint_collection:
        return skipped_result(
            "Qdrant service streaming",
            "WAVEMIND_QDRANT_COLLECTION does not match checkpoint collection_name",
        )
    collection_name = (
        configured_collection
        or checkpoint_collection
        or f"wavemind_streaming_load_{time.time_ns()}"
    )
    checkpoint_metadata["collection_name"] = collection_name
    _write_checkpoint(checkpoint_path, checkpoint)
    completed_batches = _checkpoint_completed_batches(checkpoint)
    source_ids = choose_source_ids(count, query_count, seed)
    source_vectors: dict[int, np.ndarray] = _checkpoint_source_vectors(checkpoint)
    complete_resume = _checkpoint_complete_for_run(
        checkpoint,
        count=count,
        batch_size=batch_size,
        source_ids=source_ids,
    )
    hnsw_config = (
        HnswConfigDiff(**collection_config["hnsw"])
        if collection_config["hnsw"]
        else None
    )
    scalar_quantization_config = collection_config["scalar_quantization"]
    quantization_config = (
        ScalarQuantization(
            scalar=ScalarQuantizationConfig(
                type=ScalarType.INT8,
                quantile=float(scalar_quantization_config["quantile"]),
                always_ram=bool(scalar_quantization_config["always_ram"]),
            )
        )
        if scalar_quantization_config
        else None
    )
    ingest_optimizers = dict(collection_config["optimizers"])
    if deferred_indexing["enabled"]:
        ingest_optimizers["indexing_threshold"] = deferred_indexing[
            "deferred_threshold_kb"
        ]
    ingest_optimizers_config = (
        OptimizersConfigDiff(**ingest_optimizers) if ingest_optimizers else None
    )
    recreate_kwargs = _without_none(
        {
            "hnsw_config": hnsw_config,
            "optimizers_config": ingest_optimizers_config,
            "quantization_config": quantization_config,
            "on_disk_payload": collection_config["on_disk_payload"],
            "shard_number": collection_config["shard_number"],
        }
    )
    with _local_no_proxy(url):
        client = QdrantClient(
            url=url,
            api_key=os.environ.get("WAVEMIND_QDRANT_API_KEY"),
            grpc_port=_optional_int_env("WAVEMIND_QDRANT_GRPC_PORT"),
            prefer_grpc=_bool_env("WAVEMIND_QDRANT_PREFER_GRPC", False),
            timeout=float(os.environ.get("WAVEMIND_QDRANT_TIMEOUT", "120")),
        )
    try:
        started = time.perf_counter()
        if not completed_batches:
            client.recreate_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=int(dim),
                    distance=Distance.COSINE,
                    on_disk=collection_config["vector_on_disk"],
                ),
                timeout=int(os.environ.get("WAVEMIND_QDRANT_COLLECTION_TIMEOUT", "120")),
                **recreate_kwargs,
            )
        elif complete_resume and (
            hnsw_config is not None or quantization_config is not None
        ):
            client.update_collection(
                collection_name=collection_name,
                hnsw_config=hnsw_config,
                quantization_config=quantization_config,
                timeout=int(
                    os.environ.get("WAVEMIND_QDRANT_COLLECTION_TIMEOUT", "120")
                ),
            )
        elif deferred_indexing["enabled"] and not complete_resume:
            client.update_collection(
                collection_name=collection_name,
                optimizers_config=ingest_optimizers_config,
                timeout=int(os.environ.get("WAVEMIND_QDRANT_COLLECTION_TIMEOUT", "120")),
            )
        if not complete_resume:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=upsert_workers
            ) as upsert_executor:
                for ids, vectors, captured in iter_vector_batches(
                    count=count,
                    dim=dim,
                    seed=seed + count,
                    batch_size=batch_size,
                    source_ids=source_ids,
                ):
                    batch_start = int(ids[0]) if len(ids) else 0
                    if batch_start not in completed_batches:
                        inserted = _upsert_qdrant_point_chunks(
                            executor=upsert_executor,
                            client=client,
                            collection_name=collection_name,
                            point_chunks=_iter_qdrant_point_chunks(
                                ids,
                                vectors,
                                point_type=PointStruct,
                                chunk_size=upsert_batch_size,
                            ),
                            max_in_flight=upsert_workers,
                        )
                        if inserted != len(ids):
                            raise RuntimeError(
                                "Qdrant upsert did not acknowledge every point"
                            )
                    source_vectors.update(captured)
                    _record_checkpoint_batch(
                        path=checkpoint_path,
                        payload=checkpoint,
                        batch_start=batch_start,
                        captured=captured,
                    )
                    completed_batches.add(batch_start)
        index_restore_ms = 0.0
        if deferred_indexing["enabled"] and not complete_resume:
            restore_started = time.perf_counter()
            final_optimizers = dict(collection_config["optimizers"])
            final_optimizers["indexing_threshold"] = deferred_indexing[
                "final_threshold_kb"
            ]
            updated = client.update_collection(
                collection_name=collection_name,
                optimizers_config=OptimizersConfigDiff(**final_optimizers),
                timeout=int(os.environ.get("WAVEMIND_QDRANT_COLLECTION_TIMEOUT", "120")),
            )
            if not updated:
                raise RuntimeError(
                    f"Qdrant collection {collection_name!r} rejected final indexing threshold"
                )
            index_restore_ms = (time.perf_counter() - restore_started) * 1000.0
        wait_after_build_seconds = float(os.environ.get("WAVEMIND_QDRANT_WAIT_AFTER_BUILD_SECONDS", "0"))
        if wait_after_build_seconds > 0:
            time.sleep(wait_after_build_seconds)
        index_ready_timeout_seconds = float(
            os.environ.get("WAVEMIND_QDRANT_INDEX_READY_TIMEOUT_SECONDS", "0")
        )
        index_ready_poll_seconds = float(
            os.environ.get("WAVEMIND_QDRANT_INDEX_READY_POLL_SECONDS", "5")
        )
        require_full_index = _bool_env("WAVEMIND_QDRANT_REQUIRE_FULL_INDEX", False)
        index_readiness = _wait_for_qdrant_index_ready(
            client,
            collection_name,
            expected_vectors=count,
            timeout_seconds=index_ready_timeout_seconds,
            poll_interval_seconds=index_ready_poll_seconds,
            require_full_index=require_full_index,
        )
        build_ms = (time.perf_counter() - started) * 1000.0
        hnsw_ef = os.environ.get("WAVEMIND_QDRANT_HNSW_EF")
        exact = os.environ.get("WAVEMIND_QDRANT_EXACT", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        quantization_search_params = None
        if scalar_quantization_config:
            quantization_search_params = QuantizationSearchParams(
                ignore=_optional_bool_env(
                    "WAVEMIND_QDRANT_QUANTIZATION_IGNORE"
                ),
                rescore=_optional_bool_env(
                    "WAVEMIND_QDRANT_QUANTIZATION_RESCORE"
                ),
                oversampling=_optional_float_env(
                    "WAVEMIND_QDRANT_QUANTIZATION_OVERSAMPLING"
                ),
            )
        search_params = None
        if hnsw_ef or exact or quantization_search_params is not None:
            search_params = SearchParams(
                hnsw_ef=int(hnsw_ef) if hnsw_ef else None,
                exact=exact or None,
                quantization=quantization_search_params,
            )
        query_timeout_seconds = _optional_int_env(
            "WAVEMIND_QDRANT_QUERY_TIMEOUT_SECONDS"
        )
        query_kwargs = _without_none({"timeout": query_timeout_seconds})
        queries = make_queries(source_ids=source_ids, source_vectors=source_vectors, seed=seed + count, noise=noise)
        warmup_queries = int(os.environ.get("WAVEMIND_QDRANT_WARMUP_QUERIES", "0"))
        if warmup_queries > 0 and queries:
            for index in range(warmup_queries):
                _, query = queries[index % len(queries)]
                list(
                    client.query_points(
                        collection_name=collection_name,
                        query=query.tolist(),
                        limit=top_k,
                        with_payload=False,
                        search_params=search_params,
                        **query_kwargs,
                    ).points
                )
        rows: list[dict[str, Any]] = []
        for source_id, query in queries:
            started = time.perf_counter()
            hits = list(
                client.query_points(
                    collection_name=collection_name,
                    query=query.tolist(),
                    limit=top_k,
                    with_payload=False,
                    search_params=search_params,
                    **query_kwargs,
                ).points
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            top = [int(hit.id) for hit in hits]
            rows.append(
                {
                    "source_id": int(source_id),
                    "target_hit": int(source_id) in top,
                    "target_hit_at_1": bool(top and top[0] == int(source_id)),
                    "latency_ms": latency_ms,
                }
            )
        return _metrics_from_hits(
            engine="Qdrant service streaming",
            vector_count=count,
            dim=dim,
            batch_size=batch_size,
            top_k=top_k,
            build_ms=build_ms,
            query_rows=rows,
            extra={
                "collection_name": collection_name,
                "warmup_queries": warmup_queries,
                "wait_after_build_seconds": wait_after_build_seconds,
                "index_readiness": index_readiness,
                "deferred_indexing": deferred_indexing,
                "index_restore_ms": index_restore_ms,
                "search_params": {
                    "hnsw_ef": int(hnsw_ef) if hnsw_ef else None,
                    "exact": exact,
                    "quantization": {
                        "enabled": quantization_search_params is not None,
                        "ignore": _optional_bool_env(
                            "WAVEMIND_QDRANT_QUANTIZATION_IGNORE"
                        ),
                        "rescore": _optional_bool_env(
                            "WAVEMIND_QDRANT_QUANTIZATION_RESCORE"
                        ),
                        "oversampling": _optional_float_env(
                            "WAVEMIND_QDRANT_QUANTIZATION_OVERSAMPLING"
                        ),
                    },
                },
                "transport": {
                    "prefer_grpc": _bool_env(
                        "WAVEMIND_QDRANT_PREFER_GRPC", False
                    ),
                    "grpc_port": _optional_int_env("WAVEMIND_QDRANT_GRPC_PORT"),
                    "query_timeout_seconds": query_timeout_seconds,
                },
                "collection_params": collection_config,
                "upsert_batch_size": upsert_batch_size,
                "upsert_workers": upsert_workers,
                "qdrant_checkpoint_complete_resume": bool(complete_resume),
                "memory_mode": "streaming upsert; query source vectors only",
                **_checkpoint_extra(checkpoint_path, checkpoint, completed_batches),
            },
        )
    finally:
        keep = checkpoint_path is not None or os.environ.get("WAVEMIND_QDRANT_KEEP_COLLECTION", "0").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not keep:
            try:
                client.delete_collection(collection_name=collection_name)
            except Exception:
                pass
        close = getattr(client, "close", None)
        if callable(close):
            close()


def run_qdrant_sharded_streaming(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
) -> dict[str, Any]:
    engine = "Qdrant sharded service streaming"
    try:
        upsert_batch_size = _positive_int_env("WAVEMIND_QDRANT_UPSERT_BATCH_SIZE", 5000)
    except ValueError as exc:
        return skipped_result(engine, str(exc))
    target_urls = _split_env_list(os.environ.get("WAVEMIND_QDRANT_URLS"))
    if len(target_urls) < 2:
        return skipped_result(
            engine,
            "Set WAVEMIND_QDRANT_URLS to at least two comma-separated Qdrant service URLs",
        )
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import (
            Distance,
            HnswConfigDiff,
            OptimizersConfigDiff,
            PointStruct,
            QuantizationSearchParams,
            ScalarQuantization,
            ScalarQuantizationConfig,
            ScalarType,
            SearchParams,
            VectorParams,
        )
    except ImportError as exc:
        return skipped_result(engine, f"Install qdrant-client: {exc}")

    collection_config = _qdrant_collection_config_from_env()
    deferred_indexing = _qdrant_deferred_indexing_config_from_env()
    checkpoint_path = _checkpoint_path_from_env()
    signature = _checkpoint_signature(
        engine=engine,
        count=count,
        dim=dim,
        query_count=query_count,
        top_k=top_k,
        seed=seed,
        noise=noise,
        batch_size=batch_size,
        extra={"collection_config": collection_config, "target_urls": target_urls},
    )
    try:
        checkpoint = _load_checkpoint(checkpoint_path, signature)
    except ValueError as exc:
        return skipped_result(engine, str(exc))
    checkpoint_metadata = checkpoint.setdefault("metadata", {})
    configured_prefix = (
        os.environ.get("WAVEMIND_QDRANT_COLLECTION_PREFIX")
        or os.environ.get("WAVEMIND_QDRANT_COLLECTION")
    )
    checkpoint_prefix = checkpoint_metadata.get("collection_prefix")
    if configured_prefix and checkpoint_prefix and configured_prefix != checkpoint_prefix:
        return skipped_result(
            engine,
            "WAVEMIND_QDRANT_COLLECTION_PREFIX does not match checkpoint collection_prefix",
        )
    base_collection_name = (
        configured_prefix
        or checkpoint_prefix
        or f"wavemind_streaming_load_{time.time_ns()}"
    )
    checkpoint_metadata["collection_prefix"] = base_collection_name
    _write_checkpoint(checkpoint_path, checkpoint)
    try:
        targets = _qdrant_shard_targets_from_env(base_collection_name)
    except ValueError as exc:
        return skipped_result(engine, f"Invalid Qdrant shard transport configuration: {exc}")
    if len(targets) < 2:
        return skipped_result(
            engine,
            "Set WAVEMIND_QDRANT_URLS to at least two comma-separated Qdrant service URLs",
        )
    try:
        fanout_workers = min(
            len(targets),
            _positive_int_env("WAVEMIND_QDRANT_FANOUT_WORKERS", len(targets)),
        )
    except ValueError as exc:
        return skipped_result(engine, str(exc))
    hnsw_config = (
        HnswConfigDiff(**collection_config["hnsw"])
        if collection_config["hnsw"]
        else None
    )
    scalar_quantization_config = collection_config["scalar_quantization"]
    quantization_config = (
        ScalarQuantization(
            scalar=ScalarQuantizationConfig(
                type=ScalarType.INT8,
                quantile=float(scalar_quantization_config["quantile"]),
                always_ram=bool(scalar_quantization_config["always_ram"]),
            )
        )
        if scalar_quantization_config
        else None
    )
    ingest_optimizers = dict(collection_config["optimizers"])
    if deferred_indexing["enabled"]:
        ingest_optimizers["indexing_threshold"] = deferred_indexing[
            "deferred_threshold_kb"
        ]
    ingest_optimizers_config = (
        OptimizersConfigDiff(**ingest_optimizers) if ingest_optimizers else None
    )
    recreate_kwargs = _without_none(
        {
            "hnsw_config": hnsw_config,
            "optimizers_config": ingest_optimizers_config,
            "quantization_config": quantization_config,
            "on_disk_payload": collection_config["on_disk_payload"],
            "shard_number": collection_config["shard_number"],
        }
    )
    clients = []
    for target in targets:
        with _local_no_proxy(target.url):
            clients.append(
                QdrantClient(
                    url=target.url,
                    api_key=target.api_key,
                    grpc_port=target.grpc_port,
                    prefer_grpc=_bool_env("WAVEMIND_QDRANT_PREFER_GRPC", False),
                    timeout=float(os.environ.get("WAVEMIND_QDRANT_TIMEOUT", "120")),
                )
            )

    def query_target(client: Any, target: QdrantShardTarget, query: np.ndarray, search_params: Any) -> list[Any]:
        return list(
            client.query_points(
                collection_name=target.collection_name,
                query=query.tolist(),
                limit=top_k,
                with_payload=False,
                search_params=search_params,
                **query_kwargs,
            ).points
        )

    try:
        source_ids = choose_source_ids(count, query_count, seed)
        source_vectors: dict[int, np.ndarray] = _checkpoint_source_vectors(checkpoint)
        completed_batches = _checkpoint_completed_batches(checkpoint)
        complete_resume = _checkpoint_complete_for_run(
            checkpoint,
            count=count,
            batch_size=batch_size,
            source_ids=source_ids,
        )
        started = time.perf_counter()
        if not completed_batches:
            for client, target in zip(clients, targets):
                client.recreate_collection(
                    collection_name=target.collection_name,
                    vectors_config=VectorParams(
                        size=int(dim),
                        distance=Distance.COSINE,
                        on_disk=collection_config["vector_on_disk"],
                    ),
                    timeout=int(os.environ.get("WAVEMIND_QDRANT_COLLECTION_TIMEOUT", "120")),
                    **recreate_kwargs,
                )
        elif complete_resume and (
            hnsw_config is not None or quantization_config is not None
        ):
            for client, target in zip(clients, targets):
                client.update_collection(
                    collection_name=target.collection_name,
                    hnsw_config=hnsw_config,
                    quantization_config=quantization_config,
                    timeout=int(
                        os.environ.get("WAVEMIND_QDRANT_COLLECTION_TIMEOUT", "120")
                    ),
                )
        elif deferred_indexing["enabled"] and not complete_resume:
            for client, target in zip(clients, targets):
                client.update_collection(
                    collection_name=target.collection_name,
                    optimizers_config=ingest_optimizers_config,
                    timeout=int(os.environ.get("WAVEMIND_QDRANT_COLLECTION_TIMEOUT", "120")),
                )
        if not complete_resume:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=fanout_workers
            ) as ingest_executor:
                for ids, vectors, captured in iter_vector_batches(
                    count=count,
                    dim=dim,
                    seed=seed + count,
                    batch_size=batch_size,
                    source_ids=source_ids,
                ):
                    batch_start = int(ids[0]) if len(ids) else 0
                    if batch_start not in completed_batches:
                        point_chunks_by_shard = {
                            target.index: _iter_qdrant_shard_point_chunks(
                                ids,
                                vectors,
                                shard_index=target.index,
                                shard_count=len(targets),
                                point_type=PointStruct,
                                chunk_size=upsert_batch_size,
                            )
                            for target in targets
                        }
                        inserted = _upsert_qdrant_shards(
                            executor=ingest_executor,
                            clients=clients,
                            targets=targets,
                            point_chunks_by_shard=point_chunks_by_shard,
                        )
                        if inserted != len(ids):
                            raise RuntimeError(
                                "Qdrant sharded upsert did not acknowledge every point"
                            )
                    source_vectors.update(captured)
                    _record_checkpoint_batch(
                        path=checkpoint_path,
                        payload=checkpoint,
                        batch_start=batch_start,
                        captured=captured,
                    )
                    completed_batches.add(batch_start)
        index_restore_ms = 0.0
        if deferred_indexing["enabled"] and not complete_resume:
            restore_started = time.perf_counter()
            final_optimizers = dict(collection_config["optimizers"])
            final_optimizers["indexing_threshold"] = deferred_indexing[
                "final_threshold_kb"
            ]
            for client, target in zip(clients, targets):
                updated = client.update_collection(
                    collection_name=target.collection_name,
                    optimizers_config=OptimizersConfigDiff(**final_optimizers),
                    timeout=int(os.environ.get("WAVEMIND_QDRANT_COLLECTION_TIMEOUT", "120")),
                )
                if not updated:
                    raise RuntimeError(
                        f"Qdrant collection {target.collection_name!r} rejected final indexing threshold"
                    )
            index_restore_ms = (time.perf_counter() - restore_started) * 1000.0
        wait_after_build_seconds = float(os.environ.get("WAVEMIND_QDRANT_WAIT_AFTER_BUILD_SECONDS", "0"))
        if wait_after_build_seconds > 0:
            time.sleep(wait_after_build_seconds)
        index_ready_timeout_seconds = float(
            os.environ.get("WAVEMIND_QDRANT_INDEX_READY_TIMEOUT_SECONDS", "0")
        )
        index_ready_poll_seconds = float(
            os.environ.get("WAVEMIND_QDRANT_INDEX_READY_POLL_SECONDS", "5")
        )
        require_full_index = _bool_env("WAVEMIND_QDRANT_REQUIRE_FULL_INDEX", False)
        base_expected = int(count) // len(targets)
        remainder = int(count) % len(targets)
        index_readiness = [
            _wait_for_qdrant_index_ready(
                client,
                target.collection_name,
                expected_vectors=base_expected + (1 if target.index < remainder else 0),
                timeout_seconds=index_ready_timeout_seconds,
                poll_interval_seconds=index_ready_poll_seconds,
                require_full_index=require_full_index,
            )
            for client, target in zip(clients, targets)
        ]
        build_ms = (time.perf_counter() - started) * 1000.0
        hnsw_ef = os.environ.get("WAVEMIND_QDRANT_HNSW_EF")
        exact = os.environ.get("WAVEMIND_QDRANT_EXACT", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        quantization_search_params = None
        if scalar_quantization_config:
            quantization_search_params = QuantizationSearchParams(
                ignore=_optional_bool_env(
                    "WAVEMIND_QDRANT_QUANTIZATION_IGNORE"
                ),
                rescore=_optional_bool_env(
                    "WAVEMIND_QDRANT_QUANTIZATION_RESCORE"
                ),
                oversampling=_optional_float_env(
                    "WAVEMIND_QDRANT_QUANTIZATION_OVERSAMPLING"
                ),
            )
        search_params = None
        if hnsw_ef or exact or quantization_search_params is not None:
            search_params = SearchParams(
                hnsw_ef=int(hnsw_ef) if hnsw_ef else None,
                exact=exact or None,
                quantization=quantization_search_params,
            )
        query_timeout_seconds = _optional_int_env(
            "WAVEMIND_QDRANT_QUERY_TIMEOUT_SECONDS"
        )
        query_kwargs = _without_none({"timeout": query_timeout_seconds})
        queries = make_queries(source_ids=source_ids, source_vectors=source_vectors, seed=seed + count, noise=noise)
        with concurrent.futures.ThreadPoolExecutor(max_workers=fanout_workers) as executor:
            warmup_queries = int(os.environ.get("WAVEMIND_QDRANT_WARMUP_QUERIES", "0"))
            if warmup_queries > 0 and queries:
                for index in range(warmup_queries):
                    _, query = queries[index % len(queries)]
                    list(
                        executor.map(
                            lambda pair: query_target(pair[0], pair[1], query, search_params),
                            zip(clients, targets),
                        )
                    )
            rows: list[dict[str, Any]] = []
            for source_id, query in queries:
                started = time.perf_counter()
                hits_by_shard = list(
                    executor.map(
                        lambda pair: query_target(pair[0], pair[1], query, search_params),
                        zip(clients, targets),
                    )
                )
                latency_ms = (time.perf_counter() - started) * 1000.0
                top = _merge_scored_hits(hits_by_shard, top_k)
                rows.append(
                    {
                        "source_id": int(source_id),
                        "target_hit": int(source_id) in top,
                        "target_hit_at_1": bool(top and top[0] == int(source_id)),
                        "latency_ms": latency_ms,
                    }
                )
        return _metrics_from_hits(
            engine=engine,
            vector_count=count,
            dim=dim,
            batch_size=batch_size,
            top_k=top_k,
            build_ms=build_ms,
            query_rows=rows,
            extra={
                "collection_prefix": base_collection_name,
                "collection_names": [target.collection_name for target in targets],
                "shard_count": len(targets),
                "fanout_workers": fanout_workers,
                "parallel_shard_upsert": True,
                "routing": "point_id_minus_one_mod_shard_count",
                "warmup_queries": warmup_queries,
                "wait_after_build_seconds": wait_after_build_seconds,
                "index_readiness": index_readiness,
                "index_ready_all": all(row["ready"] for row in index_readiness),
                "deferred_indexing": deferred_indexing,
                "index_restore_ms": index_restore_ms,
                "search_params": {
                    "hnsw_ef": int(hnsw_ef) if hnsw_ef else None,
                    "exact": exact,
                    "quantization": {
                        "enabled": quantization_search_params is not None,
                        "ignore": _optional_bool_env(
                            "WAVEMIND_QDRANT_QUANTIZATION_IGNORE"
                        ),
                        "rescore": _optional_bool_env(
                            "WAVEMIND_QDRANT_QUANTIZATION_RESCORE"
                        ),
                        "oversampling": _optional_float_env(
                            "WAVEMIND_QDRANT_QUANTIZATION_OVERSAMPLING"
                        ),
                    },
                },
                "transport": {
                    "prefer_grpc": _bool_env(
                        "WAVEMIND_QDRANT_PREFER_GRPC", False
                    ),
                    "grpc_ports": [target.grpc_port for target in targets],
                    "query_timeout_seconds": query_timeout_seconds,
                },
                "collection_params": collection_config,
                "upsert_batch_size": upsert_batch_size,
                "qdrant_checkpoint_complete_resume": bool(complete_resume),
                "memory_mode": "horizontally sharded streaming upsert; parallel fanout query merge",
                **_checkpoint_extra(checkpoint_path, checkpoint, completed_batches),
            },
        )
    finally:
        keep = checkpoint_path is not None or os.environ.get("WAVEMIND_QDRANT_KEEP_COLLECTION", "0").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        for client, target in zip(clients, targets):
            if not keep:
                try:
                    client.delete_collection(collection_name=target.collection_name)
                except Exception:
                    pass
            close = getattr(client, "close", None)
            if callable(close):
                close()


def run_pgvector_streaming(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
) -> dict[str, Any]:
    dsn = os.environ.get("WAVEMIND_PGVECTOR_DSN")
    engine = "WaveMind pgvector streaming"
    if not dsn:
        return skipped_result(engine, "Set WAVEMIND_PGVECTOR_DSN to run streaming pgvector")
    try:
        import psycopg
    except ImportError as exc:
        return skipped_result(engine, f'Install PostgreSQL support with: pip install "wavemind[postgres]": {exc}')

    try:
        config = _pgvector_config_from_env()
    except ValueError as exc:
        return skipped_result(engine, str(exc))
    iterative_scan = config.get("iterative_scan")
    if iterative_scan and iterative_scan not in {"strict_order", "relaxed_order", "off"}:
        return skipped_result(
            engine,
            "WAVEMIND_PGVECTOR_ITERATIVE_SCAN must be strict_order, relaxed_order, or off",
        )

    table = str(config["table"])
    storage_type = str(config["storage_type"])
    insert_mode = str(config["insert_mode"])
    index_type = str(config["index_type"])
    ivfflat_lists = config["ivfflat_lists"] or max(1, int(round(math.sqrt(count))))
    ivfflat_probes = config["ivfflat_probes"] or max(1, int(round(math.sqrt(ivfflat_lists))))
    if ivfflat_lists <= 0:
        return skipped_result(engine, "WAVEMIND_PGVECTOR_IVFFLAT_LISTS must be positive")
    if ivfflat_probes <= 0 or ivfflat_probes > ivfflat_lists:
        return skipped_result(
            engine,
            "WAVEMIND_PGVECTOR_IVFFLAT_PROBES must be positive and no greater than lists",
        )
    index_name = f"{table}_embedding_{index_type}_idx"
    checkpoint_path = _checkpoint_path_from_env()
    signature = _checkpoint_signature(
        engine=engine,
        count=count,
        dim=dim,
        query_count=query_count,
        top_k=top_k,
        seed=seed,
        noise=noise,
        batch_size=batch_size,
        extra={
            "table": table,
            "storage_type": storage_type,
            "insert_mode": insert_mode,
        },
    )
    try:
        checkpoint = _load_pgvector_checkpoint(checkpoint_path, signature)
    except ValueError as exc:
        return skipped_result(engine, str(exc))
    checkpoint_metadata = checkpoint.setdefault("metadata", {})
    configured_collection = os.environ.get("WAVEMIND_PGVECTOR_COLLECTION")
    checkpoint_collection = checkpoint_metadata.get("collection")
    if configured_collection and checkpoint_collection and configured_collection != checkpoint_collection:
        return skipped_result(
            engine,
            "WAVEMIND_PGVECTOR_COLLECTION does not match checkpoint collection",
        )
    collection = configured_collection or checkpoint_collection or str(config["collection"])
    checkpoint_metadata["collection"] = collection
    _write_checkpoint(checkpoint_path, checkpoint)
    completed_batches = _checkpoint_completed_batches(checkpoint)
    source_ids = choose_source_ids(count, query_count, seed)
    source_vectors: dict[int, np.ndarray] = _checkpoint_source_vectors(checkpoint)
    complete_resume = _checkpoint_complete_for_run(
        checkpoint,
        count=count,
        batch_size=batch_size,
        source_ids=source_ids,
    )
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        started = time.perf_counter()
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                collection TEXT NOT NULL,
                memory_id BIGINT NOT NULL,
                embedding {storage_type}({int(dim)}) NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (collection, memory_id)
            )
            """
        )
        conn.execute(f"CREATE INDEX IF NOT EXISTS {table}_collection_idx ON {table} (collection)")
        column_type = conn.execute(
            """
            SELECT format_type(attribute.atttypid, attribute.atttypmod)
            FROM pg_attribute AS attribute
            WHERE attribute.attrelid = %s::regclass
              AND attribute.attname = 'embedding'
              AND NOT attribute.attisdropped
            """,
            (table,),
        ).fetchone()
        expected_column_type = f"{storage_type}({int(dim)})"
        if not column_type or str(column_type[0]).lower() != expected_column_type:
            actual = None if not column_type else str(column_type[0])
            raise RuntimeError(
                f"pgvector table {table!r} embedding type is {actual!r}; "
                f"expected {expected_column_type!r}"
            )
        if not completed_batches:
            conn.execute(f"DELETE FROM {table} WHERE collection = %s", (collection,))
        if not complete_resume:
            with conn.cursor() as cur:
                for ids, vectors, captured in iter_vector_batches(
                    count=count,
                    dim=dim,
                    seed=seed + count,
                    batch_size=batch_size,
                    source_ids=source_ids,
                ):
                    batch_start = int(ids[0]) if len(ids) else 0
                    if batch_start not in completed_batches:
                        _pgvector_insert_batch(
                            cur,
                            table=table,
                            collection=collection,
                            ids=ids,
                            vectors=vectors,
                            storage_type=storage_type,
                            insert_mode=insert_mode,
                        )
                    source_vectors.update(captured)
                    _record_checkpoint_batch(
                        path=checkpoint_path,
                        payload=checkpoint,
                        batch_start=batch_start,
                        captured=captured,
                    )
                    completed_batches.add(batch_start)

        remote_row_count = int(
            conn.execute(
                f"SELECT count(*) FROM {table} WHERE collection = %s",
                (collection,),
            ).fetchone()[0]
        )
        if remote_row_count != int(count):
            raise RuntimeError(
                f"pgvector collection {collection!r} contains {remote_row_count} rows; "
                f"expected {int(count)}"
            )
        checkpoint_metadata["remote_row_count"] = remote_row_count
        checkpoint_metadata["storage_type"] = storage_type
        checkpoint_metadata["insert_mode"] = insert_mode
        _write_checkpoint(checkpoint_path, checkpoint)
        if config["create_hnsw"]:
            if index_type == "hnsw":
                options = []
                if config["hnsw_m"] is not None:
                    options.append(f"m = {int(config['hnsw_m'])}")
                if config["hnsw_ef_construction"] is not None:
                    options.append(f"ef_construction = {int(config['hnsw_ef_construction'])}")
                with_options = f" WITH ({', '.join(options)})" if options else ""
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON {table} USING hnsw (embedding {_pgvector_operator_class(storage_type)})"
                    f"{with_options}"
                )
            else:
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON {table} USING ivfflat (embedding {_pgvector_operator_class(storage_type)}) "
                    f"WITH (lists = {int(ivfflat_lists)})"
                )
        index_present = bool(
            conn.execute("SELECT to_regclass(%s)", (index_name,)).fetchone()[0]
        )
        if config["create_hnsw"] and not index_present:
            raise RuntimeError(f"pgvector {index_type} index {index_name!r} is missing")
        checkpoint_metadata["index_name"] = index_name
        checkpoint_metadata["index_type"] = index_type
        checkpoint_metadata["index_present"] = index_present
        _write_checkpoint(checkpoint_path, checkpoint)
        conn.execute(f"ANALYZE {table}")
        prewarm_blocks = 0
        if config["prewarm_index"] and index_present:
            conn.execute("CREATE EXTENSION IF NOT EXISTS pg_prewarm")
            prewarm_blocks = int(
                conn.execute(
                    "SELECT pg_prewarm(%s, 'buffer')",
                    (index_name,),
                ).fetchone()[0]
            )
        wait_after_build_seconds = float(os.environ.get("WAVEMIND_PGVECTOR_WAIT_AFTER_BUILD_SECONDS", "0"))
        if wait_after_build_seconds > 0:
            time.sleep(wait_after_build_seconds)
        build_ms = (time.perf_counter() - started) * 1000.0

        queries = make_queries(source_ids=source_ids, source_vectors=source_vectors, seed=seed + count, noise=noise)
        if index_type == "hnsw" and config["ef_search"] is not None:
            conn.execute(f"SET hnsw.ef_search = {int(config['ef_search'])}")
        if index_type == "ivfflat":
            conn.execute(f"SET ivfflat.probes = {int(ivfflat_probes)}")
        if iterative_scan:
            conn.execute(f"SET hnsw.iterative_scan = '{iterative_scan}'")
        if config["max_scan_tuples"] is not None:
            conn.execute(f"SET hnsw.max_scan_tuples = {int(config['max_scan_tuples'])}")
        if config["scan_mem_multiplier"] is not None:
            conn.execute(f"SET hnsw.scan_mem_multiplier = {int(config['scan_mem_multiplier'])}")
        if config["exact"]:
            conn.execute("SET enable_indexscan = off")
            conn.execute("SET enable_bitmapscan = off")

        warmup_queries = int(os.environ.get("WAVEMIND_PGVECTOR_WARMUP_QUERIES", "0"))
        search_sql = (
            f"SELECT memory_id FROM {table} "
            f"WHERE collection = %s "
            f"ORDER BY embedding <=> %s::{storage_type} "
            f"LIMIT %s"
        )
        if warmup_queries > 0 and queries:
            for index in range(warmup_queries):
                _, query = queries[index % len(queries)]
                conn.execute(search_sql, (collection, _vector_literal(query), int(top_k))).fetchall()
        rows: list[dict[str, Any]] = []
        for source_id, query in queries:
            started = time.perf_counter()
            hits = conn.execute(search_sql, (collection, _vector_literal(query), int(top_k))).fetchall()
            latency_ms = (time.perf_counter() - started) * 1000.0
            top = [int(row[0]) for row in hits]
            rows.append(
                {
                    "source_id": int(source_id),
                    "target_hit": int(source_id) in top,
                    "target_hit_at_1": bool(top and top[0] == int(source_id)),
                    "latency_ms": latency_ms,
                }
            )
        return _metrics_from_hits(
            engine=engine,
            vector_count=count,
            dim=dim,
            batch_size=batch_size,
            top_k=top_k,
            build_ms=build_ms,
            query_rows=rows,
            extra={
                "table": table,
                "collection": collection,
                "storage_type": storage_type,
                "insert_mode": insert_mode,
                "index_type": index_type,
                "remote_row_count": remote_row_count,
                "complete_resume": complete_resume,
                "index_name": index_name,
                "index_present": index_present,
                "prewarm_index": bool(config["prewarm_index"]),
                "prewarm_blocks": prewarm_blocks,
                "warmup_queries": warmup_queries,
                "wait_after_build_seconds": wait_after_build_seconds,
                "search_params": {
                    "hnsw_ef": config["ef_search"],
                    "ivfflat_probes": ivfflat_probes if index_type == "ivfflat" else None,
                    "exact": config["exact"],
                    "iterative_scan": iterative_scan,
                    "max_scan_tuples": config["max_scan_tuples"],
                    "scan_mem_multiplier": config["scan_mem_multiplier"],
                },
                "collection_params": {
                    "create_hnsw": config["create_hnsw"],
                    "hnsw_m": config["hnsw_m"],
                    "hnsw_ef_construction": config["hnsw_ef_construction"],
                    "index_type": index_type,
                    "ivfflat_lists": ivfflat_lists if index_type == "ivfflat" else None,
                },
                "memory_mode": "streaming PostgreSQL insert; query source vectors only",
                **_checkpoint_extra(checkpoint_path, checkpoint, completed_batches),
            },
        )
    finally:
        try:
            if not config.get("keep_collection") and checkpoint_path is None:
                conn.execute(f"DELETE FROM {table} WHERE collection = %s", (collection,))
        finally:
            conn.close()


def run_size(
    *,
    count: int,
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
    engines: Iterable[str],
    target_recall: float = 0.95,
    target_p99_ms: float = 100.0,
) -> dict[str, Any]:
    results = []
    for engine in engines:
        key = engine.lower()
        kwargs = {
            "count": count,
            "dim": dim,
            "query_count": query_count,
            "top_k": top_k,
            "seed": seed,
            "noise": noise,
            "batch_size": batch_size,
        }
        if key in {"numpy", "numpy-streaming"}:
            results.append(run_numpy_streaming(**kwargs))
        elif key in {"faiss", "faiss-persisted", "faiss-streaming"}:
            results.append(run_faiss_streaming(**kwargs))
        elif key in {"faiss-ivfpq", "faiss-ivfpq-persisted", "faiss-ivfpq-streaming"}:
            results.append(
                run_faiss_ivfpq_streaming(
                    **kwargs,
                    target_recall=target_recall,
                    target_p99_ms=target_p99_ms,
                )
            )
        elif key in {"qdrant", "qdrant-service", "qdrant-streaming"}:
            results.append(run_qdrant_streaming(**kwargs))
        elif key in {"qdrant-sharded", "qdrant-sharded-service", "qdrant-sharded-streaming"}:
            results.append(run_qdrant_sharded_streaming(**kwargs))
        elif key in {"pgvector", "pgvector-service", "pgvector-streaming"}:
            results.append(run_pgvector_streaming(**kwargs))
        else:
            raise ValueError(f"Unknown engine: {engine}")
    return {
        "vectors": int(count),
        "vector_dim": int(dim),
        "queries": min(int(query_count), int(count)),
        "top_k": int(top_k),
        "noise": float(noise),
        "batch_size": int(batch_size),
        "results": results,
    }


def run_streaming_load(
    *,
    sizes: Iterable[int],
    dim: int,
    query_count: int,
    top_k: int,
    seed: int,
    noise: float,
    batch_size: int,
    engines: Iterable[str],
    output_path: Path | None = None,
    target_recall: float = 0.95,
    target_p99_ms: float = 100.0,
    target_qps: float = 100.0,
    replicas: int = 3,
    autoscaling_max_replicas: int = 24,
    capacity_headroom: float = 0.70,
    replica_hourly_cost_usd: float = 0.25,
    storage_gb_monthly_cost_usd: float = 0.10,
    memory_payload_kb: float = 2.0,
    vector_dtype_bytes: int = 4,
) -> dict[str, Any]:
    size_list = [int(size) for size in sizes]
    payload = {
        **_benchmark_provenance(),
        "scenario": {
            "name": "production_streaming_load_profile",
            "description": (
                "Memory-bounded production load profile for 10M+ vector runs. "
                "Vectors are generated and inserted in batches. Quality is measured "
                "as target-recall: whether a noisy copy of a known source vector "
                "returns that source id in top-k. This is scalable to large N and "
                "complements exact-neighbor benchmarks at smaller N. Use persisted "
                "FAISS IVF-PQ for memory-bounded 10M+ compressed-index profiles."
            ),
            "sizes": size_list,
            "vector_dim": int(dim),
            "queries_per_size": int(query_count),
            "top_k": int(top_k),
            "seed": int(seed),
            "noise": float(noise),
            "batch_size": int(batch_size),
            "target_recall_definition": "source id appears in top-k for a noisy copy of that source vector",
            "memory_model": "streaming batches; stores only selected query source vectors outside the index",
            "default_target_sizes": [10_000_000, 50_000_000],
        },
        "preflight": preflight(output_path=output_path),
        "results": [
            run_size(
                count=size,
                dim=dim,
                query_count=query_count,
                top_k=top_k,
                seed=seed,
                noise=noise,
                batch_size=batch_size,
                engines=engines,
                target_recall=target_recall,
                target_p99_ms=target_p99_ms,
            )
            for size in size_list
        ],
    }
    add_slo_evaluation(
        payload,
        target_recall=target_recall,
        target_p99_ms=target_p99_ms,
        target_qps=target_qps,
        replicas=replicas,
        autoscaling_max_replicas=autoscaling_max_replicas,
        capacity_headroom=capacity_headroom,
        replica_hourly_cost_usd=replica_hourly_cost_usd,
        storage_gb_monthly_cost_usd=storage_gb_monthly_cost_usd,
        memory_payload_kb=memory_payload_kb,
        vector_dtype_bytes=vector_dtype_bytes,
    )
    return payload


def print_table(payload: dict[str, Any]) -> None:
    top_k = payload["scenario"]["top_k"]
    print(f"| vectors | engine | target recall@{top_k} | avg latency | p95 latency | p99 latency | build |")
    print("|---:|---|---:|---:|---:|---:|---:|")
    for size_result in payload["results"]:
        for result in size_result["results"]:
            if result.get("skipped"):
                print(f"| {size_result['vectors']} | {result['engine']} | skipped | - | - | - | - |")
                continue
            print(
                f"| {size_result['vectors']} | {result['engine']} | "
                f"{result['target_recall_at_k']:.3f} | "
                f"{result['avg_latency_ms']:.2f} ms | "
                f"{result['p95_latency_ms']:.2f} ms | "
                f"{result['p99_latency_ms']:.2f} ms | "
                f"{result['build_ms']:.1f} ms |"
            )


def print_plan_table(payload: dict[str, Any]) -> None:
    print("| vectors | engine | status | runner storage | local free | required local free | blockers |")
    print("|---:|---|---|---|---:|---:|---|")
    for row in payload.get("plans", []):
        blockers = ", ".join(row.get("blockers", [])) or "-"
        print(
            f"| {row['vectors']} | {row['engine']} | {row['status']} | "
            f"{row.get('runner_storage_root', 'state')} | "
            f"{row['disk_free_gb']:.2f} GB | {row['required_local_free_gb']:.2f} GB | {blockers} |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[10_000_000])
    parser.add_argument("--dim", type=int, default=128)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise", type=float, default=0.08)
    parser.add_argument("--batch-size", type=int, default=50_000)
    parser.add_argument("--target-recall", type=float, default=0.95)
    parser.add_argument("--target-p99-ms", type=float, default=100.0)
    parser.add_argument("--target-qps", type=float, default=100.0)
    parser.add_argument("--replicas", type=int, default=3)
    parser.add_argument("--autoscaling-max-replicas", type=int, default=24)
    parser.add_argument("--capacity-headroom", type=float, default=0.70)
    parser.add_argument("--replica-hourly-cost-usd", type=float, default=0.25)
    parser.add_argument("--storage-gb-monthly-cost-usd", type=float, default=0.10)
    parser.add_argument("--memory-payload-kb", type=float, default=2.0)
    parser.add_argument("--vector-dtype-bytes", type=int, default=4)
    parser.add_argument("--plan-only", action="store_true", help="Write a large-N preflight plan without generating vectors.")
    parser.add_argument("--planned-result-output", type=Path, default=None, help="Result JSON path embedded in plan-only reproduction commands.")
    parser.add_argument("--safety-factor", type=float, default=1.25, help="Disk safety factor for plan-only local index/transient storage estimates.")
    parser.add_argument("--disk-free-gb", type=float, default=None, help="Override local free disk for deterministic plan-only artifacts.")
    parser.add_argument(
        "--runner-storage-root",
        type=Path,
        default=None,
        help="Directory or mounted volume used for plan-only checkpoints and local index paths.",
    )
    parser.add_argument(
        "--checkpoint-path",
        type=Path,
        default=None,
        help="Enable resumable batch checkpointing for one size and one engine.",
    )
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=[
            "numpy-streaming",
            "faiss-persisted",
            "faiss-ivfpq-persisted",
            "qdrant-service",
            "qdrant-sharded-service",
            "pgvector-service",
            "pgvector-streaming",
        ],
        default=["faiss-persisted", "qdrant-service"],
    )
    parser.add_argument("--output", type=Path, default=Path("benchmarks/production_streaming_load_results.json"))
    args = parser.parse_args()
    if args.checkpoint_path and (len(args.sizes) != 1 or len(args.engines) != 1):
        parser.error("--checkpoint-path requires exactly one --sizes value and one --engines value")
    if args.checkpoint_path:
        os.environ["WAVEMIND_STREAMING_CHECKPOINT_PATH"] = str(args.checkpoint_path)
    if args.plan_only:
        payload = plan_streaming_load(
            sizes=args.sizes,
            dim=args.dim,
            query_count=args.queries,
            top_k=args.top_k,
            seed=args.seed,
            noise=args.noise,
            batch_size=args.batch_size,
            engines=args.engines,
            output_path=args.output,
            planned_result_output_path=args.planned_result_output,
            target_recall=args.target_recall,
            target_p99_ms=args.target_p99_ms,
            target_qps=args.target_qps,
            replicas=args.replicas,
            autoscaling_max_replicas=args.autoscaling_max_replicas,
            capacity_headroom=args.capacity_headroom,
            memory_payload_kb=args.memory_payload_kb,
            vector_dtype_bytes=args.vector_dtype_bytes,
            safety_factor=args.safety_factor,
            runner_storage_root=args.runner_storage_root,
            disk_free_gb_override=args.disk_free_gb,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print_plan_table(payload)
        print(f"\nWrote {args.output}")
        return 0
    payload = run_streaming_load(
        sizes=args.sizes,
        dim=args.dim,
        query_count=args.queries,
        top_k=args.top_k,
        seed=args.seed,
        noise=args.noise,
        batch_size=args.batch_size,
        engines=args.engines,
        output_path=args.output,
        target_recall=args.target_recall,
        target_p99_ms=args.target_p99_ms,
        target_qps=args.target_qps,
        replicas=args.replicas,
        autoscaling_max_replicas=args.autoscaling_max_replicas,
        capacity_headroom=args.capacity_headroom,
        replica_hourly_cost_usd=args.replica_hourly_cost_usd,
        storage_gb_monthly_cost_usd=args.storage_gb_monthly_cost_usd,
        memory_payload_kb=args.memory_payload_kb,
        vector_dtype_bytes=args.vector_dtype_bytes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_table(payload)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
