from __future__ import annotations

import hashlib
import importlib.util
import math
import sys
import threading
import types
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "benchmarks" / "scientific_longmemeval_v2_backend.py"
OFFICIAL_REPOSITORY_SHA = "2cc8c540bdb87fe6761629b585e727e1c4704520"
CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
MEMORY_TYPE = "wavemind_scientific_v31"


def _memory_safe_select_operation_memories(
    self,
    query,
    definitions,
    *,
    token_budget,
    latency_budget_ms,
):
    reconciliation = sys.modules[type(self).__module__]
    query_tokens = reconciliation._tokens(query)
    overlaps = {}
    document_frequency = Counter()
    for memory_id, definition in definitions.items():
        overlap = query_tokens.intersection(
            reconciliation._tokens(definition.content)
        )
        overlaps[memory_id] = overlap
        document_frequency.update(overlap)
    total = max(1, len(definitions))
    weights = {
        token: math.log((total + 1) / (document_frequency[token] + 1)) + 1.0
        for token in query_tokens
    }
    denominator = sum(weights.values()) or 1.0
    query_phrases = (
        reconciliation.extract_query_candidate_phrases(query)
        if self.query_phrase_aware
        else ()
    )
    ranked = []
    scores = {}
    relevant_tombstones = set()
    for memory_id, definition in definitions.items():
        overlap = overlaps[memory_id]
        lexical = sum(weights[token] for token in overlap) / denominator
        tombstone = reconciliation._MEMORY_TOMBSTONE_MARKER in definition.provenance
        normalized_content = reconciliation.normalize_query_phrase(definition.content)
        phrase_hits = sum(phrase in normalized_content for phrase in query_phrases)
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
                    -reconciliation._source_order(definition),
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
                    -reconciliation._source_order(definition),
                    memory_id,
                )
            )
    ranked.sort()
    candidate_ids = [item[-1] for item in ranked[: self.maximum_candidates]]
    if self.tombstone_cutover and relevant_tombstones:
        cutover_order = max(
            reconciliation._source_order(definitions[memory_id])
            for memory_id in relevant_tombstones
        )
        candidate_ids = [
            memory_id
            for memory_id in (item[-1] for item in ranked)
            if memory_id in relevant_tombstones
            or reconciliation._source_order(definitions[memory_id]) >= cutover_order
        ][: self.maximum_candidates]
    memory_ids = self._fit_budget(
        candidate_ids,
        definitions,
        token_budget=token_budget,
        latency_budget_ms=latency_budget_ms,
    )
    return reconciliation.ReconciliationSelection(
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


def _memory_safe_select_ranked_memories(
    self,
    query,
    definitions,
    *,
    token_budget,
    latency_budget_ms,
):
    reconciliation = sys.modules[type(self).__module__]
    query_tokens = reconciliation._tokens(query)
    if not query_tokens or not definitions:
        return reconciliation.ReconciliationSelection(
            (), {}, "no query-aligned active state"
        )
    overlaps = {}
    document_frequency = Counter()
    for memory_id, definition in definitions.items():
        overlap = query_tokens.intersection(
            reconciliation._tokens(definition.content)
        )
        overlaps[memory_id] = overlap
        document_frequency.update(overlap)
    total = max(1, len(definitions))
    query_weight = {
        token: math.log((total + 1) / (document_frequency[token] + 1)) + 1.0
        for token in query_tokens
    }
    denominator = sum(query_weight.values()) or 1.0
    maximum_order = max(
        (reconciliation._source_order(item) for item in definitions.values()),
        default=0,
    )
    query_phrases = (
        reconciliation.extract_query_candidate_phrases(query)
        if self.query_phrase_aware
        else ()
    )
    ranked = []
    for memory_id, definition in definitions.items():
        overlap = overlaps[memory_id]
        if not overlap:
            continue
        lexical = sum(query_weight[token] for token in overlap) / denominator
        order = reconciliation._source_order(definition)
        recency = (order / maximum_order) if maximum_order else 0.0
        score = lexical + (self.source_recency_weight * recency)
        normalized_content = reconciliation.normalize_query_phrase(definition.content)
        phrase_hits = sum(phrase in normalized_content for phrase in query_phrases)
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
    return reconciliation.ReconciliationSelection(
        memory_ids=memory_ids,
        relevance={
            memory_id: min(1.0, scores[memory_id]) for memory_id in memory_ids
        },
        reason=(
            "evaluation-only phrase-aligned lexical-state retrieval without source recency"
            if query_phrases
            else "evaluation-only lexical-state retrieval without source recency"
            if self.source_recency_weight == 0.0
            else "evaluation-only lexical-state retrieval with source recency"
        ),
    )


def _base_module():
    spec = importlib.util.spec_from_file_location(
        "wavemind_scientific_longmemeval_v31_base", BASE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load frozen LongMemEval-V2 adapter base")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OFFICIAL_REPOSITORY_SHA = OFFICIAL_REPOSITORY_SHA
    module.CANDIDATE_SOURCE_SHA = CANDIDATE_SOURCE_SHA
    module.MEMORY_TYPE = MEMORY_TYPE
    return module


def register_backend(*, official_repository: str | Path, candidate_repository: str | Path):
    backend_class = _base_module().register_backend(
        official_repository=official_repository,
        candidate_repository=candidate_repository,
    )
    original_init = backend_class.__init__
    original_compile_once = backend_class._compile_once
    original_query = backend_class.query
    original_post_query_hook = backend_class.post_query_hook

    def synchronized_init(self, memory_params):
        original_init(self, memory_params)
        self._v31_compile_lock = threading.Lock()
        self._v31_query_lock = threading.Lock()
        self._v31_query_metadata = threading.local()
        reconciler = self._runtime.state_reconciler
        reconciler._select_operation_memories = types.MethodType(
            _memory_safe_select_operation_memories,
            reconciler,
        )
        reconciler._select_ranked_memories = types.MethodType(
            _memory_safe_select_ranked_memories,
            reconciler,
        )

    def synchronized_compile_once(self):
        if self._compiled:
            return
        with self._v31_compile_lock:
            if self._compiled:
                return
            original_compile_once(self)

    def synchronized_query(self, query, query_image=None):
        with self._v31_query_lock:
            context = original_query(self, query, query_image=query_image)
            self._v31_query_metadata.value = dict(self._last_metadata or {})
            return context

    def thread_local_post_query_hook(
        self,
        *,
        query,
        query_image,
        memory_context,
    ):
        metadata = getattr(self._v31_query_metadata, "value", None)
        if metadata is None:
            return original_post_query_hook(
                self,
                query=query,
                query_image=query_image,
                memory_context=memory_context,
            )
        del self._v31_query_metadata.value
        return dict(metadata)

    backend_class.__init__ = synchronized_init
    backend_class._compile_once = synchronized_compile_once
    backend_class.query = synchronized_query
    backend_class.post_query_hook = thread_local_post_query_hook
    return backend_class


def registration_fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(BASE_PATH.read_bytes())
    digest.update(Path(__file__).read_bytes())
    digest.update(OFFICIAL_REPOSITORY_SHA.encode("ascii"))
    digest.update(CANDIDATE_SOURCE_SHA.encode("ascii"))
    digest.update(MEMORY_TYPE.encode("ascii"))
    return digest.hexdigest()
