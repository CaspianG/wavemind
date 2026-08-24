from __future__ import annotations

import hashlib

import pytest

from wavemind.scientific_memory import (
    MemoryDefinition,
    MemoryKind,
    ValidityInterval,
    VerificationDecision,
    VerifierKind,
    VerifierResult,
)
from wavemind.scientific_runtime import (
    ScientificCandidateMode,
    ScientificMemoryRuntime,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _definition(memory_id: str) -> MemoryDefinition:
    return MemoryDefinition(
        memory_id=memory_id,
        kind=MemoryKind.PROCEDURE,
        content="deploy service with verified rollback procedure",
        applicability={"domain": "operations"},
        validity=ValidityInterval(valid_from=0.0, valid_until=100.0),
        provenance=("training://operations",),
        estimated_tokens=8,
        estimated_latency_ms=1.0,
        safety_risk=0.05,
    )


def _verifier(index: int, treatment: float, control: float) -> VerifierResult:
    return VerifierResult(
        verifier_kind=VerifierKind.ENVIRONMENT,
        verifier_id="deterministic-environment",
        verifier_run_id=f"run-{index}",
        decision=VerificationDecision.VERIFIED,
        treatment_outcome=treatment,
        control_outcome=control,
        evidence_uri=f"artifact://runtime/{index}",
        evidence_sha256=_sha(f"evidence-{index}"),
    )


def _promote(runtime: ScientificMemoryRuntime, memory_id: str) -> None:
    for index in range(4):
        recall = runtime.shadow_recall(
            "deploy service rollback",
            context={"domain": "operations"},
            moment=10.0,
            token_budget=20,
            latency_budget_ms=5.0,
            max_safety_risk=0.1,
        )
        runtime.record_verified_influence(
            recall,
            receipt_id=f"receipt-{index}",
            task_id=f"task-{index}",
            case_id=f"case-{index}",
            action={"tool": "deploy"},
            verifier_result=_verifier(index, 1.0, 0.0),
            safe_for_randomization=True,
        )


def test_runtime_abstains_before_proof_then_recalls_promoted_memory(tmp_path):
    with ScientificMemoryRuntime(
        tmp_path / "scientific.sqlite3",
        mode=ScientificCandidateMode.CAUSAL,
        bootstrap_repeats=200,
    ) as runtime:
        runtime.register_memory(_definition("procedure:deploy"))
        substrate_result = runtime.retriever.query(
            "deploy service rollback",
            namespace="scientific",
            top_k=1,
        )[0]
        assert substrate_result.metadata["verified"] is False
        assert (
            substrate_result.metadata["verification_status"] == "candidate_unverified"
        )
        before = runtime.recall(
            "deploy service rollback",
            context={"domain": "operations"},
            moment=10.0,
            token_budget=20,
            latency_budget_ms=5.0,
            max_safety_risk=0.1,
        )
        assert before.abstained is True

        for index in range(4):
            recall = runtime.shadow_recall(
                "deploy service rollback",
                context={"domain": "operations"},
                moment=10.0,
                token_budget=20,
                latency_budget_ms=5.0,
                max_safety_risk=0.1,
            )
            runtime.record_verified_influence(
                recall,
                receipt_id=f"receipt-{index}",
                task_id=f"task-{index}",
                case_id=f"case-{index}",
                action={"tool": "deploy"},
                verifier_result=_verifier(index, 1.0, 0.0),
                safe_for_randomization=True,
            )
        after = runtime.recall(
            "deploy service rollback",
            context={"domain": "operations"},
            moment=10.0,
            token_budget=20,
            latency_budget_ms=5.0,
            max_safety_risk=0.1,
        )

        assert after.abstained is False
        assert after.selected_memory_ids == ("procedure:deploy",)
        assert runtime.event_log.memory_state("procedure:deploy").production_eligible
        assert runtime.event_log.validate_chain() == []


def test_runtime_graph_and_hybrid_use_proven_nodes_only(tmp_path):
    for mode in (ScientificCandidateMode.GRAPH, ScientificCandidateMode.HYBRID):
        with ScientificMemoryRuntime(
            tmp_path / f"{mode.value}.sqlite3",
            mode=mode,
            bootstrap_repeats=200,
        ) as runtime:
            runtime.register_memory(_definition("procedure:deploy"))
            _promote(runtime, "procedure:deploy")

            recalled = runtime.recall(
                "deploy service rollback",
                context={"domain": "operations"},
                moment=10.0,
                token_budget=20,
                latency_budget_ms=5.0,
                max_safety_risk=0.1,
            )

            assert recalled.selected_memory_ids == ("procedure:deploy",)


def test_runtime_rejects_receipt_for_abstention(tmp_path):
    with ScientificMemoryRuntime(
        tmp_path / "abstain.sqlite3",
        mode=ScientificCandidateMode.CAUSAL,
        bootstrap_repeats=200,
    ) as runtime:
        runtime.register_memory(_definition("procedure:deploy"))
        recall = runtime.recall(
            "deploy service rollback",
            context={"domain": "operations"},
            moment=10.0,
            token_budget=20,
            latency_budget_ms=5.0,
            max_safety_risk=0.1,
        )

        with pytest.raises(ValueError, match="abstained"):
            runtime.record_verified_influence(
                recall,
                receipt_id="invalid",
                task_id="task",
                case_id="case",
                action={"tool": "deploy"},
                verifier_result=_verifier(1, 1.0, 0.0),
                safe_for_randomization=False,
            )


def test_runtime_reopen_retains_proof_and_production_lifecycle(tmp_path):
    path = tmp_path / "persistent-runtime.sqlite3"
    with ScientificMemoryRuntime(
        path,
        mode=ScientificCandidateMode.CAUSAL,
        bootstrap_repeats=200,
    ) as runtime:
        runtime.register_memory(_definition("procedure:deploy"))
        _promote(runtime, "procedure:deploy")
        assert runtime.event_log.memory_state("procedure:deploy").production_eligible

    with ScientificMemoryRuntime(
        path,
        mode=ScientificCandidateMode.CAUSAL,
        bootstrap_repeats=200,
    ) as reopened:
        recalled = reopened.recall(
            "deploy service rollback",
            context={"domain": "operations"},
            moment=10.0,
            token_budget=20,
            latency_budget_ms=5.0,
            max_safety_risk=0.1,
        )

        assert recalled.abstained is False
        assert recalled.selected_memory_ids == ("procedure:deploy",)
        assert len(reopened.event_log.receipts()) == 4
        assert reopened.event_log.validate_chain() == []


def test_v2_runtime_has_real_evaluation_intervention_but_abstains_in_production(
    tmp_path,
):
    with ScientificMemoryRuntime(
        tmp_path / "v2.sqlite3",
        mode=ScientificCandidateMode.STATE_RECONCILER,
    ) as runtime:
        runtime.register_memory(
            MemoryDefinition(
                memory_id="state:portland",
                kind=MemoryKind.STATE_TRANSITION,
                content="The user currently lives in Portland.",
                provenance=("source-order:7",),
                estimated_tokens=8,
                estimated_latency_ms=0.1,
                safety_risk=0.0,
            )
        )

        production = runtime.recall(
            "Where does the user currently live?",
            context={},
            moment=0.0,
            token_budget=20,
            latency_budget_ms=10.0,
            max_safety_risk=0.0,
        )
        evaluation = runtime.evaluation_recall(
            "Where does the user currently live?",
            context={},
            moment=0.0,
            token_budget=20,
            latency_budget_ms=10.0,
            max_safety_risk=0.0,
        )

        assert production.abstained is True
        assert evaluation.selected_memory_ids == ("state:portland",)
        assert evaluation.evaluation_only is True
        assert runtime.event_log.memory_state("state:portland").production_eligible is False
