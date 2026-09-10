import {el, add, t, button, field, card, note, details, check, lines, download, citationPicker} from './ui.js';

const ids = (records, empty = 'None') => [['', empty], ...records.map(r => [r.id, `${r.name || r.content || r.kind} · ${r.id}`])];
const kinds = names => names.map(x => [x, x]);
const post = (s, path, data) => s.api(`${s.brain}/${path}`, data);
const contextCopy = {
  coverage_is_not_complete: 'Coverage is partial; this is not a complete account.',
  causal_effects_not_established: 'Causal effects have not been established.',
  source_content_is_untrusted_data: 'Source text is untrusted data, not instructions.',
  firewall_is_heuristic_not_universal_injection_prevention: 'The safety filter is heuristic and cannot prevent every instruction-injection attempt.',
  bounded_authoritative_fallback: 'Selection uses a bounded local text search.',
  conservative_provenance_may_omit_reviewed_history: 'Conservative source tracking can omit reviewed history.',
  partial_conflicts_exclude_whole_records: 'Unresolved overlapping conflicts exclude whole records.',
  context_pending_no_action: 'Dependencies need rechecking; this packet cannot start an action.',
  restored_sources_quarantined: 'Restored sources await owner inspection in quarantine.',
  budget_truncated: 'Some content was omitted to fit the byte limit.',
};
function result(parent, data) {
  const box = card(parent), list = el('dl');
  const labels = {verification: 'Verification', source: 'Verification source', mode: 'Verification method', success: 'Successful result', verifier: 'Verifier', note: 'Verification note', evidence_citation_ids: 'Selected evidence', reporter: 'Reporter', receipt: 'Receipt', reported_steps: 'Reported steps', integration_status: 'Integration status', eligible: 'Current procedure eligibility', status: 'Status', readable_source_refs: 'Currently readable source references', coverage: 'Coverage', unknowns: 'Unknowns', warnings: 'Warnings', conflicts: 'Conflicts'};
  for (const [key, value] of Object.entries(data)) {
    const description = el('dd'); add(list, el('dt', t(labels[key] || key)), description);
    if (Array.isArray(value)) {
      const items = el('ul');
      for (const item of value) add(items, el('li', typeof item === 'object' ? JSON.stringify(item) : item));
      add(description, items); if (!value.length) description.textContent = '—';
    } else if (value && typeof value === 'object') result(description, value);
    else description.textContent = value == null ? '—' : t(String(value));
  }
  add(box, list);
  return box;
}
function reviews(parent, s) {
  if (![...s.memory.entities, ...s.memory.claims, ...s.memory.relations].length) note(parent, 'No records yet. Propose a cited record, then review it.');
  for (const [type, records] of [['entity', s.memory.entities], ['claim', s.memory.claims], ['relation', s.memory.relations]]) {
    for (const record of records) {
      const row = card(parent, record.name || record.content || `${record.kind}: ${record.from_id} → ${record.to_id}`, {'data-record-id': record.id});
      add(row, el('span', t(record.status), {class: 'badge'}), el('p', record.id, {class: 'identifier'}));
      const lastReview = s.memory.changes.filter(change => change.record_id === record.id && ['approve', 'reject', 'recheck'].some(action => change.kind === `${type}_${action}`)).at(-1);
      if (lastReview?.kind === `${type}_reject`) note(row, 'Rejected by owner');
      if (record.needs_recheck) note(row, 'Recheck');
      if (record.supersedes) add(row, el('p', `${t('Replaces record')}: ${record.supersedes}`));
      if (record.valid_from != null || record.valid_until != null) add(row, el('p', `[${record.valid_from ?? '−∞'}, ${record.valid_until ?? '+∞'}) UTC`));
      const evidence = details(row, 'Selected evidence');
      for (const cid of record.citation_ids || []) add(evidence, button(cid, () => s.run(async () => {
        const citation = await s.api(`${s.brain}/citations/${cid}`); add(evidence, el('blockquote', citation.text));
      }), true));
      const actions = el('div', undefined, {class: 'row'});
      for (const action of ['approve', 'reject', 'recheck']) add(actions, button(action[0].toUpperCase() + action.slice(1), () => s.run(async () => {
        const path = type === 'claim' ? 'claims/review' : 'memory/review';
        await post(s, path, type === 'claim' ? {claim_ids: [record.id], action} : {record_type: type, record_ids: [record.id], action});
        await s.refresh();
      }), action !== 'approve'));
      add(row, actions);
    }
  }
}
function memory(parent, s) {
  const area = card(parent, 'Known and current');
  note(area, 'History is conservative: overlapping unresolved conflicts can suppress whole records. It is not complete historical coverage.');
  reviews(area, s);
  context(parent, s);
  const creation = details(parent, 'Add or revise records');
  creation.open = !s.memory.entities.length && !s.memory.claims.length;
  const citations = citationPicker(creation, s);
  const entityForm = details(creation, 'Propose entity'); entityForm.open = true;
  const entityName = field(entityForm, 'Entity name'), entityKind = field(entityForm, 'Entity kind', {options: kinds(['project', 'client', 'person', 'organization', 'artifact'])});
  add(entityForm, button('Propose entity', () => s.run(async () => {
    await post(s, 'entities', {kind: entityKind.value, name: entityName.value, citation_ids: citations()}); await s.refresh();
  })));
  const form = details(creation, 'Propose record'); form.open = true;
  const id = field(form, 'Record ID'), kind = field(form, 'Record type', {options: kinds(['fact', 'goal', 'constraint', 'decision', 'commitment'])});
  const key = field(form, 'Topic key'), content = field(form, 'Record text', {rows: 3});
  const entity = field(form, 'Project or client', {options: ids(s.memory.entities.filter(x => ['project', 'client'].includes(x.kind)))});
  const supersedes = field(form, 'Replaces record', {options: ids(s.memory.claims)});
  const from = field(form, 'Valid from (UTC epoch, optional)', {type: 'number'}), until = field(form, 'Valid until (exclusive, optional)', {type: 'number'});
  add(form, button('Propose record', () => s.run(async () => {
    const claim = {kind: kind.value, key: key.value, content: content.value, citation_ids: citations(), entity_ids: entity.value ? [entity.value] : []};
    if (id.value) claim.id = id.value;
    if (supersedes.value) claim.supersedes = supersedes.value;
    if (from.value) claim.valid_from = Number(from.value);
    if (until.value) claim.valid_until = Number(until.value);
    await post(s, 'claims/propose', {claims: [claim]}); await s.refresh();
  })));
  const relation = details(creation, 'Propose relation'); relation.open = true;
  const relationKind = field(relation, 'Relation kind', {options: kinds(['related_to', 'justified_by', 'depends_on', 'supersedes'])});
  const all = [...s.memory.claims, ...s.memory.entities, ...s.memory.relations];
  const fromRecord = field(relation, 'From record', {options: ids(all)}), toRecord = field(relation, 'To record', {options: ids(all)});
  add(relation, button('Propose relation', () => s.run(async () => {
    await post(s, 'relations', {relation: {kind: relationKind.value, from_id: fromRecord.value, to_id: toRecord.value, citation_ids: citations()}}); await s.refresh();
  })));
}
function context(parent, s) {
  const area = card(parent, 'Build context');
  const question = field(area, 'Context question'), scope = field(area, 'Context scope', {options: ids(s.memory.entities.filter(x => x.status === 'active' && ['project', 'client'].includes(x.kind)), 'All readable sources')});
  const bytes = field(area, 'Maximum bytes', {type: 'number', value: '16384'});
  const output = el('div', undefined, {'data-testid': 'context-packet'});
  add(area, button('Build context', () => s.run(async () => {
    const packet = await post(s, 'context', {question: question.value, project_id: scope.value || null, max_bytes: Number(bytes.value)});
    s.packet = packet; output.replaceChildren();
    add(output, el('h3', t('Current facts')), el('p', `${t('Facts')}: ${packet.claims.length} · ${t('Citations')}: ${packet.citations.length} · ${t('Conflicts')}: ${packet.conflicts.length} · ${t('Coverage')}: ${t(packet.coverage.status)}`));
    add(output, el('p', `${t('Expires')}: ${new Date(packet.expires_at * 1000).toISOString()} · ${t('Bytes')}: ${packet.cost.bytes} · ${t('Estimated tokens')}: ${packet.cost.tokens}`));
    for (const claim of packet.claims) add(output, el('p', claim.content));
    if (!packet.claims.length) note(output, 'No current facts in this selection.');
    if (packet.experiences.length) add(output, el('h3', t('Reusable experience')));
    for (const experience of packet.experiences) add(output, el('p', experience.content));
    const limitations = el('ul');
    for (const code of [...packet.unknowns, ...packet.warnings]) add(limitations, el('li', t(contextCopy[code] || code)));
    add(output, limitations);
    const quotations = details(output, 'Source quotations');
    for (const citation of packet.citations) add(quotations, el('blockquote', citation.text), el('small', `${citation.source_id} · ${citation.id}`));
    const technical = details(output, 'Technical packet details');
    result(technical, {coverage: packet.coverage, unknowns: packet.unknowns, warnings: packet.warnings, conflicts: packet.conflicts, network_calls: packet.cost.network_calls});
    note(output, 'Empty or unavailable scope has no fallback to other projects.');
  })), button('Validate current packet', () => s.run(async () => {
    if (!s.packet) throw new Error(t('Build context'));
    result(output, await post(s, 'context/validate', {packet_id: s.packet.id}));
  }), true), output);
}
function changes(parent, s) {
  const area = card(parent, 'Changes');
  if (!s.memory.changes.length) note(area, 'No changes visible.');
  for (const change of s.memory.changes) add(area, el('p', `${change.kind} · ${change.record_id} · ${new Date(change.created_at * 1000).toISOString()}`));
  result(area, {pending: s.memory.pending});
  add(area, button('Recheck dependencies', () => s.run(async () => {
    const status = await post(s, 'dependencies/recheck', {}); await s.refresh(); s.notify(`${t('Graph pending')}: ${status.pending}${status.reason ? ' · ' + status.reason : ''}`);
  })));
  note(area, 'Admission is not semantic approval. Recheck records and earn fresh experience after cleanup.');
  reviews(area, s);
}
function experience(parent, s) {
  const area = card(parent, 'Experience');
  note(area, 'Reported steps, not observed execution or causality. One attestation does not establish eligibility.');
  const citations = citationPicker(area, s);
  const outcomeForm = details(area, 'Record outcome');
  const action = field(outcomeForm, 'Action description (not executed)'), receipt = field(outcomeForm, 'Receipt ID');
  add(outcomeForm, button('Register preaction receipt', () => s.run(async () => {
    if (!s.packet) throw new Error(t('Build context'));
    const value = await post(s, 'actions', {packet_id: s.packet.id, run_id: crypto.randomUUID(), action: action.value}); receipt.value = value.id;
  })));
  const summary = field(outcomeForm, 'Outcome summary', {rows: 2}), steps = field(outcomeForm, 'Reported steps, one per line', {rows: 3});
  add(outcomeForm, button('Record outcome', () => s.run(async () => {
    await post(s, 'outcomes', {receipt_id: receipt.value, outcome: {idempotency_key: crypto.randomUUID(), summary: summary.value, procedure: lines(steps), evidence_citation_ids: citations()}}); await load();
  })));
  const verify = card(area, 'Outcome to verify');
  const selected = field(verify, 'Outcome to verify', {options: [['', 'Select']]}), success = check(verify, 'Successful result');
  const noteInput = field(verify, 'Verification note', {rows: 2}), verifier = field(verify, 'Registered verifier ID');
  note(verify, 'Manual attestation is your statement. A registered verifier must already be configured locally; this field cannot install code or URLs.');
  const verificationOutput = el('div');
  async function attest(configured) {
    const body = {evidence_citation_ids: citations(), note: noteInput.value};
    if (configured) body.verifier_id = verifier.value; else body.success = success.checked;
    const response = await post(s, `outcomes/${selected.value}/${configured ? 'verify-with' : 'verify'}`, body);
    verificationOutput.replaceChildren(); result(verificationOutput, response); await load();
  }
  add(verify, button('Attest result', () => s.run(() => attest(false))), button('Use registered verifier', () => s.run(() => attest(true)), true), verificationOutput);
  const history = el('div'), procedures = el('div'); let outcomeCursor = null, procedureCursor = null;
  async function load(which) {
    const previousSelection = selected.value;
    if (!which) { history.replaceChildren(); procedures.replaceChildren(); selected.replaceChildren(el('option', t('Select'), {value: ''})); outcomeCursor = procedureCursor = null; }
    const query = new URLSearchParams({limit: '20'});
    if (which === 'outcomes' && outcomeCursor) query.set('outcome_cursor', outcomeCursor);
    if (which === 'procedures' && procedureCursor) query.set('procedure_cursor', procedureCursor);
    const response = await s.api(`${s.brain}/experience?${query}`);
    if (which !== 'procedures') {
      if (!response.outcomes.length && !which) note(history, 'No outcomes yet.');
      for (const outcome of response.outcomes) {
        const row = card(history, 'Historical outcome');
        add(row, el('p', outcome.summary), el('span', t(outcome.status), {class: 'badge'}));
        result(row, {integration_status: outcome.integration_status, verification: outcome.verification, reported_steps: outcome.procedure, reporter: outcome.reporter_id, receipt: outcome.receipt_id});
        add(selected, el('option', `${outcome.summary} · ${outcome.status}`, {value: outcome.id}));
      }
      outcomeCursor = response.next_outcome_cursor; moreOutcomes.hidden = !outcomeCursor;
      if ([...selected.options].some(option => option.value === previousSelection)) selected.value = previousSelection;
    }
    if (which !== 'outcomes') {
      for (const procedure of response.procedures) {
        const row = card(procedures, 'Current procedure eligibility');
        add(row, el('p', procedure.content)); result(row, {status: procedure.status, integration_status: procedure.integration_status, eligible: procedure.eligible});
      }
      procedureCursor = response.next_procedure_cursor; moreProcedures.hidden = !procedureCursor;
    }
  }
  const moreOutcomes = button('More outcomes', () => s.run(() => load('outcomes'))), moreProcedures = button('More procedures', () => s.run(() => load('procedures')));
  moreOutcomes.hidden = moreProcedures.hidden = true;
  add(area, button('Refresh history', () => s.run(() => load())), history, moreOutcomes, procedures, moreProcedures);
  s.run(() => load());
}
function sources(parent, s) {
  const area = card(parent, 'Sources and access');
  note(area, 'Pause stops ingestion; existing readable content remains readable. Revocation/deletion blocks future reads. Retained backups and data already forwarded to another client cannot be recalled.');
  if (!s.sources.length) note(area, 'No sources yet. Preview a note or file to begin.');
  for (const source of s.sources) {
    const row = card(area, source.title, {'data-source-id': source.id}); add(row, el('p', `${t(source.status)} · ${source.id}`, {class: 'identifier'}));
    for (const action of ['pause', 'resume', 'revoke', 'delete']) add(row, button(action[0].toUpperCase() + action.slice(1), () => s.run(async () => {
      if (!confirm(t('Confirm this source change?'))) return;
      const status = await post(s, `sources/${source.id}/${action}`, {}); await s.refresh(); s.notify(JSON.stringify(status));
    }), true));
    const acl = details(row, 'Audience');
    const audience = field(acl, 'New audience', {options: [['private', 'Only you'], ['selected', 'Selected identities'], ['members', 'All live members (including future members)']]});
    const readers = field(acl, 'Reader identities, one per line', {rows: 2});
    add(acl, button('Apply audience', () => s.run(async () => {
      if (!confirm(t('Confirm this source change?'))) return;
      await post(s, 'access/sources', {source_id: source.id, readers: audience.value === 'members' ? null : audience.value === 'private' ? [] : lines(readers)}); await s.refresh();
    })));
  }
  agentPanel(parent, s); recovery(parent, s);
}
function agentPanel(parent, s) {
  const area = card(parent, 'Create agent key');
  note(area, 'Select sources deliberately. Source caps are immutable. For a new document, the owner imports it, creates a new scoped credential, and retires the old one. Source-capped agents cannot import.');
  const label = field(area, 'Agent label');
  const selected = s.sources.map(source => [source.id, check(area, `${t('Grant source')} ${source.id}`)]);
  for (let index = 0; index < s.sources.length; index++) note(selected[index][1].parentElement, s.sources[index].title);
  const propose = check(area, 'Allow proposals'), outcome = check(area, 'Allow outcome reports'), exp = check(area, 'Allow export');
  const consent = check(area, 'Add this agent to the selected source audiences');
  const output = el('div');
  add(area, button('Create agent key', () => s.run(async () => {
    const sources = selected.filter(x => x[1].checked).map(x => x[0]);
    if (!sources.length) throw new Error(t('Choose at least one source.'));
    const operations = ['read']; if (propose.checked) operations.push('propose'); if (outcome.checked) operations.push('record_outcome'); if (exp.checked) operations.push('export');
    const issued = await s.api('credentials/agents', {brain_ids: [s.brain], operations, label: label.value, source_grants: {[s.brain]: sources}, grant_selected_sources: consent.checked});
    output.replaceChildren(); add(output, el('p', t('Setup generated; connection unverified')));
    const secret = field(output, 'One-time agent key', {type: 'password', value: issued.token}); secret.readOnly = true;
    add(output, button('Reveal key', () => { secret.type = 'text'; secret.focus(); secret.select(); }, true));
    result(output, {identity: issued.identity, readable_source_refs: issued.readable_source_refs});
    for (const [, input] of selected) input.checked = false;
    propose.checked = outcome.checked = exp.checked = consent.checked = false;
    note(output, 'The downloaded Python check asks for the agent key (or WAVEMIND_BRAIN_TOKEN) and reads one allowed citation. Its successful result proves that HTTP read only; no AI model connection is implied.');
    add(output, button('Hide key', () => { secret.value = ''; output.replaceChildren(); }));
    add(output, button('Download HTTP check', () => s.run(async () => {
      const ref = issued.readable_source_refs[0];
      if (!ref) throw new Error(t('Choose a source and at least one citation.'));
      const page = await s.api(`${ref[0]}/sources/${ref[1]}/citations?limit=1`);
      if (!page.citations.length) throw new Error(t('Choose a source and at least one citation.'));
      const config = btoa(JSON.stringify({origin: location.origin, brain: ref[0], citation: page.citations[0].id}));
      download('wavemind-http-check.py', `# Local D1 citation read check. No model connection is implied.\nimport base64, getpass, json, os, urllib.request\nc = json.loads(base64.b64decode('${config}'))\ntoken = os.environ.get('WAVEMIND_BRAIN_TOKEN') or getpass.getpass('Agent key: ')\nrequest = urllib.request.Request(c['origin'] + '/brain/api/' + c['brain'] + '/citations/' + c['citation'], headers={'Authorization': 'Bearer ' + token})\ntry:\n    with urllib.request.urlopen(request, timeout=15) as response:\n        citation = json.load(response)\n    if citation.get('id') != c['citation']:\n        raise ValueError('Unexpected citation')\n    print('Allowed citation read verified. No model connection is implied.')\nexcept Exception:\n    raise SystemExit('Citation read failed; check local server and live source grants.')\n`, 'text/x-python');
    })));
  })), output);
  const credentials = details(area, 'Credentials');
  add(credentials, button('Refresh', () => s.run(async () => {
    credentials.querySelectorAll('.card').forEach(x => x.remove());
    for (const credential of await s.api('credentials')) {
      const row = card(credentials, credential.label); add(row, el('p', `${credential.status} · ${credential.identity}`, {class: 'identifier'}));
      add(row, button('Revoke credential', () => s.run(async () => {
        if (!confirm(t('Confirm credential revocation? Historical ACL identities remain inert.'))) return;
        const response = await s.api(`credentials/${credential.token_id}/revoke`, {}); result(row, response);
      }), true));
    }
  })));
}
function recovery(parent, s) {
  const area = card(parent, 'Backup and recovery');
  add(area, button('Export JSON', () => s.run(async () => download('brain-export.json', JSON.stringify(await s.api(`${s.brain}/export`), null, 2)))));
  note(area, 'Backup uses the local CLI and a new destination. Restore requires an empty target and a trusted local owner; credentials are not restored. Existing archives are never rotated or deleted automatically.');
  add(area, el('pre', 'python -m wavemind brain backup --state-dir <local-profile> --brain-id ' + s.brain + ' --destination <new-archive>\npython -m wavemind brain restore --state-dir <empty-initialized-profile> --archive <selected-archive>'));
  note(area, 'import_previews_not_restored: committed sources are preserved; unfinished imports and retry screens must be previewed again. Old preview IDs cannot resume. Source-version digest prevents duplicate commits.');
  note(area, 'Archive warnings describe the snapshot when created. Refresh live state. cleanup_pending means cleanup unfinished; purged means that private cleanup completed. Runtime status in export still requires_live_context_validation.');
  add(area, el('p', 'bootstrap_required · recovery_required · restored_sources_quarantined'));
  const managed = details(area, 'Managed sources'); const rows = el('div'); let cursor = null;
  async function load(append) {
    if (!append) { cursor = null; rows.replaceChildren(); }
    const query = new URLSearchParams({limit: '20'}); if (cursor) query.set('cursor', cursor);
    const data = await s.api(`${s.brain}/sources/managed?${query}`);
    for (const source of data.sources) {
      const row = card(rows, source.id); add(row, el('p', t(source.status)));
      if (source.status === 'quarantined') {
        let versionCursor = null, citationCursor = null; const review = el('div');
        async function inspect(which) {
          const q = new URLSearchParams({limit: '20'});
          if (which === 'versions' && versionCursor) q.set('version_cursor', versionCursor);
          if (which === 'citations' && citationCursor) q.set('citation_cursor', citationCursor);
          const page = await s.api(`${s.brain}/sources/${source.id}/review?${q}`);
          if (!which) review.replaceChildren();
          if (which !== 'citations') for (const version of page.versions) add(review, el('p', `v${version.version} · ${version.digest}`));
          if (which !== 'versions') for (const citation of page.citations) add(review, el('blockquote', citation.text));
          if (which !== 'citations') versionCursor = page.next_version_cursor;
          if (which !== 'versions') citationCursor = page.next_citation_cursor;
          moreVersions.hidden = !versionCursor; moreCitations.hidden = !citationCursor; admit.hidden = false;
        }
        const moreVersions = button('More versions', () => s.run(() => inspect('versions'))), moreCitations = button('More recovery citations', () => s.run(() => inspect('citations')));
        const admit = button('Admit reviewed source', () => s.run(async () => {
          if (!confirm(t('Confirm this source change?'))) return;
          const admitted = await post(s, 'sources/admit', {source_ids: [source.id]}); await s.refresh(); s.notify(JSON.stringify(admitted));
        }));
        moreVersions.hidden = moreCitations.hidden = admit.hidden = true;
        add(row, button('Review quarantined source', () => s.run(() => inspect())), review, moreVersions, moreCitations, admit);
        note(row, 'Admission is not semantic approval. Recheck records and earn fresh experience after cleanup.');
      }
      if (!s.sources.some(x => x.id === source.id)) add(row, button('Delete', () => s.run(async () => {
        if (!confirm(t('Confirm this source change?'))) return;
        result(row, await post(s, `sources/${source.id}/delete`, {}));
      }), true));
    }
    cursor = data.next_cursor; more.hidden = !cursor;
  }
  const more = button('More managed sources', () => s.run(() => load(true))); more.hidden = true;
  add(managed, button('Refresh', () => s.run(() => load(false))), rows, more);
}
export function renderPanel(parent, section, state) {
  ({'Known and current': memory, 'Changes': changes, 'Experience': experience, 'Sources and access': sources})[section]?.(parent, state);
}
