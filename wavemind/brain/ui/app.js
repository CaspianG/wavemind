import {el, add, t, setLanguage, button, field, card, note, lines, check} from './ui.js';
import {renderPanel} from './panels.js';

const root = document.getElementById('app');
let language = localStorage.getItem('brain-language') === 'en' ? 'en' : 'ru';
setLanguage(language);
let csrf = '', timer, generation = 0, pending = new AbortController();
let section = 'Projects', preview = null, importController = null, messageNode, main;
const s = {brain: '', sources: [], memory: {claims: [], entities: [], relations: [], changes: [], pending: []}, packet: null};
function forget() {
  generation++; pending.abort(); pending = new AbortController(); importController?.abort(); clearTimeout(timer);
  csrf = ''; preview = null; s.brain = ''; s.sources = []; s.memory = {claims: [], entities: [], relations: [], changes: [], pending: []}; s.packet = null;
  section = 'Projects'; root.replaceChildren();
}
function message(value, error = false) {
  if (!messageNode) return;
  messageNode.setAttribute('role', error ? 'alert' : 'status'); messageNode.textContent = value;
}
s.run = async callback => {
  const current = generation;
  message(t('Working…'));
  try { await callback(); if (current === generation && messageNode?.textContent === t('Working…')) message(t('Done')); }
  catch (error) {
    if (error.name === 'AbortError' || current !== generation) return;
    message(error.message || t('Request failed. Check the visible fields and retry.'), true);
  }
};
s.api = async (path, data, signal) => {
  const current = generation;
  const response = await fetch('/brain/api/' + path, {
    method: data === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: data === undefined ? {} : {'Content-Type': 'application/json', ...(csrf ? {'X-Brain-CSRF': csrf} : {})},
    body: data === undefined ? undefined : JSON.stringify(data), signal: signal || pending.signal,
  });
  const result = await response.json();
  if (current !== generation) throw new DOMException('Abandoned view', 'AbortError');
  if (!response.ok) {
    const code = result.error?.code || 'request_failed';
    if ((response.status === 401 || code === 'csrf_required') && csrf) {
      forget(); shell(false); message(t('Session ended. Sign in again.'), true);
      throw new DOMException('Session ended', 'AbortError');
    }
    throw new Error(`${code}: ${t('Request failed. Check the visible fields and retry.')}`);
  }
  return result;
};
s.refresh = async () => {
  const [sources, memory] = await Promise.all([s.api(`${s.brain}/sources`), s.api(`${s.brain}/memory`)]);
  s.sources = sources; s.memory = memory; s.packet = null; render();
};
s.notify = message;
async function bootstrap() {
  const session = await s.api('session');
  csrf = session.csrf_token;
  clearTimeout(timer);
  timer = setTimeout(() => { forget(); shell(false); message(t('Session ended. Sign in again.'), true); }, Math.max(0, session.expires_in * 1000));
  shell(true); await projects();
}
function shell(authenticated) {
  root.replaceChildren();
  const header = el('header'); add(header, el('h1', `WaveMind · ${t('Project memory')}`));
  for (const lang of ['RU', 'EN']) add(header, button(lang, () => s.run(async () => {
    language = lang.toLowerCase(); localStorage.setItem('brain-language', language); setLanguage(language);
    shell(Boolean(csrf)); if (csrf) await (s.brain ? s.refresh() : projects());
  }), true));
  if (authenticated) add(header, button('Sign out', () => s.run(async () => {
    try { await discardPreview(); await s.api('logout', {}); }
    finally { forget(); shell(false); }
  }), true));
  add(root, header);
  main = el('main'); messageNode = el('div', '', {id: 'message', role: 'status', 'aria-live': 'polite'});
  add(main, messageNode); add(root, main);
  note(main, 'D1 local pilot: plaintext storage for nonsecret materials. Python is required. Installation (D2), team deployment (D3), and real usefulness (D4) remain separate.');
  if (!authenticated) {
    const login = card(main, 'Project memory'); login.classList.add('login');
    note(login, 'Keep decisions, constraints and their sources ready for your next session.');
    const key = field(login, 'Owner key', {type: 'password'});
    const submit = () => s.run(async () => {
      const secret = key.value; key.value = '';
      await s.api('login', {secret}); await bootstrap();
    });
    key.addEventListener('keydown', event => { if (event.key === 'Enter') submit(); });
    add(login, button('Sign in', submit));
  }
  add(root, el('footer', 'WaveMind · D1 · local / локально'));
}
async function discardPreview() {
  importController?.abort(); importController = null;
  if (preview) {
    const old = preview; preview = null;
    await s.api(`${old.brain}/sources/commit`, {preview_id: old.data.id, accepted_ids: []});
  }
}
async function chooseBrain(brain) {
  await discardPreview(); generation++; pending.abort(); pending = new AbortController();
  s.brain = brain; s.packet = null; section = 'Sources and access'; await s.refresh();
}
async function projects() {
  const brains = await s.api('brains');
  render(brains);
}
function render(brains) {
  main.querySelector('.layout')?.remove();
  const layout = el('div', undefined, {class: 'layout'}), nav = el('nav', undefined, {'aria-label': t('Projects')}), body = el('div');
  for (const name of ['Projects', 'Known and current', 'Changes', 'Experience', 'Sources and access']) {
    const control = button(name, () => s.run(async () => {
      await discardPreview(); section = name;
      if (name === 'Projects') await projects(); else if (s.brain) render(); else await projects();
    }));
    if (section === name) control.setAttribute('aria-current', 'page');
    add(nav, control);
  }
  add(layout, nav, body); add(main, layout);
  if (section === 'Projects' || !s.brain) {
    const area = card(body, 'Projects');
    if (brains) {
      if (!brains.length) note(area, 'No memories yet. Create your first project.');
      for (const brain of brains) add(area, button(brain.title, () => s.run(() => chooseBrain(brain.id)), true));
    }
    let mode = 'personal';
    const modeStatus = el('p', 'personal');
    add(area, button('Personal project', () => { mode = 'personal'; modeStatus.textContent = mode; }), button('Client workspace', () => { mode = 'team'; modeStatus.textContent = mode; }), modeStatus);
    const title = field(area, 'Project name');
    add(area, button('Create memory', () => s.run(async () => {
      const brain = await s.api('brains', {title: title.value, mode}); await chooseBrain(brain.id);
    })));
    return;
  }
  add(body, el('small', s.brain, {'data-testid': 'brain-id', class: 'identifier'}));
  note(body, 'Model not connected. Entries below are owner-entered proposals, not AI extraction.');
  if (section === 'Sources and access') importPanel(body);
  renderPanel(body, section, s);
}
function importPanel(parent) {
  const area = card(parent, 'Preview');
  const name = field(area, 'Source name', {value: 'notes.txt'}), text = field(area, 'Source text', {rows: 5});
  const files = field(area, 'Files', {type: 'file'});
  const update = field(area, 'Update source', {options: [['', 'New source'], ...s.sources.map(x => [x.id, x.title])]});
  const audience = field(area, 'Audience', {options: [['private', 'Only you'], ['selected', 'Selected identities'], ['members', 'All live members (including future members)']]});
  const readers = field(area, 'Reader identities, one per line', {rows: 2});
  update.onchange = () => { audience.disabled = Boolean(update.value); readers.disabled = Boolean(update.value); };
  const output = el('div', undefined, {'data-testid': 'preview'}); add(area, output);
  const encode = bytes => { let binary = ''; for (const byte of bytes) binary += String.fromCharCode(byte); return btoa(binary); };
  const start = button('Preview', () => s.run(async () => {
    await discardPreview();
    const generationAtStart = generation;
    importController = new AbortController(); start.disabled = true;
    try {
      const uploads = [];
      if (update.value && Number(Boolean(text.value)) + files.files.length !== 1) throw new Error(t('An update accepts exactly one pasted text or one file.'));
      if (text.value) uploads.push({name: name.value, content_base64: encode(new TextEncoder().encode(text.value)), source_id: update.value || null});
      for (const file of files.files) {
        if (file.size > 10 * 1024 * 1024) throw new Error('10 MiB per file');
        uploads.push({name: file.name, content_base64: encode(new Uint8Array(await file.arrayBuffer())), source_id: update.value || null});
      }
      const initialReaders = update.value || audience.value === 'members' ? null : audience.value === 'private' ? [] : lines(readers);
      const data = await s.api(`${s.brain}/sources/preview`, {files: uploads, new_source_readers: initialReaders}, importController.signal);
      if (generationAtStart !== generation) return;
      preview = {brain: s.brain, data}; output.replaceChildren();
      add(output, el('p', t('Data is not sent to an external model')));
      const accepted = [];
      for (const file of data.files) {
        const row = card(output, file.name || file.title || file.id);
        add(row, el('span', file.status, {class: 'badge'}));
        if (file.error) add(row, el('p', typeof file.error === 'string' ? file.error : file.error.code));
        if (file.preview_text) add(row, el('blockquote', file.preview_text));
        const access = file.access || data.new_source_access;
        note(row, access.mode === 'all_live_members' ? 'All live members (including future members)' : access.readers.length ? access.readers.join(', ') : 'Only you');
        if (file.status !== 'error') accepted.push([file.id, check(row, file.name || file.id, true)]);
      }
      add(output, button('Save source', () => s.run(async () => {
        if (!preview) return;
        const saved = await s.api(`${preview.brain}/sources/commit`, {preview_id: preview.data.id, accepted_ids: accepted.filter(x => x[1].checked).map(x => x[0])});
        preview = null; await s.refresh(); message(t(saved.sources.length ? 'Source saved' : 'Import cancelled'));
      })));
    } finally { start.disabled = false; importController = null; }
  }));
  add(area, start, button('Cancel import', () => s.run(async () => {
    await discardPreview(); output.replaceChildren(); message(t('Import cancelled'));
  }), true));
  note(area, 'Cancellation discards a received preview. An interrupted request may leave an uncommitted draft until its 15-minute expiry; it is never saved automatically.');
}

shell(false);
// An absent cookie is an ordinary first-use state, not an automatic owner re-login.
bootstrap().catch(error => { if (error.name !== 'AbortError' && csrf) message(error.message, true); });
window.addEventListener('pagehide', () => {
  if (preview && csrf) fetch(`/brain/api/${preview.brain}/sources/commit`, {method: 'POST', keepalive: true, credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-Brain-CSRF': csrf}, body: JSON.stringify({preview_id: preview.data.id, accepted_ids: []})}).catch(() => {});
  importController?.abort();
});
