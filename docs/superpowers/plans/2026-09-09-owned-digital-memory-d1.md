# Owner-controlled digital memory D1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a usable, persistent engineering preview that lets an owner carry a personal project or client case between agents, correct its memory, and reuse independently reviewed experience without losing control of sources.

**Architecture:** Add an isolated `wavemind.brain` domain behind a shared service used by HTTP, MCP and the owner UI. SQLite is authoritative; the existing experience runtime has a separate private database and a durable idempotent outbox. Existing generic APIs and research semantics remain unchanged.

**Tech Stack:** Python >=3.10, SQLite, existing FastAPI/Pydantic/pypdf, vanilla HTML/CSS/JavaScript, optional existing MCP package, pytest, Ruff, isolated Chrome/Playwright for UI verification.

**Spec:** [Approved design](../specs/2026-09-09-owned-digital-memory-design.md), approved 2026-09-09; baseline `00192c3faed463e08e90a3e898fc84378b43a028`.

## Global Constraints

- Authoritative database: `brain.sqlite3`; private existing-runtime database: `brain-experience.sqlite3`. Neither is mounted on generic memory/experience routes.
- Context contract: `wavemind.brain_context.v1`. Existing ExperiencePacket and scientific-memory contracts remain unchanged.
- Validity: `[valid_from, valid_until)`; statuses: `proposed`, `active`, `conflicted`, `superseded`, `revoked`.
- Import: 20 files, 10 MiB per file, 50 MiB per import, 2 MiB extracted UTF-8 text per file, 30 seconds parsing per file. No archives, symlink/reparse traversal, HTTP server-path reads, or automatic external calls.
- Exact Brain ID and all originating source IDs authorize every read, derived record, citation, history and export. Missing authorization fails closed; principal is transport-bound, never request-supplied.
- Owner/editor/reader membership and independently restricted agent operations; agent proposals are not owner approval or trusted verification. Claims are not established causal effects.
- D1 is plaintext local storage for nonsecret pilot materials. No encrypted-storage, mass-installer, scientific-breakthrough, paid-provider, or measured-user-value claim.
- RU and EN owner interface, explicit preview/confirmation, freshness/coverage/conflicts/unknowns, visible errors and cancellation. No fabricated model answers or automatically selected personal accounts.
- Preserve prior research and failed results. D2 Windows installation, D3 team deployment and D4 real usefulness/research validation remain required separate stages; D1 tests cannot satisfy them.
- Existing linked worktree `work/wavemind-breakthrough` and branch `design/owned-digital-memory-20260909`; do not create/delete other worktrees or edit unrelated work.
- Use `apply_patch`, TDD with observed RED/GREEN, focused commits, per-task review. Do not weaken existing tests or evidence admissions to obtain green status.

## Execution and shared conventions

The controller reads the approved spec and self-reviews this plan. Tasks execute in order, one implementer at a time with a fresh read-only reviewer. Each brief includes this Global Constraints section. Review findings and exact commits/tests are recorded in `.superpowers/sdd/2026-09-09-owned-digital-memory-d1/progress.md`.

PowerShell test commands run from the worktree. Set `PYTHONPATH` to that directory, `PYTHONDONTWRITEBYTECODE=1`, and per-process `GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=safe.directory`, `GIT_CONFIG_VALUE_0` to the exact worktree. Interpreter is `../wavemind/.venv/Scripts/python.exe`. Use a newly generated, nonexisting short `--basetemp` path such as `Join-Path $env:TEMP ('wmb-' + [guid]::NewGuid().ToString('N'))` with `-p no:cacheprovider`; nested Git fixtures exceed Windows path limits under the deep plan directory. Reports, briefs and review packages still belong to the plan workspace. Never reuse a populated basetemp (pytest removes it). Earlier baseline used D: while write access existed; after the permission change use only the authorized worktree/system temp. In examples below, `python` means that interpreter with these settings. Run `python -m ruff check` against changed Python files after GREEN. Each task adds literal expected outcomes, negative controls and restart checks, not source-text assertions.

Public JSON values are ordinary dictionaries/lists/primitives validated at the boundary. Domain errors are `BrainError(code: str, message: str)`; unauthorized/nonexistent resources share `not_found`, and errors contain no hidden title/content/count. In-process callers are trusted to supply a `Principal`; untrusted HTTP/MCP callers cannot construct one. IDs are opaque UUID hex strings except owner-supplied claim IDs, which are bounded opaque identifiers (needed for reordered corrections). Times are finite UTC epoch seconds; unknown bounds are `None`. Every data operation has keyword-only arguments and `principal: Principal`; none obtains identity from payload.

### File map

| Unit | Files | Responsibility |
|---|---|---|
| Foundation | `wavemind/brain/{__init__,models,store,access,service}.py` | Records, transactional state, exact ACL, shared facade |
| Import | `wavemind/brain/{sources,parsing}.py` | Bounded preview, approved commit, source versions and citations |
| Reconciliation | `wavemind/brain/reconcile.py` | Explicit claims/entities/relations, conflicts, correction and dependency lifecycle |
| Context | `wavemind/brain/context.py` | Scoped selection, honest budget, packet validity and preaction receipts |
| Experience | `wavemind/brain/experience_bridge.py` | Trusted outcome review, private runtime, durable integration and purge |
| Portability | `wavemind/brain/portability.py` | Full export, consistent backup, validated/quarantined restore |
| Transport | `wavemind/brain/{auth,http,mcp,cli}.py` | Bound credentials, strict routes and MCP/CLI entry points |
| Owner app | `wavemind/brain/ui/{index.html,app.js,style.css}` | Accessible RU/EN first-use and daily memory workflow |
| User guidance | `docs/brain/{personal,teams,agent-contract,limitations}.md` | Truthful use, setup, rights and current limits |
| Acceptance | `tests/brain/`, `scripts/verify_brain_d1.py` | Persistence, abuse cases and real transport/UI scenarios |

## Shared service contract

`Principal(identity: str, kind: str = "human", brain_ids: frozenset[str] | None = None, operations: frozenset[str] | None = None)` is frozen. `None` means no additional token restriction, NOT membership in any Brain. Membership and source ACL still apply. Agent grants must provide nonempty exact brain IDs and explicit operations. Human identity is a local bootstrap owner or stored authenticated membership, not an arbitrary JSON field.

`BrainService(state_dir: Path)` owns a `BrainStore`, closes with `close()`, and delegates domain operations to small modules. `BrainStore.transaction(*, write: bool = False)` yields a sqlite connection under a process lock; writes use `BEGIN IMMEDIATE`, foreign keys and rollback. All writes, authorization and revision increments share one transaction. Cross-process writers are serialized by SQLite, not only a Python lock. `require_access(conn, principal, brain_id, operation, source_ids=())` checks live rights using that same transaction. `allowed_sources(conn, principal, brain_id)` returns exact readable IDs; derived reads require all dependencies, never any one.

The public service functions and dictionary fields below are the contracts produced by each task. Internal SQL helpers may be added in their responsible module. No module may copy private Brain data into the old default databases.

### Task 0: Repair existing cross-volume upgrade recovery

**Files:** Modify `wavemind/upgrade.py:restore_upgrade_backup`; extend `tests/test_upgrade.py`. This prerequisite was added after the baseline run exposed a real failure with TEMP on C: and the selected data profile on D:.

**Interfaces:** Preserve `restore_upgrade_backup(path: Path) -> None` and the existing archive format. No dependency on the new Brain code. Every restored candidate and its recovery copy must permit same-filesystem atomic replacement at its own target, including profiles whose assets live on different volumes. Validation happens before replacement; a subsequent failure restores exact prior bytes or prior absence for already touched targets. Do not change TMP/TEMP to conceal the defect or use non-atomic move fallback for the final replacement.

- [ ] Reproduce existing `test_interrupted_journal_is_recovered_before_retry` with system TEMP unchanged on C: and fresh pytest basetemp under `D:/codex-brain-d1`; observed RED is `OSError: [WinError 17]` at `os.replace(candidate, target)`.
- [ ] Add a portable regression which models volume boundaries through `os.replace` while checking real restored contents:

```python
def test_restore_stages_each_asset_on_its_target_volume(tmp_path, monkeypatch):
    import errno
    first, second = tmp_path / "volume-a", tmp_path / "volume-b"
    first.mkdir()
    second.mkdir()
    core, experience, _, _ = _state(first)
    config = second / "client.json"
    config.write_text('{"saved": true}', encoding="utf-8")
    wheel, digest = _wheel(first / "wavemind-2.12.1-py3-none-any.whl", "2.12.1")
    options = _options(first, core, experience, wheel, digest, config_paths=(config,))
    archive = create_upgrade_backup(options, first / "backup.zip", source_version="2.12.1", target_version="2.12.1")
    config.write_text("changed", encoding="utf-8")
    real_replace = upgrade.os.replace
    def volume(path):
        resolved = Path(path).resolve()
        return next((root for root in (first, second) if resolved.is_relative_to(root)), None)
    def same_volume_only(source, target):
        if volume(source) != volume(target):
            raise OSError(errno.EXDEV, "cross-device replacement")
        return real_replace(source, target)
    monkeypatch.setattr(upgrade.os, "replace", same_volume_only)
    restore_upgrade_backup(archive)
    assert config.read_text(encoding="utf-8") == '{"saved": true}'
    assert database_inventory(core)["tables"]["memories"]["rows"] == 1
```

  Run the new test before production change and observe cross-device RED. Add failure injection on a later asset with real unchanged earlier bytes, missing target restoration and task-owned staging cleanup assertions.
- [ ] Allocate candidate/rollback staging per target using `TemporaryDirectory(dir=target.parent)` managed across the restore by `contextlib.ExitStack`, preserving rollback files until the whole operation succeeds. Copy archive bytes there, validate SQLite candidates before replacing, and recover with same-target-volume replacements where possible. Retain original failure and report rollback failure as `UpgradeRollbackError`. Never mutate unrelated files.

```python
with contextlib.ExitStack() as stack:
    local = Path(stack.enter_context(tempfile.TemporaryDirectory(
        prefix=".wavemind-restore-", dir=target.parent)))
    candidate = local / "candidate"
```

  The stack covers the entire multi-target restore, not one loop iteration. Rollback must run before stack cleanup.
- [ ] Run focused regression, all `tests/test_upgrade.py` and Ruff, inspect diff and commit `fix: restore upgrade assets atomically across data volumes`. Review this prerequisite independently before Task 1. Repeat final full-suite verification after the repair; the initial baseline had 1323 pass, 14 skips and one third-party Pydantic warning before this failure.

### Task 1: Persistent Brain state and exact authorization

**Files:** Create `wavemind/brain/__init__.py`, `models.py`, `store.py`, `access.py`, `service.py`; create `tests/brain/__init__.py`, `tests/brain/test_store_access.py`.

**Interfaces:** Produce `Principal`, `BrainError`, `BrainStore.transaction`, `require_access`, `allowed_sources`, `BrainService` above. Service methods: `create_brain(*, principal, title: str, mode: str = "personal") -> dict`; `list_brains(*, principal) -> list[dict]`; `set_member(*, principal, brain_id: str, identity: str, role: str | None) -> None`; `set_source_access(*, principal, brain_id: str, source_id: str, readers: list[str] | None) -> None`. Brain dict has `id,title,mode,owner,revision`. `readers=None` means all current members; an explicit list restricts nonowner members. Owner always controls their own sources. Revoked/quarantined/deleted sources are unreadable even to owner through normal context/citation routes; management status is separate and sanitized.

- [ ] Write tests before implementation:

```python
def test_restart_membership_is_exact_and_readers_cannot_grant(tmp_path):
    from wavemind.brain.service import BrainService
    from wavemind.brain.models import Principal, BrainError
    import pytest
    owner, guest = Principal("owner"), Principal("guest")
    service = BrainService(tmp_path)
    brain = service.create_brain(principal=owner, title="Project", mode="personal")
    service.set_member(principal=owner, brain_id=brain["id"], identity="guest", role="reader")
    service.close()
    service = BrainService(tmp_path)
    assert [b["id"] for b in service.list_brains(principal=guest)] == [brain["id"]]
    with pytest.raises(BrainError):
        service.set_member(principal=guest, brain_id=brain["id"], identity="intruder", role="owner")
    assert service.list_brains(principal=Principal("guest-prefix")) == []
    service.close()
```

- [ ] Run `python -m pytest tests/brain/test_store_access.py -q`; observe missing feature RED, then behavioral assertions. Add interleaved-writer rollback/revision tests, agent missing-grants refusal and no shared default DB creation.
- [ ] Implement schema version 1 with explicit tables for brains, members, sources, source_versions, chunks, previews, entities, claims, relations, dependencies, packets, receipts, outcomes, outbox, tombstones and minimal audit. Schema columns can be JSON for versioned records; relational keys must scope by brain/source. Store IDs/type-only audit, not raw payload. Transactions follow this pattern:

```python
with store.transaction(write=True) as conn:
    require_access(conn, principal, brain_id, "manage_access")
    conn.execute("DELETE FROM members WHERE brain_id=? AND identity=?", (brain_id, identity))
    conn.execute("UPDATE brains SET revision=revision+1 WHERE id=?", (brain_id,))
```

  Validate bounded nonempty identity/title/mode/role; prevent removal of the sole owner. Permission operations are `read`, `import`, `propose`, `review`, `record_outcome`, `verify_outcome`, `manage_access`, `delete`, `export`, `restore`. Human editors can import/propose/record but not approve/trust/delete/grant; readers only read. Agents cannot approve/trust/delete/grant even if a request claims those roles. Future data modules must use this one authority.
- [ ] Run focused tests and Ruff, inspect new schema and reopen behavior, commit `feat(brain): add isolated persistent state and exact access control`.

### Task 2: Explicit bounded import and source lifecycle

**Files:** Create `wavemind/brain/sources.py`, `parsing.py`, `tests/brain/test_sources.py`; extend `service.py` delegation and schema only if required.

**Interfaces:** Consume Task 1 transactions/ACL. Produce service `preview_import(*, principal, brain_id: str, files: list[dict]) -> dict`, `commit_import(*, principal, brain_id: str, preview_id: str, accepted_ids: list[str]) -> dict`, `read_citation(*, principal, brain_id: str, citation_id: str) -> dict`, `list_sources(*, principal, brain_id: str) -> list[dict]`, `change_source(*, principal, brain_id: str, source_id: str, action: str) -> dict`. Each input file is `{name: str, content: bytes, source_id?: str}`; pasted text becomes explicit UTF-8 bytes. No public file-path field. Preview returns `id,files:[{id,name,status,error,bytes,extracted_bytes,source_id,preview_text}],network_calls:0,model_connected:false`. Commit returns `sources:[{id,version,citations:[{id,text,start,end}]}]`. Citation returns exact `id,source_id,version,text,start,end`. Source actions are `pause`, `resume`, `revoke`, `delete`; both revoke/delete immediately invalidate packets/dependents in the authoritative transaction. `Sources` module exposes the same methods; facade delegates.

- [ ] Write tests:

```python
def test_preview_commit_retry_and_exact_citation(tmp_path):
    from wavemind.brain.service import BrainService
    from wavemind.brain.models import Principal
    s, owner = BrainService(tmp_path), Principal("owner")
    b = s.create_brain(principal=owner, title="Notes")["id"]
    p = s.preview_import(principal=owner, brain_id=b, files=[{"name": "note.md", "content": b"Ship on Friday."}])
    assert p["network_calls"] == 0
    assert s.list_sources(principal=owner, brain_id=b) == []
    args = dict(principal=owner, brain_id=b, preview_id=p["id"], accepted_ids=[p["files"][0]["id"]])
    first, second = s.commit_import(**args), s.commit_import(**args)
    assert first == second
    citation = first["sources"][0]["citations"][0]
    assert s.read_citation(principal=owner, brain_id=b, citation_id=citation["id"])["text"] == "Ship on Friday."
    s.close()
```

- [ ] Observe RED with `python -m pytest tests/brain/test_sources.py -q`. Add literal boundary cases for all five limits; changed source is explicit; identical content without explicit source ID uses content digest identity within the same Brain, not filename. Competing names cannot silently update existing sources.
- [ ] Implement UTF-8 text/Markdown, text PDF using pypdf in a bounded subprocess and `wavemind.messages.v1` JSON `{schema,messages:[{role,content,timestamp?}]}`. JSON fields and types are strict, total extracted UTF-8 limit applies after normalization. PDF subprocess receives bytes through a temporary task-owned file/pipe, hard timeout/termination, no unsafe pickle from the source. Reject encrypted, empty/scanned, malformed documents and archives; no parser success with empty content. Local CLI path loader later checks every reparse/symlink ancestor. Persist bounded previews with creator/Brain binding, expiry, and idempotency; commit only accepted valid IDs, never hidden partial success. Chunk by character boundaries with exact offsets and bounded UTF-8 sizes. Use digest, not basename, for duplicate detection:

```python
digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
with store.transaction(write=True) as conn:
    require_access(conn, principal, brain_id, "import")
    existing = conn.execute(
        "SELECT version FROM source_versions WHERE brain_id=? AND source_id=? AND digest=?",
        (brain_id, source_id, digest),
    ).fetchone()
```

  Source ACL/update/revoke/delete must purge derived source text in previews and enqueue only opaque IDs for private-experience cleanup. Purge all linked live claim/packet/receipt text on delete without deleting the upstream file. Preserve minimal tombstone and disclose retained backup limitations. Use one shared lifecycle invalidation helper that Task 3 extends, not separate conflicting implementations.
- [ ] Run source+foundation tests and Ruff; commit `feat(brain): add reviewed bounded imports and source controls`.

### Task 3: Typed claims, explicit entities, corrections and dependencies

**Read-only eligibility failure signaling (controller ruling):** `record_eligible` returns booleans for ordinary eligibility, but bounded/cycle-safe prerequisite verification raises sanitized `BrainError` codes `dependency_limit` or `dependency_cycle` when verification cannot complete. It must not mutate a caller-owned read transaction. Existing lifecycle/recovery writes persist pending; Task4's authorized packet-building write transaction catches these named failures, marks Brain-wide pending and discards all partially collected context. No partial/actionable packet may escape. Supersession lineage requires reviewed, nonstale origins but not temporal overlap with the replaced predecessor; ordinary prerequisites use the requested as-of time.

**Entity-type/erasure refinement (controller ruling):** Entity kinds are the explicit `person,organization,project,client,artifact` types from spec4.2, not user-supplied descriptive content. Validate this allowlist before storing proposals. Permanent deletion must also erase any previously persisted free-text entity kind rather than retaining content outside payload_json; preserve only opaque identity and non-content lifecycle metadata. Cover both rejected arbitrary input and a legacy persisted free-text kind in erasure tests.

**Backdated correction refinement (controller ruling):** An approved correction beginning before its predecessor's declared start is legitimate. Keep original bounds unchanged and represent the predecessor's derived intersection as explicitly empty, never inverted. One supported representation is equal effective bounds plus `effective_empty=true`; user-supplied empty/inverted intervals remain invalid. Both event arrival orders must agree, and neither historical context nor replacement expiry may admit the empty predecessor. Carry the chosen exact representation into Task4/UI handoffs.

**Erasure-only cap exception (controller ruling):** Normal dependency eligibility/invalidation traversal remains capped at10,000 visited nodes with persisted fail-closed pending state. Successful permanent deletion must erase the complete exact affected closure, so an exact-Brain recursive SQL `UNION` closure may exceed that node cap solely for content erasure. Use finite execution cancellation, cycle termination, allowlisted record types, and the same authorized transaction; keep dependency rows until all affected payloads are scrubbed. Cancellation/failure rolls back atomically and returns a sanitized failure, never complete or partial success. Test overflow erasure, unchanged unrelated records, a cycle, and forced interruption. This is not permission to use unbounded traversal for reads or to purge the whole Brain.

**Controller refinement against approved spec (rulings recorded in SDD ledger):** Add owner-only `review_records(*, principal, brain_id, record_type, record_ids, action) -> list[dict]`, with record_type `entity|relation` and action `approve|reject|recheck`. `create_entity` and `add_relation` always produce proposals; no unreviewable or automatically approved agent data. Add schema v2 `brain_context_state(brain_id PRIMARY KEY, pending, reason)` with an atomic v1 migration/restart test, and source-owned/shared `context_pending(conn, brain_id)` eligibility helper. Owner-only `recheck_dependencies(*, principal, brain_id) -> {pending,reason}` validates the bounded eligible dependency graph before clearing the global gate; it does not approve records or clear individual needs_recheck flags. If the graph still exceeds safe bounds, pending remains; test a recoverable graph after explicit rejection/deletion reduces affected scope.

A superseding correction needs a finite explicit effective start for activation (`valid_from`, otherwise `event_time`); missing start remains unknown/proposed with a pending reason. Preserve input bounds and derive effective bounds from reviewed decisions. A replacement ending never revives the predecessor, but a rejected competing correction does not continue clipping it. Example: old starts100; competing A starts200, B starts210 and ends300; after owner rejects A and selects B, old applies at205, B at210, old does not return at300. Include these tests plus restricted-agent nonclaim approval denial. Transport/UI tasks below consume the added review/recovery operations.

**Files:** Create `wavemind/brain/reconcile.py`, `tests/brain/test_reconcile.py`; extend `service.py`, source lifecycle helper and models/schema as needed.

**Interfaces:** Service `create_entity(*, principal, brain_id: str, kind: str, name: str, citation_ids: list[str]) -> dict`; `propose_claims(*, principal, brain_id: str, claims: list[dict]) -> list[dict]`; `review_claims(*, principal, brain_id: str, claim_ids: list[str], action: str) -> list[dict]`; `review_memory(*, principal, brain_id: str) -> dict`; `add_relation(*, principal, brain_id: str, relation: dict) -> dict`. Claim input `{id?,kind,content,key,citation_ids,entity_ids?,depends_on?,supersedes?,valid_from?,valid_until?,event_time?}`; output includes `id,status,registered_at` and all validated input. Kinds `fact,goal,constraint,decision,commitment`. `key` is the explicitly reviewed topic/scope for conflict detection, not automatic semantic truth detection. Review actions `approve,reject,recheck`; owner resolving a conflict explicitly rejects alternatives then approves selected claim. `review_memory` returns permitted `claims,entities,relations,changes,pending` without hidden counts/content. Relations `{kind,from_id,to_id,citation_ids,depends_on?}` use `related_to,supersedes,depends_on,justified_by,action_outcome`; endpoints must belong to the same Brain and be visible.

- [ ] Write behavior tests before code:

```python
def test_competing_values_do_not_choose_latest_import(source_fixture):
    s, owner, brain_id, citation_id = source_fixture
    rows = s.propose_claims(principal=owner, brain_id=brain_id, claims=[
        {"id": "a", "kind": "constraint", "key": "budget", "content": "100", "citation_ids": [citation_id]},
        {"id": "b", "kind": "constraint", "key": "budget", "content": "200", "citation_ids": [citation_id]},
    ])
    assert [r["status"] for r in rows] == ["proposed", "proposed"]
    s.review_claims(principal=owner, brain_id=brain_id, claim_ids=["a", "b"], action="approve")
    assert {r["status"] for r in s.review_memory(principal=owner, brain_id=brain_id)["claims"]} == {"conflicted"}
```

  Define the local `source_fixture` by creating one Brain, previewing/committing a Markdown source with `"Budget evidence"` and yielding its first citation; close the service in fixture teardown. Add correction in both arrival orders, different event/import times, half-open adjacent intervals, unknown original, cross-Brain reference denial, identical names distinct entities, dependency cycle/bounded traversal, conflicting correction forks and deletion of all derived text tests.
- [ ] Run `python -m pytest tests/brain/test_reconcile.py -q` and inspect RED.
- [ ] Implement explicit reviewed semantic keys and deterministic reconciliation from stored approvals/effective events. Approving an unresolved correction records intent but leaves it proposed; receipt of the original reconciles the same set regardless of import order. Invalid/denied citation is never used to authorize a foreign claim. SQL work stays in one transaction with source authorization. Overlap is:

```python
def overlaps(a_start, a_end, b_start, b_end):
    return (a_end is None or b_start is None or b_start < a_end) and (
        b_end is None or a_start is None or a_start < b_end
    )
```

  Reject nonfinite/inverted intervals, empty evidence, unknown entity/dependency, and cycles. Preserve explicit event validity/history: a correction must not erase earlier as-of meaning, nor make the old statement current after its replacement interval. For a changed dependency conservatively require owner recheck; do not auto-reactivate downstream data by import ordering. Bound closure at 10,000 visited nodes; overflow marks the entire affected Brain context pending (fail closed), not partially trustworthy. Lifecycle deletion purges content of all derived records/outbox payloads; minimal IDs-only audit is retained.
- [ ] Run foundation/source/reconcile tests and Ruff; commit `feat(brain): track reviewed temporal claims and dependency invalidation`.

### Task 4: Budgeted current context and preaction receipts

**Persisted scope field:** Extend the packet field list below with required nullable `project_id`, storing the authorized project/client selector in the canonical persisted and public v1 packet, including digest and cost accounting. A receipt inherits scope from its validated packet. Task5 applicability must not infer scope from question text or whichever claim happened to fit the byte budget.

**Task4 boundary refinements (controller rulings):** Build/validate require read; begin_action requires record_outcome plus independent read, reusing the existing operation taxonomy and never executing its action string. `project_id` selects an explicit same-Brain approved/readable entity of kind project or client, referenced in claim.entity_ids; no name matching or automatic project merging. Hidden/missing/ineligible selectors fail closed, never fall back to global retrieval. Explicit project filtering omits unscoped source-only evidence. Keep Task4 experiences empty and its service-owned private extension point uninvoked until Task5 defines the actual verified-runtime item/provenance contract and tests integration. No transport-supplied provider/trust fields or prematurely simulated experience. Digest hashes the complete canonical packet excluding digest only; final cost.bytes includes the digest and cost envelope itself.

**Files:** Create `wavemind/brain/context.py`, `tests/brain/test_context.py`; extend service.

**Interfaces:** `build_context(*, principal, brain_id: str, question: str, moment: float | None = None, project_id: str | None = None, max_bytes: int = 16384) -> dict`; `validate_packet(*, principal, brain_id: str, packet_id: str) -> dict`; `begin_action(*, principal, brain_id: str, packet_id: str, run_id: str, action: str) -> dict`. Packet fields `schema,id,brain_id,principal_id,revision,question,moment,claims,citations,experiences,conflicts,unknowns,coverage,warnings,cost,expires_at,digest`. `cost` distinguishes actual serialized UTF-8 `bytes`, estimated `tokens`, `network_calls=0`; enforce budget on complete packet, not snippets only. `begin_action` returns `id,packet_id,packet_digest,revision,run_id,action,status`; status starts `pending_outcome`. Receipt is captured before the action and unique per Brain/run/action/packet. Packet validity max 15 minutes; future validity transitions shorten expiry. Experience list is empty before Task 5; a single optional private provider hook is set by the service, not transport input.

- [ ] Write tests:

```python
def test_revocation_blocks_issued_packet_and_citation(active_claim_fixture):
    import pytest
    from wavemind.brain.models import BrainError
    s, owner, brain_id, source_id, citation_id = active_claim_fixture
    packet = s.build_context(principal=owner, brain_id=brain_id, question="Next step?")
    assert packet["schema"] == "wavemind.brain_context.v1"
    assert packet["claims"]
    s.change_source(principal=owner, brain_id=brain_id, source_id=source_id, action="revoke")
    with pytest.raises(BrainError):
        s.validate_packet(principal=owner, brain_id=brain_id, packet_id=packet["id"])
    with pytest.raises(BrainError):
        s.read_citation(principal=owner, brain_id=brain_id, citation_id=citation_id)
```

  Define fixture using source workflow plus one approved goal, and test two restricted agents with disjoint sources; ancestor dependencies, expired interval, malicious source instruction, packet-tamper, foreign packet identity, guessed receipt, exact byte budget, renamed query/source data, hidden conflict labels/counts, and old generic API isolation.
- [ ] Run `python -m pytest tests/brain/test_context.py -q`; observe RED.
- [ ] Build deterministic lexical candidate selection from the authoritative permitted rows; reuse existing lexical helpers only where semantics match. No mandatory embeddings/download/model. Rank by explicit project filter, query overlap and stable IDs. Include applicable active claims, permitted conflicts and genuine unknowns; source-only search may return clearly labeled unreviewed evidence, never promote it to active truth. Omit expired/superseded/conflicted text as actionable facts; mention uncertainty without leaking restricted content. If a projection is unavailable, bounded authoritative fallback reports a warning. Serialize/digest canonically and reduce selected content until full envelope fits; refuse budgets too small for the envelope.

```python
def canonical_bytes(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
```

  Validate live revision, all dependency/source rights and expiry again on read/reapplication. Recompute digest independently of mutable client JSON. Server records receipt binding in one transaction and only accepts a currently valid persisted packet; calling `begin_action` after a stale packet fails, regardless of client-supplied success.
- [ ] Run all `tests/brain` and Ruff; commit `feat(brain): issue scoped context with revocable action receipts`.

### Task 5: Verified outcomes and private reusable experience

#### Controller-approved Task5 contract refinements

- Private procedure isolation/recovery: namespace is `brain:{brain_id}:{basis_digest}:{SHA256(canonical ordered reported-procedure list)}`. Different procedures cannot share contributing outcome IDs, authorization, scores or purge. Successful full private purge sets retained outcome integration_status='purged', preserves actual history/attestation/old public experience IDs and replay hashes, then retires only that sub-scope's current brain_experience_links mappings and acknowledges its old pending integration work in the same Brain transaction. Failure or private-purge-before-ack retains opaque mappings for retry. Before any new verification/callback/integration mapping in a dirty sub-scope, raise sanitized cleanup_pending; history recording remains allowed, callback is not invoked, and caller can drain then retry the same outcome. Existing immutable attestation retry remains historical/idempotent, never requeues. Drain prioritizes cleanup; fresh post-cleanup independent runs start with empty runtime validation credit and must earn every existing promotion gate. Validate encountered pre-fix scope formats against authoritative basis+procedure and fail closed for mixed old namespaces. Cover sibling isolation, same-basis ACL restoration with three fresh runs, pending callback suppression/retry, purge-before-ack crash and old evidence replay.

- Authoritative v3 opaque-only tables are approved: brain_experience_links with composite Brain/outcome FK, unique Brain/outcome/runtime-ID mappings and an empty-ID pending scope mapping; brain_experience_evidence with unique (brain_id,key) replay hashes and composite outcome FK. Their constraints support deterministic integration and deletion retry after text erasure without source text in outbox. Preserve these tables in Task6 structural archive validation; no extra public authority follows from them.

- Provider items also carry private strict-bool `applicable`. Completed-authorized active-runtime candidates that are temporarily ineligible still contribute their verified governing origins and future transitions to packet invalidation/expiry; only applicable items become public experience groups. Missing/nonbool applicability fails closed. Hidden/missing/unproven candidates yield no partial authority; cycle/limit persists pending and discards actionable partial output. Test an empty scoped packet crossing a future procedure prerequisite and erasure of a bound-only contributor.

- Manifest strengthening: store opaque SHA256 `basis_digest TEXT` beside the governing origin triples, computed in the same issuance transaction. Late outcomes consume this immutable issuance digest; live integration/reuse recomputes and compares rather than relabeling an old result with current basis. Legacy empty-experience packets may acquire a current digest only after proving original active packet/current revision and complete legacy origins; stale legacy packets remain authorized historical reports but nonintegrable. Missing/malformed digest on a new bridge-era packet fails closed. Test issuance on basis A, reviewed change to B, then late report/verification: old outcome cannot inherit B namespace or scores; expiry alone still does not prevent authorized historical reporting.

- Historical receipt validation checks persisted receipt/packet IDs, canonical digest binding, original actionable coverage and issuance-window ordering, then current actual caller operation plus read over all retained origins. Current expiry, unrelated memory revision or different issuer identity do not by themselves prevent historical recording/owner verification. Store the actual reporter separately from receipt issuer. Historical success never reapplies a stale packet; current procedure reuse separately verifies live basis, pending and lifecycle.
- Private scope uses Brain ID, explicit nullable project_id and a deterministic governing-basis fingerprint. Canonical basis includes governing semantic/source origin triples; governing sources' latest version id/version/digest/status; relevant cited chunk id/version_id/source_id; semantic type/id/status and present kind/name/key/content/citation_ids/depends_on/entity_ids/supersedes/from_id/to_id/valid_from/valid_until/effective_valid_from/effective_valid_until/effective_empty/_review/needs_recheck. Exclude run/packet/receipt/outcome IDs, question wording, registration timestamps and per-run verification evidence. Recompute live basis before integration/reuse; different basis cannot inherit earlier promotion counts. Keep full accumulated evidence lineage separately for all-origin access/erasure. Auto-appended experience evidence must not feed back into basis identity: derive governing roots from reviewed packet claims/conflicts, selector and source-only context evidence, or raise a narrow private manifest contract before introducing schema. Positive repeated-run coalescing after experience is offered and negative same-ID re-reviewed source/client changes are required.
- Same run, receipt or replayed verification evidence cannot add independent validation by changing outcome key/packet ID. Retain permitted unverified/failed/replay history; preserve actual existing ExperienceCompilerPolicy thresholds.
- review_experience(*, principal, brain_id, limit=100, outcome_cursor=None, procedure_cursor=None) returns outcomes and procedures plus next_outcome_cursor/next_procedure_cursor. limit is an int in1..100 and applies independently to each array. Cursors are last visible record IDs in stable (created_at,id) order, resolved under the same Brain/live all-origin rights; missing/unreadable cursor is sanitized not_found. Filter rights before page cuts; no hidden totals or silent truncation. Outcome items: id,receipt_id,summary,procedure,evidence_citation_ids,status,verification,experience_ids,integration_status,project_id (and actual reporter if exposed). Procedure items: id,project_id,status,integration_status,eligible,content,outcome_ids.
- eligible_experiences gains keyword project_id. Its private items are id,project_id,content,verification='verified_procedure',citation_ids,origins,transitions; origins/transitions are authoritative internal values, stripped into packet dependency/expiry tracking rather than emitted as client authority. Public content/citations enter actual complete budget/digest. Bound verification; incomplete traversal cannot yield actionable partial experience.
- action_outcome relation endpoints are a persisted receipt and its actual same-Brain outcome. Preserve semantic TABLES for semantic review and extend shared lookup/traversal narrowly. Unverified/failed/stale outcomes cannot become usable evidence solely by approving a relation. Actual receipt/outcome provenance must participate in source invalidation/complete erasure.
- Extend existing runtime only with an optional declared_procedure metadata path: honest 'Reported steps' / 'Procedure reported for a verified outcome' language, not 'Operator-declared' when an agent supplied the report, and no invented TOOL_CALL events or observed-tool applicability. Outcome verification does not establish observation of each step or causal benefit. Old tool-derived behavior and promotion policy remain unchanged; cover old runtime with RED/GREEN.
- In-process only register_outcome_verifier(*,verifier_id,source: VerificationSource,callback: Callable[[dict],bool]) and verify_outcome_with(*,principal,brain_id,outcome_id,verifier_id,evidence_citation_ids,note=''). Callback receives authorized persisted receipt/outcome/packet/evidence after current verify_outcome+read checks. Accept bool only; exceptions yield unverified plus verification_failed with sanitized error, no promotion. Metadata distinguishes explicit operator attestation from configured verifier. Exact immutable-attestation retry is idempotent, contradiction invalid_state; callback errors remain retryable. No callback code/URL/source trust from HTTP. Carry owner-only registered-verifier selection to Task7.
- Three new modules: experience_bridge.py orchestration, experience_records.py historical/scope/endpoint state, experience_runtime_bridge.py private integration/purge. Corresponding focused tests may be split; narrow wavemind/experience_runtime.py and its existing runtime tests are part of Task5 ownership. Additional authority schema changes still require a concrete proposal. Private cleanup failure must be pending/incomplete rather than a completed purge claim; retain opaque retry mappings after authoritative content erasure.

- Approved private basis manifest: `brain_packet_basis(brain_id,packet_id,payload_json)` with composite Brain/packet primary and foreign keys. Capture opaque governing-origin triples from the initial authorized context selection (including future-bound and budget-trimmed contributors) plus retained non-experience groups, in the same transaction as the finalized packet. Origins must be contained in complete packet provenance; this is not a public packet field or digest input and never replaces full receipt authorization. Erasure clears it with the packet. New bridge-era missing/malformed/unproven manifests fail closed. Preserve legacy pre-bridge packets with experiences=[] only from their complete proved persisted context-origin set, not displayed roots alone; if proof is unavailable require a rebuilt packet. Never apply legacy fallback to experience-bearing packets. Test actual schema migration and future-bound legacy origins, report exact schema version and carry manifest validation into Task6 backup/restore.

**Files:** Create `wavemind/brain/experience_bridge.py`, `experience_records.py`, `experience_runtime_bridge.py` and corresponding focused `tests/brain` modules; extend service, context provider hook, lifecycle cleanup, narrow BrainStore manifest migration/tests and the optional reported-procedure path in `wavemind/experience_runtime.py`/`tests/test_experience_runtime.py`.

**Interfaces:** Consume private `SQLiteExperienceStore`, `AgentExperienceRuntime`, `AgentExperienceEvent`, `OutcomeVerification`, existing compiler/promotion policy after reading their implementations. Service `record_outcome(*, principal, brain_id: str, receipt_id: str, outcome: dict) -> dict`; `verify_outcome(*, principal, brain_id: str, outcome_id: str, success: bool, evidence_citation_ids: list[str], note: str = "") -> dict`; `drain_outbox(*, limit: int = 100) -> dict`. Outcome payload only `{idempotency_key,summary,procedure:[str],evidence_citation_ids:[str]}`; no accepted `source/verifier/trust/success` privilege labels. Agent records unverified proposals. Owner manual attestation is explicitly `operator`; configured in-process verifier callbacks are separate trusted registration, never HTTP arbitrary callbacks. Output has `id,status,verification,experience_ids,integration_status`. Private provider `eligible_experiences(conn, *, principal, brain_id, question, moment, project_id) -> list[dict]` is called inside authorized context build and requires all live origins and completed integration. `BrainService.close` closes both DB connections.

- [ ] Add tests:

```python
def test_agent_success_label_cannot_become_verified(action_fixture):
    import pytest
    from wavemind.brain.models import BrainError
    s, owner, agent, brain_id, receipt_id, evidence_id = action_fixture
    with pytest.raises(BrainError):
        s.record_outcome(principal=agent, brain_id=brain_id, receipt_id=receipt_id,
            outcome={"idempotency_key": "attempt", "summary": "done", "procedure": ["check"],
                     "evidence_citation_ids": [evidence_id], "source": "test", "success": True})
    result = s.record_outcome(principal=agent, brain_id=brain_id, receipt_id=receipt_id,
        outcome={"idempotency_key": "attempt", "summary": "done", "procedure": ["check"],
                 "evidence_citation_ids": [evidence_id]})
    assert result["status"] == "unverified"
```

  Fixture creates owner/agent membership, token operations read/record_outcome, approved source claim, agent packet and receipt. Additional tests cover owner attestation, configured verifier failure, independent repeated runs under current runtime promotion policy, same receipt/evidence replay without added validation, crash after runtime commit before outbox ack, revoked dependency during pending integration, deletion purging private runtime events/trajectories/validation copies, and reopening both DBs.
- [ ] Run `python -m pytest tests/brain/test_experience_bridge.py -q`; observe RED.
- [ ] Implement private runtime integration with deterministic event/run/evidence IDs. Preserve the existing promotion threshold; one self-rated run cannot become active experience. Store pending authoritative outcome first, enqueue opaque operation ID, integrate existing runtime, then acknowledge. Idempotent runtime replay/checks must survive this fault window:

```python
with store.transaction(write=True) as conn:
    # Authorization and receipt/dependency checks precede this transaction's insert.
    conn.execute("INSERT OR IGNORE INTO outbox(id,brain_id,kind,status) VALUES (?,?,?,?)",
                 (operation_id, brain_id, "integrate_outcome", "pending"))
```

  Hold the Brain write lock across private runtime mutation/ack so live rights cannot race it, but do not claim cross-DB atomicity. Failures leave retryable pending state. Empty/no success verification cannot issue reusable procedures. Validate evidence belongs to authorized sources independent of originating procedure. On base change, eligibility closes immediately even if runtime invalidation is delayed. Delete all dependent live private copies, not just top-level records; audit/outbox retains no source text. Manual attestation is labeled as such, and reused experience remains a verified procedure, not proof of causal benefit.
- [ ] Run Brain suite plus existing `tests/test_experience_runtime.py` and `tests/test_workspace_experience.py`, Ruff; commit `feat(brain): connect reviewed outcomes to private experience runtime`.

### Task 6: Complete export, backup and safe restore

#### Controller-approved Task6 contract refinements

- Archive v1 has only manifest.json, brain.sqlite3 and optional brain-experience.sqlite3. Limits:512MiB archive,1GiB aggregate expanded,768MiB per DB,1MiB manifest,at most3 members,compression ratio<=100. Validate fixed schemas/PK/FK/integrity/counts/hashes and reject structural/path/member surprises; hashes detect corruption, not authenticity.
- BrainService(state_dir, *, bootstrap_owner: str|None=None) retains existing default behavior. Empty-target restore requires actual human principal.identity equal this trusted locally configured binding, unrestricted brain_ids, and independent manage_access+restore+read operations; missing binding is bootstrap_required. No body/archive field sets it. Preserve original Brain ID and immutable packet/receipt issuers/digests/history, replace only live owner/members with caller, import no credentials. Current-history checks independently require actual caller's owner+restore+read on that same Brain.
- Backup requires human owner+manage_access+export+read. Omit revoked/deleted source payload and dependent plaintext, retaining only opaque lifecycle/tombstone metadata. Quarantined recovery payload requires additional explicit owner restore+read authority as in its management review; normal export excludes it. Keep projection exclusions visible, not false full-active-state claims.
- Ephemeral import previews and their cached commit-retry responses are not archived/restored: uncommitted draft text has no admitted source lineage and may belong to another creator. Preserve all permitted committed source versions/chunks and ordinary digest deduplication. Always disclose import_previews_not_restored as a generic snapshot/recovery warning without leaking draft presence/counts; old preview IDs cannot resume after restore and users preview again. No opaque preview rows or new schema are needed.
- A sanitized snapshot omitting an unavailable shared private namespace may mark surviving permitted sibling outcomes integration_status=cleanup_pending and warn private_cleanup_pending, while retaining immutable history/replay, opaque mappings and actual pending source-cleanup work. This state requires a real same-scope revoked/scrubbed contributor and corresponding pending cleanup; a standalone label is insufficient. Real drain transitions to purged/retired mappings; no live source-profile mutation or completed-purge/old-credit fiction. Independently authenticated current pending=true and archived pending=true must survive restoration until ordinary owner recovery; existing needs_recheck flags are never cleared by restore.
- list_managed_sources(*,principal,brain_id,limit=100,cursor=None) returns sources:[{id,status}],next_cursor under owner manage_access. review_restored_source(*,principal,brain_id,source_id,limit=100,version_cursor=None,citation_cursor=None) requires owner restore+read and returns id,status,versions,citations,next_version_cursor,next_citation_cursor. Each list independently uses int limit1..100 and source-local stable opaque last-ID cursors; wrong-source/hidden cursor is not_found. Only quarantined content may be inspected; revoked/deleted are metadata-only with empty lists. No ordinary agent/source-read lifecycle bypass.
- Independently authenticated current history may preserve active restored authority only when relevant source/version, semantic approval/basis, packet/receipt/outcome bindings and private validation support correspond; unchanged source digest alone cannot authenticate forged labels or inflated scores. Without proof, quarantine sources/derived eligibility. Explicit admission enables sources only, invalidates old packets/private integration and marks affected semantics needs_recheck for ordinary owner recheck/review. Preserve actual historical outcomes/replay claims, not old promotion credit. A fully corresponding untouched current-history roundtrip must retain permitted active state. Specific quarantine warning is owner/manage_access-authorized and contains no source names/counts; ordinary readers get generic incomplete coverage.
- Reconstruct fresh selected-Brain/private snapshots under authority BEGIN IMMEDIATE plus private write/lock barrier. Never copy whole profile then delete unrelated rows (including free-page leakage), or call SQLite backup on source connection inside its own write transaction. Back up only completed sanitized reconstruction.
- Activate validated staged private DB only into a previously absent target while inserting authority rows transactionally. Durable crash marker binds opaque operation ID, expected Brain ID, fixed private basename/hash/size; matching opaque restore-committed audit is in the authority transaction. Startup may remove only exact matching owned orphan bytes after proving an existing valid authority DB empty/uncommitted. Missing/corrupt/unexpected authority, malformed marker or changed file yields recovery_required without destructive guesses. Committed matching audit finalizes marker only after required files/integrity checks; never delete committed data. Targets stay inside selected profile, with same-volume rollback and no user backup deletion.
- Approve portability.py public orchestration, portability_archive.py fixed-schema projection/validation, tests/test_portability and narrow service/bootstrap/startup, context-warning, access-role and legacy backup/upgrade guards. No unrelated refactor. Reader/editor may export their readable scope; separate read/all-origin checks remain, agents need explicit export+read/exact-Brain grants, and backup stays human-owner management. No other role expansion.

**Task5 integration handoff:** Include the private `brain_packet_basis` manifest and actual migrated schema version in archive validation, consistent snapshot, export policy and restore. Preserve complete governing origins separately from accumulated experience/result lineage. Never fabricate a missing bridge-era manifest or reconstruct only displayed claims: future-bound and budget-trimmed origins remain governing. Handle private cleanup retry mappings without resurrecting erased data; exact final schema/contracts come from task-5-report.md.

**Files:** Create `wavemind/brain/portability.py`, `wavemind/brain/portability_archive.py`, `tests/brain/test_portability.py`; extend service bootstrap/recovery, access export roles, context warning and narrow guards in `wavemind/product_backup.py` and `wavemind/upgrade.py`.

**Interfaces:** `export_brain(*, principal, brain_id: str) -> dict`; `backup_brain(*, principal, brain_id: str, destination: Path) -> dict`; `restore_brain(*, principal, archive: Path, current_state_dir: Path | None = None) -> dict`. Export is versioned `wavemind.brain_export.v1`, with complete visible source versions/chunks, claims, entities/relations, verified experience/provenance, minimal lifecycle metadata, counts/digests, and no tokens/passwords. Owner-only restore installs into an empty selected profile/Brain, not silently overwrite existing live data; restored sources are quarantined unless current authoritative revocation/deletion state is reconciled. Explicit `admit_restored_sources(*, principal, brain_id, source_ids: list[str]) -> dict` owner action cannot override known deletion tombstones. Backup is an owner management operation; normal exports cannot reveal revoked/deleted content. Archive format is separate from document import and cannot be supplied as an import file.

- [ ] Write tests:

```python
def test_restore_without_current_history_is_quarantined(populated_brain_fixture, tmp_path):
    from wavemind.brain.service import BrainService
    s, owner, brain_id = populated_brain_fixture
    archive = tmp_path / "brain.wmb"
    s.backup_brain(principal=owner, brain_id=brain_id, destination=archive)
    restored = BrainService(tmp_path / "restored", bootstrap_owner=owner.identity)
    result = restored.restore_brain(principal=owner, archive=archive)
    packet = restored.build_context(principal=owner, brain_id=result["brain_id"], question="Continue")
    assert packet["claims"] == []
    assert "restored_sources_quarantined" in packet["warnings"]
    restored.close()
```

  Fixture populates reviewed claims and independently verified experience using real earlier service methods. Add roundtrip complete counts beyond old exporter limits, digest corruption, zip traversal/duplicate/bomb bounds, wrong profile, stale backup after deletion, private runtime/outbox consistency at snapshot, source ACL filtered export, and old backup/upgrade refusal for a new Brain profile.
- [ ] Observe RED with `python -m pytest tests/brain/test_portability.py -q`.
- [ ] Implement brief write pause across authoritative/private stores with SQLite backup APIs and manifest hashes; include durable pending IDs, not a falsely atomic dump. Validate archive sizes, fixed allowed members, schema versions, counts/digests, foreign keys and integrity before activation. Use a staged new profile; rollback failed activation leaves existing data unchanged. Read-only current-history reconciliation never imports tokens, never reactivates tombstoned source/procedure. Without current history, quarantine sources and all derived eligibility; owner must inspect and explicitly admit them. Full export uses pagination/SQL over all authorized records rather than existing 10k/100k hard-limited exporter. Keep backup location/retention explicit; never automatically delete user backups.

```python
if (profile_dir / "brain.sqlite3").exists():
    raise ProductBackupError("Brain profiles require the Brain backup command; legacy backup is incomplete")
```

  Apply analogous specific guard in upgrade only when its chosen state profile actually contains Brain DB; do not break unrelated old profiles.
- [ ] Run Brain+legacy backup/upgrade tests and Ruff; commit `feat(brain): add complete portable snapshots and quarantine restore`.

### Task 7: Authenticated HTTP, MCP and developer launch path

**Controller transport rulings, 2026-09-10 (override provisional source_ids proposal):** `BrainAuth(state_dir)` owns a separate `brain-auth.sqlite3` with a generated immutable bootstrap owner identity. `bootstrap_owner()` returns its one-time terminal secret only at creation; repeat initialization refuses rather than resetting existing authority. The read-only `owner_identity` binds `BrainService(..., bootstrap_owner=...)`; request bodies and archives never choose it. Credentials are digest-only and excluded from Brain archives/exports.

Issued credentials have unique `agent:<uuid>` identities, exact owner-authorized Brain editor memberships and explicit operations intersected with live service rights. Activation/disclosure occurs only after the exact memberships and any explicitly requested grants commit. Pending/failed issuance cannot authenticate and must never auto-activate on restart. Revocation commits credential invalidation before best-effort removal of only its unique agent memberships; partial cleanup cannot leave a usable token. Use a consistent lock order and document/test the actual two-database failure behavior, not a fictitious atomic transaction. No owner-key reset/recovery expansion in this task.

The authenticated MCP launcher must reauthenticate on every call, keeping its originally bound identity; an optional binding on a trusted in-process adapter does not make authentication optional at the launcher. Browser sessions reference their credential and recheck credential revocation/expiry and session expiry on each request. Login secrets never appear in URLs, browser storage, diagnostics or ordinary responses.

Use immutable `Principal.source_refs: frozenset[tuple[str, str]] | None`, with exact `(brain_id, source_id)` pairs, not a global set of source IDs: the sources primary key is composite. Copy/validate mutable inputs, preserve this cap in trusted principal serialization, and intersect it before source owner exemption in both require_access and allowed_sources. `None` is no additional cap, never an ACL grant. Credential issuance accepts `source_grants: dict[str, list[str]] | None` and converts it to source_refs; its map keys must belong to the exact granted Brains, absent keys confer no sources when the map is present, and every selected source must exist and be currently owner-readable. Source-capped credentials cannot include import because new IDs are not pregranted. Same-ID sources in two Brains must have a behavioral negative test.

To connect a new unique agent to a previously owner-private source, issuance may accept an explicit `grant_selected_sources: bool = False`. True requires a nonempty source_grants selection and human-owner management of every selected Brain, and means the confirmation explicitly authorizes adding only this new agent identity to those selected existing restricted reader lists. NULL/all-members ACLs and every other reader/source remain unchanged. Membership plus these selected additive ACL grants share one authority-store transaction with ordinary revision/invalidation/audit behavior; no broad ACL replacement, no silent grant in cap-only mode. Return actual currently readable selected source references separately from requested caps so UI can distinguish a restricted/not-yet-readable connection from a tested working one. Revocation need not rewrite those inert ACL entries after membership removal, but must not claim physical erasure of historical identities.

`preview_import(..., new_source_readers: list[str] | None = None)` binds an explicit initial source audience into the creator-bound preview; commit inserts it with each newly created source in the same transaction. Restricted initial audiences require human-owner management in both preview and commit. Existing source update/dedup must preserve live ACL and reject a mismatching explicitly requested audience. Preview and commit disclose actual/default all_live_members semantics without changing legacy content results; an already-connected agent must never observe an intermediate unrestricted private import. An unchanged omitted/default audience must not accidentally reset an existing restricted source. Narrow changes to models.py, access.py, service.py, sources.py, principal_data in experience_bridge.py and focused tests are authorized for these boundaries.

Dedicated `create_app(..., brain_service=None, brain_auth=None, brain_only=False)` validates both dependencies and takes an early Brain-only branch before legacy environment-driven stores, observability, cache, rate or auth setup. It may use an explicitly in-memory SQLite WaveMind and HashingTextEncoder where required, mounts no generic legacy routes, and closes owned resources on shutdown. Default False legacy/coexistence behavior remains compatible; half configuration fails clearly. No remote model/store/download side effects in dedicated D1 startup. Developer startup remains loopback-only and is not the D2 mass installer.

**Session reload refinement:** Add authenticated `GET /brain/api/session` returning only `{csrf_token, expires_in, identity, kind}` from the live cookie session and its currently valid parent credential. This is UI session bootstrap, not a new credential or membership operation. Reject query fields; preserve exact Host/Origin rules and no CORS/no-store/referrer protections. An absent Origin is necessary for ordinary same-origin browser GET; when Sec-Fetch-Site is present require same-origin, rejecting same-site/cross-site/navigation-none. Non-browser requests without that browser header still require the actual session cookie. Derive a stable CSRF value as SHA256 of UTF-8 `wavemind.brain.csrf.v1:` plus the random raw session-cookie value; store only its digest, never the raw session cookie or owner key. Login and session bootstrap produce the same CSRF for a valid session. Legacy provisional random-CSRF sessions may replace their CSRF digest once under the same live-auth transaction; this can require a previously open old tab to refresh, never extends expiry or revives revoked credentials. Return actual remaining session lifetime, not a renewed fixed lease. Test page-state loss/reload, two tabs, service restart, forged/expired/revoked cookie/parent, and browser metadata/origin negatives. The UI keeps CSRF in memory only and obtains it again through this endpoint after reload.

**Task5 integration handoff:** Expose authorized `review_experience` with independent outcome/procedure visible-ID cursors and limit1..100. Preserve failed/unverified/pending history and explicit operator versus configured-verifier labels. Only an owner may select an already registered in-process verifier through `verify_outcome_with`; no callback code, URL, arbitrary trust/source label or verifier registration through HTTP/MCP. Read exact reviewed response/error contracts from task-5-report.md before wiring. Actual reporter identity is distinct from receipt issuer.

Consume Task3's owner-only `review_records` and `recheck_dependencies` contracts. Add strict authenticated `POST /brain/api/{brain_id}/memory/review` (`record_type,record_ids,action`) and `POST /brain/api/{brain_id}/dependencies/recheck` (empty body) routes plus facade/MCP adapter delegation under the same authority rules. Agent tokens cannot approve entities/relations or clear the dependency gate. These owner operations must be included in transport tests and available to the actual UI, not only Python calls.

**Files:** Create `wavemind/brain/auth.py`, `http.py`, `mcp.py`, `cli.py`, `tests/brain/test_http.py`, `test_mcp_cli.py`; narrow integration changes to `wavemind/api.py`, `wavemind/cli.py`, `pyproject.toml`. Add `wavemind/integrations/mcp_compat.py` shared MCP initialization helper and use it from the existing `wavemind/mcp_server.py` and `wavemind/integrations/mcp_experience.py` builders; extend `tests/test_official_provider_contracts.py` for cold-process compatibility.

**Interfaces:** `BrainAuth(state_dir: Path)`, `bootstrap_owner() -> str` (one-time local terminal secret, never URL/log), `issue_agent(*, principal, brain_ids, operations, label) -> dict`, `authenticate(token: str) -> Principal`, `revoke_token(*, principal, token_id: str) -> None`. Store only token digests, owner-scoped grants and revocation metadata, never echo token beyond creation. `mount_brain(app: FastAPI, service: BrainService, auth: BrainAuth) -> None`; extend existing `create_app` with optional keyword `brain_service=None, brain_auth=None` default disabled. `BrainMCPAdapter(service, principal)` exposes explicit typed operations and refuses requests containing principal/role/verifier; MCP stdio launcher authenticates a local configured credential before binding. CLI delegates via `wavemind brain init|serve|mcp|backup|restore|export|doctor`, separate parser in new module; the `brain serve` command launches existing FastAPI with optional Brain only, not a new independent service.

- [ ] Write tests:

```python
def test_http_does_not_trust_body_principal(brain_http_fixture):
    client, reader_token, brain_id = brain_http_fixture
    response = client.post(f"/brain/api/{brain_id}/claims/review",
        headers={"Authorization": f"Bearer {reader_token}"},
        json={"principal": {"identity": "owner"}, "claim_ids": [], "action": "approve"})
    assert response.status_code in (403, 404, 422)
    assert client.get(f"/brain/api/{brain_id}/memory").status_code == 401
```

  Fixture mounts real service/auth on FastAPI TestClient with a temporary profile and two memberships. Add two distinct MCP connections, token scope restriction/revoke, strict JSON fields, source ID ACLs, HTTP body-size rejection before parse, blocked nonlocal Host and cross-site Origin, expired/absent UI CSRF, path field refusal and old generic `/query` isolation. CLI tests exercise actual subprocess/restart/JSON outputs and local file symlink/reparse checks, with tokens not in command output except deliberate one-time init/issue.
- [ ] Run transport tests to observe RED.
- [ ] Implement narrow explicit routes: `/brain/api/brains` create/list, `/{brain_id}/sources/preview|commit`, `sources`, `sources/{source_id}/{action}`, `claims/propose|review`, `entities`, `relations`, `memory`, `context`, `citations/{citation_id}`, `actions`, `outcomes`, `outcomes/{id}/verify`, `export`, `access/members`, `access/sources`; agent credentials endpoints separate owner-only. Route functions call the facade and never reconstruct authority from body. JSON upload uses bounded base64 bytes with validated decoded limits. Browser owner signs in via secret pasted into POST login, then HttpOnly SameSite=Strict cookie plus session-bound CSRF on mutations; all routes validate configured Host, and browser Origin must match. Bearer API access without Origin is allowed after exact auth; CORS stays off. Reject nonloopback `brain serve` in D1 with a clear D3/TLS deployment gate. No token in query string/localStorage/sessionStorage or logs.

```python
principal = auth.authenticate(bearer_token)
return service.build_context(principal=principal, brain_id=brain_id,
                             question=request.question, max_bytes=request.max_bytes)
```

  Fail closed when Brain auth is not explicitly configured, even though old API local mode permits unauthenticated operations. Add shutdown cleanup without breaking existing app shutdown. MCP methods are shared service invocations with bound principal, not an arbitrary SQL/command adapter. Developer startup explicitly says it requires Python and is not D2 consumer installation; core workflows do not call models or download embeddings.

  Baseline diagnostic found mcp 1.29.0 + pydantic 2.13.4 + pydantic-settings 2.15.0 warns on first FastMCP construction because its Settings.lifespan forward reference is incomplete. A fresh-process check confirmed rebuilding Settings before constructing FastMCP resolves the cause. Add `require_fastmcp() -> tuple[type, type]` returning `(FastMCP, Context)` from the shared helper; preserve optional-dependency ImportError behavior in each caller. Do not mutate installed dependency files or suppress warnings. The helper's initialization is:

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.server import Settings
Settings.model_rebuild()
return FastMCP, Context
```

  Put these imports inside the helper so the core package still imports without the MCP extra. Before the helper change, add a fresh subprocess test for each existing builder with `warnings.simplefilter("error", IncompleteFieldDefinitionWarning)` and real `list_tools()` output validation; observe the first-construction failure. After the helper, require both cold-start tool contracts and Brain MCP initialization to pass without warning. A warm second construction is insufficient evidence.
- [ ] Run Brain+existing API/CLI/MCP tests and Ruff, build wheel and inspect modules; commit `feat(brain): expose authenticated shared HTTP MCP and CLI workflows`.

### Controller refinement: bounded citation discovery for Task8

First-use and restart citation selection must not depend on downloading a full Brain export. `list_sources` returns source metadata, while recovery review intentionally rejects active/paused sources, so an ordinary source needs a bounded read-only listing. This refines the existing visible-source/citation-picker requirement, not source access or recovery authority.

Extend `sources.py`, `service.py`, `http.py`, and the two source-ID routing lists in `mcp.py`, with behavioral tests in `tests/brain/test_ui_scenarios.py` (or a focused `tests/brain/test_source_citations.py` if clearer). No schema/index or role/capability changes.

`list_source_citations(*, principal, brain_id, source_id, limit=50, cursor=None, versions="current") -> {source_id, citations, next_cursor}`. `versions` is exactly `current|all`, current by default; strict integer limit1..100. Current means the latest source-version number; all is an explicitly selected historical view. Each citation is the existing public `resolve_citation` dictionary, not a private SQL row. Order by source version, chunk ordinal, chunk ID.

Use a read transaction with existing exact Brain/read/source authorization, including immutable credential caps. Active and paused remain readable under `_readable`; revoked/deleted/quarantined/missing/unauthorized sources fail `not_found`. A non-null cursor must resolve within this exact authorized source and selected version set; foreign, stale-current, or missing cursor fails the same generic error. Query at most limit+1 matching rows with deterministic keyset filtering; do not load all source history then slice. A current-source update between pages makes an older cursor invalid instead of silently mixing versions. Every later page rechecks live rights.

HTTP route: `GET /brain/api/{brain_id}/sources/{source_id}/citations` with only `limit`, `cursor`, and `versions`. Use the existing shared strict operation/query boundary and expose the same read-only MCP operation with required source_id, not a second validation implementation. Reject duplicate/unknown fields and injected authority. Preserve privacy headers. UI defaults to current, offers explicit historical view and Load more, clears cursor/selection on source/mode change and asks for refresh on invalidated cursor. It does not represent a fetched page as all citations or retain source content in browser storage.

Before implementation observe failing behavioral domain/HTTP/MCP tests for bounded multi-page traversal, current/all versions, restart, current-version update/stale cursor, exact-source/Brain cap denial, live revocation, paused readability, and malformed/duplicate query. These and the UI restart picker become Task8 review inputs; full export remains an explicit portability action, not normal page bootstrap.

### Task 8: Usable RU/EN owner workflow and real browser scenarios

**Task5 integration handoff:** Experience UI must use paginated `review_experience`, including permitted failed/unverified/replay/integration-pending history after restart, and distinguish current procedure eligibility from historical outcome verification. Show explicit manual operator attestation versus configured verifier, report-only procedure steps rather than observed execution/causality, and actual reporter separately from receipt issuer when displayed. Owner verification selects only server-registered verifiers; no arbitrary code/URL configuration in UI. Exact finalized contracts come from task-5-report.md.

Include explicit entity/relation proposal review via Task3/7 `review_records`, and owner dependency-recheck recovery for persisted pending state. Show pending/rejected/approved status plainly; neither creating a named entity nor receiving a model relation counts as approval. Recovery reports whether the graph is still pending and does not silently activate individual records requiring recheck. Exercise owner approval and denied agent approval in the real workflow.

**Files:** Create `wavemind/brain/ui/index.html`, `app.js`, `style.css`, `tests/brain/test_ui_scenarios.py`, `scripts/verify_brain_ui.mjs`; extend `http.py` static mounting, `pyproject.toml` package data and optional test dependencies only if needed.

**Interfaces:** UI uses only authenticated `/brain/api` routes from Task 7; scripts read origin and ephemeral test credentials from environment, never committed screenshots/logs. Serve under `/brain`; default language Russian with explicit EN switch persisted only for language. Package data contains `brain/ui/*.html`, `*.js`, `*.css`. UI does not require build tool or network assets.

- [ ] Write a failing browser journey before the UI code. Use actual selectors/labels, not HTML source grep:

```javascript
await page.goto(`${origin}/brain`);
await page.getByLabel('Ключ владельца').fill(ownerKey);
await page.getByRole('button', {name: 'Войти', exact: true}).click();
await page.getByRole('button', {name: 'Личный проект', exact: true}).click();
await page.getByLabel('Название проекта').fill('Переезд');
await page.getByRole('button', {name: 'Создать память', exact: true}).click();
await page.getByLabel('Текст источника').fill('Бюджет переезда 60000 рублей.');
await page.getByRole('button', {name: 'Предпросмотр', exact: true}).click();
await page.getByText('Данные не отправляются внешней модели', {exact: true}).waitFor();
await page.getByRole('button', {name: 'Сохранить источник', exact: true}).click();
```

  Python acceptance tests launch actual service, call the browser script and inspect persistent service state afterward; optional browser tooling missing locally is an explicit unexecuted gate, not a fake pass. Test EN and narrow viewport, cancellation/error, keyboard labels/focus, no console errors; screenshots are actual nonsecret generated fixtures with demo labels.
- [ ] Run the browser journey to observe missing UI RED.
- [ ] Implement first-use steps: mode/project, local privacy warning, file/pasted text preview including per-file failures, reviewed typed facts with citation picker, first context with visible source references, agent credential creation/downloadable setup plus actual second-connection citation read check (not just config generated). Five daily sections: projects, known/current, changes, experience, sources/access. Include explicit correction/conflict resolution, relation rationale, owner outcome verification with evidence, source pause/revoke/delete confirmation, export/backup guidance and stale/quarantine warnings. Display unconnected model state and no simulated answer. Inputs and source content render via `textContent`, never untrusted `innerHTML`; no CDN/fonts/tracking.

```javascript
function showText(node, value) {
  node.textContent = String(value ?? '');
}
```

  Use light background, dark readable typography, restrained orange accent, responsive two-column layout collapsing on mobile, clear empty states and pending/error messages. Provide cancellable import requests using AbortController; discard abandoned previews safely. Expose source coverage and exact packet bytes, estimate tokens explicitly. Connect-agent panel explains data already forwarded cannot be retracted from the agent's own history. Never automatically select all sources or grant broad rights by default.
- [ ] Run complete P1 and B1 through real UI + two distinct bound agent connections, restart midway, correct constraints/policy, verify outcome and later eligibility, revoke/delete source, test cross-client negative control with renamed data/reversed import order. Save actual screenshots and scenario report under temporary evidence workspace. Run full Brain suite and wheel asset verification; commit `feat(brain): add bilingual owner workflow and cross-agent scenario checks`.

### Task 9: Truthful public explanation and complete D1 verification

**Files:** Create `docs/brain/personal.md`, `teams.md`, `agent-contract.md`, `limitations.md`, `scripts/verify_brain_d1.py`, `tests/brain/test_acceptance.py`; update `README.md`, `CHANGELOG.md`, appropriate existing roadmap/product-status sources through their generator, and add actual UI screenshots to `docs/assets/brain/`.

**Interfaces:** Acceptance runner calls existing service and real transport methods, emits `wavemind.brain_d1_evidence.v1` JSON with exact source commit, executed tests/scenarios, per-gate pass/fail/unexecuted, versions and no private tokens/source material. It cannot convert D2/D3/D4 into pass. Read existing product-status generator before changing its input; do not overwrite historical evidence hashes or mark research admitted.

- [ ] Write test for failed gate preservation:

```python
def test_acceptance_report_does_not_admit_unexecuted_user_pilots():
    from scripts.verify_brain_d1 import summarize_gates
    report = summarize_gates({"F01": "pass", "F12": "fail"})
    assert report["d1_status"] == "incomplete"
    assert report["mass_release"] == "not_evaluated"
    assert report["scientific_breakthrough"] == "not_established"
```

- [ ] Observe RED with `python -m pytest tests/brain/test_acceptance.py -q`. Add all fourteen F gates represented, absent evidence never pass, and same-SHA source binding tests. Actual P1/B1 results remain engineering examples, not invented external users.
- [ ] Implement evidence summary without optimistic defaults:

```python
required = {f"F{n:02d}" for n in range(1, 15)}
status = "pass" if all(gates.get(key) == "pass" for key in required) else "incomplete"
```

  Rewrite the first README screen around owned project/company memory and actual available D1 workflow, with two concrete continuation examples, real screenshots, current install distinction and source-controlled privacy. Keep README below existing 700-line gate and preserve required navigation/research links; move old quantum-first cover to historical research section without deleting assets/evidence. Plain language RU/EN personal/team instructions: why useful, what stored/sent, how correct/delete/export, what verification proves, exact current launch commands and troubleshooting. State engineering preview, plaintext nonsecret data, unmeasured user benefit and no causal/scientific breakthrough. No generated charts are required for D1; if quantitative charts are added, load requested diagram-design and use actual evidence only.
- [ ] Run full pytest from clean test temp, Ruff, packaging build/twine/wheel asset smoke, docs local links/product-status sync, P1+B1 actual UI/HTTP/MCP twice with variations. Refresh relevant source-bound admissions via existing official scripts rather than rewriting claims. Record optional-dependency skips, failures and external gates separately; do not call the overall user mission 100% complete.
- [ ] Commit `docs(brain): explain owned digital memory with verified preview evidence`. Obtain whole-branch spec/security/code review, fix load-bearing findings via a bounded fix wave, and reverify affected tests plus release gates. Publish the reviewed branch/PR through the existing authorized GitHub workflow, verify exact remote SHA and required checks, and integrate only after checks pass. Do not create a stable package tag or claim signed installation until those release gates exist.

## Coverage and remaining stages

| Spec criterion | Tasks / evidence |
|---|---|
| F01 persistence | 1,2,3,5,6,8 restart tests |
| F02 idempotency/crash | 2,4,5 outbox fault window |
| F03 event order | 3,8 reordered correction |
| F04 conflicts | 3,4,8 explicit owner resolution |
| F05 true citations | 2,4,7 exact version and live ACL |
| F06 access/no leaks | 1–8 all-origins controls incl derived/export/cache |
| F07 dependency invalidation | 2–5 pending and changed policy |
| F08 genuine evidence | 4,5 receipt binding, verifier boundary and replay |
| F09 live deletion | 2,3,5,6 source/derived/private audit inspection |
| F10 portability | 6 complete export, quarantine and stale backup |
| F11 input/transport safety | 2,7 bounds, reparse, Host/Origin/CSRF |
| F12 real P1/B1 UI+clients | 8,9 browser plus two clients, variations |
| F13 compatibility | 6,7,9 complete old suite, no silent migrations |
| F14 explicit network/actions | 2,7,8,9 no model by default, owner review |

D1's completion report must name D2 (bundled signed Windows install/update/uninstall), D3 (team TLS/auth/backup deployment), and D4 (10 novice users, 14-day retention, 3 team pilots and frozen scientific comparison) as remaining work, with actual blockers rather than simulated participants. Continue safe local next-stage design after D1; contacting people, acquiring signing certificates, paying providers or ingesting private data requires their relevant authority. No 100% usefulness or scientific claim follows from 100% executed engineering tests.
