"""Fixed-schema, selected-Brain archives; no untrusted SQL or profile copies."""

import hashlib
import json
import math
import re
import sqlite3
import stat
import time
import zipfile
from contextlib import closing, contextmanager
from pathlib import Path

from .experience_records import digest, encode
from .models import BrainError
from .store import BrainStore
from ..experience import SQLiteExperienceStore
from ..experience_compiler import ExperienceCompiler
from ..experience_runtime import AgentExperienceRuntime
from ..memory_firewall import MemoryFirewall, MemoryFirewallPolicy
from ..schema_migrations import validate_runtime_schema, EXPERIENCE_COMPONENT


ARCHIVE_SCHEMA = "wavemind.brain_backup.v1"
BRAIN = "brain.sqlite3"
PRIVATE = "brain-experience.sqlite3"
MANIFEST = "manifest.json"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_DATABASE_BYTES = 768 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_COMPRESSION_RATIO = 100
DERIVED = {
    "entities": "entity",
    "claims": "claim",
    "relations": "relation",
    "packets": "packet",
    "receipts": "receipt",
    "outcomes": "outcome",
    "previews": "preview",
}
PRIVATE_TABLES = (
    "experience_records",
    "experience_trajectories",
    "experience_trajectory_steps",
    "experience_audit_events",
    "experience_candidate_validations",
    "agent_experience_events",
    "agent_experience_verifications",
    "agent_experience_injections",
    "wavemind_schema_migrations",
)


def invalid_archive():
    return BrainError("invalid_archive", "Brain archive validation failed.")


def safe_path(value):
    path = Path(value).absolute()
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise BrainError("invalid_path", "Linked paths are not supported.")
    return path.resolve()


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


@contextmanager
def readonly(path):
    conn = sqlite3.connect(
        Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA trusted_schema=OFF")
    conn.execute("PRAGMA query_only=ON")
    try:
        yield conn
    finally:
        conn.close()


def schema(conn):
    return {
        (row[0], row[1]): " ".join((row[2] or "").split())
        for row in conn.execute(
            "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
        )
    }


def table_names(conn):
    return [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
        )
    ]


def rows(conn, table):
    return [
        dict(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
    ]


def insert_rows(conn, table, values):
    if values:
        columns = list(values[0])
        conn.executemany(
            f'INSERT INTO "{table}" ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
            ([value[column] for column in columns] for value in values),
        )


def private_template():
    store = SQLiteExperienceStore(":memory:")
    AgentExperienceRuntime(
        ExperienceCompiler(
            store, MemoryFirewall(MemoryFirewallPolicy(namespace="schema"))
        )
    )
    store.conn.row_factory = sqlite3.Row
    return store


def inspect_database(conn, expected_schema, version):
    if (
        schema(conn) != expected_schema
        or conn.execute("PRAGMA user_version").fetchone()[0] != version
    ):
        raise invalid_archive()
    if (
        conn.execute("PRAGMA integrity_check").fetchall()[0][0] != "ok"
        or conn.execute("PRAGMA foreign_key_check").fetchone()
    ):
        raise invalid_archive()
    result = {}
    for table in table_names(conn):
        values = rows(conn, table)
        time_columns = {
            r[1]
            for r in conn.execute(f'PRAGMA table_info("{table}")')
            if r[2] == "REAL"
        }
        for value in values:
            if "schema_version" in value and value["schema_version"] != 1:
                raise invalid_archive()
            for name, field in value.items():
                if (
                    name in time_columns
                    and field is not None
                    and (type(field) not in (int, float) or not math.isfinite(field))
                ):
                    raise invalid_archive()
                if name.endswith("_json") and field is not None:
                    json.loads(
                        field,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                    )
        result[table] = {"count": len(values), "digest": digest(values)}
    return result


def selected_rows(conn, brain_id):
    result = {}
    for table in table_names(conn):
        if table in {"members", "previews"}:
            result[table] = []
            continue
        result[table] = [
            dict(r)
            for r in conn.execute(
                f'SELECT * FROM "{table}" WHERE {"id" if table == "brains" else "brain_id"}=? ORDER BY rowid',
                (brain_id,),
            )
        ]
    # Live memberships and import retry caches are not portable authority.
    result["members"] = []
    result["previews"] = []
    result["dependencies"] = [
        r for r in result["dependencies"] if r["dependent_type"] != "preview"
    ]
    return result


def scrub_unavailable(data):
    """Omit unavailable plaintext before any bytes enter a new SQLite file."""
    forbidden = {
        r["id"] for r in data["sources"] if r["status"] in {"revoked", "deleted"}
    }
    affected = {
        (r["dependent_type"], r["dependent_id"])
        for r in data["dependencies"]
        if r["source_id"] in forbidden
    }
    edges = [
        ((r["origin_type"], r["origin_id"]), (r["dependent_type"], r["dependent_id"]))
        for r in data["dependencies"]
    ]
    edges += [
        (("packet", r["packet_id"]), ("receipt", r["id"])) for r in data["receipts"]
    ]
    edges += [
        (("receipt", r["receipt_id"]), ("outcome", r["id"])) for r in data["outcomes"]
    ]
    while True:
        expanded = affected | {child for origin, child in edges if origin in affected}
        if expanded == affected:
            break
        affected = expanded
    for value in data["sources"]:
        if value["id"] in forbidden:
            value.update(title="", kind="text", readers_json=None, metadata_json="{}")
    for table in ("source_versions", "chunks"):
        data[table] = [r for r in data[table] if r["source_id"] not in forbidden]
    for table, kind in DERIVED.items():
        for value in data[table]:
            if (kind, value["id"]) in affected:
                value["payload_json"] = "{}"
                if "status" in value:
                    value["status"] = "revoked"
                if kind in {"entity", "claim", "relation"}:
                    value["kind"] = "deleted"
    data["brain_packet_basis"] = [
        r
        for r in data["brain_packet_basis"]
        if ("packet", r["packet_id"]) not in affected
    ]
    blocked_namespaces = {
        r["namespace"]
        for r in data["brain_experience_links"]
        if ("outcome", r["outcome_id"]) in affected
    }
    for value in data["outbox"]:
        if value["source_id"] in forbidden:
            value["payload_json"] = "{}"
    return forbidden, blocked_namespaces


def private_rows(conn, namespaces):
    result = {}
    scoped = "namespace IN (SELECT value FROM json_each(?))"
    parameter = encode(sorted(namespaces))
    for table in PRIVATE_TABLES:
        if table in {
            "experience_trajectory_steps",
            "experience_audit_events",
            "experience_candidate_validations",
            "wavemind_schema_migrations",
        }:
            continue
        result[table] = [
            dict(r)
            for r in conn.execute(
                f'SELECT * FROM "{table}" WHERE {scoped} ORDER BY rowid', (parameter,)
            )
        ]
    record_select = f"SELECT id FROM experience_records WHERE {scoped}"
    trajectory_select = f"SELECT id FROM experience_trajectories WHERE {scoped}"
    result["experience_trajectory_steps"] = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM experience_trajectory_steps WHERE trajectory_id IN ({trajectory_select}) ORDER BY rowid",
            (parameter,),
        )
    ]
    result["experience_candidate_validations"] = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM experience_candidate_validations WHERE experience_id IN ({record_select}) ORDER BY rowid",
            (parameter,),
        )
    ]
    result["experience_audit_events"] = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM experience_audit_events WHERE experience_id IN ({record_select}) OR trajectory_id IN ({trajectory_select}) ORDER BY rowid",
            (parameter, parameter),
        )
    ]
    result["wavemind_schema_migrations"] = rows(conn, "wavemind_schema_migrations")
    return result


def write_authority(path, data):
    store = BrainStore(Path(path).parent / "build")
    try:
        with store.transaction(write=True) as target:
            for table in table_names(target):
                insert_rows(target, table, data[table])
        # The source is a committed reconstruction, never our live write TX.
        with closing(sqlite3.connect(path)) as destination:
            store._conn.backup(destination)
    finally:
        store.close()


def write_private(path, data):
    store = private_template()
    try:
        with store.conn:
            store.conn.execute("DELETE FROM wavemind_schema_migrations")
            for table in PRIVATE_TABLES:
                insert_rows(store.conn, table, data[table])
        with closing(sqlite3.connect(path)) as destination:
            store.conn.backup(destination)
    finally:
        store.close()


def validate_bindings(data, brain_id):
    if (
        len(data["brains"]) != 1
        or data["brains"][0]["id"] != brain_id
        or data["members"]
        or data["previews"]
    ):
        raise invalid_archive()
    for table, values in data.items():
        if table != "brains" and any(r["brain_id"] != brain_id for r in values):
            raise invalid_archive()
    packets = {r["id"]: r for r in data["packets"]}
    manifests = {r["packet_id"]: r for r in data["brain_packet_basis"]}
    dependencies = {}
    for r in data["dependencies"]:
        dependencies.setdefault((r["dependent_type"], r["dependent_id"]), set()).add(
            (r["origin_type"], r["origin_id"], r["source_id"])
        )
    for row in packets.values():
        packet = json.loads(row["payload_json"])
        if not packet:
            continue
        if (
            packet.get("brain_id"),
            packet.get("id"),
            packet.get("principal_id"),
            packet.get("revision"),
            packet.get("digest"),
        ) != (brain_id, row["id"], row["principal_id"], row["revision"], row["digest"]):
            raise invalid_archive()
        if digest({k: v for k, v in packet.items() if k != "digest"}) != row["digest"]:
            raise invalid_archive()
        byte_count = len(encode(packet).encode())
        if (
            packet.get("schema") != "wavemind.brain_context.v1"
            or packet.get("expires_at") != row["expires_at"]
            or packet.get("cost")
            != {
                "bytes": byte_count,
                "tokens": (byte_count + 3) // 4,
                "network_calls": 0,
            }
        ):
            raise invalid_archive()
        basis = manifests.get(row["id"])
        if basis is None:
            raise invalid_archive()
        if not (
            basis["legacy"] == 1 and basis["basis_digest"] is None
        ) and not re.fullmatch(r"[0-9a-f]{64}", basis["basis_digest"] or ""):
            raise invalid_archive()
        origins = json.loads(basis["payload_json"])
        if not isinstance(origins, list) or any(
            not isinstance(o, list)
            or len(o) != 3
            or not all(isinstance(v, str) for v in o)
            for o in origins
        ):
            raise invalid_archive()
        if not {tuple(o) for o in origins} <= dependencies.get(
            ("packet", row["id"]), set()
        ):
            raise invalid_archive()
    for row in data["receipts"]:
        receipt = json.loads(row["payload_json"])
        if not receipt:
            continue
        packet = packets[row["packet_id"]]
        if (
            (row["packet_digest"], row["principal_id"])
            != (packet["digest"], packet["principal_id"])
            or receipt.get("packet_digest") != packet["digest"]
            or receipt.get("packet_id") != packet["id"]
            or receipt.get("id") != row["id"]
        ):
            raise invalid_archive()
        if (
            receipt.get("revision") != packet["revision"]
            or not packet["created_at"] <= row["created_at"] < packet["expires_at"]
        ):
            raise invalid_archive()
    for row in data["brain_experience_links"]:
        if (
            re.fullmatch(
                r"brain:" + re.escape(brain_id) + r":[0-9a-f]{64}:[0-9a-f]{64}",
                row["namespace"],
            )
            is None
        ):
            raise invalid_archive()


def validate_private_support(data, private_data):
    records = (
        {}
        if private_data is None
        else {r["id"]: r for r in private_data["experience_records"]}
    )
    for outcome in data["outcomes"]:
        payload = json.loads(outcome["payload_json"])
        if (
            outcome["status"] not in {"verified", "failed"}
            or payload.get("integration_status") != "completed"
        ):
            continue
        mappings = [
            r
            for r in data["brain_experience_links"]
            if r["outcome_id"] == outcome["id"] and r["experience_id"]
        ]
        if not mappings or any(
            r["experience_id"] not in records
            or records[r["experience_id"]]["namespace"] != r["namespace"]
            for r in mappings
        ):
            raise invalid_archive()


def write_archive(path, staging, brain_id, private_state, warnings):
    files = {}
    template = BrainStore(staging / "schema")
    private = private_template()
    try:
        for name, expected, version in (
            (BRAIN, schema(template._conn), 3),
            (PRIVATE, schema(private.conn), 0),
        ):
            file = staging / name
            if not file.exists():
                continue
            if file.stat().st_size > MAX_DATABASE_BYTES:
                raise BrainError(
                    "archive_limit", "Brain archive exceeds supported size."
                )
            with readonly(file) as conn:
                inventory = inspect_database(conn, expected, version)
            files[name] = {
                "size": file.stat().st_size,
                "sha256": sha256(file),
                "schema_version": 3 if name == BRAIN else 1,
                "sqlite_user_version": version,
                "tables": inventory,
            }
    finally:
        template.close()
        private.close()
    manifest = {
        "schema": ARCHIVE_SCHEMA,
        "brain_id": brain_id,
        "created_at": time.time(),
        "files": files,
        "private_state": private_state,
        "warnings": warnings,
    }
    encoded = encode(manifest).encode()
    if (
        len(encoded) > MAX_MANIFEST_BYTES
        or sum(f["size"] for f in files.values()) + len(encoded) > MAX_EXPANDED_BYTES
    ):
        raise BrainError("archive_limit", "Brain archive exceeds supported size.")
    # Stored members have ratio 1 even for highly repetitive legitimate text.
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(MANIFEST, encoded)
        for name in files:
            archive.write(staging / name, name)
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise BrainError("archive_limit", "Brain archive exceeds supported size.")
    return manifest


def read_archive(path, staging):
    try:
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise invalid_archive()
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            names = [m.filename for m in members]
            if (
                len(names) != len(set(names))
                or not {MANIFEST, BRAIN} <= set(names)
                or not set(names) <= {MANIFEST, BRAIN, PRIVATE}
            ):
                raise invalid_archive()
            if sum(m.file_size for m in members) > MAX_EXPANDED_BYTES:
                raise invalid_archive()
            for member in members:
                limit = (
                    MAX_MANIFEST_BYTES
                    if member.filename == MANIFEST
                    else MAX_DATABASE_BYTES
                )
                if (
                    member.file_size > limit
                    or member.file_size
                    > max(1, member.compress_size) * MAX_COMPRESSION_RATIO
                    or member.flag_bits & 1
                    or stat.S_ISLNK(member.external_attr >> 16)
                ):
                    raise invalid_archive()
                with (
                    archive.open(member) as source,
                    (staging / member.filename).open("xb") as target,
                ):
                    remaining = limit
                    while block := source.read(min(1024 * 1024, remaining + 1)):
                        remaining -= len(block)
                        if remaining < 0:
                            raise invalid_archive()
                        target.write(block)
        manifest = json.loads((staging / MANIFEST).read_text(encoding="utf-8"))
        if (
            set(manifest)
            != {
                "schema",
                "brain_id",
                "created_at",
                "files",
                "private_state",
                "warnings",
            }
            or manifest["schema"] != ARCHIVE_SCHEMA
            or re.fullmatch(r"[0-9a-f]{32}", manifest["brain_id"]) is None
        ):
            raise invalid_archive()
        if set(manifest["files"]) != set(names) - {MANIFEST}:
            raise invalid_archive()
        template = BrainStore(staging / "schema")
        private = private_template()
        try:
            for name, expected, version in (
                (BRAIN, schema(template._conn), 3),
                (PRIVATE, schema(private.conn), 0),
            ):
                if name not in manifest["files"]:
                    continue
                metadata = manifest["files"][name]
                file = staging / name
                if (
                    metadata["size"] != file.stat().st_size
                    or metadata["sha256"] != sha256(file)
                    or metadata["schema_version"] != (3 if name == BRAIN else 1)
                    or metadata["sqlite_user_version"] != version
                ):
                    raise invalid_archive()
                with readonly(file) as conn:
                    if inspect_database(conn, expected, version) != metadata["tables"]:
                        raise invalid_archive()
                    if name == PRIVATE:
                        validate_runtime_schema(conn, EXPERIENCE_COMPONENT)
            with readonly(staging / BRAIN) as conn:
                data = {t: rows(conn, t) for t in table_names(conn)}
            validate_bindings(data, manifest["brain_id"])
            private_data = None
            if PRIVATE in manifest["files"]:
                with readonly(staging / PRIVATE) as conn:
                    private_data = {t: rows(conn, t) for t in PRIVATE_TABLES}
                    projected = private_rows(
                        conn, {r["namespace"] for r in data["brain_experience_links"]}
                    )
                    if private_data != projected:
                        raise invalid_archive()
            if manifest["private_state"] not in {
                "included",
                "absent_with_pending_lineage",
                "unused_or_purged",
            } or (manifest["private_state"] == "included") != (
                private_data is not None
            ):
                raise invalid_archive()
            validate_private_support(data, private_data)
            return manifest, data, private_data
        finally:
            template.close()
            private.close()
    except BrainError:
        raise
    except (
        OSError,
        sqlite3.Error,
        ValueError,
        TypeError,
        KeyError,
        zipfile.BadZipFile,
        RuntimeError,
    ):
        raise invalid_archive() from None
