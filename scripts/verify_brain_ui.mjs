// Optional verifier only: npm-installed playwright, or explicit BRAIN_UI_PLAYWRIGHT path.
// No production runtime, credentials in output, user browser profile, or remote assets.
import {createRequire} from 'node:module';
import {mkdtemp, mkdir, writeFile, access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';

const require = createRequire(import.meta.url);
let playwright;
try { playwright = require(process.env.BRAIN_UI_PLAYWRIGHT || 'playwright'); }
catch { console.error('Playwright unavailable; browser gate unexecuted.'); process.exit(77); }
const origin = process.env.BRAIN_UI_ORIGIN;
const ownerKey = process.env.BRAIN_UI_OWNER_KEY;
if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(origin || '') || !ownerKey) {
  console.error('Explicit loopback origin and ephemeral owner credential required.'); process.exit(2);
}
const evidence = resolve(process.env.BRAIN_UI_EVIDENCE || await mkdtemp(join(tmpdir(), 'wm-ui-evidence-')));
await mkdir(evidence, {recursive: true});
const profile = await mkdtemp(join(tmpdir(), 'wm-ui-browser-'));
let browser, page;
const clients = [];
let stage = 'browser launch';
try {
  browser = await playwright.chromium.launchPersistentContext(profile, {
    headless: true, executablePath: process.env.BRAIN_UI_CHROME || undefined,
    viewport: {width: 1280, height: 900},
  });
  page = await browser.newPage();
  page.setDefaultTimeout(8000);
  const consoleErrors = [];
  const failedResponses = [], failedRequests = [], expectedResponses = [{path: '/brain/api/session', status: 401}];
  page.on('response', response => { if (response.status() >= 400) failedResponses.push({path: new URL(response.url()).pathname, status: response.status()}); });
  page.on('requestfailed', request => failedRequests.push({path: new URL(request.url()).pathname, error: request.failure()?.errorText}));
  page.on('pageerror', () => consoleErrors.push('pageerror'));
  page.on('console', message => {
    // Every HTTP failure is separately checked against exact deliberate negatives below.
    if (message.type() === 'error' && !message.text().startsWith('Failed to load resource:')) consoleErrors.push('console');
  });
  const click = name => { stage = `button ${name}`; return page.getByRole('button', {name, exact: true}).click(); };
  const fill = (name, value) => { stage = `field ${name}`; return page.getByLabel(name, {exact: true}).fill(value); };
  async function action(path, callback) {
    const pending = page.waitForResponse(r => r.url().endsWith(path) && r.request().method() === 'POST');
    await callback();
    const response = await pending;
    assert.equal(response.status(), 200, `UI request failed: ${path.split('/').at(-1)}`);
    return response.json();
  }
  async function pick(source) {
    stage = 'citation picker';
    await page.getByLabel('Citation source', {exact: true}).waitFor({state: 'attached'});
    if (!await page.getByLabel('Citation source', {exact: true}).isVisible()) await page.getByText('Add or revise records', {exact: true}).click();
    await page.getByLabel('Citation source', {exact: true}).selectOption(source.id);
    await click('Load citations');
    stage = 'citation checkbox';
    await page.getByLabel(`Use citation ${source.citations[0].id}`, {exact: true}).check();
    stage = 'citation selected';
  }
  async function importText(name, text) {
    await click('Sources and access');
    await fill('Source name', name);
    await fill('Source text', text);
    const preview = await action('/sources/preview', () => click('Preview'));
    assert.deepEqual(preview.new_source_access, {mode: 'restricted', readers: []});
    const saved = await action('/sources/commit', () => click('Save source'));
    await page.getByText('Source saved', {exact: true}).waitFor();
    return saved.sources[0];
  }
  async function claim(id, kind, key, content, source, entity, supersedes = '') {
    await click('Known and current');
    await pick(source);
    await fill('Record ID', id);
    await page.getByLabel('Record type', {exact: true}).selectOption(kind);
    await fill('Topic key', key);
    await fill('Record text', content);
    await page.getByLabel('Project or client', {exact: true}).selectOption(entity);
    await page.getByLabel('Replaces record', {exact: true}).selectOption(supersedes);
    if (supersedes) await fill('Valid from (UTC epoch, optional)', String(Date.now() / 1000));
    stage = `propose ${id}`;
    const result = await action('/claims/propose', () => click('Propose record'));
    assert.equal(result[0].status, 'proposed');
    stage = `approve ${id}`;
    await page.locator(`[data-record-id="${id}"]`).getByRole('button', {name: 'Approve', exact: true}).click();
    await page.locator(`[data-record-id="${id}"]`).getByText('active', {exact: true}).waitFor();
    return result[0];
  }
  async function issue(label, sources) {
    await click('Sources and access');
    await fill('Agent label', label);
    for (const source of sources) await page.getByLabel(`Grant source ${source.id}`, {exact: true}).check();
    await page.getByLabel('Allow proposals', {exact: true}).check();
    await page.getByLabel('Allow outcome reports', {exact: true}).check();
    await page.getByLabel('Add this agent to the selected source audiences', {exact: true}).check();
    const issued = await action('/credentials/agents', () => click('Create agent key'));
    await page.getByText('Setup generated; connection unverified', {exact: true}).waitFor();
    const client = await playwright.request.newContext({baseURL: origin, extraHTTPHeaders: {Authorization: `Bearer ${issued.token}`}});
    clients.push(client);
    const check = await client.get(`/brain/api/${brain}/citations/${sources[0].citations[0].id}`);
    assert.equal(check.status(), 200);
    assert.equal((await check.json()).id, sources[0].citations[0].id);
    const downloadEvent = page.waitForEvent('download');
    await click('Download HTTP check');
    const download = await downloadEvent;
    const stream = await download.createReadStream();
    let setup = ''; for await (const chunk of stream) setup += chunk.toString();
    assert(!setup.includes(issued.token) && !setup.includes(ownerKey));
    const checked = spawnSync(process.env.BRAIN_UI_PYTHON || 'python', ['-'], {input: setup, encoding: 'utf8', timeout: 20000,
      env: {...process.env, WAVEMIND_BRAIN_TOKEN: issued.token}});
    assert.equal(checked.status, 0, 'Downloaded Python HTTP check failed');
    assert.equal(checked.stdout.trim(), 'Allowed citation read verified. No model connection is implied.');
    assert.equal(checked.stderr, '');
    await click('Hide key');
    return {client, identity: issued.identity, tokenId: issued.token_id};
  }
  async function agentPost(client, path, data, expected = 200) {
    const response = await client.post(`/brain/api/${brain}/${path}`, {data});
    assert.equal(response.status(), expected, `Agent operation ${path.split('/')[0]}`);
    return response.json();
  }
  stage = 'Russian first-use journey';
  await page.goto(`${origin}/brain`);
  await page.getByLabel('Ключ владельца', {exact: true}).fill(ownerKey);
  await page.getByRole('button', {name: 'Войти', exact: true}).click();
  await page.getByRole('button', {name: 'Личный проект', exact: true}).click();
  if (process.env.BRAIN_UI_SCENARIO === 'B1') await click('Клиентский проект');
  await page.getByLabel('Название проекта', {exact: true}).fill('Переезд');
  await page.getByRole('button', {name: 'Создать память', exact: true}).click();
  await page.getByLabel('Текст источника', {exact: true}).fill('Бюджет переезда 60000 рублей.');
  await page.getByRole('button', {name: 'Предпросмотр', exact: true}).click();
  await page.getByText('Данные не отправляются внешней модели', {exact: true}).waitFor();
  const initial = await action('/sources/commit', () => click('Сохранить источник'));
  const base = initial.sources[0];
  await click('EN');
  const scenario = process.env.BRAIN_UI_SCENARIO || 'P1';
  const variant = Number(process.env.BRAIN_UI_VARIANT || 0);
  const title = variant ? 'Harbor transfer' : 'Orchard transfer';
  const corrected = variant ? 'Limit is 42000 credits.' : 'Limit is 55000 credits.';
  const brain = (await page.getByTestId('brain-id').textContent()).trim();
  const hiddenText = `DEMO hidden ${variant ? 'Cedar' : 'Birch'} internal pricing.`;
  stage = 'cancellation, per-file failures and nonsecret fixture imports';
  await fill('Source text', 'Cancelled fixture');
  await action('/sources/preview', () => click('Preview'));
  await action('/sources/commit', () => click('Cancel import'));
  await page.getByText('Import cancelled', {exact: true}).waitFor();
  await page.getByLabel('Files', {exact: true}).setInputFiles({name: 'rejected.zip', mimeType: 'application/zip', buffer: Buffer.from('not an archive')});
  await fill('Source text', '');
  await action('/sources/preview', () => click('Preview'));
  await page.getByTestId('preview').getByText('error', {exact: true}).waitFor();
  await action('/sources/commit', () => click('Cancel import'));
  await page.getByLabel('Files', {exact: true}).setInputFiles([]);
  await page.getByLabel('Update source', {exact: true}).selectOption(base.id);
  await fill('Source text', 'A single selected update');
  await page.getByLabel('Files', {exact: true}).setInputFiles({name: 'unrelated.txt', mimeType: 'text/plain', buffer: Buffer.from('Must not become a broadly shared new source')});
  await click('Preview');
  await page.getByRole('alert').getByText('An update accepts exactly one pasted text or one file.', {exact: true}).waitFor();
  await page.getByLabel('Files', {exact: true}).setInputFiles([]);
  await page.getByLabel('Update source', {exact: true}).selectOption('');
  const inputs = [
    ['conversation.txt', `DEMO ${title}. Goal: transfer safely. Deadline: Friday. Decision: inspect first. Rationale: avoid loss. Open question: who signs?`],
    ['result-1.txt', `DEMO independent result ${title} one checked at dock one.`],
    ['result-2.txt', `DEMO independent result ${title} two checked at dock two.`],
    ['result-3.txt', `DEMO independent result ${title} three checked at dock three.`],
  ];
  const documents = {};
  for (const [name, text] of (variant ? [...inputs].reverse() : inputs)) documents[name] = await importText(name, text);
  const transcript = documents['conversation.txt'];
  const evidenceSources = [documents['result-1.txt'], documents['result-2.txt'], documents['result-3.txt']];
  const initialSources = [base, transcript, ...evidenceSources];
  const priorEvidence = await importText('prior-result.txt', `DEMO prior independently observed outcome for ${title}.`);
  initialSources.push(priorEvidence);
  const agentA = await issue('DEMO Agent A', initialSources);
  const oldB = await issue('DEMO Agent B before update', initialSources);
  assert.notEqual(agentA.identity, oldB.identity);
  await fill('Source name', 'notes.txt');
  await fill('Source text', 'Бюджет переезда 60000 рублей.');
  expectedResponses.push({path: `/brain/api/${brain}/sources/preview`, status: 422});
  const rejectedAudience = page.waitForResponse(r => r.url().endsWith('/sources/preview') && r.request().method() === 'POST');
  await click('Preview');
  assert.equal((await rejectedAudience).status(), 422);
  await page.getByRole('alert').waitFor();
  assert.equal(await page.getByRole('button', {name: 'Save source', exact: true}).count(), 0);
  const internal = await importText('internal.txt', hiddenText);
  assert.equal((await oldB.client.get(`/brain/api/${brain}/citations/${internal.citations[0].id}`)).status(), 404);
  stage = 'reviewed typed facts, entity, rationale and conflicts';
  await click('Known and current');
  await pick(transcript);
  await fill('Entity name', title);
  await page.getByLabel('Entity kind', {exact: true}).selectOption(scenario === 'B1' ? 'client' : 'project');
  stage = 'propose entity';
  const entity = await action('/entities', () => click('Propose entity'));
  stage = 'approve entity';
  await page.locator(`[data-record-id="${entity.id}"]`).getByRole('button', {name: 'Approve', exact: true}).click();
  await page.locator(`[data-record-id="${entity.id}"]`).getByText('active', {exact: true}).waitFor();
  await claim('goal', 'goal', 'goal', 'Transfer safely.', transcript, entity.id);
  await claim('budget', 'constraint', 'budget', 'Limit is 60000 credits.', base, entity.id);
  await claim('deadline', 'constraint', 'deadline', 'Finish by Friday.', transcript, entity.id);
  await claim('decision', 'decision', 'decision', 'Inspect first.', transcript, entity.id);
  await claim('rationale', 'fact', 'rationale', 'Avoid loss.', transcript, entity.id);
  await claim('question', 'fact', 'open-question', 'Unknown: who signs?', transcript, entity.id);
  await pick(transcript);
  await page.getByLabel('Relation kind', {exact: true}).selectOption('justified_by');
  await page.getByLabel('From record', {exact: true}).selectOption('decision');
  await page.getByLabel('To record', {exact: true}).selectOption('rationale');
  const relation = await action('/relations', () => click('Propose relation'));
  await page.locator(`[data-record-id="${relation.id}"]`).getByRole('button', {name: 'Approve', exact: true}).click();
  await page.locator(`[data-record-id="${relation.id}"]`).getByText('active', {exact: true}).waitFor();
  await pick(transcript);
  await fill('Record ID', 'conflicting-budget');
  await page.getByLabel('Record type', {exact: true}).selectOption('constraint');
  await fill('Topic key', 'budget'); await fill('Record text', 'Competing limit is 70000 credits.');
  await page.getByLabel('Project or client', {exact: true}).selectOption(entity.id);
  await action('/claims/propose', () => click('Propose record'));
  await action('/claims/review', () => page.locator('[data-record-id="conflicting-budget"]').getByRole('button', {name: 'Approve', exact: true}).click());
  await page.locator('[data-record-id="budget"]').getByText('conflicted', {exact: true}).waitFor();
  const conflicted = await agentPost(agentA.client, 'context', {question: 'budget', project_id: entity.id});
  assert(conflicted.conflicts.some(record => record.id === 'budget'));
  await action('/claims/review', () => page.locator('[data-record-id="conflicting-budget"]').getByRole('button', {name: 'Reject', exact: true}).click());
  await page.locator('[data-record-id="budget"]').getByText('active', {exact: true}).waitFor();
  await agentPost(agentA.client, 'memory/review', {record_type: 'entity', record_ids: [entity.id], action: 'approve'}, 404);
  const before = await agentPost(agentA.client, 'context', {question: 'transfer budget decision rationale unknown', project_id: entity.id});
  assert(before.claims.some(c => c.id === 'budget'));
  const priorReceipt = await agentPost(agentA.client, 'actions', {packet_id: before.id, run_id: `prior-${scenario}-${variant}`, action: 'Prior proposed inspection'});
  const priorOutcome = await agentPost(agentA.client, 'outcomes', {receipt_id: priorReceipt.id, outcome: {
    idempotency_key: 'prior-report', summary: 'DEMO prior outcome', procedure: ['Prior inspection report'], evidence_citation_ids: [priorEvidence.citations[0].id],
  }});
  await click('Experience'); await click('Refresh history'); await pick(priorEvidence);
  await page.getByLabel('Outcome to verify', {exact: true}).selectOption(priorOutcome.id);
  await page.getByLabel('Successful result', {exact: true}).setChecked(scenario === 'B1');
  const priorVerified = await action(`/outcomes/${priorOutcome.id}/verify`, () => click('Attest result'));
  assert.equal(priorVerified.status, scenario === 'B1' ? 'verified' : 'failed');
  // Other client is a separate Brain, with a deliberately renamed negative control.
  await click('Projects');
  await click('Client workspace');
  await fill('Project name', variant ? 'Larch client' : 'Maple client');
  const other = await action('/brains', () => click('Create memory'));
  const otherSource = await importText('other-client.txt', 'DEMO cross-client private limit 999999.');
  assert.equal((await oldB.client.get(`/brain/api/${other.id}/citations/${otherSource.citations[0].id}`)).status(), 404);
  await click('Projects'); await click('Переезд');
  stage = 'restart, page reload, second tab and citation picker recovery';
  await writeFile(join(evidence, 'restart.request'), 'restart');
  const deadline = Date.now() + 30000;
  while (true) {
    try { await access(join(evidence, 'restart.ready')); break; }
    catch { assert(Date.now() < deadline, 'Restart timed out'); await new Promise(r => setTimeout(r, 50)); }
  }
  await page.reload();
  await click('Переезд');
  const secondTab = await browser.newPage();
  await secondTab.goto(`${origin}/brain`);
  await secondTab.getByRole('button', {name: 'Переезд', exact: true}).waitFor();
  await secondTab.close();
  const pendingPacket = await agentPost(oldB.client, 'context', {question: 'transfer'});
  assert.equal(pendingPacket.coverage.status, 'pending');
  assert.deepEqual(pendingPacket.claims, []);
  await click('Changes');
  const rechecked = await action('/dependencies/recheck', () => click('Recheck dependencies'));
  assert.equal(rechecked.pending, false);
  await page.getByRole('status').getByText('Graph pending: false', {exact: true}).waitFor();
  await click('Known and current'); await pick(transcript);
  assert.equal((await oldB.client.get(`/brain/api/${brain}/citations/${transcript.citations[0].id}`)).status(), 200);
  const correction = await importText('correction.txt', `DEMO policy correction. ${corrected}`);
  assert.equal((await oldB.client.get(`/brain/api/${brain}/citations/${correction.citations[0].id}`)).status(), 404);
  const agentB = await issue('DEMO Agent B updated selection', [...initialSources, correction]);
  await claim('budget-new', 'constraint', 'budget', corrected, correction, entity.id, 'budget');
  const after = await agentPost(agentB.client, 'context', {question: 'transfer budget decision rationale unknown', project_id: entity.id});
  assert(after.claims.some(c => c.id === 'budget-new' && c.content === corrected));
  assert(!after.claims.some(c => c.id === 'budget'));
  assert(after.claims.some(c => c.content === 'Avoid loss.'));
  assert(after.claims.some(c => c.content === 'Unknown: who signs?'));
  assert(!JSON.stringify(after).includes(hiddenText));
  const changedHistory = await (await agentB.client.get(`/brain/api/${brain}/experience`)).json();
  assert(changedHistory.outcomes.some(item => item.id === priorOutcome.id && item.verification.success === (scenario === 'B1')));
  assert(!changedHistory.procedures.some(item => item.outcome_ids.includes(priorOutcome.id) && item.eligible));
  await agentPost(agentA.client, 'context/validate', {packet_id: before.id}, 422);
  stage = 'owner context, fresh reported outcomes, failed verifier and later eligibility';
  await click('Known and current');
  await fill('Context question', 'transfer budget decision rationale unknown');
  await page.getByLabel('Context scope', {exact: true}).selectOption(entity.id);
  const uiPacket = await action('/context', () => click('Build context'));
  await page.getByTestId('context-packet').getByText(corrected, {exact: true}).waitFor();
  const technical = page.getByTestId('context-packet').locator('details').filter({has: page.getByText('Technical packet details', {exact: true})});
  assert.equal(await technical.getAttribute('open'), null);
  await page.getByTestId('context-packet').getByText('Coverage is partial; this is not a complete account.', {exact: true}).waitFor();
  await page.getByTestId('context-packet').scrollIntoViewIfNeeded();
  await page.screenshot({path: join(evidence, `${scenario}-${variant}-context.png`)});
  assert.equal(uiPacket.cost.network_calls, 0);
  assert(uiPacket.cost.bytes > 0 && uiPacket.cost.tokens > 0);
  for (let index = 0; index < 3; index++) {
    const packet = await agentPost(agentB.client, 'context', {question: 'transfer', project_id: entity.id});
    const receipt = await agentPost(agentB.client, 'actions', {packet_id: packet.id, run_id: `demo-${scenario}-${variant}-${index}`, action: 'Report-only inspection'});
    const outcome = await agentPost(agentB.client, 'outcomes', {receipt_id: receipt.id, outcome: {
      idempotency_key: `result-${index}`, summary: `DEMO inspection result ${index}`, procedure: ['Inspect transfer', 'Check limit'],
      evidence_citation_ids: [evidenceSources[index].citations[0].id],
    }});
    assert.equal(outcome.status, 'unverified');
    await click('Experience'); await click('Refresh history'); await pick(evidenceSources[index]);
    await page.getByLabel('Outcome to verify', {exact: true}).selectOption(outcome.id);
    if (index === 0) {
      await fill('Registered verifier ID', 'demo-unavailable');
      const failed = await action(`/outcomes/${outcome.id}/verify-with`, () => click('Use registered verifier'));
      assert.equal(failed.status, 'unverified'); assert.equal(failed.integration_status, 'verification_failed');
    }
    await page.getByLabel('Successful result', {exact: true}).check();
    const verified = await action(`/outcomes/${outcome.id}/verify`, () => click('Attest result'));
    assert.equal(verified.verification.mode, 'manual_attestation');
    await click('Refresh history');
    const untilIntegrated = Date.now() + 10000;
    let body;
    do {
      body = await (await agentB.client.get(`/brain/api/${brain}/experience`)).json();
      if (body.outcomes.find(item => item.id === outcome.id)?.integration_status === 'completed') break;
      assert(Date.now() < untilIntegrated, 'Server maintenance did not integrate the outcome');
      await new Promise(resolve => setTimeout(resolve, 100));
    } while (true);
    if (index === 0) assert(!body.procedures.some(p => p.eligible));
    if (index === 2) assert(body.procedures.some(p => p.eligible));
  }
  const experienced = await agentPost(agentB.client, 'context', {question: 'transfer inspection', project_id: entity.id});
  assert(experienced.experiences.length > 0);
  stage = 'narrow keyboard UI, storage, screenshots and lifecycle negative controls';
  await page.setViewportSize({width: 390, height: 844});
  await page.getByRole('button', {name: 'Projects', exact: true}).focus();
  await page.keyboard.press('Tab');
  stage = 'narrow keyboard focus';
  assert(await page.evaluate(() => document.activeElement.textContent === 'Known and current' && getComputedStyle(document.activeElement).outlineStyle !== 'none'));
  await page.keyboard.press('Enter');
  await page.locator('[data-record-id="goal"]').waitFor();
  stage = 'narrow viewport width';
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  stage = 'computed text contrast';
  const contrast = await page.evaluate(() => {
    const luminance = color => {
      const rgb = color.match(/[\d.]+/g).slice(0, 3).map(Number).map(value => { const c = value / 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; });
      return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
    };
    const ratio = (a, b) => (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
    const body = getComputedStyle(document.documentElement), button = getComputedStyle(document.querySelector('nav button'));
    return {body: ratio(luminance(body.color), luminance(body.backgroundColor)), button: ratio(luminance(button.color), luminance(button.backgroundColor))};
  });
  assert(contrast.body >= 4.5 && contrast.button >= 4.5, 'Normal-size text contrast');
  await page.screenshot({path: join(evidence, `${scenario}-${variant}-mobile.png`), fullPage: true});
  await page.setViewportSize({width: 1280, height: 900});
  await click('Known and current');
  await page.screenshot({path: join(evidence, `${scenario}-${variant}-desktop.png`), fullPage: true});
  const stored = await page.evaluate(() => ({local: Object.keys(localStorage), session: Object.keys(sessionStorage), cookie: document.cookie}));
  assert.deepEqual(stored.local, ['brain-language']); assert.deepEqual(stored.session, []); assert.equal(stored.cookie, '');
  await click('Sources and access');
  page.once('dialog', dialog => dialog.accept());
  await action(`/sources/${correction.id}/revoke`, () => page.locator(`[data-source-id="${correction.id}"]`).getByRole('button', {name: 'Revoke', exact: true}).click());
  stage = 'revoked source denies bound client';
  assert.equal((await agentB.client.get(`/brain/api/${brain}/citations/${correction.citations[0].id}`)).status(), 404);
  await agentPost(agentB.client, 'context/validate', {packet_id: experienced.id}, 404);
  page.once('dialog', dialog => dialog.accept());
  await action(`/sources/${base.id}/delete`, () => page.locator(`[data-source-id="${base.id}"]`).getByRole('button', {name: 'Delete', exact: true}).click());
  stage = 'deleted source excluded from context';
  const deleted = await agentPost(agentB.client, 'context', {question: 'budget', project_id: entity.id});
  assert(!deleted.claims.some(c => c.id === 'budget'));
  assert(!JSON.stringify(deleted).includes('Бюджет переезда'));
  await click('Sign out');
  await page.getByLabel('Owner key', {exact: true}).waitFor();
  if (process.env.BRAIN_UI_TEST_CONTROL === '1') {
    expectedResponses.push({path: '/brain/api/brains', status: 401});
    for (const control of ['expire', 'revoke']) {
      await fill('Owner key', ownerKey); await click('Sign in');
      await page.getByRole('button', {name: 'Переезд', exact: true}).waitFor();
      await writeFile(join(evidence, `${control}.request`), control);
      const limit = Date.now() + 10000;
      while (true) { try { await access(join(evidence, `${control}.ready`)); break; } catch { assert(Date.now() < limit); await new Promise(resolve => setTimeout(resolve, 50)); } }
      await click('Projects');
      await page.getByLabel('Owner key', {exact: true}).waitFor();
      assert.equal(await page.getByTestId('brain-id').count(), 0);
    }
  }
  stage = 'unexpected console errors';
  assert(failedResponses.every(response => expectedResponses.some(expected => expected.path === response.path && expected.status === response.status)), 'Unexpected HTTP response failure');
  assert.deepEqual(failedRequests, [], 'Unexpected network request failure');
  assert.deepEqual(consoleErrors, []);
  await writeFile(join(evidence, 'result.json'), JSON.stringify({scenario, variant, brain_id: brain, corrected_content: corrected,
    two_bound_clients: true, cross_client_denied: true, restart: true, demo: 'Synthetic nonsecret fixtures; no model answers or measured usefulness',
    console_errors: 0, deliberate_http_errors: failedResponses, text_contrast: contrast, persisted_pending_rechecked: true, session_controls: process.env.BRAIN_UI_TEST_CONTROL === '1',
    screenshots: [`${scenario}-${variant}-mobile.png`, `${scenario}-${variant}-desktop.png`, `${scenario}-${variant}-context.png`]}));
  console.log(`${scenario} variation ${variant}: browser and independent HTTP client checks passed (synthetic nonsecret demo).`);
} catch (error) {
  // Do not emit Playwright call logs (fill values and response bodies can be credentials).
  console.error(`Browser gate failed at: ${stage}; ${error.name}`);
  if (page) await page.screenshot({path: join(evidence, 'failure.png'), fullPage: true, mask: [page.locator('input[type=password]')]}).catch(() => {});
  process.exitCode = 1;
} finally {
  for (const client of clients) await client.dispose();
  if (browser) { try { await browser.clearCookies(); } finally { await browser.close(); } }
  // Retain the newly allocated isolated profile as test-owned evidence; never use user profiles.
}
