"""Brain reported-state extraction must not alter the legacy runtime contract."""

import pytest

from wavemind.brain.experience_runtime_bridge import PrivateRuntime
from wavemind.experience_runtime import (
    AgentExperienceEvent,
    AgentExperienceRuntime,
    OutcomeVerification,
)


def reported_run(runtime, procedure=None):
    for sequence, (kind, payload) in enumerate(
        [
            (
                "task.started",
                {
                    "objective": "Orchard checked",
                    "domain": "brain",
                    "task_type": "reported procedure",
                    "declared_procedure": ["Check orchard"]
                    if procedure is None
                    else procedure,
                },
            ),
            ("run.finished", {}),
        ]
    ):
        runtime.capture(
            AgentExperienceEvent(
                id=f"event-{sequence}",
                namespace="brain:fixture",
                run_id="run-fixture",
                kind=kind,
                sequence=sequence,
                occurred_at=sequence + 1.0,
                payload=payload,
            )
        )
    return runtime.finalize_run(
        namespace="brain:fixture",
        run_id="run-fixture",
        verification=OutcomeVerification(
            evidence_id="evidence-fixture",
            source="operator",
            verifier="owner-fixture",
            success=True,
            score=1.0,
            reference="fixture-reference",
            verified_at=3.0,
        ),
    )


def test_legacy_runtime_does_not_derive_reported_procedure(tmp_path):
    private = PrivateRuntime(tmp_path)
    try:
        runtime = AgentExperienceRuntime(private.runtime("brain:fixture").compiler)
        assert reported_run(runtime).candidate_ids == ()
    finally:
        private.close()


def test_private_reported_candidate_retains_identity_and_evidence(tmp_path):
    private = PrivateRuntime(tmp_path)
    try:
        runtime = private.runtime("brain:fixture")
        result = reported_run(runtime)
        # Fixed canonical fingerprint preserves stored records and replay identity.
        assert result.candidate_ids == ("exp_runtime_f799372ae9bda237c838326c",)
        record = private.store.get(result.candidate_ids[0])
        assert record.title == "Procedure reported for a verified outcome"
        assert record.content == "Reported steps: Check orchard"
        assert record.applicability.as_dict() == {
            "domains": ["brain"],
            "task_types": ["reported procedure"],
            "tools": [],
            "conditions": {},
        }
        assert record.source.provider == "agent_experience_runtime"
        assert record.source.source_type == "independently_verified_run"
        assert record.source.source_id == result.trajectory_id
        assert record.source.metadata == {
            "verification_evidence_id": "evidence-fixture",
            "verification_reference": "fixture-reference",
        }
        assert record.metadata["reported_steps"] == ["Check orchard"]
        assert record.metadata["steps_observed"] is False
        assert record.metadata["verification_required"] is True
        assert record.metadata["objective"] == "Orchard checked"
        trajectory = private.store.get_trajectory(result.trajectory_id)
        assert record.trajectory.trajectory_id == result.trajectory_id
        assert record.trajectory.source_sha256 == trajectory.source_sha256
        assert record.trajectory.raw_event_count == 2
        assert {step.kind.value for step in trajectory.steps} == {"state"}
        assert reported_run(runtime).candidate_ids == result.candidate_ids
    finally:
        private.close()


@pytest.mark.parametrize("procedure", [[], [""], [" "], [1], "Check orchard"])
def test_private_runtime_rejects_malformed_reported_steps(tmp_path, procedure):
    private = PrivateRuntime(tmp_path)
    try:
        assert (
            reported_run(private.runtime("brain:fixture"), procedure).candidate_ids
            == ()
        )
    finally:
        private.close()
