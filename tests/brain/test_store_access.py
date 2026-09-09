"""Behavioral checks for persistence, transaction isolation and exact rights."""

import dataclasses
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest


def make_service(tmp_path):
    from wavemind.brain.models import Principal
    from wavemind.brain.service import BrainService

    service = BrainService(tmp_path)
    owner = Principal("owner")
    brain = service.create_brain(principal=owner, title="Project", mode="personal")
    return service, owner, brain["id"]


def add_source(service, brain_id, source_id, *, status="active", readers=None):
    # Task 1 deliberately has no import API yet. Insert real source rows using
    # its production schema; subsequent assertions use the authority itself.
    with service.store.transaction(write=True) as conn:
        conn.execute(
            "INSERT INTO sources(brain_id,id,status,readers_json) VALUES (?,?,?,?)",
            (
                brain_id,
                source_id,
                status,
                None if readers is None else json.dumps(readers),
            ),
        )


def test_restart_membership_is_exact_and_readers_cannot_grant(tmp_path):
    from wavemind.brain.models import BrainError, Principal
    from wavemind.brain.service import BrainService

    service, owner, brain_id = make_service(tmp_path)
    service.set_member(
        principal=owner, brain_id=brain_id, identity="guest", role="reader"
    )
    service.close()
    service = BrainService(tmp_path)
    try:
        assert service.list_brains(principal=Principal("guest")) == [
            {
                "id": brain_id,
                "title": "Project",
                "mode": "personal",
                "owner": "owner",
                "revision": 2,
            }
        ]
        with pytest.raises(BrainError) as error:
            service.set_member(
                principal=Principal("guest"),
                brain_id=brain_id,
                identity="intruder",
                role="owner",
            )
        assert error.value.code == "not_found"
        assert service.list_brains(principal=Principal("guest-prefix")) == []
        service.set_member(
            principal=owner, brain_id=brain_id, identity="guest", role=None
        )
        assert service.list_brains(principal=Principal("guest")) == []
    finally:
        service.close()


def test_isolated_schema_reopens_without_creating_generic_databases(tmp_path):
    from wavemind.brain.store import BrainStore

    service, owner, brain_id = make_service(tmp_path)
    assert service.list_brains(principal=owner)[0]["id"] == brain_id
    service.close()
    assert {path.name for path in tmp_path.iterdir()} == {"brain.sqlite3"}
    store = BrainStore(tmp_path)
    try:
        with store.transaction() as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert {
                "brains",
                "members",
                "sources",
                "source_versions",
                "chunks",
                "previews",
                "entities",
                "claims",
                "relations",
                "dependencies",
                "packets",
                "receipts",
                "outcomes",
                "outbox",
                "tombstones",
                "audit",
            } <= tables
            assert (
                conn.execute(
                    "SELECT revision FROM brains WHERE id=?", (brain_id,)
                ).fetchone()[0]
                == 1
            )
    finally:
        store.close()


def test_principal_is_frozen_and_copies_mutable_grants():
    from wavemind.brain.models import Principal

    ids, operations = {"exact"}, {"read"}
    principal = Principal("agent", "agent", ids, operations)
    ids.add("other")
    operations.add("manage_access")
    assert principal.brain_ids == frozenset({"exact"})
    assert principal.operations == frozenset({"read"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        principal.identity = "owner"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"identity": ""},
        {"identity": " "},
        {"identity": "x" * 257},
        {"identity": 5},
        {"identity": "a\x00b"},
        {"identity": "a", "kind": "owner"},
        {"identity": "a", "brain_ids": "brain"},
        {"identity": "a", "operations": frozenset({"unknown"})},
    ],
)
def test_invalid_principal_is_rejected(kwargs):
    from wavemind.brain.models import BrainError, Principal

    with pytest.raises(BrainError):
        Principal(**kwargs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", ""),
        ("title", " "),
        ("title", "x" * 501),
        ("title", 1),
        ("mode", "shared"),
        ("mode", None),
    ],
)
def test_invalid_brain_does_not_write(tmp_path, field, value):
    from wavemind.brain.models import BrainError, Principal
    from wavemind.brain.service import BrainService

    service = BrainService(tmp_path)
    try:
        with pytest.raises(BrainError):
            service.create_brain(
                principal=Principal("owner"),
                **{field: value, **({"title": "ok"} if field != "title" else {})},
            )
        assert service.list_brains(principal=Principal("owner")) == []
    finally:
        service.close()


def test_no_scope_or_operation_grant_creates_membership(tmp_path):
    from wavemind.brain.access import require_access
    from wavemind.brain.models import BrainError, Principal

    service, owner, brain_id = make_service(tmp_path)
    try:
        stranger = Principal("stranger", brain_ids={brain_id}, operations={"read"})
        assert service.list_brains(principal=stranger) == []
        with service.store.transaction() as conn:
            with pytest.raises(BrainError) as missing:
                require_access(conn, stranger, brain_id, "read")
            with pytest.raises(BrainError) as nonexistent:
                require_access(conn, owner, "unknown", "read")
        assert (missing.value.code, str(missing.value)) == (
            nonexistent.value.code,
            str(nonexistent.value),
        )
        assert (
            service.list_brains(
                principal=Principal("owner", brain_ids={brain_id + "prefix"})
            )
            == []
        )
        assert service.list_brains(principal=Principal("owner", operations=set())) == []
    finally:
        service.close()


@pytest.mark.parametrize(
    "role,allowed",
    [
        (
            "owner",
            {
                "read",
                "import",
                "propose",
                "review",
                "record_outcome",
                "verify_outcome",
                "manage_access",
                "delete",
                "export",
                "restore",
            },
        ),
        ("editor", {"read", "import", "propose", "record_outcome"}),
        ("reader", {"read"}),
    ],
)
def test_live_human_role_operation_matrix(tmp_path, role, allowed):
    from wavemind.brain.access import require_access
    from wavemind.brain.models import BrainError, Principal

    service, owner, brain_id = make_service(tmp_path)
    try:
        service.set_member(
            principal=owner, brain_id=brain_id, identity="member", role=role
        )
        with service.store.transaction() as conn:
            for operation in (
                "read",
                "import",
                "propose",
                "review",
                "record_outcome",
                "verify_outcome",
                "manage_access",
                "delete",
                "export",
                "restore",
                "unknown",
            ):
                if operation in allowed:
                    require_access(conn, Principal("member"), brain_id, operation)
                else:
                    with pytest.raises(BrainError) as error:
                        require_access(conn, Principal("member"), brain_id, operation)
                    assert error.value.code == "not_found"
    finally:
        service.close()


@pytest.mark.parametrize(
    "brain_grant,operation_grant",
    [
        (None, None),
        (None, {"read"}),
        (set(), {"read"}),
        ("exact", None),
        ("exact", set()),
    ],
)
def test_agents_without_complete_grants_fail_closed(
    tmp_path, brain_grant, operation_grant
):
    from wavemind.brain.models import BrainError, Principal

    service, owner, brain_id = make_service(tmp_path)
    try:
        with pytest.raises(BrainError):
            principal = Principal(
                "owner",
                "agent",
                {brain_id} if brain_grant == "exact" else brain_grant,
                operation_grant,
            )
            service.create_brain(principal=principal, title="Agent-created")
        assert len(service.list_brains(principal=owner)) == 1
    finally:
        service.close()


def test_agent_grants_never_approve_trust_delete_or_grant(tmp_path):
    from wavemind.brain.access import require_access
    from wavemind.brain.models import BrainError, Principal

    service, owner, brain_id = make_service(tmp_path)
    operations = {
        "read",
        "import",
        "propose",
        "record_outcome",
        "review",
        "verify_outcome",
        "delete",
        "manage_access",
        "restore",
        "export",
    }
    try:
        principal = Principal("owner", "agent", {brain_id}, operations)
        with service.store.transaction() as conn:
            for operation in ("read", "import", "propose", "record_outcome", "export"):
                require_access(conn, principal, brain_id, operation)
            for operation in (
                "review",
                "verify_outcome",
                "delete",
                "manage_access",
                "restore",
            ):
                with pytest.raises(BrainError):
                    require_access(conn, principal, brain_id, operation)
        with pytest.raises(BrainError):
            service.create_brain(principal=principal, title="Agent-created")
        assert (
            service.list_brains(
                principal=Principal("owner", "agent", {brain_id + "suffix"}, {"read"})
            )
            == []
        )
        assert len(service.list_brains(principal=owner)) == 1
    finally:
        service.close()


def test_source_acl_is_exact_all_dependencies_required_and_live(tmp_path):
    from wavemind.brain.access import allowed_sources, require_access
    from wavemind.brain.models import BrainError, Principal

    service, owner, brain_id = make_service(tmp_path)
    guest = Principal("guest")
    try:
        other = service.create_brain(principal=owner, title="Other")["id"]
        service.set_member(
            principal=owner, brain_id=brain_id, identity="guest", role="reader"
        )
        add_source(service, brain_id, "public")
        add_source(service, brain_id, "restricted", readers=["guest-prefix"])
        add_source(service, other, "foreign")
        with service.store.transaction() as conn:
            assert allowed_sources(conn, guest, brain_id) == {"public"}
            assert allowed_sources(conn, owner, brain_id) == {"public", "restricted"}
            require_access(conn, guest, brain_id, "read", ("public",))
            for ids in (("public", "restricted"), ("foreign",), ("public-prefix",)):
                with pytest.raises(BrainError) as error:
                    require_access(conn, guest, brain_id, "read", ids)
                assert error.value.code == "not_found"
        service.set_source_access(
            principal=owner,
            brain_id=brain_id,
            source_id="restricted",
            readers=["guest"],
        )
        with service.store.transaction() as conn:
            require_access(conn, guest, brain_id, "read", ("public", "restricted"))
        service.set_source_access(
            principal=owner, brain_id=brain_id, source_id="restricted", readers=[]
        )
        service.close()
        from wavemind.brain.service import BrainService

        service = BrainService(tmp_path)
        with service.store.transaction() as conn:
            assert allowed_sources(conn, guest, brain_id) == {"public"}
        service.set_source_access(
            principal=owner, brain_id=brain_id, source_id="restricted", readers=None
        )
        with service.store.transaction() as conn:
            assert allowed_sources(conn, guest, brain_id) == {"public", "restricted"}
        service.set_member(
            principal=owner, brain_id=brain_id, identity="guest", role=None
        )
        with service.store.transaction() as conn:
            with pytest.raises(BrainError):
                allowed_sources(conn, guest, brain_id)
    finally:
        service.close()


@pytest.mark.parametrize("status", ["revoked", "quarantined", "deleted"])
def test_unreadable_source_states_block_even_owner(tmp_path, status):
    from wavemind.brain.access import allowed_sources, require_access
    from wavemind.brain.models import BrainError

    service, owner, brain_id = make_service(tmp_path)
    try:
        add_source(service, brain_id, "source", status=status)
        with service.store.transaction() as conn:
            assert allowed_sources(conn, owner, brain_id) == set()
            with pytest.raises(BrainError):
                require_access(conn, owner, brain_id, "read", ("source",))
    finally:
        service.close()


def test_paused_source_is_readable_snapshot(tmp_path):
    from wavemind.brain.access import allowed_sources, require_access

    service, owner, brain_id = make_service(tmp_path)
    try:
        add_source(service, brain_id, "snapshot", status="paused")
        with service.store.transaction() as conn:
            assert allowed_sources(conn, owner, brain_id) == {"snapshot"}
            require_access(conn, owner, brain_id, "read", ("snapshot",))
    finally:
        service.close()


def test_version_uniqueness_and_minimal_outbox_write(tmp_path):
    service, owner, brain_id = make_service(tmp_path)
    try:
        add_source(service, brain_id, "source")
        with service.store.transaction(write=True) as conn:
            conn.execute(
                "INSERT INTO source_versions(brain_id,source_id,id,version,digest) VALUES (?,?,?,?,?)",
                (brain_id, "source", "v1", 1, "digest1"),
            )
            conn.execute(
                "INSERT INTO outbox(id,brain_id,kind,status) VALUES (?,?,?,?)",
                ("job", brain_id, "sync", "pending"),
            )
        for version, digest in ((1, "digest2"), (2, "digest1")):
            with pytest.raises(sqlite3.IntegrityError):
                with service.store.transaction(write=True) as conn:
                    conn.execute(
                        "INSERT INTO source_versions(brain_id,source_id,id,version,digest) VALUES (?,?,?,?,?)",
                        (brain_id, "source", "v2", version, digest),
                    )
        with service.store.transaction() as conn:
            assert (
                conn.execute(
                    "SELECT version FROM source_versions WHERE brain_id=? AND source_id=? AND digest=?",
                    (brain_id, "source", "digest1"),
                ).fetchone()[0]
                == 1
            )
            assert (
                conn.execute(
                    "SELECT status FROM outbox WHERE brain_id=? AND id='job'",
                    (brain_id,),
                ).fetchone()[0]
                == "pending"
            )
    finally:
        service.close()


def test_invalid_acl_and_cross_brain_management_do_not_change_revision(tmp_path):
    from wavemind.brain.models import BrainError, Principal

    service, owner, brain_id = make_service(tmp_path)
    try:
        add_source(service, brain_id, "source")
        other = service.create_brain(principal=owner, title="Other")["id"]
        for readers in ("owner", [""], [5], ["x" * 257]):
            with pytest.raises(BrainError):
                service.set_source_access(
                    principal=owner,
                    brain_id=brain_id,
                    source_id="source",
                    readers=readers,
                )
        for actor, target in ((owner, other), (Principal("stranger"), brain_id)):
            with pytest.raises(BrainError) as error:
                service.set_source_access(
                    principal=actor, brain_id=target, source_id="source", readers=[]
                )
            assert error.value.code == "not_found"
        assert [b["revision"] for b in service.list_brains(principal=owner)] == [1, 1]
    finally:
        service.close()


def test_sole_owner_cannot_be_removed_and_owner_handoff_is_persistent(tmp_path):
    from wavemind.brain.models import BrainError, Principal
    from wavemind.brain.service import BrainService

    service, owner, brain_id = make_service(tmp_path)
    try:
        for role in (None, "reader", "editor", "invalid"):
            with pytest.raises(BrainError):
                service.set_member(
                    principal=owner, brain_id=brain_id, identity="owner", role=role
                )
        for identity in ("", " ", 7, "x" * 257):
            with pytest.raises(BrainError):
                service.set_member(
                    principal=owner, brain_id=brain_id, identity=identity, role="reader"
                )
        assert service.list_brains(principal=owner)[0]["revision"] == 1
        service.set_member(
            principal=owner, brain_id=brain_id, identity="successor", role="owner"
        )
        service.set_member(
            principal=owner, brain_id=brain_id, identity="owner", role=None
        )
        assert service.list_brains(principal=owner) == []
        service.close()
        service = BrainService(tmp_path)
        assert service.list_brains(principal=Principal("successor")) == [
            {
                "id": brain_id,
                "title": "Project",
                "mode": "personal",
                "owner": "successor",
                "revision": 3,
            }
        ]
    finally:
        service.close()


def test_failed_transaction_rolls_back_membership_revision_and_audit(tmp_path):
    from wavemind.brain.access import require_access
    from wavemind.brain.models import Principal
    from wavemind.brain.service import BrainService

    service, owner, brain_id = make_service(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="abort"):
            with service.store.transaction(write=True) as conn:
                require_access(conn, owner, brain_id, "manage_access")
                conn.execute(
                    "INSERT INTO members VALUES (?,?,?)", (brain_id, "guest", "reader")
                )
                conn.execute(
                    "UPDATE brains SET revision=revision+1 WHERE id=?", (brain_id,)
                )
                raise RuntimeError("abort")
        # Inject a real SQLite failure at the final mutation, after the service
        # has changed membership and revision. Every earlier write must roll back.
        with service.store.transaction(write=True) as conn:
            conn.execute(
                "CREATE TRIGGER abort_audit BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT, 'abort'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            service.set_member(
                principal=owner, brain_id=brain_id, identity="guest", role="reader"
            )
        service.close()
        service = BrainService(tmp_path)
        assert service.list_brains(principal=Principal("guest")) == []
        assert service.list_brains(principal=owner)[0]["revision"] == 1
        with service.store.transaction() as conn:
            assert conn.execute("SELECT count(*) FROM audit").fetchone()[0] == 1
    finally:
        service.close()


def test_schema_rejects_cross_brain_source_version_references(tmp_path):
    service, owner, brain_id = make_service(tmp_path)
    try:
        other = service.create_brain(principal=owner, title="Other")["id"]
        add_source(service, brain_id, "source")
        with pytest.raises(sqlite3.IntegrityError):
            with service.store.transaction(write=True) as conn:
                conn.execute(
                    "INSERT INTO source_versions(brain_id,source_id,id) VALUES (?,?,?)",
                    (other, "source", "version"),
                )
        with service.store.transaction(write=True) as conn:
            conn.execute(
                "INSERT INTO source_versions(brain_id,source_id,id) VALUES (?,?,?)",
                (brain_id, "source", "version"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            with service.store.transaction(write=True) as conn:
                conn.execute(
                    "INSERT INTO chunks(brain_id,source_id,version_id,id) VALUES (?,?,?,?)",
                    (other, "source", "version", "chunk"),
                )
    finally:
        service.close()


def test_two_store_writers_serialize_without_lost_revisions(tmp_path):
    from wavemind.brain.service import BrainService

    service, owner, brain_id = make_service(tmp_path)
    other = BrainService(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    instance.set_member,
                    principal=owner,
                    brain_id=brain_id,
                    identity=f"member-{i}",
                    role="reader",
                )
                for i, instance in enumerate((service, other))
            ]
            for future in futures:
                future.result(timeout=10)
        assert service.list_brains(principal=owner)[0]["revision"] == 3
        with service.store.transaction() as conn:
            assert {
                r[0]
                for r in conn.execute(
                    "SELECT identity FROM members WHERE brain_id=?", (brain_id,)
                )
            } == {"owner", "member-0", "member-1"}
    finally:
        service.close()
        other.close()


def test_interleaved_writer_rechecks_access_after_committed_revocation(tmp_path):
    from wavemind.brain.access import require_access
    from wavemind.brain.models import BrainError, Principal
    from wavemind.brain.service import BrainService

    service, owner, brain_id = make_service(tmp_path)
    service.set_member(
        principal=owner, brain_id=brain_id, identity="editor", role="editor"
    )
    other = BrainService(tmp_path)
    started = Event()

    def writer():
        started.set()
        with other.store.transaction(write=True) as conn:
            require_access(conn, Principal("editor"), brain_id, "propose")
            conn.execute(
                "UPDATE brains SET revision=revision+1 WHERE id=?", (brain_id,)
            )

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with service.store.transaction(write=True) as conn:
                require_access(conn, owner, brain_id, "manage_access")
                conn.execute(
                    "DELETE FROM members WHERE brain_id=? AND identity='editor'",
                    (brain_id,),
                )
                conn.execute(
                    "UPDATE brains SET revision=revision+1 WHERE id=?", (brain_id,)
                )
                future = pool.submit(writer)
                assert started.wait(5)
                assert not future.done()
            with pytest.raises(BrainError) as error:
                future.result(timeout=10)
            assert error.value.code == "not_found"
        assert service.list_brains(principal=owner)[0]["revision"] == 3
    finally:
        other.close()
        service.close()


def test_cross_process_writer_uses_sqlite_lock_and_live_rights(tmp_path):
    service, owner, brain_id = make_service(tmp_path)
    service.set_member(
        principal=owner, brain_id=brain_id, identity="guest", role="owner"
    )
    script = """
import sys
from wavemind.brain.models import BrainError, Principal
from wavemind.brain.service import BrainService
service = BrainService(sys.argv[1])
print('ready', flush=True)
try:
    service.set_member(principal=Principal('guest'), brain_id=sys.argv[2], identity='intruder', role='reader')
except BrainError as error:
    print(error.code, flush=True)
finally:
    service.close()
"""
    child = None
    try:
        # Launch before taking the write lock so schema initialization completes.
        # A separate stdin gate ensures its mutation starts while lock is held.
        script = script.replace(
            "print('ready', flush=True)",
            "print('ready', flush=True)\nsys.stdin.readline()",
        )
        child = subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path), brain_id],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert (
                pool.submit(child.stdout.readline).result(timeout=15).strip() == "ready"
            )
        with service.store.transaction(write=True) as conn:
            conn.execute(
                "DELETE FROM members WHERE brain_id=? AND identity='guest'", (brain_id,)
            )
            conn.execute(
                "UPDATE brains SET revision=revision+1 WHERE id=?", (brain_id,)
            )
            child.stdin.write("go\n")
            child.stdin.flush()
            with pytest.raises(subprocess.TimeoutExpired):
                child.wait(timeout=0.2)
        stdout, stderr = child.communicate(timeout=15)
        assert child.returncode == 0, stderr
        assert stdout.strip() == "not_found"
        assert stderr == ""
        assert service.list_brains(principal=owner)[0]["revision"] == 3
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate()
        service.close()
