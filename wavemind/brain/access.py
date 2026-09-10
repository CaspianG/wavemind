"""The single live authority for membership, token grants and source access."""

import json
import sqlite3
from collections.abc import Iterable

from .models import OPERATIONS, BrainError, Principal


_ROLE_OPERATIONS = {
    "owner": OPERATIONS,
    "editor": frozenset({"read", "import", "propose", "record_outcome", "export"}),
    "reader": frozenset({"read", "export"}),
}
_AGENT_OPERATIONS = frozenset({"read", "import", "propose", "record_outcome", "export"})


def _not_found():
    # Identical error for nonexistent and unauthorized resources: no title,
    # source ID, membership identity, or hidden record count in the failure.
    return BrainError("not_found", "Resource not found.")


def _membership(conn, principal, brain_id, operation):
    if (
        not isinstance(principal, Principal)
        or not isinstance(brain_id, str)
        or not isinstance(operation, str)
        or operation not in OPERATIONS
        or not conn.in_transaction
        or (principal.brain_ids is not None and brain_id not in principal.brain_ids)
        or (principal.operations is not None and operation not in principal.operations)
        or (principal.kind == "agent" and operation not in _AGENT_OPERATIONS)
    ):
        raise _not_found()
    row = conn.execute(
        "SELECT role FROM members WHERE brain_id=? AND identity=?",
        (brain_id, principal.identity),
    ).fetchone()
    if row is None or operation not in _ROLE_OPERATIONS.get(row["role"], ()):
        raise _not_found()
    return row["role"]


def _readable(row, principal, role):
    if row["status"] not in ("active", "paused"):
        return False
    if role == "owner" or row["readers_json"] is None:
        return True
    try:
        readers = json.loads(row["readers_json"])
    except (TypeError, ValueError):
        return False
    return (
        isinstance(readers, list)
        and all(isinstance(item, str) for item in readers)
        and principal.identity in readers
    )


def require_access(
    conn: sqlite3.Connection,
    principal: Principal,
    brain_id: str,
    operation: str,
    source_ids: Iterable[str] = (),
) -> None:
    """Authorize within the caller's transaction, requiring every source.

    This checks normal source visibility for all operations. Management of an
    unreadable source first authorizes the Brain without source_ids, then uses
    a separately scoped lookup; that must never become a content-read bypass.
    """
    role = _membership(conn, principal, brain_id, operation)
    if isinstance(source_ids, (str, bytes)) or source_ids is None:
        raise _not_found()
    for source_id in source_ids:
        if not isinstance(source_id, str):
            raise _not_found()
        row = conn.execute(
            "SELECT status,readers_json FROM sources WHERE brain_id=? AND id=?",
            (brain_id, source_id),
        ).fetchone()
        if row is None or not _readable(row, principal, role):
            raise _not_found()


def allowed_sources(
    conn: sqlite3.Connection, principal: Principal, brain_id: str
) -> set[str]:
    """Return only exact IDs of readable sources in an authorized Brain."""
    role = _membership(conn, principal, brain_id, "read")
    return {
        row["id"]
        for row in conn.execute(
            "SELECT id,status,readers_json FROM sources WHERE brain_id=?", (brain_id,)
        )
        if _readable(row, principal, role)
    }
