from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from wavemind.experience_runtime import (
    AgentExperienceRuntime,
    CapturedRun,
    ExperienceIntervention,
    OutcomeVerification,
    OutcomeVerifier,
    RunFinalization,
)


@dataclass
class ProviderExperienceRun:
    """Provider-neutral handle backed by the canonical runtime event contract."""

    provider: str
    captured: CapturedRun
    intervention: ExperienceIntervention

    @property
    def run_id(self) -> str:
        return self.captured.run_id

    @property
    def packet(self) -> dict[str, Any]:
        return self.intervention.as_dict()

    def tool_call(
        self,
        tool_name: str,
        input: Mapping[str, Any] | None = None,
    ) -> str:
        return self.captured.capture_tool_call(tool_name, input).id

    def tool_result(
        self,
        tool_name: str,
        *,
        success: bool,
        output: Any = None,
        call_id: str | None = None,
        duration_ms: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        return self.captured.capture_tool_result(
            tool_name,
            success=success,
            output=output,
            parent_event_id=call_id,
            duration_ms=duration_ms,
            metadata=metadata,
        ).id

    def error(
        self,
        error: Exception | str,
        *,
        error_code: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        return self.captured.capture_error(
            error,
            error_code=error_code,
            metadata=metadata,
        ).id

    def verify(self, verifier: OutcomeVerifier) -> OutcomeVerification:
        return self.captured.verify(verifier)

    def finish(self) -> RunFinalization:
        return self.captured.finish()


class AgentExperienceHooks:
    """Small adapter surface shared by provider SDK integrations."""

    def __init__(
        self,
        runtime: AgentExperienceRuntime,
        *,
        namespace: str,
        provider: str,
        token_budget: int = 400,
        top_k: int = 3,
    ) -> None:
        self.runtime = runtime
        self.namespace = str(namespace).strip()
        self.provider = str(provider).strip()
        self.token_budget = int(token_budget)
        self.top_k = int(top_k)
        if not self.namespace:
            raise ValueError("namespace must not be empty")
        if not self.provider:
            raise ValueError("provider must not be empty")

    def begin(
        self,
        query: str,
        *,
        objective: str,
        domain: str,
        task_type: str,
        tools: Sequence[str] = (),
        session_id: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        canary: bool = False,
    ) -> ProviderExperienceRun:
        intervention = self.runtime.decide(
            query,
            namespace=self.namespace,
            run_id=run_id,
            task_id=task_id,
            domains=(domain,),
            task_types=(task_type,),
            tools=tools,
            token_budget=self.token_budget,
            top_k=self.top_k,
            canary=canary,
        )
        applied = (
            tuple(item.experience_id for item in intervention.packet.items)
            if intervention.inject and intervention.packet is not None
            else ()
        )
        captured = self.runtime.begin_run(
            namespace=self.namespace,
            objective=objective,
            domain=domain,
            task_type=task_type,
            session_id=session_id,
            run_id=run_id,
            task_id=task_id,
            metadata={"provider": self.provider, **dict(metadata or {})},
            applied_experience_ids=applied,
        )
        return ProviderExperienceRun(
            provider=self.provider,
            captured=captured,
            intervention=intervention,
        )

    def inspect(self, *, limit: int = 100) -> dict[str, Any]:
        return self.runtime.snapshot(namespace=self.namespace, limit=limit)

    def approve(self, experience_id: str, *, evidence_id: str, score: float = 1.0) -> str:
        return self.runtime.approve(
            experience_id,
            namespace=self.namespace,
            evidence_id=evidence_id,
            score=score,
        )

    def reject(self, experience_id: str, *, reason: str) -> dict[str, Any]:
        return self.runtime.reject(
            experience_id,
            namespace=self.namespace,
            reason=reason,
        ).as_dict()

    def rollback(self, experience_id: str, *, reason: str) -> dict[str, Any]:
        return self.runtime.rollback(
            experience_id,
            namespace=self.namespace,
            reason=reason,
        ).as_dict()
