from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

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
from .observability import trace_span
from .scale import ScalePlan, build_scale_plan
from .storage import (
    AuditEvent,
    MemoryRecord,
    append_recovery_journal_entry,
    create_memory_store,
)


LEXICAL_STOPWORDS = DEFAULT_TOKEN_STOPWORDS
_AUDIT_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|authorization|password|secret|token)"
    r"\s*([=:])\s*([^\s&,;]+)"
)
_AUDIT_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_AUDIT_PROVIDER_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def _redact_audit_text(value: object) -> str:
    text = str(value)
    text = _AUDIT_SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        text,
    )
    text = _AUDIT_BEARER_RE.sub("Bearer [REDACTED]", text)
    return _AUDIT_PROVIDER_KEY_RE.sub("[REDACTED]", text)


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
        np.clip(self.state, -12.0, 12.0, out=self.state)

    def forget(self, pattern: np.ndarray, strength: float = 0.5) -> None:
        h = min(self.H, pattern.shape[0])
        w = min(self.W, pattern.shape[1])
        self.state[:h, :w] -= pattern[:h, :w, np.newaxis] * strength
        np.clip(self.state, -12.0, 12.0, out=self.state)

    def evolve(self, steps: int = 1) -> None:
        rad = self.radius
        for _ in range(steps):
            np.clip(self.state, -12.0, 12.0, out=self.state)
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
            self.state = np.clip((state + diff) * self.decay, -12.0, 12.0)

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
    confidence_reason: str = ""


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
        recovery_journal_path: str | Path | None = None,
        shared_store_refresh_seconds: float = -1.0,
        confidence_gate: bool = True,
        hash_confidence_threshold: float = 0.12,
        hash_lexical_coverage_threshold: float = 1.0 / 3.0,
        semantic_confidence_threshold: float = 0.28,
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
        self.recovery_journal_path = Path(recovery_journal_path) if recovery_journal_path else None
        self.shared_store_refresh_seconds = float(shared_store_refresh_seconds)
        self.confidence_gate = bool(confidence_gate)
        self.hash_confidence_threshold = float(hash_confidence_threshold)
        self.hash_lexical_coverage_threshold = float(hash_lexical_coverage_threshold)
        self.semantic_confidence_threshold = float(semantic_confidence_threshold)
        self._namespace_store_refresh_at: dict[str, float] = {}
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
        with trace_span(
            "wavemind.remember.encode",
            {
                "wavemind.namespace": namespace,
                "wavemind.text_length": len(text),
                "wavemind.vector_dim": self.encoder.vector_dim,
            },
        ):
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
        with trace_span("wavemind.remember.store", {"wavemind.namespace": namespace}):
            id = self.store.insert(record)
        record.id = id
        self._cache_record(record)
        with trace_span(
            "wavemind.remember.index",
            {
                "wavemind.index": getattr(self.index, "name", type(self.index).__name__),
                "wavemind.memory_id": int(id),
            },
        ):
            self.index.add(id, vector)
        self._mark_graph_dirty()
        with trace_span("wavemind.remember.field", {"wavemind.evolve_steps": self._evolve_n}):
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
        self._append_recovery_journal("remember", [record])
        return id

    def remember_batch(
        self,
        items: Iterable[Mapping[str, Any]],
    ) -> list[int]:
        """Remember heterogeneous items using one storage transaction."""
        normalized = [dict(item) for item in items]
        if not normalized:
            return []
        texts = [str(item["text"]) for item in normalized]
        with trace_span(
            "wavemind.remember_batch.encode",
            {
                "wavemind.batch_size": len(normalized),
                "wavemind.vector_dim": self.encoder.vector_dim,
            },
        ):
            vectors = np.asarray(
                self.encoder.encode_vectors(texts),
                dtype=np.float32,
            )
            expected_shape = (len(normalized), self.encoder.vector_dim)
            if vectors.shape != expected_shape:
                raise ValueError(
                    "encoder returned batch shape "
                    f"{vectors.shape}, expected {expected_shape}"
                )
            patterns = [
                self.projector.to_pattern(vector)
                for vector in vectors
            ]

        now = time.time()
        records: list[MemoryRecord] = []
        strengths: list[float] = []
        ttl_values: list[float | None] = []
        for item, text, vector, pattern in zip(
            normalized,
            texts,
            vectors,
            patterns,
        ):
            ttl_seconds = item.get("ttl_seconds")
            ttl = (
                float(ttl_seconds)
                if ttl_seconds is not None
                else None
            )
            priority = float(item.get("priority", 1.0))
            records.append(
                MemoryRecord(
                    text=text,
                    namespace=str(item.get("namespace", "default")),
                    tags=tuple(item.get("tags") or ()),
                    metadata=dict(item.get("metadata") or {}),
                    vector=vector,
                    pattern=pattern,
                    expires_at=now + ttl if ttl is not None else None,
                    priority=priority,
                )
            )
            strengths.append(float(item.get("strength", 1.0)))
            ttl_values.append(ttl)

        with trace_span(
            "wavemind.remember_batch.store",
            {"wavemind.batch_size": len(records)},
        ):
            insert_many = getattr(self.store, "insert_many", None)
            if callable(insert_many):
                ids = [int(value) for value in insert_many(records)]
            else:
                ids = [int(self.store.insert(record)) for record in records]
        if len(ids) != len(records):
            raise RuntimeError(
                f"store inserted {len(ids)} records for a batch of {len(records)}"
            )

        for record, memory_id in zip(records, ids):
            record.id = memory_id
            self._cache_record(record)
            self.index.add(memory_id, record.vector)
        self._mark_graph_dirty()
        with trace_span(
            "wavemind.remember_batch.field",
            {
                "wavemind.batch_size": len(records),
                "wavemind.evolve_steps": self._evolve_n,
            },
        ):
            for record, strength in zip(records, strengths):
                self.field.feed(
                    record.pattern,
                    strength=strength * record.priority,
                )
                self.field.evolve(self._evolve_n)
            self._refresh_field_magnitude()

        audit_events = [
            AuditEvent(
                action="remember",
                created_at=time.time(),
                namespace=record.namespace,
                memory_id=memory_id,
                metadata={
                    "tags": list(record.tags),
                    "ttl_seconds": ttl_seconds,
                    "priority": float(record.priority),
                    "text_length": len(record.text),
                    "batch": True,
                },
            )
            for record, memory_id, ttl_seconds in zip(
                records,
                ids,
                ttl_values,
            )
        ]
        log_audit_events = getattr(self.store, "log_audit_events", None)
        if callable(log_audit_events):
            log_audit_events(audit_events)
        else:
            for event in audit_events:
                self.store.log_audit_event(
                    event.action,
                    namespace=event.namespace,
                    memory_id=event.memory_id,
                    metadata=event.metadata,
                )
        self._append_recovery_journal(
            "remember",
            records,
            metadata={"batch": True, "count": len(records)},
        )
        return ids

    def supersede(
        self,
        id: int,
        text: str,
        *,
        namespace: str | None = None,
        tags: Iterable[str] | None = None,
        ttl_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
        priority: float | None = None,
        strength: float = 1.0,
        transition_id: str | None = None,
    ) -> int:
        """Create a verified replacement while retaining predecessor provenance."""

        predecessor = self.store.get(int(id))
        if predecessor is None or predecessor.is_expired:
            raise KeyError(f"memory not found: {id}")
        selected_namespace = predecessor.namespace if namespace is None else str(namespace)
        if selected_namespace != predecessor.namespace:
            raise ValueError("replacement must remain in the same namespace")
        replacement_metadata = dict(predecessor.metadata)
        for lifecycle_key in (
            "_wavemind_transition",
            "memory_status",
            "verification_status",
            "verified",
            "provenance",
        ):
            replacement_metadata.pop(lifecycle_key, None)
        replacement_metadata.update(dict(metadata or {}))
        with trace_span(
            "wavemind.supersede.encode",
            {
                "wavemind.namespace": selected_namespace,
                "wavemind.predecessor_id": int(id),
                "wavemind.text_length": len(text),
            },
        ):
            vector = self.encoder.encode_vector(text)
            pattern = self.projector.to_pattern(vector)
        expires_at = (
            time.time() + float(ttl_seconds)
            if ttl_seconds is not None
            else predecessor.expires_at
        )
        replacement = MemoryRecord(
            text=text,
            namespace=selected_namespace,
            tags=tuple(predecessor.tags if tags is None else tags),
            metadata=replacement_metadata,
            vector=vector,
            pattern=pattern,
            expires_at=expires_at,
            priority=(predecessor.priority if priority is None else float(priority)),
        )
        store_supersede = getattr(self.store, "supersede", None)
        if not callable(store_supersede):
            raise RuntimeError("configured memory store does not support supersede")
        with trace_span(
            "wavemind.supersede.store",
            {
                "wavemind.namespace": selected_namespace,
                "wavemind.predecessor_id": int(id),
            },
        ):
            stored_predecessor, stored_replacement, inserted = store_supersede(
                int(id), replacement, transition_id=transition_id
            )
        if stored_replacement.id is None:
            raise RuntimeError("memory store returned an unpersisted replacement")
        replacement_id = int(stored_replacement.id)
        if not inserted:
            if replacement_id not in self._records_by_id:
                self._cache_record(stored_replacement)
                self.index.add(replacement_id, stored_replacement.vector)
            return replacement_id
        self._uncache_record(int(id))
        self._cache_record(stored_predecessor)
        self._cache_record(stored_replacement)
        self.index.add(replacement_id, stored_replacement.vector)
        self._mark_graph_dirty()
        self.field.forget(predecessor.pattern, strength=0.7)
        self.field.feed(
            stored_replacement.pattern,
            strength=float(strength) * stored_replacement.priority,
        )
        self.field.evolve(max(1, self._evolve_n))
        self._refresh_field_magnitude()
        self._append_recovery_journal(
            "supersede",
            [stored_predecessor, stored_replacement],
            metadata={
                "predecessor_id": int(id),
                "replacement_id": replacement_id,
                "transition_id": stored_replacement.metadata[
                    "_wavemind_transition"
                ]["transition_id"],
            },
        )
        return replacement_id

    def query(
        self,
        text: str,
        namespace: str = "default",
        top_k: int = 3,
        tags: Iterable[str] | None = None,
        min_score: float | None = None,
        query_vector: np.ndarray | None = None,
        metadata_filters: Mapping[str, Any] | None = None,
    ) -> list[QueryResult]:
        self._refresh_namespace_if_due(namespace)
        allowed_ids = self._allowed_ids(
            namespace=namespace,
            tags=tags,
            metadata_filters=metadata_filters,
        )
        if not allowed_ids:
            return []

        if query_vector is None:
            with trace_span(
                "wavemind.query.encode",
                {
                    "wavemind.namespace": namespace,
                    "wavemind.top_k": int(top_k),
                    "wavemind.allowed_ids": len(allowed_ids),
                },
            ):
                query_vector = self.encoder.encode_vector(text)
        else:
            query_vector = np.asarray(query_vector, dtype=np.float32)

        vector_top_k = max(top_k, self.rerank_k)
        with trace_span(
            "wavemind.query.index_search",
            {
                "wavemind.index": getattr(self.index, "name", type(self.index).__name__),
                "wavemind.top_k": int(vector_top_k),
                "wavemind.allowed_ids": len(allowed_ids),
            },
        ):
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
            with trace_span(
                "wavemind.query.graph",
                {
                    "wavemind.graph_steps": self.graph_steps,
                    "wavemind.candidate_count": len(candidate_scores),
                },
            ):
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
        with trace_span(
            "wavemind.query.rerank",
            {
                "wavemind.candidate_count": len(candidate_scores),
                "wavemind.field_weight": field_weight,
                "wavemind.lexical_weight": lexical_weight,
            },
        ):
            for candidate_id, vector_score in candidate_scores.items():
                record = self._records_by_id[candidate_id]
                field_score = self._field_resonance(record.pattern) if field_weight > 0 else 0.0
                graph_score = graph_scores.get(candidate_id, self.graph.energy(candidate_id) if self.graph_weight > 0 else 0.0)
                priority_score = min(1.0, max(0.0, record.priority / 10.0))
                lexical_score = self._lexical_match(query_tokens, record.id, record.text)
                confidence_reason = self._confidence_reason(
                    record,
                    vector_score=float(vector_score),
                    lexical_score=float(lexical_score),
                )
                if confidence_reason is None:
                    continue
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
                        confidence_reason=confidence_reason,
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
                    "query": _redact_audit_text(text),
                    "top_k": int(top_k),
                    "result_count": len(selected),
                    "candidate_count": len(candidate_scores),
                    "tags": list(tags or []),
                    "min_score": threshold,
                    "metadata_filters": self._serializable_metadata_filters(
                        metadata_filters
                    ),
                },
            )
        return selected

    def confidence_policy(self) -> dict[str, Any]:
        encoder_name = type(self.encoder).__name__
        is_hash = encoder_name == "HashingTextEncoder"
        return {
            "enabled": self.confidence_gate,
            "encoder": encoder_name,
            "mode": (
                "lexical_and_vector"
                if is_hash
                else "semantic_vector_or_exact_lexical"
            ),
            "vector_threshold": (
                self.hash_confidence_threshold
                if is_hash
                else self.semantic_confidence_threshold
            ),
            "lexical_coverage_threshold": self.hash_lexical_coverage_threshold,
            "blocks_unverified_or_stale": True,
        }

    def _confidence_reason(
        self,
        record: MemoryRecord,
        *,
        vector_score: float,
        lexical_score: float,
    ) -> str | None:
        if not self.confidence_gate:
            return "confidence_gate_disabled"
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        verification_status = str(metadata.get("verification_status") or "").strip().lower()
        memory_status = str(metadata.get("memory_status") or "").strip().lower()
        blocked_statuses = {
            "unverified",
            "rejected",
            "stale",
            "contradictory",
            "rolled_back",
        }
        if verification_status in blocked_statuses or memory_status in blocked_statuses:
            return None
        if metadata.get("stale") is True or metadata.get("contradictory") is True:
            return None
        trust = str(metadata.get("trust") or "").strip().lower()
        if trust in {"unverified", "tool_output", "model_generated"} and metadata.get("verified") is not True:
            return None
        if type(self.encoder).__name__ == "HashingTextEncoder":
            if (
                lexical_score < self.hash_lexical_coverage_threshold
                or vector_score < self.hash_confidence_threshold
            ):
                return None
            return "lexical_and_vector_match"
        if lexical_score >= self.hash_lexical_coverage_threshold:
            return "exact_lexical_match"
        if vector_score < self.semantic_confidence_threshold:
            return None
        return "semantic_vector_match"

    def forget(
        self,
        id: int | None = None,
        text: str | None = None,
        namespace: str | None = None,
    ) -> int:
        with trace_span(
            "wavemind.forget.store",
            {
                "wavemind.namespace": namespace,
                "wavemind.memory_id": id,
                "wavemind.has_text": text is not None,
            },
        ):
            records = self.store.delete(id=id, text=text, namespace=namespace)
        for record in records:
            if record.id is not None:
                with trace_span(
                    "wavemind.forget.index",
                    {
                        "wavemind.index": getattr(self.index, "name", type(self.index).__name__),
                        "wavemind.memory_id": int(record.id),
                    },
                ):
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
        self._append_recovery_journal("forget", records)
        return len(records)

    def feedback(
        self,
        id: int,
        useful: bool = True,
        strength: float = 0.25,
        namespace: str | None = None,
        query: str | None = None,
        reason: str | None = None,
    ) -> bool:
        record = self._records_by_id.get(int(id))
        if record is None or record.is_expired:
            return False
        if namespace is not None and record.namespace != namespace:
            return False
        self._apply_feedback_signal(
            record,
            useful=useful,
            strength=strength,
            query=query,
            reason=reason,
        )
        self.field.evolve(1)
        self._refresh_field_magnitude()
        return True

    def feedback_batch(
        self,
        signals: Iterable[Mapping[str, Any]],
        *,
        namespace: str | None = None,
    ) -> dict[str, object]:
        accepted: list[dict[str, object]] = []
        rejected: list[dict[str, object]] = []
        feedback_updates: list[dict[str, object]] = []
        for raw_signal in signals:
            signal = dict(raw_signal)
            try:
                memory_id = int(signal["id"])
            except Exception:
                rejected.append(
                    {
                        "id": signal.get("id"),
                        "namespace": signal.get("namespace", namespace),
                        "error": "invalid_id",
                    }
                )
                continue
            signal_namespace = signal.get("namespace", namespace)
            record = self._records_by_id.get(memory_id)
            if record is None or record.is_expired:
                rejected.append(
                    {
                        "id": memory_id,
                        "namespace": signal_namespace,
                        "error": "memory_not_found",
                    }
                )
                continue
            if signal_namespace is not None and record.namespace != str(signal_namespace):
                rejected.append(
                    {
                        "id": memory_id,
                        "namespace": signal_namespace,
                        "error": "namespace_mismatch",
                    }
                )
                continue
            metadata = self._apply_feedback_signal(
                record,
                useful=bool(signal.get("useful", True)),
                strength=float(signal.get("strength", 0.25)),
                query=signal.get("query"),
                reason=signal.get("reason"),
                persist=False,
            )
            feedback_updates.append(
                {
                    "id": memory_id,
                    "namespace": record.namespace,
                    "priority": float(record.priority),
                    "access_count": int(record.access_count),
                    "metadata": metadata,
                }
            )
            accepted.append(
                {
                    "id": memory_id,
                    "namespace": record.namespace,
                    "priority": float(record.priority),
                    "access_count": int(record.access_count),
                }
            )
        if accepted:
            apply_feedback_batch = getattr(self.store, "apply_feedback_batch", None)
            if callable(apply_feedback_batch):
                apply_feedback_batch(feedback_updates)
            else:
                for row in feedback_updates:
                    update_memory_state = getattr(self.store, "update_memory_state", None)
                    if callable(update_memory_state):
                        update_memory_state(
                            int(row["id"]),
                            priority=float(row["priority"]),
                            access_count=int(row["access_count"]),
                        )
                    self.store.log_audit_event(
                        "feedback",
                        namespace=str(row["namespace"]),
                        memory_id=int(row["id"]),
                        metadata=dict(row["metadata"]),
                    )
            self.field.evolve(1)
            self._refresh_field_magnitude()
        return {
            "accepted": len(accepted),
            "rejected": len(rejected),
            "accepted_ids": tuple(int(item["id"]) for item in accepted),
            "rejected_ids": tuple(
                int(item["id"])
                for item in rejected
                if isinstance(item.get("id"), int)
            ),
            "namespaces": tuple(
                sorted({str(item["namespace"]) for item in accepted if item.get("namespace")})
            ),
            "results": tuple(accepted),
            "errors": tuple(rejected),
        }

    def _apply_feedback_signal(
        self,
        record: MemoryRecord,
        *,
        useful: bool,
        strength: float,
        query: object | None = None,
        reason: object | None = None,
        persist: bool = True,
    ) -> dict[str, object]:
        delta = abs(float(strength))
        if bool(useful):
            record.priority += delta
            record.access_count += 1
            self.field.feed(record.pattern, strength=delta)
        else:
            record.priority = max(0.0, record.priority - delta)
            self.field.forget(record.pattern, strength=delta)
        metadata: dict[str, object] = {
            "useful": bool(useful),
            "strength": delta,
            "priority": float(record.priority),
            "access_count": int(record.access_count),
        }
        if reason:
            metadata["reason"] = _redact_audit_text(reason)
        if query:
            if self.audit_queries:
                metadata["query"] = _redact_audit_text(query)
            else:
                metadata["query_length"] = len(str(query))
        if persist:
            update_memory_state = getattr(self.store, "update_memory_state", None)
            if callable(update_memory_state):
                update_memory_state(
                    record.id,
                    priority=record.priority,
                    access_count=record.access_count,
                )
            self.store.log_audit_event(
                "feedback",
                namespace=record.namespace,
                memory_id=record.id,
                metadata=metadata,
            )
        return metadata

    def save(
        self,
        backup_path: str | Path | None = None,
        keep_last: int | None = None,
        backup_prefix: str = "wavemind",
    ) -> Path | None:
        with trace_span(
            "wavemind.save",
            {
                "wavemind.backup_requested": backup_path is not None,
                "wavemind.keep_last": keep_last,
            },
        ):
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
        with trace_span(
            "wavemind.load",
            {"wavemind.index": getattr(self.index, "name", type(self.index).__name__)},
        ):
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

    @staticmethod
    def _record_revision(record: MemoryRecord) -> tuple[Any, ...]:
        return (
            record.namespace,
            record.text,
            tuple(record.tags),
            record.metadata,
            float(record.created_at),
            float(record.updated_at),
            record.expires_at,
        )

    def refresh_namespace_from_store(self, namespace: str) -> dict[str, int]:
        """Refresh one namespace from a shared source of truth.

        Stateless workers keep a local metadata/reranking cache. PostgreSQL is
        shared, so another worker can create or delete a memory without touching
        this process. This incremental refresh makes those mutations visible
        without rebuilding every namespace or destructively recreating a shared
        vector index.
        """

        records = self.store.list(namespace=namespace, include_expired=False)
        incoming = {
            int(record.id): record
            for record in records
            if record.id is not None
        }
        current_ids = set(self._namespace_ids.get(namespace, set()))
        incoming_ids = set(incoming)
        added = 0
        updated = 0
        removed = 0

        for memory_id, record in incoming.items():
            current = self._records_by_id.get(memory_id)
            if current is not None and self._record_revision(current) == self._record_revision(record):
                continue
            if current is not None:
                self._uncache_record(memory_id)
                updated += 1
            else:
                added += 1
            self._cache_record(record)
            self.index.add(memory_id, record.vector)

        for memory_id in current_ids - incoming_ids:
            self._uncache_record(memory_id)
            removed += 1

        self._namespace_store_refresh_at[namespace] = time.monotonic()
        return {"added": added, "updated": updated, "removed": removed}

    def _refresh_namespace_if_due(self, namespace: str) -> None:
        interval = self.shared_store_refresh_seconds
        if interval < 0:
            return
        now = time.monotonic()
        last = self._namespace_store_refresh_at.get(namespace)
        if last is not None and now - last < interval:
            return
        self.refresh_namespace_from_store(namespace)

    def list_records(
        self,
        namespace: str,
        *,
        tags: Iterable[str] | None = None,
    ) -> list[MemoryRecord]:
        """Return active cached records for one namespace.

        Local mutations update this cache synchronously. Shared stores retain
        their configured refresh semantics, while read-heavy layers avoid
        repeatedly decoding the same persisted records.
        """

        selected_namespace = str(namespace)
        self._refresh_namespace_if_due(selected_namespace)
        required_tags = set(tags or ())
        records = []
        for memory_id in sorted(self._namespace_ids.get(selected_namespace, ())):
            record = self._records_by_id.get(memory_id)
            if record is None or record.is_expired:
                continue
            if required_tags and not required_tags.issubset(record.tags):
                continue
            records.append(record)
        return records

    def _append_recovery_journal(
        self,
        action: str,
        records: Iterable[MemoryRecord],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.recovery_journal_path is None:
            return
        records = list(records)
        if not records:
            return
        append_recovery_journal_entry(
            self.recovery_journal_path,
            action,
            records,
            metadata=metadata,
        )

    def index_health(self) -> dict[str, Any]:
        expected_ids = set(self._records_by_id)
        health = getattr(self.index, "health", None)
        if callable(health):
            return health(expected_ids=expected_ids).as_dict()
        vector_count = len(self.index) if hasattr(self.index, "__len__") else None
        healthy = vector_count is None or vector_count == len(expected_ids)
        return {
            "backend": getattr(self.index, "name", type(self.index).__name__),
            "healthy": healthy,
            "exact": False,
            "vector_dim": self.encoder.vector_dim,
            "expected_count": len(expected_ids),
            "vector_count": vector_count,
            "missing_count": 0,
            "extra_count": 0,
            "missing_ids_sample": [],
            "extra_ids_sample": [],
            "dirty": False,
            "persisted": False,
            "loaded_from_persisted": False,
            "path": None,
            "reason": "Index backend does not expose exact health checks",
        }

    def rebuild_index(self) -> dict[str, Any]:
        records = list(self._records_by_id.values())
        with trace_span(
            "wavemind.index.rebuild",
            {
                "wavemind.index": getattr(self.index, "name", type(self.index).__name__),
                "wavemind.records": len(records),
            },
        ):
            replace = getattr(self.index, "replace", None)
            if callable(replace):
                replace(records)
            else:
                self.index.build(records)
        health = self.index_health()
        self.store.log_audit_event(
            "index_rebuild",
            metadata={
                "backend": health["backend"],
                "healthy": health["healthy"],
                "expected_count": health["expected_count"],
                "vector_count": health["vector_count"],
                "missing_count": health["missing_count"],
                "extra_count": health["extra_count"],
            },
        )
        return health

    def ensure_index_health(self, rebuild: bool = True) -> dict[str, Any]:
        health = self.index_health()
        if rebuild and not health["healthy"]:
            return self.rebuild_index()
        return health

    def purge_expired(self) -> int:
        expired_records: list[MemoryRecord] = []
        if self.recovery_journal_path is not None:
            list_expired = getattr(self.store, "list_expired", None)
            if callable(list_expired):
                expired_records = list_expired()
            else:
                expired_records = [
                    record
                    for record in self.store.list(include_expired=True)
                    if record.is_expired
                ]
        purged = self.store.purge_expired()
        if purged:
            self.load()
            self.store.log_audit_event("purge_expired", metadata={"deleted": purged})
            self._append_recovery_journal(
                "purge_expired",
                expired_records,
                metadata={"deleted": purged},
            )
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
        index_health = self.index_health()
        payload = {
            "active_memories": len(active),
            "expired_memories": len(expired),
            "total_memories": len(all_records),
            "audit_events": self.store.audit_count(namespace=namespace),
            "field_energy": round(self.field.energy(), 6),
            "clusters": len(clusters),
            "field_shape": f"{self.field.H}x{self.field.W}x{self.field.L}",
            "index": getattr(self.index, "name", type(self.index).__name__),
            "index_healthy": index_health["healthy"],
            "index_expected_records": index_health["expected_count"],
            "index_vector_records": index_health["vector_count"],
            "index_missing_records": index_health["missing_count"],
            "index_extra_records": index_health["extra_count"],
            "index_health": index_health,
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

    def scale_plan(
        self,
        target_memories: int | None = None,
        namespace: str | None = None,
        latency_target_ms: float = 20.0,
    ) -> ScalePlan:
        stats = self.stats(namespace=namespace)
        return build_scale_plan(
            current_memories=int(stats["active_memories"]),
            target_memories=target_memories,
            index=str(stats["index"]),
            vector_dim=int(stats["vector_dim"]),
            namespace=namespace,
            latency_target_ms=latency_target_ms,
        )

    def audit_events(
        self,
        namespace: str | None = None,
        action: str | None = None,
        memory_id: int | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        return self.store.list_audit_events(
            namespace=namespace,
            action=action,
            memory_id=memory_id,
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

    def consolidate_concepts(
        self,
        namespace: str | None = None,
        seed_text: str | None = None,
        min_energy: float = 0.05,
        min_size: int = 2,
        max_concepts: int = 3,
        priority: float = 6.0,
    ) -> list[dict[str, object]]:
        """Create durable concept memories from active graph clusters.

        This is intentionally extractive and local: no LLM call is used. The
        method turns a co-activated cluster into a new memory with explicit
        provenance so users can inspect which memories caused consolidation.
        """
        if seed_text is not None:
            self._seed_graph(seed_text=seed_text, namespace=namespace)
        self._ensure_graph()
        existing_signatures = {
            str(record.metadata.get("concept_signature"))
            for record in self._records_by_id.values()
            if record.metadata.get("source") == "wavemind_consolidation"
            and record.metadata.get("concept_signature")
        }
        existing_source_keys = {
            (
                record.namespace,
                tuple(sorted(int(id) for id in record.metadata.get("memory_ids", []))),
            )
            for record in self._records_by_id.values()
            if record.metadata.get("source") == "wavemind_consolidation"
            and isinstance(record.metadata.get("memory_ids"), list)
        }
        created: list[dict[str, object]] = []
        for concept in self.concept_candidates(
            namespace=namespace,
            min_energy=min_energy,
            min_size=min_size,
        ):
            if len(created) >= max(0, int(max_concepts)):
                break
            memory_ids = tuple(sorted(int(id) for id in concept.get("memory_ids", [])))
            source_records = [
                self._records_by_id[id]
                for id in memory_ids
                if id in self._records_by_id
                and self._records_by_id[id].metadata.get("source") != "wavemind_consolidation"
            ]
            if len(source_records) < min_size:
                continue
            source_namespaces = {record.namespace for record in source_records}
            if namespace is not None and source_namespaces != {namespace}:
                continue
            if len(source_namespaces) != 1:
                continue
            concept_namespace = next(iter(source_namespaces))
            source_ids = tuple(
                sorted(int(record.id) for record in source_records if record.id is not None)
            )
            if (concept_namespace, source_ids) in existing_source_keys:
                continue
            label = self._concept_label(source_records)
            signature = self._concept_signature(concept_namespace, label, source_ids)
            if signature in existing_signatures:
                continue
            text = self._concept_text(label, source_records)
            tags = self._concept_tags(label, source_records)
            metadata = {
                "source": "wavemind_consolidation",
                "concept_signature": signature,
                "concept_label": label,
                "memory_ids": list(source_ids),
                "energy": float(concept.get("energy", 0.0)),
                "size": len(source_records),
            }
            concept_id = self.remember(
                text,
                namespace=concept_namespace,
                tags=tags,
                metadata=metadata,
                priority=priority,
            )
            self.store.log_audit_event(
                "consolidate_concept",
                namespace=concept_namespace,
                memory_id=concept_id,
                metadata={
                    "concept_label": label,
                    "source_memory_ids": list(source_ids),
                    "concept_signature": signature,
                },
            )
            existing_signatures.add(signature)
            existing_source_keys.add((concept_namespace, source_ids))
            created.append(
                {
                    "id": concept_id,
                    "text": text,
                    "namespace": concept_namespace,
                    "tags": list(tags),
                    "metadata": metadata,
                }
            )
        return created

    @property
    def memory(self) -> list[tuple[str, np.ndarray]]:
        return [(record.text, record.pattern) for record in self._records_by_id.values()]

    def _seed_graph(self, seed_text: str, namespace: str | None = None) -> None:
        namespaces = [namespace] if namespace is not None else sorted(self._namespace_ids)
        if not namespaces:
            return
        query_vector = self.encoder.encode_vector(seed_text)
        self._ensure_graph()
        for item_namespace in namespaces:
            allowed_ids = self._allowed_ids(namespace=item_namespace, tags=None)
            if not allowed_ids:
                continue
            candidates = self.index.search(
                query_vector,
                top_k=max(1, self.rerank_k),
                allowed_ids=allowed_ids,
            )
            if not candidates:
                continue
            self.graph.propagate(
                {candidate.id: max(0.0, candidate.score) for candidate in candidates},
                allowed_ids=allowed_ids,
                steps=max(1, self.graph_steps),
            )

    def _concept_signature(
        self,
        namespace: str,
        label: str,
        memory_ids: tuple[int, ...],
    ) -> str:
        payload = f"{namespace}|{label}|{','.join(str(id) for id in memory_ids)}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def _concept_label(self, records: list[MemoryRecord]) -> str:
        tag_counts = Counter(tag for record in records for tag in record.tags if tag != "concept")
        if tag_counts:
            return " ".join(tag for tag, _ in tag_counts.most_common(3))
        token_counts = Counter(
            token
            for record in records
            for token in self._tokens(record.text)
        )
        return " ".join(token for token, _ in token_counts.most_common(3)) or "memory cluster"

    def _concept_tags(
        self,
        label: str,
        records: list[MemoryRecord],
    ) -> tuple[str, ...]:
        tags = ["concept"]
        common_tags = Counter(tag for record in records for tag in record.tags if tag != "concept")
        tags.extend(tag for tag, _ in common_tags.most_common(4))
        for token in self._tokens(label):
            if token not in tags:
                tags.append(token)
        return tuple(tags[:8])

    def _concept_text(self, label: str, records: list[MemoryRecord]) -> str:
        evidence = "; ".join(record.text for record in records[:3])
        return f"Consolidated memory: {label}. Evidence: {evidence}."

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
        metadata_filters: Mapping[str, Any] | None = None,
    ) -> set[int]:
        ids = set(self._namespace_ids.get(namespace, set()))
        required_tags = set(tags or ())
        required_metadata = dict(metadata_filters or {})
        if not ids:
            return set()
        allowed = set()
        for id in ids:
            record = self._records_by_id[id]
            if record.is_expired:
                continue
            if required_tags and not required_tags.issubset(set(record.tags)):
                continue
            if required_metadata and not self._metadata_matches(
                record.metadata,
                required_metadata,
            ):
                continue
            allowed.add(id)
        return allowed

    @staticmethod
    def _metadata_matches(
        metadata: Mapping[str, Any],
        filters: Mapping[str, Any],
    ) -> bool:
        for key, expected in filters.items():
            if not str(key):
                raise ValueError("metadata filter keys must not be empty")
            actual = metadata.get(str(key))
            if isinstance(expected, (list, tuple, set, frozenset)):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    @staticmethod
    def _serializable_metadata_filters(
        filters: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in sorted((filters or {}).items()):
            payload[str(key)] = (
                sorted(value, key=lambda item: str(item))
                if isinstance(value, (set, frozenset))
                else list(value)
                if isinstance(value, tuple)
                else value
            )
        return payload

    def _refresh_field_magnitude(self) -> None:
        self._field_magnitude = np.nan_to_num(
            np.sum(np.abs(self.field.state), axis=2, dtype=np.float64),
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )
        norm = float(np.linalg.norm(self._field_magnitude))
        self._field_magnitude_norm = norm if np.isfinite(norm) else 0.0

    def _field_resonance(self, pattern: np.ndarray) -> float:
        field = self._field_magnitude.astype(np.float64, copy=False).ravel()
        pat = np.nan_to_num(
            pattern.astype(np.float64, copy=False).ravel(),
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )
        pattern_norm = float(np.linalg.norm(pat))
        denom = (self._field_magnitude_norm * pattern_norm) + 1e-9
        score = float(np.dot(field, pat) / denom)
        return score if np.isfinite(score) else 0.0

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
