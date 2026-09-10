"""The private existing runtime adapter; no default database or remote calls."""

from pathlib import Path

from ..experience import (
    SQLiteExperienceStore,
    ExperienceApplicability,
    ExperienceKind,
    ExperienceOutcome,
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    TrajectoryProvenance,
    TrustClass,
)
from ..experience_compiler import ExperienceCompiler
from ..experience_runtime import (
    AgentExperienceRuntime,
    AgentExperienceEvent,
    OutcomeVerification,
)
from ..memory_firewall import MemoryFirewall, MemoryFirewallPolicy, FirewallContext
from .experience_records import digest


def reported_record(trajectory, verification, reported):
    """Retain the Brain record/fingerprint contract, not legacy quality claims.

    These shared schema fields are required by the unchanged compiler lifecycle.
    Reported steps never become observed tools or independently observed steps.
    """
    metadata = trajectory.metadata
    domain = str(metadata.get("domain") or "general")
    task_type = str(metadata.get("task_type") or "task")
    verified = verification is not None
    content = "Reported steps: " + " -> ".join(reported)
    fingerprint = digest(
        {
            "namespace": trajectory.namespace,
            "kind": "procedure",
            "domain": domain,
            "task_type": task_type,
            "content": content,
            "verified_track": verified,
        }
    )[:24]
    return ExperienceRecord.create(
        id=f"exp_runtime_{fingerprint}",
        namespace=trajectory.namespace,
        kind=ExperienceKind.PROCEDURE,
        title="Procedure reported for a verified outcome"
        if verified
        else "Reported procedure awaiting verification",
        content=content,
        applicability=ExperienceApplicability(
            domains=(domain,), task_types=(task_type,)
        ),
        outcome=ExperienceOutcome(
            success=verification.success if verification else None,
            score=verification.score if verification else None,
            summary=f"Verified by {verification.source.value}:{verification.verifier}."
            if verification
            else "Awaiting independent outcome verification.",
        ),
        confidence=0.85 if verified else 0.35,
        trust=TrustClass.TOOL_OUTPUT if verified else TrustClass.AGENT_GENERATED,
        status=ExperienceStatus.SHADOW,
        source=ExperienceSource(
            provider="agent_experience_runtime",
            source_type="independently_verified_run" if verified else "unverified_run",
            source_id=trajectory.id,
            metadata={
                "verification_evidence_id": verification.evidence_id
                if verification
                else None,
                "verification_reference": verification.reference
                if verification
                else None,
            },
        ),
        trajectory=TrajectoryProvenance(
            trajectory_id=trajectory.id,
            step_ids=tuple(step.id for step in trajectory.steps),
            source_sha256=trajectory.source_sha256,
            raw_event_count=trajectory.raw_event_count,
        ),
        metadata={
            "reported_steps": list(reported),
            "steps_observed": False,
            "objective": str(metadata.get("objective") or task_type),
            "runtime_run_id": metadata.get("run_id"),
            "verification_required": True,
        },
    )


class _BrainRuntime(AgentExperienceRuntime):
    """Brain-only extraction; finalization, review and promotion stay inherited."""

    def _derive_candidates(self, trajectory, verification):
        candidates = super()._derive_candidates(trajectory, verification)
        reported = trajectory.metadata.get("declared_procedure")
        if (
            isinstance(reported, list)
            and reported
            and all(isinstance(step, str) and step.strip() for step in reported)
        ):
            return (reported_record(trajectory, verification, reported), *candidates)
        return candidates


class PrivateRuntime:
    def __init__(self, state_dir):
        self.path = Path(state_dir) / "brain-experience.sqlite3"
        self._store = None

    @property
    def store(self):
        if self._store is None:
            self._store = SQLiteExperienceStore(self.path)
        return self._store

    def runtime(self, namespace):
        return _BrainRuntime(
            ExperienceCompiler(
                self.store, MemoryFirewall(MemoryFirewallPolicy(namespace=namespace))
            )
        )

    def integrate(self, *, brain_id, data):
        namespace, run = data["_namespace"], data["_run"]
        runtime = self.runtime(namespace)
        verification = OutcomeVerification(**data["_runtime_verification"])
        # Explicit reported-state events; user steps are not TOOL_CALL evidence.
        for sequence, (kind, payload) in enumerate(
            [
                (
                    "task.started",
                    {
                        "objective": data["summary"],
                        "domain": "brain",
                        "task_type": "reported procedure",
                        "declared_procedure": data["procedure"],
                    },
                ),
                (
                    "outcome",
                    {
                        "verified": True,
                        "success": verification.success,
                        "source": verification.source.value,
                        "evidence_id": verification.evidence_id,
                    },
                ),
                ("run.finished", {}),
            ]
        ):
            runtime.capture(
                AgentExperienceEvent(
                    id=digest([run, sequence]),
                    namespace=namespace,
                    run_id=run,
                    kind=kind,
                    sequence=sequence,
                    occurred_at=data["_verified_at"],
                    payload=payload,
                )
            )
        result = runtime.finalize_run(
            namespace=namespace, run_id=run, verification=verification
        )
        return list(result.candidate_ids)

    def compile(self, namespace, question):
        compiler = self.runtime(namespace).compiler
        return compiler.compile_packet(
            question,
            namespace=namespace,
            context=FirewallContext(namespace=namespace),
            top_k=100,
        )

    def purge(self, namespace):
        # Entire scope is a conservative erasure unit; retained Brain mappings
        # are opaque and permit retry after the authoritative payload is gone.
        self.runtime(namespace)
        with self.store._lock, self.store.conn:
            conn = self.store.conn
            conn.execute(
                "DELETE FROM experience_candidate_validations WHERE experience_id IN (SELECT id FROM experience_records WHERE namespace=?)",
                (namespace,),
            )
            conn.execute(
                "DELETE FROM experience_audit_events WHERE experience_id IN (SELECT id FROM experience_records WHERE namespace=?) OR trajectory_id IN (SELECT id FROM experience_trajectories WHERE namespace=?)",
                (namespace, namespace),
            )
            conn.execute(
                "DELETE FROM experience_records WHERE namespace=?", (namespace,)
            )
            conn.execute(
                "DELETE FROM experience_trajectory_steps WHERE trajectory_id IN (SELECT id FROM experience_trajectories WHERE namespace=?)",
                (namespace,),
            )
            conn.execute(
                "DELETE FROM experience_trajectories WHERE namespace=?", (namespace,)
            )
            for table in (
                "agent_experience_events",
                "agent_experience_verifications",
                "agent_experience_injections",
            ):
                conn.execute(f"DELETE FROM {table} WHERE namespace=?", (namespace,))

    def close(self):
        if self._store is not None:
            self._store.close()
