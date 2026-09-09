"""The private existing runtime adapter; no default database or remote calls."""

from pathlib import Path

from ..experience import SQLiteExperienceStore
from ..experience_compiler import ExperienceCompiler
from ..experience_runtime import (
    AgentExperienceRuntime,
    AgentExperienceEvent,
    OutcomeVerification,
)
from ..memory_firewall import MemoryFirewall, MemoryFirewallPolicy, FirewallContext
from .experience_records import digest


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
        return AgentExperienceRuntime(
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
