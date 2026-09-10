"""Local digest-only credentials; live service membership remains authoritative.

Issuance commits pending auth, then authority grants, then active auth. A crash
never activates pending tokens. Revocation commits first; membership cleanup is
best effort. No cross-database atomicity is claimed. Locks never nest an auth
transaction inside an authority transaction.
"""

import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .access import _not_found, allowed_sources, require_access
from .models import BrainError, Principal, bounded_text
from .portability_archive import safe_path
from .sources import invalidate_source
from .store import BrainStore, record_change

AGENT_OPERATIONS = frozenset({"read", "import", "propose", "record_outcome", "export"})
SESSION_SECONDS = 3600
AGENT_SECONDS = 30 * 86400


def _digest(value):
    if not isinstance(value, str) or not 32 <= len(value) <= 256:
        raise BrainError("unauthenticated", "Authentication required.")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _unauthenticated():
    return BrainError("unauthenticated", "Authentication required.")


def _csrf(session):
    return hashlib.sha256(
        ("wavemind.brain.csrf.v1:" + session).encode("utf-8")
    ).hexdigest()


def _profile_paths(state_dir):
    path = safe_path(state_dir)
    for name in ("brain.sqlite3", "brain-experience.sqlite3", "brain-auth.sqlite3"):
        for suffix in ("", "-journal", "-wal", "-shm"):
            safe_path(path / (name + suffix))
    return path


class BrainAuth:
    def __init__(self, state_dir: Path):
        self.state_dir = _profile_paths(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = safe_path(self.state_dir / "brain-auth.sqlite3")
        with self._transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bootstrap (singleton INTEGER PRIMARY KEY CHECK(singleton=1), identity TEXT NOT NULL UNIQUE)"
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS credentials (
                id TEXT PRIMARY KEY,digest TEXT NOT NULL UNIQUE,identity TEXT NOT NULL,
                kind TEXT NOT NULL,issuer TEXT NOT NULL,label TEXT NOT NULL,
                brain_ids TEXT,operations TEXT,source_refs TEXT,status TEXT NOT NULL,
                created_at REAL NOT NULL,expires_at REAL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
                digest TEXT PRIMARY KEY,credential_id TEXT NOT NULL,csrf_digest TEXT NOT NULL,
                expires_at REAL NOT NULL,FOREIGN KEY(credential_id) REFERENCES credentials(id))""")

    @contextmanager
    def _transaction(self):
        safe_path(self.path)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @property
    def owner_identity(self):
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT identity FROM bootstrap WHERE singleton=1"
            ).fetchone()
            if row is None:
                raise BrainError(
                    "bootstrap_required", "Initialize the local owner first."
                )
            return row[0]

    def bootstrap_owner(self, *, persist=None) -> str:
        token, identity = secrets.token_urlsafe(32), "owner:" + uuid4().hex
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM bootstrap").fetchone():
                raise BrainError(
                    "already_initialized", "Local owner already initialized."
                )
            if persist is not None:
                persist(token)
            conn.execute("INSERT INTO bootstrap VALUES (1,?)", (identity,))
            conn.execute(
                "INSERT INTO credentials VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uuid4().hex,
                    _digest(token),
                    identity,
                    "human",
                    identity,
                    "Local owner",
                    None,
                    None,
                    None,
                    "active",
                    time.time(),
                    None,
                ),
            )
        return token

    def _live(self, conn, *, digest=None, token_id=None):
        row = conn.execute(
            "SELECT * FROM credentials WHERE "
            + ("digest=?" if digest is not None else "id=?"),
            (digest if digest is not None else token_id,),
        ).fetchone()
        if (
            row is None
            or row["status"] != "active"
            or (row["expires_at"] is not None and row["expires_at"] <= time.time())
        ):
            raise _unauthenticated()
        return row

    @staticmethod
    def _principal(row):
        return Principal(
            identity=row["identity"],
            kind=row["kind"],
            **{
                field: None if row[field] is None else json.loads(row[field])
                for field in ("brain_ids", "operations", "source_refs")
            },
        )

    def authenticate(self, token: str) -> Principal:
        with self._transaction() as conn:
            return self._principal(self._live(conn, digest=_digest(token)))

    def token_id(self, token: str) -> str:
        with self._transaction() as conn:
            return self._live(conn, digest=_digest(token))["id"]

    @staticmethod
    def _owners(conn, principal, brain_ids):
        if not isinstance(principal, Principal) or principal.kind != "human":
            raise _not_found()
        for brain in brain_ids:
            require_access(conn, principal, brain, "manage_access")

    def issue_agent(
        self,
        *,
        principal,
        brain_ids,
        operations,
        label,
        source_grants=None,
        grant_selected_sources=False,
    ) -> dict:
        label = bounded_text(label, maximum=128)
        if (
            not isinstance(brain_ids, list)
            or not 1 <= len(brain_ids) <= 100
            or not all(isinstance(x, str) for x in brain_ids)
            or len(set(brain_ids)) != len(brain_ids)
            or not isinstance(operations, list)
            or not operations
            or not all(isinstance(x, str) for x in operations)
            or not set(operations) <= AGENT_OPERATIONS
            or type(grant_selected_sources) is not bool
        ):
            raise BrainError("invalid_input", "Invalid agent grant.")
        brains = sorted(bounded_text(x) for x in brain_ids)
        refs = None
        if source_grants is not None:
            if (
                not isinstance(source_grants, dict)
                or not source_grants.keys() <= set(brains)
                or "import" in operations
            ):
                raise BrainError("invalid_input", "Invalid source grant.")
            refs = []
            for brain, ids in source_grants.items():
                if not isinstance(ids, list) or len(ids) > 100:
                    raise BrainError("invalid_input", "Invalid source grant.")
                refs.extend((brain, bounded_text(sid)) for sid in ids)
            refs = sorted(set(refs))
        if grant_selected_sources and not refs:
            raise BrainError(
                "invalid_input", "Select sources for the explicit access grant."
            )
        token, token_id, identity = (
            secrets.token_urlsafe(32),
            uuid4().hex,
            "agent:" + uuid4().hex,
        )
        issued = Principal(identity, "agent", brains, operations, refs)
        store = BrainStore(_profile_paths(self.state_dir))
        try:
            # Check before persisting pending metadata; recheck before grants.
            with store.transaction() as conn:
                self._owners(conn, principal, brains)
                for brain, sid in refs or []:
                    require_access(conn, principal, brain, "read", [sid])
            with self._transaction() as conn:
                conn.execute(
                    "INSERT INTO credentials VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        token_id,
                        _digest(token),
                        identity,
                        "agent",
                        principal.identity,
                        label,
                        json.dumps(brains),
                        json.dumps(sorted(set(operations))),
                        None if refs is None else json.dumps(refs),
                        "pending",
                        time.time(),
                        time.time() + AGENT_SECONDS,
                    ),
                )
            with store.transaction(write=True) as conn:
                self._owners(conn, principal, brains)
                for brain, sid in refs or []:
                    require_access(conn, principal, brain, "read", [sid])
                for brain in brains:
                    conn.execute(
                        "INSERT INTO members VALUES (?,?,'editor')", (brain, identity)
                    )
                    record_change(
                        conn,
                        brain_id=brain,
                        kind="agent_member_set",
                        record_id=token_id,
                    )
                if grant_selected_sources:
                    for brain, sid in refs:
                        row = conn.execute(
                            "SELECT readers_json FROM sources WHERE brain_id=? AND id=?",
                            (brain, sid),
                        ).fetchone()
                        if row[0] is not None:
                            readers = sorted(set(json.loads(row[0])) | {identity})
                            conn.execute(
                                "UPDATE sources SET readers_json=? WHERE brain_id=? AND id=?",
                                (json.dumps(readers), brain, sid),
                            )
                            invalidate_source(
                                conn,
                                brain_id=brain,
                                source_id=sid,
                                reason="access_changed",
                            )
                            record_change(
                                conn,
                                brain_id=brain,
                                kind="source_access_set",
                                record_id=sid,
                            )
            readable = []
            with store.transaction() as conn:
                if "read" in operations:
                    for brain in brains:
                        readable.extend(
                            [brain, sid]
                            for sid in sorted(allowed_sources(conn, issued, brain))
                        )
            self._activate(token_id)
            return {
                "token_id": token_id,
                "token": token,
                "identity": identity,
                "label": label,
                "brain_ids": brains,
                "operations": sorted(set(operations)),
                "source_grants": source_grants,
                "readable_source_refs": readable,
                "grant_selected_sources": grant_selected_sources,
            }
        finally:
            store.close()

    def _activate(self, token_id):
        with self._transaction() as conn:
            changed = conn.execute(
                "UPDATE credentials SET status='active' WHERE id=? AND status='pending'",
                (token_id,),
            )
            if changed.rowcount != 1:
                raise _unauthenticated()

    def revoke_token(self, *, principal, token_id: str) -> None:
        bounded_text(token_id)
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT * FROM credentials WHERE id=?", (token_id,)
            ).fetchone()
            if row is None:
                raise _not_found()
            row = dict(row)
        brains = json.loads(row["brain_ids"]) if row["brain_ids"] else []
        owner_identity = self.owner_identity
        store = BrainStore(_profile_paths(self.state_dir))
        try:
            with store.transaction() as conn:
                self._owners(conn, principal, brains)
                if not brains and (
                    principal.identity != owner_identity
                    or row["identity"] != principal.identity
                ):
                    raise _not_found()
            with self._transaction() as conn:
                conn.execute(
                    "UPDATE credentials SET status='revoked' WHERE id=?", (token_id,)
                )
            if row["kind"] == "agent":
                try:
                    self._remove_memberships(store, row["identity"], brains, token_id)
                except (OSError, sqlite3.Error, BrainError):
                    pass  # Revocation already durable; ACL identities may remain inert.
        finally:
            store.close()

    @staticmethod
    def _remove_memberships(store, identity, brains, token_id):
        with store.transaction(write=True) as conn:
            for brain in brains:
                removed = conn.execute(
                    "DELETE FROM members WHERE brain_id=? AND identity=? AND role!='owner'",
                    (brain, identity),
                )
                if removed.rowcount:
                    record_change(
                        conn,
                        brain_id=brain,
                        kind="agent_member_removed",
                        record_id=token_id,
                    )

    def list_tokens(self, *, principal):
        if principal.kind != "human":
            raise _not_found()
        with self._transaction() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT id AS token_id,identity,label,status,created_at,expires_at FROM credentials WHERE issuer=? ORDER BY created_at,id",
                    (principal.identity,),
                )
            ]

    def login(self, secret: str):
        session = secrets.token_urlsafe(32)
        csrf = _csrf(session)
        with self._transaction() as conn:
            credential = self._live(conn, digest=_digest(secret))
            if credential["kind"] != "human":
                raise _unauthenticated()
            conn.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)",
                (
                    _digest(session),
                    credential["id"],
                    _digest(csrf),
                    time.time() + SESSION_SECONDS,
                ),
            )
        return session, csrf

    def session_info(self, session: str):
        with self._transaction() as conn:
            digest = _digest(session)
            row = conn.execute(
                "SELECT * FROM sessions WHERE digest=?", (digest,)
            ).fetchone()
            if row is None or row["expires_at"] <= time.time():
                raise _unauthenticated()
            credential = self._live(conn, token_id=row["credential_id"])
            csrf = _csrf(session)
            if row["csrf_digest"] != _digest(csrf):
                # Only the provisional random-CSRF digest migrates. Neither
                # parent validity nor session lifetime is renewed.
                conn.execute(
                    "UPDATE sessions SET csrf_digest=? WHERE digest=?",
                    (_digest(csrf), digest),
                )
            expires_at = row["expires_at"]
            if credential["expires_at"] is not None:
                expires_at = min(expires_at, credential["expires_at"])
            return {
                "csrf_token": csrf,
                "expires_in": max(0, int(expires_at - time.time())),
                "identity": credential["identity"],
                "kind": credential["kind"],
            }

    def authenticate_session(
        self, session: str, *, csrf: str | None = None, mutation=False
    ):
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE digest=?", (_digest(session),)
            ).fetchone()
            if row is None or row["expires_at"] <= time.time():
                raise _unauthenticated()
            credential = self._live(conn, token_id=row["credential_id"])
            if mutation:
                if (
                    not isinstance(csrf, str)
                    or len(csrf) < 32
                    or not secrets.compare_digest(row["csrf_digest"], _digest(csrf))
                ):
                    raise BrainError("csrf_required", "Valid session CSRF required.")
            return self._principal(credential)

    def logout(self, session: str):
        with self._transaction() as conn:
            conn.execute("DELETE FROM sessions WHERE digest=?", (_digest(session),))

    def close(self):
        """Connections are short-lived and closed by each transaction."""
