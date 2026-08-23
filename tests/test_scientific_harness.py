from __future__ import annotations

import hashlib

import pytest

from wavemind.scientific_harness import (
    ArmResponse,
    ScientificCase,
    VerifiedArmOutcome,
    run_equal_protocol_case,
)
from wavemind.scientific_protocol import REQUIRED_BASELINES


CANDIDATE = "causal-utility-controller-v1"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_harness_runs_exact_arms_on_identical_input_and_trusts_verifier_only():
    observed: list[tuple[str, dict[str, object]]] = []

    def runner(arm_id: str):
        def execute(payload):
            observed.append((arm_id, dict(payload)))
            payload["local_mutation"] = arm_id
            return ArmResponse(
                action={"answer": arm_id},
                context_tokens=25 if arm_id == CANDIDATE else 50,
                receipt_digest=_sha("receipt") if arm_id == CANDIDATE else None,
            )

        return execute

    arms = {
        arm_id: runner(arm_id) for arm_id in REQUIRED_BASELINES | {CANDIDATE}
    }

    def verifier(case, arm_id, response):
        return VerifiedArmOutcome(
            verifier_source="environment",
            verifier_id="deterministic-state-machine",
            task_success=1.0 if arm_id == CANDIDATE else 0.0,
            repeated_errors=0 if arm_id == CANDIDATE else 1,
            stale_or_contradiction_errors=0,
            evidence_digest=_sha(f"{case.case_id}:{arm_id}:{response.action}"),
        )

    case = ScientificCase("memops", "case-1", "update", {"value": 7}, 100)
    row = run_equal_protocol_case(
        case,
        candidate_id=CANDIDATE,
        arms=arms,
        verifier=verifier,
        seed=17,
    )

    assert len(observed) == len(REQUIRED_BASELINES) + 1
    assert all(payload == {"value": 7} for _, payload in observed)
    assert row["arms"][CANDIDATE]["task_success"] == 1.0
    assert row["verification"]["source"] == "environment"
    assert row["verification"]["receipt_digest"] == _sha("receipt")
    assert row["case_input_sha256"] == _sha('{"value":7}')


def test_harness_rejects_agent_self_scoring():
    arms = {
        arm_id: (
            lambda payload, arm_id=arm_id: ArmResponse(
                action={"arm": arm_id},
                context_tokens=1,
                receipt_digest=_sha("receipt") if arm_id == CANDIDATE else None,
            )
        )
        for arm_id in REQUIRED_BASELINES | {CANDIDATE}
    }

    def verifier(case, arm_id, response):
        return VerifiedArmOutcome(
            verifier_source="agent_self",
            verifier_id="agent",
            task_success=1.0,
            repeated_errors=0,
            stale_or_contradiction_errors=0,
            evidence_digest=_sha("self-score"),
        )

    with pytest.raises(ValueError, match="independent verifier"):
        run_equal_protocol_case(
            ScientificCase("memops", "case", "update", {"x": 1}, 10),
            candidate_id=CANDIDATE,
            arms=arms,
            verifier=verifier,
            seed=1,
        )


def test_harness_rejects_missing_real_baseline_arm():
    arms = {baseline: (lambda payload: None) for baseline in REQUIRED_BASELINES}
    arms.pop("mem0-oss")

    with pytest.raises(ValueError, match="exact frozen arm set"):
        run_equal_protocol_case(
            ScientificCase("memops", "case", "update", {"x": 1}, 10),
            candidate_id=CANDIDATE,
            arms=arms,
            verifier=lambda case, arm, response: None,
            seed=1,
        )
