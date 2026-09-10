// Deterministic timing controls around real HTTP responses and bundled UI modules.
import {createRequire} from 'node:module';
import {mkdtemp, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
let playwright;
try { playwright = require(process.env.BRAIN_UI_PLAYWRIGHT || 'playwright'); }
catch { console.error('Playwright unavailable; browser gate unexecuted.'); process.exit(77); }
const origin = process.env.BRAIN_UI_ORIGIN, evidence = process.env.BRAIN_UI_EVIDENCE;
const mode = process.env.BRAIN_UI_TRANSITION;
const {a, b} = JSON.parse(process.env.BRAIN_UI_FIXTURE);
const profile = await mkdtemp(join(tmpdir(), 'wm-transition-'));
let browser, page, stage = 'launch';
const posts = [], releases = [];
const latch = () => { let resolve; const promise = new Promise(done => resolve = done); return {promise, resolve}; };
const held = {sources: latch(), memory: latch()}, delivered = {sources: latch(), memory: latch()};
const gates = {sources: latch(), memory: latch()};
try {
  browser = await playwright.chromium.launchPersistentContext(profile, {headless: true,
    executablePath: process.env.BRAIN_UI_CHROME || undefined, viewport: {width: 1280, height: 900}});
  page = await browser.newPage(); page.setDefaultTimeout(8000);
  await page.addInitScript(() => {
    const original = window.fetch;
    window.claimMutations = [];
    window.fetch = (url, options) => {
      if (options?.method === 'POST' && String(url).endsWith('/claims/review')) window.claimMutations.push(String(url));
      return original(url, options);
    };
  });
  const click = name => page.getByRole('button', {name, exact: true}).click();
  await page.goto(origin + '/brain');
  await page.getByLabel('Ключ владельца', {exact: true}).fill(process.env.BRAIN_UI_OWNER_KEY);
  await click('Войти'); await click('EN'); await click('DEMO Brain A');
  await page.getByTestId('brain-id').filter({hasText: a}).waitFor();
  await click('Known and current');
  await page.getByText('Only Brain A budget', {exact: true}).waitFor();
  await page.locator('[data-record-id="budget"]').getByRole('button', {name: 'Approve', exact: true}).evaluate(node => { window.detachedApproval = node; });
  await click('Projects');
  await page.route(`**/brain/api/${b}/*`, async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() === 'POST') { posts.push(path); await route.continue(); return; }
    const kind = path.split('/').at(-1);
    if (!held[kind]) { await route.continue(); return; }
    const response = await route.fetch(); // real service/auth response, delayed only in delivery
    held[kind].resolve();
    await gates[kind].promise;
    await route.fulfill({response}); delivered[kind].resolve();
  });
  releases.push(() => gates.sources.resolve(), () => gates.memory.resolve());
  await click('DEMO Brain B');
  await Promise.all([held.sources.promise, held.memory.promise]);
  if (mode === 'mutation') {
    stage = 'detached approval during Brain transition must not issue a mutation';
    const attempted = await page.evaluate(() => { window.detachedApproval.click(); return window.claimMutations; });
    assert.deepEqual(attempted, []);
    stage = 'no prior Brain record or editable form during incomplete reads';
    assert.equal(await page.getByText('Only Brain A budget', {exact: true}).count(), 0);
    assert.equal(await page.getByLabel('Source text', {exact: true}).count(), 0);
    assert.equal(await page.getByRole('button', {name: 'Known and current', exact: true}).isDisabled(), true);
  } else {
    stage = 'partial reversed read completion must not expose an editable form';
    gates.memory.resolve(); await delivered.memory.promise;
    // Deliberately dispatch even on a disabled control: the handler must enforce readiness.
    await page.getByRole('button', {name: 'Sources and access', exact: true}).evaluate(node => node.dispatchEvent(new Event('click')));
    assert.equal(await page.getByLabel('Source text', {exact: true}).count(), 0);
    assert.equal(await page.locator('main').getAttribute('aria-busy'), 'true');
  }
  gates.memory.resolve(); gates.sources.resolve();
  await Promise.all([delivered.memory.promise, delivered.sources.promise]);
  stage = 'ready selected Brain exposes only its own records';
  await page.getByLabel('Source text', {exact: true}).waitFor();
  assert.equal(await page.locator('main').getAttribute('aria-busy'), 'false');
  assert.equal((await page.getByTestId('brain-id').textContent()).trim(), b);
  await click('Known and current');
  await page.getByText('Only Brain B budget', {exact: true}).waitFor();
  assert.equal(await page.getByText('Only Brain A budget', {exact: true}).count(), 0);
  stage = 'old detached approval must remain rejected after readiness';
  assert.deepEqual(await page.evaluate(() => { window.detachedApproval.click(); return window.claimMutations; }), []);
  assert.deepEqual(posts, []);
  await click('Sources and access');
  await page.getByLabel('Source name', {exact: true}).fill('preserved.txt');
  await page.getByLabel('Source text', {exact: true}).fill('DEMO preserved input after full readiness.');
  // Both response deliveries already completed; no timer/sleep stands in for readiness.
  await page.evaluate(() => fetch('/brain/api/session'));
  assert.equal(await page.getByLabel('Source text', {exact: true}).inputValue(), 'DEMO preserved input after full readiness.');
  const previewResponse = page.waitForResponse(r => r.url().endsWith('/sources/preview') && r.request().method() === 'POST');
  await click('Preview'); const response = await previewResponse;
  assert.equal(response.status(), 200);
  const preview = await response.json();
  assert.equal(preview.files[0].preview_text, 'DEMO preserved input after full readiness.');
  await page.screenshot({path: join(evidence, 'transition-ready.png'), fullPage: true});
  await click('Cancel import');
  await writeFile(join(evidence, 'transition-result.json'), JSON.stringify({mode, wrong_brain_mutations: 0, stale_handler_rejected: true, input_preserved: true, real_modules: true}));
  console.log('Transition gate passed: stale action rejected; delayed reads isolated; ready form preserved.');
} catch (error) {
  console.error(`Transition gate failed: ${stage}; ${error.name}`);
  await writeFile(join(evidence, 'transition-failure.json'), JSON.stringify({mode, stage, mutation_paths: posts}));
  if (page) await page.screenshot({path: join(evidence, 'transition-failure.png'), fullPage: true, mask: [page.locator('input[type=password]')]}).catch(() => {});
  process.exitCode = 1;
} finally {
  releases.forEach(release => release());
  if (browser) { try { await browser.clearCookies(); } finally { await browser.close(); } }
}
