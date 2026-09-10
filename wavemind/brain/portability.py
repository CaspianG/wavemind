"""Complete authorized exports and explicit owner recovery operations."""

import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from .access import _not_found, allowed_sources, require_access
from .experience_records import digest, origins_for
from .experience_bridge import public_experience_id
from .models import BrainError, Principal
from .store import record_change
from .sources import invalidate_source
from . import portability_archive as archive_io


RESTORE_MARKER = "brain-restore-pending.json"


def _owner(conn, principal, brain_id, *operations):
    if not isinstance(principal, Principal) or principal.kind != "human":
        raise _not_found()
    for operation in operations:
        require_access(conn, principal, brain_id, operation)
    member = conn.execute(
        "SELECT role FROM members WHERE brain_id=? AND identity=?",
        (brain_id, principal.identity),
    ).fetchone()
    if member is None or member[0] != "owner":
        raise _not_found()


def _bootstrap(service, principal):
    if service.bootstrap_owner is None:
        raise BrainError(
            "bootstrap_required",
            "Configure the authenticated local restore owner first.",
        )
    if (
        not isinstance(principal, Principal)
        or principal.kind != "human"
        or principal.identity != service.bootstrap_owner
        or principal.brain_ids is not None
        or (
            principal.operations is not None
            and not {"manage_access", "restore", "read"} <= principal.operations
        )
    ):
        raise _not_found()


def _page(values, cursor, limit):
    if cursor is not None:
        if not isinstance(cursor, str):
            raise _not_found()
        indices = [i for i, row in enumerate(values) if row["id"] == cursor]
        if not indices:
            raise _not_found()
        values = values[indices[0] + 1 :]
    result = values[:limit]
    return result, result[-1]["id"] if len(values) > limit else None


def _limit(value):
    if type(value) is not int or not 1 <= value <= 100:
        raise BrainError("invalid_input", "Invalid review page size.")


def list_managed_sources(service, *, principal, brain_id, limit=100, cursor=None):
    with service.store.transaction() as conn:
        _owner(conn, principal, brain_id, "manage_access")
        _limit(limit)
        values = [
            dict(r)
            for r in conn.execute(
                "SELECT id,status FROM sources WHERE brain_id=? ORDER BY id",
                (brain_id,),
            )
        ]
        sources, next_cursor = _page(values, cursor, limit)
        return {"sources": sources, "next_cursor": next_cursor}


def review_restored_source(
    service,
    *,
    principal,
    brain_id,
    source_id,
    limit=100,
    version_cursor=None,
    citation_cursor=None,
):
    with service.store.transaction() as conn:
        _owner(conn, principal, brain_id, "restore", "read")
        _limit(limit)
        if not isinstance(source_id, str):
            raise _not_found()
        source = conn.execute(
            "SELECT id,status FROM sources WHERE brain_id=? AND id=?",
            (brain_id, source_id),
        ).fetchone()
        if source is None or source["status"] not in {
            "quarantined",
            "revoked",
            "deleted",
        }:
            raise _not_found()
        versions, citations = [], []
        if source["status"] == "quarantined":
            versions = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM source_versions WHERE brain_id=? AND source_id=? ORDER BY version,id",
                    (brain_id, source_id),
                )
            ]
            citations = [
                dict(r)
                for r in conn.execute(
                    "SELECT c.* FROM chunks c JOIN source_versions v ON v.brain_id=c.brain_id AND v.id=c.version_id WHERE c.brain_id=? AND c.source_id=? ORDER BY v.version,c.ordinal,c.id",
                    (brain_id, source_id),
                )
            ]
        versions, next_version = _page(versions, version_cursor, limit)
        citations, next_citation = _page(citations, citation_cursor, limit)
        return {
            "id": source_id,
            "status": source["status"],
            "versions": versions,
            "citations": citations,
            "next_version_cursor": next_version,
            "next_citation_cursor": next_citation,
        }


def admit_restored_sources(service, *, principal, brain_id, source_ids):
    with service.store.transaction(write=True) as conn:
        _owner(conn, principal, brain_id, "restore", "read")
        if (
            not isinstance(source_ids, list)
            or not source_ids
            or len(source_ids) > 100
            or any(not isinstance(s, str) for s in source_ids)
            or len(set(source_ids)) != len(source_ids)
        ):
            raise BrainError(
                "invalid_input", "Select between one and 100 distinct sources."
            )
        for source_id in source_ids:
            row = conn.execute(
                "SELECT status FROM sources WHERE brain_id=? AND id=?",
                (brain_id, source_id),
            ).fetchone()
            if row is None:
                raise _not_found()
            if (
                row[0] != "quarantined"
                or conn.execute(
                    "SELECT 1 FROM tombstones WHERE brain_id=? AND kind='source_deleted' AND record_id=?",
                    (brain_id, source_id),
                ).fetchone()
            ):
                raise BrainError("invalid_state", "Source cannot be admitted.")
        for source_id in source_ids:
            conn.execute(
                "UPDATE sources SET status='active' WHERE brain_id=? AND id=?",
                (brain_id, source_id),
            )
            invalidate_source(
                conn, brain_id=brain_id, source_id=source_id, reason="updated"
            )
            record_change(
                conn,
                brain_id=brain_id,
                kind="restored_source_admitted",
                record_id=source_id,
            )
    service.drain_outbox()
    with service.store.transaction() as conn:
        _owner(conn, principal, brain_id, "restore", "read")
        pending = conn.execute(
            "SELECT 1 FROM outbox WHERE brain_id=? AND status='pending' AND source_id IN (SELECT value FROM json_each(?)) LIMIT 1",
            (brain_id, json.dumps(source_ids)),
        ).fetchone()
    return {
        "source_ids": source_ids,
        "status": "admitted",
        "requires_review": True,
        "private_cleanup": "pending" if pending else "completed",
        "warnings": ["restored_memory_requires_recheck_and_new_experience"],
    }


def backup_brain(service, *, principal, brain_id, destination):
    # Authorize before returning path state or creating user-visible output.
    with service.store.transaction(write=True) as conn:
        _owner(conn, principal, brain_id, "manage_access", "export", "read")
        data = archive_io.selected_rows(conn, brain_id)
        if any(r["status"] == "quarantined" for r in data["sources"]):
            _owner(conn, principal, brain_id, "restore", "read")
        forbidden, blocked = archive_io.scrub_unavailable(data)
        namespaces = {r["namespace"] for r in data["brain_experience_links"]} - blocked
        private_data = None
        if namespaces and service.experience.private.path.exists():
            private = service.experience.private.store
            with private._lock:
                private.conn.execute("BEGIN IMMEDIATE")
                try:
                    private_data = archive_io.private_rows(private.conn, namespaces)
                finally:
                    private.conn.rollback()
        if private_data is None and namespaces:
            # Pending integrations/purges can legitimately lack private rows.
            completed = {
                r["id"]
                for r in data["outcomes"]
                if r["payload_json"] != "{}"
                and json.loads(r["payload_json"]).get("integration_status")
                == "completed"
            }
            if any(
                r["outcome_id"] in completed and r["namespace"] in namespaces
                for r in data["brain_experience_links"]
            ):
                raise BrainError(
                    "incomplete_snapshot",
                    "Required private experience data is unavailable.",
                )
        archive_io.validate_bindings(data, brain_id)
        archive_io.validate_private_support(data, private_data)
        target = archive_io.safe_path(destination)
        if target.exists():
            raise BrainError("destination_exists", "Choose a new backup destination.")
        if target in {
            service.store.path.resolve(),
            service.experience.private.path.resolve(),
        }:
            raise BrainError("invalid_path", "Invalid backup destination.")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Keep authority through publication: a completed revocation cannot
        # race an old readable snapshot becoming a newly published archive.
        with tempfile.TemporaryDirectory(
            prefix="wmb-backup-", dir=target.parent
        ) as raw:
            staging = Path(raw)
            archive_io.write_authority(staging / archive_io.BRAIN, data)
            if private_data is not None:
                archive_io.write_private(staging / archive_io.PRIVATE, private_data)
            warnings = ["import_previews_not_restored"]
            if forbidden:
                warnings.append("unavailable_content_omitted")
            private_state = (
                "included"
                if private_data is not None
                else "absent_with_pending_lineage"
                if data["brain_experience_links"]
                else "unused_or_purged"
            )
            temporary = staging / "archive.wmb"
            manifest = archive_io.write_archive(
                temporary, staging, brain_id, private_state, warnings
            )
            # Exclusive destination creation never overwrites user backups.
            with temporary.open("rb") as source, target.open("xb") as output:
                try:
                    import shutil

                    shutil.copyfileobj(source, output)
                    output.flush()
                    os.fsync(output.fileno())
                except BaseException:
                    output.close()
                    target.unlink(missing_ok=True)
                    raise
        return {
            "brain_id": brain_id,
            "archive": str(target),
            "schema": archive_io.ARCHIVE_SCHEMA,
            "files": manifest["files"],
            "private_state": private_state,
            "warnings": warnings,
            "pending_ids": [
                r["id"] for r in data["outbox"] if r["status"] == "pending"
            ],
        }


def _same_history(archived, current, private, current_private):
    for table, values in archived.items():
        if table in {"brains", "members", "audit", "previews", "brain_context_state"}:
            continue
        present = {digest(r) for r in current[table]}
        if any(digest(r) not in present for r in values):
            return False
    if private is not None:
        if current_private is None:
            return False
        for table, values in private.items():
            if table == "wavemind_schema_migrations":
                continue
            present = {digest(r) for r in current_private[table]}
            if {digest(r) for r in values} != present:
                return False
    return True


def _current_history(path, principal, brain_id, data, private_data):
    source = archive_io.safe_path(path) / archive_io.BRAIN
    if not source.is_file():
        raise _not_found()
    with archive_io.readonly(source) as conn:
        conn.execute("BEGIN")
        _owner(conn, principal, brain_id, "restore", "read")
        current = archive_io.selected_rows(conn, brain_id)
        current_private = None
        private_path = source.parent / archive_io.PRIVATE
        if private_path.exists():
            with archive_io.readonly(private_path) as private:
                current_private = archive_io.private_rows(
                    private, {r["namespace"] for r in current["brain_experience_links"]}
                )
        proved = _same_history(data, current, private_data, current_private)
        lifecycle = {r["id"]: r["status"] for r in current["sources"]}
        tombstones = current["tombstones"]
        conn.rollback()
        return proved, lifecycle, tombstones


def _recovery_error():
    return BrainError(
        "recovery_required",
        "Brain restore recovery requires inspection; existing files were preserved.",
    )


def recover_restore(state_dir):
    """Finish only a matching owned operation; no marker controls a path."""
    profile = archive_io.safe_path(state_dir)
    marker_path = profile / RESTORE_MARKER
    if not marker_path.exists() and not marker_path.is_symlink():
        if (profile / archive_io.PRIVATE).exists():
            try:
                with archive_io.readonly(profile / archive_io.BRAIN) as conn:
                    if conn.execute("SELECT 1 FROM brains LIMIT 1").fetchone() is None:
                        raise _recovery_error()
            except (OSError, sqlite3.Error):
                raise _recovery_error() from None
        return
    try:
        archive_io.safe_path(marker_path)
        if marker_path.stat().st_size > 4096:
            raise _recovery_error()
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if (
            set(marker)
            != {
                "operation_id",
                "brain_id",
                "private_name",
                "private_sha256",
                "private_size",
            }
            or marker["private_name"] != archive_io.PRIVATE
        ):
            raise _recovery_error()
        from uuid import UUID

        if (
            UUID(marker["operation_id"]).hex != marker["operation_id"]
            or UUID(marker["brain_id"]).hex != marker["brain_id"]
        ):
            raise _recovery_error()
        if marker["private_size"] is None:
            if marker["private_sha256"] is not None:
                raise _recovery_error()
        elif (
            type(marker["private_size"]) is not int
            or not 0 < marker["private_size"] <= archive_io.MAX_DATABASE_BYTES
            or not isinstance(marker["private_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", marker["private_sha256"]) is None
        ):
            raise _recovery_error()
        authority = archive_io.safe_path(profile / archive_io.BRAIN)
        if not authority.is_file():
            raise _recovery_error()
        # SQLite serializes recovery against other processes, not merely this
        # service's process lock. No live-schema write is necessary.
        with closing(
            sqlite3.connect(authority.as_uri() + "?mode=rw", uri=True, timeout=5)
        ) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA trusted_schema=OFF")
            conn.execute("BEGIN IMMEDIATE")
            with tempfile.TemporaryDirectory(prefix="wmb-recovery-schema-") as raw:
                from .store import BrainStore

                expected = BrainStore(Path(raw))
                try:
                    archive_io.inspect_database(
                        conn, archive_io.schema(expected._conn), 3
                    )
                finally:
                    expected.close()
            brains = [r[0] for r in conn.execute("SELECT id FROM brains")]
            committed = conn.execute(
                "SELECT 1 FROM audit WHERE brain_id=? AND kind='restore_committed' AND record_id=?",
                (marker["brain_id"], marker["operation_id"]),
            ).fetchone()
            private = archive_io.safe_path(profile / archive_io.PRIVATE)
            matches = (
                private.is_file()
                and private.stat().st_size == marker["private_size"]
                and archive_io.sha256(private) == marker["private_sha256"]
            )
            if brains == [marker["brain_id"]] and committed:
                if marker["private_size"] is not None:
                    if not matches:
                        raise _recovery_error()
                    with archive_io.readonly(private) as private_conn:
                        expected_private = archive_io.private_template()
                        try:
                            archive_io.inspect_database(
                                private_conn,
                                archive_io.schema(expected_private.conn),
                                0,
                            )
                        finally:
                            expected_private.close()
                elif private.exists():
                    raise _recovery_error()
                marker_path.unlink()
            elif not brains and not committed:
                if private.exists():
                    if not matches or marker["private_size"] is None:
                        raise _recovery_error()
                    private.unlink()
                marker_path.unlink()
            else:
                raise _recovery_error()
            conn.rollback()
    except BrainError:
        raise _recovery_error() from None
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        raise _recovery_error() from None


def restore_brain(service, *, principal, archive, current_state_dir=None):
    try:
        return _restore_brain(
            service,
            principal=principal,
            archive=archive,
            current_state_dir=current_state_dir,
        )
    except Exception as error:
        if (service.store.path.parent / RESTORE_MARKER).exists():
            recover_restore(service.store.path.parent)
        if isinstance(error, BrainError):
            raise
        raise BrainError("restore_failed", "Brain restore did not complete.") from None


def _restore_brain(service, *, principal, archive, current_state_dir=None):
    _bootstrap(service, principal)
    source = archive_io.safe_path(archive)
    profile = service.store.path.parent.resolve()
    with service.store.transaction(write=True) as target:
        if (
            target.execute("SELECT 1 FROM brains").fetchone()
            or service.experience.private.path.exists()
            or service.experience.private._store is not None
        ):
            raise BrainError(
                "target_not_empty", "Restore requires an empty selected profile."
            )
        if (profile / RESTORE_MARKER).exists():
            raise _recovery_error()
        with tempfile.TemporaryDirectory(prefix="wmb-restore-", dir=profile) as raw:
            staging = Path(raw)
            manifest, data, private_data = archive_io.read_archive(source, staging)
            brain_id = manifest["brain_id"]
            proved, lifecycle, tombstones = False, {}, []
            if current_state_dir is not None:
                if archive_io.safe_path(current_state_dir) == profile:
                    raise BrainError(
                        "invalid_input",
                        "Current history must be a separate authorized profile.",
                    )
                proved, lifecycle, tombstones = _current_history(
                    current_state_dir, principal, brain_id, data, private_data
                )
            deleted = {
                r["record_id"]
                for r in [*tombstones, *data["tombstones"]]
                if r["kind"] == "source_deleted"
            }
            for row in data["sources"]:
                if row["id"] in deleted or lifecycle.get(row["id"]) == "deleted":
                    row["status"] = "deleted"
                elif lifecycle.get(row["id"]) == "revoked":
                    row["status"] = "revoked"
                elif row["status"] in {"active", "paused"} and not proved:
                    row["status"] = "quarantined"
            old_tombstones = {r["id"] for r in data["tombstones"]}
            data["tombstones"].extend(
                r for r in tombstones if r["id"] not in old_tombstones
            )
            _, blocked = archive_io.scrub_unavailable(data)
            if private_data is not None and blocked:
                clean = staging / "clean-private.sqlite3"
                archive_io.write_private(clean, private_data)
                with archive_io.readonly(clean) as conn:
                    private_data = archive_io.private_rows(
                        conn,
                        {r["namespace"] for r in data["brain_experience_links"]}
                        - blocked,
                    )
            data["brains"][0]["owner"] = principal.identity
            data["members"] = [
                {"brain_id": brain_id, "identity": principal.identity, "role": "owner"}
            ]
            # Old action packets cannot be applied after target activation.
            data["brains"][0]["revision"] += 1
            operation_id = uuid4().hex
            private_stage = staging / "install-private.sqlite3"
            if private_data is not None:
                archive_io.write_private(private_stage, private_data)
            marker = {
                "operation_id": operation_id,
                "brain_id": brain_id,
                "private_name": archive_io.PRIVATE,
                "private_sha256": archive_io.sha256(private_stage)
                if private_data is not None
                else None,
                "private_size": private_stage.stat().st_size
                if private_data is not None
                else None,
            }
            marker_path = profile / RESTORE_MARKER
            with marker_path.open("x", encoding="utf-8") as output:
                output.write(json.dumps(marker))
                output.flush()
                os.fsync(output.fileno())
            try:
                for table in archive_io.table_names(target):
                    archive_io.insert_rows(target, table, data[table])
                record_change(
                    target,
                    brain_id=brain_id,
                    kind="restore_committed",
                    record_id=operation_id,
                    increment=False,
                )
                if private_data is not None:
                    os.replace(private_stage, profile / archive_io.PRIVATE)
                # BrainStore owns commit/rollback after leaving this method's
                # transaction. The durable marker covers that commit window.
            except BaseException:
                # Leave marker; startup proves rollback before owned cleanup.
                raise
    recover_restore(profile)
    warnings = ["import_previews_not_restored"]
    if any(row["status"] == "quarantined" for row in data["sources"]):
        warnings += [
            "restored_sources_quarantined",
            "restored_memory_requires_recheck_and_new_experience",
        ]
    return {
        "brain_id": brain_id,
        "status": "restored",
        "current_history_verified": proved,
        "warnings": warnings,
    }


def export_brain(service, *, principal, brain_id):
    """Export full visible history under one live authorization snapshot.

    This deliberately does not use bounded context/review providers. Private
    runtime data is represented by its verified authoritative outcomes here;
    the owner backup preserves the exact private runtime database separately.
    """
    with service.store.transaction() as conn:
        require_access(conn, principal, brain_id, "export")
        visible = allowed_sources(conn, principal, brain_id)
        records = {}
        for table in ("sources", "source_versions", "chunks"):
            records[table] = []
            for row in conn.execute(
                f"SELECT * FROM {table} WHERE brain_id=? ORDER BY rowid", (brain_id,)
            ):
                if row["id" if table == "sources" else "source_id"] not in visible:
                    continue
                item = dict(row)
                item.pop("readers_json", None)
                records[table].append(item)
        selected = set()
        for kind, table in (
            ("entity", "entities"),
            ("claim", "claims"),
            ("relation", "relations"),
            ("packet", "packets"),
            ("receipt", "receipts"),
            ("outcome", "outcomes"),
        ):
            records[table] = []
            for row in conn.execute(
                f"SELECT * FROM {table} WHERE brain_id=? ORDER BY id", (brain_id,)
            ):
                origins = origins_for(conn, brain_id, kind, row["id"])
                if not origins or not {o[2] for o in origins} <= visible:
                    continue
                if row["payload_json"] == "{}":
                    continue
                item = dict(row)
                if kind == "outcome":
                    payload = json.loads(item["payload_json"])
                    item["payload_json"] = json.dumps(
                        {k: v for k, v in payload.items() if not k.startswith("_")},
                        ensure_ascii=False,
                    )
                records[table].append(item)
                selected.add((kind, row["id"]))
        records["dependencies"] = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM dependencies WHERE brain_id=? ORDER BY rowid",
                (brain_id,),
            )
            if (row["dependent_type"], row["dependent_id"]) in selected
        ]
        records["brain_packet_basis"] = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM brain_packet_basis WHERE brain_id=? ORDER BY packet_id",
                (brain_id,),
            )
            if ("packet", row["packet_id"]) in selected
        ]
        records["experiences"] = []
        links = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM brain_experience_links WHERE brain_id=?", (brain_id,)
            )
        ]
        groups = {}
        for link in links:
            if link["brain_id"] == brain_id:
                groups.setdefault(link["namespace"], []).append(link)
        # All contributors, not any single visible result, authorize the exact
        # runtime scope. SQL iteration has no provider/context selection cap.
        if groups and service.experience.private.path.exists():
            private = service.experience.private.store
            with private._lock:
                private.conn.execute("BEGIN")
                try:
                    for namespace, mappings in groups.items():
                        ids = {r["outcome_id"] for r in mappings}
                        if not all(("outcome", oid) in selected for oid in ids):
                            continue
                        outcomes = [r for r in records["outcomes"] if r["id"] in ids]
                        if any(
                            r["status"] not in {"verified", "failed"} for r in outcomes
                        ):
                            continue
                        evidence = sorted(
                            {
                                json.loads(r["payload_json"])["verification"]["source"]
                                for r in outcomes
                            }
                        )
                        for row in private.conn.execute(
                            "SELECT * FROM experience_records WHERE namespace=? ORDER BY id",
                            (namespace,),
                        ):
                            if not any(
                                m["experience_id"] == row["id"] for m in mappings
                            ):
                                continue
                            records["experiences"].append(
                                {
                                    "id": public_experience_id(brain_id, row["id"]),
                                    "kind": row["kind"],
                                    "status": row["status"],
                                    "content": row["content"],
                                    "outcome_ids": sorted(ids),
                                    "verification_sources": evidence,
                                    "integration_statuses": sorted(
                                        {
                                            json.loads(r["payload_json"])[
                                                "integration_status"
                                            ]
                                            for r in outcomes
                                        }
                                    ),
                                    "eligibility": "requires_live_context_validation",
                                    "validation_count": private.conn.execute(
                                        "SELECT COUNT(*) FROM experience_candidate_validations WHERE experience_id=?",
                                        (row["id"],),
                                    ).fetchone()[0],
                                }
                            )
                finally:
                    private.conn.rollback()
        counts = {name: len(rows) for name, rows in records.items()}
        result = {
            "schema": "wavemind.brain_export.v1",
            "brain_id": brain_id,
            "revision": conn.execute(
                "SELECT revision FROM brains WHERE id=?", (brain_id,)
            ).fetchone()[0],
            "records": records,
            "counts": counts,
            "digests": {name: digest(rows) for name, rows in records.items()},
        }
        result["digest"] = digest(result)
        return result
