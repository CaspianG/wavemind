"""Explicit owner decisions, temporal claims, and all-origin provenance.

Payload _review is internal decision intent, never an input field. Approval
does not assert causal truth. Stored status alone is insufficient for context:
consumers must also check source authority, needs_recheck and effective bounds.
"""

import json
import math
import re
import time
from collections import defaultdict, deque
from uuid import uuid4

from .access import _not_found, allowed_sources, require_access
from .models import BrainError, Principal, bounded_text
from .sources import (
    context_pending,
    dependency_edges,
    invalidate_dependents,
    mark_context_pending,
    resolve_citation,
)
from .store import record_change


TABLES = {"claim": "claims", "entity": "entities", "relation": "relations"}
CLAIM_KINDS = {"fact", "goal", "constraint", "decision", "commitment"}
ENTITY_KINDS = {"person", "organization", "project", "client", "artifact"}
RELATION_KINDS = {
    "related_to",
    "supersedes",
    "depends_on",
    "justified_by",
    "action_outcome",
}
MAX_RECORDS = 10000


def _invalid():
    return BrainError("invalid_input", "Invalid memory request.")


def _identifier(value):
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None
    ):
        raise _invalid()
    return value


def _text(value, maximum=65536):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _invalid()
    if any((ord(c) < 32 and c not in "\n\r\t") or ord(c) == 127 for c in value):
        raise _invalid()
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise _invalid() from None
    return value


def _ids(value, *, required=False):
    if not isinstance(value, list) or len(value) > 100 or (required and not value):
        raise _invalid()
    values = [_identifier(item) for item in value]
    if len(set(values)) != len(values):
        raise _invalid()
    return values


def _timestamp(value):
    if value is not None:
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid:
            raise _invalid()
    return value


def overlaps(a_start, a_end, b_start, b_end):
    return (a_end is None or b_start is None or b_start < a_end) and (
        b_end is None or a_start is None or a_start < b_end
    )


def _start(data):
    return (
        data.get("valid_from")
        if data.get("valid_from") is not None
        else data.get("event_time")
    )


def record_sources(conn, *, brain_id, record_type, record_id):
    """All materialized originating sources, empty means unproven/ineligible."""
    return {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT source_id FROM dependencies WHERE brain_id=? AND dependent_type=? AND dependent_id=?",
            (brain_id, record_type, record_id),
        )
    }


def _load(conn, brain_id):
    records = {}
    for kind, table in TABLES.items():
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE brain_id=? ORDER BY id", (brain_id,)
        ):
            data = json.loads(row["payload_json"])
            if data:
                records[row["id"]] = {
                    "type": kind,
                    "status": row["status"],
                    "data": data,
                }
    return records


def _prerequisites(record):
    data = record["data"]
    ids = set(data.get("depends_on", [])) | set(data.get("entity_ids", []))
    if record["type"] == "relation":
        ids.update((data["from_id"], data["to_id"]))
    return ids


def _origins(record):
    data = record["data"]
    ids = _prerequisites(record)
    if data.get("supersedes"):
        ids.add(data["supersedes"])
    return ids


def _order(records):
    """Iterative topological sort avoids recursion limits and rejects cycles."""
    remaining, children = {}, defaultdict(set)
    for rid, row in records.items():
        parents = _origins(row) & records.keys()
        remaining[rid] = len(parents)
        for parent in parents:
            children[parent].add(rid)
    ready = deque(sorted(rid for rid, count in remaining.items() if not count))
    result = []
    while ready:
        rid = ready.popleft()
        result.append(rid)
        for child in sorted(children[rid]):
            remaining[child] -= 1
            if not remaining[child]:
                ready.append(child)
    if len(result) != len(records):
        raise _invalid()
    return result


def _save(conn, brain_id, rid, row):
    conn.execute(
        f"UPDATE {TABLES[row['type']]} SET status=?,payload_json=? WHERE brain_id=? AND id=?",
        (
            row["status"],
            json.dumps(row["data"], ensure_ascii=False, allow_nan=False),
            brain_id,
            rid,
        ),
    )


def _public(rid, row):
    return {
        **{k: v for k, v in row["data"].items() if not k.startswith("_")},
        "id": rid,
        "status": row["status"],
    }


def record_eligible(conn, *, principal, brain_id, record_type, record_id, as_of):
    """Read-only, bounded as-of verification of all applicable prerequisites.

    Superseded claims remain eligible within their preserved effective history.
    Supersession lineage needs reviewed/fresh state, but its own effective time
    need not include the replacement's later time. Explicit ordinary edges
    still require as_of validity, including an ID also named by supersedes.
    Missing/inaccessible data raises not_found. Graph cycle/overflow raises
    dependency_cycle/dependency_limit without writing from this read snapshot;
    a write consumer must mark pending and discard partially collected context.
    """
    require_access(conn, principal, brain_id, "read")
    if _timestamp(as_of) is None:
        raise _invalid()
    records, completed, path, authorized_sources = {}, set(), set(), set()
    pending = context_pending(conn, brain_id=brain_id)
    lookup = (
        """SELECT r.*, (SELECT json_group_array(json_array(d.origin_type,d.origin_id,d.source_id))
        FROM dependencies d WHERE d.brain_id=? AND d.dependent_type=r.record_type AND d.dependent_id=?) AS origins_json
        FROM ("""
        + " UNION ALL ".join(
            f"SELECT '{kind}' AS record_type,status,payload_json FROM {table} WHERE brain_id=? AND id=? AND payload_json!='{{}}'"
            for kind, table in TABLES.items()
        )
        + ") r"
    )
    stack = [(record_id, True, False, record_type)]
    while stack:
        rid, temporal, finished, expected_type = stack.pop()
        state = (rid, temporal)
        if finished:
            path.remove(rid)
            completed.add(state)
            continue
        if rid in path:
            raise BrainError(
                "dependency_cycle", "Dependency cycle prevents verification."
            )
        if state in completed:
            if expected_type is not None and records[rid]["type"] != expected_type:
                raise _not_found()
            continue
        if rid not in records:
            if len(records) == MAX_RECORDS:
                raise BrainError(
                    "dependency_limit", "Dependency verification limit reached."
                )
            # Load only reached records: a deep unrelated history cannot widen
            # the traversal or make a bounded eligibility check unbounded.
            found = conn.execute(lookup, (brain_id, rid) * (len(TABLES) + 1)).fetchall()
            if len(found) != 1:
                raise _not_found()
            stored = found[0]
            records[rid] = {
                "type": stored["record_type"],
                "status": stored["status"],
                "data": json.loads(stored["payload_json"]),
                "origins": json.loads(stored["origins_json"]),
            }
        row = records[rid]
        if expected_type is not None and row["type"] != expected_type:
            raise _not_found()
        sources = {origin[2] for origin in row["origins"]}
        if not sources:
            raise _not_found()
        # This cache is local to this call and the immutable caller-owned
        # transaction. It cannot outlive a source ACL or membership snapshot.
        unseen_sources = sources - authorized_sources
        if unseen_sources:
            require_access(conn, principal, brain_id, "read", unseen_sources)
            authorized_sources.update(unseen_sources)
        data = row["data"]
        if pending or data.get("needs_recheck") or data.get("_review") != "approved":
            return False
        if row["status"] not in ("active", "superseded"):
            return False
        if row["type"] != "claim" and row["status"] != "active":
            return False
        if temporal and row["type"] == "claim":
            start, end = (
                data.get("effective_valid_from"),
                data.get("effective_valid_until"),
            )
            if (
                data.get("effective_empty")
                or (start is not None and as_of < start)
                or (end is not None and as_of >= end)
            ):
                return False
        path.add(rid)
        stack.append((rid, temporal, True, expected_type))
        ordinary = _prerequisites(row)
        origin_types = {}
        for kind, parent, _ in row["origins"]:
            if kind == "source":
                continue
            if kind not in TABLES:
                raise _not_found()
            origin_types[parent] = kind
            if parent != data.get("supersedes"):
                ordinary.add(parent)
        for parent in sorted(ordinary, reverse=True):
            stack.append((parent, True, False, origin_types.get(parent)))
        if data.get("supersedes") and data["supersedes"] not in ordinary:
            stack.append((data["supersedes"], False, False, "claim"))
    return True


def _require_record(conn, principal, brain_id, rid, records, record_type=None):
    row = records.get(rid)
    if row is None or (record_type is not None and row["type"] != record_type):
        raise _not_found()
    sources = record_sources(
        conn, brain_id=brain_id, record_type=row["type"], record_id=rid
    )
    if not sources:
        raise _not_found()
    require_access(conn, principal, brain_id, "read", sources)
    return row


def _evidence(conn, principal, brain_id, citation_ids):
    return {
        resolve_citation(conn, principal=principal, brain_id=brain_id, citation_id=cid)[
            "source_id"
        ]
        for cid in _ids(citation_ids, required=True)
    }


def _register(conn, brain_id, rid, row, sources):
    for sid in sources:
        conn.execute(
            "INSERT OR IGNORE INTO dependencies VALUES (?,?,?,'source',?,?)",
            (brain_id, row["type"], rid, sid, sid),
        )


def _check_capacity(conn, brain_id, additional):
    count = sum(
        conn.execute(
            f"SELECT count(*) FROM {table} WHERE brain_id=? AND status!='revoked'",
            (brain_id,),
        ).fetchone()[0]
        for table in TABLES.values()
    )
    if count + additional > MAX_RECORDS:
        raise BrainError("dependency_limit", "Memory dependency limit reached.")


def _basis_signature(row):
    data = row["data"]
    return (
        row["status"],
        bool(data.get("needs_recheck")),
        data.get("effective_valid_from"),
        data.get("effective_valid_until"),
        bool(data.get("effective_empty")),
    )


def _reconcile(conn, brain_id):
    records = _load(conn, brain_id)
    if sum(row["status"] != "revoked" for row in records.values()) > MAX_RECORDS:
        mark_context_pending(conn, brain_id=brain_id)
        return records
    previous = {rid: row["status"] for rid, row in records.items()}
    previous_basis = {rid: _basis_signature(row) for rid, row in records.items()}
    order = _order(records)
    governing = defaultdict(set)
    # Materialize every origin after out-of-order originals arrive. These
    # links never authorize a read by themselves; callers still need all ACLs.
    for rid in order:
        row = records[rid]
        for parent in _origins(row):
            target = records.get(parent)
            if target is None:
                continue
            for sid in record_sources(
                conn, brain_id=brain_id, record_type=target["type"], record_id=parent
            ):
                conn.execute(
                    "INSERT OR IGNORE INTO dependencies VALUES (?,?,?,?,?,?)",
                    (brain_id, row["type"], rid, target["type"], parent, sid),
                )
    for rid in order:
        row, data = records[rid], records[rid]["data"]
        data.pop("pending_reason", None)
        approved = data.get("_review") == "approved"
        if data.get("_review") == "rejected" or row["status"] == "revoked":
            row["status"] = "revoked"
            continue
        row["status"] = (
            "active" if approved and not data.get("needs_recheck") else "proposed"
        )
        if data.get("needs_recheck"):
            data["pending_reason"] = "needs_recheck"
        if row["type"] == "claim":
            data["effective_valid_from"] = _start(data)
            data["effective_valid_until"] = data.get("valid_until")
            data["effective_empty"] = False
            parent = data.get("supersedes")
            if parent:
                target = records.get(parent)
                if _start(data) is None:
                    row["status"], data["pending_reason"] = (
                        "proposed",
                        "needs_effective_time",
                    )
                elif (
                    target is None
                    or target["type"] != "claim"
                    or target["data"].get("_review") != "approved"
                ):
                    row["status"], data["pending_reason"] = (
                        "proposed",
                        "unresolved_original",
                    )
                elif (
                    target["data"].get("key") != data["key"]
                    or target["data"].get("kind") != data["kind"]
                ):
                    row["status"], data["pending_reason"] = (
                        "proposed",
                        "incompatible_original",
                    )
                elif target["data"].get("needs_recheck"):
                    # New correction proposals must inherit a stale basis too;
                    # source invalidation cannot have visited a not-yet-existing row.
                    data["needs_recheck"] = True
                    row["status"], data["pending_reason"] = "proposed", "needs_recheck"
                elif target["status"] not in ("active", "superseded"):
                    row["status"], data["pending_reason"] = (
                        "proposed",
                        "unusable_original",
                    )
        ordinary = _prerequisites(row)
        if any(records[p]["status"] != "active" for p in ordinary if p in records):
            row["status"], data["pending_reason"] = "proposed", "dependency_unreviewed"
            if previous[rid] in ("active", "superseded"):
                data["needs_recheck"] = True
    # Reviewed corrections clip predecessors even while evidence is awaiting
    # recheck. That cannot resurrect an old assertion as current. Rejection
    # removes the correction decision, and therefore removes its clipping.
    for rid in order:
        row, data = records[rid], records[rid]["data"]
        parent = data.get("supersedes")
        if (
            row["type"] != "claim"
            or data.get("_review") != "approved"
            or parent not in records
            or _start(data) is None
        ):
            continue
        original = records[parent]
        base = original["data"]
        if (
            original["type"] != "claim"
            or base.get("_review") != "approved"
            or base.get("key") != data["key"]
            or base.get("kind") != data["kind"]
        ):
            continue
        boundary = _start(data)
        old_end = base.get("effective_valid_until")
        base["effective_valid_until"] = (
            boundary if old_end is None else min(old_end, boundary)
        )
        if (
            base["effective_valid_from"] is not None
            and base["effective_valid_until"] <= base["effective_valid_from"]
        ):
            base["effective_valid_until"] = base["effective_valid_from"]
            base["effective_empty"] = True
        governing[parent].add(rid)
        if original["status"] == "active":
            original["status"] = "superseded"
    candidates = [
        (rid, row)
        for rid, row in records.items()
        if row["type"] == "claim"
        and row["status"] in ("active", "superseded")
        and not row["data"]["effective_empty"]
    ]
    for index, (first_id, first) in enumerate(candidates):
        a = first["data"]
        for second_id, second in candidates[index + 1 :]:
            b = second["data"]
            if (
                a["kind"] == b["kind"]
                and a["key"] == b["key"]
                and a["content"] != b["content"]
                and overlaps(
                    a["effective_valid_from"],
                    a["effective_valid_until"],
                    b["effective_valid_from"],
                    b["effective_valid_until"],
                )
            ):
                first["status"] = second["status"] = "conflicted"
                governing[first_id].add(second_id)
                governing[second_id].add(first_id)
    for rid in order:
        row = records[rid]
        ordinary = _prerequisites(row)
        original = records.get(row["data"].get("supersedes"))
        unusable_original = original is not None and (
            original["status"] not in ("active", "superseded")
            or original["data"].get("needs_recheck")
        )
        if row["status"] in ("active", "superseded") and (
            unusable_original
            or any(records[p]["status"] != "active" for p in ordinary if p in records)
        ):
            row["status"] = "proposed"
            row["data"]["pending_reason"] = "dependency_unreviewed"
            if previous[rid] in ("active", "superseded"):
                row["data"]["needs_recheck"] = True
        _save(conn, brain_id, rid, row)
    # Propagate governing provenance to a fixed point. Cycles in this read
    # provenance graph are harmless unions, not semantic dependency cycles.
    source_sets = {
        rid: record_sources(
            conn, brain_id=brain_id, record_type=row["type"], record_id=rid
        )
        for rid, row in records.items()
    }
    children = defaultdict(set)
    for rid, row in records.items():
        for origin in (_origins(row) | governing[rid]) & records.keys():
            children[origin].add(rid)
    queue = deque(order)
    queued = set(order)
    while queue:
        origin = queue.popleft()
        queued.discard(origin)
        for child in children[origin]:
            new = source_sets[origin] - source_sets[child]
            if new:
                source_sets[child].update(new)
                if child not in queued:
                    queue.append(child)
                    queued.add(child)
    for rid, row in records.items():
        _register(conn, brain_id, rid, row, source_sets[rid])
        if (
            previous[rid] in ("active", "superseded")
            and row["status"] == "proposed"
            and row["data"].get("needs_recheck")
        ):
            invalidate_dependents(conn, brain_id=brain_id, seeds={(row["type"], rid)})
    # Invalidation may have changed descendants already visited above.
    records = _load(conn, brain_id)
    changed_basis = {
        (row["type"], rid)
        for rid, row in records.items()
        if previous_basis[rid] != _basis_signature(row)
    }
    if changed_basis:
        # A packet can depend directly on a conflicted or temporally clipped
        # claim. Its invalidation must not rely on an intermediate semantic row
        # becoming proposed, nor require the correction itself to be rechecked.
        invalidate_dependents(
            conn, brain_id=brain_id, seeds=changed_basis, context_only=True
        )
    return records


class Reconciliation:
    def __init__(self, store):
        self.store = store

    def create_entity(
        self,
        *,
        principal: Principal,
        brain_id: str,
        kind: str,
        name: str,
        citation_ids: list[str],
    ) -> dict:
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "propose")
            sources = _evidence(conn, principal, brain_id, citation_ids)
            _check_capacity(conn, brain_id, 1)
            if not isinstance(kind, str) or kind not in ENTITY_KINDS:
                raise _invalid()
            rid = uuid4().hex
            data = {
                "kind": kind,
                "name": _text(bounded_text(name, maximum=500), 500),
                "citation_ids": citation_ids,
                "registered_at": time.time(),
                "_review": "none",
            }
            row = {"type": "entity", "status": "proposed", "data": data}
            conn.execute(
                "INSERT INTO entities(brain_id,id,kind,payload_json) VALUES (?,?,?,?)",
                (brain_id, rid, kind, json.dumps(data)),
            )
            _register(conn, brain_id, rid, row, sources)
            record_change(
                conn, brain_id=brain_id, kind="entity_proposed", record_id=rid
            )
            return _public(rid, row)

    def propose_claims(
        self, *, principal: Principal, brain_id: str, claims: list[dict]
    ) -> list[dict]:
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "propose")
            require_access(conn, principal, brain_id, "read")
            if not isinstance(claims, list) or not 1 <= len(claims) <= 100:
                raise _invalid()
            _check_capacity(conn, brain_id, len(claims))
            records, added = _load(conn, brain_id), []
            for value in claims:
                required = {"kind", "content", "key", "citation_ids"}
                if (
                    not isinstance(value, dict)
                    or not required <= value.keys()
                    or not value.keys()
                    <= required
                    | {
                        "id",
                        "entity_ids",
                        "depends_on",
                        "supersedes",
                        "valid_from",
                        "valid_until",
                        "event_time",
                    }
                ):
                    raise _invalid()
                data = dict(value)
                rid = _identifier(data.pop("id", uuid4().hex))
                if (
                    rid in records
                    or conn.execute(
                        "SELECT 1 FROM claims WHERE brain_id=? AND id=?",
                        (brain_id, rid),
                    ).fetchone()
                ):
                    raise _not_found()
                if not isinstance(data["kind"], str) or data["kind"] not in CLAIM_KINDS:
                    raise _invalid()
                _text(data["content"])
                _text(bounded_text(data["key"], maximum=500), 500)
                for field in ("valid_from", "valid_until", "event_time"):
                    data[field] = _timestamp(data.get(field))
                start, end = _start(data), data["valid_until"]
                if start is not None and end is not None and start >= end:
                    raise _invalid()
                for field in ("entity_ids", "depends_on"):
                    data[field] = _ids(data.get(field, []))
                if data.get("supersedes") is not None:
                    _identifier(data["supersedes"])
                sources = _evidence(conn, principal, brain_id, data["citation_ids"])
                data.update(registered_at=time.time(), _review="none")
                row = {"type": "claim", "status": "proposed", "data": data}
                records[rid] = row
                conn.execute(
                    "INSERT INTO claims(brain_id,id,kind,valid_from,valid_until,recorded_at,payload_json) VALUES (?,?,?,?,?,?,?)",
                    (
                        brain_id,
                        rid,
                        data["kind"],
                        data["valid_from"],
                        end,
                        data["registered_at"],
                        json.dumps(data),
                    ),
                )
                _register(conn, brain_id, rid, row, sources)
                added.append(rid)
            _order(records)
            for rid in added:
                data = records[rid]["data"]
                for target in data["entity_ids"]:
                    _require_record(
                        conn, principal, brain_id, target, records, "entity"
                    )
                for target in data["depends_on"]:
                    _require_record(conn, principal, brain_id, target, records)
                if data.get("supersedes") in records:
                    _require_record(
                        conn, principal, brain_id, data["supersedes"], records, "claim"
                    )
                record_change(
                    conn, brain_id=brain_id, kind="claim_proposed", record_id=rid
                )
            records = _reconcile(conn, brain_id)
            # Re-resolve full provenance after a same-batch dependency chain.
            return [
                _public(rid, _require_record(conn, principal, brain_id, rid, records))
                for rid in added
            ]

    def review_claims(
        self, *, principal: Principal, brain_id: str, claim_ids: list[str], action: str
    ) -> list[dict]:
        return self._review(
            principal=principal,
            brain_id=brain_id,
            record_type="claim",
            record_ids=claim_ids,
            action=action,
        )

    def review_records(
        self,
        *,
        principal: Principal,
        brain_id: str,
        record_type: str,
        record_ids: list[str],
        action: str,
    ) -> list[dict]:
        if record_type not in ("entity", "relation"):
            raise _invalid()
        return self._review(
            principal=principal,
            brain_id=brain_id,
            record_type=record_type,
            record_ids=record_ids,
            action=action,
        )

    def _review(self, *, principal, brain_id, record_type, record_ids, action):
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "review")
            require_access(conn, principal, brain_id, "read")
            if action not in ("approve", "reject", "recheck"):
                raise _invalid()
            ids, records = _ids(record_ids, required=True), _load(conn, brain_id)
            review_order = (
                [rid for rid in _order(records) if rid in ids]
                if action == "recheck"
                else ids
            )
            if len(review_order) != len(ids):
                raise _not_found()
            for rid in review_order:
                row = _require_record(
                    conn, principal, brain_id, rid, records, record_type
                )
                data = row["data"]
                _evidence(conn, principal, brain_id, data["citation_ids"])
                if action == "reject" and data.get("_review") == "approved":
                    invalidate_dependents(
                        conn, brain_id=brain_id, seeds={(record_type, rid)}
                    )
                if action == "recheck":
                    ordinary = _prerequisites(row)
                    data["needs_recheck"] = any(
                        records[p]["status"] != "active"
                        or records[p]["data"].get("needs_recheck")
                        for p in ordinary
                        if p in records
                    )
                    original = records.get(data.get("supersedes"))
                    if original is not None and (
                        original["data"].get("needs_recheck")
                        or original["data"].get("_review") != "approved"
                    ):
                        data["needs_recheck"] = True
                data["_review"] = "rejected" if action == "reject" else "approved"
                row["status"] = "revoked" if action == "reject" else "proposed"
                _save(conn, brain_id, rid, row)
                record_change(
                    conn,
                    brain_id=brain_id,
                    kind=record_type + "_" + action,
                    record_id=rid,
                )
                if action == "recheck":
                    records = _reconcile(conn, brain_id)
            records = _reconcile(conn, brain_id)
            return [_public(rid, records[rid]) for rid in ids]

    def recheck_dependencies(self, *, principal: Principal, brain_id: str) -> dict:
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "review")
            require_access(conn, principal, brain_id, "read")
            record_change(
                conn,
                brain_id=brain_id,
                kind="dependencies_rechecked",
                record_id=brain_id,
            )
            records = {
                rid: row
                for rid, row in _load(conn, brain_id).items()
                if row["status"] != "revoked"
                and row["data"].get("_review") != "rejected"
            }
            nodes = set()
            for kind, table in {
                "source": "sources",
                **TABLES,
                "packet": "packets",
                "preview": "previews",
                "outcome": "outcomes",
            }.items():
                for row in conn.execute(
                    f"SELECT id,status FROM {table} WHERE brain_id=?", (brain_id,)
                ):
                    if row["status"] not in (
                        "revoked",
                        "deleted",
                        "cancelled",
                        "expired",
                        "committed",
                        "quarantined",
                    ):
                        nodes.add((kind, row["id"]))
                        if len(nodes) > MAX_RECORDS:
                            mark_context_pending(conn, brain_id=brain_id)
                            return {"pending": True, "reason": "dependency_limit"}
            for row in conn.execute(
                "SELECT id,packet_id FROM receipts WHERE brain_id=?", (brain_id,)
            ):
                if ("packet", row["packet_id"]) in nodes:
                    nodes.add(("receipt", row["id"]))
                    if len(nodes) > MAX_RECORDS:
                        mark_context_pending(conn, brain_id=brain_id)
                        return {"pending": True, "reason": "dependency_limit"}
            try:
                _order(records)
            except BrainError:
                mark_context_pending(conn, brain_id=brain_id, reason="dependency_cycle")
                return {"pending": True, "reason": "dependency_cycle"}
            # Validate stored graph edges too, including legacy packet/receipt
            # paths that are not encoded in semantic payload fields.
            graph = defaultdict(set)
            for origin, child in dependency_edges(conn, brain_id=brain_id):
                if child in nodes and origin not in nodes:
                    mark_context_pending(
                        conn, brain_id=brain_id, reason="unresolved_dependency"
                    )
                    return {"pending": True, "reason": "unresolved_dependency"}
                if origin in nodes and child in nodes:
                    graph[child].add(origin)
            pending_nodes = {node: len(graph[node]) for node in nodes}
            children = defaultdict(set)
            for child, parents in graph.items():
                for parent in parents:
                    children[parent].add(child)
            queue = deque(node for node, count in pending_nodes.items() if count == 0)
            visited = set()
            while queue:
                node = queue.popleft()
                visited.add(node)
                for child in children[node]:
                    pending_nodes[child] -= 1
                    if pending_nodes[child] == 0:
                        queue.append(child)
            if len(visited) != len(nodes):
                mark_context_pending(conn, brain_id=brain_id, reason="dependency_cycle")
                return {"pending": True, "reason": "dependency_cycle"}
            for rid, row in records.items():
                sources = record_sources(
                    conn, brain_id=brain_id, record_type=row["type"], record_id=rid
                )
                if not sources:
                    mark_context_pending(
                        conn, brain_id=brain_id, reason="unresolved_dependency"
                    )
                    return {"pending": True, "reason": "unresolved_dependency"}
                require_access(conn, principal, brain_id, "read", sources)
            conn.execute(
                "UPDATE brain_context_state SET pending=0,reason=NULL WHERE brain_id=?",
                (brain_id,),
            )
            return {"pending": False, "reason": None}

    def add_relation(
        self, *, principal: Principal, brain_id: str, relation: dict
    ) -> dict:
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "propose")
            required = {"kind", "from_id", "to_id", "citation_ids"}
            if (
                not isinstance(relation, dict)
                or not required <= relation.keys()
                or not relation.keys() <= required | {"depends_on"}
            ):
                raise _invalid()
            data = dict(relation)
            if not isinstance(data["kind"], str) or data["kind"] not in RELATION_KINDS:
                raise _invalid()
            sources = _evidence(conn, principal, brain_id, data["citation_ids"])
            _check_capacity(conn, brain_id, 1)
            records = _load(conn, brain_id)
            data["depends_on"] = _ids(data.get("depends_on", []))
            for rid in [data["from_id"], data["to_id"], *data["depends_on"]]:
                _require_record(conn, principal, brain_id, _identifier(rid), records)
            rid = uuid4().hex
            data.update(registered_at=time.time(), _review="none")
            row = {"type": "relation", "status": "proposed", "data": data}
            conn.execute(
                "INSERT INTO relations(brain_id,id,kind,payload_json) VALUES (?,?,?,?)",
                (brain_id, rid, data["kind"], json.dumps(data)),
            )
            _register(conn, brain_id, rid, row, sources)
            records = _reconcile(conn, brain_id)
            record_change(
                conn, brain_id=brain_id, kind="relation_proposed", record_id=rid
            )
            return _public(rid, records[rid])

    def review_memory(self, *, principal: Principal, brain_id: str) -> dict:
        with self.store.transaction() as conn:
            visible = allowed_sources(conn, principal, brain_id)
            result = {
                "claims": [],
                "entities": [],
                "relations": [],
                "changes": [],
                "pending": [],
            }
            if context_pending(conn, brain_id=brain_id):
                reason = conn.execute(
                    "SELECT reason FROM brain_context_state WHERE brain_id=?",
                    (brain_id,),
                ).fetchone()[0]
                result["pending"].append(
                    {"record_type": "brain", "id": brain_id, "reason": reason}
                )
            permitted = set()
            for rid, row in _load(conn, brain_id).items():
                origins = record_sources(
                    conn, brain_id=brain_id, record_type=row["type"], record_id=rid
                )
                if not origins or not origins <= visible:
                    continue
                result[TABLES[row["type"]]].append(_public(rid, row))
                permitted.add((row["type"], rid))
                if row["status"] == "proposed":
                    result["pending"].append(
                        {
                            "record_type": row["type"],
                            "id": rid,
                            "reason": row["data"].get("pending_reason", "needs_review"),
                        }
                    )
            for change in conn.execute(
                "SELECT * FROM audit WHERE brain_id=? ORDER BY revision,created_at,id",
                (brain_id,),
            ):
                kind = change["kind"].split("_", 1)[0]
                if (kind, change["record_id"]) in permitted:
                    result["changes"].append(dict(change))
            return result
