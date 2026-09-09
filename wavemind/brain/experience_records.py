"""Private outcome history, immutable basis identities and live provenance."""

import hashlib
import json

from .access import _not_found, require_access
from .models import BrainError
from . import reconcile
from .sources import context_pending


def encode(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def origins_for(conn, brain_id, kind, rid):
    return {
        tuple(row)
        for row in conn.execute(
            "SELECT origin_type,origin_id,source_id FROM dependencies WHERE brain_id=? AND dependent_type=? AND dependent_id=?",
            (brain_id, kind, rid),
        )
    }


def authorize_record(conn, *, principal, brain_id, kind, rid):
    origins = origins_for(conn, brain_id, kind, rid)
    if not origins:
        raise _not_found()
    require_access(conn, principal, brain_id, "read", {o[2] for o in origins})
    return origins


def register(conn, brain_id, kind, rid, origins):
    for ot, oi, sid in origins:
        conn.execute(
            "INSERT OR IGNORE INTO dependencies VALUES (?,?,?,?,?,?)",
            (brain_id, kind, rid, ot, oi, sid),
        )


def historical_receipt(conn, *, principal, brain_id, receipt_id):
    require_access(conn, principal, brain_id, "read")
    if not isinstance(receipt_id, str):
        raise _not_found()
    receipt = conn.execute(
        "SELECT * FROM receipts WHERE brain_id=? AND id=?", (brain_id, receipt_id)
    ).fetchone()
    if receipt is None:
        raise _not_found()
    origins = authorize_record(
        conn, principal=principal, brain_id=brain_id, kind="receipt", rid=receipt_id
    )
    row = conn.execute(
        "SELECT * FROM packets WHERE brain_id=? AND id=?",
        (brain_id, receipt["packet_id"]),
    ).fetchone()
    if row is None:
        raise _not_found()
    origins |= authorize_record(
        conn, principal=principal, brain_id=brain_id, kind="packet", rid=row["id"]
    )
    try:
        r, p = json.loads(receipt["payload_json"]), json.loads(row["payload_json"])
        valid = (
            r["id"] == receipt_id
            and r["packet_id"] == row["id"]
            and r["packet_digest"]
            == receipt["packet_digest"]
            == row["digest"]
            == p["digest"]
            and digest({k: v for k, v in p.items() if k != "digest"}) == p["digest"]
            and p["schema"] == "wavemind.brain_context.v1"
            and p["brain_id"] == brain_id
            and p["id"] == row["id"]
            and r["revision"] == p["revision"] == row["revision"]
            and p["principal_id"] == row["principal_id"] == receipt["principal_id"]
            and p["coverage"]["status"] != "pending"
            and row["created_at"]
            <= receipt["created_at"]
            < row["expires_at"]
            == p["expires_at"]
            and p["cost"]
            == {
                "bytes": len(encode(p).encode()),
                "tokens": (len(encode(p).encode()) + 3) // 4,
                "network_calls": 0,
            }
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise BrainError("invalid_receipt", "Receipt integrity check failed.")
    return r, p, origins


def basis_origins(conn, *, principal, brain_id, packet):
    row = conn.execute(
        "SELECT payload_json FROM brain_packet_basis WHERE brain_id=? AND packet_id=?",
        (brain_id, packet["id"]),
    ).fetchone()
    try:
        origins = {tuple(o) for o in json.loads(row[0])} if row else set()
        valid = origins and all(
            len(o) == 3
            and o[0] in {"source", *reconcile.TABLES}
            and all(isinstance(v, str) for v in o)
            for o in origins
        )
        valid &= origins <= origins_for(conn, brain_id, "packet", packet["id"])
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise _not_found()
    require_access(conn, principal, brain_id, "read", {o[2] for o in origins})
    return origins


BASIS_FIELDS = (
    "kind",
    "name",
    "key",
    "content",
    "citation_ids",
    "depends_on",
    "entity_ids",
    "supersedes",
    "from_id",
    "to_id",
    "valid_from",
    "valid_until",
    "effective_valid_from",
    "effective_valid_until",
    "effective_empty",
    "_review",
    "needs_recheck",
)


def basis_fingerprint(conn, *, brain_id, project_id, origins):
    values = {
        "project_id": project_id,
        "origins": sorted(origins),
        "sources": [],
        "records": [],
        "citations": [],
    }
    for sid in sorted({o[2] for o in origins}):
        row = conn.execute(
            "SELECT id,version,digest,status FROM source_versions WHERE brain_id=? AND source_id=? ORDER BY version DESC LIMIT 1",
            (brain_id, sid),
        ).fetchone()
        if row is None:
            raise _not_found()
        values["sources"].append({"source_id": sid, **dict(row)})
    for kind, rid in sorted(
        {(o[0], o[1]) for o in origins if o[0] in reconcile.TABLES}
    ):
        row = conn.execute(
            f"SELECT status,payload_json FROM {reconcile.TABLES[kind]} WHERE brain_id=? AND id=?",
            (brain_id, rid),
        ).fetchone()
        if row is None or row[1] == "{}":
            raise _not_found()
        data = json.loads(row[1])
        values["records"].append(
            {
                "type": kind,
                "id": rid,
                "status": row[0],
                **{k: data[k] for k in BASIS_FIELDS if k in data},
            }
        )
        for cid in sorted(data.get("citation_ids", [])):
            c = conn.execute(
                "SELECT id,version_id,source_id FROM chunks WHERE brain_id=? AND id=?",
                (brain_id, cid),
            ).fetchone()
            if c is None:
                raise _not_found()
            values["citations"].append(dict(c))
    return digest(values)


def live_basis(conn, *, principal, brain_id, data, moment):
    origins = {tuple(o) for o in data["_basis_origins"]}
    require_access(conn, principal, brain_id, "read", {o[2] for o in origins})
    eligible = not context_pending(conn, brain_id=brain_id)
    packet = conn.execute(
        "SELECT p.status FROM packets p JOIN receipts r ON r.brain_id=p.brain_id AND r.packet_id=p.id WHERE r.brain_id=? AND r.id=?",
        (brain_id, data["receipt_id"]),
    ).fetchone()
    eligible &= (
        packet is not None and packet[0] == "active" and data["_basis"] is not None
    )
    transitions, reached = set(), set(origins)
    for kind, rid in sorted(
        {(o[0], o[1]) for o in origins if o[0] in reconcile.TABLES}
    ):
        current, bounds, dependencies = reconcile.context_record_state(
            conn,
            principal=principal,
            brain_id=brain_id,
            record_type=kind,
            record_id=rid,
            as_of=moment,
        )
        eligible &= current
        transitions.update(bounds)
        reached.update(dependencies)
    eligible &= (
        basis_fingerprint(
            conn, brain_id=brain_id, project_id=data["project_id"], origins=origins
        )
        == data["_basis"]
    )
    return eligible, transitions, reached


def endpoint_record(conn, brain_id, rid, kind):
    """Normalize persisted endpoints for the existing bounded graph traversal.

    This is a load adapter, not authorization or a second graph walker.
    Receipt application expiry is an endpoint bound; historical reporting and
    reusable procedure state use their separate explicit policies.
    """
    if kind == "receipt":
        row = conn.execute(
            "SELECT r.*,p.status packet_status,p.expires_at,p.payload_json packet_json FROM receipts r JOIN packets p ON p.brain_id=r.brain_id AND p.id=r.packet_id WHERE r.brain_id=? AND r.id=?",
            (brain_id, rid),
        ).fetchone()
        if row is None or row["payload_json"] == "{}" or row["packet_json"] == "{}":
            return None
        data = json.loads(row["payload_json"])
        packet = json.loads(row["packet_json"])
        active = (
            row["packet_status"] == "active"
            and packet.get("coverage", {}).get("status") != "pending"
        )
        data.update(
            _review="approved",
            _endpoint_until=row["expires_at"],
            citation_ids=[],
            depends_on=sorted(
                {
                    o[1]
                    for o in origins_for(conn, brain_id, kind, rid)
                    if o[0] != "source"
                }
            ),
        )
        return {
            "type": kind,
            "status": "active" if active else "proposed",
            "data": data,
        }
    if kind == "outcome":
        row = conn.execute(
            "SELECT * FROM outcomes WHERE brain_id=? AND id=?", (brain_id, rid)
        ).fetchone()
        if row is None or row["payload_json"] == "{}":
            return None
        data = json.loads(row["payload_json"])
        verification = data.get("verification")
        active = (
            row["status"] == "verified"
            and verification
            and verification.get("success") is True
            and bool(verification.get("evidence_citation_ids"))
        )
        data.update(
            _review="approved" if active else "none",
            depends_on=[row["receipt_id"]],
            citation_ids=sorted(
                set(data.get("evidence_citation_ids", []))
                | set((verification or {}).get("evidence_citation_ids", []))
            ),
        )
        return {
            "type": kind,
            "status": "active" if active else "proposed",
            "data": data,
        }
    return None
