from __future__ import annotations

import math
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Mapping, Sequence

from .scientific_memory import MemoryDefinition
from .scientific_query_phrases import (
    extract_query_candidate_phrases,
    normalize_query_phrase,
)


STATE_RECONCILER_ID = "proof-carrying-state-reconciler-v2"
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
_NUMBERED_FACT_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")
_SOURCE_ORDER_RE = re.compile(r"(?:source-order|fact-order):(\d+)$")
_MEMORY_OPERATION_MARKER = "memory-operation:1"
_MEMORY_TOMBSTONE_MARKER = "memory-tombstone:1"
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "did",
    "do",
    "does",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}


@dataclass(frozen=True)
class ReconciledClaim:
    memory_id: str
    source_order: int
    subject: str
    relation: str
    object: str
    content: str

    @property
    def state_key(self) -> tuple[str, str]:
        return (_normalize_entity(self.subject), self.relation)


@dataclass(frozen=True)
class ReconciliationSelection:
    memory_ids: tuple[str, ...]
    relevance: Mapping[str, float]
    reason: str


_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("official_language", re.compile(r"^The official language of (.+?) is (.+?)\.$")),
    ("director", re.compile(r"^The director of (.+?) is (.+?)\.$")),
    ("chairperson", re.compile(r"^The chairperson of (.+?) is (.+?)\.$")),
    ("capital", re.compile(r"^The capital of (.+?) is (.+?)\.$")),
    ("citizenship", re.compile(r"^(.+?) is a citizen of (.+?)\.$")),
    ("position", re.compile(r"^(.+?) plays the position of (.+?)\.$")),
    (
        "sport",
        re.compile(r"^(.+?) is associated with the sport of (.+?)\.$"),
    ),
    ("performer", re.compile(r"^(.+?) was performed by (.+?)\.$")),
    ("continent", re.compile(r"^(.+?) is located in the continent of (.+?)\.$")),
    ("spouse", re.compile(r"^(.+?) is married to (.+?)\.$")),
    ("music", re.compile(r"^The type of music that (.+?) plays is (.+?)\.$")),
    ("educated_at", re.compile(r"^The univeristy where (.+?) was educated is (.+?)\.$")),
    ("founded_by", re.compile(r"^(.+?) was founded by (.+?)\.$")),
    ("religion", re.compile(r"^(.+?) is affiliated with the religion of (.+?)\.$")),
    ("worked_in", re.compile(r"^(.+?) worked in the city of (.+?)\.$")),
    ("created_by", re.compile(r"^(.+?) was created by (.+?)\.$")),
    ("created_country", re.compile(r"^(.+?) was created in the country of (.+?)\.$")),
)


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN_RE.findall(value)
        if len(token) > 1 and token.casefold() not in _STOPWORDS
    }


def _normalize_entity(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.casefold()))


def _source_order(definition: MemoryDefinition) -> int:
    for provenance in definition.provenance:
        match = _SOURCE_ORDER_RE.search(str(provenance))
        if match:
            return int(match.group(1))
    return 0


def parse_numbered_claim(definition: MemoryDefinition) -> ReconciledClaim | None:
    numbered = _NUMBERED_FACT_RE.match(definition.content)
    if not numbered:
        return None
    order = int(numbered.group(1))
    statement = numbered.group(2).strip()
    for relation, pattern in _CLAIM_PATTERNS:
        match = pattern.match(statement)
        if match:
            return ReconciledClaim(
                memory_id=definition.memory_id,
                source_order=order,
                subject=match.group(1).strip(),
                relation=relation,
                object=match.group(2).strip(),
                content=definition.content,
            )
    return None


def active_claims(
    definitions: Mapping[str, MemoryDefinition],
) -> tuple[ReconciledClaim, ...]:
    latest: dict[tuple[str, str], ReconciledClaim] = {}
    for definition in definitions.values():
        claim = parse_numbered_claim(definition)
        if claim is None:
            continue
        previous = latest.get(claim.state_key)
        if previous is None or (claim.source_order, claim.memory_id) > (
            previous.source_order,
            previous.memory_id,
        ):
            latest[claim.state_key] = claim
    return tuple(sorted(latest.values(), key=lambda item: (item.source_order, item.memory_id)))


class ProofCarryingStateReconciler:
    """Frozen v2 selector over source-ordered, provenance-carrying memory."""

    def __init__(
        self,
        *,
        maximum_graph_hops: int = 4,
        maximum_candidates: int = 20,
        operation_aware: bool = False,
        source_recency_weight: float = 0.25,
        query_phrase_aware: bool = False,
        target_scoped_tombstones: bool = False,
        relevant_tombstones_first: bool = False,
        tombstone_cutover: bool = False,
    ):
        if maximum_graph_hops < 1 or maximum_candidates < 1:
            raise ValueError("reconciliation bounds must be positive")
        self.maximum_graph_hops = int(maximum_graph_hops)
        self.maximum_candidates = int(maximum_candidates)
        self.operation_aware = bool(operation_aware)
        self.source_recency_weight = float(source_recency_weight)
        self.query_phrase_aware = bool(query_phrase_aware)
        self.target_scoped_tombstones = bool(target_scoped_tombstones)
        self.relevant_tombstones_first = bool(relevant_tombstones_first)
        self.tombstone_cutover = bool(tombstone_cutover)
        if self.source_recency_weight < 0.0:
            raise ValueError("source recency weight must be non-negative")

    def select(
        self,
        query: str,
        definitions: Mapping[str, MemoryDefinition],
        *,
        token_budget: int,
        latency_budget_ms: float,
        max_safety_risk: float,
        context: Mapping[str, str],
        moment: float,
    ) -> ReconciliationSelection:
        eligible = {
            memory_id: definition
            for memory_id, definition in definitions.items()
            if definition.safety_risk <= max_safety_risk
            and definition.validity.contains(moment)
            and all(
                str(context.get(key)) == value
                for key, value in definition.applicability.items()
            )
        }
        if self.operation_aware and any(
            _MEMORY_OPERATION_MARKER in definition.provenance
            for definition in eligible.values()
        ):
            return self._select_operation_memories(
                query,
                eligible,
                token_budget=token_budget,
                latency_budget_ms=latency_budget_ms,
            )
        claims = active_claims(eligible)
        if claims:
            return self._select_claim_graph(
                query,
                eligible,
                claims,
                token_budget=token_budget,
                latency_budget_ms=latency_budget_ms,
            )
        return self._select_ranked_memories(
            query,
            eligible,
            token_budget=token_budget,
            latency_budget_ms=latency_budget_ms,
        )

    def select_sequence_coverage(
        self,
        definitions: Mapping[str, MemoryDefinition],
        *,
        token_budget: int,
        latency_budget_ms: float,
    ) -> ReconciliationSelection:
        """Select source-ordered evidence at deterministic, evenly spaced positions.

        Query relevance is deliberately absent: global summarization is a coverage
        task, and few-shot examples in the query are not evidence about the target
        sequence. Endpoints are retained so beginnings and resolutions remain
        represented when the source is much larger than the memory budget.
        """

        ordered = sorted(
            definitions,
            key=lambda memory_id: (
                _source_order(definitions[memory_id]),
                memory_id,
            ),
        )
        if not ordered:
            return ReconciliationSelection((), {}, "no source sequence available")
        target_count = min(self.maximum_candidates, len(ordered))
        if target_count == 1:
            candidate_ids = ordered[:1]
        else:
            last = len(ordered) - 1
            positions = {
                round(index * last / (target_count - 1))
                for index in range(target_count)
            }
            candidate_ids = [ordered[index] for index in sorted(positions)]
        memory_ids = self._fit_budget(
            candidate_ids,
            definitions,
            token_budget=token_budget,
            latency_budget_ms=latency_budget_ms,
        )
        return ReconciliationSelection(
            memory_ids=memory_ids,
            relevance={memory_id: 1.0 for memory_id in memory_ids},
            reason="evaluation-only deterministic source-sequence coverage",
        )

    def _select_operation_memories(
        self,
        query: str,
        definitions: Mapping[str, MemoryDefinition],
        *,
        token_budget: int,
        latency_budget_ms: float,
    ) -> ReconciliationSelection:
        """Put explicit deletion obligations before operation-bearing evidence."""

        query_tokens = _tokens(query)
        tokenized = {
            memory_id: _tokens(definition.content)
            for memory_id, definition in definitions.items()
        }
        document_frequency = Counter(
            token
            for tokens in tokenized.values()
            for token in query_tokens.intersection(tokens)
        )
        total = max(1, len(definitions))
        weights = {
            token: math.log((total + 1) / (document_frequency[token] + 1)) + 1.0
            for token in query_tokens
        }
        denominator = sum(weights.values()) or 1.0
        query_phrases = (
            extract_query_candidate_phrases(query) if self.query_phrase_aware else ()
        )
        ranked: list[tuple[int, int, int, float, int, str]] = []
        scores: dict[str, float] = {}
        relevant_tombstones: set[str] = set()
        for memory_id, definition in definitions.items():
            overlap = query_tokens.intersection(tokenized[memory_id])
            lexical = sum(weights[token] for token in overlap) / denominator
            tombstone = _MEMORY_TOMBSTONE_MARKER in definition.provenance
            normalized_content = normalize_query_phrase(definition.content)
            phrase_hits = sum(
                phrase in normalized_content for phrase in query_phrases
            )
            scores[memory_id] = (
                max(lexical, min(1.0, phrase_hits / max(1, len(query_phrases))))
                if self.target_scoped_tombstones
                else 1.0
                if tombstone
                else lexical
            )
            if self.target_scoped_tombstones:
                relevant_tombstone = tombstone and bool(phrase_hits or lexical > 0.0)
                if relevant_tombstone:
                    relevant_tombstones.add(memory_id)
                ranked.append(
                    (
                        (
                            0
                            if self.relevant_tombstones_first and relevant_tombstone
                            else 1
                            if self.relevant_tombstones_first
                            else 0
                        ),
                        -phrase_hits,
                        -lexical,
                        -_source_order(definition),
                        0 if tombstone else 1,
                        memory_id,
                    )
                )
            else:
                ranked.append(
                    (
                        0,
                        0 if tombstone else 1,
                        -phrase_hits,
                        -lexical,
                        -_source_order(definition),
                        memory_id,
                    )
                )
        ranked.sort()
        candidate_ids = [item[-1] for item in ranked[: self.maximum_candidates]]
        if self.tombstone_cutover and relevant_tombstones:
            cutover_order = max(
                _source_order(definitions[memory_id])
                for memory_id in relevant_tombstones
            )
            candidate_ids = [
                memory_id
                for memory_id in (item[-1] for item in ranked)
                if memory_id in relevant_tombstones
                or _source_order(definitions[memory_id]) >= cutover_order
            ][: self.maximum_candidates]
        memory_ids = self._fit_budget(
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
                if self.tombstone_cutover
                else "evaluation-only slice-local relevant-tombstone-first operation evidence"
                if self.relevant_tombstones_first
                else "evaluation-only target-scoped phrase-aligned operation evidence"
                if self.target_scoped_tombstones
                else (
                    "evaluation-only phrase-aligned operation evidence with mandatory tombstones"
                    if query_phrases
                    else "evaluation-only operation evidence with mandatory tombstones"
                )
            ),
        )

    def _select_claim_graph(
        self,
        query: str,
        definitions: Mapping[str, MemoryDefinition],
        claims: Sequence[ReconciledClaim],
        *,
        token_budget: int,
        latency_budget_ms: float,
    ) -> ReconciliationSelection:
        query_normalized = _normalize_entity(query)
        query_tokens = _tokens(query)
        outgoing: dict[str, list[ReconciledClaim]] = defaultdict(list)
        for claim in claims:
            outgoing[_normalize_entity(claim.subject)].append(claim)
        seeds = sorted(
            subject
            for subject in outgoing
            if subject in query_normalized
            or (_tokens(subject) and _tokens(subject).issubset(query_tokens))
        )
        if not seeds:
            return self._select_ranked_memories(
                query,
                definitions,
                token_budget=token_budget,
                latency_budget_ms=latency_budget_ms,
            )
        queue = deque((seed, 0) for seed in seeds)
        visited_entities = set(seeds)
        selected: list[tuple[ReconciledClaim, int]] = []
        seen_memories: set[str] = set()
        while queue:
            entity, depth = queue.popleft()
            if depth >= self.maximum_graph_hops:
                continue
            for claim in sorted(
                outgoing.get(entity, ()),
                key=lambda item: (item.relation, item.memory_id),
            ):
                if claim.memory_id not in seen_memories:
                    selected.append((claim, depth))
                    seen_memories.add(claim.memory_id)
                target = _normalize_entity(claim.object)
                if target in outgoing and target not in visited_entities:
                    visited_entities.add(target)
                    queue.append((target, depth + 1))
        ranked = sorted(
            selected,
            key=lambda item: (item[1], -item[0].source_order, item[0].memory_id),
        )[: self.maximum_candidates]
        memory_ids = self._fit_budget(
            [item[0].memory_id for item in ranked],
            definitions,
            token_budget=token_budget,
            latency_budget_ms=latency_budget_ms,
        )
        relevance = {
            claim.memory_id: 1.0 / (1.0 + depth)
            for claim, depth in ranked
            if claim.memory_id in memory_ids
        }
        return ReconciliationSelection(
            memory_ids=memory_ids,
            relevance=relevance,
            reason="evaluation-only active-state graph traversal",
        )

    def _select_ranked_memories(
        self,
        query: str,
        definitions: Mapping[str, MemoryDefinition],
        *,
        token_budget: int,
        latency_budget_ms: float,
    ) -> ReconciliationSelection:
        query_tokens = _tokens(query)
        if not query_tokens or not definitions:
            return ReconciliationSelection((), {}, "no query-aligned active state")
        tokenized = {
            memory_id: _tokens(definition.content)
            for memory_id, definition in definitions.items()
        }
        document_frequency = Counter(
            token
            for tokens in tokenized.values()
            for token in query_tokens.intersection(tokens)
        )
        total = max(1, len(definitions))
        query_weight = {
            token: math.log((total + 1) / (document_frequency[token] + 1)) + 1.0
            for token in query_tokens
        }
        denominator = sum(query_weight.values()) or 1.0
        maximum_order = max((_source_order(item) for item in definitions.values()), default=0)
        query_phrases = (
            extract_query_candidate_phrases(query) if self.query_phrase_aware else ()
        )
        ranked: list[tuple[int, float, int, str]] = []
        for memory_id, definition in definitions.items():
            overlap = query_tokens.intersection(tokenized[memory_id])
            if not overlap:
                continue
            lexical = sum(query_weight[token] for token in overlap) / denominator
            order = _source_order(definition)
            recency = (order / maximum_order) if maximum_order else 0.0
            score = lexical + (self.source_recency_weight * recency)
            normalized_content = normalize_query_phrase(definition.content)
            phrase_hits = sum(
                phrase in normalized_content for phrase in query_phrases
            )
            ranked.append((phrase_hits, score, order, memory_id))
        ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
        candidates = [item[3] for item in ranked[: self.maximum_candidates]]
        memory_ids = self._fit_budget(
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
                if self.source_recency_weight == 0.0
                else "evaluation-only lexical-state retrieval with source recency"
            ),
        )

    @staticmethod
    def _fit_budget(
        ranked_ids: Sequence[str],
        definitions: Mapping[str, MemoryDefinition],
        *,
        token_budget: int,
        latency_budget_ms: float,
    ) -> tuple[str, ...]:
        selected: list[str] = []
        tokens = 0
        latency = 0.0
        for memory_id in ranked_ids:
            definition = definitions[memory_id]
            if tokens + definition.estimated_tokens > token_budget:
                continue
            if latency + definition.estimated_latency_ms > latency_budget_ms:
                continue
            selected.append(memory_id)
            tokens += definition.estimated_tokens
            latency += definition.estimated_latency_ms
        return tuple(selected)
