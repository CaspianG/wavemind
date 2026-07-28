from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable

from .experience import (
    ExperienceKind,
    ExperienceRecord,
    ExperienceStatus,
    TrustClass,
)


class FirewallAction(str, Enum):
    INGEST = "ingest"
    ACTIVATE = "activate"
    RETRIEVE = "retrieve"
    EXPORT = "export"
    DELETE = "delete"
    SUPERSEDE = "supersede"


class FirewallVerdict(str, Enum):
    ALLOW = "allow"
    QUARANTINE = "quarantine"
    REQUIRE_CONSENT = "require_consent"
    DENY = "deny"


@dataclass(frozen=True)
class MemoryFirewallPolicy:
    namespace: str
    policy_id: str = "default"
    version: int = 1
    locked: bool = True
    allow_cross_namespace: bool = False
    protected_ids: tuple[str, ...] = ()
    protected_kinds: tuple[ExperienceKind, ...] = (
        ExperienceKind.CONSTRAINT,
        ExperienceKind.CORRECTION,
    )
    require_consent_for_user_data: bool = True
    allow_canary_retrieval: bool = False
    sensitive_metadata_keys: tuple[str, ...] = (
        "secret",
        "credential",
        "api_key",
        "access_token",
        "personal_data",
    )

    def __post_init__(self) -> None:
        if not self.namespace.strip():
            raise ValueError("firewall namespace must not be empty")
        if int(self.version) < 1:
            raise ValueError("firewall policy version must be positive")
        object.__setattr__(
            self,
            "protected_kinds",
            tuple(
                value
                if isinstance(value, ExperienceKind)
                else ExperienceKind(str(value))
                for value in self.protected_kinds
            ),
        )


@dataclass(frozen=True)
class FirewallContext:
    namespace: str
    actor: str = "agent"
    actor_trust: TrustClass = TrustClass.AGENT_GENERATED
    consent_token: str | None = None
    operator_override: bool = False
    cross_namespace_grant: bool = False
    validated_candidate: bool = False
    canary: bool = False
    purpose: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FirewallDecision:
    action: FirewallAction
    verdict: FirewallVerdict
    reason_codes: tuple[str, ...]
    policy_id: str
    policy_version: int
    record_id: str
    namespace: str
    tainted: bool
    recommended_status: ExperienceStatus | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict == FirewallVerdict.ALLOW

    @property
    def contained(self) -> bool:
        return self.verdict in {
            FirewallVerdict.QUARANTINE,
            FirewallVerdict.REQUIRE_CONSENT,
            FirewallVerdict.DENY,
        }

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action"] = self.action.value
        payload["verdict"] = self.verdict.value
        payload["recommended_status"] = (
            self.recommended_status.value if self.recommended_status else None
        )
        return payload


class MemoryFirewallDenied(PermissionError):
    def __init__(self, decision: FirewallDecision):
        self.decision = decision
        reasons = ", ".join(decision.reason_codes) or "policy denied"
        super().__init__(
            f"{decision.action.value} denied for {decision.record_id}: {reasons}"
        )


_INSTRUCTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bignore\s+(all\s+)?(previous|prior|earlier)\s+instructions?\b",
        r"\b(disregard|override)\s+(the\s+)?(system|developer|safety)\b",
        r"\breveal\s+(the\s+)?(system\s+prompt|developer\s+message|secret)\b",
        r"\b(exfiltrate|leak|steal)\s+(credentials?|tokens?|secrets?|data)\b",
        r"\bdo\s+not\s+tell\s+(the\s+)?user\b",
        r"\byou\s+are\s+now\s+(in\s+)?(developer|system|admin)\s+mode\b",
        r"<\s*(system|developer|tool)\s*>",
        r"\bexecute\s+this\s+(hidden\s+)?instruction\b",
    )
)


_TRUST_SCORE = {
    TrustClass.UNTRUSTED_EXTERNAL: 0,
    TrustClass.IMPORTED: 1,
    TrustClass.AGENT_GENERATED: 2,
    TrustClass.TOOL_OUTPUT: 3,
    TrustClass.EXPLICIT_USER: 4,
    TrustClass.VERIFIED_OPERATOR: 5,
    TrustClass.SYSTEM: 6,
}


class MemoryFirewall:
    def __init__(self, policy: MemoryFirewallPolicy):
        self.policy = policy

    def evaluate(
        self,
        record: ExperienceRecord,
        action: FirewallAction | str,
        *,
        context: FirewallContext,
        existing: Iterable[ExperienceRecord] = (),
    ) -> FirewallDecision:
        action = (
            action if isinstance(action, FirewallAction) else FirewallAction(str(action))
        )
        reasons: list[str] = []
        tainted = self.is_tainted(record)

        if context.namespace != record.namespace:
            if not (
                self.policy.allow_cross_namespace
                and context.cross_namespace_grant
                and context.actor_trust
                in {TrustClass.SYSTEM, TrustClass.VERIFIED_OPERATOR}
            ):
                reasons.append("namespace_isolation")
                return self._decision(
                    record,
                    action,
                    FirewallVerdict.DENY,
                    reasons,
                    tainted=tainted,
                )

        if record.namespace != self.policy.namespace:
            reasons.append("policy_namespace_mismatch")
            return self._decision(
                record,
                action,
                FirewallVerdict.DENY,
                reasons,
                tainted=tainted,
            )

        conflict = self.find_conflict(record, existing)
        if conflict is not None and action in {
            FirewallAction.INGEST,
            FirewallAction.ACTIVATE,
            FirewallAction.SUPERSEDE,
        }:
            reasons.append("unresolved_conflict")

        if action == FirewallAction.INGEST:
            if tainted:
                reasons.append("tainted_content")
            if record.trust == TrustClass.UNTRUSTED_EXTERNAL:
                reasons.append("untrusted_external")
            if record.status == ExperienceStatus.ACTIVE and record.trust not in {
                TrustClass.SYSTEM,
                TrustClass.EXPLICIT_USER,
                TrustClass.VERIFIED_OPERATOR,
            }:
                reasons.append("unvalidated_active_ingest")
            if reasons:
                return self._decision(
                    record,
                    action,
                    FirewallVerdict.QUARANTINE,
                    reasons,
                    tainted=tainted,
                    recommended_status=ExperienceStatus.QUARANTINED,
                )
            return self._decision(
                record,
                action,
                FirewallVerdict.ALLOW,
                (),
                tainted=False,
                recommended_status=(
                    ExperienceStatus.ACTIVE
                    if record.status == ExperienceStatus.ACTIVE
                    else ExperienceStatus.SHADOW
                ),
            )

        if action == FirewallAction.ACTIVATE:
            if tainted:
                reasons.append("tainted_content")
            if record.trust == TrustClass.UNTRUSTED_EXTERNAL:
                reasons.append("untrusted_external")
            if record.trust in {
                TrustClass.IMPORTED,
                TrustClass.AGENT_GENERATED,
                TrustClass.TOOL_OUTPUT,
            } and not context.validated_candidate:
                reasons.append("candidate_validation_required")
            if conflict is not None:
                reasons.append("conflict_review_required")
            if reasons:
                return self._decision(
                    record,
                    action,
                    FirewallVerdict.QUARANTINE,
                    reasons,
                    tainted=tainted,
                    recommended_status=ExperienceStatus.QUARANTINED,
                )
            return self._decision(
                record,
                action,
                FirewallVerdict.ALLOW,
                (),
                tainted=False,
                recommended_status=ExperienceStatus.ACTIVE,
            )

        if action == FirewallAction.RETRIEVE:
            if tainted:
                reasons.append("tainted_content")
            if record.status == ExperienceStatus.CANARY:
                if not (
                    self.policy.allow_canary_retrieval
                    and context.canary
                    and context.validated_candidate
                ):
                    reasons.append("canary_not_authorized")
            elif record.status != ExperienceStatus.ACTIVE:
                reasons.append("inactive_memory")
            if record.trust == TrustClass.UNTRUSTED_EXTERNAL:
                reasons.append("untrusted_external")
            if reasons:
                return self._decision(
                    record,
                    action,
                    FirewallVerdict.DENY,
                    reasons,
                    tainted=tainted,
                )
            return self._decision(
                record, action, FirewallVerdict.ALLOW, (), tainted=False
            )

        if action in {FirewallAction.DELETE, FirewallAction.SUPERSEDE}:
            protected = self.is_protected(record)
            needs_consent = (
                protected
                or (
                    self.policy.require_consent_for_user_data
                    and record.trust == TrustClass.EXPLICIT_USER
                )
            )
            if needs_consent and not self._valid_privileged_consent(context):
                reasons.append(
                    "protected_memory"
                    if protected
                    else "explicit_user_consent_required"
                )
                return self._decision(
                    record,
                    action,
                    FirewallVerdict.REQUIRE_CONSENT,
                    reasons,
                    tainted=tainted,
                )
            if (
                _TRUST_SCORE[context.actor_trust] < _TRUST_SCORE[record.trust]
                and not context.operator_override
            ):
                reasons.append("actor_trust_too_low")
                return self._decision(
                    record,
                    action,
                    FirewallVerdict.DENY,
                    reasons,
                    tainted=tainted,
                )
            return self._decision(
                record, action, FirewallVerdict.ALLOW, (), tainted=tainted
            )

        if action == FirewallAction.EXPORT:
            sensitive = self.is_sensitive(record)
            if sensitive and not self._valid_privileged_consent(context):
                reasons.append("sensitive_export_requires_consent")
                return self._decision(
                    record,
                    action,
                    FirewallVerdict.REQUIRE_CONSENT,
                    reasons,
                    tainted=tainted,
                )
            if tainted:
                reasons.append("tainted_export")
                return self._decision(
                    record,
                    action,
                    FirewallVerdict.DENY,
                    reasons,
                    tainted=True,
                )
            return self._decision(
                record, action, FirewallVerdict.ALLOW, (), tainted=False
            )

        return self._decision(
            record,
            action,
            FirewallVerdict.DENY,
            ("unsupported_action",),
            tainted=tainted,
        )

    def enforce(
        self,
        record: ExperienceRecord,
        action: FirewallAction | str,
        *,
        context: FirewallContext,
        existing: Iterable[ExperienceRecord] = (),
    ) -> FirewallDecision:
        decision = self.evaluate(
            record,
            action,
            context=context,
            existing=existing,
        )
        if not decision.allowed:
            raise MemoryFirewallDenied(decision)
        return decision

    def is_tainted(self, record: ExperienceRecord) -> bool:
        if record.metadata.get("tainted") is True:
            return True
        if record.source.metadata.get("tainted") is True:
            return True
        if record.source.metadata.get("untrusted_input") is True:
            return True
        return any(pattern.search(record.content) for pattern in _INSTRUCTION_PATTERNS)

    def is_protected(self, record: ExperienceRecord) -> bool:
        return (
            record.id in self.policy.protected_ids
            or record.kind in self.policy.protected_kinds
            or record.trust in {TrustClass.SYSTEM, TrustClass.VERIFIED_OPERATOR}
            or record.metadata.get("protected") is True
        )

    def is_sensitive(self, record: ExperienceRecord) -> bool:
        return any(
            key in record.metadata and bool(record.metadata[key])
            for key in self.policy.sensitive_metadata_keys
        )

    def find_conflict(
        self,
        record: ExperienceRecord,
        existing: Iterable[ExperienceRecord],
    ) -> ExperienceRecord | None:
        subject = str(record.metadata.get("subject") or "").strip().lower()
        if not subject:
            return None
        for candidate in existing:
            candidate_subject = str(
                candidate.metadata.get("subject") or ""
            ).strip().lower()
            if (
                candidate.id != record.id
                and candidate.namespace == record.namespace
                and candidate.status == ExperienceStatus.ACTIVE
                and candidate_subject == subject
                and candidate.content_sha256 != record.content_sha256
                and record.supersedes_id != candidate.id
                and record.kind != ExperienceKind.CORRECTION
            ):
                return candidate
        return None

    def _valid_privileged_consent(self, context: FirewallContext) -> bool:
        return (
            context.operator_override
            and context.actor_trust
            in {TrustClass.SYSTEM, TrustClass.VERIFIED_OPERATOR}
            and bool(context.consent_token and context.consent_token.strip())
        )

    def _decision(
        self,
        record: ExperienceRecord,
        action: FirewallAction,
        verdict: FirewallVerdict,
        reason_codes: Iterable[str],
        *,
        tainted: bool,
        recommended_status: ExperienceStatus | None = None,
    ) -> FirewallDecision:
        return FirewallDecision(
            action=action,
            verdict=verdict,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            policy_id=self.policy.policy_id,
            policy_version=self.policy.version,
            record_id=record.id,
            namespace=record.namespace,
            tainted=tainted,
            recommended_status=recommended_status,
        )
