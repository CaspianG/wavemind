from __future__ import annotations

import json
from pathlib import Path

import pytest

from wavemind.experience import ExperienceStatus, SQLiteExperienceStore
from wavemind.experience_compiler import ExperienceCompiler, ExperienceCompilerPolicy
from wavemind.experience_runtime import (
    AgentEventKind,
    AgentExperienceEvent,
    AgentExperienceRuntime,
    AgentExperienceRuntimePolicy,
    CallableOutcomeVerifier,
    OutcomeVerification,
    VerificationSource,
)
from wavemind.memory_firewall import MemoryFirewall, MemoryFirewallPolicy


def _runtime(tmp_path: Path, *, namespace: str = "tenant-a") -> AgentExperienceRuntime:
    store = SQLiteExperienceStore(tmp_path / "experience.sqlite3")
    compiler = ExperienceCompiler(
        store,
        MemoryFirewall(
            MemoryFirewallPolicy(
                namespace=namespace,
                allow_canary_retrieval=True,
                require_consent_for_user_data=False,
            )
        ),
        policy=ExperienceCompilerPolicy(
            shadow_validation_count=2,
            activation_validation_count=3,
            rejection_failure_count=2,
        ),
    )
    return AgentExperienceRuntime(
        compiler,
        policy=AgentExperienceRuntimePolicy(intervention_score_threshold=0.0),
    )


def _verified_run(
    runtime: AgentExperienceRuntime,
    *,
    suffix: str,
    success: bool = True,
    applied_experience_ids: tuple[str, ...] = (),
):
    run = runtime.begin_run(
        namespace="tenant-a",
        objective="deploy the service safely",
        domain="operations",
        task_type="deploy",
        run_id=f"run-{suffix}",
        session_id=f"session-{suffix}",
        task_id=f"task-{suffix}",
        applied_experience_ids=applied_experience_ids,
    )
    run.execute_tool("validate", lambda: {"checks": "pass"})
    run.execute_tool("deploy", lambda: {"revision": suffix})
    run.verify(
        CallableOutcomeVerifier(
            source=VerificationSource.ENVIRONMENT,
            verifier="deployment-health-check",
            callback=lambda _context: (success, 1.0 if success else 0.0),
            reference=f"health://deployment/{suffix}",
        )
    )
    return run.finish()


def test_runtime_redacts_secrets_limits_payload_and_is_idempotent(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    event = AgentExperienceEvent(
        id="evt-1",
        namespace="tenant-a",
        run_id="run-1",
        kind=AgentEventKind.TOOL_CALL,
        sequence=0,
        occurred_at=1.0,
        tool_name="request",
        payload={
            "api_key": "sk-this-must-never-persist",
            "header": "Bearer abc.def.ghi",
            "message": "password=hunter2",
        },
    )

    first = runtime.capture(event)
    second = runtime.capture(event)
    stored = runtime.events(namespace="tenant-a", run_id="run-1")

    assert first.inserted is True
    assert second.inserted is False
    assert len(stored) == 1
    serialized = json.dumps(stored[0].payload)
    assert "hunter2" not in serialized
    assert "abc.def.ghi" not in serialized
    assert "sk-this" not in serialized
    assert serialized.count("[REDACTED]") == 3
    assert runtime.events(namespace="tenant-b", run_id="run-1") == ()


def test_runtime_rejects_same_event_id_with_different_data(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    base = dict(
        id="evt-1",
        namespace="tenant-a",
        run_id="run-1",
        kind=AgentEventKind.ERROR,
        sequence=0,
        occurred_at=1.0,
    )
    runtime.capture(AgentExperienceEvent(**base, payload={"message": "first"}))

    with pytest.raises(ValueError, match="different data"):
        runtime.capture(AgentExperienceEvent(**base, payload={"message": "second"}))


def test_unverified_run_stays_shadow(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    run = runtime.begin_run(
        namespace="tenant-a",
        objective="deploy the service safely",
        domain="operations",
        task_type="deploy",
    )
    run.execute_tool("validate", lambda: {"ok": True})
    result = run.finish()

    assert result.verified is False
    assert len(result.candidate_ids) == 1
    record = runtime.store.get(result.candidate_ids[0])
    assert record is not None
    assert record.status == ExperienceStatus.SHADOW
    assert runtime.store.candidate_validation_summary(record.id).validation_count == 0


def test_three_independent_verified_runs_promote_shadow_canary_active(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    first = _verified_run(runtime, suffix="one")
    second = _verified_run(runtime, suffix="two")
    third = _verified_run(runtime, suffix="three")

    candidate_id = first.candidate_ids[0]
    assert second.candidate_ids[0] == candidate_id
    assert third.candidate_ids[0] == candidate_id
    assert first.candidate_statuses[candidate_id] == "shadow"
    assert second.candidate_statuses[candidate_id] == "canary"
    assert third.candidate_statuses[candidate_id] == "active"
    summary = runtime.store.candidate_validation_summary(candidate_id)
    assert summary.validation_count == 3
    assert summary.successful_count == 3
    assert len(set(summary.evidence_ids)) == 3

    event_kinds = {
        event.kind
        for event in runtime.events(namespace="tenant-a", run_id="run-three")
    }
    assert {
        AgentEventKind.SESSION_STARTED,
        AgentEventKind.RUN_STARTED,
        AgentEventKind.TASK_STARTED,
        AgentEventKind.TOOL_CALL,
        AgentEventKind.TOOL_RESULT,
        AgentEventKind.OUTCOME,
        AgentEventKind.TASK_FINISHED,
        AgentEventKind.RUN_FINISHED,
        AgentEventKind.SESSION_FINISHED,
    } <= event_kinds


def test_selective_intervention_is_silent_until_experience_is_active(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    cold = runtime.decide(
        "deploy service",
        namespace="tenant-a",
        domains=("operations",),
        task_types=("deploy",),
        tools=("validate", "deploy"),
    )
    assert cold.inject is False
    assert cold.reason == "no_applicable_verified_experience"

    result = None
    for suffix in ("one", "two", "three"):
        result = _verified_run(runtime, suffix=suffix)
    assert result is not None

    warm = runtime.decide(
        "deploy the service safely",
        namespace="tenant-a",
        run_id="consumer-run",
        task_id="consumer-task",
        domains=("operations",),
        task_types=("deploy",),
        tools=("validate", "deploy"),
        token_budget=160,
        top_k=1,
    )

    assert warm.inject is True
    assert warm.reason == "applicable_verified_experience"
    assert warm.packet is not None
    assert warm.packet.estimated_tokens <= 160
    assert warm.packet.items[0].citation.startswith("experience:")
    assert warm.source_tool_result_refs
    assert all("#step:" in ref for ref in warm.source_tool_result_refs)
    decisions = runtime.injection_decisions(namespace="tenant-a")
    assert {row["inject"] for row in decisions} == {False, True}


def test_repeated_independently_verified_failure_rejects_applied_experience(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    result = None
    for suffix in ("one", "two", "three"):
        result = _verified_run(runtime, suffix=suffix)
    assert result is not None
    candidate_id = result.candidate_ids[0]
    assert runtime.store.get(candidate_id).status == ExperienceStatus.ACTIVE

    _verified_run(
        runtime,
        suffix="failure-one",
        success=False,
        applied_experience_ids=(candidate_id,),
    )
    assert runtime.store.get(candidate_id).status == ExperienceStatus.ACTIVE
    _verified_run(
        runtime,
        suffix="failure-two",
        success=False,
        applied_experience_ids=(candidate_id,),
    )
    assert runtime.store.get(candidate_id).status == ExperienceStatus.REJECTED


def test_llm_self_assessment_cannot_be_used_as_verification() -> None:
    with pytest.raises(ValueError, match="self-assessment"):
        OutcomeVerification(
            evidence_id="self-claim",
            source=VerificationSource.TOOL,
            verifier="agent-output",
            success=True,
            metadata={"llm_self_assessed": True},
        )


def test_run_context_captures_tool_error_and_finishes_without_learning_active(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)

    with pytest.raises(RuntimeError, match="boom"):
        with runtime.run(
            namespace="tenant-a",
            objective="run risky tool",
            domain="operations",
            task_type="repair",
            run_id="run-error",
        ) as run:
            run.execute_tool("repair", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    events = runtime.events(namespace="tenant-a", run_id="run-error")
    assert any(event.kind == AgentEventKind.ERROR for event in events)
    assert events[-1].kind == AgentEventKind.SESSION_FINISHED
    records = runtime.store.list(namespace="tenant-a", limit=100)
    learned = [record for record in records if record.kind.value == "failure"]
    assert learned
    assert all(record.status == ExperienceStatus.SHADOW for record in learned)
