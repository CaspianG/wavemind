from __future__ import annotations

import math
import re
import time
from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable, Mapping

import numpy as np

from .encoders import HashingTextEncoder
from .experience import (
    CandidateValidationSummary,
    ExperienceRecord,
    ExperienceStatus,
    SQLiteExperienceStore,
    TrustClass,
)
from .memory_firewall import (
    FirewallAction,
    FirewallContext,
    FirewallDecision,
    FirewallVerdict,
    MemoryFirewall,
)


_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)


@dataclass(frozen=True)
class ExperienceCompilerPolicy:
    shadow_validation_count: int = 2
    activation_validation_count: int = 3
    minimum_success_rate: float = 0.8
    minimum_average_score: float = 0.6
    rejection_failure_count: int = 2
    default_token_budget: int = 800
    max_item_tokens: int = 160
    recency_half_life_days: float = 30.0
    vector_weight: float = 0.38
    lexical_weight: float = 0.18
    applicability_weight: float = 0.12
    confidence_weight: float = 0.10
    trust_weight: float = 0.10
    outcome_weight: float = 0.07
    recency_weight: float = 0.05

    def __post_init__(self) -> None:
        if self.shadow_validation_count < 1:
            raise ValueError("shadow_validation_count must be positive")
        if self.activation_validation_count < self.shadow_validation_count:
            raise ValueError(
                "activation_validation_count must be >= shadow_validation_count"
            )
        if not 0.0 <= self.minimum_success_rate <= 1.0:
            raise ValueError("minimum_success_rate must be in [0, 1]")
        if not 0.0 <= self.minimum_average_score <= 1.0:
            raise ValueError("minimum_average_score must be in [0, 1]")
        if self.rejection_failure_count < 1:
            raise ValueError("rejection_failure_count must be positive")
        if self.default_token_budget < 32:
            raise ValueError("default_token_budget must be at least 32")
        if self.max_item_tokens < 8:
            raise ValueError("max_item_tokens must be at least 8")
        if self.recency_half_life_days <= 0.0:
            raise ValueError("recency_half_life_days must be positive")
        weights = (
            self.vector_weight,
            self.lexical_weight,
            self.applicability_weight,
            self.confidence_weight,
            self.trust_weight,
            self.outcome_weight,
            self.recency_weight,
        )
        if any(weight < 0.0 for weight in weights):
            raise ValueError("compiler signal weights must be non-negative")
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
            raise ValueError("compiler signal weights must sum to 1.0")


@dataclass(frozen=True)
class CandidateReview:
    experience_id: str
    previous_status: ExperienceStatus
    status: ExperienceStatus
    validation: CandidateValidationSummary
    firewall: FirewallDecision | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "previous_status": self.previous_status.value,
            "status": self.status.value,
            "validation": asdict(self.validation),
            "firewall": self.firewall.as_dict() if self.firewall else None,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExperiencePacketItem:
    experience_id: str
    version: int
    kind: str
    title: str
    excerpt: str
    score: float
    signals: dict[str, float]
    citation: str
    detail_ref: str
    provenance: dict[str, Any]
    estimated_tokens: int
    canary: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExperiencePacket:
    namespace: str
    query: str
    token_budget: int
    estimated_tokens: int
    items: tuple[ExperiencePacketItem, ...]
    omitted_count: int
    generated_at: float
    compiler_policy: dict[str, Any]

    @property
    def citations(self) -> tuple[str, ...]:
        return tuple(item.citation for item in self.items)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "wavemind.experience_packet.v1",
            "namespace": self.namespace,
            "query": self.query,
            "token_budget": self.token_budget,
            "estimated_tokens": self.estimated_tokens,
            "items": [item.as_dict() for item in self.items],
            "omitted_count": self.omitted_count,
            "generated_at": self.generated_at,
            "compiler_policy": dict(self.compiler_policy),
            "citations": list(self.citations),
        }

    def as_prompt(self) -> str:
        lines = [
            f"Experience packet for namespace {self.namespace}:",
            "Use only when applicable. Cite bracketed experience references.",
        ]
        for index, item in enumerate(self.items, start=1):
            canary = " [canary]" if item.canary else ""
            lines.append(
                f"[E{index}] {item.title}{canary}: {item.excerpt} "
                f"({item.citation})"
            )
        if self.omitted_count:
            lines.append(
                f"{self.omitted_count} lower-ranked experience(s) omitted by token budget."
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class ExperienceDetail:
    experience_id: str
    version: int
    kind: str
    title: str
    content: str
    applicability: dict[str, Any]
    outcome: dict[str, Any]
    source: dict[str, Any]
    trajectory: dict[str, Any] | None
    citation: str
    content_sha256: str


class ExperienceCompiler:
    def __init__(
        self,
        store: SQLiteExperienceStore,
        firewall: MemoryFirewall,
        *,
        policy: ExperienceCompilerPolicy | None = None,
        encoder: HashingTextEncoder | None = None,
    ):
        if store.path != ":memory:" and firewall.policy.namespace == "":
            raise ValueError("firewall policy requires a namespace")
        self.store = store
        self.firewall = firewall
        self.policy = policy or ExperienceCompilerPolicy()
        self.encoder = encoder or HashingTextEncoder(vector_dim=384)

    def submit(
        self,
        record: ExperienceRecord,
        *,
        context: FirewallContext,
    ) -> tuple[ExperienceRecord, FirewallDecision]:
        existing = self.store.list(
            namespace=record.namespace,
            include_expired=False,
            limit=10_000,
        )
        decision = self.firewall.evaluate(
            record,
            FirewallAction.INGEST,
            context=context,
            existing=existing,
        )
        if decision.verdict == FirewallVerdict.DENY:
            raise PermissionError(
                f"experience ingest denied: {', '.join(decision.reason_codes)}"
            )
        status = decision.recommended_status or ExperienceStatus.SHADOW
        prepared = replace(
            record,
            status=status,
            metadata={
                **record.metadata,
                "firewall_policy_id": decision.policy_id,
                "firewall_policy_version": decision.policy_version,
                "firewall_reason_codes": list(decision.reason_codes),
                "tainted": bool(decision.tainted),
            },
        )
        stored = self.store.put(prepared)
        return stored, decision

    def review_candidate(
        self,
        experience_id: str,
        *,
        evidence_id: str,
        successful: bool,
        score: float | None,
        context: FirewallContext,
        metadata: Mapping[str, Any] | None = None,
    ) -> CandidateReview:
        current = self.store.get(experience_id)
        if current is None:
            raise KeyError(experience_id)
        if current.status not in {
            ExperienceStatus.SHADOW,
            ExperienceStatus.CANARY,
            ExperienceStatus.ACTIVE,
        }:
            raise ValueError(
                f"candidate review is not allowed in {current.status.value} status"
            )
        summary = self.store.add_candidate_validation(
            experience_id,
            evidence_id=evidence_id,
            successful=successful,
            score=score,
            metadata=metadata,
        )
        previous = current.status
        firewall_decision: FirewallDecision | None = None
        reason = "more_validation_required"

        if summary.failed_count >= self.policy.rejection_failure_count:
            current = self.store.transition_status(
                experience_id,
                ExperienceStatus.REJECTED,
                reason="candidate exceeded the validation failure budget",
            )
            reason = "failure_budget_exceeded"
        elif (
            current.status == ExperienceStatus.SHADOW
            and summary.validation_count >= self.policy.shadow_validation_count
            and summary.success_rate >= self.policy.minimum_success_rate
            and self._score_passes(summary)
        ):
            current = self.store.transition_status(
                experience_id,
                ExperienceStatus.CANARY,
                reason="candidate met shadow validation gates",
            )
            reason = "promoted_to_canary"

        if (
            current.status == ExperienceStatus.CANARY
            and summary.validation_count >= self.policy.activation_validation_count
            and summary.success_rate >= self.policy.minimum_success_rate
            and self._score_passes(summary)
        ):
            existing = self.store.list(
                namespace=current.namespace,
                status=ExperienceStatus.ACTIVE,
                limit=10_000,
            )
            activation_context = replace(context, validated_candidate=True)
            firewall_decision = self.firewall.evaluate(
                current,
                FirewallAction.ACTIVATE,
                context=activation_context,
                existing=existing,
            )
            if firewall_decision.allowed:
                current = self.store.transition_status(
                    experience_id,
                    ExperienceStatus.ACTIVE,
                    reason="candidate met activation and firewall gates",
                )
                reason = "activated"
            elif firewall_decision.verdict == FirewallVerdict.QUARANTINE:
                current = self.store.transition_status(
                    experience_id,
                    ExperienceStatus.QUARANTINED,
                    reason=(
                        "activation blocked by firewall: "
                        + ", ".join(firewall_decision.reason_codes)
                    ),
                )
                reason = "firewall_quarantine"

        return CandidateReview(
            experience_id=experience_id,
            previous_status=previous,
            status=current.status,
            validation=summary,
            firewall=firewall_decision,
            reason=reason,
        )

    def reject(
        self,
        experience_id: str,
        *,
        reason: str,
        actor: str = "experience_compiler",
    ) -> ExperienceRecord:
        return self.store.transition_status(
            experience_id,
            ExperienceStatus.REJECTED,
            reason=reason,
            actor=actor,
        )

    def delete(
        self,
        experience_id: str,
        *,
        reason: str,
        context: FirewallContext,
    ) -> bool:
        record = self.store.get(experience_id)
        if record is None:
            return False
        self.firewall.enforce(
            record,
            FirewallAction.DELETE,
            context=context,
        )
        return self.store.delete(
            experience_id,
            reason=reason,
            actor=context.actor,
        )

    def rollback(
        self,
        experience_id: str,
        *,
        reason: str,
        context: FirewallContext,
    ) -> ExperienceRecord:
        record = self.store.get(experience_id)
        if record is None:
            raise KeyError(experience_id)
        self.firewall.enforce(
            record,
            FirewallAction.SUPERSEDE,
            context=context,
        )
        return self.store.rollback(experience_id, reason=reason)

    def compile_packet(
        self,
        query: str,
        *,
        namespace: str,
        context: FirewallContext,
        token_budget: int | None = None,
        top_k: int = 8,
        domains: Iterable[str] = (),
        task_types: Iterable[str] = (),
        tools: Iterable[str] = (),
        include_canary: bool = False,
    ) -> ExperiencePacket:
        query = query.strip()
        if not query:
            raise ValueError("packet query must not be empty")
        budget = int(token_budget or self.policy.default_token_budget)
        if budget < 32:
            raise ValueError("token_budget must be at least 32")
        if not 1 <= int(top_k) <= 100:
            raise ValueError("top_k must be between 1 and 100")
        statuses = [ExperienceStatus.ACTIVE]
        if include_canary:
            statuses.append(ExperienceStatus.CANARY)
        records: list[ExperienceRecord] = []
        for status in statuses:
            records.extend(
                self.store.list(
                    namespace=namespace,
                    status=status,
                    limit=10_000,
                )
            )
        selected_context = replace(
            context,
            canary=bool(include_canary),
            validated_candidate=bool(include_canary),
        )
        query_vector = self.encoder.encode_vector(query)
        query_tokens = _tokens(query)
        requested = {
            "domains": {value.lower() for value in domains},
            "task_types": {value.lower() for value in task_types},
            "tools": {value.lower() for value in tools},
        }
        ranked: list[tuple[float, ExperienceRecord, dict[str, float]]] = []
        for record in records:
            decision = self.firewall.evaluate(
                record,
                FirewallAction.RETRIEVE,
                context=selected_context,
            )
            if not decision.allowed:
                continue
            signals = self._signals(
                record,
                query_vector=query_vector,
                query_tokens=query_tokens,
                requested=requested,
            )
            score = sum(
                signals[name] * weight
                for name, weight in self._weights().items()
            )
            ranked.append((score, record, signals))
        ranked.sort(key=lambda row: (-row[0], -row[1].confidence, row[1].id))

        header_tokens = _estimated_tokens(
            f"Experience packet for namespace {namespace}. "
            "Use only when applicable and cite experience references."
        )
        consumed = header_tokens
        items: list[ExperiencePacketItem] = []
        considered = ranked[: int(top_k)]
        for score, record, signals in considered:
            remaining = budget - consumed
            if remaining < 12:
                break
            excerpt_budget = min(
                self.policy.max_item_tokens,
                max(8, remaining - 8),
            )
            excerpt = _truncate_tokens(record.content, excerpt_budget)
            item_tokens = _estimated_tokens(record.title) + _estimated_tokens(
                excerpt
            ) + 8
            if item_tokens > remaining:
                continue
            citation = f"experience:{record.id}@v{record.version}"
            provenance = {
                "source": {
                    "provider": record.source.provider,
                    "source_type": record.source.source_type,
                    "source_id": record.source.source_id,
                },
                "trajectory_id": (
                    record.trajectory.trajectory_id if record.trajectory else None
                ),
                "content_sha256": record.content_sha256,
            }
            items.append(
                ExperiencePacketItem(
                    experience_id=record.id,
                    version=record.version,
                    kind=record.kind.value,
                    title=record.title,
                    excerpt=excerpt,
                    score=round(float(score), 6),
                    signals={
                        key: round(float(value), 6)
                        for key, value in signals.items()
                    },
                    citation=citation,
                    detail_ref=f"experience://{record.id}?version={record.version}",
                    provenance=provenance,
                    estimated_tokens=item_tokens,
                    canary=record.status == ExperienceStatus.CANARY,
                )
            )
            consumed += item_tokens
        return ExperiencePacket(
            namespace=namespace,
            query=query,
            token_budget=budget,
            estimated_tokens=consumed,
            items=tuple(items),
            omitted_count=max(0, len(considered) - len(items)),
            generated_at=time.time(),
            compiler_policy={
                "signal_weights": self._weights(),
                "recency_half_life_days": self.policy.recency_half_life_days,
                "active_only": not include_canary,
                "progressive_disclosure": True,
            },
        )

    def expand(
        self,
        experience_ids: Iterable[str],
        *,
        namespace: str,
        context: FirewallContext,
    ) -> list[ExperienceDetail]:
        details = []
        for experience_id in dict.fromkeys(experience_ids):
            record = self.store.get(experience_id)
            if record is None or record.namespace != namespace:
                continue
            decision = self.firewall.evaluate(
                record,
                FirewallAction.RETRIEVE,
                context=context,
            )
            if not decision.allowed:
                continue
            details.append(
                ExperienceDetail(
                    experience_id=record.id,
                    version=record.version,
                    kind=record.kind.value,
                    title=record.title,
                    content=record.content,
                    applicability=record.applicability.as_dict(),
                    outcome=record.outcome.as_dict(),
                    source=record.source.as_dict(),
                    trajectory=(
                        record.trajectory.as_dict() if record.trajectory else None
                    ),
                    citation=f"experience:{record.id}@v{record.version}",
                    content_sha256=record.content_sha256,
                )
            )
        return details

    def _score_passes(self, summary: CandidateValidationSummary) -> bool:
        return (
            summary.average_score is None
            or summary.average_score >= self.policy.minimum_average_score
        )

    def _signals(
        self,
        record: ExperienceRecord,
        *,
        query_vector: np.ndarray,
        query_tokens: set[str],
        requested: Mapping[str, set[str]],
    ) -> dict[str, float]:
        record_vector = self.encoder.encode_vector(
            f"{record.title}\n{record.content}"
        )
        vector = max(0.0, float(np.dot(query_vector, record_vector)))
        record_tokens = _tokens(f"{record.title} {record.content}")
        lexical = (
            len(query_tokens & record_tokens) / len(query_tokens | record_tokens)
            if query_tokens and record_tokens
            else 0.0
        )
        applicability = _applicability_score(record, requested, query_tokens)
        outcome = (
            record.outcome.score
            if record.outcome.score is not None
            else 1.0
            if record.outcome.success is True
            else 0.0
            if record.outcome.success is False
            else 0.5
        )
        age_days = max(0.0, (time.time() - record.observed_at) / 86_400.0)
        recency = math.exp(
            -math.log(2.0) * age_days / self.policy.recency_half_life_days
        )
        return {
            "vector": min(1.0, vector),
            "lexical": min(1.0, lexical),
            "applicability": min(1.0, applicability),
            "confidence": float(record.confidence),
            "trust": _trust_signal(record.trust),
            "outcome": float(outcome),
            "recency": min(1.0, recency),
        }

    def _weights(self) -> dict[str, float]:
        return {
            "vector": self.policy.vector_weight,
            "lexical": self.policy.lexical_weight,
            "applicability": self.policy.applicability_weight,
            "confidence": self.policy.confidence_weight,
            "trust": self.policy.trust_weight,
            "outcome": self.policy.outcome_weight,
            "recency": self.policy.recency_weight,
        }


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _TOKEN_RE.finditer(text)}


def _estimated_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def _truncate_tokens(text: str, token_budget: int) -> str:
    max_chars = max(4, int(token_budget) * 4)
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 3)].rstrip() + "..."


def _applicability_score(
    record: ExperienceRecord,
    requested: Mapping[str, set[str]],
    query_tokens: set[str],
) -> float:
    groups = {
        "domains": {value.lower() for value in record.applicability.domains},
        "task_types": {value.lower() for value in record.applicability.task_types},
        "tools": {value.lower() for value in record.applicability.tools},
    }
    scores = []
    for name, values in groups.items():
        if not values:
            continue
        explicit = requested.get(name, set())
        if explicit:
            scores.append(len(explicit & values) / len(explicit | values))
        else:
            expanded = set()
            for value in values:
                expanded.update(_tokens(value))
            scores.append(
                len(query_tokens & expanded) / len(expanded) if expanded else 0.0
            )
    if not scores:
        return 0.5
    return sum(scores) / len(scores)


def _trust_signal(trust: TrustClass) -> float:
    return {
        TrustClass.UNTRUSTED_EXTERNAL: 0.0,
        TrustClass.IMPORTED: 0.25,
        TrustClass.AGENT_GENERATED: 0.40,
        TrustClass.TOOL_OUTPUT: 0.60,
        TrustClass.EXPLICIT_USER: 0.85,
        TrustClass.VERIFIED_OPERATOR: 0.95,
        TrustClass.SYSTEM: 1.0,
    }[trust]
