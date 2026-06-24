from __future__ import annotations

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

    def __init__(self, vector_dim: int, n_trees: int = 16):
        try:
            from annoy import AnnoyIndex
        except ImportError as exc:
            raise ImportError("Install annoy to use AnnoyVectorIndex") from exc
        super().__init__(vector_dim)
        self._AnnoyIndex = AnnoyIndex
        self.n_trees = int(n_trees)
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


def create_vector_index(kind: str, vector_dim: int):
    kind = (kind or "numpy").lower()
    if kind in {"numpy", "exact"}:
        return NumpyVectorIndex(vector_dim)
    if kind == "faiss":
        return FaissVectorIndex(vector_dim)
    if kind == "annoy":
        return AnnoyVectorIndex(vector_dim)
    raise ValueError(
        f"Unknown vector index kind: {kind}. Choose an explicit index: numpy, faiss, or annoy."
    )
