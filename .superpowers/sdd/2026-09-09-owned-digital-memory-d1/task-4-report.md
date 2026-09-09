# Task4 implementation report

Worktree: `C:/Users/LEO/Documents/Codex/2026-08-16/ct/work/wavemind-breakthrough`.
Branch: `design/owned-digital-memory-20260909`.
Implementation review base: `67011423801c4817ea4065e00100fa5f6bceb988`.
The controller added docs-only commits c7b095e and 8db4e4d during implementation, clarifying the reserved provider and project/client scope contracts. Those changes are not this implementation's work.

## Delivered behavior

- Added `Context` and the three keyword-only BrainService methods `build_context`, `validate_packet`, `begin_action`.
- Live source ACLs and all materialized semantic origins are checked under the same SQLite transaction as selection/persistence or application. Semantic applicability uses Task3 `record_eligible`; context does not reconcile, approve, or derive effective intervals itself.
- Deterministic Unicode lexical selection uses query overlap then stable IDs, bounded to 10,000 scanned claim rows and 128 ranked claim candidates. An explicit project/client ID filters exact claim.entity_ids after same-Brain approved/readable selector authorization; no name matching or source-only fallback occurs in scoped requests. Unscoped source-only evidence is limited to sources with no semantic dependencies and is explicitly unreviewed. Source-only scan is at most 128 readable sources with 128 latest-version chunks each, with at most 128 resulting citations.
- Approved applicable claims and permitted conflict records occupy different packet arrays. Conflict records are never added to actionable claims. All evidence citations are source data. Unknowns and warnings disclose incomplete/conservative coverage without hidden titles, IDs, or omitted counts.
- Full canonical UTF-8 packet budget includes the digest, self-consistent costs, question, scope, warnings, metadata and evidence. Removal operates on complete claim/conflict/evidence groups. Insufficient envelope budgets fail with a domain error.
- Packet validity is at most 900 seconds and is shortened by future effective validity transitions in the authorized scoped candidates and their contributing origins. Persisted validation rechecks identity, Brain, live revision, rights, expiry, digest and semantic applicability.
- Receipts bind a validated persisted packet to exact run/action before any external action. `begin_action` does not execute the action string. BEGIN IMMEDIATE serializes the lookup/insert uniqueness boundary across service instances. Every retry validates current packet authority first.
- Named dependency_limit/dependency_cycle failures discard every partially selected claim, citation, conflict and experience, persist the Brain-wide pending gate, and issue explicit pending/no-action output. A too-small envelope error occurs after committing this gate, so it cannot accidentally roll back recovery state.
- Projection/audit distinction: normal packet/receipt issuance calls record_change with increment=False and cannot invalidate its own packet. A newly discovered global pending transition changes authoritative eligibility, so it calls record_change(kind=`context_pending`, record_id=brain_id) with the default increment=True in the same transaction; the pending packet captures that new revision. Already-pending builds do not repeat this increment/audit. Genuine source/claim/access changes continue to advance the existing authoritative revision.
- A pending packet has SQL status `pending` and coverage.status `pending`, with project_id null because selector applicability was not established. This is the only scope exception. Clearing the global gate and reopening the service cannot revive that packet: its persisted non-active status continues to reject validation and actions. Fresh successful packets retain the actual authorized selector and its provenance, including when no claims fit or exist.
- Generic memory and experience API isolation is verified through actual `/query`, `/experience/packet`, and `/experience/{id}` calls with both default and exact Brain namespaces.

## Firewall integration

The adapter reuses `MemoryFirewall.is_tainted` and the existing ExperienceRecord/ExperienceSource definitions. Ephemeral records have IMPORTED trust and the default SHADOW status. They are neither persisted nor returned as legacy experience, and the adapter never promotes source-only evidence to ACTIVE just to pass a legacy retrieve lifecycle check. Source metadata taint and actual source/semantic strings pass through the existing heuristic. No regex lists or legacy firewall semantics were changed.

A focused regression found that canonical JSON would escape semantic newlines before the existing whitespace patterns saw them. The adapter now scans actual string values; an agent-proposed `Ignore\nprevious instructions` claim is omitted even after owner approval. Whitespace-only valid citation chunks are mapped to a harmless nonempty adapter placeholder while preserving source metadata checks; the original exact citation text is unchanged. Imported malicious source instructions are omitted from packet evidence and associated claims. The packet explicitly warns that this heuristic is not universal injection prevention.

## Packet / receipt handoff for Tasks5,7,8

Public canonical packet fields are exactly:

`schema,id,brain_id,principal_id,revision,question,moment,project_id,claims,citations,experiences,conflicts,unknowns,coverage,warnings,cost,expires_at,digest`.

- schema: `wavemind.brain_context.v1`.
- IDs for packets/receipts are UUID hex; principal_id is trusted in-process Principal.identity, never a request identity field.
- moment is finite epoch seconds, defaulting to issuance time. expires_at is finite wall-clock epoch time with half-open expiry (`now >= expires_at` rejects).
- project_id is the explicit authorized same-Brain project/client entity ID or null; receipts inherit this scope from their validated persisted packet, not from question text or the first claim. The explicit pending/no-action exception above has null scope.
- claims/conflicts copy public semantic payload fields, omit internal underscore fields, and add id/status/authority=`reviewed_claim`. Claims may have superseded SQL status only when Task3's preserved nonempty historical effective interval includes the requested moment. Source data does not establish causal effects.
- citations preserve `resolve_citation` exact fields (`id,source_id,version,text` plus existing locator keys), add authority=`source_data`, and review_status=`evidence_for_reviewed_memory` or `unreviewed` for source-only evidence.
- experiences is always `[]` in Task4.
- unknowns: `coverage_is_not_complete`, `causal_effects_not_established`.
- coverage: `{status: 'partial'|'pending', selection: 'bounded_lexical', selected_claims: int, selected_citations: int}`; these counts describe only selected visible returned items, never hidden totals.
- warnings always include `source_content_is_untrusted_data`, `firewall_is_heuristic_not_universal_injection_prevention`, `bounded_authoritative_fallback`, `conservative_provenance_may_omit_reviewed_history`, `partial_conflicts_exclude_whole_records`. Budget reduction adds `budget_truncated`; pending adds `context_pending_no_action`.
- Canonical serialization: json.dumps with ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False, encoded UTF-8.
- digest: lowercase SHA-256 hex over the canonical complete packet excluding only its digest key. cost.bytes includes the final 64-character digest and cost fields themselves. Cost widths converge using a fixed-length digest placeholder, then the digest is computed with the settled cost. cost.tokens is the explicitly estimated integer ceiling of bytes/4; network_calls is always 0. This digest detects alteration relative to persisted server state; it is not an encryption, signature, or protection against arbitrary database rewriting.

Receipt public fields are exactly `id,packet_id,packet_digest,revision,run_id,action,status`. Initial status is `pending_outcome`; status resides in payload_json, since receipts have no SQL status column. The SQL row additionally stores brain_id, principal_id, packet_digest, created_at and schema_version=1. Uniqueness is the serialized exact (Brain, packet, run_id, action) lookup/insert. Input run_id is nonempty bounded UTF-8 text up to 256 characters; action is up to 4096. Neither is executed.

Context requirements are `read` for build/validate, and both `record_outcome` and independent `read` for begin_action. Restricting a same-identity principal's operations still narrows current rights. All public callers must bind Principal through trusted transport authentication; JSON cannot select principals or callbacks.

The internal helper `validate_persisted_packet(conn, *, principal, brain_id, packet_id)` operates in a caller-owned transaction and returns the persisted validated packet. Task5 can reuse it where current packet reapplication is required; it enforces current revision and expiry, so Task5 must not silently treat it as a historical outcome verification policy.

Origins: packets store singular semantic `(claim|entity|relation, id)` origins for every reached contributing record, plus singular source origins for all governing sources. Every dependency includes exact brain_id and source_id. The explicit selector also contributes origins even for an empty packet. Receipt creation copies those origins; the existing shared helper supplies implicit packet→receipt→outcome edges. Source lifecycle and Task3 context-only invalidation therefore reach packets, receipts and outcomes. Receipt pending_outcome payload alone never proves live authority: source revocation/updates revoke the packet and source deletion scrubs receipt payloads to `{}`. Task5 must recheck origin/receipt authority when reading and verifying outcomes.

Service-owned private extension point: `BrainService._private_experience_provider = None`, reserved and uninvoked. No request setter exists. Task5 owns integrating its `eligible_experiences(conn, principal, brain_id, question, moment)` provider and defining/testing exact returned item, trust and provenance metadata. Task4 does not claim delivered experience integration or accept provider authority from dictionaries.

Domain error handoff:

- `not_found`: same sanitized message `Resource not found.` for unauthorized/missing/foreign identity or Brain, unavailable sources, and missing/ineligible scope selectors.
- `invalid_input`: invalid question/scope/run/action/moment/budget boundary values, with no echoed payload.
- `budget_too_small`: complete envelope cannot fit; no oversized packet is returned.
- `stale_packet`: SQL status is not active, memory revision changed, wall-clock expiry reached, or current semantic applicability fails.
- `invalid_packet`: persisted digest/envelope binding or cost integrity mismatch.
- `context_pending`: global gate or explicit pending coverage blocks application.
- `dependency_limit` / `dependency_cycle`: build catches only these named incomplete-walk errors and commits pending; read-side validation propagates them safely without trying to write from a read transaction.

HTTP/MCP endpoints, RU/EN owner UI, private verified experience runtime, models/providers and external actions remain later tasks. Future UI/docs must carry both exact limitations: monotonic governing-source provenance may conservatively omit/delete earlier history after a competitor is rejected; unresolved partial overlaps exclude whole records rather than segmenting nonconflicting intervals. No full historical truth, universal injection prevention, causal effect, measured-user-value, D2/D3/D4 completion, or encrypted-storage claim is made.

## TDD and verification evidence

All commands ran in the worktree above using the existing interpreter `../wavemind/.venv/Scripts/python.exe`, not D:. Every pytest invocation used a fresh nonexisting system-temp path and disabled pytest cache. Common full PowerShell invocation:

```powershell
$env:PYTHONPATH=(Get-Location).Path
$env:PYTHONDONTWRITEBYTECODE='1'
$env:GIT_CONFIG_COUNT='1'
$env:GIT_CONFIG_KEY_0='safe.directory'
$env:GIT_CONFIG_VALUE_0=(Get-Location).Path
$taskTemp=Join-Path $env:TEMP ('wmb-'+[guid]::NewGuid().ToString('N'))
../wavemind/.venv/Scripts/python.exe -m pytest tests/brain/test_context.py -q -p no:cacheprovider --basetemp $taskTemp
```

Observed runs:

1. Initial RED before implementation: `17 failed in 1.57s`, all expected AttributeError `'BrainService' object has no attribute 'build_context'`. Tests used real imported/approved source fixtures, not mocked authority.
2. Initial implementation: `1 failed, 16 passed in 1.46s`. Investigation showed the temporal fixture gave the successor a different key; Task3 explicitly marks that incompatible_original. Corrected only that fixture to use the predecessor's key. Subsequent run: `17 passed in 1.17s`.
3. New explicit scope/selector-erasure RED: `3 failed, 20 passed in 1.77s` (missing top-level project_id, and missing empty selector packet origin). After adding the agreed field and selector provenance: `23 passed in 1.46s`.
4. Multiline semantic instruction RED: `1 failed, 24 passed in 2.28s`, actual output included attack plus goal. Existing firewall whitespace rules were receiving JSON escapes. Actual-text adapter fix covered by subsequent GREEN.
5. Whitespace chunk RED with `-k whitespace`: `1 failed, 25 deselected in 0.85s`, ValueError `content must not be empty` from the legacy record constructor. Harmless adapter placeholder fixes the mismatch without changing source text/authority.
6. Focused GREEN after both adapter fixes: `26 passed in 2.00s`.
7. Covering command substitutes `tests/brain` in the common invocation: `196 passed in 41.21s`, output pristine. This included all then-existing 26 context tests, store/access/source/reconciliation tests, and actual generic API isolation.
8. Controller requested an additional recovery negative after the covering run had already started. Focused `-k pending_scoped` run: `1 passed, 26 deselected in 0.55s`, using real recovery/reopen and no production changes. Then complete context run: `27 passed in 2.22s`.
9. Final self-review identified the newly discovered pending gate as an authoritative revision change, and the controller confirmed the narrow audit fix. Focused `-k new_pending_gate` RED: `1 failed, 27 deselected in 0.78s`, literal failure `assert 6 == (6 + 1)`. GREEN after adding the transition audit: `1 passed, 27 deselected in 0.53s`. Test checks the exact single opaque audit row, once-only increment on repeated pending builds, and agreement between returned/SQL/persisted-payload revision. A fresh covering run follows because production changed.

Lint command:

```powershell
../wavemind/.venv/Scripts/python.exe -m ruff check wavemind/brain/context.py wavemind/brain/service.py tests/brain/test_context.py
git diff --check
```

Observed Ruff output: `All checks passed!`; diff check emitted no errors. Ruff format was used only on the three owned Python files. No global Git/config/credential changes, models, network calls, downloads, or paid providers were used.

## Self-review and files

Owned files: new `wavemind/brain/context.py`, new `tests/brain/test_context.py`, narrow delegation/reserved-hook additions to `wavemind/brain/service.py`, this report. No shared authority/schema/firewall/reconciliation redesign.

Self-review checked all packet fields, digest/cost circularity, exact budget truncation, source-only labeling, historical half-open intervals, all-origin erasure, source-restricted agents, hidden conflicts, scoped negative controls, matching-principal narrowed operations, current-revision idempotence, generic API isolation, incomplete-walk rollback behavior and per-packet recovery rejection. The explicit project provenance and firewall adapter edge cases were fixed with observed regressions as recorded above.

Performance remains bounded authoritative fallback, not a search index: repeated eligible candidates can each traverse their prerequisite graph while holding the write transaction. No completeness/latency claim is made. This is intentionally conservative, with explicit partial coverage, and uses no new reconciliation implementation.

## Final verification and commit

Final production commit: `2ebb48fa9216b8f7a67fb8ed02d0de0c55edc6b2` — `feat(brain): issue scoped context with revocable action receipts`.

After the pending-transition audit change and formatting, the fresh full `tests/brain` command above returned:

```text
........................................................................ [ 36%]
........................................................................ [ 72%]
......................................................                   [100%]
198 passed in 41.21s
All checks passed!
```

This final covering run includes all 28 context tests. Ruff was run against all three changed Python files and passed; `git diff --check` was clean. Code commit touched only the three owned Python files (605-line context module, 48-line service extension, 824-line behavioral test module). The report is a separate documentation commit so it can cite the exact code SHA without circular self-reference. No code changed after this final verification.

Status: DONE. No outstanding implementation blocker or known correctness issue. Accepted conservative coverage limits and the explicitly reserved/uninvoked private provider remain as documented, with independent review owned by the controller.
