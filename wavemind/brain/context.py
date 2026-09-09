"""Budgeted, revocable projections of live Brain authority.

Packet/receipt writes are projection audits, not logical memory mutations.
All authorization, selection, origin registration and persistence share a
transaction. Source data is never a controlling instruction or legacy memory.
"""

import hashlib
import json
import math
import re
import time
from uuid import uuid4

from wavemind.experience import ExperienceRecord, ExperienceSource, TrustClass
from wavemind.memory_firewall import MemoryFirewall, MemoryFirewallPolicy

from . import reconcile
from .access import _not_found, allowed_sources, require_access
from .models import BrainError, Principal, bounded_text
from .sources import context_pending, mark_context_pending, resolve_citation
from .store import record_change


SCHEMA = "wavemind.brain_context.v1"
MAX_SCAN = 10000
MAX_CANDIDATES = 128
LIFETIME = 900
WARNINGS = [
    "source_content_is_untrusted_data",
    "firewall_is_heuristic_not_universal_injection_prevention",
    "bounded_authoritative_fallback",
    "conservative_provenance_may_omit_reviewed_history",
    "partial_conflicts_exclude_whole_records",
]


def canonical_bytes(payload):
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _invalid():
    return BrainError("invalid_input", "Invalid context request.")


def _text(value, *, maximum):
    bounded_text(value, maximum=maximum)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise _invalid() from None
    return value


def _terms(text):
    return set(re.findall(r"\w+", text.casefold()))


def _seal(packet):
    # Fixed-size digest breaks the size/hash circularity. Cost converges as
    # decimal widths stabilize, then the digest includes those final costs.
    packet["digest"] = "0" * 64
    packet["cost"] = {"bytes": 0, "tokens": 0, "network_calls": 0}
    while True:
        size = len(canonical_bytes(packet))
        cost = {"bytes": size, "tokens": (size + 3) // 4, "network_calls": 0}
        if packet["cost"] == cost:
            break
        packet["cost"] = cost
    packet["digest"] = hashlib.sha256(
        canonical_bytes({k: v for k, v in packet.items() if k != "digest"})
    ).hexdigest()
    return packet


def _tainted(firewall, *, text, metadata=None):
    # is_tainted does not require legacy ACTIVE lifecycle. This ephemeral
    # SHADOW adapter is never stored or returned as an ExperienceRecord.
    record = ExperienceRecord.create(
        kind="fact",
        title="Brain source data",
        content=text if text.strip() else "[empty source content]",
        namespace=firewall.policy.namespace,
        trust=TrustClass.IMPORTED,
        source=ExperienceSource(
            provider="brain", source_type="source", metadata=metadata or {}
        ),
    )
    return firewall.is_tainted(record)


def _evidence(conn, *, principal, brain_id, origins, firewall):
    """Inspect evidence for the shared verifier's completed authorized origins.

    No second graph walk: payload and stored references must have identical
    scope for applicability, bounds, evidence/firewall checks and persistence.
    """
    require_access(conn, principal, brain_id, "read", {sid for _, _, sid in origins})
    citations = {}
    tainted = False
    for node in sorted({(kind, rid) for kind, rid, _ in origins if kind != "source"}):
        table = {**reconcile.TABLES, "receipt": "receipts", "outcome": "outcomes"}.get(
            node[0]
        )
        if table is None:
            raise _not_found()
        row = conn.execute(
            f"SELECT payload_json FROM {table} WHERE brain_id=? AND id=?",
            (brain_id, node[1]),
        ).fetchone()
        if row is None:
            raise _not_found()
        data = json.loads(row[0])
        # Scan actual strings: JSON escapes would turn newlines into literal
        # backslash-n and alter the firewall's existing whitespace patterns.
        tainted |= _tainted(
            firewall,
            text="\n".join(value for value in data.values() if isinstance(value, str)),
        )
        for cid in data.get("citation_ids", []):
            c = resolve_citation(
                conn, principal=principal, brain_id=brain_id, citation_id=cid
            )
            if (node[0], node[1], c["source_id"]) not in origins:
                # An evidence source absent from the verified record's origins
                # is incomplete provenance, not permission to invent a link.
                raise _not_found()
            meta = conn.execute(
                "SELECT metadata_json FROM sources WHERE brain_id=? AND id=?",
                (brain_id, c["source_id"]),
            ).fetchone()
            tainted |= _tainted(firewall, text=c["text"], metadata=json.loads(meta[0]))
            citations[cid] = {
                **c,
                "authority": "source_data",
                "review_status": "evidence_for_reviewed_memory",
            }
    return list(citations.values()), tainted


def _eligible(conn, *, principal, brain_id, kind, rid, moment):
    return reconcile.record_eligible(
        conn,
        principal=principal,
        brain_id=brain_id,
        record_type=kind,
        record_id=rid,
        as_of=moment,
    )


def _select(conn, *, principal, brain_id, question, moment, project_id, now):
    firewall = MemoryFirewall(MemoryFirewallPolicy(namespace=brain_id))
    permitted = allowed_sources(conn, principal, brain_id)
    groups, transitions, context_origins = [], [], set()
    if project_id is not None:
        project = conn.execute(
            "SELECT kind FROM entities WHERE brain_id=? AND id=?",
            (brain_id, project_id),
        ).fetchone()
        if project is None or project[0] not in ("project", "client"):
            raise _not_found()
        applicable, bounds, selector_origins = reconcile.context_record_state(
            conn,
            principal=principal,
            brain_id=brain_id,
            record_type="entity",
            record_id=project_id,
            as_of=moment,
        )
        if not applicable:
            raise _not_found()
        _, tainted = _evidence(
            conn,
            principal=principal,
            brain_id=brain_id,
            origins=selector_origins,
            firewall=firewall,
        )
        transitions.extend(bounds)
        if tainted:
            raise _not_found()
        context_origins.update(selector_origins)
    rows = conn.execute(
        "SELECT id,status,payload_json FROM claims WHERE brain_id=? ORDER BY id LIMIT ?",
        (brain_id, MAX_SCAN + 1),
    ).fetchall()
    if len(rows) > MAX_SCAN:
        raise BrainError("dependency_limit", "Dependency verification limit reached.")
    query = _terms(question)
    ranked = []
    # Authorize before inspecting content or counting any visible result.
    for row in rows:
        sources = reconcile.record_sources(
            conn, brain_id=brain_id, record_type="claim", record_id=row["id"]
        )
        if not sources or not sources <= permitted:
            continue
        data = json.loads(row["payload_json"])
        if project_id is not None and project_id not in data.get("entity_ids", []):
            continue
        score = len(query & _terms(data.get("content", "") + " " + data.get("key", "")))
        ranked.append((-score, row["id"], row, data))
    for _, rid, row, data in sorted(ranked)[:MAX_CANDIDATES]:
        try:
            conflict = row["status"] == "conflicted"
            applicable, bounds, origins = reconcile.context_record_state(
                conn,
                principal=principal,
                brain_id=brain_id,
                record_type="claim",
                record_id=rid,
                as_of=moment,
                conflict=conflict,
            )
            if not applicable and not any(bound > now for bound in bounds):
                continue
            citations, tainted = _evidence(
                conn,
                principal=principal,
                brain_id=brain_id,
                origins=origins,
                firewall=firewall,
            )
        except BrainError as error:
            if error.code == "not_found":
                continue
            raise
        transitions.extend(bounds)
        if any(bound > now for bound in bounds):
            # Bounds influence even empty/budget-trimmed envelopes. Keep all
            # their origins for live ACL checks and erasure without emitting
            # currently ineligible evidence or claiming it as active memory.
            context_origins.update(origins)
        if not applicable or tainted:
            continue
        public = {k: v for k, v in data.items() if not k.startswith("_")}
        public.update(id=rid, status=row["status"], authority="reviewed_claim")
        groups.append(
            ("conflicts" if conflict else "claims", public, citations, origins)
        )
    if project_id is None:
        # Source-only evidence has no semantic review; do not use this path to
        # replay obsolete/conflicted reviewed sources as apparent fresh facts.
        evidence = []
        for sid in sorted(permitted)[:MAX_CANDIDATES]:
            if conn.execute(
                "SELECT 1 FROM dependencies WHERE brain_id=? AND source_id=? AND dependent_type IN ('claim','entity','relation') LIMIT 1",
                (brain_id, sid),
            ).fetchone():
                continue
            meta = json.loads(
                conn.execute(
                    "SELECT metadata_json FROM sources WHERE brain_id=? AND id=?",
                    (brain_id, sid),
                ).fetchone()[0]
            )
            chunks = conn.execute(
                """SELECT c.id,c.text FROM chunks c JOIN source_versions v
                ON v.brain_id=c.brain_id AND v.source_id=c.source_id AND v.id=c.version_id
                WHERE c.brain_id=? AND c.source_id=? AND v.version=(SELECT MAX(version) FROM source_versions WHERE brain_id=? AND source_id=?)
                ORDER BY c.id LIMIT ?""",
                (brain_id, sid, brain_id, sid, MAX_CANDIDATES),
            )
            for chunk in chunks:
                score = len(query & _terms(chunk["text"]))
                if score and not _tainted(firewall, text=chunk["text"], metadata=meta):
                    evidence.append((-score, chunk["id"], sid))
        for _, cid, sid in sorted(evidence)[:MAX_CANDIDATES]:
            c = resolve_citation(
                conn, principal=principal, brain_id=brain_id, citation_id=cid
            )
            c.update(authority="source_data", review_status="unreviewed")
            groups.append(("citations", c, [], {("source", sid, sid)}))
    expiry = min([now + LIFETIME] + [bound for bound in transitions if bound > now])
    return groups, expiry, context_origins


def _assemble(packet, groups):
    for field in ("claims", "citations", "experiences", "conflicts"):
        packet[field] = []
    citations = {}
    for field, item, evidence, _ in groups:
        if field == "citations":
            citations[item["id"]] = item
        else:
            packet[field].append(item)
        citations.update((c["id"], c) for c in evidence)
    packet["citations"] = [citations[cid] for cid in sorted(citations)]
    packet["coverage"]["selected_claims"] = len(packet["claims"])
    packet["coverage"]["selected_citations"] = len(packet["citations"])
    return _seal(packet)


def validate_persisted_packet(conn, *, principal, brain_id, packet_id):
    """Internal existing-transaction contract for receipts and Task5 outcomes."""
    require_access(conn, principal, brain_id, "read")
    if not isinstance(packet_id, str):
        raise _not_found()
    row = conn.execute(
        "SELECT * FROM packets WHERE brain_id=? AND id=?", (brain_id, packet_id)
    ).fetchone()
    if row is None or row["principal_id"] != principal.identity:
        raise _not_found()
    sources = reconcile.record_sources(
        conn, brain_id=brain_id, record_type="packet", record_id=packet_id
    )
    require_access(conn, principal, brain_id, "read", sources)
    if context_pending(conn, brain_id=brain_id):
        raise BrainError("context_pending", "Context verification is pending.")
    revision = conn.execute(
        "SELECT revision FROM brains WHERE id=?", (brain_id,)
    ).fetchone()[0]
    if (
        row["status"] != "active"
        or row["revision"] != revision
        or row["expires_at"] is None
        or time.time() >= row["expires_at"]
    ):
        raise BrainError("stale_packet", "Context packet is no longer current.")
    try:
        packet = json.loads(row["payload_json"])
        digest = hashlib.sha256(
            canonical_bytes({k: v for k, v in packet.items() if k != "digest"})
        ).hexdigest()
        valid = (
            packet["schema"] == SCHEMA
            and packet["id"] == packet_id
            and packet["brain_id"] == brain_id
            and packet["principal_id"] == principal.identity
            and packet["revision"] == revision
            and packet["expires_at"] == row["expires_at"]
            and packet["digest"] == row["digest"] == digest
            and packet["cost"]
            == {
                "bytes": len(canonical_bytes(packet)),
                "tokens": (len(canonical_bytes(packet)) + 3) // 4,
                "network_calls": 0,
            }
        )
    except (KeyError, TypeError, ValueError, AttributeError, UnicodeError):
        valid = False
    if not valid:
        raise BrainError("invalid_packet", "Context packet integrity check failed.")
    if packet["coverage"]["status"] == "pending":
        raise BrainError("context_pending", "Context verification is pending.")
    for claim in packet["claims"]:
        if not _eligible(
            conn,
            principal=principal,
            brain_id=brain_id,
            kind="claim",
            rid=claim["id"],
            moment=packet["moment"],
        ):
            raise BrainError("stale_packet", "Context packet is no longer current.")
    for conflict in packet["conflicts"]:
        applicable, _, _ = reconcile.context_record_state(
            conn,
            principal=principal,
            brain_id=brain_id,
            record_type="claim",
            record_id=conflict["id"],
            as_of=packet["moment"],
            conflict=True,
        )
        if not applicable:
            raise BrainError("stale_packet", "Context packet is no longer current.")
    project = packet["project_id"]
    if project is not None and not _eligible(
        conn,
        principal=principal,
        brain_id=brain_id,
        kind="entity",
        rid=project,
        moment=packet["moment"],
    ):
        raise BrainError("stale_packet", "Context packet is no longer current.")
    for citation in packet["citations"]:
        resolve_citation(
            conn, principal=principal, brain_id=brain_id, citation_id=citation["id"]
        )
    return packet


class Context:
    def __init__(self, store):
        self.store = store
        self.experience_provider = None

    def build_context(
        self,
        *,
        principal: Principal,
        brain_id: str,
        question: str,
        moment: float | None = None,
        project_id: str | None = None,
        max_bytes: int = 16384,
    ) -> dict:
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "read")
            _text(question, maximum=8192)
            try:
                valid_moment = moment is None or (
                    type(moment) in (int, float) and math.isfinite(moment)
                )
            except OverflowError:
                valid_moment = False
            if not valid_moment or type(max_bytes) is not int or max_bytes <= 0:
                raise _invalid()
            if project_id is not None:
                _text(project_id, maximum=128)
            now = time.time()
            moment = now if moment is None else float(moment)
            pending = context_pending(conn, brain_id=brain_id)
            groups, expiry, context_origins = [], now + LIFETIME, set()
            governing_origins = set()
            if not pending:
                try:
                    groups, expiry, context_origins = _select(
                        conn,
                        principal=principal,
                        brain_id=brain_id,
                        question=question,
                        moment=moment,
                        project_id=project_id,
                        now=now,
                    )
                    governing_origins = set(context_origins)
                    if self.experience_provider is not None:
                        firewall = MemoryFirewall(
                            MemoryFirewallPolicy(namespace=brain_id)
                        )
                        for item in self.experience_provider(
                            conn,
                            principal,
                            brain_id,
                            question,
                            moment,
                            project_id=project_id,
                        ):
                            origins = {tuple(o) for o in item["origins"]}
                            require_access(
                                conn,
                                principal,
                                brain_id,
                                "read",
                                {o[2] for o in origins},
                            )
                            if (
                                not origins
                                or item["project_id"] != project_id
                                or type(item.get("applicable")) is not bool
                            ):
                                raise _not_found()
                            evidence = [
                                resolve_citation(
                                    conn,
                                    principal=principal,
                                    brain_id=brain_id,
                                    citation_id=cid,
                                )
                                for cid in item["citation_ids"]
                            ]
                            if any(
                                c["source_id"] not in {o[2] for o in origins}
                                for c in evidence
                            ):
                                raise _not_found()
                            if _tainted(firewall, text=item["content"]) or any(
                                _tainted(
                                    firewall,
                                    text=c["text"],
                                    metadata=json.loads(
                                        conn.execute(
                                            "SELECT metadata_json FROM sources WHERE brain_id=? AND id=?",
                                            (brain_id, c["source_id"]),
                                        ).fetchone()[0]
                                    ),
                                )
                                for c in evidence
                            ):
                                continue
                            bounds = [
                                bound for bound in item["transitions"] if bound > now
                            ]
                            expiry = min([expiry] + bounds)
                            if bounds:
                                context_origins.update(origins)
                            if item["applicable"]:
                                public = {
                                    k: v
                                    for k, v in item.items()
                                    if k not in ("origins", "transitions", "applicable")
                                }
                                groups.append(
                                    ("experiences", public, evidence, origins)
                                )
                except BrainError as error:
                    if error.code not in {"dependency_limit", "dependency_cycle"}:
                        raise
                    mark_context_pending(conn, brain_id=brain_id, reason=error.code)
                    # The first global gate transition changes authority.
                    # Already-pending builds skip selection and never repeat it.
                    record_change(
                        conn,
                        brain_id=brain_id,
                        kind="context_pending",
                        record_id=brain_id,
                    )
                    # Commit the gate even if this request cannot fit a packet.
                    pending, groups, context_origins, governing_origins = (
                        True,
                        [],
                        set(),
                        set(),
                    )
            packet = dict(
                schema=SCHEMA,
                id=uuid4().hex,
                brain_id=brain_id,
                principal_id=principal.identity,
                revision=conn.execute(
                    "SELECT revision FROM brains WHERE id=?", (brain_id,)
                ).fetchone()[0],
                question=question,
                moment=moment,
                project_id=None if pending else project_id,
                claims=[],
                citations=[],
                experiences=[],
                conflicts=[],
                unknowns=["coverage_is_not_complete", "causal_effects_not_established"],
                coverage={
                    "status": "pending" if pending else "partial",
                    "selection": "bounded_lexical",
                },
                warnings=list(WARNINGS),
                cost={},
                expires_at=expiry,
                digest="",
            )
            if pending:
                packet["warnings"].append("context_pending_no_action")
            _assemble(packet, groups)
            while packet["cost"]["bytes"] > max_bytes and groups:
                groups.pop()
                if "budget_truncated" not in packet["warnings"]:
                    packet["warnings"].append("budget_truncated")
                _assemble(packet, groups)
            too_small = packet["cost"]["bytes"] > max_bytes
            if not too_small:
                conn.execute(
                    "INSERT INTO packets(brain_id,id,principal_id,revision,digest,created_at,expires_at,status,payload_json) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        brain_id,
                        packet["id"],
                        principal.identity,
                        packet["revision"],
                        packet["digest"],
                        now,
                        expiry,
                        "pending" if pending else "active",
                        canonical_bytes(packet).decode(),
                    ),
                )
                origins = context_origins | {
                    origin for group in groups for origin in group[3]
                }
                # Governing basis excludes private experience evidence lineage.
                basis = {
                    origin
                    for group in groups
                    if group[0] != "experiences"
                    for origin in group[3]
                }
                basis.update(governing_origins)
                if not basis <= origins:
                    raise _not_found()
                from .experience_records import basis_fingerprint

                fingerprint = basis_fingerprint(
                    conn,
                    brain_id=brain_id,
                    project_id=packet["project_id"],
                    origins=basis,
                )
                conn.execute(
                    "INSERT INTO brain_packet_basis(brain_id,packet_id,payload_json,basis_digest) VALUES (?,?,?,?)",
                    (
                        brain_id,
                        packet["id"],
                        canonical_bytes(sorted(basis)).decode(),
                        fingerprint,
                    ),
                )
                for kind, rid, sid in sorted(origins):
                    conn.execute(
                        "INSERT INTO dependencies VALUES (?, 'packet', ?, ?, ?, ?)",
                        (brain_id, packet["id"], kind, rid, sid),
                    )
                record_change(
                    conn,
                    brain_id=brain_id,
                    kind="packet_issued",
                    record_id=packet["id"],
                    increment=False,
                )
        if too_small:
            raise BrainError(
                "budget_too_small", "Byte budget cannot fit the context envelope."
            )
        return packet

    def validate_packet(
        self, *, principal: Principal, brain_id: str, packet_id: str
    ) -> dict:
        with self.store.transaction() as conn:
            return validate_persisted_packet(
                conn, principal=principal, brain_id=brain_id, packet_id=packet_id
            )

    def begin_action(
        self,
        *,
        principal: Principal,
        brain_id: str,
        packet_id: str,
        run_id: str,
        action: str,
    ) -> dict:
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "record_outcome")
            packet = validate_persisted_packet(
                conn, principal=principal, brain_id=brain_id, packet_id=packet_id
            )
            _text(run_id, maximum=256)
            _text(action, maximum=4096)
            existing = conn.execute(
                """SELECT payload_json FROM receipts WHERE brain_id=? AND packet_id=?
                AND json_extract(payload_json,'$.run_id')=? AND json_extract(payload_json,'$.action')=?""",
                (brain_id, packet_id, run_id, action),
            ).fetchone()
            if existing:
                return json.loads(existing[0])
            receipt = dict(
                id=uuid4().hex,
                packet_id=packet_id,
                packet_digest=packet["digest"],
                revision=packet["revision"],
                run_id=run_id,
                action=action,
                status="pending_outcome",
            )
            conn.execute(
                "INSERT INTO receipts(brain_id,id,packet_id,principal_id,packet_digest,created_at,payload_json) VALUES (?,?,?,?,?,?,?)",
                (
                    brain_id,
                    receipt["id"],
                    packet_id,
                    principal.identity,
                    packet["digest"],
                    time.time(),
                    canonical_bytes(receipt).decode(),
                ),
            )
            conn.execute(
                """INSERT INTO dependencies SELECT brain_id,'receipt',?,origin_type,origin_id,source_id
                FROM dependencies WHERE brain_id=? AND dependent_type='packet' AND dependent_id=?""",
                (receipt["id"], brain_id, packet_id),
            )
            record_change(
                conn,
                brain_id=brain_id,
                kind="action_begun",
                record_id=receipt["id"],
                increment=False,
            )
            return receipt
