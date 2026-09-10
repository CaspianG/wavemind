"""Portability exercises real authority, SQLite files, and recovery lifecycle."""

import json
import hashlib
import sqlite3
import subprocess
import sys
import zipfile

import pytest

from wavemind.brain.models import BrainError, Principal
from wavemind.brain.service import BrainService


def import_text(service, owner, brain_id, text="Orchard inspection plan"):
    preview = service.preview_import(
        principal=owner,
        brain_id=brain_id,
        files=[{"name": "plan.md", "content": text.encode()}],
    )
    return service.commit_import(
        principal=owner,
        brain_id=brain_id,
        preview_id=preview["id"],
        accepted_ids=[preview["files"][0]["id"]],
    )["sources"][0]


@pytest.fixture
def populated_brain_fixture(tmp_path):
    service, owner = BrainService(tmp_path / "original"), Principal("owner")
    brain_id = service.create_brain(principal=owner, title="Orchard")["id"]
    source = import_text(service, owner, brain_id)
    citation = source["citations"][0]["id"]
    service.propose_claims(
        principal=owner,
        brain_id=brain_id,
        claims=[
            {
                "id": "inspection",
                "kind": "goal",
                "key": "orchard",
                "content": "Inspect the orchard",
                "citation_ids": [citation],
            }
        ],
    )
    service.review_claims(
        principal=owner,
        brain_id=brain_id,
        claim_ids=["inspection"],
        action="approve",
    )
    yield service, owner, brain_id
    service.close()


def test_restore_without_current_history_is_quarantined(
    populated_brain_fixture, tmp_path
):
    service, owner, brain_id = populated_brain_fixture
    archive = tmp_path / "brain.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        result = restored.restore_brain(principal=owner, archive=archive)
        assert result["brain_id"] == brain_id
        packet = restored.build_context(
            principal=owner, brain_id=brain_id, question="Continue"
        )
        assert packet["claims"] == []
        assert "restored_sources_quarantined" in packet["warnings"]
    finally:
        restored.close()


def test_export_requires_read_and_filters_all_source_lineage(populated_brain_fixture):
    service, owner, brain_id = populated_brain_fixture
    source = service.list_sources(principal=owner, brain_id=brain_id)[0]
    service.set_member(
        principal=owner, brain_id=brain_id, identity="agent", role="owner"
    )
    write_only = Principal("agent", "agent", {brain_id}, {"export"})
    with pytest.raises(BrainError, match="Resource not found"):
        service.export_brain(principal=write_only, brain_id=brain_id)
    agent = Principal("agent", "agent", {brain_id}, {"read", "export"})
    exported = service.export_brain(principal=agent, brain_id=brain_id)
    assert exported["schema"] == "wavemind.brain_export.v1"
    assert exported["counts"]["claims"] == 1
    service.change_source(
        principal=owner, brain_id=brain_id, source_id=source["id"], action="revoke"
    )
    serialized = json.dumps(service.export_brain(principal=owner, brain_id=brain_id))
    assert "Orchard inspection plan" not in serialized
    assert "Inspect the orchard" not in serialized


def test_backup_never_contains_other_brain_bytes(populated_brain_fixture, tmp_path):
    service, owner, brain_id = populated_brain_fixture
    other_owner = Principal("other-owner")
    other = service.create_brain(principal=other_owner, title="Other Brain")["id"]
    sentinel = "UNRELATED_PRIVATE_SENTINEL_48321_CROSS_BRAIN"
    import_text(service, other_owner, other, sentinel)
    archive = tmp_path / "selected.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    with zipfile.ZipFile(archive) as opened:
        for name in opened.namelist():
            assert sentinel.encode() not in opened.read(name)
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        restored.restore_brain(principal=owner, archive=archive)
        with restored.store.transaction() as conn:
            assert [r[0] for r in conn.execute("SELECT id FROM brains")] == [brain_id]
            assert (
                conn.execute(
                    "SELECT 1 FROM sources WHERE brain_id=?", (other,)
                ).fetchone()
                is None
            )
    finally:
        restored.close()


def test_export_source_acl_omits_whole_derived_record(populated_brain_fixture):
    service, owner, brain_id = populated_brain_fixture
    hidden = import_text(service, owner, brain_id, "SECOND_PRIVATE_ORIGIN")
    service.propose_claims(
        principal=owner,
        brain_id=brain_id,
        claims=[
            {
                "id": "mixed",
                "kind": "fact",
                "key": "mixed",
                "content": "DERIVED_MIXED_PRIVATE_CONTENT",
                "citation_ids": [hidden["citations"][0]["id"]],
                "depends_on": ["inspection"],
            }
        ],
    )
    service.set_member(
        principal=owner, brain_id=brain_id, identity="exporter", role="editor"
    )
    actor = Principal("exporter", "agent", {brain_id}, {"read", "export"})
    service.set_source_access(
        principal=owner, brain_id=brain_id, source_id=hidden["id"], readers=[]
    )
    unrelated = service.create_brain(
        principal=Principal("stranger"), title="Unrelated"
    )["id"]
    import_text(
        service, Principal("stranger"), unrelated, "OTHER_BRAIN_EXPORT_SENTINEL"
    )
    encoded = json.dumps(service.export_brain(principal=actor, brain_id=brain_id))
    assert "SECOND_PRIVATE_ORIGIN" not in encoded
    assert "DERIVED_MIXED_PRIVATE_CONTENT" not in encoded
    assert "Inspect the orchard" in encoded
    assert "OTHER_BRAIN_EXPORT_SENTINEL" not in encoded


def test_restore_requires_explicit_bootstrap_binding(populated_brain_fixture, tmp_path):
    service, owner, brain_id = populated_brain_fixture
    archive = tmp_path / "brain.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    restored = BrainService(tmp_path / "unbound")
    try:
        with pytest.raises(BrainError) as error:
            restored.restore_brain(principal=owner, archive=archive)
        assert error.value.code == "bootstrap_required"
        assert restored.list_brains(principal=owner) == []
    finally:
        restored.close()


def test_owner_review_admission_and_restart(populated_brain_fixture, tmp_path):
    service, owner, brain_id = populated_brain_fixture
    source = service.list_sources(principal=owner, brain_id=brain_id)[0]
    archive = tmp_path / "brain.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    restored = BrainService(tmp_path / "restored", bootstrap_owner="new-owner")
    new_owner = Principal("new-owner")
    try:
        restored.restore_brain(principal=new_owner, archive=archive)
        assert restored.list_brains(principal=owner) == []
        assert restored.list_sources(principal=new_owner, brain_id=brain_id) == []
        managed = restored.list_managed_sources(principal=new_owner, brain_id=brain_id)
        assert managed == {
            "sources": [{"id": source["id"], "status": "quarantined"}],
            "next_cursor": None,
        }
        reviewed = restored.review_restored_source(
            principal=new_owner, brain_id=brain_id, source_id=source["id"]
        )
        assert reviewed["citations"][0]["text"] == "Orchard inspection plan"
        restored.admit_restored_sources(
            principal=new_owner, brain_id=brain_id, source_ids=[source["id"]]
        )
        packet = restored.build_context(
            principal=new_owner, brain_id=brain_id, question="orchard"
        )
        assert packet["claims"] == []
        with restored.store.transaction() as conn:
            claim = conn.execute(
                "SELECT status,payload_json FROM claims WHERE id='inspection'"
            ).fetchone()
            assert claim[0] == "proposed"
            assert json.loads(claim[1])["needs_recheck"] is True
    finally:
        restored.close()
    reopened = BrainService(tmp_path / "restored")
    try:
        assert (
            reopened.list_sources(principal=new_owner, brain_id=brain_id)[0]["status"]
            == "active"
        )
        assert (
            reopened.build_context(
                principal=new_owner, brain_id=brain_id, question="orchard"
            )["claims"]
            == []
        )
    finally:
        reopened.close()


def test_legacy_backup_refuses_selected_brain_profile(
    populated_brain_fixture, tmp_path
):
    from wavemind import HashingTextEncoder, SQLiteExperienceStore, WaveMind
    from wavemind.product_backup import ProductBackupError, create_product_backup

    service, _, _ = populated_brain_fixture
    profile = service.store.path.parent
    mind = WaveMind(
        db_path=profile / "core.sqlite3", encoder=HashingTextEncoder(vector_dim=32)
    )
    try:
        with SQLiteExperienceStore(profile / "experience.sqlite3") as experience:
            with pytest.raises(ProductBackupError, match="Brain"):
                create_product_backup(mind, experience, tmp_path / "incomplete.zip")
        assert not (tmp_path / "incomplete.zip").exists()
    finally:
        mind.close()


def test_legacy_upgrade_refuses_selected_brain_profile(
    populated_brain_fixture, tmp_path
):
    from wavemind.upgrade import (
        UpgradeBlocked,
        UpgradeOptions,
        create_upgrade_backup,
        run_upgrade,
    )

    service, _, _ = populated_brain_fixture
    profile = service.store.path.parent
    options = UpgradeOptions(
        core_db=profile / "core.sqlite3",
        experience_db=profile / "experience.sqlite3",
        state_dir=tmp_path / "upgrade",
        target="1.0.0",
    )
    with pytest.raises(UpgradeBlocked, match="Brain"):
        create_upgrade_backup(
            options,
            tmp_path / "incomplete.zip",
            source_version="1.0.0",
            target_version="1.1.0",
        )
    with pytest.raises(UpgradeBlocked, match="Brain"):
        run_upgrade(options)
    assert not (tmp_path / "incomplete.zip").exists()


def verified_runs(
    service, owner, brain_id, count=3, *, start=0, procedure="Inspect orchard"
):
    for index in range(start, start + count):
        packet = service.build_context(
            principal=owner, brain_id=brain_id, question="orchard"
        )
        receipt = service.begin_action(
            principal=owner,
            brain_id=brain_id,
            packet_id=packet["id"],
            run_id=f"run-{index}",
            action="Inspect orchard",
        )
        source = import_text(
            service, owner, brain_id, f"Independent successful inspection {index}"
        )
        citation = source["citations"][0]["id"]
        outcome = service.record_outcome(
            principal=owner,
            brain_id=brain_id,
            receipt_id=receipt["id"],
            outcome={
                "idempotency_key": "attempt",
                "summary": "Inspection done",
                "procedure": [procedure],
                "evidence_citation_ids": [citation],
            },
        )
        service.register_outcome_verifier(
            verifier_id="test", source="test", callback=lambda context: True
        )
        service.verify_outcome_with(
            principal=owner,
            brain_id=brain_id,
            outcome_id=outcome["id"],
            verifier_id="test",
            evidence_citation_ids=[citation],
        )
        service.drain_outbox()


def rewrite_archive(
    original, target, tmp_path, *, sql=None, member=None, payload=None, refresh=True
):
    """Adversarial fixture recomputes integrity metadata, never authority."""
    with zipfile.ZipFile(original) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    if sql:
        name = member or "brain.sqlite3"
        database = tmp_path / ("mutated-" + target.stem + ".sqlite3")
        database.write_bytes(files[name])
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        try:
            for statement, parameters in sql:
                conn.execute(statement, parameters)
            conn.commit()
            files[name] = database.read_bytes()
            if refresh:
                manifest = json.loads(files["manifest.json"])
                info = manifest["files"][name]
                info["size"] = len(files[name])
                info["sha256"] = hashlib.sha256(files[name]).hexdigest()
                for table in info["tables"]:
                    rows = [
                        dict(r)
                        for r in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
                    ]
                    encoded = json.dumps(
                        rows,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode()
                    info["tables"][table] = {
                        "count": len(rows),
                        "digest": hashlib.sha256(encoded).hexdigest(),
                    }
                files["manifest.json"] = json.dumps(manifest).encode()
        finally:
            conn.close()
    elif member:
        files[member] = payload
    with zipfile.ZipFile(target, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)


def test_verified_private_roundtrip_preserves_history_and_scope(
    populated_brain_fixture, tmp_path
):
    service, owner, brain_id = populated_brain_fixture
    verified_runs(service, owner, brain_id)
    before = service.review_experience(principal=owner, brain_id=brain_id)
    assert before["procedures"][0]["eligible"] is True
    other_owner = Principal("other")
    other = service.create_brain(principal=other_owner, title="Other")["id"]
    other_source = import_text(
        service, other_owner, other, "UNRELATED_PRIVATE_RUNTIME_7345"
    )
    service.propose_claims(
        principal=other_owner,
        brain_id=other,
        claims=[
            {
                "id": "other-plan",
                "kind": "goal",
                "key": "orchard",
                "content": "UNRELATED_PRIVATE_RUNTIME_7345",
                "citation_ids": [other_source["citations"][0]["id"]],
            }
        ],
    )
    service.review_claims(
        principal=other_owner,
        brain_id=other,
        claim_ids=["other-plan"],
        action="approve",
    )
    verified_runs(service, other_owner, other, count=1)
    archive = tmp_path / "private.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    with zipfile.ZipFile(archive) as opened:
        assert set(opened.namelist()) == {
            "manifest.json",
            "brain.sqlite3",
            "brain-experience.sqlite3",
        }
        assert (
            json.loads(opened.read("manifest.json"))["files"][
                "brain-experience.sqlite3"
            ]["schema_version"]
            == 1
        )
        assert all(
            b"UNRELATED_PRIVATE_RUNTIME_7345" not in opened.read(name)
            for name in opened.namelist()
        )
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        result = restored.restore_brain(
            principal=owner,
            archive=archive,
            current_state_dir=service.store.path.parent,
        )
        assert result["current_history_verified"] is True
        assert restored.review_experience(principal=owner, brain_id=brain_id) == before
        assert len(restored.experience.private.store.candidate_validations()) == 3
        with (
            restored.store.transaction() as conn,
            service.store.transaction() as original,
        ):
            assert [
                tuple(r) for r in conn.execute("SELECT * FROM packets ORDER BY id")
            ] == [
                tuple(r)
                for r in original.execute(
                    "SELECT * FROM packets WHERE brain_id=? ORDER BY id", (brain_id,)
                )
            ]
    finally:
        restored.close()


def test_revoked_backup_omits_bytes_and_owner_can_delete_after_restart(
    populated_brain_fixture, tmp_path
):
    service, owner, brain_id = populated_brain_fixture
    verified_runs(service, owner, brain_id)
    source = service.list_sources(principal=owner, brain_id=brain_id)[0]
    service.change_source(
        principal=owner, brain_id=brain_id, source_id=source["id"], action="revoke"
    )
    archive = tmp_path / "revoked.wmb"
    result = service.backup_brain(
        principal=owner, brain_id=brain_id, destination=archive
    )
    assert "unavailable_content_omitted" in result["warnings"]
    with zipfile.ZipFile(archive) as opened:
        for name in opened.namelist():
            assert b"Orchard inspection plan" not in opened.read(name)
            assert b"Inspect the orchard" not in opened.read(name)
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    restored.restore_brain(principal=owner, archive=archive)
    restored.close()
    restored = BrainService(tmp_path / "restored")
    try:
        managed = restored.list_managed_sources(principal=owner, brain_id=brain_id)
        assert {"id": source["id"], "status": "revoked"} in managed["sources"]
        review = restored.review_restored_source(
            principal=owner, brain_id=brain_id, source_id=source["id"]
        )
        assert review["versions"] == review["citations"] == []
        restored.change_source(
            principal=owner, brain_id=brain_id, source_id=source["id"], action="delete"
        )
        with pytest.raises(BrainError):
            restored.admit_restored_sources(
                principal=owner, brain_id=brain_id, source_ids=[source["id"]]
            )
    finally:
        restored.close()


def test_current_deletion_overrides_stale_backup(populated_brain_fixture, tmp_path):
    service, owner, brain_id = populated_brain_fixture
    source = service.list_sources(principal=owner, brain_id=brain_id)[0]
    archive = tmp_path / "old.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    service.change_source(
        principal=owner, brain_id=brain_id, source_id=source["id"], action="delete"
    )
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        restored.restore_brain(
            principal=owner,
            archive=archive,
            current_state_dir=service.store.path.parent,
        )
        assert restored.list_managed_sources(principal=owner, brain_id=brain_id)[
            "sources"
        ] == [{"id": source["id"], "status": "deleted"}]
        with restored.store.transaction() as conn:
            assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
            assert conn.execute("SELECT payload_json FROM claims").fetchone()[0] == "{}"
        with pytest.raises(BrainError):
            restored.admit_restored_sources(
                principal=owner, brain_id=brain_id, source_ids=[source["id"]]
            )
    finally:
        restored.close()


@pytest.mark.parametrize(
    "attack",
    [
        "digest",
        "schema",
        "traversal",
        "duplicate",
        "ratio",
        "packet_basis",
        "row_schema",
        "receipt_binding",
    ],
)
def test_archive_corruption_and_schema_surprises_fail_before_activation(
    populated_brain_fixture, tmp_path, attack
):
    service, owner, brain_id = populated_brain_fixture
    packet = service.build_context(
        principal=owner, brain_id=brain_id, question="orchard"
    )
    service.begin_action(
        principal=owner,
        brain_id=brain_id,
        packet_id=packet["id"],
        run_id="binding",
        action="Inspect",
    )
    original, hostile = tmp_path / "original.wmb", tmp_path / "hostile.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=original)
    if attack == "schema":
        rewrite_archive(
            original,
            hostile,
            tmp_path,
            sql=[("CREATE TABLE surprise(secret TEXT)", ())],
        )
    elif attack == "packet_basis":
        rewrite_archive(
            original, hostile, tmp_path, sql=[("DELETE FROM brain_packet_basis", ())]
        )
    elif attack == "row_schema":
        rewrite_archive(
            original,
            hostile,
            tmp_path,
            sql=[("UPDATE source_versions SET schema_version=99", ())],
        )
    elif attack == "receipt_binding":
        rewrite_archive(
            original,
            hostile,
            tmp_path,
            sql=[
                (
                    "UPDATE receipts SET payload_json=json_set(payload_json,'$.revision',999999)",
                    (),
                )
            ],
        )
    elif attack == "digest":
        rewrite_archive(
            original,
            hostile,
            tmp_path,
            sql=[("UPDATE claims SET kind='decision'", ())],
            refresh=False,
        )
    elif attack == "traversal":
        rewrite_archive(
            original, hostile, tmp_path, member="../escape", payload=b"invalid"
        )
    else:
        with (
            zipfile.ZipFile(original) as source,
            zipfile.ZipFile(
                hostile,
                "w",
                compression=zipfile.ZIP_DEFLATED
                if attack == "ratio"
                else zipfile.ZIP_STORED,
            ) as target,
        ):
            for name in source.namelist():
                target.writestr(
                    name,
                    b"0" * (2 * 1024 * 1024)
                    if attack == "ratio" and name == "brain.sqlite3"
                    else source.read(name),
                )
            if attack == "duplicate":
                with pytest.warns(UserWarning):
                    target.writestr("manifest.json", source.read("manifest.json"))
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        with pytest.raises(BrainError) as error:
            restored.restore_brain(principal=owner, archive=hostile)
        assert error.value.code == "invalid_archive"
        assert restored.list_brains(principal=owner) == []
        assert not restored.experience.private.path.exists()
    finally:
        restored.close()


@pytest.mark.parametrize(
    "table,statement",
    [
        (
            "claims",
            "UPDATE claims SET payload_json=json_set(payload_json,'$.content','FORGED APPROVED CLAIM')",
        ),
        (
            "outcomes",
            "UPDATE outcomes SET payload_json=json_set(payload_json,'$.verification.source','environment','$.verification.note','FORGED VERIFICATION')",
        ),
        ("private", "UPDATE experience_candidate_validations SET score=999"),
    ],
)
def test_source_digest_alone_cannot_authenticate_approval_or_verification(
    populated_brain_fixture, tmp_path, table, statement
):
    service, owner, brain_id = populated_brain_fixture
    verified_runs(service, owner, brain_id)
    original, hostile = tmp_path / "original.wmb", tmp_path / "hostile.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=original)
    rewrite_archive(
        original,
        hostile,
        tmp_path,
        sql=[(statement, ())],
        member="brain-experience.sqlite3" if table == "private" else "brain.sqlite3",
    )
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        result = restored.restore_brain(
            principal=owner,
            archive=hostile,
            current_state_dir=service.store.path.parent,
        )
        assert result["current_history_verified"] is False
        packet = restored.build_context(
            principal=owner, brain_id=brain_id, question="orchard"
        )
        assert packet["claims"] == packet["experiences"] == []
        sources = restored.list_managed_sources(principal=owner, brain_id=brain_id)[
            "sources"
        ]
        restored.admit_restored_sources(
            principal=owner, brain_id=brain_id, source_ids=[r["id"] for r in sources]
        )
        assert (
            restored.build_context(
                principal=owner, brain_id=brain_id, question="orchard"
            )["experiences"]
            == []
        )
        assert restored.experience.private.store.candidate_validations() == []
    finally:
        restored.close()


def test_backup_finishes_in_bounded_process_without_sqlite_self_deadlock(tmp_path):
    command = """
from pathlib import Path
from wavemind.brain.service import BrainService
from wavemind.brain.models import Principal
s=BrainService(Path(__import__('sys').argv[1]))
p=Principal('owner')
b=s.create_brain(principal=p,title='bounded')['id']
s.backup_brain(principal=p,brain_id=b,destination=Path(__import__('sys').argv[2]))
s.close()
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            command,
            str(tmp_path / "profile"),
            str(tmp_path / "result.wmb"),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "result.wmb").is_file()


def test_export_includes_complete_verified_experience_provenance(
    populated_brain_fixture,
):
    service, owner, brain_id = populated_brain_fixture
    verified_runs(service, owner, brain_id)
    exported = service.export_brain(principal=owner, brain_id=brain_id)
    assert exported["counts"]["experiences"] == 1
    procedure = exported["records"]["experiences"][0]
    assert procedure["content"] == "Reported steps: Inspect orchard"
    assert procedure["validation_count"] == 3
    assert procedure["verification_sources"] == ["test"]
    assert procedure["integration_statuses"] == ["completed"]
    assert procedure["eligibility"] == "requires_live_context_validation"
    assert len(procedure["outcome_ids"]) == 3
    assert "exp_runtime_" not in json.dumps(exported)


def test_failed_private_activation_rolls_back_and_can_retry(
    populated_brain_fixture, tmp_path, monkeypatch
):
    import wavemind.brain.portability as portability

    service, owner, brain_id = populated_brain_fixture
    verified_runs(service, owner, brain_id)
    archive = tmp_path / "private.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    original = portability.os.replace

    def failure_after_install(source, destination):
        original(source, destination)
        raise OSError("simulated filesystem completion failure")

    try:
        monkeypatch.setattr(portability.os, "replace", failure_after_install)
        with pytest.raises(BrainError) as error:
            restored.restore_brain(principal=owner, archive=archive)
        assert error.value.code == "restore_failed"
        assert restored.list_brains(principal=owner) == []
        assert not restored.experience.private.path.exists()
        assert not (restored.store.path.parent / portability.RESTORE_MARKER).exists()
        monkeypatch.setattr(portability.os, "replace", original)
        assert (
            restored.restore_brain(principal=owner, archive=archive)["status"]
            == "restored"
        )
    finally:
        restored.close()


@pytest.mark.parametrize(
    "mismatch",
    [
        "none",
        "private_changed",
        "authority_missing",
        "authority_unexpected",
        "authority_schema",
        "malformed",
    ],
)
def test_interrupted_activation_recovery_never_guesses(
    populated_brain_fixture, tmp_path, monkeypatch, mismatch
):
    import wavemind.brain.portability as portability

    service, owner, brain_id = populated_brain_fixture
    verified_runs(service, owner, brain_id)
    archive = tmp_path / "private.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    profile = tmp_path / "restored"
    restored = BrainService(profile, bootstrap_owner=owner.identity)
    original = portability.os.replace

    def interrupted_after_install(source, destination):
        original(source, destination)
        raise KeyboardInterrupt("simulated process loss")

    monkeypatch.setattr(portability.os, "replace", interrupted_after_install)
    with pytest.raises(KeyboardInterrupt):
        restored.restore_brain(principal=owner, archive=archive)
    restored.close()
    monkeypatch.setattr(portability.os, "replace", original)
    private = profile / "brain-experience.sqlite3"
    assert private.is_file()
    if mismatch == "private_changed":
        with private.open("ab") as file:
            file.write(b"changed")
    elif mismatch == "authority_missing":
        (profile / "brain.sqlite3").unlink()
    elif mismatch == "authority_unexpected":
        with sqlite3.connect(profile / "brain.sqlite3") as conn:
            conn.execute(
                "INSERT INTO brains(id,title,mode,owner) VALUES ('unrelated','Other','personal','elsewhere')"
            )
    elif mismatch == "authority_schema":
        with sqlite3.connect(profile / "brain.sqlite3") as conn:
            conn.execute("CREATE TABLE surprise(value TEXT)")
    elif mismatch == "malformed":
        (profile / portability.RESTORE_MARKER).write_text("{}", encoding="utf-8")
    before = private.read_bytes()
    if mismatch == "none":
        reopened = BrainService(profile, bootstrap_owner=owner.identity)
        try:
            assert not private.exists()
            assert reopened.list_brains(principal=owner) == []
            assert (
                reopened.restore_brain(principal=owner, archive=archive)["status"]
                == "restored"
            )
        finally:
            reopened.close()
    else:
        with pytest.raises(BrainError) as error:
            BrainService(profile)
        assert error.value.code == "recovery_required"
        assert private.read_bytes() == before
        assert (profile / portability.RESTORE_MARKER).exists()


def test_committed_marker_recovery_retains_both_databases(
    populated_brain_fixture, tmp_path, monkeypatch
):
    import wavemind.brain.portability as portability

    service, owner, brain_id = populated_brain_fixture
    verified_runs(service, owner, brain_id)
    archive = tmp_path / "private.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    profile = tmp_path / "restored"
    restored = BrainService(profile, bootstrap_owner=owner.identity)
    original = portability.recover_restore

    def interrupted_finalize(path):
        raise KeyboardInterrupt("after authoritative commit")

    monkeypatch.setattr(portability, "recover_restore", interrupted_finalize)
    with pytest.raises(KeyboardInterrupt):
        restored.restore_brain(
            principal=owner,
            archive=archive,
            current_state_dir=service.store.path.parent,
        )
    restored.close()
    private_bytes = (profile / "brain-experience.sqlite3").read_bytes()
    monkeypatch.setattr(portability, "recover_restore", original)
    reopened = BrainService(profile)
    try:
        assert (profile / "brain-experience.sqlite3").read_bytes() == private_bytes
        assert (
            reopened.review_experience(principal=owner, brain_id=brain_id)[
                "procedures"
            ][0]["eligible"]
            is True
        )
        assert not (profile / portability.RESTORE_MARKER).exists()
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "role,operations",
    [
        ("owner", {"restore"}),
        ("owner", {"read"}),
        ("reader", {"restore", "read"}),
    ],
)
def test_quarantine_review_and_admission_require_independent_owner_read(
    populated_brain_fixture, tmp_path, role, operations
):
    service, owner, brain_id = populated_brain_fixture
    archive = tmp_path / "backup.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        restored.restore_brain(principal=owner, archive=archive)
        source_id = restored.list_managed_sources(principal=owner, brain_id=brain_id)[
            "sources"
        ][0]["id"]
        restored.set_member(
            principal=owner, brain_id=brain_id, identity="limited", role=role
        )
        principal = Principal("limited", operations=operations)
        for operation in (
            lambda: restored.review_restored_source(
                principal=principal, brain_id=brain_id, source_id=source_id
            ),
            lambda: restored.admit_restored_sources(
                principal=principal, brain_id=brain_id, source_ids=[source_id]
            ),
        ):
            with pytest.raises(BrainError) as error:
                operation()
            assert error.value.code == "not_found"
        if "read" in operations:
            packet = restored.build_context(
                principal=principal, brain_id=brain_id, question="orchard"
            )
            assert "restored_sources_quarantined" not in packet["warnings"]
    finally:
        restored.close()


def test_management_review_pagination_and_foreign_source_cursor(
    populated_brain_fixture, tmp_path
):
    service, owner, brain_id = populated_brain_fixture
    large = import_text(service, owner, brain_id, "A" * 17000)
    archive = tmp_path / "backup.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        restored.restore_brain(principal=owner, archive=archive)
        first = restored.list_managed_sources(
            principal=owner, brain_id=brain_id, limit=1
        )
        second = restored.list_managed_sources(
            principal=owner, brain_id=brain_id, limit=1, cursor=first["next_cursor"]
        )
        assert first["sources"][0]["id"] != second["sources"][0]["id"]
        assert second["next_cursor"] is None
        page = restored.review_restored_source(
            principal=owner, brain_id=brain_id, source_id=large["id"], limit=1
        )
        assert len(page["citations"]) == 1
        following = restored.review_restored_source(
            principal=owner,
            brain_id=brain_id,
            source_id=large["id"],
            limit=1,
            citation_cursor=page["next_citation_cursor"],
        )
        assert following["citations"][0]["ordinal"] == 1
        other_id = next(
            r["id"]
            for r in restored.list_managed_sources(principal=owner, brain_id=brain_id)[
                "sources"
            ]
            if r["id"] != large["id"]
        )
        with pytest.raises(BrainError) as error:
            restored.review_restored_source(
                principal=owner,
                brain_id=brain_id,
                source_id=other_id,
                citation_cursor=page["citations"][0]["id"],
            )
        assert error.value.code == "not_found"
        for limit in [True, 0, 101, "1"]:
            with pytest.raises(BrainError) as error:
                restored.review_restored_source(
                    principal=owner,
                    brain_id=brain_id,
                    source_id=large["id"],
                    limit=limit,
                )
            assert error.value.code == "invalid_input"
    finally:
        restored.close()


def test_current_history_never_uses_archived_owner_credentials(
    populated_brain_fixture, tmp_path
):
    service, owner, brain_id = populated_brain_fixture
    archive = tmp_path / "backup.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    new_owner = Principal("new-owner")
    restored = BrainService(tmp_path / "restored", bootstrap_owner=new_owner.identity)
    try:
        with pytest.raises(BrainError) as error:
            restored.restore_brain(
                principal=new_owner,
                archive=archive,
                current_state_dir=service.store.path.parent,
            )
        assert error.value.code == "not_found"
        assert restored.list_brains(principal=new_owner) == []
        assert (
            restored.restore_brain(principal=new_owner, archive=archive)["status"]
            == "restored"
        )
        with pytest.raises(BrainError) as error:
            restored.restore_brain(principal=new_owner, archive=archive)
        assert error.value.code == "target_not_empty"
    finally:
        restored.close()


def test_backup_quarantine_content_needs_restore_grant(
    populated_brain_fixture, tmp_path
):
    service, owner, brain_id = populated_brain_fixture
    archive = tmp_path / "backup.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        restored.restore_brain(principal=owner, archive=archive)
        limited = Principal(
            owner.identity, operations={"manage_access", "export", "read"}
        )
        with pytest.raises(BrainError) as error:
            restored.backup_brain(
                principal=limited,
                brain_id=brain_id,
                destination=tmp_path / "denied.wmb",
            )
        assert error.value.code == "not_found"
        assert not (tmp_path / "denied.wmb").exists()
        restored.backup_brain(
            principal=owner, brain_id=brain_id, destination=tmp_path / "allowed.wmb"
        )
        assert "Orchard inspection plan" not in json.dumps(
            restored.export_brain(principal=owner, brain_id=brain_id)
        )
    finally:
        restored.close()


def test_export_and_roundtrip_exceed_legacy_record_limits(
    populated_brain_fixture, tmp_path
):
    service, owner, brain_id = populated_brain_fixture
    with service.store.transaction(write=True) as conn:
        chunk = conn.execute("SELECT source_id,version_id FROM chunks").fetchone()
        conn.executemany(
            "INSERT INTO chunks(brain_id,source_id,version_id,id,ordinal,text) VALUES (?,?,?,?,?,?)",
            (
                (brain_id, chunk[0], chunk[1], f"bulk-{i}", i, f"Chunk {i}")
                for i in range(1, 100001)
            ),
        )
        claim = conn.execute("SELECT payload_json FROM claims").fetchone()[0]
        conn.executemany(
            "INSERT INTO claims(brain_id,id,kind,status,payload_json) VALUES (?,?,'goal','active',?)",
            ((brain_id, f"bulk-claim-{i}", claim) for i in range(1, 10001)),
        )
        conn.executemany(
            "INSERT INTO dependencies VALUES (?, 'claim', ?, 'source', ?, ?)",
            (
                (brain_id, f"bulk-claim-{i}", chunk[0], chunk[0])
                for i in range(1, 10001)
            ),
        )
    exported = service.export_brain(principal=owner, brain_id=brain_id)
    assert exported["counts"]["chunks"] == 100001
    assert exported["counts"]["claims"] == 10001
    assert exported["records"]["chunks"][-1]["text"] == "Chunk 100000"
    archive = tmp_path / "complete.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        restored.restore_brain(principal=owner, archive=archive)
        with restored.store.transaction() as conn:
            assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 100001
            assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 10001
    finally:
        restored.close()


def test_completed_mapping_cannot_restore_without_private_database(
    populated_brain_fixture, tmp_path
):
    service, owner, brain_id = populated_brain_fixture
    verified_runs(service, owner, brain_id)
    original, hostile = tmp_path / "original.wmb", tmp_path / "missing-private.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=original)
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(hostile, "w") as target:
        manifest = json.loads(source.read("manifest.json"))
        del manifest["files"]["brain-experience.sqlite3"]
        manifest["private_state"] = "unused_or_purged"
        target.writestr("manifest.json", json.dumps(manifest))
        target.writestr("brain.sqlite3", source.read("brain.sqlite3"))
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        with pytest.raises(BrainError) as error:
            restored.restore_brain(
                principal=owner,
                archive=hostile,
                current_state_dir=service.store.path.parent,
            )
        assert error.value.code == "invalid_archive"
        assert restored.list_brains(principal=owner) == []
    finally:
        restored.close()


def test_archive_tombstone_prevents_quarantine_content_recovery(
    populated_brain_fixture, tmp_path
):
    from uuid import uuid4

    service, owner, brain_id = populated_brain_fixture
    source = service.list_sources(principal=owner, brain_id=brain_id)[0]
    original, hostile = tmp_path / "original.wmb", tmp_path / "tombstone.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=original)
    rewrite_archive(
        original,
        hostile,
        tmp_path,
        sql=[
            (
                "INSERT INTO tombstones(brain_id,id,kind,record_id,revision,created_at) VALUES (?,?,'source_deleted',?,1,0)",
                (brain_id, uuid4().hex, source["id"]),
            )
        ],
    )
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        restored.restore_brain(principal=owner, archive=hostile)
        assert (
            restored.review_restored_source(
                principal=owner, brain_id=brain_id, source_id=source["id"]
            )["citations"]
            == []
        )
        assert (
            restored.list_managed_sources(principal=owner, brain_id=brain_id)[
                "sources"
            ][0]["status"]
            == "deleted"
        )
    finally:
        restored.close()


@pytest.mark.parametrize(
    "checkpoint", ["before_private", "after_private", "purge_pending", "purged"]
)
def test_snapshot_preserves_durable_pending_and_purged_lineage(
    populated_brain_fixture, tmp_path, monkeypatch, checkpoint
):
    service, owner, brain_id = populated_brain_fixture
    if checkpoint == "before_private":
        original_drain = service.drain_outbox
        monkeypatch.setattr(
            service, "drain_outbox", lambda **kw: {"completed": 0, "pending": 1}
        )
        verified_runs(service, owner, brain_id, count=1)
        monkeypatch.setattr(service, "drain_outbox", original_drain)
        assert not service.experience.private.path.exists()
    elif checkpoint == "after_private":
        original_ack = service.experience._acknowledge
        monkeypatch.setattr(
            service.experience,
            "_acknowledge",
            lambda *args: (_ for _ in ()).throw(OSError("after private commit")),
        )
        verified_runs(service, owner, brain_id, count=1)
        monkeypatch.setattr(service.experience, "_acknowledge", original_ack)
        assert len(service.experience.private.store.candidate_validations()) == 1
    else:
        verified_runs(service, owner, brain_id)
        origin = service.list_sources(principal=owner, brain_id=brain_id)[0]["id"]
        service.set_source_access(
            principal=owner, brain_id=brain_id, source_id=origin, readers=[]
        )
        service.set_source_access(
            principal=owner, brain_id=brain_id, source_id=origin, readers=None
        )
        if checkpoint == "purged":
            service.drain_outbox()
    with service.store.transaction() as conn:
        pending = {
            r[0] for r in conn.execute("SELECT id FROM outbox WHERE status='pending'")
        }
        reservations = conn.execute(
            "SELECT COUNT(*) FROM brain_experience_evidence"
        ).fetchone()[0]
    archive = tmp_path / "pending.wmb"
    result = service.backup_brain(
        principal=owner, brain_id=brain_id, destination=archive
    )
    assert set(result["pending_ids"]) == pending
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        result = restored.restore_brain(
            principal=owner,
            archive=archive,
            current_state_dir=service.store.path.parent,
        )
        assert result["current_history_verified"] is True
        with restored.store.transaction() as conn:
            assert {
                r[0]
                for r in conn.execute("SELECT id FROM outbox WHERE status='pending'")
            } == pending
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM brain_experience_evidence"
                ).fetchone()[0]
                == reservations
            )
        assert restored.drain_outbox()["pending"] == 0
        if checkpoint.startswith("purge"):
            assert (
                restored.review_experience(principal=owner, brain_id=brain_id)[
                    "procedures"
                ]
                == []
            )
            with restored.store.transaction() as conn:
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM brain_experience_links"
                    ).fetchone()[0]
                    == 0
                )
        else:
            assert len(restored.experience.private.store.candidate_validations()) == 1
        assert restored.drain_outbox() == {"completed": 0, "pending": 0}
    finally:
        restored.close()


def test_legacy_restore_refuses_brain_targets(populated_brain_fixture, tmp_path):
    from wavemind import HashingTextEncoder, SQLiteExperienceStore, WaveMind
    from wavemind.product_backup import (
        ProductBackupError,
        create_product_backup,
        restore_product_backup,
    )
    from wavemind.upgrade import (
        UpgradeBlocked,
        UpgradeOptions,
        create_upgrade_backup,
        restore_upgrade_backup,
    )

    service, _, _ = populated_brain_fixture
    old_profile = tmp_path / "legacy"
    old_profile.mkdir()
    mind = WaveMind(
        db_path=old_profile / "core.sqlite3", encoder=HashingTextEncoder(vector_dim=32)
    )
    product = tmp_path / "legacy.zip"
    try:
        with SQLiteExperienceStore(old_profile / "experience.sqlite3") as private:
            create_product_backup(mind, private, product)
    finally:
        mind.close()
    target = service.store.path.parent
    with pytest.raises(ProductBackupError, match="Brain"):
        restore_product_backup(
            product,
            core_destination=target / "core.sqlite3",
            experience_destination=target / "experience.sqlite3",
        )
    assert not (target / "core.sqlite3").exists()
    upgrade_file = tmp_path / "upgrade.zip"
    create_upgrade_backup(
        UpgradeOptions(
            core_db=old_profile / "core.sqlite3",
            experience_db=old_profile / "experience.sqlite3",
        ),
        upgrade_file,
        source_version="1.0.0",
        target_version="1.1.0",
    )
    added_brain = BrainService(old_profile)
    try:
        with pytest.raises(UpgradeBlocked, match="Brain"):
            restore_upgrade_backup(upgrade_file)
    finally:
        added_brain.close()


@pytest.mark.parametrize(
    "limit",
    [
        "MAX_ARCHIVE_BYTES",
        "MAX_EXPANDED_BYTES",
        "MAX_DATABASE_BYTES",
        "MAX_MANIFEST_BYTES",
    ],
)
def test_archive_byte_bounds_reject_before_activation(
    populated_brain_fixture, tmp_path, monkeypatch, limit
):
    from wavemind.brain import portability_archive

    service, owner, brain_id = populated_brain_fixture
    archive = tmp_path / "backup.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        monkeypatch.setattr(portability_archive, limit, 1)
        with pytest.raises(BrainError) as error:
            restored.restore_brain(principal=owner, archive=archive)
        assert error.value.code == "invalid_archive"
        assert restored.list_brains(principal=owner) == []
    finally:
        restored.close()


def test_snapshot_blocks_cross_process_authority_writer(
    populated_brain_fixture, tmp_path, monkeypatch
):
    from wavemind.brain import portability_archive

    service, owner, brain_id = populated_brain_fixture
    original = portability_archive.write_authority
    observations = []

    def checked_projection(path, data):
        code = """
import sqlite3,sys
c=sqlite3.connect(sys.argv[1],timeout=0.1)
try:
 c.execute('BEGIN IMMEDIATE')
 print('WRITER ACQUIRED')
except sqlite3.OperationalError:
 print('writer blocked')
finally:
 c.close()
"""
        process = subprocess.run(
            [sys.executable, "-c", code, str(service.store.path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        observations.append(process.stdout.strip())
        return original(path, data)

    monkeypatch.setattr(portability_archive, "write_authority", checked_projection)
    service.backup_brain(
        principal=owner, brain_id=brain_id, destination=tmp_path / "locked.wmb"
    )
    assert observations == ["writer blocked"]


def test_admission_reports_remaining_cleanup_beyond_one_drain_batch(
    populated_brain_fixture, tmp_path
):
    service, owner, brain_id = populated_brain_fixture
    source_id = service.list_sources(principal=owner, brain_id=brain_id)[0]["id"]
    for _ in range(101):
        service.set_source_access(
            principal=owner, brain_id=brain_id, source_id=source_id, readers=None
        )
    archive = tmp_path / "pending.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        restored.restore_brain(principal=owner, archive=archive)
        result = restored.admit_restored_sources(
            principal=owner, brain_id=brain_id, source_ids=[source_id]
        )
        with restored.store.transaction() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM outbox WHERE status='pending'"
                ).fetchone()[0]
                > 0
            )
        assert result["private_cleanup"] == "pending"
    finally:
        restored.close()


def test_preview_drafts_are_not_portable_and_repreview_deduplicates(
    populated_brain_fixture, tmp_path
):
    service, owner, brain_id = populated_brain_fixture
    source_id = service.list_sources(principal=owner, brain_id=brain_id)[0]["id"]
    service.set_member(
        principal=owner, brain_id=brain_id, identity="creator", role="editor"
    )
    service.preview_import(
        principal=Principal("creator"),
        brain_id=brain_id,
        files=[{"name": "draft.md", "content": b"OTHER_CREATOR_UNCOMMITTED_SENTINEL"}],
    )
    old_preview = service.preview_import(
        principal=owner,
        brain_id=brain_id,
        files=[{"name": "plan.md", "content": b"Orchard inspection plan"}],
    )
    archive = tmp_path / "backup.wmb"
    backup = service.backup_brain(
        principal=owner, brain_id=brain_id, destination=archive
    )
    assert "import_previews_not_restored" in backup["warnings"]
    with zipfile.ZipFile(archive) as opened:
        assert (
            "import_previews_not_restored"
            in json.loads(opened.read("manifest.json"))["warnings"]
        )
        assert all(
            b"OTHER_CREATOR_UNCOMMITTED_SENTINEL" not in opened.read(name)
            for name in opened.namelist()
        )
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        result = restored.restore_brain(
            principal=owner,
            archive=archive,
            current_state_dir=service.store.path.parent,
        )
        assert "import_previews_not_restored" in result["warnings"]
        with pytest.raises(BrainError) as error:
            restored.commit_import(
                principal=owner,
                brain_id=brain_id,
                preview_id=old_preview["id"],
                accepted_ids=[old_preview["files"][0]["id"]],
            )
        assert error.value.code == "not_found"
        repeated = import_text(restored, owner, brain_id)
        assert repeated["id"] == source_id
        assert repeated["version"] == 1
        with restored.store.transaction() as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0] == 1
            )
    finally:
        restored.close()


def test_current_history_pending_gate_survives_restore_and_restart(
    populated_brain_fixture, tmp_path
):
    from wavemind.brain.sources import mark_context_pending
    from wavemind.brain.store import record_change

    service, owner, brain_id = populated_brain_fixture
    verified_runs(service, owner, brain_id)
    archive = tmp_path / "before-pending.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    with service.store.transaction(write=True) as conn:
        mark_context_pending(conn, brain_id=brain_id, reason="dependency_limit")
        record_change(
            conn, brain_id=brain_id, kind="context_pending", record_id=brain_id
        )
    current = service.build_context(
        principal=owner, brain_id=brain_id, question="orchard"
    )
    assert current["coverage"]["status"] == "pending"
    assert current["claims"] == current["experiences"] == []
    profile = tmp_path / "restored"
    restored = BrainService(profile, bootstrap_owner=owner.identity)
    try:
        result = restored.restore_brain(
            principal=owner,
            archive=archive,
            current_state_dir=service.store.path.parent,
        )
        assert result["current_history_verified"] is True
        packet = restored.build_context(
            principal=owner, brain_id=brain_id, question="orchard"
        )
        assert packet["coverage"]["status"] == "pending"
        assert packet["claims"] == packet["experiences"] == []
    finally:
        restored.close()
    reopened = BrainService(profile)
    try:
        packet = reopened.build_context(
            principal=owner, brain_id=brain_id, question="orchard"
        )
        assert packet["coverage"]["status"] == "pending"
        assert packet["claims"] == packet["experiences"] == []
        assert (
            reopened.recheck_dependencies(principal=owner, brain_id=brain_id)["pending"]
            is False
        )
        assert (
            reopened.build_context(
                principal=owner, brain_id=brain_id, question="orchard"
            )["coverage"]["status"]
            != "pending"
        )
    finally:
        reopened.close()


@pytest.mark.parametrize("action", ["revoke", "delete"])
def test_shared_scope_pending_cleanup_backup_preserves_permitted_history(
    populated_brain_fixture, tmp_path, action, monkeypatch
):
    service, owner, brain_id = populated_brain_fixture
    verified_runs(service, owner, brain_id)
    with service.store.transaction() as conn:
        newest = conn.execute(
            "SELECT id,payload_json FROM outcomes ORDER BY created_at DESC,id DESC LIMIT 1"
        ).fetchone()
        newest_id = newest["id"]
        citation_id = json.loads(newest["payload_json"])["verification"][
            "evidence_citation_ids"
        ][0]
    evidence_source = service.read_citation(
        principal=owner, brain_id=brain_id, citation_id=citation_id
    )["source_id"]
    with monkeypatch.context() as patch:
        if action == "delete":

            def unavailable_disk(_):
                raise OSError("private cleanup unavailable")

            patch.setattr(service.experience.private, "purge", unavailable_disk)
        changed = service.change_source(
            principal=owner, brain_id=brain_id, source_id=evidence_source, action=action
        )
        if action == "delete":
            assert changed["private_cleanup"] == "pending"
    with service.store.transaction() as conn:
        originals = {
            row["id"]: json.loads(row["payload_json"])
            for row in conn.execute("SELECT id,payload_json FROM outcomes")
        }
        pending_ids = {
            row[0]
            for row in conn.execute("SELECT id FROM outbox WHERE status='pending'")
        }
        replay = [
            tuple(r)
            for r in conn.execute(
                "SELECT * FROM brain_experience_evidence ORDER BY key"
            )
        ]
    assert len(pending_ids) == 1
    archive = tmp_path / "pending-cleanup.wmb"
    backup = service.backup_brain(
        principal=owner, brain_id=brain_id, destination=archive
    )
    assert set(backup["pending_ids"]) == pending_ids
    assert "private_cleanup_pending" in backup["warnings"]
    with service.store.transaction() as conn:
        assert {
            row["id"]: json.loads(row["payload_json"])
            for row in conn.execute("SELECT id,payload_json FROM outcomes")
        } == originals
    with zipfile.ZipFile(archive) as opened:
        assert all(
            b"Independent successful inspection 2" not in opened.read(name)
            for name in opened.namelist()
        )
    profile = tmp_path / "restored"
    restored = BrainService(profile, bootstrap_owner=owner.identity)
    try:
        result = restored.restore_brain(principal=owner, archive=archive)
        assert "private_cleanup_pending" in result["warnings"]
        with restored.store.transaction() as conn:
            for row in conn.execute("SELECT id,status,payload_json FROM outcomes"):
                data = json.loads(row["payload_json"])
                if row["id"] == newest_id:
                    assert data == {}
                    assert row["status"] == "revoked"
                else:
                    assert row["status"] == "verified"
                    assert data == {
                        **originals[row["id"]],
                        "integration_status": "cleanup_pending",
                    }
            assert {
                r[0]
                for r in conn.execute("SELECT id FROM outbox WHERE status='pending'")
            } == pending_ids
            assert [
                tuple(r)
                for r in conn.execute(
                    "SELECT * FROM brain_experience_evidence ORDER BY key"
                )
            ] == replay
    finally:
        restored.close()
    reopened = BrainService(profile)
    try:
        pending_backup = reopened.backup_brain(
            principal=owner,
            brain_id=brain_id,
            destination=tmp_path / "still-pending.wmb",
        )
        assert "private_cleanup_pending" in pending_backup["warnings"]
        assert reopened.drain_outbox()["pending"] == 0
        with reopened.store.transaction() as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM brain_experience_links").fetchone()[
                    0
                ]
                == 0
            )
            assert [
                tuple(r)
                for r in conn.execute(
                    "SELECT * FROM brain_experience_evidence ORDER BY key"
                )
            ] == replay
            for row in conn.execute(
                "SELECT id,payload_json FROM outcomes WHERE payload_json!='{}'"
            ):
                assert json.loads(row["payload_json"]) == {
                    **originals[row["id"]],
                    "integration_status": "purged",
                }
        assert reopened.experience.private.store.candidate_validations() == []
        drained_backup = reopened.backup_brain(
            principal=owner, brain_id=brain_id, destination=tmp_path / "drained.wmb"
        )
        assert "private_cleanup_pending" not in drained_backup["warnings"]
        with zipfile.ZipFile(archive) as opened:
            # An immutable old manifest describes its snapshot, not live state.
            assert (
                "private_cleanup_pending"
                in json.loads(opened.read("manifest.json"))["warnings"]
            )
    finally:
        reopened.close()


def test_archive_pending_gate_and_semantic_recheck_are_not_cleared(
    populated_brain_fixture, tmp_path
):
    from wavemind.brain.sources import mark_context_pending

    service, owner, brain_id = populated_brain_fixture
    source_id = service.list_sources(principal=owner, brain_id=brain_id)[0]["id"]
    preview = service.preview_import(
        principal=owner,
        brain_id=brain_id,
        files=[
            {
                "name": "plan.md",
                "source_id": source_id,
                "content": b"Updated orchard plan",
            }
        ],
    )
    service.commit_import(
        principal=owner,
        brain_id=brain_id,
        preview_id=preview["id"],
        accepted_ids=[preview["files"][0]["id"]],
    )
    with service.store.transaction(write=True) as conn:
        mark_context_pending(conn, brain_id=brain_id)
    archive = tmp_path / "pending.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    assert (
        service.recheck_dependencies(principal=owner, brain_id=brain_id)["pending"]
        is False
    )
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        restored.restore_brain(
            principal=owner,
            archive=archive,
            current_state_dir=service.store.path.parent,
        )
        assert (
            restored.build_context(
                principal=owner, brain_id=brain_id, question="orchard"
            )["coverage"]["status"]
            == "pending"
        )
        assert (
            restored.recheck_dependencies(principal=owner, brain_id=brain_id)["pending"]
            is False
        )
        with restored.store.transaction() as conn:
            row = conn.execute(
                "SELECT status,payload_json FROM claims WHERE id='inspection'"
            ).fetchone()
            assert row["status"] == "proposed"
            assert json.loads(row["payload_json"])["needs_recheck"] is True
        assert (
            restored.build_context(
                principal=owner, brain_id=brain_id, question="orchard"
            )["claims"]
            == []
        )
    finally:
        restored.close()


def test_current_semantic_recheck_restriction_survives_stale_archive(
    populated_brain_fixture, tmp_path
):
    service, owner, brain_id = populated_brain_fixture
    archive = tmp_path / "before-recheck.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    source_id = service.list_sources(principal=owner, brain_id=brain_id)[0]["id"]
    preview = service.preview_import(
        principal=owner,
        brain_id=brain_id,
        files=[
            {
                "name": "plan.md",
                "source_id": source_id,
                "content": b"Updated orchard plan",
            }
        ],
    )
    service.commit_import(
        principal=owner,
        brain_id=brain_id,
        preview_id=preview["id"],
        accepted_ids=[preview["files"][0]["id"]],
    )
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        restored.restore_brain(
            principal=owner,
            archive=archive,
            current_state_dir=service.store.path.parent,
        )
        with restored.store.transaction() as conn:
            row = conn.execute(
                "SELECT status,payload_json FROM claims WHERE id='inspection'"
            ).fetchone()
            assert json.loads(row["payload_json"]).get("needs_recheck") is True
            assert row["status"] == "proposed"
    finally:
        restored.close()


@pytest.mark.parametrize(
    "action,mutation",
    [
        ("revoke", "UPDATE outbox SET status='completed' WHERE kind='source_revoked'"),
        (
            "revoke",
            "DELETE FROM brain_experience_links WHERE outcome_id IN (SELECT id FROM outcomes WHERE status='revoked')",
        ),
        ("revoke", "UPDATE sources SET status='active' WHERE status='revoked'"),
        (
            "revoke",
            "DELETE FROM dependencies WHERE dependent_type='outcome' AND source_id IN (SELECT id FROM sources WHERE status='revoked')",
        ),
        ("delete", "DELETE FROM tombstones WHERE kind='source_deleted'"),
    ],
)
def test_cleanup_pending_label_requires_real_same_scope_maintenance(
    populated_brain_fixture, tmp_path, action, mutation, monkeypatch
):
    service, owner, brain_id = populated_brain_fixture
    verified_runs(service, owner, brain_id)
    with service.store.transaction() as conn:
        latest = json.loads(
            conn.execute(
                "SELECT payload_json FROM outcomes ORDER BY created_at DESC,id DESC LIMIT 1"
            ).fetchone()[0]
        )
    citation = latest["verification"]["evidence_citation_ids"][0]
    source = service.read_citation(
        principal=owner, brain_id=brain_id, citation_id=citation
    )["source_id"]
    with monkeypatch.context() as patch:
        if action == "delete":

            def unavailable_disk(_):
                raise OSError("private cleanup unavailable")

            patch.setattr(service.experience.private, "purge", unavailable_disk)
        service.change_source(
            principal=owner, brain_id=brain_id, source_id=source, action=action
        )
    archive, invalid = tmp_path / "pending.wmb", tmp_path / "invalid.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    rewrite_archive(archive, invalid, tmp_path, sql=[(mutation, ())])
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    try:
        with pytest.raises(BrainError) as error:
            restored.restore_brain(principal=owner, archive=invalid)
        assert error.value.code == "invalid_archive"
        assert restored.list_brains(principal=owner) == []
        assert not restored.experience.private.path.exists()
    finally:
        restored.close()


def test_cleanup_snapshot_preserves_unrelated_scope_and_allows_fresh_learning(
    populated_brain_fixture, tmp_path
):
    from wavemind.brain.portability_archive import private_rows

    service, owner, brain_id = populated_brain_fixture
    verified_runs(service, owner, brain_id, start=10, procedure="Water orchard")
    with service.store.transaction() as conn:
        unrelated_links = [
            tuple(r)
            for r in conn.execute("SELECT * FROM brain_experience_links ORDER BY rowid")
        ]
        unrelated_namespace = conn.execute(
            "SELECT namespace FROM brain_experience_links LIMIT 1"
        ).fetchone()[0]
    verified_runs(service, owner, brain_id)
    private_before = private_rows(
        service.experience.private.store.conn, {unrelated_namespace}
    )
    with service.store.transaction() as conn:
        latest = json.loads(
            conn.execute(
                "SELECT payload_json FROM outcomes ORDER BY created_at DESC,id DESC LIMIT 1"
            ).fetchone()[0]
        )
        old_outcomes = {r[0] for r in conn.execute("SELECT id FROM outcomes")}
        replay = {
            tuple(r) for r in conn.execute("SELECT * FROM brain_experience_evidence")
        }
    source = service.read_citation(
        principal=owner,
        brain_id=brain_id,
        citation_id=latest["verification"]["evidence_citation_ids"][0],
    )["source_id"]
    service.change_source(
        principal=owner, brain_id=brain_id, source_id=source, action="revoke"
    )
    live_export = service.export_brain(principal=owner, brain_id=brain_id)
    assert "cleanup_pending" not in json.dumps(live_export)
    archive = tmp_path / "pending.wmb"
    service.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    profile = tmp_path / "restored"
    restored = BrainService(profile, bootstrap_owner=owner.identity)
    restored.restore_brain(principal=owner, archive=archive)
    restored.close()
    restored = BrainService(profile)
    try:
        assert (
            private_rows(restored.experience.private.store.conn, {unrelated_namespace})
            == private_before
        )
        assert restored.drain_outbox()["pending"] == 0
        assert (
            private_rows(restored.experience.private.store.conn, {unrelated_namespace})
            == private_before
        )
        with restored.store.transaction() as conn:
            assert [
                tuple(r)
                for r in conn.execute(
                    "SELECT * FROM brain_experience_links ORDER BY rowid"
                )
            ] == unrelated_links
            assert {
                tuple(r)
                for r in conn.execute("SELECT * FROM brain_experience_evidence")
            } == replay
        sources = restored.list_managed_sources(principal=owner, brain_id=brain_id)[
            "sources"
        ]
        restored.admit_restored_sources(
            principal=owner,
            brain_id=brain_id,
            source_ids=[r["id"] for r in sources if r["status"] == "quarantined"],
        )
        restored.review_claims(
            principal=owner,
            brain_id=brain_id,
            claim_ids=["inspection"],
            action="recheck",
        )
        restored.recheck_dependencies(principal=owner, brain_id=brain_id)
        verified_runs(restored, owner, brain_id, count=1, start=20)
        procedures = restored.review_experience(principal=owner, brain_id=brain_id)[
            "procedures"
        ]
        assert len(procedures) == 1
        assert (
            procedures[0]["status"] == "shadow" and procedures[0]["eligible"] is False
        )
        assert not old_outcomes.intersection(procedures[0]["outcome_ids"])
        verified_runs(restored, owner, brain_id, count=2, start=21)
        procedures = restored.review_experience(principal=owner, brain_id=brain_id)[
            "procedures"
        ]
        assert len(procedures) == 1 and procedures[0]["eligible"] is True
        assert not old_outcomes.intersection(procedures[0]["outcome_ids"])
        assert len(restored.experience.private.store.candidate_validations()) == 3
        with restored.store.transaction() as conn:
            assert replay <= {
                tuple(r)
                for r in conn.execute("SELECT * FROM brain_experience_evidence")
            }
    finally:
        restored.close()
