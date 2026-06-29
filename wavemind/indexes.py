from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class IndexResult:
    id: int
    score: float


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


class FaissVectorIndex(NumpyVectorIndex):
    name = "faiss-flat-ip"

    def __init__(self, vector_dim: int):
        try:
            import faiss
        except ImportError as exc:
            raise ImportError("Install faiss-cpu to use FaissVectorIndex") from exc
        super().__init__(vector_dim)
        self._faiss = faiss
        self._index = faiss.IndexFlatIP(self.vector_dim)
        self._id_order: list[int] = []
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

    def remove(self, id: int) -> None:
        self._vectors.pop(int(id), None)
        self._dirty = True
        self._ann_dirty = True

    def _ensure_ann(self) -> None:
        if not self._ann_dirty:
            return
        items = sorted(self._vectors.items())
        self._id_order = [int(id) for id, _ in items]
        self._index = self._faiss.IndexFlatIP(self.vector_dim)
        if items:
            self._index.add(np.stack([vector for _, vector in items]).astype(np.float32))
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


class PgVectorIndex:
    name = "pgvector-cosine"

    def __init__(
        self,
        vector_dim: int,
        dsn: str | None = None,
        table: str | None = None,
        collection: str | None = None,
        create_hnsw: bool | None = None,
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
            create_hnsw = os.environ.get("WAVEMIND_PGVECTOR_CREATE_HNSW", "0").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        self.create_hnsw = bool(create_hnsw)
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
            self.conn.execute(
                f"CREATE INDEX IF NOT EXISTS {self.table}_embedding_hnsw_idx "
                f"ON {self.table} USING hnsw (embedding vector_cosine_ops)"
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
        rows = [
            (self.collection, int(record.id), _vector_literal(record.vector))
            for record in records
            if record.id is not None
        ]
        if not rows:
            return
        with self.conn.cursor() as cur:
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

    def __len__(self) -> int:
        return int(
            self.conn.execute(
                f"SELECT COUNT(*) FROM {self.table} WHERE collection = %s",
                (self.collection,),
            ).fetchone()[0]
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
        points = [
            self._point(record.id, record.vector)
            for record in records
            if record.id is not None
        ]
        for offset in range(0, len(points), 1000):
            self.client.upsert(
                collection_name=self.collection,
                points=points[offset : offset + 1000],
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
    if kind == "annoy":
        return AnnoyVectorIndex(vector_dim)
    if kind in {"pgvector", "postgres", "postgresql"}:
        return PgVectorIndex(vector_dim)
    if kind == "qdrant":
        return QdrantVectorIndex(vector_dim)
    raise ValueError(
        f"Unknown vector index kind: {kind}. Choose an explicit index: numpy, quantized, faiss, annoy, pgvector, or qdrant."
    )
