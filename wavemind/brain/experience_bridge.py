"""Authoritative reviewed outcomes and retryable private-runtime integration."""

import json
import time
from uuid import NAMESPACE_URL, uuid4, uuid5

from .access import _not_found, require_access
from .models import BrainError, Principal, bounded_text
from .sources import resolve_citation, context_pending
from .store import record_change
from .experience_records import (
    authorize_record,
    basis_origins,
    digest,
    encode,
    historical_receipt,
    live_basis,
    origins_for,
    register,
)
from .experience_runtime_bridge import PrivateRuntime
from ..experience_runtime import VerificationSource


MAX_PRIVATE_RECORDS = 10000


def invalid():
    return BrainError("invalid_input", "Invalid outcome request.")


def public_experience_id(brain_id, runtime_id):
    return uuid5(
        NAMESPACE_URL, "wavemind.brain.experience:" + brain_id + ":" + runtime_id
    ).hex


def private_scope(brain_id, data):
    """One ordered reported procedure per immutable governing basis."""
    basis = data["_basis"] or digest(["legacy", data["receipt_id"]])
    return "brain:" + brain_id + ":" + basis + ":" + digest(data["procedure"])


def citations(conn, principal, brain_id, ids):
    if (
        not isinstance(ids, list)
        or len(ids) > 100
        or any(not isinstance(cid, str) for cid in ids)
    ):
        raise invalid()
    return [
        resolve_citation(conn, principal=principal, brain_id=brain_id, citation_id=cid)
        for cid in sorted(set(ids))
    ]


def principal_data(principal):
    return {
        "identity": principal.identity,
        "kind": principal.kind,
        "brain_ids": sorted(principal.brain_ids)
        if principal.brain_ids is not None
        else None,
        "operations": sorted(principal.operations)
        if principal.operations is not None
        else None,
        "source_refs": sorted(principal.source_refs)
        if principal.source_refs is not None
        else None,
    }


class ExperienceBridge:
    def __init__(self, store, state_dir):
        self.store = store
        self.private = PrivateRuntime(state_dir)
        self.verifiers = {}

    def _outcome(self, conn, principal, brain_id, outcome_id):
        require_access(conn, principal, brain_id, "read")
        if not isinstance(outcome_id, str):
            raise _not_found()
        row = conn.execute(
            "SELECT * FROM outcomes WHERE brain_id=? AND id=?", (brain_id, outcome_id)
        ).fetchone()
        if row is None or row["payload_json"] == "{}":
            raise _not_found()
        authorize_record(
            conn, principal=principal, brain_id=brain_id, kind="outcome", rid=outcome_id
        )
        return row, json.loads(row["payload_json"])

    def _public(self, row, data):
        return {
            "id": row["id"],
            "status": row["status"],
            "verification": data["verification"],
            "experience_ids": data["experience_ids"],
            "integration_status": data["integration_status"],
        }

    def _save(self, conn, brain_id, oid, data, status=None):
        conn.execute(
            "UPDATE outcomes SET payload_json=? WHERE brain_id=? AND id=?",
            (encode(data), brain_id, oid),
        )
        if status is not None:
            conn.execute(
                "UPDATE outcomes SET status=? WHERE brain_id=? AND id=?",
                (status, brain_id, oid),
            )

    def record_outcome(self, *, principal, brain_id, receipt_id, outcome):
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "record_outcome")
            receipt, packet, origins = historical_receipt(
                conn, principal=principal, brain_id=brain_id, receipt_id=receipt_id
            )
            if not isinstance(outcome, dict) or set(outcome) != {
                "idempotency_key",
                "summary",
                "procedure",
                "evidence_citation_ids",
            }:
                raise invalid()
            bounded_text(outcome["idempotency_key"], maximum=128)
            bounded_text(outcome["summary"], maximum=8192)
            steps = outcome["procedure"]
            if not isinstance(steps, list) or len(steps) > 50:
                raise invalid()
            for step in steps:
                bounded_text(step, maximum=1024)
            evidence = citations(
                conn, principal, brain_id, outcome["evidence_citation_ids"]
            )
            for row in conn.execute(
                "SELECT * FROM outcomes WHERE brain_id=? AND receipt_id=?",
                (brain_id, receipt_id),
            ):
                data = json.loads(row["payload_json"])
                if data.get("idempotency_key") == outcome["idempotency_key"]:
                    self._outcome(conn, principal, brain_id, row["id"])
                    if any(data[k] != outcome[k] for k in outcome):
                        raise BrainError(
                            "invalid_state", "Idempotency key already used."
                        )
                    return self._public(row, data)
            basis = basis_origins(
                conn, principal=principal, brain_id=brain_id, packet=packet
            )
            manifest = conn.execute(
                "SELECT basis_digest,legacy FROM brain_packet_basis WHERE brain_id=? AND packet_id=?",
                (brain_id, packet["id"]),
            ).fetchone()
            fingerprint = manifest[0]
            if not (
                isinstance(fingerprint, str)
                and len(fingerprint) == 64
                and all(c in "0123456789abcdef" for c in fingerprint)
            ):
                if not (manifest[1] and fingerprint is None):
                    raise _not_found()
            oid = uuid4().hex
            data = {
                **outcome,
                "receipt_id": receipt_id,
                "project_id": packet["project_id"],
                "reporter_id": principal.identity,
                "verification": None,
                "experience_ids": [],
                "integration_status": "unverified",
                "_basis_origins": sorted(basis),
                "_basis": fingerprint,
                "_run": digest([brain_id, receipt["run_id"]]),
                "_receipt_run_id": receipt["run_id"],
            }
            data["_namespace"] = private_scope(brain_id, data)
            conn.execute(
                "INSERT INTO outcomes(brain_id,id,receipt_id,status,created_at,payload_json) VALUES (?,?,?,'unverified',?,?)",
                (brain_id, oid, receipt_id, time.time(), encode(data)),
            )
            origins |= {("source", c["source_id"], c["source_id"]) for c in evidence}
            origins |= {("receipt", receipt_id, sid) for sid in {o[2] for o in origins}}
            register(conn, brain_id, "outcome", oid, origins)
            record_change(
                conn, brain_id=brain_id, kind="outcome_recorded", record_id=oid
            )
            row, data = self._outcome(conn, principal, brain_id, oid)
            return self._public(row, data)

    def register_outcome_verifier(self, *, verifier_id, source, callback):
        bounded_text(verifier_id, maximum=128)
        try:
            source = VerificationSource(source)
        except ValueError:
            raise invalid() from None
        if source == VerificationSource.OPERATOR or not callable(callback):
            raise invalid()
        self.verifiers[verifier_id] = (source.value, callback)

    def verify_outcome(
        self,
        *,
        principal,
        brain_id,
        outcome_id,
        success,
        evidence_citation_ids,
        note="",
    ):
        return self._verify(
            principal=principal,
            brain_id=brain_id,
            outcome_id=outcome_id,
            success=success,
            evidence_citation_ids=evidence_citation_ids,
            note=note,
            verifier_id=None,
        )

    def verify_outcome_with(
        self,
        *,
        principal,
        brain_id,
        outcome_id,
        verifier_id,
        evidence_citation_ids,
        note="",
    ):
        return self._verify(
            principal=principal,
            brain_id=brain_id,
            outcome_id=outcome_id,
            success=None,
            evidence_citation_ids=evidence_citation_ids,
            note=note,
            verifier_id=verifier_id,
        )

    def _verify(
        self,
        *,
        principal,
        brain_id,
        outcome_id,
        success,
        evidence_citation_ids,
        note,
        verifier_id,
    ):
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "verify_outcome")
            row, data = self._outcome(conn, principal, brain_id, outcome_id)
            receipt, packet, _ = historical_receipt(
                conn,
                principal=principal,
                brain_id=brain_id,
                receipt_id=row["receipt_id"],
            )
            if not isinstance(note, str) or len(note) > 8192:
                raise invalid()
            evidence = citations(conn, principal, brain_id, evidence_citation_ids)
            if data["verification"] is None:
                if data["_namespace"] != private_scope(brain_id, data):
                    raise BrainError(
                        "invalid_state", "Private experience scope requires review."
                    )
                if self._scope_dirty(conn, brain_id, data["_namespace"]):
                    raise BrainError(
                        "cleanup_pending", "Private experience cleanup is pending."
                    )
            if verifier_id is not None:
                if (
                    not isinstance(verifier_id, str)
                    or verifier_id not in self.verifiers
                ):
                    raise invalid()
                source, callback = self.verifiers[verifier_id]
                if data["verification"] is None:
                    try:
                        success = callback(
                            {
                                "receipt": receipt,
                                "packet": packet,
                                "outcome": {
                                    k: v
                                    for k, v in data.items()
                                    if not k.startswith("_")
                                },
                                "evidence": evidence,
                            }
                        )
                        if type(success) is not bool:
                            raise ValueError("nonboolean result")
                    except Exception:
                        data["integration_status"] = "verification_failed"
                        self._save(conn, brain_id, outcome_id, data)
                        record_change(
                            conn,
                            brain_id=brain_id,
                            kind="outcome_verification_failed",
                            record_id=outcome_id,
                        )
                        return self._public(row, data)
                else:
                    success = data["verification"]["success"]
                mode = "configured_verifier"
            else:
                source, mode = "operator", "manual_attestation"
            if type(success) is not bool:
                raise invalid()
            verification = {
                "source": source,
                "mode": mode,
                "verifier": verifier_id or principal.identity,
                "success": success,
                "evidence_citation_ids": sorted({c["id"] for c in evidence}),
                "note": note,
            }
            if data["verification"] is not None:
                if data["verification"] != verification:
                    raise BrainError(
                        "invalid_state", "Outcome verification is immutable."
                    )
                return self._public(row, data)
            data.update(
                verification=verification,
                _verifier_principal=principal_data(principal),
                _verified_at=time.time(),
            )
            origins = origins_for(conn, brain_id, "outcome", outcome_id)
            origins |= {("source", c["source_id"], c["source_id"]) for c in evidence}
            register(conn, brain_id, "outcome", outcome_id, origins)
            keys = [
                digest(["run", data["_receipt_run_id"]]),
                digest(["receipt", row["receipt_id"]]),
            ]
            keys += [digest(["citation", c["id"]]) for c in evidence]
            keys += [digest(["evidence_content", c["text"]]) for c in evidence]
            keys = sorted(set(keys))
            replay = any(
                conn.execute(
                    "SELECT 1 FROM brain_experience_evidence WHERE brain_id=? AND key=?",
                    (brain_id, key),
                ).fetchone()
                for key in keys
            )
            status = "verified" if success else "failed"
            data["integration_status"] = "replay" if replay else "pending"
            if not evidence or not data["procedure"]:
                data["integration_status"] = "incomplete"
            if data["integration_status"] == "pending":
                for key in keys:
                    conn.execute(
                        "INSERT INTO brain_experience_evidence VALUES (?,?,?)",
                        (brain_id, key, outcome_id),
                    )
                data["_runtime_verification"] = {
                    "evidence_id": digest([brain_id, data["_run"]]),
                    "source": source,
                    "verifier": verifier_id or principal.identity,
                    "success": success,
                    "score": 1.0 if success else 0.0,
                    "verified_at": data["_verified_at"],
                }
                conn.execute(
                    "INSERT INTO outbox(brain_id,id,kind,created_at) VALUES (?,?,'integrate_outcome',?)",
                    (brain_id, outcome_id, time.time()),
                )
                conn.execute(
                    "INSERT INTO brain_experience_links VALUES (?,?,?,'',?)",
                    (brain_id, outcome_id, data["_namespace"], row["created_at"]),
                )
            self._save(conn, brain_id, outcome_id, data, status)
            conn.execute(
                "UPDATE outcomes SET verifier_id=? WHERE brain_id=? AND id=?",
                (principal.identity, brain_id, outcome_id),
            )
            record_change(
                conn, brain_id=brain_id, kind="outcome_verified", record_id=outcome_id
            )
            row, data = self._outcome(conn, principal, brain_id, outcome_id)
            return self._public(row, data)

    def _acknowledge(self, conn, brain_id, operation_id, data, experience_ids):
        data.update(
            experience_ids=[
                public_experience_id(brain_id, eid) for eid in experience_ids
            ],
            integration_status="completed",
        )
        self._save(conn, brain_id, operation_id, data)
        for eid in experience_ids:
            conn.execute(
                "INSERT OR IGNORE INTO brain_experience_links SELECT brain_id,outcome_id,namespace,?,created_at FROM brain_experience_links WHERE brain_id=? AND outcome_id=? AND experience_id=''",
                (eid, brain_id, operation_id),
            )
        conn.execute(
            "UPDATE outbox SET status='completed' WHERE brain_id=? AND id=?",
            (brain_id, operation_id),
        )
        record_change(
            conn,
            brain_id=brain_id,
            kind="experience_integrated",
            record_id=operation_id,
        )

    def drain_outbox(self, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise invalid()
        completed, pending = 0, 0
        with self.store.transaction(write=True) as conn:
            rows = conn.execute(
                "SELECT * FROM outbox WHERE status='pending' ORDER BY CASE WHEN kind LIKE 'source_%' THEN 0 ELSE 1 END,created_at,id LIMIT ?",
                (limit,),
            ).fetchall()
            for operation in rows:
                brain, oid = operation["brain_id"], operation["id"]
                # A preceding purge can retire queued integrations already in
                # this snapshot; never replay them into the now-clean scope.
                if (
                    conn.execute(
                        "SELECT status FROM outbox WHERE brain_id=? AND id=?",
                        (brain, oid),
                    ).fetchone()[0]
                    != "pending"
                ):
                    continue
                conn.execute("SAVEPOINT experience_operation")
                try:
                    if operation["kind"] == "integrate_outcome":
                        row = conn.execute(
                            "SELECT * FROM outcomes WHERE brain_id=? AND id=?",
                            (brain, oid),
                        ).fetchone()
                        data = json.loads(row["payload_json"]) if row else {}
                        eligible = False
                        if data and row["status"] in ("verified", "failed"):
                            principal = Principal(**data["_verifier_principal"])
                            require_access(conn, principal, brain, "verify_outcome")
                            self._outcome(conn, principal, brain, oid)
                            eligible, _, _ = live_basis(
                                conn,
                                principal=principal,
                                brain_id=brain,
                                data=data,
                                moment=time.time(),
                            )
                            eligible &= data["_namespace"] == private_scope(brain, data)
                            eligible &= (
                                conn.execute(
                                    "SELECT 1 FROM brain_experience_links WHERE brain_id=? AND outcome_id=? AND namespace=?",
                                    (brain, oid, data["_namespace"]),
                                ).fetchone()
                                is not None
                            )
                            if self._scope_dirty(conn, brain, data["_namespace"]):
                                raise BrainError(
                                    "cleanup_pending",
                                    "Private experience cleanup is pending.",
                                )
                        if eligible:
                            ids = self.private.integrate(brain_id=brain, data=data)
                            self._acknowledge(conn, brain, oid, data, ids)
                        else:
                            self._purge_outcome_scopes(conn, brain, oid)
                            if data:
                                data["integration_status"] = "blocked"
                                self._save(conn, brain, oid, data)
                            conn.execute(
                                "UPDATE outbox SET status='completed' WHERE brain_id=? AND id=?",
                                (brain, oid),
                            )
                    elif operation["kind"].startswith("source_"):
                        # Deletion has scrubbed authoritative payloads; opaque
                        # link mappings still identify every copied scope.
                        affected = conn.execute(
                            "SELECT DISTINCT l.namespace FROM brain_experience_links l JOIN outcomes o ON o.brain_id=l.brain_id AND o.id=l.outcome_id WHERE l.brain_id=? AND (o.status='revoked' OR o.payload_json='{}')",
                            (brain,),
                        ).fetchall()
                        for item in affected:
                            self._purge_scope(conn, brain, item[0])
                        conn.execute(
                            "UPDATE outbox SET status='completed' WHERE brain_id=? AND id=?",
                            (brain, oid),
                        )
                    else:
                        raise ValueError("unsupported operation")
                    conn.execute("RELEASE experience_operation")
                    completed += 1
                except Exception:
                    conn.execute("ROLLBACK TO experience_operation")
                    conn.execute("RELEASE experience_operation")
                    conn.execute(
                        "UPDATE outbox SET attempts=attempts+1 WHERE brain_id=? AND id=?",
                        (brain, oid),
                    )
                    pending += 1
        return {"completed": completed, "pending": pending}

    def _purge_outcome_scopes(self, conn, brain, oid):
        for row in conn.execute(
            "SELECT DISTINCT namespace FROM brain_experience_links WHERE brain_id=? AND outcome_id=?",
            (brain, oid),
        ).fetchall():
            self._purge_scope(conn, brain, row[0])

    def _scope_dirty(self, conn, brain_id, namespace):
        return (
            conn.execute(
                "SELECT 1 FROM brain_experience_links l JOIN outcomes o ON o.brain_id=l.brain_id AND o.id=l.outcome_id WHERE l.brain_id=? AND l.namespace=? AND (o.status='revoked' OR o.payload_json='{}') LIMIT 1",
                (brain_id, namespace),
            ).fetchone()
            is not None
        )

    def _purge_scope(self, conn, brain_id, namespace):
        self.private.purge(namespace)
        self._retire_scope(conn, brain_id, namespace)

    def _retire_scope(self, conn, brain_id, namespace):
        """Retire only fully purged current mappings; keep history/replay keys.

        The caller holds the Brain write transaction across private deletion
        and this acknowledgment. A failure keeps opaque links for retry.
        """
        rows = conn.execute(
            "SELECT DISTINCT o.id,o.payload_json FROM outcomes o JOIN brain_experience_links l ON l.brain_id=o.brain_id AND l.outcome_id=o.id WHERE l.brain_id=? AND l.namespace=?",
            (brain_id, namespace),
        ).fetchall()
        for row in rows:
            data = json.loads(row["payload_json"])
            if data:
                data["integration_status"] = "purged"
                self._save(conn, brain_id, row["id"], data)
            conn.execute(
                "UPDATE outbox SET status='completed' WHERE brain_id=? AND id=? AND kind='integrate_outcome'",
                (brain_id, row["id"]),
            )
        conn.execute(
            "DELETE FROM brain_experience_links WHERE brain_id=? AND namespace=?",
            (brain_id, namespace),
        )
        if rows:
            record_change(
                conn,
                brain_id=brain_id,
                kind="experience_purged",
                record_id=rows[0]["id"],
            )

    def _procedures(
        self, conn, principal, brain_id, *, moment, project_id=None, all_projects=False
    ):
        require_access(conn, principal, brain_id, "read")
        groups = conn.execute(
            "SELECT namespace,experience_id,MIN(created_at) created_at FROM brain_experience_links WHERE brain_id=? AND experience_id!='' GROUP BY namespace,experience_id ORDER BY created_at,experience_id LIMIT ?",
            (brain_id, MAX_PRIVATE_RECORDS + 1),
        ).fetchall()
        if len(groups) > MAX_PRIVATE_RECORDS:
            raise BrainError(
                "dependency_limit", "Dependency verification limit reached."
            )
        result, inspected = [], set()
        for group in groups:
            links = conn.execute(
                "SELECT DISTINCT o.* FROM outcomes o JOIN brain_experience_links l ON o.brain_id=l.brain_id AND o.id=l.outcome_id WHERE l.brain_id=? AND l.namespace=? ORDER BY o.created_at,o.id LIMIT ?",
                (brain_id, group["namespace"], MAX_PRIVATE_RECORDS + 1),
            ).fetchall()
            inspected.update(row["id"] for row in links)
            if len(inspected) > MAX_PRIVATE_RECORDS:
                raise BrainError(
                    "dependency_limit", "Dependency verification limit reached."
                )
            origins, bounds, ids, evidence = set(), set(), set(), set()
            eligible, scope, integration = True, None, "completed"
            try:
                for row in links:
                    _, data = self._outcome(conn, principal, brain_id, row["id"])
                    if data["_namespace"] != group["namespace"] or data[
                        "_namespace"
                    ] != private_scope(brain_id, data):
                        raise _not_found()
                    scope = data["project_id"]
                    eligible &= (
                        row["status"] in ("verified", "failed")
                        and data["integration_status"] == "completed"
                    )
                    if data["integration_status"] != "completed":
                        integration = data["integration_status"]
                    current, transitions, reached = live_basis(
                        conn,
                        principal=principal,
                        brain_id=brain_id,
                        data=data,
                        moment=moment,
                    )
                    eligible &= current
                    bounds.update(transitions)
                    origins.update(reached)
                    origins.update(origins_for(conn, brain_id, "outcome", row["id"]))
                    origins.update(
                        ("outcome", row["id"], sid)
                        for sid in {
                            o[2]
                            for o in origins_for(conn, brain_id, "outcome", row["id"])
                        }
                    )
                    ids.add(row["id"])
                    evidence.update(data["evidence_citation_ids"])
                    evidence.update(data["verification"]["evidence_citation_ids"])
            except BrainError as error:
                if error.code == "not_found":
                    continue
                raise
            if not all_projects and scope != project_id:
                continue
            record = self.private.store.get(group["experience_id"])
            if record is None or record.namespace != group["namespace"]:
                continue
            result.append(
                {
                    "id": public_experience_id(brain_id, record.id),
                    "project_id": scope,
                    "status": record.status.value,
                    "integration_status": integration,
                    "eligible": bool(eligible and record.status.value == "active"),
                    "content": record.content,
                    "outcome_ids": sorted(ids),
                    "_origins": origins,
                    "_transitions": bounds,
                    "_namespace": group["namespace"],
                    "_created_at": group["created_at"],
                    "_runtime_id": record.id,
                    "_citations": sorted(evidence),
                }
            )
        result.sort(key=lambda item: (item["_created_at"], item["id"]))
        return result

    def eligible_experiences(
        self, conn, principal, brain_id, question, moment, *, project_id=None
    ):
        if context_pending(conn, brain_id=brain_id):
            return []
        result = []
        for item in self._procedures(
            conn, principal, brain_id, moment=moment, project_id=project_id
        ):
            if item["status"] != "active" or (
                not item["eligible"]
                and not any(bound > time.time() for bound in item["_transitions"])
            ):
                continue
            packet = self.private.compile(item["_namespace"], question)
            if not any(p.experience_id == item["_runtime_id"] for p in packet.items):
                continue
            result.append(
                {
                    "id": item["id"],
                    "project_id": item["project_id"],
                    "content": item["content"],
                    "verification": "verified_procedure",
                    "citation_ids": item["_citations"],
                    "origins": sorted(item["_origins"]),
                    "transitions": sorted(item["_transitions"]),
                    "applicable": item["eligible"],
                }
            )
        return result

    def review_experience(
        self,
        *,
        principal,
        brain_id,
        limit=100,
        outcome_cursor=None,
        procedure_cursor=None,
    ):
        with self.store.transaction() as conn:
            require_access(conn, principal, brain_id, "read")
            if type(limit) is not int or not 1 <= limit <= 100:
                raise invalid()
            outcomes = []
            for row in conn.execute(
                "SELECT * FROM outcomes WHERE brain_id=? ORDER BY created_at,id",
                (brain_id,),
            ):
                try:
                    _, data = self._outcome(conn, principal, brain_id, row["id"])
                except BrainError as error:
                    if error.code == "not_found":
                        continue
                    raise
                outcomes.append(
                    {
                        **self._public(row, data),
                        **{
                            k: data[k]
                            for k in (
                                "receipt_id",
                                "summary",
                                "procedure",
                                "evidence_citation_ids",
                                "project_id",
                                "reporter_id",
                            )
                        },
                    }
                )
            procedures = self._procedures(
                conn, principal, brain_id, moment=time.time(), all_projects=True
            )

            def page(items, cursor):
                if cursor is not None:
                    indices = [
                        i for i, item in enumerate(items) if item["id"] == cursor
                    ]
                    if not indices:
                        raise _not_found()
                    items = items[indices[0] + 1 :]
                selected = [
                    {k: v for k, v in item.items() if not k.startswith("_")}
                    for item in items[:limit]
                ]
                return selected, selected[-1]["id"] if len(items) > limit else None

            outcomes, next_outcome = page(outcomes, outcome_cursor)
            procedures, next_procedure = page(procedures, procedure_cursor)
            return {
                "outcomes": outcomes,
                "procedures": procedures,
                "next_outcome_cursor": next_outcome,
                "next_procedure_cursor": next_procedure,
            }

    def close(self):
        self.private.close()
