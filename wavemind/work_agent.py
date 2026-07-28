from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Protocol, Sequence

from .experience import (
    ExperienceApplicability,
    ExperienceKind,
    ExperienceOutcome,
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    TrajectoryProvenance,
    TrustClass,
    parse_tool_trajectory,
)
from .experience_compiler import ExperienceCompiler, ExperiencePacket
from .memory_firewall import FirewallContext


@dataclass(frozen=True)
class WorkRequest:
    id: str
    objective: str
    namespace: str
    domain: str
    task_type: str
    fallback_plan: tuple[str, ...]
    demonstration_plan: tuple[str, ...] = ()
    token_budget: int = 400

    def __post_init__(self) -> None:
        for label in ("id", "objective", "namespace", "domain", "task_type"):
            if not str(getattr(self, label)).strip():
                raise ValueError(f"{label} must not be empty")
        if not self.fallback_plan:
            raise ValueError("fallback_plan must not be empty")
        if self.token_budget < 32:
            raise ValueError("token_budget must be at least 32")


@dataclass(frozen=True)
class ToolExecution:
    name: str
    success: bool
    output: dict[str, Any]
    error_code: str | None
    duration_ms: float


class WorkRuntime(Protocol):
    @property
    def available_tools(self) -> Sequence[str]: ...

    def call(self, name: str) -> ToolExecution: ...

    def verify(self) -> bool: ...


@dataclass(frozen=True)
class WorkAgentRun:
    request_id: str
    run_id: str
    success: bool
    plan_source: str
    plan: tuple[str, ...]
    executions: tuple[ToolExecution, ...]
    packet: dict[str, Any] | None
    selected_experience_id: str | None
    trajectory_id: str
    learned_experience_id: str | None
    repeated_error_codes: tuple[str, ...]
    context_tokens: int
    latency_ms: float

    @property
    def tool_steps(self) -> int:
        return len(self.executions)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["executions"] = [asdict(item) for item in self.executions]
        payload["tool_steps"] = self.tool_steps
        return payload


class ExperiencedWorkAgent:
    """Local work-agent loop that learns guarded tool plans from completed runs."""

    def __init__(self, compiler: ExperienceCompiler):
        self.compiler = compiler

    def run(
        self,
        request: WorkRequest,
        runtime: WorkRuntime,
        *,
        learn: bool = True,
        known_error_codes: Sequence[str] = (),
    ) -> WorkAgentRun:
        started = time.perf_counter()
        run_id = f"work_{uuid.uuid4().hex}"
        packet: ExperiencePacket | None = None
        selected_experience_id: str | None = None
        if request.demonstration_plan:
            plan = request.demonstration_plan
            plan_source = "demonstration"
        else:
            packet = self.compiler.compile_packet(
                request.objective,
                namespace=request.namespace,
                context=FirewallContext(
                    namespace=request.namespace,
                    actor="experienced_work_agent",
                ),
                token_budget=request.token_budget,
                top_k=1,
                domains=(request.domain,),
                task_types=(request.task_type,),
                tools=tuple(runtime.available_tools),
                reference_only=True,
            )
            selected = self._plan_from_packet(packet, request, runtime)
            if selected is None:
                plan = request.fallback_plan
                plan_source = "fallback"
            else:
                plan, selected_experience_id = selected
                plan_source = "experience"
        _validate_plan(plan, runtime.available_tools)

        executions = tuple(runtime.call(name) for name in plan)
        success = bool(runtime.verify())
        trajectory = _trajectory_from_run(
            request=request,
            run_id=run_id,
            plan_source=plan_source,
            executions=executions,
            success=success,
        )
        ingest = self.compiler.store.ingest_trajectory(
            trajectory,
            trust=TrustClass.TOOL_OUTPUT,
            status=ExperienceStatus.SHADOW,
            confidence=1.0,
        )
        learned_experience_id = None
        if learn:
            learned_experience_id = self._learn(
                request=request,
                plan=plan,
                trajectory_id=ingest.trajectory_id,
                trajectory_sha=ingest.source_sha256,
                trajectory_step_ids=tuple(
                    step.id for step in trajectory.steps
                ),
                success=success,
                executions=executions,
                evidence_id=run_id,
            )
        observed_errors = {
            item.error_code for item in executions if item.error_code is not None
        }
        repeated = tuple(sorted(observed_errors & set(known_error_codes)))
        latency_ms = (time.perf_counter() - started) * 1000.0
        return WorkAgentRun(
            request_id=request.id,
            run_id=run_id,
            success=success,
            plan_source=plan_source,
            plan=tuple(plan),
            executions=executions,
            packet=packet.as_dict() if packet else None,
            selected_experience_id=selected_experience_id,
            trajectory_id=trajectory.id,
            learned_experience_id=learned_experience_id,
            repeated_error_codes=repeated,
            context_tokens=packet.estimated_tokens if packet else 0,
            latency_ms=latency_ms,
        )

    def _plan_from_packet(
        self,
        packet: ExperiencePacket,
        request: WorkRequest,
        runtime: WorkRuntime,
    ) -> tuple[tuple[str, ...], str] | None:
        for item in packet.items:
            details = self.compiler.expand(
                [item.experience_id],
                namespace=request.namespace,
                context=FirewallContext(
                    namespace=request.namespace,
                    actor="experienced_work_agent",
                ),
            )
            if not details:
                continue
            raw_plan = details[0].metadata.get("tool_plan")
            if not isinstance(raw_plan, list) or not raw_plan:
                continue
            plan = tuple(str(name) for name in raw_plan)
            try:
                _validate_plan(plan, runtime.available_tools)
            except ValueError:
                continue
            return plan, item.experience_id
        return None

    def _learn(
        self,
        *,
        request: WorkRequest,
        plan: Sequence[str],
        trajectory_id: str,
        trajectory_sha: str,
        trajectory_step_ids: tuple[str, ...],
        success: bool,
        executions: Sequence[ToolExecution],
        evidence_id: str,
    ) -> str | None:
        if not success:
            error_codes = tuple(
                sorted(
                    {
                        item.error_code
                        for item in executions
                        if item.error_code is not None
                    }
                )
            )
            record = ExperienceRecord.create(
                id=f"exp_failure_{hashlib.sha256(evidence_id.encode()).hexdigest()[:24]}",
                kind=ExperienceKind.FAILURE,
                title=f"{request.task_type} failed attempt",
                content=(
                    f"Plan {' -> '.join(plan)} failed"
                    + (f" with {', '.join(error_codes)}." if error_codes else ".")
                ),
                namespace=request.namespace,
                applicability=ExperienceApplicability(
                    domains=(request.domain,),
                    task_types=(request.task_type,),
                    tools=tuple(plan),
                ),
                outcome=ExperienceOutcome(
                    success=False,
                    score=0.0,
                    summary="The work runtime verifier rejected the completed run.",
                ),
                trust=TrustClass.TOOL_OUTPUT,
                status=ExperienceStatus.SHADOW,
                source=ExperienceSource(
                    provider="wavemind_work_agent",
                    source_type="verified_trajectory",
                    source_id=trajectory_id,
                ),
                trajectory=TrajectoryProvenance(
                    trajectory_id=trajectory_id,
                    step_ids=trajectory_step_ids,
                    source_sha256=trajectory_sha,
                    raw_event_count=len(trajectory_step_ids),
                ),
                metadata={
                    "tool_plan": list(plan),
                    "error_codes": list(error_codes),
                    "work_request_id": request.id,
                },
            )
            stored, _ = self.compiler.submit(
                record,
                context=FirewallContext(
                    namespace=request.namespace,
                    actor="experienced_work_agent",
                    actor_trust=TrustClass.TOOL_OUTPUT,
                ),
            )
            return stored.id

        candidate_id = _strategy_id(request, plan)
        candidate = self.compiler.store.get(candidate_id)
        if candidate is None:
            record = ExperienceRecord.create(
                id=candidate_id,
                kind=ExperienceKind.SUCCESSFUL_STRATEGY,
                title=f"Verified {request.task_type} strategy",
                content=(
                    f"For {request.task_type} work, use the verified tool sequence: "
                    f"{' -> '.join(plan)}."
                ),
                namespace=request.namespace,
                applicability=ExperienceApplicability(
                    domains=(request.domain,),
                    task_types=(request.task_type,),
                    tools=tuple(plan),
                ),
                outcome=ExperienceOutcome(
                    success=True,
                    score=1.0,
                    summary="The work runtime verifier accepted this plan.",
                ),
                confidence=0.8,
                trust=TrustClass.AGENT_GENERATED,
                status=ExperienceStatus.SHADOW,
                source=ExperienceSource(
                    provider="wavemind_work_agent",
                    source_type="repeated_verified_outcome",
                    source_id=trajectory_id,
                ),
                trajectory=TrajectoryProvenance(
                    trajectory_id=trajectory_id,
                    step_ids=trajectory_step_ids,
                    source_sha256=trajectory_sha,
                    raw_event_count=len(trajectory_step_ids),
                ),
                metadata={
                    "tool_plan": list(plan),
                    "work_request_id": request.id,
                },
            )
            candidate, _ = self.compiler.submit(
                record,
                context=FirewallContext(
                    namespace=request.namespace,
                    actor="experienced_work_agent",
                    actor_trust=TrustClass.TOOL_OUTPUT,
                ),
            )
        self.compiler.review_candidate(
            candidate.id,
            evidence_id=evidence_id,
            successful=True,
            score=1.0,
            context=FirewallContext(
                namespace=request.namespace,
                actor="experienced_work_agent",
                actor_trust=TrustClass.TOOL_OUTPUT,
            ),
            metadata={"trajectory_id": trajectory_id, "request_id": request.id},
        )
        return candidate.id


def _validate_plan(plan: Sequence[str], available_tools: Sequence[str]) -> None:
    if not plan:
        raise ValueError("work plan must not be empty")
    allowed = set(available_tools)
    invalid = [name for name in plan if name not in allowed]
    if invalid:
        raise ValueError(f"work plan uses unavailable tools: {', '.join(invalid)}")


def _strategy_id(request: WorkRequest, plan: Sequence[str]) -> str:
    payload = "\0".join(
        (request.namespace, request.domain, request.task_type, *plan)
    )
    return f"exp_strategy_{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


def _trajectory_from_run(
    *,
    request: WorkRequest,
    run_id: str,
    plan_source: str,
    executions: Sequence[ToolExecution],
    success: bool,
):
    steps: list[dict[str, Any]] = []
    for index, execution in enumerate(executions):
        call_id = f"{run_id}:call:{index}"
        steps.extend(
            [
                {
                    "id": call_id,
                    "kind": "tool_call",
                    "name": execution.name,
                    "input": {"request_id": request.id},
                },
                {
                    "id": f"{call_id}:result",
                    "kind": "tool_result",
                    "name": execution.name,
                    "output": {
                        **execution.output,
                        "error_code": execution.error_code,
                        "duration_ms": execution.duration_ms,
                    },
                    "success": execution.success,
                    "parent_id": call_id,
                },
            ]
        )
    return parse_tool_trajectory(
        {
            "id": run_id,
            "steps": steps,
            "metadata": {
                "work_request_id": request.id,
                "domain": request.domain,
                "task_type": request.task_type,
                "plan_source": plan_source,
                "verified_success": success,
            },
        },
        provider="wavemind",
        namespace=request.namespace,
        trajectory_id=run_id,
    )
