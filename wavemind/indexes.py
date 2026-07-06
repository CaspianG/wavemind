from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class IndexResult:
    id: int
    score: float


@dataclass(frozen=True)
class IndexHealth:
    backend: str
    vector_dim: int
    healthy: bool
    exact: bool
    expected_count: int | None = None
    vector_count: int | None = None
    missing_ids: tuple[int, ...] = ()
    extra_ids: tuple[int, ...] = ()
    dirty: bool = False
    persisted: bool = False
    loaded_from_persisted: bool = False
    path: str | None = None
    reason: str | None = None

    @property
    def missing_count(self) -> int:
        return len(self.missing_ids)

    @property
    def extra_count(self) -> int:
        return len(self.extra_ids)

    def as_dict(self, sample: int = 20) -> dict[str, object]:
        payload: dict[str, object] = {
            "backend": self.backend,
            "healthy": self.healthy,
            "exact": self.exact,
            "vector_dim": self.vector_dim,
            "expected_count": self.expected_count,
            "vector_count": self.vector_count,
            "missing_count": self.missing_count,
            "extra_count": self.extra_count,
            "missing_ids_sample": list(self.missing_ids[:sample]),
            "extra_ids_sample": list(self.extra_ids[:sample]),
            "dirty": self.dirty,
            "persisted": self.persisted,
            "loaded_from_persisted": self.loaded_from_persisted,
            "path": self.path,
        }
        if self.reason:
            payload["reason"] = self.reason
        return payload


def _index_health(
    *,
    backend: str,
    vector_dim: int,
    ids: Iterable[int] | None = None,
    expected_ids: Iterable[int] | None = None,
    vector_count: int | None = None,
    dirty: bool = False,
    persisted: bool = False,
    loaded_from_persisted: bool = False,
    path: str | None = None,
    reason: str | None = None,
) -> IndexHealth:
    expected = None if expected_ids is None else {int(id) for id in expected_ids}
    actual = None if ids is None else {int(id) for id in ids}
    if vector_count is None and actual is not None:
        vector_count = len(actual)
    expected_count = None if expected is None else len(expected)
    missing: tuple[int, ...] = ()
    extra: tuple[int, ...] = ()
    exact = actual is not None
    if exact and expected is not None:
        missing = tuple(sorted(expected - actual))
        extra = tuple(sorted(actual - expected))
        healthy = not missing and not extra
    elif expected_count is not None and vector_count is not None:
        healthy = expected_count == vector_count
    else:
        healthy = True
    return IndexHealth(
        backend=backend,
        vector_dim=int(vector_dim),
        healthy=healthy,
        exact=exact,
        expected_count=expected_count,
        vector_count=vector_count,
        missing_ids=missing,
        extra_ids=extra,
        dirty=dirty,
        persisted=persisted,
        loaded_from_persisted=loaded_from_persisted,
        path=path,
        reason=reason,
    )


def _normalize(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        return vector
    return (vector / norm).astype(np.float32)


def _quantize_unit_vector(vector: np.ndarray) -> np.ndarray:
    normalized = _normalize(vector)
    return np.clip(np.rint(normalized * 127.0), -127, 127).astype(np.int8)


def _vector_literal(vector: np.ndarray) -> str:
    normalized = _normalize(vector)
    return json.dumps([float(value) for value in normalized], separators=(",", ":"))


def _safe_identifier(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"{label} must be a simple SQL identifier")
    return value


def _env_positive_int(name: str, default: int | None = None) -> int | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return bool(default)
    return value.lower() in {"1", "true", "yes", "on"}


class NumpyVectorIndex:
    name = "numpy-exact"

    def __init__(self, vector_dim: int):
        self.vector_dim = int(vector_dim)
        self._vectors: dict[int, np.ndarray] = {}
        self._ids = np.array([], dtype=np.int64)
        self._id_to_pos: dict[int, int] = {}
        self._matrix = np.zeros((0, self.vector_dim), dtype=np.float32)
        self._dirty = True

    def add(self, id: int, vector: np.ndarray) -> None:
        self._vectors[int(id)] = _normalize(vector)
        self._dirty = True

    def remove(self, id: int) -> None:
        self._vectors.pop(int(id), None)
        self._dirty = True

    def build(self, records: Iterable) -> None:
        self._vectors.clear()
        for record in records:
            self.add(record.id, record.vector)
        self._dirty = True

    def _ensure_matrix(self) -> None:
        if not self._dirty:
            return
        if not self._vectors:
            self._ids = np.array([], dtype=np.int64)
            self._id_to_pos = {}
            self._matrix = np.zeros((0, self.vector_dim), dtype=np.float32)
            self._dirty = False
            return
        items = sorted(self._vectors.items())
        self._ids = np.array([id for id, _ in items], dtype=np.int64)
        self._id_to_pos = {int(id): pos for pos, (id, _) in enumerate(items)}
        self._matrix = np.stack([vector for _, vector in items]).astype(np.float32)
        self._dirty = False

    def search(
        self,
        vector: np.ndarray,
        top_k: int = 3,
        allowed_ids: set[int] | None = None,
    ) -> list[IndexResult]:
        if top_k <= 0 or not self._vectors:
            return []

        self._ensure_matrix()
        query = _normalize(vector)
        if allowed_ids is None:
            ids = self._ids
            matrix = self._matrix
        else:
            positions = [
                self._id_to_pos[int(id)]
                for id in allowed_ids
                if int(id) in self._id_to_pos
            ]
            if not positions:
                return []
            position_array = np.fromiter(positions, dtype=np.int64)
            ids = self._ids[position_array]
            matrix = self._matrix[position_array]
        if ids.size == 0:
            return []

        scores = matrix @ query
        order = np.argsort(scores)[::-1][:top_k]
        return [IndexResult(int(ids[int(i)]), float(scores[int(i)])) for i in order]

    def __len__(self) -> int:
        return len(self._vectors)

    def health(self, expected_ids: Iterable[int] | None = None) -> IndexHealth:
        return _index_health(
            backend=self.name,
            vector_dim=self.vector_dim,
            ids=self._vectors.keys(),
            expected_ids=expected_ids,
            dirty=self._dirty,
        )


class QuantizedVectorIndex:
    name = "quantized-int8"

    def __init__(self, vector_dim: int):
        self.vector_dim = int(vector_dim)
        self._vectors: dict[int, np.ndarray] = {}
        self._ids = np.array([], dtype=np.int64)
        self._id_to_pos: dict[int, int] = {}
        self._matrix_dtype = np.int16 if self.vector_dim <= 8192 else np.int32
        self._matrix = np.zeros((0, self.vector_dim), dtype=self._matrix_dtype)
        self._norms = np.ones((0,), dtype=np.float32)
        self._dirty = True

    def add(self, id: int, vector: np.ndarray) -> None:
        self._vectors[int(id)] = _quantize_unit_vector(vector)
        self._dirty = True

    def remove(self, id: int) -> None:
        self._vectors.pop(int(id), None)
        self._dirty = True

    def build(self, records: Iterable) -> None:
        self._vectors.clear()
        for record in records:
            self.add(record.id, record.vector)
        self._dirty = True

    def _ensure_matrix(self) -> None:
        if not self._dirty:
            return
        if not self._vectors:
            self._ids = np.array([], dtype=np.int64)
            self._id_to_pos = {}
            self._matrix = np.zeros((0, self.vector_dim), dtype=self._matrix_dtype)
            self._norms = np.ones((0,), dtype=np.float32)
            self._dirty = False
            return
        items = sorted(self._vectors.items())
        self._ids = np.array([id for id, _ in items], dtype=np.int64)
        self._id_to_pos = {int(id): pos for pos, (id, _) in enumerate(items)}
        self._matrix = np.stack([vector for _, vector in items]).astype(self._matrix_dtype)
        norms = np.linalg.norm(self._matrix.astype(np.float32), axis=1)
        self._norms = np.where(norms <= 1e-12, 1.0, norms).astype(np.float32)
        self._dirty = False

    def search(
        self,
        vector: np.ndarray,
        top_k: int = 3,
        allowed_ids: set[int] | None = None,
    ) -> list[IndexResult]:
        if top_k <= 0 or not self._vectors:
            return []

        self._ensure_matrix()
        query = _quantize_unit_vector(vector)
        query_norm = float(np.linalg.norm(query.astype(np.float32)))
        if query_norm <= 1e-12:
            query_norm = 1.0
        if allowed_ids is None:
            ids = self._ids
            matrix = self._matrix
            norms = self._norms
        else:
            positions = [
                self._id_to_pos[int(id)]
                for id in allowed_ids
                if int(id) in self._id_to_pos
            ]
            if not positions:
                return []
            position_array = np.fromiter(positions, dtype=np.int64)
            ids = self._ids[position_array]
            matrix = self._matrix[position_array]
            norms = self._norms[position_array]
        if ids.size == 0:
            return []

        dots = matrix @ query.astype(self._matrix_dtype)
        scores = dots.astype(np.float32) / (norms * query_norm)
        order = np.argsort(scores)[::-1][:top_k]
        return [IndexResult(int(ids[int(i)]), float(scores[int(i)])) for i in order]

    def __len__(self) -> int:
        return len(self._vectors)

    def health(self, expected_ids: Iterable[int] | None = None) -> IndexHealth:
        return _index_health(
            backend=self.name,
            vector_dim=self.vector_dim,
            ids=self._vectors.keys(),
            expected_ids=expected_ids,
            dirty=self._dirty,
        )


class FaissVectorIndex(NumpyVectorIndex):
    name = "faiss-flat-ip"

    def __init__(
        self,
        vector_dim: int,
        index_path: str | Path | None = None,
        autosave: bool | None = None,
    ):
        try:
            import faiss
        except ImportError as exc:
            raise ImportError("Install faiss-cpu to use FaissVectorIndex") from exc
        super().__init__(vector_dim)
        self._faiss = faiss
        self._index = faiss.IndexFlatIP(self.vector_dim)
        self._id_order: list[int] = []
        self._ann_dirty = True
        env_path = os.environ.get("WAVEMIND_FAISS_PATH")
        self.index_path = Path(index_path or env_path).expanduser() if index_path or env_path else None
        if autosave is None:
            autosave = os.environ.get("WAVEMIND_FAISS_AUTOSAVE", "1").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        self.autosave = bool(autosave)
        self.loaded_from_persisted = False

    @property
    def metadata_path(self) -> Path | None:
        if self.index_path is None:
            return None
        return self.index_path.with_name(self.index_path.name + ".ids.json")

    def build(self, records: Iterable) -> None:
        records = list(records)
        self._vectors.clear()
        for record in records:
            if record.id is not None:
                self._vectors[int(record.id)] = _normalize(record.vector)
        self._dirty = True
        self._ann_dirty = True
        expected_ids = sorted(int(record.id) for record in records if record.id is not None)
        if self._load_persisted(expected_ids=expected_ids):
            return
        self._ensure_ann()
        self._save_persisted()

    def add(self, id: int, vector: np.ndarray) -> None:
        self._vectors[int(id)] = _normalize(vector)
        self._dirty = True
        self._ann_dirty = True
        if self.autosave and self.index_path is not None:
            self._ensure_ann()
            self._save_persisted()

    def remove(self, id: int) -> None:
        self._vectors.pop(int(id), None)
        self._dirty = True
        self._ann_dirty = True
        if self.autosave and self.index_path is not None:
            self._ensure_ann()
            self._save_persisted()

    def _ensure_ann(self) -> None:
        if not self._ann_dirty:
            return
        items = sorted(self._vectors.items())
        self._id_order = [int(id) for id, _ in items]
        self._index = self._faiss.IndexFlatIP(self.vector_dim)
        if items:
            self._index.add(np.stack([vector for _, vector in items]).astype(np.float32))
        self._ann_dirty = False
        self.loaded_from_persisted = False

    def _load_persisted(self, expected_ids: list[int]) -> bool:
        metadata_path = self.metadata_path
        if self.index_path is None or metadata_path is None:
            return False
        if not self.index_path.exists() or not metadata_path.exists():
            return False
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        ids = [int(id) for id in metadata.get("ids", [])]
        if int(metadata.get("vector_dim", -1)) != self.vector_dim:
            return False
        if ids != expected_ids:
            return False
        try:
            self._index = self._faiss.read_index(str(self.index_path))
        except Exception:
            return False
        if getattr(self._index, "d", self.vector_dim) != self.vector_dim:
            return False
        self._id_order = ids
        self._ann_dirty = False
        self.loaded_from_persisted = True
        return True

    def _save_persisted(self) -> None:
        metadata_path = self.metadata_path
        if self.index_path is None or metadata_path is None:
            return
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self._faiss.write_index(self._index, str(self.index_path))
        metadata = {
            "backend": self.name,
            "vector_dim": self.vector_dim,
            "ids": self._id_order,
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _ann_search_limit(self, top_k: int, allowed_ids: set[int] | None) -> int:
        total = len(self._vectors)
        if allowed_ids is None:
            return min(top_k, total)
        allowed_count = sum(1 for id in allowed_ids if int(id) in self._vectors)
        if allowed_count <= 0:
            return 0
        if allowed_count == total:
            return min(top_k, total)
        if allowed_count / max(1, total) >= 0.80:
            return min(total, max(top_k * 8, top_k + 128))
        return 0

    def search(
        self,
        vector: np.ndarray,
        top_k: int = 3,
        allowed_ids: set[int] | None = None,
    ) -> list[IndexResult]:
        search_k = self._ann_search_limit(top_k, allowed_ids)
        if search_k <= 0:
            return super().search(vector, top_k=top_k, allowed_ids=allowed_ids)
        self._ensure_ann()
        if top_k <= 0 or not self._id_order:
            return []
        query = _normalize(vector).reshape(1, -1).astype(np.float32)
        scores, positions = self._index.search(query, search_k)
        results = []
        for score, pos in zip(scores[0], positions[0]):
            if pos < 0:
                continue
            id = self._id_order[int(pos)]
            if allowed_ids is not None and id not in allowed_ids:
                continue
            results.append(IndexResult(id, float(score)))
            if len(results) >= top_k:
                break
        return results

    def health(self, expected_ids: Iterable[int] | None = None) -> IndexHealth:
        ids = self._vectors.keys() if self._ann_dirty else self._id_order
        return _index_health(
            backend=self.name,
            vector_dim=self.vector_dim,
            ids=ids,
            expected_ids=expected_ids,
            dirty=self._ann_dirty,
            persisted=self.index_path is not None,
            loaded_from_persisted=self.loaded_from_persisted,
            path=str(self.index_path) if self.index_path is not None else None,
        )


class AnnoyVectorIndex(NumpyVectorIndex):
    name = "annoy-angular"

    def __init__(self, vector_dim: int, n_trees: int = 64, search_k_factor: int = 1024):
        try:
            from annoy import AnnoyIndex
        except ImportError as exc:
            raise ImportError("Install annoy to use AnnoyVectorIndex") from exc
        super().__init__(vector_dim)
        self._AnnoyIndex = AnnoyIndex
        self.n_trees = int(n_trees)
        self.search_k_factor = int(search_k_factor)
        self._index = AnnoyIndex(self.vector_dim, "angular")
        self._id_order: list[int] = []
        self._built = False
        self._ann_dirty = True

    def build(self, records: Iterable) -> None:
        self._vectors.clear()
        for record in records:
            self._vectors[int(record.id)] = _normalize(record.vector)
        self._dirty = True
        self._ann_dirty = True
        self._ensure_ann()

    def add(self, id: int, vector: np.ndarray) -> None:
        self._vectors[int(id)] = _normalize(vector)
        self._dirty = True
        self._ann_dirty = True
        self._built = False

    def remove(self, id: int) -> None:
        self._vectors.pop(int(id), None)
        self._dirty = True
        self._ann_dirty = True
        self._built = False

    def _ensure_ann(self) -> None:
        if not self._ann_dirty:
            return
        items = sorted(self._vectors.items())
        self._id_order = [int(id) for id, _ in items]
        self._index = self._AnnoyIndex(self.vector_dim, "angular")
        for pos, (_, vector) in enumerate(items):
            self._index.add_item(pos, vector.tolist())
        if self._id_order:
            self._index.build(self.n_trees)
        self._built = True
        self._ann_dirty = False

    def _ann_search_limit(self, top_k: int, allowed_ids: set[int] | None) -> int:
        total = len(self._vectors)
        if allowed_ids is None:
            return min(top_k, total)
        allowed_count = sum(1 for id in allowed_ids if int(id) in self._vectors)
        if allowed_count <= 0:
            return 0
        if allowed_count == total:
            return min(top_k, total)
        if allowed_count / max(1, total) >= 0.80:
            return min(total, max(top_k * 8, top_k + 128))
        return 0

    def search(
        self,
        vector: np.ndarray,
        top_k: int = 3,
        allowed_ids: set[int] | None = None,
    ) -> list[IndexResult]:
        search_k = self._ann_search_limit(top_k, allowed_ids)
        if search_k <= 0:
            return super().search(vector, top_k=top_k, allowed_ids=allowed_ids)
        self._ensure_ann()
        if top_k <= 0 or not self._id_order or not self._built:
            return []
        positions, distances = self._index.get_nns_by_vector(
            _normalize(vector).tolist(),
            search_k,
            search_k=max(self.n_trees * search_k, self.search_k_factor * top_k),
            include_distances=True,
        )
        results = []
        for pos, distance in zip(positions, distances):
            id = self._id_order[int(pos)]
            if allowed_ids is not None and id not in allowed_ids:
                continue
            score = 1.0 - (float(distance) * float(distance) / 2.0)
            results.append(IndexResult(id, score))
            if len(results) >= top_k:
                break
        return results

    def health(self, expected_ids: Iterable[int] | None = None) -> IndexHealth:
        ids = self._vectors.keys() if self._ann_dirty else self._id_order
        return _index_health(
            backend=self.name,
            vector_dim=self.vector_dim,
            ids=ids,
            expected_ids=expected_ids,
            dirty=self._ann_dirty,
        )


class PgVectorIndex:
    name = "pgvector-cosine"

    def __init__(
        self,
        vector_dim: int,
        dsn: str | None = None,
        table: str | None = None,
        collection: str | None = None,
        create_hnsw: bool | None = None,
        hnsw_m: int | None = None,
        hnsw_ef_construction: int | None = None,
        ef_search: int | None = None,
        exact_search: bool | None = None,
        iterative_scan: str | None = None,
        max_scan_tuples: int | None = None,
        scan_mem_multiplier: int | None = None,
    ):
        self.vector_dim = int(vector_dim)
        self.dsn = dsn or os.environ.get("WAVEMIND_PGVECTOR_DSN")
        if not self.dsn:
            raise ValueError(
                "Set WAVEMIND_PGVECTOR_DSN to use the pgvector index backend"
            )
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                'Install PostgreSQL support with: pip install "wavemind[postgres]"'
            ) from exc
        self._psycopg = psycopg
        self.table = _safe_identifier(
            table or os.environ.get("WAVEMIND_PGVECTOR_TABLE", "wavemind_vectors"),
            "WAVEMIND_PGVECTOR_TABLE",
        )
        self.collection = collection or os.environ.get(
            "WAVEMIND_PGVECTOR_COLLECTION",
            "default",
        )
        if create_hnsw is None:
            create_hnsw = _env_bool("WAVEMIND_PGVECTOR_CREATE_HNSW")
        self.create_hnsw = bool(create_hnsw)
        self.hnsw_m = hnsw_m or _env_positive_int("WAVEMIND_PGVECTOR_HNSW_M")
        self.hnsw_ef_construction = hnsw_ef_construction or _env_positive_int(
            "WAVEMIND_PGVECTOR_HNSW_EF_CONSTRUCTION"
        )
        self.ef_search = ef_search or _env_positive_int(
            "WAVEMIND_PGVECTOR_EF_SEARCH"
        )
        self.exact_search = (
            _env_bool("WAVEMIND_PGVECTOR_EXACT")
            if exact_search is None
            else bool(exact_search)
        )
        self.iterative_scan = iterative_scan or os.environ.get(
            "WAVEMIND_PGVECTOR_ITERATIVE_SCAN"
        )
        if self.iterative_scan and self.iterative_scan not in {
            "strict_order",
            "relaxed_order",
            "off",
        }:
            raise ValueError(
                "WAVEMIND_PGVECTOR_ITERATIVE_SCAN must be strict_order, relaxed_order, or off"
            )
        self.max_scan_tuples = max_scan_tuples or _env_positive_int(
            "WAVEMIND_PGVECTOR_MAX_SCAN_TUPLES"
        )
        self.scan_mem_multiplier = scan_mem_multiplier or _env_positive_int(
            "WAVEMIND_PGVECTOR_SCAN_MEM_MULTIPLIER"
        )
        self.conn = psycopg.connect(self.dsn, autocommit=True)
        self._closed = False
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        self.conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                collection TEXT NOT NULL,
                memory_id BIGINT NOT NULL,
                embedding vector({self.vector_dim}) NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (collection, memory_id)
            )
            """
        )
        self.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {self.table}_collection_idx "
            f"ON {self.table} (collection)"
        )
        if self.create_hnsw:
            options = []
            if self.hnsw_m is not None:
                options.append(f"m = {self.hnsw_m}")
            if self.hnsw_ef_construction is not None:
                options.append(f"ef_construction = {self.hnsw_ef_construction}")
            with_options = f" WITH ({', '.join(options)})" if options else ""
            self.conn.execute(
                f"CREATE INDEX IF NOT EXISTS {self.table}_embedding_hnsw_idx "
                f"ON {self.table} USING hnsw (embedding vector_cosine_ops)"
                f"{with_options}"
            )

    def add(self, id: int, vector: np.ndarray) -> None:
        self.conn.execute(
            f"""
            INSERT INTO {self.table} (
                collection, memory_id, embedding, updated_at
            ) VALUES (%s, %s, %s::vector, now())
            ON CONFLICT (collection, memory_id)
            DO UPDATE SET embedding = EXCLUDED.embedding, updated_at = now()
            """,
            (self.collection, int(id), _vector_literal(vector)),
        )

    def remove(self, id: int) -> None:
        self.conn.execute(
            f"DELETE FROM {self.table} WHERE collection = %s AND memory_id = %s",
            (self.collection, int(id)),
        )

    def build(self, records: Iterable) -> None:
        self.conn.execute(
            f"DELETE FROM {self.table} WHERE collection = %s",
            (self.collection,),
        )
        with self.conn.cursor() as cur:
            batch = []
            for record in records:
                if record.id is None:
                    continue
                batch.append((self.collection, int(record.id), _vector_literal(record.vector)))
                if len(batch) >= 1000:
                    self._insert_batch(cur, batch)
                    batch.clear()
            if batch:
                self._insert_batch(cur, batch)

    def _insert_batch(self, cur, rows: list[tuple[str, int, str]]) -> None:
        cur.executemany(
            f"""
            INSERT INTO {self.table} (
                collection, memory_id, embedding, updated_at
            ) VALUES (%s, %s, %s::vector, now())
            ON CONFLICT (collection, memory_id)
            DO UPDATE SET embedding = EXCLUDED.embedding, updated_at = now()
            """,
            rows,
        )

    def search(
        self,
        vector: np.ndarray,
        top_k: int = 3,
        allowed_ids: set[int] | None = None,
    ) -> list[IndexResult]:
        if top_k <= 0:
            return []
        self._apply_search_settings()
        query = _vector_literal(vector)
        params: list[object] = [query, self.collection]
        where = "collection = %s"
        if allowed_ids is not None:
            ids = sorted(int(id) for id in allowed_ids)
            if not ids:
                return []
            where += " AND memory_id = ANY(%s)"
            params.append(ids)
        params.extend([query, int(top_k)])
        try:
            rows = self.conn.execute(
                f"""
                SELECT memory_id, 1.0 - (embedding <=> %s::vector) AS score
                FROM {self.table}
                WHERE {where}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                params,
            ).fetchall()
            return [IndexResult(int(row[0]), float(row[1])) for row in rows]
        finally:
            if self.exact_search:
                self._restore_approximate_search_settings()

    def _apply_search_settings(self) -> None:
        if self.ef_search is not None:
            self.conn.execute(f"SET hnsw.ef_search = {self.ef_search}")
        if self.iterative_scan:
            self.conn.execute(f"SET hnsw.iterative_scan = '{self.iterative_scan}'")
        if self.max_scan_tuples is not None:
            self.conn.execute(f"SET hnsw.max_scan_tuples = {self.max_scan_tuples}")
        if self.scan_mem_multiplier is not None:
            self.conn.execute(
                f"SET hnsw.scan_mem_multiplier = {self.scan_mem_multiplier}"
            )
        if self.exact_search:
            self.conn.execute("SET enable_indexscan = off")
            self.conn.execute("SET enable_bitmapscan = off")

    def _restore_approximate_search_settings(self) -> None:
        self.conn.execute("SET enable_indexscan = on")
        self.conn.execute("SET enable_bitmapscan = on")

    def __len__(self) -> int:
        return int(
            self.conn.execute(
                f"SELECT COUNT(*) FROM {self.table} WHERE collection = %s",
                (self.collection,),
            ).fetchone()[0]
        )

    def ids(self) -> set[int]:
        rows = self.conn.execute(
            f"SELECT memory_id FROM {self.table} WHERE collection = %s",
            (self.collection,),
        ).fetchall()
        return {int(row[0]) for row in rows}

    def health(self, expected_ids: Iterable[int] | None = None) -> IndexHealth:
        try:
            return _index_health(
                backend=self.name,
                vector_dim=self.vector_dim,
                ids=self.ids(),
                expected_ids=expected_ids,
                dirty=False,
            )
        except Exception as exc:
            return _index_health(
                backend=self.name,
                vector_dim=self.vector_dim,
                ids=None,
                expected_ids=expected_ids,
                vector_count=len(self),
                dirty=False,
                reason=f"Exact pgvector id scan failed: {exc}",
            )

    def close(self) -> None:
        if self._closed:
            return
        self.conn.close()
        self._closed = True


class QdrantVectorIndex:
    name = "qdrant-cosine"

    def __init__(
        self,
        vector_dim: int,
        url: str | None = None,
        collection: str | None = None,
        api_key: str | None = None,
        recreate: bool | None = None,
    ):
        self.vector_dim = int(vector_dim)
        self.url = url or os.environ.get("WAVEMIND_QDRANT_URL")
        if not self.url:
            raise ValueError(
                "Set WAVEMIND_QDRANT_URL to use the qdrant index backend"
            )
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import (
                Distance,
                FieldCondition,
                Filter,
                MatchAny,
                PointStruct,
                VectorParams,
            )
        except ImportError as exc:
            raise ImportError(
                'Install Qdrant support with: pip install "wavemind[indexes]"'
            ) from exc

        self._Distance = Distance
        self._FieldCondition = FieldCondition
        self._Filter = Filter
        self._MatchAny = MatchAny
        self._PointStruct = PointStruct
        self._VectorParams = VectorParams
        self.collection = collection or os.environ.get(
            "WAVEMIND_QDRANT_COLLECTION",
            "wavemind_vectors",
        )
        self.api_key = api_key or os.environ.get("WAVEMIND_QDRANT_API_KEY")
        if recreate is None:
            recreate = os.environ.get("WAVEMIND_QDRANT_RECREATE", "0").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        if self.url == ":memory:":
            self.client = QdrantClient(":memory:")
        else:
            self.client = QdrantClient(url=self.url, api_key=self.api_key)
        self._closed = False
        self._ensure_collection(recreate=bool(recreate))

    def _collection_exists(self) -> bool:
        collection_exists = getattr(self.client, "collection_exists", None)
        if callable(collection_exists):
            return bool(collection_exists(collection_name=self.collection))
        try:
            self.client.get_collection(collection_name=self.collection)
            return True
        except Exception:
            return False

    def _ensure_collection(self, recreate: bool = False) -> None:
        vectors_config = self._VectorParams(
            size=self.vector_dim,
            distance=self._Distance.COSINE,
        )
        exists = self._collection_exists()
        if recreate:
            delete_collection = getattr(self.client, "delete_collection", None)
            if exists and callable(delete_collection):
                delete_collection(collection_name=self.collection)
                exists = False
            if exists:
                self.client.recreate_collection(
                    collection_name=self.collection,
                    vectors_config=vectors_config,
                )
                return
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=vectors_config,
            )
            return

        if not exists:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=vectors_config,
            )

    def _point(self, id: int, vector: np.ndarray):
        memory_id = int(id)
        return self._PointStruct(
            id=memory_id,
            vector=_normalize(vector).tolist(),
            payload={"memory_id": memory_id},
        )

    def add(self, id: int, vector: np.ndarray) -> None:
        self.client.upsert(
            collection_name=self.collection,
            points=[self._point(id, vector)],
        )

    def remove(self, id: int) -> None:
        self.client.delete(
            collection_name=self.collection,
            points_selector=[int(id)],
        )

    def build(self, records: Iterable) -> None:
        self._ensure_collection(recreate=True)
        points = []
        for record in records:
            if record.id is None:
                continue
            points.append(self._point(record.id, record.vector))
            if len(points) >= 1000:
                self.client.upsert(
                    collection_name=self.collection,
                    points=points,
                )
                points.clear()
        if points:
            self.client.upsert(
                collection_name=self.collection,
                points=points,
            )

    def _allowed_filter(self, allowed_ids: set[int] | None):
        if allowed_ids is None:
            return None
        ids = sorted(int(id) for id in allowed_ids)
        if not ids:
            return None
        return self._Filter(
            must=[
                self._FieldCondition(
                    key="memory_id",
                    match=self._MatchAny(any=ids),
                )
            ]
        )

    def search(
        self,
        vector: np.ndarray,
        top_k: int = 3,
        allowed_ids: set[int] | None = None,
    ) -> list[IndexResult]:
        if top_k <= 0:
            return []
        if allowed_ids is not None and not allowed_ids:
            return []
        query_filter = self._allowed_filter(allowed_ids)
        query = _normalize(vector).tolist()
        query_points = getattr(self.client, "query_points", None)
        if callable(query_points):
            response = query_points(
                collection_name=self.collection,
                query=query,
                query_filter=query_filter,
                limit=int(top_k),
                with_payload=True,
            )
            hits = getattr(response, "points", response)
        else:
            hits = self.client.search(
                collection_name=self.collection,
                query_vector=query,
                query_filter=query_filter,
                limit=int(top_k),
                with_payload=True,
            )

        results = []
        for hit in hits:
            payload = getattr(hit, "payload", None) or {}
            memory_id = int(payload.get("memory_id", getattr(hit, "id")))
            if allowed_ids is not None and memory_id not in allowed_ids:
                continue
            results.append(IndexResult(memory_id, float(getattr(hit, "score", 0.0))))
        return results

    def __len__(self) -> int:
        return int(
            self.client.count(
                collection_name=self.collection,
                exact=True,
            ).count
        )

    def ids(self) -> set[int]:
        scroll = getattr(self.client, "scroll", None)
        if not callable(scroll):
            raise RuntimeError("Qdrant client does not expose scroll")
        ids: set[int] = set()
        offset = None
        while True:
            points, offset = scroll(
                collection_name=self.collection,
                with_payload=True,
                limit=1024,
                offset=offset,
            )
            for point in points:
                payload = getattr(point, "payload", None) or {}
                ids.add(int(payload.get("memory_id", getattr(point, "id"))))
            if offset is None:
                return ids

    def health(self, expected_ids: Iterable[int] | None = None) -> IndexHealth:
        try:
            return _index_health(
                backend=self.name,
                vector_dim=self.vector_dim,
                ids=self.ids(),
                expected_ids=expected_ids,
                dirty=False,
            )
        except Exception as exc:
            return _index_health(
                backend=self.name,
                vector_dim=self.vector_dim,
                ids=None,
                expected_ids=expected_ids,
                vector_count=len(self),
                dirty=False,
                reason=f"Exact Qdrant id scan failed: {exc}",
            )

    def close(self) -> None:
        if self._closed:
            return
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
        self._closed = True


def create_vector_index(kind: str, vector_dim: int):
    kind = (kind or "numpy").lower()
    if kind in {"numpy", "exact"}:
        return NumpyVectorIndex(vector_dim)
    if kind in {"quantized", "int8"}:
        return QuantizedVectorIndex(vector_dim)
    if kind == "faiss":
        return FaissVectorIndex(vector_dim)
    if kind in {"faiss-persisted", "persisted-faiss"}:
        path = os.environ.get("WAVEMIND_FAISS_PATH")
        if not path:
            raise ValueError("Set WAVEMIND_FAISS_PATH to use the persisted FAISS backend")
        return FaissVectorIndex(vector_dim, index_path=path)
    if kind == "annoy":
        return AnnoyVectorIndex(vector_dim)
    if kind in {"pgvector", "postgres", "postgresql"}:
        return PgVectorIndex(vector_dim)
    if kind == "qdrant":
        return QdrantVectorIndex(vector_dim)
    raise ValueError(
        f"Unknown vector index kind: {kind}. Choose an explicit index: numpy, quantized, faiss, annoy, pgvector, or qdrant."
    )
