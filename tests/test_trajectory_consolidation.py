from __future__ import annotations

from wavemind import WaveMind
from wavemind.encoders import HashingTextEncoder
from wavemind.trajectory_consolidation import TrajectoryDeltaConsolidator


def _state_text(
    *,
    goal: str,
    index: int,
    action: str,
    thought: str,
    labels: tuple[str, ...],
) -> str:
    observed = "\n".join(
        f"\t[{position}] button '{label}', visible"
        for position, label in enumerate(labels, start=1)
    )
    return "\n".join(
        (
            "Environment: browser",
            f"Trajectory goal: {goal}",
            "Trajectory outcome: success",
            f"State index: {index}",
            f"Action: {action}",
            f"Thought: {thought}",
            "Observed page:",
            observed,
        )
    )


def test_trajectory_delta_consolidation_is_idempotent_and_provenanced(tmp_path):
    memory = WaveMind(
        db_path=tmp_path / "trajectory.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
        score_threshold=0.0,
    )
    try:
        source_ids = memory.remember_batch(
            (
                {
                    "text": _state_text(
                        goal="Reassign the incident",
                        index=0,
                        action="Open filters",
                        thought="Find incident filters",
                        labels=("Filters", "Incident Portal"),
                    ),
                    "namespace": "tenant:a",
                    "tags": ("trajectory-state",),
                    "metadata": {
                        "trajectory_id": "run-1",
                        "state_index": 0,
                        "outcome": "success",
                    },
                },
                {
                    "text": _state_text(
                        goal="Reassign the incident",
                        index=1,
                        action="Select Incident Portal",
                        thought="Apply the matching filter",
                        labels=(
                            "Filters",
                            "Incident Portal",
                            "My Open Incidents",
                        ),
                    ),
                    "namespace": "tenant:a",
                    "tags": ("trajectory-state",),
                    "metadata": {
                        "trajectory_id": "run-1",
                        "state_index": 1,
                        "outcome": "success",
                    },
                },
            )
        )

        worker = TrajectoryDeltaConsolidator(memory)
        first = worker.run_once(namespace="tenant:a")
        second = worker.run_once(namespace="tenant:a")

        assert first.ok is True
        assert first.created == 2
        assert first.provenance_coverage == 1.0
        assert second.created == 0
        assert second.skipped_existing == 2

        rows = memory.query(
            "My Open Incidents",
            namespace="tenant:a",
            top_k=2,
            tags=("trajectory-delta",),
            min_score=0.0,
        )
        assert rows
        assert "My Open Incidents" in rows[0].text
        assert rows[0].metadata["source"] == "wavemind_trajectory_delta"
        assert rows[0].metadata["source_memory_ids"][0] in source_ids
        assert rows[0].metadata["trajectory_id"] == "run-1"
        assert worker.source_text(rows[0]) == memory.store.get(
            rows[0].metadata["source_memory_ids"][0]
        ).text
    finally:
        memory.close()


def test_trajectory_delta_consolidation_respects_namespace_and_input_tag(
    tmp_path,
):
    memory = WaveMind(
        db_path=tmp_path / "trajectory-scope.sqlite3",
        encoder=HashingTextEncoder(vector_dim=64),
        width=16,
        height=16,
        layers=1,
    )
    try:
        for namespace in ("tenant:a", "tenant:b"):
            memory.remember(
                _state_text(
                    goal="Inspect account",
                    index=0,
                    action="Open account",
                    thought="Review details",
                    labels=("Account", namespace),
                ),
                namespace=namespace,
                tags=("trajectory-state",),
                metadata={
                    "trajectory_id": f"run-{namespace}",
                    "state_index": 0,
                },
            )
        memory.remember(
            "ordinary note",
            namespace="tenant:a",
            metadata={"trajectory_id": "ignored", "state_index": 0},
        )

        report = TrajectoryDeltaConsolidator(memory).run_once(
            namespace="tenant:a"
        )

        assert report.scanned_memories == 2
        assert report.eligible_memories == 1
        assert report.created == 1
        assert memory.stats(namespace="tenant:a")["total_memories"] == 3
        assert memory.stats(namespace="tenant:b")["total_memories"] == 1
    finally:
        memory.close()
