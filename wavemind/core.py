from __future__ import annotations

import time
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .encoders import (
    DEFAULT_TOKEN_STOPWORDS,
    FieldProjector,
    HashingTextEncoder,
    TextVectorEncoder,
    is_stopword_token,
    normalize_token,
)
from .field_graph import MemoryFieldGraph
from .indexes import create_vector_index
from .storage import AuditEvent, MemoryRecord, create_memory_store


LEXICAL_STOPWORDS = DEFAULT_TOKEN_STOPWORDS


class WaveField:
    def __init__(
        self,
        width: int = 128,
        height: int = 128,
        layers: int = 6,
        radius: int = 1,
        decay: float = 0.965,
        speed: float = 0.14,
        nonlin: float = 0.04,
        threshold_nl: float = 3e-4,
        stable_threshold: float = 8e-5,
    ):
        self.W = width
        self.H = height
        self.L = layers
        self.radius = radius
        self.decay = decay
        self.speed = speed
        self.nonlin = nonlin
        self.threshold_nl = threshold_nl
        self.stable_threshold = stable_threshold
        self.state = np.zeros((height, width, layers), dtype=np.float32)

    def feed(self, pattern: np.ndarray, strength: float = 1.0) -> None:
        h = min(self.H, pattern.shape[0])
        w = min(self.W, pattern.shape[1])
        noise = np.random.uniform(0.94, 1.06, (h, w, self.L)).astype(np.float32)
        self.state[:h, :w] += pattern[:h, :w, np.newaxis] * noise * strength

    def forget(self, pattern: np.ndarray, strength: float = 0.5) -> None:
        h = min(self.H, pattern.shape[0])
        w = min(self.W, pattern.shape[1])
        self.state[:h, :w] -= pattern[:h, :w, np.newaxis] * strength
        np.clip(self.state, -12.0, 12.0, out=self.state)

    def evolve(self, steps: int = 1) -> None:
        rad = self.radius
        for _ in range(steps):
            state = self.state
            neighbours = np.zeros_like(state)
            count = 0
            for dy in range(-rad, rad + 1):
                for dx in range(-rad, rad + 1):
                    if dx == 0 and dy == 0:
                        continue
                    neighbours += np.roll(np.roll(state, dy, axis=0), dx, axis=1)
                    count += 1
            average = neighbours / count
            diff = average - state
            diff = np.where(np.abs(diff) < self.threshold_nl, 0.0, diff)
            diff = diff * self.speed - self.nonlin * (state ** 2) * diff
            self.state = (state + diff) * self.decay

    def field_resonance(self, pattern: np.ndarray) -> float:
        h = min(self.H, pattern.shape[0])
        w = min(self.W, pattern.shape[1])
        field_mag = np.sum(np.abs(self.state[:h, :w]), axis=2)
        pat = pattern[:h, :w]
        denom = (np.linalg.norm(field_mag) * np.linalg.norm(pat)) + 1e-9
        return float(np.dot(field_mag.flatten(), pat.flatten()) / denom)

    def energy(self) -> float:
        return float(np.sum(self.state ** 2))

    def detect_clusters(self) -> list[list[tuple[int, int]]]:
        magnitude = np.sum(np.abs(self.state), axis=2)
        active = magnitude > self.stable_threshold
        visited = np.zeros((self.H, self.W), dtype=bool)
        clusters = []
        ys, xs = np.where(active)
        for y0, x0 in zip(ys.tolist(), xs.tolist()):
            if visited[y0, x0]:
                continue
            cluster = []
            stack = [(x0, y0)]
            visited[y0, x0] = True
            while stack:
                cx, cy = stack.pop()
                cluster.append((cx, cy))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < self.W and 0 <= ny < self.H:
                            if not visited[ny, nx] and active[ny, nx]:
                                visited[ny, nx] = True
                                stack.append((nx, ny))
            clusters.append(cluster)
        return clusters

    def reset(self) -> None:
        self.state[:] = 0.0


@dataclass(frozen=True)
class QueryResult:
    id: int
    text: str
    score: float
    vector_score: float
    field_score: float
    graph_score: float
    namespace: str
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class WaveMind:
    def __init__(
        self,
        db_path: str | Path | None = None,
        width: int = 128,
        height: int = 128,
        layers: int = 6,
        encoder: TextVectorEncoder | None = None,
        store: Any | None = None,
        store_kind: str | None = None,
        postgres_dsn: str | None = None,
        index_kind: str = "numpy",
        score_threshold: float = 0.0,
        evolve_on_feed: int = 6,
        vector_weight: float = 0.94,
        field_weight: float = 0.04,
        priority_weight: float = 0.02,
        lexical_weight: float = 0.20,
        short_query_lexical_weight: float = 2.0,
        max_lexical_token_frequency: int = 64,
        rerank_k: int = 10,
        field_disable_after: int = 1000,
        graph_weight: float = 0.0,
        graph_steps: int = 2,
        graph_expand_k: int = 10,
        persist_access_on_query: bool = False,
        query_feedback_strength: float = 0.0,
        audit_queries: bool = False,
    ):
        self.encoder = encoder or HashingTextEncoder(vector_dim=384)
        self.projector = FieldProjector(width, height, self.encoder.vector_dim)
        self.field = WaveField(width=width, height=height, layers=layers)
        self.graph = MemoryFieldGraph()
        self.store = store or create_memory_store(
            kind=store_kind,
            path=db_path,
            postgres_dsn=postgres_dsn,
        )
        self.index = create_vector_index(index_kind, self.encoder.vector_dim)
        self.score_threshold = float(score_threshold)
        self._evolve_n = int(evolve_on_feed)
        self.vector_weight = float(vector_weight)
        self.field_weight = float(field_weight)
        self.priority_weight = float(priority_weight)
        self.lexical_weight = float(lexical_weight)
        self.short_query_lexical_weight = float(short_query_lexical_weight)
        self.max_lexical_token_frequency = int(max_lexical_token_frequency)
        self.rerank_k = int(rerank_k)
        self.field_disable_after = int(field_disable_after)
        self.graph_weight = float(graph_weight)
        self.graph_steps = int(graph_steps)
        self.graph_expand_k = int(graph_expand_k)
        self.persist_access_on_query = bool(persist_access_on_query)
        self.query_feedback_strength = float(query_feedback_strength)
        self.audit_queries = bool(audit_queries)
        self._records_by_id: dict[int, MemoryRecord] = {}
        self._namespace_ids: dict[str, set[int]] = {}
        self._token_ids: dict[str, set[int]] = {}
        self._record_tokens: dict[int, frozenset[str]] = {}
        self._graph_dirty = True
        self._field_magnitude = np.zeros((height, width), dtype=np.float32)
        self._field_magnitude_norm = 0.0
        self.load()

    def remember(
        self,
        text: str,
        namespace: str = "default",
        tags: Iterable[str] | None = None,
        ttl_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
        priority: float = 1.0,
        strength: float = 1.0,
    ) -> int:
        vector = self.encoder.encode_vector(text)
        pattern = self.projector.to_pattern(vector)
        expires_at = time.time() + ttl_seconds if ttl_seconds is not None else None
        record = MemoryRecord(
            text=text,
            namespace=namespace,
            tags=tuple(tags or ()),
            metadata=metadata or {},
            vector=vector,
            pattern=pattern,
            expires_at=expires_at,
            priority=priority,
        )
        id = self.store.insert(record)
        record.id = id
        self._cache_record(record)
        self.index.add(id, vector)
        self._mark_graph_dirty()
        self.field.feed(pattern, strength=strength * priority)
        self.field.evolve(self._evolve_n)
        self._refresh_field_magnitude()
        self.store.log_audit_event(
            "remember",
            namespace=namespace,
            memory_id=id,
            metadata={
                "tags": list(record.tags),
                "ttl_seconds": ttl_seconds,
                "priority": float(priority),
                "text_length": len(text),
            },
        )
        return id

    def query(
        self,
        text: str,
        namespace: str = "default",
        top_k: int = 3,
        tags: Iterable[str] | None = None,
        min_score: float | None = None,
    ) -> list[QueryResult]:
        allowed_ids = self._allowed_ids(namespace=namespace, tags=tags)
        if not allowed_ids:
            return []

        query_vector = self.encoder.encode_vector(text)

        vector_top_k = max(top_k, self.rerank_k)
        candidates = self.index.search(
            query_vector,
            top_k=vector_top_k,
            allowed_ids=allowed_ids,
        )

        threshold = self.score_threshold if min_score is None else float(min_score)
        query_tokens = self._tokens(text)
        field_weight = self._effective_field_weight(len(allowed_ids))
        lexical_weight = self._effective_lexical_weight(query_tokens)
        candidate_scores = {candidate.id: candidate.score for candidate in candidates}
        for id in self._lexical_candidate_ids(query_tokens, allowed_ids):
            if id not in candidate_scores:
                record = self._records_by_id[id]
                candidate_scores[id] = float(np.dot(query_vector, record.vector))
        graph_scores: dict[int, float] = {}
        if self.graph_weight > 0.0 and candidate_scores:
            self._ensure_graph()
            graph_scores = self.graph.propagate(
                {id: max(0.0, score) for id, score in candidate_scores.items()},
                allowed_ids=allowed_ids,
                steps=self.graph_steps,
            )
            for id, _ in sorted(
                graph_scores.items(),
                key=lambda item: item[1],
                reverse=True,
            )[: max(0, self.graph_expand_k)]:
                if id not in candidate_scores and id in self._records_by_id:
                    record = self._records_by_id[id]
                    candidate_scores[id] = float(np.dot(query_vector, record.vector))

        results: list[QueryResult] = []
        for candidate_id, vector_score in candidate_scores.items():
            record = self._records_by_id[candidate_id]
            field_score = self._field_resonance(record.pattern) if field_weight > 0 else 0.0
            graph_score = graph_scores.get(candidate_id, self.graph.energy(candidate_id) if self.graph_weight > 0 else 0.0)
            priority_score = min(1.0, max(0.0, record.priority / 10.0))
            lexical_score = self._lexical_match(query_tokens, record.id, record.text)
            score = (
                self.vector_weight * vector_score
                + field_weight * field_score
                + self.graph_weight * graph_score
                + self.priority_weight * priority_score
                + lexical_weight * lexical_score
            )
            if score < threshold:
                continue
            results.append(
                QueryResult(
                    id=int(record.id),
                    text=record.text,
                    score=float(score),
                    vector_score=float(vector_score),
                    field_score=float(field_score),
                    graph_score=float(graph_score),
                    namespace=record.namespace,
                    tags=record.tags,
                    metadata=record.metadata,
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        selected = results[:top_k]
        for result in selected:
            record = self._records_by_id[result.id]
            record.access_count += 1
            record.priority += 0.05
            if self.persist_access_on_query:
                self.store.touch(result.id)
            if self.query_feedback_strength > 0:
                self.field.feed(record.pattern, strength=self.query_feedback_strength)
        if selected and self.query_feedback_strength > 0:
            self.field.evolve(1)
            self._refresh_field_magnitude()
        if selected and self.graph_weight > 0:
            self._ensure_graph()
        if self.audit_queries:
            self.store.log_audit_event(
                "query",
                namespace=namespace,
                metadata={
                    "top_k": int(top_k),
                    "result_count": len(selected),
                    "candidate_count": len(candidate_scores),
                    "tags": list(tags or []),
                    "min_score": threshold,
                },
            )
        return selected

    def forget(
        self,
        id: int | None = None,
        text: str | None = None,
        namespace: str | None = None,
    ) -> int:
        records = self.store.delete(id=id, text=text, namespace=namespace)
        for record in records:
            if record.id is not None:
                self.index.remove(record.id)
                self._uncache_record(record.id)
                self.graph.remove(record.id)
            self.field.forget(record.pattern, strength=0.7)
        if records:
            self.field.evolve(4)
            self._refresh_field_magnitude()
        for record in records:
            self.store.log_audit_event(
                "forget",
                namespace=record.namespace,
                memory_id=record.id,
                metadata={
                    "tags": list(record.tags),
                    "text_length": len(record.text),
                },
            )
        return len(records)

    def save(
        self,
        backup_path: str | Path | None = None,
        keep_last: int | None = None,
        backup_prefix: str = "wavemind",
    ) -> Path | None:
        commit = getattr(self.store, "commit", None)
        if callable(commit):
            commit()
        if backup_path is not None:
            backup_path = Path(backup_path)
            if backup_path.suffix:
                backup = getattr(self.store, "backup", None)
                if not callable(backup):
                    raise NotImplementedError(
                        "This memory store does not support file backups. "
                        "Use the database engine's native backup tooling."
                    )
                path = backup(backup_path)
            else:
                backup_timestamped = getattr(self.store, "backup_timestamped", None)
                if not callable(backup_timestamped):
                    raise NotImplementedError(
                        "This memory store does not support timestamped file backups. "
                        "Use the database engine's native backup tooling."
                    )
                path = backup_timestamped(
                    backup_path,
                    prefix=backup_prefix,
                    keep_last=keep_last,
                )
            self.store.log_audit_event(
                "backup",
                metadata={
                    "destination": str(path),
                    "keep_last": keep_last,
                    "prefix": backup_prefix,
                },
            )
            return path
        return None

    def close(self) -> None:
        close_index = getattr(self.index, "close", None)
        if callable(close_index):
            close_index()
        self.store.close()

    def __enter__(self) -> "WaveMind":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def load(self) -> None:
        records = self.store.list(include_expired=False)
        self._build_cache(records)
        self.index.build(records)
        self._mark_graph_dirty()
        if self.graph_weight > 0:
            self._ensure_graph()
        self.field.reset()
        for record in records:
            self.field.feed(record.pattern, strength=max(0.1, record.priority))
        if records:
            self.field.evolve(self._evolve_n)
        self._refresh_field_magnitude()

    def purge_expired(self) -> int:
        purged = self.store.purge_expired()
        if purged:
            self.load()
            self.store.log_audit_event("purge_expired", metadata={"deleted": purged})
        return purged

    def consolidate(self, steps: int = 40) -> None:
        self.field.evolve(steps)
        self._refresh_field_magnitude()
        if self.graph_weight > 0:
            self._ensure_graph()
            self.graph.decay_energy(steps=max(1, steps // 10))

    def stats(self, namespace: str | None = None) -> dict[str, Any]:
        active = self.store.list(namespace=namespace, include_expired=False)
        all_records = self.store.list(namespace=namespace, include_expired=True)
        expired = [record for record in all_records if record.is_expired]
        clusters = self.field.detect_clusters()
        payload = {
            "active_memories": len(active),
            "expired_memories": len(expired),
            "total_memories": len(all_records),
            "audit_events": self.store.audit_count(namespace=namespace),
            "field_energy": round(self.field.energy(), 6),
            "clusters": len(clusters),
            "field_shape": f"{self.field.H}x{self.field.W}x{self.field.L}",
            "index": getattr(self.index, "name", type(self.index).__name__),
            "vector_dim": self.encoder.vector_dim,
            "graph_enabled": self.graph_weight > 0.0,
        }
        if self.graph_weight > 0.0:
            self._ensure_graph()
            payload.update(self.graph.stats())
        else:
            payload.update(
                {
                    "graph_nodes": len(self._records_by_id),
                    "graph_edges": 0,
                    "graph_positive_edges": 0,
                    "graph_negative_edges": 0,
                    "graph_energy": 0.0,
                }
            )
        return payload

    def audit_events(
        self,
        namespace: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        return self.store.list_audit_events(
            namespace=namespace,
            action=action,
            limit=limit,
        )

    def concept_candidates(
        self,
        namespace: str | None = None,
        min_energy: float = 0.05,
        min_size: int = 2,
    ) -> list[dict[str, object]]:
        self._ensure_graph()
        concepts = self.graph.concept_candidates(min_energy=min_energy, min_size=min_size)
        if namespace is None:
            return concepts
        allowed_ids = self._namespace_ids.get(namespace, set())
        return [
            concept
            for concept in concepts
            if set(concept["memory_ids"]).issubset(allowed_ids)
        ]

    @property
    def memory(self) -> list[tuple[str, np.ndarray]]:
        return [(record.text, record.pattern) for record in self._records_by_id.values()]

    def _build_cache(self, records: Iterable[MemoryRecord]) -> None:
        self._records_by_id.clear()
        self._namespace_ids.clear()
        self._token_ids.clear()
        self._record_tokens.clear()
        for record in records:
            self._cache_record(record)
        self._mark_graph_dirty()

    def _cache_record(self, record: MemoryRecord) -> None:
        if record.id is None:
            return
        id = int(record.id)
        self._records_by_id[id] = record
        self._namespace_ids.setdefault(record.namespace, set()).add(id)
        tokens = self._tokens(record.text)
        self._record_tokens[id] = frozenset(tokens)
        for token in tokens:
            self._token_ids.setdefault(token, set()).add(id)
        self._mark_graph_dirty()

    def _uncache_record(self, id: int) -> None:
        record = self._records_by_id.pop(int(id), None)
        if record is None:
            return
        ids = self._namespace_ids.get(record.namespace)
        if ids is not None:
            ids.discard(int(id))
            if not ids:
                self._namespace_ids.pop(record.namespace, None)
        tokens = self._record_tokens.pop(int(id), None)
        if tokens is None:
            tokens = frozenset(self._tokens(record.text))
        for token in tokens:
            token_ids = self._token_ids.get(token)
            if token_ids is None:
                continue
            token_ids.discard(int(id))
            if not token_ids:
                self._token_ids.pop(token, None)
        self._mark_graph_dirty()

    def _mark_graph_dirty(self) -> None:
        self._graph_dirty = True

    def _ensure_graph(self) -> None:
        if not self._graph_dirty:
            return
        self.graph.build(self._records_by_id.values())
        self._graph_dirty = False

    def _allowed_ids(
        self,
        namespace: str,
        tags: Iterable[str] | None = None,
    ) -> set[int]:
        ids = set(self._namespace_ids.get(namespace, set()))
        required_tags = set(tags or ())
        if not ids:
            return set()
        allowed = set()
        for id in ids:
            record = self._records_by_id[id]
            if record.is_expired:
                continue
            if required_tags and not required_tags.issubset(set(record.tags)):
                continue
            allowed.add(id)
        return allowed

    def _refresh_field_magnitude(self) -> None:
        self._field_magnitude = np.sum(np.abs(self.field.state), axis=2)
        self._field_magnitude_norm = float(np.linalg.norm(self._field_magnitude))

    def _field_resonance(self, pattern: np.ndarray) -> float:
        denom = (self._field_magnitude_norm * float(np.linalg.norm(pattern))) + 1e-9
        return float(np.dot(self._field_magnitude.ravel(), pattern.ravel()) / denom)

    def _effective_field_weight(self, allowed_count: int) -> float:
        if self.field_disable_after > 0 and allowed_count > self.field_disable_after:
            return 0.0
        return self.field_weight

    def _effective_lexical_weight(self, query_tokens: tuple[str, ...]) -> float:
        if 0 < len(query_tokens) <= 2:
            return self.short_query_lexical_weight
        return self.lexical_weight

    def _tokens(self, text: str) -> tuple[str, ...]:
        return tuple(
            normalized
            for token in re.findall(r"[\w]+", text.lower(), flags=re.UNICODE)
            for normalized in (normalize_token(token),)
            if normalized not in LEXICAL_STOPWORDS and not is_stopword_token(token)
        )

    def _lexical_match(self, query_tokens: tuple[str, ...], id: int | None, text: str) -> float:
        if not query_tokens:
            return 0.0
        text_tokens = self._record_tokens.get(int(id)) if id is not None else None
        if text_tokens is None:
            text_tokens = frozenset(self._tokens(text))
        matched = sum(1 for token in query_tokens if token in text_tokens)
        return matched / len(query_tokens)

    def _lexical_candidate_ids(
        self,
        query_tokens: tuple[str, ...],
        allowed_ids: set[int],
    ) -> set[int]:
        candidate_ids: set[int] = set()
        for token in query_tokens:
            token_ids = self._token_ids.get(token, set()) & allowed_ids
            if (
                self.max_lexical_token_frequency > 0
                and len(token_ids) > self.max_lexical_token_frequency
            ):
                continue
            candidate_ids.update(token_ids)
        return candidate_ids & allowed_ids
