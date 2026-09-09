"""Explicit reviewed imports, exact citations and one source lifecycle boundary."""

import hashlib
import json
import time
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


def _invalid():
    return BrainError("invalid_input", "Invalid import request.")


def invalidate_source(conn, *, brain_id: str, source_id: str, reason: str):
    """In-transaction shared invalidation for ACL/update/revoke/delete.

    Task 3+ must register every origin in dependencies with singular types
    (claim/entity/relation/packet/receipt/outcome/preview). Transitive dependents
    and packet receipt/outcome chains are invalidated here. Preview payloads
    are always purged; reviewed history is preserved except on deletion.
    Updated claims/entities/relations become proposed with needs_recheck=True.
    No source text enters the outbox. The caller records the revision change.
    """
    links = conn.execute(
        "SELECT * FROM dependencies WHERE brain_id=?", (brain_id,)
    ).fetchall()
    affected = {
        (r["dependent_type"], r["dependent_id"])
        for r in links
        if r["source_id"] == source_id
    }
    affected.add(("source", source_id))
    while True:
        added = {
            (r["dependent_type"], r["dependent_id"])
            for r in links
            if (r["origin_type"], r["origin_id"]) in affected
        } - affected
        if not added:
            break
        affected.update(added)
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
    for row in conn.execute(
        "SELECT id,packet_id FROM receipts WHERE brain_id=?", (brain_id,)
    ):
        if ("packet", row["packet_id"]) in affected:
            affected.add(("receipt", row["id"]))
    for row in conn.execute(
        "SELECT id,receipt_id FROM outcomes WHERE brain_id=?", (brain_id,)
    ):
        if ("receipt", row["receipt_id"]) in affected:
            affected.add(("outcome", row["id"]))
    tables = {
        "claim": "claims",
        "entity": "entities",
        "relation": "relations",
        "packet": "packets",
        "receipt": "receipts",
        "outcome": "outcomes",
        "preview": "previews",
    }
    for kind, record_id in affected:
        table = tables.get(kind)
        if table is None:
            continue
        if reason == "deleted" or kind == "preview":
            status = ",status='revoked'" if kind != "receipt" else ""
            conn.execute(
                f"UPDATE {table} SET payload_json='{{}}'{status} WHERE brain_id=? AND id=?",
                (brain_id, record_id),
            )
        elif kind in ("claim", "entity", "relation"):
            if reason == "updated":
                row = conn.execute(
                    f"SELECT payload_json FROM {table} WHERE brain_id=? AND id=?",
                    (brain_id, record_id),
                ).fetchone()
                if row is not None:
                    payload = json.loads(row[0])
                    payload["needs_recheck"] = True
                    conn.execute(
                        f"UPDATE {table} SET status='proposed',payload_json=? WHERE brain_id=? AND id=?",
                        (json.dumps(payload, ensure_ascii=False), brain_id, record_id),
                    )
            elif reason == "revoked":
                conn.execute(
                    f"UPDATE {table} SET status='revoked' WHERE brain_id=? AND id=?",
                    (brain_id, record_id),
                )
            # ACL changes affect readers, not the owner's semantic review.
        elif kind in ("packet", "outcome"):
            conn.execute(
                f"UPDATE {table} SET status='revoked' WHERE brain_id=? AND id=?",
                (brain_id, record_id),
            )
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
    return {"id": source_id, "version": version, "citations": citations}


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
        self, *, principal: Principal, brain_id: str, files: list[dict]
    ) -> dict:
        with self.store.transaction() as conn:
            require_access(conn, principal, brain_id, "import")
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
            for item in parsed:
                if item["status"] == "valid":
                    item["source_id"] = _resolve_source(
                        conn, principal=principal, brain_id=brain_id, item=item
                    )
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
                    json.dumps({"files": parsed}, ensure_ascii=False),
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
                        "INSERT INTO sources(brain_id,id,title,kind,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                        (
                            brain_id,
                            sid,
                            item["name"],
                            item["kind"],
                            time.time(),
                            time.time(),
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
