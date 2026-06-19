from __future__ import annotations

import re
from collections import Counter, defaultdict, deque
from typing import Iterable

import numpy as np

from .encoders import DEFAULT_TOKEN_STOPWORDS, is_stopword_token, normalize_token
from .storage import MemoryRecord


class MemoryFieldGraph:
    """Discrete memory field over stored memories.

    The 2D WaveField models spatial resonance. This graph models memory-to-memory
    interaction: related memories excite each other, while newer conflicting
    memories inhibit stale facts.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.72,
        semantic_strength: float = 0.55,
        tag_strength: float = 0.25,
        propagation_strength: float = 0.35,
        decay: float = 0.90,
        conflict_strength: float = 0.70,
        max_neighbors: int = 8,
    ) -> None:
        self.similarity_threshold = float(similarity_threshold)
        self.semantic_strength = float(semantic_strength)
        self.tag_strength = float(tag_strength)
        self.propagation_strength = float(propagation_strength)
        self.decay = float(decay)
        self.conflict_strength = float(conflict_strength)
        self.max_neighbors = int(max_neighbors)
        self.records: dict[int, MemoryRecord] = {}
        self.links: dict[int, list[tuple[int, float]]] = {}
        self._energy: dict[int, float] = {}

    def build(self, records: Iterable[MemoryRecord]) -> None:
        previous_energy = dict(self._energy)
        self.records = {
            int(record.id): record
            for record in records
            if record.id is not None
        }
        self.links = {id: [] for id in self.records}
        self._energy = {
            id: previous_energy.get(id, 0.0)
            for id in self.records
            if previous_energy.get(id, 0.0) > 1e-6
        }
        record_values = list(self.records.values())
        for index, left in enumerate(record_values):
            for right in record_values[index + 1 :]:
                if left.id is None or right.id is None:
                    continue
                if left.namespace != right.namespace:
                    continue
                left_id = int(left.id)
                right_id = int(right.id)
                positive = self._positive_weight(left, right)
                if positive > 0.0:
                    self._add_link(left_id, right_id, positive)
                    self._add_link(right_id, left_id, positive)
                if self._is_conflict(left, right):
                    newer, older = self._newer_older(left, right)
                    if newer.id is not None and older.id is not None:
                        self._add_link(int(newer.id), int(older.id), -self.conflict_strength)
                        self._add_link(int(older.id), int(newer.id), -self.conflict_strength * 0.15)
        self._trim_links()

    def propagate(
        self,
        seed_scores: dict[int, float],
        allowed_ids: set[int] | None = None,
        steps: int = 2,
    ) -> dict[int, float]:
        allowed = set(self.records) if allowed_ids is None else set(allowed_ids) & set(self.records)
        if not allowed:
            return {}
        self.decay_energy(steps=1)
        touched: set[int] = set()
        for id, score in seed_scores.items():
            id = int(id)
            if id not in allowed:
                continue
            amount = max(0.0, float(score))
            if amount <= 0.0:
                continue
            self._energy[id] = min(1.0, self._energy.get(id, 0.0) + amount)
            touched.add(id)

        for _ in range(max(0, int(steps))):
            delta: dict[int, float] = defaultdict(float)
            for source_id in allowed:
                source_energy = max(0.0, self._energy.get(source_id, 0.0))
                if source_energy <= 1e-6:
                    continue
                for target_id, weight in self.links.get(source_id, ()):
                    if target_id not in allowed:
                        continue
                    delta[target_id] += source_energy * weight * self.propagation_strength
                    touched.add(target_id)
            for id, change in delta.items():
                if abs(change) <= 1e-9:
                    continue
                self._energy[id] = min(1.0, max(0.0, self._energy.get(id, 0.0) + change))

        return {
            id: self._energy.get(id, 0.0)
            for id in touched
            if id in allowed and self._energy.get(id, 0.0) > 1e-6
        }

    def decay_energy(self, steps: int = 1) -> None:
        factor = self.decay ** max(0, int(steps))
        if factor == 1.0:
            return
        for id in list(self._energy):
            value = self._energy[id] * factor
            if value <= 1e-6:
                self._energy.pop(id, None)
            else:
                self._energy[id] = value

    def energy(self, id: int | None = None) -> float:
        if id is not None:
            return float(self._energy.get(int(id), 0.0))
        return float(sum(self._energy.values()))

    def remove(self, id: int) -> None:
        id = int(id)
        self.records.pop(id, None)
        self.links.pop(id, None)
        self._energy.pop(id, None)
        for source_id in list(self.links):
            self.links[source_id] = [
                (target_id, weight)
                for target_id, weight in self.links[source_id]
                if target_id != id
            ]

    def stats(self) -> dict[str, float | int]:
        positive = sum(1 for edges in self.links.values() for _, weight in edges if weight > 0)
        negative = sum(1 for edges in self.links.values() for _, weight in edges if weight < 0)
        return {
            "graph_nodes": len(self.records),
            "graph_edges": positive + negative,
            "graph_positive_edges": positive,
            "graph_negative_edges": negative,
            "graph_energy": round(self.energy(), 6),
        }

    def concept_candidates(self, min_energy: float = 0.05, min_size: int = 2) -> list[dict[str, object]]:
        active = {
            id
            for id, value in self._energy.items()
            if value >= min_energy and id in self.records
        }
        seen: set[int] = set()
        concepts: list[dict[str, object]] = []
        for start_id in sorted(active):
            if start_id in seen:
                continue
            component: set[int] = set()
            queue = deque([start_id])
            seen.add(start_id)
            while queue:
                current = queue.popleft()
                component.add(current)
                for target_id, weight in self.links.get(current, ()):
                    if weight <= 0 or target_id not in active or target_id in seen:
                        continue
                    seen.add(target_id)
                    queue.append(target_id)
            if len(component) < min_size:
                continue
            records = [self.records[id] for id in sorted(component)]
            concepts.append(
                {
                    "label": self._label(records),
                    "memory_ids": [int(record.id) for record in records if record.id is not None],
                    "energy": round(sum(self._energy.get(int(record.id), 0.0) for record in records if record.id is not None), 6),
                    "size": len(records),
                }
            )
        concepts.sort(key=lambda item: (float(item["energy"]), int(item["size"])), reverse=True)
        return concepts

    def _positive_weight(self, left: MemoryRecord, right: MemoryRecord) -> float:
        semantic = self._semantic_similarity(left.vector, right.vector)
        semantic_weight = 0.0
        if semantic >= self.similarity_threshold:
            span = max(1e-6, 1.0 - self.similarity_threshold)
            semantic_weight = ((semantic - self.similarity_threshold) / span) * self.semantic_strength
        tag_weight = self._tag_overlap(left.tags, right.tags) * self.tag_strength
        return min(1.0, max(0.0, semantic_weight + tag_weight))

    def _semantic_similarity(self, left: np.ndarray, right: np.ndarray) -> float:
        denom = float(np.linalg.norm(left) * np.linalg.norm(right)) + 1e-9
        return float(np.dot(left, right) / denom)

    def _tag_overlap(self, left_tags: tuple[str, ...], right_tags: tuple[str, ...]) -> float:
        left = set(left_tags)
        right = set(right_tags)
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    def _is_conflict(self, left: MemoryRecord, right: MemoryRecord) -> bool:
        left_group = left.metadata.get("conflict_group")
        right_group = right.metadata.get("conflict_group")
        return bool(left_group and left_group == right_group)

    def _newer_older(self, left: MemoryRecord, right: MemoryRecord) -> tuple[MemoryRecord, MemoryRecord]:
        if left.created_at != right.created_at:
            return (left, right) if left.created_at > right.created_at else (right, left)
        if left.priority != right.priority:
            return (left, right) if left.priority > right.priority else (right, left)
        return (left, right) if int(left.id or 0) > int(right.id or 0) else (right, left)

    def _add_link(self, source_id: int, target_id: int, weight: float) -> None:
        if source_id == target_id or abs(weight) <= 1e-9:
            return
        self.links.setdefault(source_id, []).append((target_id, float(weight)))

    def _trim_links(self) -> None:
        if self.max_neighbors <= 0:
            return
        for source_id, edges in list(self.links.items()):
            negative = [(target_id, weight) for target_id, weight in edges if weight < 0]
            positive = sorted(
                ((target_id, weight) for target_id, weight in edges if weight > 0),
                key=lambda item: item[1],
                reverse=True,
            )[: self.max_neighbors]
            self.links[source_id] = positive + negative

    def _label(self, records: list[MemoryRecord]) -> str:
        tag_counts = Counter(tag for record in records for tag in record.tags)
        if tag_counts:
            return " ".join(tag for tag, _ in tag_counts.most_common(3))
        token_counts = Counter(
            token
            for record in records
            for token in self._tokens(record.text)
        )
        return " ".join(token for token, _ in token_counts.most_common(3)) or "memory cluster"

    def _tokens(self, text: str) -> tuple[str, ...]:
        return tuple(
            normalized
            for token in re.findall(r"[\w]+", text.lower(), flags=re.UNICODE)
            for normalized in (normalize_token(token),)
            if normalized not in DEFAULT_TOKEN_STOPWORDS and not is_stopword_token(token)
        )
