from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import WaveMind
from .evidence import canonical_json_bytes, sha256_bytes
from .scientific_memory import (
    CanaryArm,
    CausalUtilityController,
    EvidenceConstrainedAssociativeGraph,
    GraphEvidenceNode,
    MemoryDefinition,
    MemoryLifecycle,
    ScientificEventLog,
    VerificationDecision,
    VerifierResult,
)
from .scientific_reconciliation import ProofCarryingStateReconciler


class ScientificCandidateMode(str, Enum):
    GRAPH = "evidence-constrained-associative-graph-v1"
    CAUSAL = "causal-utility-controller-v1"
    HYBRID = "hybrid-graph-causal-v1"
    STATE_RECONCILER = "proof-carrying-state-reconciler-v2"
    HIERARCHICAL_RECONCILER = "hierarchical-proof-state-reconciler-v3"
    EFFICIENT_HIERARCHICAL_RECONCILER = (
        "efficient-hierarchical-proof-state-reconciler-v4"
    )
    ATOMIC_BATCH_RECONCILER = "atomic-batch-hierarchical-proof-state-reconciler-v5"
    OPERATION_AWARE_TOMBSTONE_RECONCILER = "operation-aware-tombstone-reconciler-v6"
    QUERY_SLICED_OPERATION_RECONCILER = "query-sliced-operation-aware-reconciler-v7"
    PHRASE_ALIGNED_QUERY_SLICED_RECONCILER = (
        "phrase-aligned-query-sliced-reconciler-v8"
    )
    EVIDENCE_GROUNDED_ANSWER_TRANSDUCER = "evidence-grounded-answer-transducer-v9"
    OPERATION_TRACE_STRICT_OUTPUT_AGENT = "operation-trace-strict-output-agent-v10"
    EVIDENCE_CONTRACTED_QUERY_AGENT = "evidence-contracted-query-agent-v11"


@dataclass(frozen=True)
class ScientificRecall:
    query: str
    selected_memory_ids: tuple[str, ...]
    contents: tuple[str, ...]
    relevance: Mapping[str, float]
    abstained: bool
    reason: str
    estimated_tokens: int
    estimated_latency_ms: float
    evaluation_only: bool = False


class ScientificMemoryRuntime:
    """Executable candidate path over the frozen vector-retrieval substrate.

    Vector search only proposes at most twenty relevant IDs. Production
    eligibility, graph energy, utility bounds, budgets, and abstention are
    decided by the preregistered scientific candidates.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        mode: ScientificCandidateMode,
        event_log: ScientificEventLog | None = None,
        bootstrap_repeats: int = 2000,
        bootstrap_seed: int = 17,
    ) -> None:
        self.mode = ScientificCandidateMode(mode)
        selected_db_path = Path(db_path).resolve()
        self._owns_event_log = event_log is None
        self.event_log = event_log or ScientificEventLog(
            selected_db_path.with_name(
                selected_db_path.name + ".scientific-events.sqlite3"
            )
        )
        self.controller = CausalUtilityController(
            self.event_log,
            bootstrap_repeats=bootstrap_repeats,
            bootstrap_seed=bootstrap_seed,
        )
        self.graph = EvidenceConstrainedAssociativeGraph()
        self.state_reconciler = ProofCarryingStateReconciler(
            maximum_graph_hops=4,
            maximum_candidates=20,
            operation_aware=(
                self.mode
                in {
                    ScientificCandidateMode.OPERATION_AWARE_TOMBSTONE_RECONCILER,
                    ScientificCandidateMode.QUERY_SLICED_OPERATION_RECONCILER,
                    ScientificCandidateMode.PHRASE_ALIGNED_QUERY_SLICED_RECONCILER,
                    ScientificCandidateMode.EVIDENCE_GROUNDED_ANSWER_TRANSDUCER,
                    ScientificCandidateMode.OPERATION_TRACE_STRICT_OUTPUT_AGENT,
                    ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT,
                }
            ),
            source_recency_weight=(
                0.0
                if self.mode
                in {
                    ScientificCandidateMode.QUERY_SLICED_OPERATION_RECONCILER,
                    ScientificCandidateMode.PHRASE_ALIGNED_QUERY_SLICED_RECONCILER,
                    ScientificCandidateMode.EVIDENCE_GROUNDED_ANSWER_TRANSDUCER,
                    ScientificCandidateMode.OPERATION_TRACE_STRICT_OUTPUT_AGENT,
                    ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT,
                }
                else 0.25
            ),
            query_phrase_aware=(
                self.mode
                in {
                    ScientificCandidateMode.PHRASE_ALIGNED_QUERY_SLICED_RECONCILER,
                    ScientificCandidateMode.EVIDENCE_GROUNDED_ANSWER_TRANSDUCER,
                    ScientificCandidateMode.OPERATION_TRACE_STRICT_OUTPUT_AGENT,
                    ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT,
                }
            ),
        )
        self.retriever = WaveMind(
            db_path=selected_db_path,
            vector_weight=1.0,
            field_weight=0.0,
            priority_weight=0.0,
            lexical_weight=0.0,
            short_query_lexical_weight=0.0,
            graph_weight=0.0,
            persist_access_on_query=False,
            query_feedback_strength=0.0,
        )

    def close(self) -> None:
        self.retriever.close()
        if self._owns_event_log:
            self.event_log.close()

    def __enter__(self) -> "ScientificMemoryRuntime":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def register_memory(
        self,
        definition: MemoryDefinition,
        *,
        namespace: str = "scientific",
        actor: str = "training-pipeline",
    ) -> int:
        self.event_log.register_memory(definition, actor=actor)
        return self.retriever.remember(
            definition.content,
            namespace=namespace,
            tags=("scientific-memory", definition.kind.value),
            metadata={
                "scientific_memory_id": definition.memory_id,
                "verification_status": "candidate_unverified",
                "verified": False,
                "kind": definition.kind.value,
            },
        )

    def register_evaluation_memory(
        self,
        definition: MemoryDefinition,
        *,
        actor: str = "evaluation-compiler",
    ) -> None:
        """Persist shadow evidence without duplicating it into production retrieval."""

        if self.mode is not ScientificCandidateMode.EFFICIENT_HIERARCHICAL_RECONCILER:
            raise ValueError("evaluation-only storage is frozen to the v4 candidate")
        self.event_log.register_memory(definition, actor=actor)

    def register_evaluation_memories(
        self,
        definitions: Sequence[MemoryDefinition],
        *,
        actor: str = "evaluation-batch-compiler",
    ) -> tuple[str, ...]:
        """Atomically persist the frozen v5 shadow batch outside production index."""

        if self.mode not in {
            ScientificCandidateMode.ATOMIC_BATCH_RECONCILER,
            ScientificCandidateMode.OPERATION_AWARE_TOMBSTONE_RECONCILER,
            ScientificCandidateMode.QUERY_SLICED_OPERATION_RECONCILER,
            ScientificCandidateMode.PHRASE_ALIGNED_QUERY_SLICED_RECONCILER,
            ScientificCandidateMode.EVIDENCE_GROUNDED_ANSWER_TRANSDUCER,
            ScientificCandidateMode.OPERATION_TRACE_STRICT_OUTPUT_AGENT,
            ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT,
        }:
            raise ValueError("atomic evaluation storage is frozen to v5/v6 candidates")
        events = self.event_log.register_memories(definitions, actor=actor)
        return tuple(event.event_sha256 for event in events)

    def _retrieval_candidates(
        self,
        query: str,
        *,
        namespace: str,
    ) -> tuple[list[str], dict[str, float]]:
        results = self.retriever.query(query, namespace=namespace, top_k=20)
        memory_ids: list[str] = []
        relevance: dict[str, float] = {}
        definitions = self.event_log.definitions()
        for result in results:
            memory_id = str(result.metadata.get("scientific_memory_id") or "")
            if memory_id not in definitions or memory_id in relevance:
                continue
            memory_ids.append(memory_id)
            relevance[memory_id] = max(0.0, min(1.0, float(result.vector_score)))
        return memory_ids, relevance

    def _counterevidence_count(self, memory_id: str) -> int:
        count = 0
        for receipt in self.event_log.receipts().values():
            if (
                memory_id not in receipt.memory_attribution
                or not receipt.verifier_result
            ):
                continue
            result = receipt.verifier_result
            if result.decision is VerificationDecision.FALSIFIED or (
                result.paired_effect() is not None and result.paired_effect() <= 0.0
            ):
                count += 1
        return count

    def _graph_select(
        self,
        memory_ids: Sequence[str],
        relevance: Mapping[str, float],
        *,
        token_budget: int,
        require_causal_promotion: bool,
        associations: Mapping[tuple[str, str], float] | None,
        conflicts: Mapping[tuple[str, str], float] | None,
    ) -> tuple[str, ...]:
        nodes: list[GraphEvidenceNode] = []
        for memory_id in memory_ids:
            state = self.event_log.memory_state(memory_id)
            estimate = self.controller.estimate(memory_id)
            if (
                require_causal_promotion
                and state.lifecycle is not MemoryLifecycle.PRODUCTION
            ):
                continue
            nodes.append(
                GraphEvidenceNode(
                    memory_id=memory_id,
                    evidence_count=estimate.verified_pair_count,
                    counterevidence_count=self._counterevidence_count(memory_id),
                    relevance=float(relevance[memory_id]),
                    utility_lower_bound=estimate.ci_lower,
                    uncertainty_width=estimate.uncertainty_width,
                    estimated_tokens=state.definition.estimated_tokens,
                )
            )
        return self.graph.select(
            nodes,
            token_budget=token_budget,
            associations=associations,
            conflicts=conflicts,
        )

    def recall(
        self,
        query: str,
        *,
        context: Mapping[str, str],
        moment: float,
        token_budget: int,
        latency_budget_ms: float,
        max_safety_risk: float,
        namespace: str = "scientific",
        associations: Mapping[tuple[str, str], float] | None = None,
        conflicts: Mapping[tuple[str, str], float] | None = None,
    ) -> ScientificRecall:
        memory_ids, relevance = self._retrieval_candidates(
            query,
            namespace=namespace,
        )
        if not memory_ids:
            return ScientificRecall(
                query=query,
                selected_memory_ids=(),
                contents=(),
                relevance={},
                abstained=True,
                reason="vector substrate found no confidence-qualified candidate",
                estimated_tokens=0,
                estimated_latency_ms=0.0,
            )
        if self.mode is ScientificCandidateMode.CAUSAL:
            decision = self.controller.select_minimal_memories(
                memory_ids,
                context=context,
                moment=moment,
                token_budget=token_budget,
                latency_budget_ms=latency_budget_ms,
                max_safety_risk=max_safety_risk,
            )
            selected = decision.selected_memory_ids
            reason = decision.reason
        else:
            selected = self._graph_select(
                memory_ids,
                relevance,
                token_budget=token_budget,
                require_causal_promotion=self.mode is ScientificCandidateMode.HYBRID,
                associations=associations,
                conflicts=conflicts,
            )
            definitions = self.event_log.definitions()
            selected = tuple(
                memory_id
                for memory_id in selected
                if all(
                    str(context.get(key)) == value
                    for key, value in definitions[memory_id].applicability.items()
                )
                and definitions[memory_id].validity.contains(moment)
                and definitions[memory_id].safety_risk <= max_safety_risk
            )
            latency = sum(
                definitions[memory_id].estimated_latency_ms for memory_id in selected
            )
            if latency > latency_budget_ms:
                selected = ()
            reason = (
                "negative-energy evidence-constrained subset"
                if selected
                else "graph candidate abstained because proof or constraints failed"
            )
        definitions = self.event_log.definitions()
        tokens = sum(definitions[memory_id].estimated_tokens for memory_id in selected)
        latency = sum(
            definitions[memory_id].estimated_latency_ms for memory_id in selected
        )
        return ScientificRecall(
            query=query,
            selected_memory_ids=tuple(selected),
            contents=tuple(definitions[memory_id].content for memory_id in selected),
            relevance={memory_id: relevance[memory_id] for memory_id in selected},
            abstained=not bool(selected),
            reason=reason,
            estimated_tokens=tokens,
            estimated_latency_ms=latency,
        )

    def shadow_recall(
        self,
        query: str,
        *,
        context: Mapping[str, str],
        moment: float,
        token_budget: int,
        latency_budget_ms: float,
        max_safety_risk: float,
        namespace: str = "scientific",
    ) -> ScientificRecall:
        """Select evaluation candidates without granting production eligibility."""
        memory_ids, relevance = self._retrieval_candidates(query, namespace=namespace)
        definitions = self.event_log.definitions()
        eligible = []
        for memory_id in memory_ids:
            definition = definitions[memory_id]
            if not all(
                str(context.get(key)) == value
                for key, value in definition.applicability.items()
            ):
                continue
            if not definition.validity.contains(moment):
                continue
            if definition.safety_risk > max_safety_risk:
                continue
            eligible.append(memory_id)
        eligible.sort(key=lambda memory_id: (-relevance[memory_id], memory_id))
        selected: list[str] = []
        tokens = 0
        latency = 0.0
        for memory_id in eligible:
            definition = definitions[memory_id]
            if tokens + definition.estimated_tokens > token_budget:
                continue
            if latency + definition.estimated_latency_ms > latency_budget_ms:
                continue
            selected.append(memory_id)
            tokens += definition.estimated_tokens
            latency += definition.estimated_latency_ms
        return ScientificRecall(
            query=query,
            selected_memory_ids=tuple(selected),
            contents=tuple(definitions[memory_id].content for memory_id in selected),
            relevance={memory_id: relevance[memory_id] for memory_id in selected},
            abstained=not bool(selected),
            reason=(
                "evaluation-only shadow replay; no production eligibility granted"
                if selected
                else "shadow replay abstained because applicability or constraints failed"
            ),
            estimated_tokens=tokens,
            estimated_latency_ms=latency,
            evaluation_only=True,
        )

    def evaluation_recall(
        self,
        query: str,
        *,
        context: Mapping[str, str],
        moment: float,
        token_budget: int,
        latency_budget_ms: float,
        max_safety_risk: float,
        namespace: str = "scientific",
    ) -> ScientificRecall:
        """Run the frozen v2 selector without granting production eligibility."""

        if self.mode not in {
            ScientificCandidateMode.STATE_RECONCILER,
            ScientificCandidateMode.HIERARCHICAL_RECONCILER,
            ScientificCandidateMode.EFFICIENT_HIERARCHICAL_RECONCILER,
            ScientificCandidateMode.ATOMIC_BATCH_RECONCILER,
            ScientificCandidateMode.OPERATION_AWARE_TOMBSTONE_RECONCILER,
            ScientificCandidateMode.QUERY_SLICED_OPERATION_RECONCILER,
            ScientificCandidateMode.PHRASE_ALIGNED_QUERY_SLICED_RECONCILER,
            ScientificCandidateMode.EVIDENCE_GROUNDED_ANSWER_TRANSDUCER,
            ScientificCandidateMode.OPERATION_TRACE_STRICT_OUTPUT_AGENT,
            ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT,
        }:
            return self.shadow_recall(
                query,
                context=context,
                moment=moment,
                token_budget=token_budget,
                latency_budget_ms=latency_budget_ms,
                max_safety_risk=max_safety_risk,
                namespace=namespace,
            )
        definitions = self.event_log.definitions()
        selection = self.state_reconciler.select(
            query,
            definitions,
            token_budget=token_budget,
            latency_budget_ms=latency_budget_ms,
            max_safety_risk=max_safety_risk,
            context=context,
            moment=moment,
        )
        selected = selection.memory_ids
        tokens = sum(definitions[memory_id].estimated_tokens for memory_id in selected)
        latency = sum(
            definitions[memory_id].estimated_latency_ms for memory_id in selected
        )
        return ScientificRecall(
            query=query,
            selected_memory_ids=selected,
            contents=tuple(definitions[memory_id].content for memory_id in selected),
            relevance=selection.relevance,
            abstained=not bool(selected),
            reason=selection.reason,
            estimated_tokens=tokens,
            estimated_latency_ms=latency,
            evaluation_only=True,
        )

    def record_verified_influence(
        self,
        recall: ScientificRecall,
        *,
        receipt_id: str,
        task_id: str,
        case_id: str,
        action: Mapping[str, Any],
        verifier_result: VerifierResult,
        safe_for_randomization: bool,
        canary_arm: CanaryArm | None = None,
    ) -> str:
        if recall.abstained or not recall.selected_memory_ids:
            raise ValueError("an abstained recall cannot create an influence receipt")
        raw_weights = {
            memory_id: max(float(recall.relevance.get(memory_id, 0.0)), 1e-12)
            for memory_id in recall.selected_memory_ids
        }
        total = math.fsum(raw_weights.values())
        weights = {memory_id: value / total for memory_id, value in raw_weights.items()}
        context_digest = sha256_bytes(
            canonical_json_bytes(
                {
                    "query": recall.query,
                    "memory_ids": list(recall.selected_memory_ids),
                    "contents": list(recall.contents),
                }
            )
        )
        action_digest = sha256_bytes(canonical_json_bytes(dict(action)))
        receipt = self.event_log.record_influence(
            receipt_id=receipt_id,
            task_id=task_id,
            case_id=case_id,
            memory_attribution=weights,
            context_sha256=context_digest,
            action_sha256=action_digest,
            safe_for_randomization=safe_for_randomization,
            canary_arm=canary_arm,
        )
        self.event_log.verify_influence(receipt.receipt_id, verifier_result)
        for memory_id in recall.selected_memory_ids:
            self.controller.update_lifecycle(memory_id)
        return self.event_log.events[-1].event_sha256
