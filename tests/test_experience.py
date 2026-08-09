from __future__ import annotations

import json
import time

import pytest

from wavemind import (
    ExperienceApplicability,
    ExperienceKind,
    ExperienceOutcome,
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    SQLiteExperienceStore,
    TrajectoryStepKind,
    TrustClass,
    ingest_jsonl_trajectories,
    parse_tool_trajectory,
)


def _source(source_id: str = "source-1") -> ExperienceSource:
    return ExperienceSource(
        provider="test",
        source_type="operator_observation",
        source_id=source_id,
    )


def _record(
    *,
    kind: ExperienceKind = ExperienceKind.PROCEDURE,
    title: str = "Run the release checks",
    content: str = "Build, validate, publish, and verify the public install.",
    status: ExperienceStatus = ExperienceStatus.ACTIVE,
    expires_at: float | None = None,
) -> ExperienceRecord:
    return ExperienceRecord.create(
        kind=kind,
        title=title,
        content=content,
        source=_source(),
        namespace="release",
        applicability=ExperienceApplicability(
            domains=("release-engineering",),
            task_types=("publish",),
            tools=("pytest", "twine"),
            conditions={"branch": "main"},
        ),
        outcome=ExperienceOutcome(
            success=True,
            score=1.0,
            summary="Public package verified.",
            metrics={"checks": 4},
        ),
        confidence=0.95,
        trust=TrustClass.VERIFIED_OPERATOR,
        status=status,
        expires_at=expires_at,
    )


def test_all_experience_kinds_round_trip_through_sqlite(tmp_path):
    path = tmp_path / "experience.sqlite3"
    with SQLiteExperienceStore(path) as store:
        records = [
            store.put(
                _record(
                    kind=kind,
                    title=f"{kind.value} title",
                    content=f"{kind.value} content",
                )
            )
            for kind in ExperienceKind
        ]

    with SQLiteExperienceStore(path) as reopened:
        loaded = reopened.list(namespace="release", limit=100)

    assert {record.kind for record in records} == set(ExperienceKind)
    assert {record.kind for record in loaded} == set(ExperienceKind)
    assert all(record.source.provider == "test" for record in loaded)
    assert all(record.applicability.tools == ("pytest", "twine") for record in loaded)
    assert all(record.outcome.success is True for record in loaded)


def test_record_validation_rejects_invalid_confidence_and_unknown_kind():
    with pytest.raises(ValueError, match="confidence"):
        ExperienceRecord.create(
            kind=ExperienceKind.FACT,
            title="A fact",
            content="A valid fact.",
            source=_source(),
            confidence=1.1,
        )

    with pytest.raises(ValueError, match="experience kind"):
        ExperienceRecord.create(
            kind="guess",
            title="A guess",
            content="Not a supported experience kind.",
            source=_source(),
        )


def test_supersession_and_rollback_preserve_version_chain_and_audit(tmp_path):
    with SQLiteExperienceStore(tmp_path / "experience.sqlite3") as store:
        original = store.put(_record())
        replacement = ExperienceRecord.create(
            kind=ExperienceKind.CORRECTION,
            title="Verify before publishing",
            content="Verify the public index before announcing availability.",
            source=_source("correction-1"),
            namespace="release",
            confidence=1.0,
            trust=TrustClass.EXPLICIT_USER,
            status=ExperienceStatus.ACTIVE,
        )
        promoted = store.supersede(
            original.id,
            replacement,
            reason="The original procedure omitted CDN propagation.",
        )
        restored = store.rollback(
            promoted.id,
            reason="The correction caused a regression in the release flow.",
        )
        replayed = store.rollback(
            promoted.id,
            reason="The correction caused a regression in the release flow.",
        )

        assert store.get(original.id).status == ExperienceStatus.SUPERSEDED
        assert promoted.version == 2
        assert promoted.supersedes_id == original.id
        assert store.get(promoted.id).status == ExperienceStatus.ROLLED_BACK
        assert restored.version == 3
        assert restored.rollback_of_id == promoted.id
        assert restored.supersedes_id == promoted.id
        assert restored.content == original.content
        assert replayed.id == restored.id
        assert [event.action for event in store.audit_events(limit=10)] == [
            "rolled_back",
            "superseded",
            "inserted",
        ]


def test_expire_due_hides_expired_records(tmp_path):
    now = time.time()
    record = _record(expires_at=now + 0.05)
    with SQLiteExperienceStore(tmp_path / "experience.sqlite3") as store:
        store.put(record)
        assert store.list(namespace="release")
        assert store.expire_due(now=now + 1.0) == 1
        assert store.list(namespace="release") == []
        expired = store.get(record.id)
        assert expired is not None
        assert expired.status == ExperienceStatus.EXPIRED


def test_openai_responses_trajectory_is_persisted_idempotently(tmp_path):
    payload = {
        "id": "trace-openai-1",
        "provider": "openai",
        "output": [
            {
                "type": "function_call",
                "id": "call-1",
                "name": "search_repository",
                "arguments": '{"query":"release workflow"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": {"matches": 3},
            },
        ],
    }
    trajectory = parse_tool_trajectory(payload, namespace="agent-a")
    assert trajectory.provider == "openai"
    assert trajectory.success is True
    assert [step.kind for step in trajectory.steps] == [
        TrajectoryStepKind.TOOL_CALL,
        TrajectoryStepKind.TOOL_RESULT,
    ]

    path = tmp_path / "experience.sqlite3"
    with SQLiteExperienceStore(path) as store:
        first = store.ingest_trajectory(trajectory)
        second = store.ingest_trajectory(trajectory)
        episode = store.get(first.experience_ids[0])
        restored = store.get_trajectory(trajectory.id)

    assert first.inserted is True
    assert second.inserted is False
    assert second.experience_ids == first.experience_ids
    assert episode is not None
    assert episode.kind == ExperienceKind.EPISODE
    assert episode.trajectory is not None
    assert episode.trajectory.source_sha256 == trajectory.source_sha256
    assert episode.outcome.success is True
    assert restored == trajectory


def test_anthropic_tool_trajectory_tracks_failed_result():
    payload = {
        "provider": "anthropic",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu-1",
                        "name": "deploy",
                        "input": {"environment": "staging"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu-1",
                        "is_error": True,
                        "content": "health check failed",
                    }
                ],
            },
        ],
    }

    trajectory = parse_tool_trajectory(payload, namespace="agent-b")

    assert trajectory.provider == "anthropic"
    assert trajectory.success is False
    assert trajectory.steps[1].parent_id == "toolu-1"
    assert trajectory.steps[1].success is False


def test_mcp_trajectory_accepts_combined_request_response_event():
    payload = {
        "provider": "mcp",
        "events": [
            {
                "request": {
                    "jsonrpc": "2.0",
                    "id": "rpc-1",
                    "method": "tools/call",
                    "params": {
                        "name": "read_file",
                        "arguments": {"path": "README.md"},
                    },
                },
                "response": {
                    "jsonrpc": "2.0",
                    "id": "rpc-1",
                    "result": {"content": [{"type": "text", "text": "WaveMind"}]},
                },
            }
        ],
    }

    trajectory = parse_tool_trajectory(payload, namespace="agent-c")

    assert trajectory.provider == "mcp"
    assert trajectory.success is True
    assert trajectory.steps[0].name == "read_file"
    assert trajectory.steps[1].parent_id == "rpc-1"


def test_jsonl_ingest_supports_generic_and_provider_trajectories(tmp_path):
    path = tmp_path / "trajectories.jsonl"
    rows = [
        {
            "provider": "generic",
            "trajectory_id": "generic-1",
            "steps": [
                {
                    "id": "state-1",
                    "kind": "state",
                    "input": {"ticket": "INC-42"},
                }
            ],
        },
        {
            "provider": "mcp",
            "id": "mcp-1",
            "events": [
                {
                    "method": "tools/call",
                    "id": "call-2",
                    "params": {"name": "lookup_ticket", "arguments": {"id": "INC-42"}},
                    "response": {"id": "call-2", "result": {"status": "resolved"}},
                }
            ],
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    with SQLiteExperienceStore(tmp_path / "experience.sqlite3") as store:
        reports = ingest_jsonl_trajectories(
            store,
            path,
            namespace="support",
            trust=TrustClass.IMPORTED,
        )
        episodes = store.list(namespace="support", limit=10)

    assert len(reports) == 2
    assert all(report.inserted for report in reports)
    assert {report.provider for report in reports} == {"generic", "mcp"}
    assert len(episodes) == 2
    assert all(episode.trust == TrustClass.IMPORTED for episode in episodes)


def test_jsonl_ingest_rejects_oversized_lines(tmp_path):
    path = tmp_path / "too-large.jsonl"
    path.write_text(json.dumps({"steps": [{"kind": "state", "input": "x" * 100}]}))

    with SQLiteExperienceStore(tmp_path / "experience.sqlite3") as store:
        with pytest.raises(ValueError, match="line size limit"):
            ingest_jsonl_trajectories(store, path, max_line_bytes=16)
