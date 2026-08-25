from __future__ import annotations

import hashlib
import sqlite3

import pytest

from wavemind.scientific_memory import (
    CanaryArm,
    CausalUtilityController,
    EvidenceConstrainedAssociativeGraph,
    GraphEvidenceNode,
    MemoryDefinition,
    MemoryKind,
    MemoryLifecycle,
    ScientificEventLog,
    ValidityInterval,
    VerificationDecision,
    VerifierKind,
    VerifierResult,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _memory(memory_id: str = "procedure:1", **overrides: object) -> MemoryDefinition:
    values = {
        "memory_id": memory_id,
        "kind": MemoryKind.PROCEDURE,
        "content": "Run the repository test before changing the implementation.",
        "preconditions": ("repository-present",),
        "effects": ("test-evidence-recorded",),
        "applicability": {"repository": "wavemind"},
        "validity": ValidityInterval(valid_from=10.0, valid_until=100.0),
        "provenance": ("runbook://test-first",),
        "estimated_tokens": 12,
        "estimated_latency_ms": 2.0,
        "safety_risk": 0.05,
    }
    values.update(overrides)
    return MemoryDefinition(**values)


def _result(
    run: int,
    *,
    treatment: float,
    control: float,
    kind: VerifierKind = VerifierKind.TEST,
    decision: VerificationDecision = VerificationDecision.VERIFIED,
    false_promotion: bool = False,
) -> VerifierResult:
    return VerifierResult(
        verifier_kind=kind,
        verifier_id="pytest",
        verifier_run_id=f"run-{run}",
        decision=decision,
        treatment_outcome=treatment,
        control_outcome=control,
        evidence_uri=f"artifact://pytest/run-{run}",
        evidence_sha256=_sha(f"evidence-{run}"),
        false_verified_promotion=false_promotion,
    )


def _verified_pairs(
    log: ScientificEventLog,
    memory_id: str,
    effects: list[tuple[float, float]],
) -> None:
    for index, (treatment, control) in enumerate(effects, start=1):
        receipt_id = f"receipt-{memory_id}-{index}"
        log.record_influence(
            receipt_id=receipt_id,
            task_id=f"task-{index}",
            case_id=f"case-{index}",
            memory_attribution={memory_id: 1.0},
            context_sha256=_sha(f"context-{index}"),
            action_sha256=_sha(f"action-{index}"),
            safe_for_randomization=True,
            canary_arm=CanaryArm.MEMORY,
        )
        log.verify_influence(
            receipt_id,
            _result(index, treatment=treatment, control=control),
        )


def test_event_log_is_typed_hash_chained_and_rollback_is_auditable():
    log = ScientificEventLog()
    registered = log.register_memory(_memory())
    log.set_lifecycle(
        "procedure:1",
        MemoryLifecycle.PRODUCTION,
        reason="test promotion",
    )
    assert log.memory_state("procedure:1").production_eligible is True

    rollback = log.rollback_memory(
        "procedure:1",
        target_sequence=registered.sequence,
        reason="operator restored pre-promotion state",
    )

    assert log.memory_state("procedure:1").lifecycle is MemoryLifecycle.CANDIDATE
    assert rollback.payload["target_sequence"] == registered.sequence
    assert log.validate_chain() == []


def test_event_log_persists_receipts_lifecycle_and_rollback(tmp_path):
    path = tmp_path / "scientific-events.sqlite3"
    with ScientificEventLog(path) as log:
        registered = log.register_memory(_memory())
        _verified_pairs(log, "procedure:1", [(1.0, 0.0)] * 4)
        controller = CausalUtilityController(log, bootstrap_repeats=200)
        assert (
            controller.update_lifecycle("procedure:1").lifecycle
            is MemoryLifecycle.PRODUCTION
        )
        log.rollback_memory(
            "procedure:1",
            target_sequence=registered.sequence,
            reason="persistent rollback",
        )
        event_count = len(log.events)

    with ScientificEventLog(path) as reopened:
        assert len(reopened.events) == event_count
        assert reopened.validate_chain() == []
        assert len(reopened.receipts()) == 4
        assert (
            reopened.memory_state("procedure:1").lifecycle is MemoryLifecycle.CANDIDATE
        )


def test_event_log_fails_closed_on_persisted_tampering(tmp_path):
    path = tmp_path / "scientific-events.sqlite3"
    with ScientificEventLog(path) as log:
        log.register_memory(_memory())

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE scientific_memory_events SET event_json = ? WHERE sequence = 1",
            ('{"tampered":true}',),
        )

    with pytest.raises(ValueError, match="cannot be decoded"):
        ScientificEventLog(path)


def test_persistent_event_log_handles_interleaved_writers(tmp_path):
    path = tmp_path / "scientific-events.sqlite3"
    with ScientificEventLog(path) as first, ScientificEventLog(path) as second:
        first.register_memory(_memory("procedure:first"))
        second.register_memory(_memory("procedure:second"))

        assert set(first.definitions()) == {"procedure:first", "procedure:second"}
        assert set(second.definitions()) == {"procedure:first", "procedure:second"}
        assert first.validate_chain() == []
        assert second.validate_chain() == []


def test_atomic_memory_batch_persists_one_valid_ordered_chain(tmp_path):
    path = tmp_path / "scientific-events.sqlite3"
    with ScientificEventLog(path) as log:
        events = log.register_memories(
            [_memory(f"procedure:{index}") for index in range(100)]
        )

        assert len(events) == 100
        assert [event.sequence for event in events] == list(range(1, 101))
        assert len(log.definitions()) == 100
        assert log.validate_chain() == []

    with ScientificEventLog(path) as reopened:
        assert len(reopened.definitions()) == 100
        assert reopened.validate_chain() == []


def test_atomic_memory_batch_rolls_back_memory_and_disk_on_serialization_error(
    tmp_path,
):
    path = tmp_path / "scientific-events.sqlite3"
    invalid = _memory("procedure:invalid", provenance=(object(),))
    with ScientificEventLog(path) as log:
        log.register_memory(_memory("procedure:existing"))
        before = tuple(log.events)

        with pytest.raises(TypeError):
            log.register_memories([_memory("procedure:new"), invalid])

        assert log.events == before
        assert set(log.definitions()) == {"procedure:existing"}
        assert log.validate_chain() == []

    with ScientificEventLog(path) as reopened:
        assert set(reopened.definitions()) == {"procedure:existing"}
        assert reopened.validate_chain() == []


def test_atomic_batches_handle_interleaved_persistent_writers(tmp_path):
    path = tmp_path / "scientific-events.sqlite3"
    with ScientificEventLog(path) as first, ScientificEventLog(path) as second:
        first.register_memories([_memory("procedure:a"), _memory("procedure:b")])
        second.register_memories([_memory("procedure:c"), _memory("procedure:d")])

        expected = {"procedure:a", "procedure:b", "procedure:c", "procedure:d"}
        assert set(first.definitions()) == expected
        assert set(second.definitions()) == expected
        assert first.validate_chain() == []
        assert second.validate_chain() == []


def test_agent_self_assessment_never_carries_production_influence():
    log = ScientificEventLog()
    log.register_memory(_memory())
    receipt = log.record_influence(
        receipt_id="self-rated",
        task_id="task",
        case_id="case",
        memory_attribution={"procedure:1": 1.0},
        context_sha256=_sha("context"),
        action_sha256=_sha("action"),
        safe_for_randomization=False,
    )
    returned = log.verify_influence(
        receipt.receipt_id,
        _result(1, treatment=1.0, control=0.0, kind=VerifierKind.AGENT_SELF),
    )

    assert returned.verifier_result is None
    assert log.receipts()[receipt.receipt_id].carries_production_influence is False
    assert log.events[-1].event_type.value == "verification_rejected"


def test_unverified_or_unpaired_receipts_cannot_promote_memory():
    log = ScientificEventLog()
    log.register_memory(_memory())
    log.record_influence(
        receipt_id="pending",
        task_id="task",
        case_id="case",
        memory_attribution={"procedure:1": 1.0},
        context_sha256=_sha("context"),
        action_sha256=_sha("action"),
        safe_for_randomization=False,
    )
    controller = CausalUtilityController(log, bootstrap_repeats=200)

    estimate = controller.estimate("procedure:1")
    state = controller.update_lifecycle("procedure:1")

    assert estimate.verified_pair_count == 0
    assert estimate.ci_lower == -1.0
    assert state.lifecycle is MemoryLifecycle.CANDIDATE


def test_positive_paired_effect_promotes_only_when_lower_ci_is_positive():
    log = ScientificEventLog()
    log.register_memory(_memory())
    _verified_pairs(log, "procedure:1", [(1.0, 0.0)] * 6)
    controller = CausalUtilityController(
        log,
        bootstrap_repeats=300,
        minimum_verified_pairs=3,
    )

    estimate = controller.estimate("procedure:1")
    state = controller.update_lifecycle("procedure:1")

    assert estimate.ci_lower == pytest.approx(1.0)
    assert state.lifecycle is MemoryLifecycle.PRODUCTION


def test_negative_marginal_utility_revokes_instead_of_arbitrary_decay():
    log = ScientificEventLog()
    log.register_memory(_memory())
    _verified_pairs(log, "procedure:1", [(0.0, 1.0)] * 6)
    controller = CausalUtilityController(
        log,
        bootstrap_repeats=300,
        minimum_verified_pairs=3,
    )

    estimate = controller.estimate("procedure:1")
    state = controller.update_lifecycle("procedure:1")

    assert estimate.ci_upper == pytest.approx(-1.0)
    assert state.lifecycle is MemoryLifecycle.REVOKED
    assert "negative marginal utility" in str(state.reason)


def test_false_verified_promotion_blocks_production_promotion():
    log = ScientificEventLog()
    log.register_memory(_memory())
    _verified_pairs(log, "procedure:1", [(1.0, 0.0)] * 3)
    receipt_id = "false-promotion"
    log.record_influence(
        receipt_id=receipt_id,
        task_id="task-false",
        case_id="case-false",
        memory_attribution={"procedure:1": 1.0},
        context_sha256=_sha("context-false"),
        action_sha256=_sha("action-false"),
        safe_for_randomization=True,
    )
    log.verify_influence(
        receipt_id,
        _result(
            99,
            treatment=1.0,
            control=0.0,
            false_promotion=True,
        ),
    )
    controller = CausalUtilityController(log, bootstrap_repeats=200)

    estimate = controller.estimate("procedure:1")
    state = controller.update_lifecycle("procedure:1")

    assert estimate.false_verified_promotions == 1
    assert state.lifecycle is MemoryLifecycle.CANDIDATE


def test_selection_abstains_until_positive_utility_is_proven_and_respects_budgets():
    log = ScientificEventLog()
    log.register_memory(_memory("procedure:a", estimated_tokens=8))
    log.register_memory(_memory("procedure:b", estimated_tokens=20))
    controller = CausalUtilityController(log, bootstrap_repeats=200)

    before = controller.select_minimal_memories(
        ["procedure:a", "procedure:b"],
        context={"repository": "wavemind"},
        moment=50.0,
        token_budget=12,
        latency_budget_ms=5.0,
        max_safety_risk=0.10,
    )
    assert before.abstained is True

    _verified_pairs(log, "procedure:a", [(1.0, 0.0)] * 4)
    _verified_pairs(log, "procedure:b", [(1.0, 0.0)] * 4)
    controller.update_lifecycle("procedure:a")
    controller.update_lifecycle("procedure:b")
    after = controller.select_minimal_memories(
        ["procedure:a", "procedure:b"],
        context={"repository": "wavemind"},
        moment=50.0,
        token_budget=12,
        latency_budget_ms=5.0,
        max_safety_risk=0.10,
    )

    assert after.abstained is False
    assert after.selected_memory_ids == ("procedure:a",)
    assert after.total_tokens == 8


def test_selection_respects_applicability_validity_and_safety():
    log = ScientificEventLog()
    log.register_memory(_memory(safety_risk=0.7))
    _verified_pairs(log, "procedure:1", [(1.0, 0.0)] * 4)
    controller = CausalUtilityController(log, bootstrap_repeats=200)
    controller.update_lifecycle("procedure:1")

    wrong_context = controller.select_minimal_memories(
        ["procedure:1"],
        context={"repository": "other"},
        moment=50.0,
        token_budget=100,
        latency_budget_ms=10.0,
        max_safety_risk=1.0,
    )
    expired = controller.select_minimal_memories(
        ["procedure:1"],
        context={"repository": "wavemind"},
        moment=101.0,
        token_budget=100,
        latency_budget_ms=10.0,
        max_safety_risk=1.0,
    )
    unsafe = controller.select_minimal_memories(
        ["procedure:1"],
        context={"repository": "wavemind"},
        moment=50.0,
        token_budget=100,
        latency_budget_ms=10.0,
        max_safety_risk=0.1,
    )

    assert wrong_context.abstained and expired.abstained and unsafe.abstained


def test_randomized_canary_is_deterministic_and_safe_only():
    controller = CausalUtilityController(ScientificEventLog(), bootstrap_repeats=100)
    first = controller.assign_canary("case-7", safe_for_randomization=True, seed=42)
    second = controller.assign_canary("case-7", safe_for_randomization=True, seed=42)
    assert first is second
    with pytest.raises(ValueError, match="unsafe"):
        controller.assign_canary("case-8", safe_for_randomization=False, seed=42)


def test_evidence_constrained_graph_uses_frozen_energy_and_abstains_without_proof():
    graph = EvidenceConstrainedAssociativeGraph()
    proven = GraphEvidenceNode("a", 3, 0, 0.8, 0.2, 0.1, 8)
    contradicted = GraphEvidenceNode("b", 3, 1, 0.9, 0.3, 0.1, 8)
    unproven = GraphEvidenceNode("c", 0, 0, 1.0, 0.0, 1.0, 2)

    selected = graph.select(
        [proven, contradicted, unproven],
        token_budget=10,
        associations={("a", "b"): 1.0},
    )

    assert selected == ("a",)
    assert graph.select([unproven], token_budget=10) == ()
