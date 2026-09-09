"""Transport-independent Brain application operations."""

import json
from pathlib import Path
from uuid import uuid4

from .access import _not_found, require_access
from .models import BrainError, Principal, bounded_text
from .store import BrainStore, record_change
from .sources import Sources, invalidate_source
from .reconcile import Reconciliation
from .context import Context


class BrainService:
    def __init__(self, state_dir: Path):
        self.store = BrainStore(state_dir)
        self.sources = Sources(self.store)
        self.reconciliation = Reconciliation(self.store)
        self.context = Context(self.store)
        # Reserved for Task5's private runtime; never supplied by a transport.
        # Task4 does not invoke it or invent experience/provenance authority.
        self._private_experience_provider = None

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
        return self.context.build_context(
            principal=principal,
            brain_id=brain_id,
            question=question,
            moment=moment,
            project_id=project_id,
            max_bytes=max_bytes,
        )

    def validate_packet(
        self, *, principal: Principal, brain_id: str, packet_id: str
    ) -> dict:
        return self.context.validate_packet(
            principal=principal, brain_id=brain_id, packet_id=packet_id
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
        return self.context.begin_action(
            principal=principal,
            brain_id=brain_id,
            packet_id=packet_id,
            run_id=run_id,
            action=action,
        )

    def create_entity(
        self,
        *,
        principal: Principal,
        brain_id: str,
        kind: str,
        name: str,
        citation_ids: list[str],
    ) -> dict:
        return self.reconciliation.create_entity(
            principal=principal,
            brain_id=brain_id,
            kind=kind,
            name=name,
            citation_ids=citation_ids,
        )

    def propose_claims(
        self, *, principal: Principal, brain_id: str, claims: list[dict]
    ) -> list[dict]:
        return self.reconciliation.propose_claims(
            principal=principal, brain_id=brain_id, claims=claims
        )

    def review_claims(
        self, *, principal: Principal, brain_id: str, claim_ids: list[str], action: str
    ) -> list[dict]:
        return self.reconciliation.review_claims(
            principal=principal, brain_id=brain_id, claim_ids=claim_ids, action=action
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
        return self.reconciliation.review_records(
            principal=principal,
            brain_id=brain_id,
            record_type=record_type,
            record_ids=record_ids,
            action=action,
        )

    def add_relation(
        self, *, principal: Principal, brain_id: str, relation: dict
    ) -> dict:
        return self.reconciliation.add_relation(
            principal=principal, brain_id=brain_id, relation=relation
        )

    def review_memory(self, *, principal: Principal, brain_id: str) -> dict:
        return self.reconciliation.review_memory(principal=principal, brain_id=brain_id)

    def recheck_dependencies(self, *, principal: Principal, brain_id: str) -> dict:
        return self.reconciliation.recheck_dependencies(
            principal=principal, brain_id=brain_id
        )

    def preview_import(
        self, *, principal: Principal, brain_id: str, files: list[dict]
    ) -> dict:
        return self.sources.preview_import(
            principal=principal, brain_id=brain_id, files=files
        )

    def commit_import(
        self,
        *,
        principal: Principal,
        brain_id: str,
        preview_id: str,
        accepted_ids: list[str],
    ) -> dict:
        return self.sources.commit_import(
            principal=principal,
            brain_id=brain_id,
            preview_id=preview_id,
            accepted_ids=accepted_ids,
        )

    def read_citation(
        self, *, principal: Principal, brain_id: str, citation_id: str
    ) -> dict:
        return self.sources.read_citation(
            principal=principal, brain_id=brain_id, citation_id=citation_id
        )

    def list_sources(self, *, principal: Principal, brain_id: str) -> list[dict]:
        return self.sources.list_sources(principal=principal, brain_id=brain_id)

    def change_source(
        self, *, principal: Principal, brain_id: str, source_id: str, action: str
    ) -> dict:
        return self.sources.change_source(
            principal=principal, brain_id=brain_id, source_id=source_id, action=action
        )

    def close(self):
        self.store.close()

    def create_brain(
        self, *, principal: Principal, title: str, mode: str = "personal"
    ) -> dict:
        # Creating a new owner is a trusted human bootstrap operation. A token
        # scoped to existing Brains cannot acquire a new scope by creating one.
        if (
            not isinstance(principal, Principal)
            or principal.kind != "human"
            or principal.brain_ids is not None
            or (
                principal.operations is not None
                and "manage_access" not in principal.operations
            )
        ):
            raise _not_found()
        bounded_text(title, maximum=500)
        if mode not in ("personal", "team"):
            raise BrainError("invalid_input", "Invalid Brain mode.")
        brain_id = uuid4().hex
        with self.store.transaction(write=True) as conn:
            conn.execute(
                "INSERT INTO brains(id,title,mode,owner) VALUES (?,?,?,?)",
                (brain_id, title, mode, principal.identity),
            )
            conn.execute(
                "INSERT INTO members(brain_id,identity,role) VALUES (?,?,'owner')",
                (brain_id, principal.identity),
            )
            record_change(
                conn,
                brain_id=brain_id,
                kind="brain_created",
                record_id=brain_id,
                increment=False,
            )
            return dict(
                conn.execute("SELECT * FROM brains WHERE id=?", (brain_id,)).fetchone()
            )

    def list_brains(self, *, principal: Principal) -> list[dict]:
        if not isinstance(principal, Principal):
            raise _not_found()
        with self.store.transaction() as conn:
            rows = conn.execute(
                """SELECT b.* FROM brains b JOIN members m ON m.brain_id=b.id
                   WHERE m.identity=? ORDER BY b.id""",
                (principal.identity,),
            ).fetchall()
            visible = []
            for row in rows:
                try:
                    require_access(conn, principal, row["id"], "read")
                except BrainError as error:
                    if error.code != "not_found":
                        raise
                else:
                    visible.append(dict(row))
            return visible

    def set_member(
        self, *, principal: Principal, brain_id: str, identity: str, role: str | None
    ) -> None:
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "manage_access")
            bounded_text(identity)
            if role not in (None, "owner", "editor", "reader"):
                raise BrainError("invalid_input", "Invalid membership role.")
            current = conn.execute(
                "SELECT role FROM members WHERE brain_id=? AND identity=?",
                (brain_id, identity),
            ).fetchone()
            if current is not None and current["role"] == "owner" and role != "owner":
                owners = conn.execute(
                    "SELECT identity FROM members WHERE brain_id=? AND role='owner' ORDER BY identity",
                    (brain_id,),
                ).fetchall()
                if len(owners) == 1:
                    raise BrainError("invalid_input", "A Brain must retain an owner.")
                successor = next(
                    row["identity"] for row in owners if row["identity"] != identity
                )
                conn.execute(
                    "UPDATE brains SET owner=? WHERE id=? AND owner=?",
                    (successor, brain_id, identity),
                )
            if role is None:
                conn.execute(
                    "DELETE FROM members WHERE brain_id=? AND identity=?",
                    (brain_id, identity),
                )
            else:
                conn.execute(
                    """INSERT INTO members(brain_id,identity,role) VALUES (?,?,?)
                       ON CONFLICT(brain_id,identity) DO UPDATE SET role=excluded.role""",
                    (brain_id, identity, role),
                )
            # Membership identities can be personal data; the audit records only
            # the Brain's opaque ID and the operation, never the member payload.
            record_change(
                conn,
                brain_id=brain_id,
                kind="member_removed" if role is None else "member_set",
                record_id=brain_id,
            )

    def set_source_access(
        self,
        *,
        principal: Principal,
        brain_id: str,
        source_id: str,
        readers: list[str] | None,
    ) -> None:
        with self.store.transaction(write=True) as conn:
            require_access(conn, principal, brain_id, "manage_access")
            if (
                not isinstance(source_id, str)
                or conn.execute(
                    "SELECT 1 FROM sources WHERE brain_id=? AND id=?",
                    (brain_id, source_id),
                ).fetchone()
                is None
            ):
                raise _not_found()
            if readers is not None:
                if not isinstance(readers, list):
                    raise BrainError("invalid_input", "Invalid source readers.")
                readers = sorted({bounded_text(reader) for reader in readers})
            conn.execute(
                "UPDATE sources SET readers_json=? WHERE brain_id=? AND id=?",
                (None if readers is None else json.dumps(readers), brain_id, source_id),
            )
            invalidate_source(
                conn, brain_id=brain_id, source_id=source_id, reason="access_changed"
            )
            record_change(
                conn, brain_id=brain_id, kind="source_access_set", record_id=source_id
            )
