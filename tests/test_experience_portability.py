from __future__ import annotations

import copy
import json

import pytest

from wavemind.experience import (
    ExperienceKind,
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    SQLiteExperienceStore,
    TrustClass,
    parse_tool_trajectory,
)
from wavemind.experience_portability import (
    PORTABLE_EXPERIENCE_SCHEMA,
    export_experience_bundle,
    import_anthropic_memory,
    import_conversation_jsonl,
    import_experience_bundle,
    import_mem0_json,
    load_experience_bundle,
    write_experience_bundle,
)


def _record() -> ExperienceRecord:
    return ExperienceRecord.create(
        id="exp_portable",
        kind=ExperienceKind.SUCCESSFUL_STRATEGY,
        title="Retry transient HTTP errors",
        content="Retry HTTP 503 twice with bounded exponential backoff.",
        namespace="agent-a",
        confidence=0.91,
        trust=TrustClass.VERIFIED_OPERATOR,
        status=ExperienceStatus.SHADOW,
        source=ExperienceSource(
            provider="test",
            source_type="verified_run",
            source_id="run-7",
        ),
        metadata={"service": "checkout"},
    )


def test_portable_bundle_round_trip_has_exact_semantic_parity(tmp_path) -> None:
    source = SQLiteExperienceStore(tmp_path / "source.db")
    target = SQLiteExperienceStore(tmp_path / "target.db")
    try:
        record = source.put(_record())
        trajectory = parse_tool_trajectory(
            {
                "steps": [
                    {
                        "id": "call-1",
                        "kind": "tool_call",
                        "name": "checkout",
                        "input": {"order": 7},
                    },
                    {
                        "id": "result-1",
                        "kind": "tool_result",
                        "name": "checkout",
                        "output": {"ok": True},
                        "success": True,
                        "parent_id": "call-1",
                    },
                ]
            },
            provider="generic",
            namespace="agent-a",
            trajectory_id="trajectory-portable",
        )
        source.restore_trajectory(trajectory)
        source.add_candidate_validation(
            record.id,
            evidence_id="evaluation-1",
            successful=True,
            score=0.96,
            metadata={"suite": "held-out"},
        )

        path = tmp_path / "portable.json"
        written = write_experience_bundle(source, path, namespace="agent-a")
        report = import_experience_bundle(target, path)

        assert written["schema"] == PORTABLE_EXPERIENCE_SCHEMA
        assert report.exact
        assert report.parity == 1.0
        assert report.record_count == 1
        assert report.trajectory_count == 1
        assert report.validation_count == 1
        assert target.get(record.id) == record
        assert target.get_trajectory(trajectory.id) == trajectory
        assert target.candidate_validations(experience_id=record.id)[0][
            "evidence_id"
        ] == "evaluation-1"

        second = import_experience_bundle(target, path)
        assert second.exact
        assert second.inserted_records == 0
        assert second.inserted_trajectories == 0
        assert len(target.candidate_validations(experience_id=record.id)) == 1
    finally:
        source.close()
        target.close()


def test_portable_bundle_rejects_tampering_and_manifest_mismatch(tmp_path) -> None:
    store = SQLiteExperienceStore(tmp_path / "source.db")
    try:
        store.put(_record())
        bundle = export_experience_bundle(store)

        tampered = copy.deepcopy(bundle)
        tampered["records"][0]["content"] = "silently replaced"
        with pytest.raises(ValueError, match="checksum mismatch"):
            load_experience_bundle(tampered)

        manifest_tampered = copy.deepcopy(bundle)
        manifest_tampered["manifest"]["record_count"] = 99
        content = {
            key: value
            for key, value in manifest_tampered.items()
            if key != "content_sha256"
        }
        import hashlib

        manifest_tampered["content_sha256"] = hashlib.sha256(
            json.dumps(
                content,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with pytest.raises(ValueError, match="manifest record_count mismatch"):
            load_experience_bundle(manifest_tampered)
    finally:
        store.close()


def test_mem0_and_conversation_jsonl_imports_are_deduplicated(tmp_path) -> None:
    store = SQLiteExperienceStore(tmp_path / "imports.db")
    try:
        mem0 = {
            "results": [
                {
                    "id": "m-1",
                    "memory": "The customer prefers concise replies.",
                    "metadata": {"type": "preference", "confidence": 0.8},
                }
            ]
        }
        first = import_mem0_json(store, mem0, namespace="customer-1")
        second = import_mem0_json(store, mem0, namespace="customer-1")
        assert first[0].id == second[0].id
        assert first[0].kind == ExperienceKind.PREFERENCE
        assert first[0].trust == TrustClass.IMPORTED

        path = tmp_path / "conversation.jsonl"
        path.write_text(
            json.dumps(
                {
                    "id": "msg-1",
                    "role": "user",
                    "content": [{"type": "text", "text": "Never call after 18:00."}],
                    "preference": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        imported = import_conversation_jsonl(
            store,
            path,
            namespace="customer-1",
        )
        assert imported[0].kind == ExperienceKind.PREFERENCE
        assert imported[0].trust == TrustClass.EXPLICIT_USER
        assert len(store.list(namespace="customer-1", include_expired=True)) == 2
    finally:
        store.close()


def test_anthropic_memory_import_stays_inside_memory_root(tmp_path) -> None:
    store = SQLiteExperienceStore(tmp_path / "anthropic.db")
    try:
        imported = import_anthropic_memory(
            store,
            {
                "/memories/procedures/deploy.md": "Run the canary before production.",
                "/memories/preferences.md": "Use concise release notes.",
            },
            namespace="agent-a",
        )
        assert {item.source.uri for item in imported} == {
            "/memories/procedures/deploy.md",
            "/memories/preferences.md",
        }
        assert all(item.status == ExperienceStatus.SHADOW for item in imported)

        invalid = (
            "/etc/passwd",
            "/memories/../secret",
            r"\memories\..\secret",
            "/memories/%2e%2e/secret",
            "/memories-safe/secret",
        )
        for path in invalid:
            with pytest.raises(ValueError, match="memory path|encoded traversal"):
                import_anthropic_memory(store, {path: "blocked"})
    finally:
        store.close()
