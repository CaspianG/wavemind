"""Explicit reviewed imports, exact citations and one source lifecycle boundary."""

import hashlib
import json
import sqlite3
import time
from collections import defaultdict, deque
from uuid import uuid4

from .access import _not_found, allowed_sources, require_access
from .models import BrainError, Principal, bounded_text
from .parsing import MAX_FILE_BYTES, parse_file
from .store import record_change


MAX_FILES = 20
MAX_IMPORT_BYTES = 50 * 1024 * 1024
CHUNK_BYTES = 8192
PREVIEW_SECONDS = 900
MAX_PENDING_PREVIEWS = 5
MAX_DEPENDENCY_NODES = 10000
ERASURE_SECONDS = 30
DERIVED_TABLES = {
    "claim": "claims",
    "entity": "entities",
    "relation": "relations",
    "packet": "packets",
    "receipt": "receipts",
    "outcome": "outcomes",
    "preview": "previews",
}


def context_pending(conn, *, brain_id):
    """Internal transaction helper; callers authorize before reading this gate."""
    row = conn.execute(
        "SELECT pending FROM brain_context_state WHERE brain_id=?", (brain_id,)
    ).fetchone()
    return row is not None and bool(row[0])


def mark_context_pending(conn, *, brain_id, reason="dependency_limit"):
    conn.execute(
        """INSERT INTO brain_context_state(brain_id,pending,reason) VALUES (?,1,?)
                 ON CONFLICT(brain_id) DO UPDATE SET pending=1,reason=excluded.reason""",
        (brain_id, reason),
    )


def dependency_closure(conn, *, brain_id, seeds, source_id=None):
    """At most 10,000 visited nodes, including seeds; cycles terminate."""
    graph = defaultdict(set)
    starts = set(seeds)
    for row in conn.execute("SELECT * FROM dependencies WHERE brain_id=?", (brain_id,)):
        child = (row["dependent_type"], row["dependent_id"])
        graph[(row["origin_type"], row["origin_id"])].add(child)
        if source_id is not None and row["source_id"] == source_id:
            starts.add(child)
    for origin, child in dependency_edges(conn, brain_id=brain_id):
        graph[origin].add(child)
    queue, visited = deque(sorted(starts)), set()
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        if len(visited) == MAX_DEPENDENCY_NODES:
            return visited, True
        visited.add(node)
        queue.extend(sorted(graph[node] - visited))
    return visited, False


def dependency_edges(conn, *, brain_id):
    """Exact-Brain origin edges including implicit receipt/outcome references."""
    for row in conn.execute("SELECT * FROM dependencies WHERE brain_id=?", (brain_id,)):
        yield (
            (row["origin_type"], row["origin_id"]),
            (row["dependent_type"], row["dependent_id"]),
        )
    for row in conn.execute(
        "SELECT id,packet_id FROM receipts WHERE brain_id=?", (brain_id,)
    ):
        yield ("packet", row["packet_id"]), ("receipt", row["id"])
    for row in conn.execute(
        "SELECT id,receipt_id FROM outcomes WHERE brain_id=?", (brain_id,)
    ):
        yield ("receipt", row["receipt_id"]), ("outcome", row["id"])


def _overflow(conn, brain_id, reason="updated"):
    mark_context_pending(conn, brain_id=brain_id)
    # The pending gate covers every consumer. Explicit rechecks remain needed
    # after graph recovery so unvisited rows cannot retain an obsolete approval.
    for table in (
        ("claims", "entities", "relations") if reason in ("updated", "revoked") else ()
    ):
        conn.execute(
            f"UPDATE {table} SET status='proposed',payload_json=json_set(payload_json,'$.needs_recheck',json('true')) WHERE brain_id=? AND status!='revoked' AND payload_json!='{{}}'",
            (brain_id,),
        )
    for table in ("packets", "outcomes"):
        conn.execute(
            f"UPDATE {table} SET status='revoked' WHERE brain_id=?", (brain_id,)
        )
    conn.execute(
        "UPDATE previews SET status='revoked',payload_json='{}' WHERE brain_id=?",
        (brain_id,),
    )


def _invalidate_records(conn, *, brain_id, affected, reason):
    for kind, record_id in affected:
        table = DERIVED_TABLES.get(kind)
        if table is None:
            continue
        if reason == "deleted" or kind == "preview":
            status = ",status='revoked'" if kind != "receipt" else ""
            if reason == "deleted" and kind in ("claim", "entity", "relation"):
                status += ",kind='deleted'"
            conn.execute(
                f"UPDATE {table} SET payload_json='{{}}'{status} WHERE brain_id=? AND id=?",
                (brain_id, record_id),
            )
        elif kind in ("claim", "entity", "relation"):
            if reason == "updated":
                conn.execute(
                    f"UPDATE {table} SET status='proposed',payload_json=json_set(payload_json,'$.needs_recheck',json('true')) WHERE brain_id=? AND id=? AND status!='revoked' AND payload_json!='{{}}'",
                    (brain_id, record_id),
                )
            elif reason == "revoked":
                conn.execute(
                    f"UPDATE {table} SET status='revoked' WHERE brain_id=? AND id=?",
                    (brain_id, record_id),
                )
        elif kind in ("packet", "outcome"):
            conn.execute(
                f"UPDATE {table} SET status='revoked' WHERE brain_id=? AND id=?",
                (brain_id, record_id),
            )


def invalidate_dependents(conn, *, brain_id, seeds, context_only=False):
    """Share lifecycle propagation; context-only changes preserve semantic intent."""
    affected, overflow = dependency_closure(conn, brain_id=brain_id, seeds=seeds)
    if overflow:
        _overflow(conn, brain_id, "access_changed" if context_only else "updated")
    affected -= set(seeds)
    if context_only:
        affected = {
            node
            for node in affected
            if node[0] in ("packet", "receipt", "outcome", "preview")
        }
    _invalidate_records(conn, brain_id=brain_id, affected=affected, reason="updated")


def _erase_source_closure(conn, *, brain_id, source_id):
    """Erasure-only bounded-time SQL closure; UNION terminates cyclic graphs.

    Every content-bearing target is scrubbed before dependency rows can be
    removed. Exceptions propagate to the enclosing lifecycle transaction.
    """
    deadline = time.monotonic() + ERASURE_SECONDS

    def interrupted():
        return time.monotonic() >= deadline

    prefix = """WITH RECURSIVE edges(ot,oi,dt,di) AS (
        SELECT origin_type,origin_id,dependent_type,dependent_id FROM dependencies WHERE brain_id=?
        UNION SELECT 'packet',packet_id,'receipt',id FROM receipts WHERE brain_id=?
        UNION SELECT 'receipt',receipt_id,'outcome',id FROM outcomes WHERE brain_id=?
    ), affected(kind,id) AS (
        SELECT 'source',?
        UNION SELECT dependent_type,dependent_id FROM dependencies WHERE brain_id=? AND source_id=?
        UNION SELECT e.dt,e.di FROM edges e JOIN affected a ON e.ot=a.kind AND e.oi=a.id
    ) """
    params = (brain_id, brain_id, brain_id, source_id, brain_id, source_id)
    conn.set_progress_handler(interrupted, 1000)
    try:
        if interrupted():
            raise sqlite3.OperationalError("interrupted")
        conn.execute(
            "CREATE TEMP TABLE brain_erasure_targets(kind TEXT,id TEXT,PRIMARY KEY(kind,id))"
        )
        conn.execute(
            prefix + "INSERT INTO brain_erasure_targets SELECT kind,id FROM affected",
            params,
        )
        for kind, table in DERIVED_TABLES.items():
            status = ",status='revoked'" if kind != "receipt" else ""
            if kind in ("claim", "entity", "relation"):
                status += ",kind='deleted'"
            conn.execute(
                f"UPDATE {table} SET payload_json='{{}}'{status} WHERE brain_id=? AND id IN (SELECT id FROM brain_erasure_targets WHERE kind=?)",
                (brain_id, kind),
            )
        conn.execute(
            "DELETE FROM brain_packet_basis WHERE brain_id=? AND packet_id IN (SELECT id FROM brain_erasure_targets WHERE kind='packet')",
            (brain_id,),
        )
        conn.execute(
            "UPDATE outbox SET payload_json='{}' WHERE brain_id=? AND source_id=?",
            (brain_id, source_id),
        )
    except sqlite3.Error:
        raise BrainError(
            "deletion_failed", "Source deletion did not complete."
        ) from None
    finally:
        conn.set_progress_handler(None, 0)
        conn.execute("DROP TABLE IF EXISTS temp.brain_erasure_targets")


def _invalid():
    return BrainError("invalid_input", "Invalid import request.")


def resolve_citation(conn, *, principal, brain_id, citation_id):
    """Resolve exact historic evidence using the caller's authorized snapshot."""
    require_access(conn, principal, brain_id, "read")
    if not isinstance(citation_id, str):
        raise _not_found()
    row = conn.execute(
        """SELECT c.*,v.version FROM chunks c JOIN source_versions v
        ON c.brain_id=v.brain_id AND c.source_id=v.source_id AND c.version_id=v.id
        WHERE c.brain_id=? AND c.id=?""",
        (brain_id, citation_id),
    ).fetchone()
    if row is None:
        raise _not_found()
    require_access(conn, principal, brain_id, "read", [row["source_id"]])
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "version": row["version"],
        "text": row["text"],
        **json.loads(row["locator_json"]),
    }


def invalidate_source(conn, *, brain_id: str, source_id: str, reason: str):
    """In-transaction shared invalidation for ACL/update/revoke/delete.

    Task 3+ must register every origin in dependencies with singular types
    (claim/entity/relation/packet/receipt/outcome/preview). Transitive dependents
    and packet receipt/outcome chains are invalidated here. Preview payloads
    are always purged; reviewed history is preserved except on deletion.
    Updated claims/entities/relations become proposed with needs_recheck=True.
    No source text enters the outbox. The caller records the revision change.
    """
    affected, overflow = dependency_closure(
        conn, brain_id=brain_id, seeds={("source", source_id)}, source_id=source_id
    )
    if overflow:
        _overflow(conn, brain_id, reason)
    if reason == "deleted":
        _erase_source_closure(conn, brain_id=brain_id, source_id=source_id)
    # Import previews include both pending normalized content and committed
    # retry results. Purge the whole preview, never a partial accepted batch.
    for row in conn.execute(
        "SELECT id,payload_json FROM previews WHERE brain_id=?", (brain_id,)
    ).fetchall():
        data = json.loads(row["payload_json"])
        if any(
            item.get("source_id") == source_id for item in data.get("files", [])
        ) or any(
            item.get("id") == source_id
            for item in data.get("result", {}).get("sources", [])
        ):
            affected.add(("preview", row["id"]))
    _invalidate_records(conn, brain_id=brain_id, affected=affected, reason=reason)
    conn.execute(
        "INSERT INTO outbox(brain_id,id,kind,source_id,created_at) VALUES (?,?,?,?,?)",
        (brain_id, uuid4().hex, "source_" + reason, source_id, time.time()),
    )


def _chunks(text):
    start, size = 0, 0
    for position, char in enumerate(text):
        width = len(char.encode("utf-8"))
        if size + width > CHUNK_BYTES:
            yield start, position, text[start:position]
            start, size = position, 0
        size += width
    if start < len(text):
        yield start, len(text), text[start:]


def _version_result(conn, *, principal, brain_id, source_id, version):
    require_access(conn, principal, brain_id, "read", [source_id])
    citations = []
    for row in conn.execute(
        """SELECT c.id,c.text,c.locator_json FROM chunks c JOIN source_versions v
           ON v.brain_id=c.brain_id AND v.source_id=c.source_id AND v.id=c.version_id
           WHERE c.brain_id=? AND c.source_id=? AND v.version=? ORDER BY c.ordinal""",
        (brain_id, source_id, version),
    ):
        citations.append(
            {"id": row["id"], "text": row["text"], **json.loads(row["locator_json"])}
        )
    acl = conn.execute(
        "SELECT readers_json FROM sources WHERE brain_id=? AND id=?",
        (brain_id, source_id),
    ).fetchone()[0]
    return {
        "id": source_id,
        "version": version,
        "citations": citations,
        "access": _audience(None if acl is None else json.loads(acl)),
    }


def _audience(readers):
    return {
        "mode": "all_live_members" if readers is None else "restricted",
        "readers": readers,
    }


def _initial_readers(conn, principal, brain_id, readers):
    if readers is None:
        return None
    require_access(conn, principal, brain_id, "manage_access")
    if principal.kind != "human" or not isinstance(readers, list) or len(readers) > 100:
        raise _invalid()
    return sorted({bounded_text(reader) for reader in readers})


def _existing_audience(conn, brain_id, source_id, readers):
    if source_id is not None and readers is not None:
        current = conn.execute(
            "SELECT readers_json FROM sources WHERE brain_id=? AND id=?",
            (brain_id, source_id),
        ).fetchone()[0]
        if current is None or sorted(json.loads(current)) != readers:
            raise BrainError(
                "invalid_input", "Existing source audience differs from preview."
            )


def _resolve_source(conn, *, principal, brain_id, item):
    source_id = item["source_id"]
    if source_id is None:
        # All statuses participate: hidden/revoked content cannot be copied
        # into a fresh unrestricted source by submitting its digest again.
        rows = conn.execute(
            "SELECT DISTINCT source_id FROM source_versions WHERE brain_id=? AND digest=? ORDER BY source_id",
            (brain_id, item["digest"]),
        ).fetchall()
        if rows:
            require_access(conn, principal, brain_id, "import", [r[0] for r in rows])
            require_access(conn, principal, brain_id, "read", [r[0] for r in rows])
            source_id = rows[0][0]
    if source_id is not None:
        require_access(conn, principal, brain_id, "import", [source_id])
        require_access(conn, principal, brain_id, "read", [source_id])
        row = conn.execute(
            "SELECT status FROM sources WHERE brain_id=? AND id=?",
            (brain_id, source_id),
        ).fetchone()
        if row["status"] != "active":
            raise BrainError("source_paused", "Source is paused.")
    return source_id


class Sources:
    def __init__(self, store):
        self.store = store

    def preview_import(
        self,
        *,
        principal: Principal,
        brain_id: str,
        files: list[dict],
        new_source_readers: list[str] | None = None,
    ) -> dict:
        with self.store.transaction() as conn:
            require_access(conn, principal, brain_id, "import")
            if principal.source_refs is not None:
                raise _not_found()
            readers = _initial_readers(conn, principal, brain_id, new_source_readers)
            if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
                raise _invalid()
            total = 0
            for item in files:
                if (
                    not isinstance(item, dict)
                    or not {"name", "content"} <= item.keys()
                    or not item.keys() <= {"name", "content", "source_id"}
                    or not isinstance(item["content"], bytes)
                ):
                    raise _invalid()
                name = bounded_text(item["name"], maximum=500)
                try:
                    name.encode("utf-8")
                except UnicodeError:
                    raise _invalid() from None
                if any(char in name for char in "/\\:") or name in (".", ".."):
                    raise _invalid()
                total += len(item["content"])
                if len(item["content"]) > MAX_FILE_BYTES or total > MAX_IMPORT_BYTES:
                    raise _invalid()
                if "source_id" in item:
                    if not isinstance(item["source_id"], str):
                        raise _invalid()
                    require_access(
                        conn, principal, brain_id, "import", [item["source_id"]]
                    )
                    require_access(
                        conn, principal, brain_id, "read", [item["source_id"]]
                    )
        parsed = []
        for item in files:
            result = {
                "id": uuid4().hex,
                "name": item["name"],
                "status": "valid",
                "error": None,
                "bytes": len(item["content"]),
                "extracted_bytes": 0,
                "source_id": item.get("source_id"),
                "preview_text": "",
            }
            try:
                text, kind = parse_file(name=item["name"], content=item["content"])
                result.update(
                    preview_text=text,
                    extracted_bytes=len(text.encode("utf-8")),
                    kind=kind,
                    digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            except BrainError as error:
                result.update(status="error", error=error.code)
            parsed.append(result)
        now, preview_id = time.time(), uuid4().hex
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "import")
            readers = _initial_readers(conn, principal, brain_id, readers)
            for item in parsed:
                if item["status"] == "valid":
                    item["source_id"] = _resolve_source(
                        conn, principal=principal, brain_id=brain_id, item=item
                    )
                    _existing_audience(conn, brain_id, item["source_id"], readers)
                    current_readers = readers
                    if item["source_id"] is not None:
                        acl = conn.execute(
                            "SELECT readers_json FROM sources WHERE brain_id=? AND id=?",
                            (brain_id, item["source_id"]),
                        ).fetchone()[0]
                        current_readers = None if acl is None else json.loads(acl)
                    item["access"] = _audience(current_readers)
                elif item["source_id"] is not None:
                    require_access(
                        conn, principal, brain_id, "import", [item["source_id"]]
                    )
                    require_access(
                        conn, principal, brain_id, "read", [item["source_id"]]
                    )
            conn.execute(
                "UPDATE previews SET status='expired',payload_json='{}' WHERE brain_id=? AND expires_at<=? AND status='pending'",
                (brain_id, now),
            )
            count = conn.execute(
                "SELECT count(*) FROM previews WHERE brain_id=? AND principal_id=? AND status='pending'",
                (brain_id, principal.identity),
            ).fetchone()[0]
            if count >= MAX_PENDING_PREVIEWS:
                raise BrainError(
                    "preview_limit", "Too many pending previews; confirm or cancel one."
                )
            revision = conn.execute(
                "SELECT revision FROM brains WHERE id=?", (brain_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO previews(brain_id,id,principal_id,revision,created_at,expires_at,payload_json) VALUES (?,?,?,?,?,?,?)",
                (
                    brain_id,
                    preview_id,
                    principal.identity,
                    revision,
                    now,
                    now + PREVIEW_SECONDS,
                    json.dumps(
                        {"files": parsed, "new_source_readers": readers},
                        ensure_ascii=False,
                    ),
                ),
            )
        public = [
            {key: value for key, value in item.items() if key not in ("kind", "digest")}
            for item in parsed
        ]
        return {
            "id": preview_id,
            "files": public,
            "network_calls": 0,
            "model_connected": False,
            "new_source_access": _audience(readers),
        }

    def commit_import(
        self,
        *,
        principal: Principal,
        brain_id: str,
        preview_id: str,
        accepted_ids: list[str],
    ) -> dict:
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "import")
            if not isinstance(preview_id, str):
                raise _not_found()
            row = conn.execute(
                "SELECT * FROM previews WHERE brain_id=? AND id=? AND principal_id=?",
                (brain_id, preview_id, principal.identity),
            ).fetchone()
            if row is None or row["status"] not in (
                "pending",
                "committed",
                "cancelled",
            ):
                raise _not_found()
            if (
                not isinstance(accepted_ids, list)
                or len(accepted_ids) > MAX_FILES
                or any(not isinstance(value, str) for value in accepted_ids)
                or len(set(accepted_ids)) != len(accepted_ids)
            ):
                raise _invalid()
            accepted = sorted(accepted_ids)
            # This API returns persisted citation text as part of confirmation,
            # so nonempty commits need both operations even for a new source.
            # Creator identity is not a substitute for a live token read grant.
            if accepted:
                require_access(conn, principal, brain_id, "read")
            payload = json.loads(row["payload_json"])
            if row["status"] in ("committed", "cancelled"):
                if payload["accepted_ids"] != accepted:
                    raise _invalid()
                require_access(
                    conn,
                    principal,
                    brain_id,
                    "import",
                    [item["id"] for item in payload["result"]["sources"]],
                )
                if payload["result"]["sources"]:
                    require_access(
                        conn,
                        principal,
                        brain_id,
                        "read",
                        [item["id"] for item in payload["result"]["sources"]],
                    )
                return payload["result"]
            readers = _initial_readers(
                conn, principal, brain_id, payload.get("new_source_readers")
            )
            if principal.source_refs is not None:
                raise _not_found()
            if row["expires_at"] is None or row["expires_at"] <= time.time():
                raise BrainError("preview_expired", "Import preview expired.")
            selected = [item for item in payload["files"] if item["id"] in accepted]
            if len(selected) != len(accepted) or any(
                item["status"] != "valid" for item in selected
            ):
                raise _invalid()
            # Resolve every item before the first source write. Same-source
            # competing updates in one batch are rejected, never last-one-wins.
            targets = {}
            for item in selected:
                item["source_id"] = _resolve_source(
                    conn, principal=principal, brain_id=brain_id, item=item
                )
                sid = item["source_id"]
                _existing_audience(conn, brain_id, sid, readers)
                if (
                    sid is not None
                    and sid in targets
                    and targets[sid] != item["digest"]
                ):
                    raise _invalid()
                targets[sid or item["digest"]] = item["digest"]
            sources = []
            for item in selected:
                sid = _resolve_source(
                    conn, principal=principal, brain_id=brain_id, item=item
                )
                if sid is None:
                    sid = uuid4().hex
                    conn.execute(
                        "INSERT INTO sources(brain_id,id,title,kind,created_at,updated_at,readers_json) VALUES (?,?,?,?,?,?,?)",
                        (
                            brain_id,
                            sid,
                            item["name"],
                            item["kind"],
                            time.time(),
                            time.time(),
                            None if readers is None else json.dumps(readers),
                        ),
                    )
                existing = conn.execute(
                    "SELECT version FROM source_versions WHERE brain_id=? AND source_id=? AND digest=?",
                    (brain_id, sid, item["digest"]),
                ).fetchone()
                if existing:
                    sources.append(
                        _version_result(
                            conn,
                            principal=principal,
                            brain_id=brain_id,
                            source_id=sid,
                            version=existing["version"],
                        )
                    )
                    continue
                current = conn.execute(
                    "SELECT coalesce(max(version),0) FROM source_versions WHERE brain_id=? AND source_id=?",
                    (brain_id, sid),
                ).fetchone()[0]
                if current:
                    invalidate_source(
                        conn, brain_id=brain_id, source_id=sid, reason="updated"
                    )
                    conn.execute(
                        "UPDATE source_versions SET status='superseded' WHERE brain_id=? AND source_id=?",
                        (brain_id, sid),
                    )
                vid = uuid4().hex
                conn.execute(
                    "INSERT INTO source_versions(brain_id,source_id,id,version,digest,kind,created_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        brain_id,
                        sid,
                        vid,
                        current + 1,
                        item["digest"],
                        item["kind"],
                        time.time(),
                    ),
                )
                for ordinal, (start, end, text) in enumerate(
                    _chunks(item["preview_text"])
                ):
                    conn.execute(
                        "INSERT INTO chunks(brain_id,source_id,version_id,id,ordinal,text,locator_json) VALUES (?,?,?,?,?,?,?)",
                        (
                            brain_id,
                            sid,
                            vid,
                            uuid4().hex,
                            ordinal,
                            text,
                            json.dumps({"start": start, "end": end}),
                        ),
                    )
                conn.execute(
                    "UPDATE sources SET updated_at=? WHERE brain_id=? AND id=?",
                    (time.time(), brain_id, sid),
                )
                record_change(
                    conn, brain_id=brain_id, kind="source_imported", record_id=sid
                )
                sources.append(
                    _version_result(
                        conn,
                        principal=principal,
                        brain_id=brain_id,
                        source_id=sid,
                        version=current + 1,
                    )
                )
            result = {"sources": sources}
            conn.execute(
                "UPDATE previews SET status=?,payload_json=? WHERE brain_id=? AND id=?",
                (
                    "committed" if accepted else "cancelled",
                    json.dumps(
                        {"accepted_ids": accepted, "result": result}, ensure_ascii=False
                    ),
                    brain_id,
                    preview_id,
                ),
            )
            return result

    def read_citation(
        self, *, principal: Principal, brain_id: str, citation_id: str
    ) -> dict:
        with self.store.transaction() as conn:
            return resolve_citation(
                conn, principal=principal, brain_id=brain_id, citation_id=citation_id
            )

    def list_sources(self, *, principal: Principal, brain_id: str) -> list[dict]:
        with self.store.transaction() as conn:
            visible = allowed_sources(conn, principal, brain_id)
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT id,title,kind,status,created_at,updated_at FROM sources WHERE brain_id=? ORDER BY created_at,id",
                    (brain_id,),
                )
                if row["id"] in visible
            ]

    def change_source(
        self, *, principal: Principal, brain_id: str, source_id: str, action: str
    ) -> dict:
        with self.store.transaction(write=True) as conn:
            require_access(
                conn,
                principal,
                brain_id,
                "delete" if action == "delete" else "manage_access",
            )
            if not isinstance(source_id, str):
                raise _not_found()
            row = conn.execute(
                "SELECT status FROM sources WHERE brain_id=? AND id=?",
                (brain_id, source_id),
            ).fetchone()
            if row is None:
                raise _not_found()
            if action not in ("pause", "resume", "revoke", "delete"):
                raise _invalid()
            status = {
                "pause": "paused",
                "resume": "active",
                "revoke": "revoked",
                "delete": "deleted",
            }[action]
            if row["status"] != status:
                if (
                    row["status"] in ("revoked", "deleted", "quarantined")
                    and action != "delete"
                ):
                    raise BrainError("invalid_state", "Source cannot be resumed.")
                if action in ("revoke", "delete"):
                    invalidate_source(
                        conn, brain_id=brain_id, source_id=source_id, reason=status
                    )
                conn.execute(
                    "UPDATE sources SET status=?,updated_at=? WHERE brain_id=? AND id=?",
                    (status, time.time(), brain_id, source_id),
                )
                record_change(
                    conn,
                    brain_id=brain_id,
                    kind="source_" + status,
                    record_id=source_id,
                )
                if action == "delete":
                    conn.execute(
                        "DELETE FROM source_versions WHERE brain_id=? AND source_id=?",
                        (brain_id, source_id),
                    )
                    conn.execute(
                        "DELETE FROM dependencies WHERE brain_id=? AND source_id=?",
                        (brain_id, source_id),
                    )
                    conn.execute(
                        "UPDATE sources SET title='',kind='text',metadata_json='{}',readers_json=NULL WHERE brain_id=? AND id=?",
                        (brain_id, source_id),
                    )
                    conn.execute(
                        "INSERT INTO tombstones(brain_id,id,kind,record_id,revision,created_at) SELECT id,?,'source_deleted',?,revision,? FROM brains WHERE id=?",
                        (uuid4().hex, source_id, time.time(), brain_id),
                    )
            return {
                "id": source_id,
                "status": status,
                "retained_backup_limitation": "Local deletion does not erase upstream files, external backups, or forensic storage remnants.",
            }
