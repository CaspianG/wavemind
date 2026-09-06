from __future__ import annotations

import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from wavemind.scientific_memory import MemoryDefinition
from wavemind.scientific_query_phrases import (
    extract_query_candidate_phrases,
    normalize_query_phrase,
)
from wavemind.scientific_reconciliation import (
    ReconciliationSelection,
    _MEMORY_TOMBSTONE_MARKER,
    _source_order,
    _tokens,
)


SQLITE_PARAMETER_LIMIT = 900
WRITE_BATCH_SIZE = 50_000


def _chunks(values: Sequence[int], size: int = SQLITE_PARAMETER_LIMIT):
    for start in range(0, len(values), size):
        yield values[start : start + size]


class FrozenLexicalIndex:
    """Disk-backed exact lexical index for an immutable definition snapshot.

    The index stores token/document postings as integer pairs and normalized
    document text in SQLite. It deliberately keeps neither document content nor
    per-document token sets in Python after construction.
    """

    def __init__(
        self,
        path: str | Path,
        definitions: Mapping[str, MemoryDefinition],
    ) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.path.unlink()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=OFF")
        self._connection.execute("PRAGMA synchronous=OFF")
        self._connection.execute("PRAGMA temp_store=MEMORY")
        self._connection.executescript(
            """
            CREATE TABLE tokens (
                token_id INTEGER PRIMARY KEY,
                token TEXT NOT NULL UNIQUE
            );
            CREATE TABLE documents (
                doc_index INTEGER PRIMARY KEY,
                memory_id TEXT NOT NULL UNIQUE,
                normalized_content TEXT NOT NULL
            );
            CREATE TABLE postings (
                token_id INTEGER NOT NULL,
                doc_index INTEGER NOT NULL,
                PRIMARY KEY (token_id, doc_index)
            ) WITHOUT ROWID;
            """
        )
        self._token_ids: dict[str, int] = {}
        self._document_frequency: list[int] = [0]
        self._memory_ids: list[str] = []
        self._doc_index_by_memory: dict[str, int] = {}
        self._source_orders: dict[str, int] = {}
        self._tombstones: set[str] = set()
        self._definitions_identity = id(definitions)
        try:
            self._build(definitions)
        except Exception:
            self._connection.close()
            self.path.unlink(missing_ok=True)
            raise
        self._fallback_all = tuple(
            sorted(
                self._memory_ids,
                key=lambda memory_id: (
                    -self._source_orders[memory_id],
                    0 if memory_id in self._tombstones else 1,
                    memory_id,
                ),
            )
        )
        self._fallback_tombstones = tuple(
            memory_id
            for memory_id in self._fallback_all
            if memory_id in self._tombstones
        )
        self._fallback_non_tombstones = tuple(
            memory_id
            for memory_id in self._fallback_all
            if memory_id not in self._tombstones
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "FrozenLexicalIndex":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @property
    def definition_count(self) -> int:
        return len(self._memory_ids)

    @property
    def token_count(self) -> int:
        return len(self._token_ids)

    def _build(self, definitions: Mapping[str, MemoryDefinition]) -> None:
        token_rows: list[tuple[int, str]] = []
        posting_rows: list[tuple[int, int]] = []

        def flush() -> None:
            if token_rows:
                self._connection.executemany(
                    "INSERT INTO tokens(token_id, token) VALUES (?, ?)",
                    token_rows,
                )
                token_rows.clear()
            if posting_rows:
                self._connection.executemany(
                    "INSERT INTO postings(token_id, doc_index) VALUES (?, ?)",
                    posting_rows,
                )
                posting_rows.clear()

        self._connection.execute("BEGIN")
        try:
            for doc_index, (memory_id, definition) in enumerate(definitions.items()):
                self._memory_ids.append(memory_id)
                self._doc_index_by_memory[memory_id] = doc_index
                self._source_orders[memory_id] = _source_order(definition)
                if _MEMORY_TOMBSTONE_MARKER in definition.provenance:
                    self._tombstones.add(memory_id)
                self._connection.execute(
                    "INSERT INTO documents(doc_index, memory_id, normalized_content) "
                    "VALUES (?, ?, ?)",
                    (
                        doc_index,
                        memory_id,
                        normalize_query_phrase(definition.content),
                    ),
                )
                for token in sorted(_tokens(definition.content)):
                    token_id = self._token_ids.get(token)
                    if token_id is None:
                        token_id = len(self._token_ids) + 1
                        self._token_ids[token] = token_id
                        self._document_frequency.append(0)
                        token_rows.append((token_id, token))
                    posting_rows.append((token_id, doc_index))
                    self._document_frequency[token_id] += 1
                if len(posting_rows) >= WRITE_BATCH_SIZE:
                    flush()
            flush()
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def _overlaps(self, query_tokens: set[str]) -> dict[str, set[str]]:
        selected = {
            self._token_ids[token]: token
            for token in query_tokens
            if token in self._token_ids
        }
        overlaps: dict[str, set[str]] = defaultdict(set)
        token_ids = sorted(selected)
        for chunk in _chunks(token_ids):
            placeholders = ",".join("?" for _ in chunk)
            rows = self._connection.execute(
                "SELECT token_id, doc_index FROM postings "
                f"WHERE token_id IN ({placeholders})",
                tuple(chunk),
            )
            for token_id, doc_index in rows:
                overlaps[self._memory_ids[int(doc_index)]].add(
                    selected[int(token_id)]
                )
        return dict(overlaps)

    def _documents_for_token(self, token: str) -> set[int]:
        token_id = self._token_ids.get(token)
        if token_id is None:
            return set()
        rows = self._connection.execute(
            "SELECT doc_index FROM postings WHERE token_id = ?",
            (token_id,),
        )
        return {int(row[0]) for row in rows}

    def _normalized_contents(self, doc_indexes: set[int]) -> Iterable[tuple[int, str]]:
        ordered = sorted(doc_indexes)
        for chunk in _chunks(ordered):
            placeholders = ",".join("?" for _ in chunk)
            yield from self._connection.execute(
                "SELECT doc_index, normalized_content FROM documents "
                f"WHERE doc_index IN ({placeholders})",
                tuple(chunk),
            )

    def _phrase_hits(
        self,
        phrases: Sequence[str],
        *,
        restrict_to: set[str] | None = None,
    ) -> Counter[str]:
        hits: Counter[str] = Counter()
        restricted_docs = (
            {self._doc_index_by_memory[memory_id] for memory_id in restrict_to}
            if restrict_to is not None
            else None
        )
        for phrase in phrases:
            phrase_tokens = sorted(_tokens(phrase))
            if phrase_tokens:
                posting_sets = [
                    self._documents_for_token(token) for token in phrase_tokens
                ]
                posting_sets.sort(key=len)
                candidates = set(posting_sets[0]) if posting_sets else set()
                for posting_set in posting_sets[1:]:
                    candidates.intersection_update(posting_set)
                    if not candidates:
                        break
            else:
                candidates = set(range(len(self._memory_ids)))
            if restricted_docs is not None:
                candidates.intersection_update(restricted_docs)
            for doc_index, normalized_content in self._normalized_contents(candidates):
                if phrase in str(normalized_content):
                    hits[self._memory_ids[int(doc_index)]] += 1
        return hits

    def _validate_definitions(
        self,
        definitions: Mapping[str, MemoryDefinition],
    ) -> None:
        if id(definitions) == self._definitions_identity:
            return
        if len(definitions) != len(self._memory_ids) or set(definitions) != set(
            self._memory_ids
        ):
            raise RuntimeError("frozen lexical index definition set changed")

    def _token_weight(self, token: str, *, definition_count: int) -> float:
        token_id = self._token_ids.get(token)
        frequency = self._document_frequency[token_id] if token_id is not None else 0
        return math.log((definition_count + 1) / (frequency + 1)) + 1.0

    def select_operation_memories(
        self,
        reconciler,
        query: str,
        definitions: Mapping[str, MemoryDefinition],
        *,
        token_budget: int,
        latency_budget_ms: float,
    ) -> ReconciliationSelection:
        self._validate_definitions(definitions)
        query_tokens = _tokens(query)
        overlaps = self._overlaps(query_tokens)
        total = max(1, len(definitions))
        weights = {
            token: self._token_weight(token, definition_count=total)
            for token in query_tokens
        }
        denominator = sum(weights.values()) or 1.0
        query_phrases = (
            extract_query_candidate_phrases(query)
            if reconciler.query_phrase_aware
            else ()
        )
        phrase_hits = self._phrase_hits(query_phrases)
        relevant_ids = set(overlaps).union(phrase_hits)
        universe = set(relevant_ids)
        if reconciler.target_scoped_tombstones:
            universe.update(self._fallback_all[: reconciler.maximum_candidates])
        else:
            universe.update(
                self._fallback_tombstones[: reconciler.maximum_candidates]
            )
            universe.update(
                self._fallback_non_tombstones[: reconciler.maximum_candidates]
            )

        ranked = []
        scores: dict[str, float] = {}
        relevant_tombstones: set[str] = set()
        for memory_id in universe:
            overlap = overlaps.get(memory_id, set())
            lexical = sum(weights[token] for token in overlap) / denominator
            tombstone = memory_id in self._tombstones
            hits = phrase_hits.get(memory_id, 0)
            scores[memory_id] = (
                max(lexical, min(1.0, hits / max(1, len(query_phrases))))
                if reconciler.target_scoped_tombstones
                else 1.0
                if tombstone
                else lexical
            )
            if reconciler.target_scoped_tombstones:
                relevant_tombstone = tombstone and bool(hits or lexical > 0.0)
                if relevant_tombstone:
                    relevant_tombstones.add(memory_id)
                ranked.append(
                    (
                        (
                            0
                            if reconciler.relevant_tombstones_first
                            and relevant_tombstone
                            else 1
                            if reconciler.relevant_tombstones_first
                            else 0
                        ),
                        -hits,
                        -lexical,
                        -self._source_orders[memory_id],
                        0 if tombstone else 1,
                        memory_id,
                    )
                )
            else:
                ranked.append(
                    (
                        0,
                        0 if tombstone else 1,
                        -hits,
                        -lexical,
                        -self._source_orders[memory_id],
                        memory_id,
                    )
                )
        ranked.sort()
        candidate_ids = [item[-1] for item in ranked[: reconciler.maximum_candidates]]
        if reconciler.tombstone_cutover and relevant_tombstones:
            cutover_order = max(
                self._source_orders[memory_id] for memory_id in relevant_tombstones
            )
            eligible_recent = {
                memory_id
                for memory_id in self._fallback_all
                if self._source_orders[memory_id] >= cutover_order
            }
            if not eligible_recent.issubset(universe):
                return self.select_operation_memories_full_cutover(
                    reconciler,
                    definitions,
                    overlaps=overlaps,
                    phrase_hits=phrase_hits,
                    weights=weights,
                    denominator=denominator,
                    query_phrase_count=len(query_phrases),
                    relevant_tombstones=relevant_tombstones,
                    cutover_order=cutover_order,
                    token_budget=token_budget,
                    latency_budget_ms=latency_budget_ms,
                )
            candidate_ids = [
                memory_id
                for memory_id in (item[-1] for item in ranked)
                if memory_id in relevant_tombstones
                or self._source_orders[memory_id] >= cutover_order
            ][: reconciler.maximum_candidates]
        memory_ids = reconciler._fit_budget(
            candidate_ids,
            definitions,
            token_budget=token_budget,
            latency_budget_ms=latency_budget_ms,
        )
        return ReconciliationSelection(
            memory_ids=memory_ids,
            relevance={memory_id: scores[memory_id] for memory_id in memory_ids},
            reason=(
                "evaluation-only target-state tombstone cutover evidence"
                if reconciler.tombstone_cutover
                else "evaluation-only slice-local relevant-tombstone-first operation evidence"
                if reconciler.relevant_tombstones_first
                else "evaluation-only target-scoped phrase-aligned operation evidence"
                if reconciler.target_scoped_tombstones
                else (
                    "evaluation-only phrase-aligned operation evidence with mandatory tombstones"
                    if query_phrases
                    else "evaluation-only operation evidence with mandatory tombstones"
                )
            ),
        )

    def select_operation_memories_full_cutover(
        self,
        reconciler,
        definitions: Mapping[str, MemoryDefinition],
        *,
        overlaps: Mapping[str, set[str]],
        phrase_hits: Mapping[str, int],
        weights: Mapping[str, float],
        denominator: float,
        query_phrase_count: int,
        relevant_tombstones: set[str],
        cutover_order: int,
        token_budget: int,
        latency_budget_ms: float,
    ) -> ReconciliationSelection:
        universe = set(overlaps).union(phrase_hits).union(relevant_tombstones)
        universe.update(
            memory_id
            for memory_id in self._fallback_all
            if self._source_orders[memory_id] >= cutover_order
        )
        ranked = []
        scores: dict[str, float] = {}
        for memory_id in universe:
            lexical = sum(weights[token] for token in overlaps.get(memory_id, set()))
            lexical /= denominator
            hits = phrase_hits.get(memory_id, 0)
            relevant_tombstone = memory_id in relevant_tombstones
            tombstone = memory_id in self._tombstones
            scores[memory_id] = max(
                lexical,
                min(1.0, hits / max(1, query_phrase_count)),
            )
            ranked.append(
                (
                    0
                    if reconciler.relevant_tombstones_first and relevant_tombstone
                    else 1
                    if reconciler.relevant_tombstones_first
                    else 0,
                    -hits,
                    -lexical,
                    -self._source_orders[memory_id],
                    0 if tombstone else 1,
                    memory_id,
                )
            )
        ranked.sort()
        candidate_ids = [
            memory_id
            for memory_id in (item[-1] for item in ranked)
            if memory_id in relevant_tombstones
            or self._source_orders[memory_id] >= cutover_order
        ][: reconciler.maximum_candidates]
        memory_ids = reconciler._fit_budget(
            candidate_ids,
            definitions,
            token_budget=token_budget,
            latency_budget_ms=latency_budget_ms,
        )
        return ReconciliationSelection(
            memory_ids=memory_ids,
            relevance={memory_id: scores[memory_id] for memory_id in memory_ids},
            reason="evaluation-only target-state tombstone cutover evidence",
        )

    def select_ranked_memories(
        self,
        reconciler,
        query: str,
        definitions: Mapping[str, MemoryDefinition],
        *,
        token_budget: int,
        latency_budget_ms: float,
    ) -> ReconciliationSelection:
        self._validate_definitions(definitions)
        query_tokens = _tokens(query)
        if not query_tokens or not definitions:
            return ReconciliationSelection((), {}, "no query-aligned active state")
        overlaps = self._overlaps(query_tokens)
        total = max(1, len(definitions))
        weights = {
            token: self._token_weight(token, definition_count=total)
            for token in query_tokens
        }
        denominator = sum(weights.values()) or 1.0
        maximum_order = max(self._source_orders.values(), default=0)
        query_phrases = (
            extract_query_candidate_phrases(query)
            if reconciler.query_phrase_aware
            else ()
        )
        phrase_hits = self._phrase_hits(
            query_phrases,
            restrict_to=set(overlaps),
        )
        ranked = []
        for memory_id, overlap in overlaps.items():
            lexical = sum(weights[token] for token in overlap) / denominator
            order = self._source_orders[memory_id]
            recency = (order / maximum_order) if maximum_order else 0.0
            score = lexical + (reconciler.source_recency_weight * recency)
            ranked.append((phrase_hits.get(memory_id, 0), score, order, memory_id))
        ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
        candidates = [item[3] for item in ranked[: reconciler.maximum_candidates]]
        memory_ids = reconciler._fit_budget(
            candidates,
            definitions,
            token_budget=token_budget,
            latency_budget_ms=latency_budget_ms,
        )
        scores = {memory_id: score for _, score, _, memory_id in ranked}
        return ReconciliationSelection(
            memory_ids=memory_ids,
            relevance={memory_id: min(1.0, scores[memory_id]) for memory_id in memory_ids},
            reason=(
                "evaluation-only phrase-aligned lexical-state retrieval without source recency"
                if query_phrases
                else "evaluation-only lexical-state retrieval without source recency"
                if reconciler.source_recency_weight == 0.0
                else "evaluation-only lexical-state retrieval with source recency"
            ),
        )
