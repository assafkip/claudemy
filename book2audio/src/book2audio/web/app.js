'use strict';
// Everything shown comes from h()/textContent, never from innerHTML: book titles are untrusted text.
const TOKEN = new URLSearchParams(location.search).get('t') || '';
const $ = (id) => document.getElementById(id);
const CLOUD = {google: 'Google Cloud', elevenlabs: 'ElevenLabs'};
const PROVIDER = {google: 'Google', elevenlabs: 'ElevenLabs', anthropic: 'Anthropic'};
const KEY_HELP = {
  google: 'In the Google Cloud console, create an API key that is allowed to use "Cloud Text-to-Speech".',
  elevenlabs: 'On elevenlabs.io open your profile, then "API keys", and create one.',
  anthropic: 'On console.anthropic.com open "API keys" and create one.',
};
const ENGINE_NOTE = {
  piper: 'Free. Everything stays on this computer.',
  say: 'Free. Built into your Mac. Everything stays on this computer.',
  google: 'Paid. Your book\'s text is sent to Google Cloud.',
  elevenlabs: 'Paid. Your book\'s text is sent to ElevenLabs.',
};

const S = {
  keys: {}, engines: [], claudeModels: [], book: null, picked: new Set(), title: '', author: '',
  engine: 'piper', model: '', voice: '', language: 'en-US', cat: null,
  claude: {on: false, mode: 'faithful', model: 'claude-sonnet-5-5', condense: false},
  prices: {}, est: null, estError: '', estBusy: false, run: {status: 'idle'}, setup: null, folder: '', platform: '',
  sample: null, audio: null, timers: {},
};

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}
const fill = (el, ...kids) => { el.replaceChildren(...kids.flat().filter((k) => k != null && k !== false)); };
const fmt = (n) => Math.round(n).toLocaleString();
const money = (n) => '$' + (n < 0.1 && n > 0 ? n.toFixed(4) : n.toFixed(2));
const hm = (min) => { min = Math.round(min); return min >= 60 ? `${Math.floor(min / 60)}h ${String(min % 60).padStart(2, '0')}m` : `${min} min`; };
const secs = (s) => (s >= 3600 ? hm(s / 60) : s >= 90 ? `${Math.round(s / 60)} min` : `${Math.round(s)} s`);
const later = (name, ms, fn) => { clearTimeout(S.timers[name]); S.timers[name] = setTimeout(fn, ms); };

async function api(method, path, body, raw) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: {'X-B2A-Token': TOKEN, ...(body ? {'Content-Type': 'application/json'} : {})},
      body: raw || (body ? JSON.stringify(body) : undefined),
    });
  } catch (e) {
    stopped();
    throw new Error('Book2Audio is not running any more. Start it again from its launcher.');
  }
  if (res.ok && (res.headers.get('content-type') || '').startsWith('audio/')) return res;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(res.status === 403 ? 'This page is no longer allowed to talk to the program. Close it and start Book2Audio again.' : data.error || 'Something went wrong.');
  return data;
}

function stopped() {
  document.body.replaceChildren(h('main', {style: 'max-width:560px;margin:60px auto;padding:0 16px'},
    h('h1', {}, 'Book2Audio has stopped'),
    h('p', {}, 'You can close this tab. To use it again, start Book2Audio from its launcher.')));
}

// ---------------------------------------------------------------------------------------------- start
async function init() {
  const st = await api('GET', '/api/state');
  S.keys = st.keys; S.engines = st.engines; S.claudeModels = st.claude_models; S.folder = st.folder;
  S.platform = st.platform; S.prices = st.settings.prices || {}; S.run = st.run;
  const c = st.settings.choice || {};
  if (S.engines.some((e) => e.id === c.engine)) S.engine = c.engine;
  S.model = c.model || ''; S.voice = c.voice || ''; S.language = c.language || 'en-US';
  Object.assign(S.claude, {on: !!c.claude_on, mode: c.claude_mode || 'faithful', condense: !!c.claude_condense});
  if (st.claude_models.some((m) => m.id === c.claude_model)) S.claude.model = c.claude_model;
  if (st.book) takeBook(st.book, st.selection);
  renderAll();
  loadSetup();
  loadVoices();
  if (S.run.status === 'running') poll();
}

function takeBook(book, selection) {
  S.book = book; S.title = book.title; S.author = book.author;
  S.picked = new Set(selection && selection.length ? selection : book.chapters.filter((c) => !c.skip && !c.empty).map((c) => c.i));
}

async function loadSetup() {
  try { S.setup = (await api('GET', '/api/setup')).items; } catch (e) { S.setup = []; }
  renderSetup();
}

async function loadVoices() {
  try {
    S.cat = await api('GET', `/api/voices?engine=${S.engine}&language=${encodeURIComponent(S.language)}`);
  } catch (e) { S.cat = {voices: [], models: [], languages: [], note: e.message}; }
  const ids = S.cat.voices.map((v) => v.id);
  if (!ids.includes(S.voice)) S.voice = ids[0] || '';
  const models = S.cat.models.map((m) => m.id);
  if (models.length && !models.includes(S.model)) S.model = models[0];
  if (!models.length) S.model = '';
  renderVoice();
  changed();
}

function changed() { // after any choice: remember it, and work out the summary again
  later('save', 700, () => api('POST', '/api/settings', {prices: S.prices, choice: {
    engine: S.engine, model: S.model, voice: S.voice, language: S.language, claude_on: S.claude.on,
    claude_mode: S.claude.mode, claude_model: S.claude.model, claude_condense: S.claude.condense}}).catch(() => {}));
  S.est = null; S.estError = ''; S.estBusy = !!(S.book && S.picked.size && S.voice);
  renderSummary();
  later('est', 250, estimate);
}

const payload = () => ({
  book: S.book.id, chapters: [...S.picked].sort((a, b) => a - b), engine: S.engine, model: S.model, voice: S.voice,
  language: S.language, title: S.title, author: S.author, price_per_1k: S.prices[S.engine] ?? null,
  claude: {...S.claude},
});

let estSeq = 0;
async function estimate() {
  if (!(S.book && S.picked.size && S.voice)) { S.estBusy = false; renderSummary(); return; }
  const seq = ++estSeq;
  try {
    const est = await api('POST', '/api/estimate', payload());
    if (seq !== estSeq) return;
    S.est = est; S.estError = '';
  } catch (e) { if (seq !== estSeq) return; S.est = null; S.estError = e.message; }
  S.estBusy = false;
  renderSummary();
}

// ---------------------------------------------------------------------------------------------- rendering
function renderAll() { renderSetup(); renderBook(); renderChapters(); renderVoice(); renderClaude(); renderPrice(); renderSummary(); }

function renderSetup() {
  const body = $('setup-body'), chip = $('chip');
  if (!S.setup) return;
  const bad = S.setup.filter((i) => !i.ok && i.required);
  chip.hidden = false;
  chip.className = 'chip ' + (bad.length ? 'bad' : 'ok');
  chip.textContent = bad.length ? 'Needs attention' : 'Ready';
  if (bad.length) $('setup').open = true;
  fill(body, S.setup.map((i) => h('div', {class: 'check ' + (i.ok ? 'ok' : i.required ? 'todo' : 'optional')},
    h('span', {class: 'mark', 'aria-hidden': 'true'}, i.ok ? '✓' : i.required ? '!' : '–'),
    h('div', {},
      h('strong', {}, i.label), ' ', h('span', {class: 'muted'}, i.detail),
      i.fix ? fixBlock(i.fix) : null))));
}

function fixBlock(text) {
  const [intro, ...rest] = text.split('\n\n');
  const cmd = rest.join('\n\n');
  return h('div', {},
    h('div', {class: 'help'}, intro),
    cmd ? h('pre', {class: 'fix'}, cmd) : null,
    cmd ? h('button', {type: 'button', onclick: async (ev) => {
      try { await navigator.clipboard.writeText(cmd); ev.target.textContent = 'Copied'; } catch (e) { ev.target.textContent = 'Select the text above and copy it'; }
    }}, 'Copy') : null);
}

function renderBook() {
  const b = S.book, box = $('book');
  box.hidden = !b;
  $('s-chapters').hidden = $('s-voice').hidden = $('s-claude').hidden = !b;
  if (!b) return;
  fill(box, h('div', {class: 'bookrow'},
    b.cover ? h('img', {src: b.cover, alt: 'Book cover'}) : null,
    h('div', {class: 'fields'},
      h('label', {}, 'Title', h('input', {type: 'text', value: S.title, oninput: (e) => { S.title = e.target.value; changed(); }})),
      h('label', {}, 'Author', h('input', {type: 'text', value: S.author, oninput: (e) => { S.author = e.target.value; changed(); }})),
      h('div', {class: 'muted'}, `File: ${b.file}. Choose another book by dropping it above.`))));
}

function renderChapters() {
  const b = S.book;
  if (!b) return;
  fill($('chapters'), b.chapters.map((c) => {
    const id = 'ch' + c.i;
    return h('div', {class: 'chapter' + (c.skip || c.empty ? ' skipped' : '')},
      h('input', {type: 'checkbox', id, checked: S.picked.has(c.i), disabled: c.empty, onchange: (e) => {
        e.target.checked ? S.picked.add(c.i) : S.picked.delete(c.i); countChapters(); changed();
      }}),
      h('label', {for: id}, c.title || '(untitled)',
        (c.skip || c.empty) ? h('span', {class: 'why'}, ` — left out: ${c.empty ? 'no text' : c.skip}`) : null),
      h('span', {class: 'muted'}, `${fmt(c.words)} words`));
  }));
  countChapters();
}
function countChapters() {
  $('chapter-count').textContent = `${S.picked.size} of ${S.book.chapters.length} chapters ticked`;
}

let priceFor = null;
function renderVoice() {
  const cat = S.cat;
  fill($('engines'), S.engines.map((e) => h('label', {class: 'engine'},
    h('input', {type: 'radio', name: 'engine', value: e.id, checked: e.id === S.engine, onchange: () => {
      S.engine = e.id; S.voice = ''; S.model = ''; S.sample = null; stopAudio();
      S.cat = {voices: [], models: [], languages: [], note: 'Loading the voice list…'};
      renderVoice(); loadVoices();
    }}), ' ', h('strong', {}, e.label), h('small', {}, ENGINE_NOTE[e.id] || ''))));
  const cloud = CLOUD[S.engine];
  $('cloud-notice').hidden = !cloud;
  $('local-note').hidden = !!cloud;
  if (cloud) {
    fill($('cloud-notice'), h('strong', {}, `⚠ Your book's text leaves this computer.`),
      `It will be sent to ${cloud} over the internet to make the audio, and ${cloud} charges you for it. ` +
      `Only use this for books you are allowed to share with ${cloud}.`);
  } else {
    fill($('local-note'), '✓ Your book stays on this computer. Nothing is sent anywhere.');
  }
  fill($('keybox'), cloud ? keyBox(S.engine) : null);
  if (priceFor !== S.engine) { priceFor = S.engine; renderPrice(); }
  if (!cat) return;
  $('model-field').hidden = !cat.models.length;
  fill($('model'), cat.models.map((m) => h('option', {value: m.id, selected: m.id === S.model}, m.label)));
  $('language-field').hidden = !cat.languages.length;
  fill($('language'), cat.languages.map((l) => h('option', {value: l.id, selected: l.id === S.language}, l.label)));
  $('voice-note').hidden = !cat.note;
  $('voice-note').textContent = cat.note || '';
  fill($('voices'), cat.voices.map((v) => h('div', {class: 'voice'},
    h('label', {}, h('input', {type: 'radio', name: 'voice', value: v.id, checked: v.id === S.voice, onchange: () => {
      S.voice = v.id; changed();
    }}), ' ', h('strong', {}, v.name), v.detail ? h('span', {class: 'muted'}, ` — ${v.detail}`) : null),
    h('button', {type: 'button', 'aria-label': `Hear a sample of ${v.name}`, onclick: () => askSample(v)}, '▶ Sample'))));
  $('voices').hidden = !cat.voices.length;
  fill($('piper-get'), S.engine === 'piper' && cat.suggested ? piperGet(cat) : null);
  renderSample();
}

function piperGet(cat) {
  const have = new Set(cat.voices.map((v) => v.id));
  const busy = S.installing;
  return h('div', {},
    h('h3', {}, cat.voices.length ? 'Get another free voice' : 'Get a free voice'),
    h('p', {class: 'help'}, 'Each voice is a download of roughly 60 MB from the Piper voice library. Nothing from your book is sent.'),
    h('div', {class: 'row'}, cat.suggested.filter((n) => !have.has(n)).map((n) =>
      h('button', {type: 'button', disabled: !!busy, onclick: () => installVoice(n)}, busy === n ? 'Downloading…' : `Download ${n}`))));
}
async function installVoice(name) {
  S.installing = name; renderVoice();
  try { await api('POST', '/api/piper/install', {voice: name}); S.voice = name; loadSetup(); }
  catch (e) { alert(e.message); }
  S.installing = null; loadVoices();
}

function keyBox(provider) {
  const k = S.keys[provider] || {}, name = {google: 'Google', elevenlabs: 'ElevenLabs', anthropic: 'Anthropic'}[provider];
  if (k.has || (provider === 'google' && S.keys.gcloud)) {
    return h('div', {class: 'keybox'},
      h('span', {class: 'badge local'}, k.typed ? `✓ ${name} key added (kept in memory only)` :
        k.environment ? `✓ ${name} key found on this computer` : '✓ Signed in with the gcloud tool'),
      k.typed ? h('button', {type: 'button', class: 'link', onclick: () => setKey(provider, '')}, 'Remove it') : null);
  }
  const input = h('input', {type: 'password', autocomplete: 'off', spellcheck: 'false', placeholder: `Paste your ${name} key here`, 'aria-label': `${name} key`});
  const use = () => setKey(provider, input.value, input);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') use(); });
  return h('div', {},
    h('div', {class: 'keybox'}, input, h('button', {type: 'button', onclick: use}, 'Use this key')),
    h('p', {class: 'help'}, `${KEY_HELP[provider]} The key is kept only while this program runs: it is never saved to a file or shown again.`),
    S.keyError && S.keyError.p === provider ? h('div', {class: 'msg bad'}, S.keyError.m) : null);
}
async function setKey(provider, key, input) {
  try {
    S.keys = (await api('POST', '/api/key', {provider, key})).keys; S.keyError = null;
    if (input) input.value = '';
  } catch (e) { S.keyError = {p: provider, m: e.message}; }
  renderVoice(); renderClaude(); loadSetup();
  if (provider === S.engine) loadVoices(); else changed();
}

function renderClaude() {
  $('claude-on').checked = S.claude.on;
  $('claude-body').hidden = !S.claude.on;
  document.querySelectorAll('input[name=cmode]').forEach((r) => { r.checked = r.value === S.claude.mode; });
  $('condense-field').hidden = S.claude.mode !== 'adapted';
  $('condense').checked = S.claude.condense;
  fill($('cmodel'), S.claudeModels.map((m) => h('option', {value: m.id, selected: m.id === S.claude.model}, m.label)));
  fill($('claude-key'), S.claude.on ? keyBox('anthropic') : null);
}

// ---------------------------------------------------------------------------------------------- samples
function stopAudio() { if (S.audio) { S.audio.pause(); S.audio = null; } }

async function askSample(v) {
  stopAudio();
  S.sample = {voice: v, busy: true};
  renderSample();
  try {
    const body = sampleBody(v);
    const q = await api('POST', '/api/sample/quote', body);
    S.sample = {voice: v, q, body};
    if (!q.paid || q.cached) return playSample();   // free or already saved: nothing to confirm
    renderSample();
  } catch (e) { S.sample = {voice: v, error: e.message}; renderSample(); }
}
const sampleBody = (v) => ({book: S.book.id, engine: S.engine, model: S.model, voice: v.id, language: S.language,
  price_per_1k: S.prices[S.engine] ?? null, chapter: [...S.picked].sort((a, b) => a - b)[0]});

async function playSample() {
  const s = S.sample;
  s.busy = true; s.playing = false; renderSample();
  try {
    const res = await api('POST', '/api/sample', {...s.body, quote: s.q.quote});
    const url = URL.createObjectURL(await res.blob());
    S.audio = new Audio(url);
    S.audio.onended = () => { s.playing = false; renderSample(); };
    await S.audio.play();
    Object.assign(s, {busy: false, playing: true, done: true});
  } catch (e) { Object.assign(s, {busy: false, error: e.message}); }
  renderSample();
}

function renderSample() {
  const box = $('samplebox'), s = S.sample;
  box.hidden = !s;
  if (!s) return;
  const name = s.voice.name;
  if (s.error) return fill(box, h('div', {class: 'msg bad'}, s.error), h('button', {type: 'button', onclick: () => { S.sample = null; renderSample(); }}, 'Close'));
  if (!s.q) return fill(box, `Getting a sample of ${name} ready…`);
  const q = s.q;
  const reading = h('q', {}, `“${q.text}”`);
  if (s.busy) return fill(box, `Making the sample of ${name}…`, reading);
  if (s.done) return fill(box, h('strong', {}, s.playing ? `Playing ${name}` : `Sample of ${name}`), reading,
    h('div', {class: 'row'}, h('button', {type: 'button', onclick: replay}, '▶ Play again (free)'),
      h('button', {type: 'button', class: 'link', onclick: () => { stopAudio(); S.sample = null; renderSample(); }}, 'Close')));
  const cost = `${fmt(q.units)} ${q.unit}` + (q.money != null ? ` (about ${money(q.money)})` : '');
  fill(box, h('strong', {}, `Sample of ${name}`), reading,
    h('p', {}, `This sends ${q.chars} characters to ${q.sent_to.join(' and ')} and costs about ${cost}. ` +
      (q.money == null ? 'Enter your price in the summary on the right to see it in dollars. ' : '') + 'Replaying it later is free.'),
    q.missing_key ? h('div', {class: 'msg bad'}, `Add your ${q.missing_key === 'google' ? 'Google' : 'ElevenLabs'} key first (above).`) : null,
    h('div', {class: 'row'}, h('button', {type: 'button', class: 'primary', disabled: !!q.missing_key, onclick: playSample}, `Play the sample (${cost})`),
      h('button', {type: 'button', onclick: () => { S.sample = null; renderSample(); }}, 'Not now')));
}
function replay() { stopAudio(); return playSample(); }

// ---------------------------------------------------------------------------------------------- summary and convert
// The summary has fixed slots so that typing in the price box is never interrupted by an update:
// #sum-card and #sum-after are redrawn on every change, #sum-price only when the engine changes.
function renderSummary() {
  const e = S.est, running = S.run.status === 'running';
  const card = [h('h2', {}, 'Summary')], after = [];
  if (!S.book) card.push(h('p', {class: 'muted'}, 'Choose a book to see what it will cost, how long it will take and where your text goes.'));
  else {
    if (S.estError) card.push(h('div', {class: 'msg bad'}, S.estError));
    else if (!S.picked.size) card.push(h('p', {class: 'muted'}, 'Tick at least one chapter.'));
    else if (!S.voice) card.push(h('p', {class: 'muted'}, 'Pick a voice.'));
    else if (!e) card.push(h('p', {class: 'muted'}, S.estBusy ? 'Working it out…' : ''));
    else { const c = summaryCard(e); card.push(...c.card); after.push(...c.after); }
    const partial = e && e.cached_chars > 0 && e.todo_chars > 0;
    after.push(h('button', {type: 'button', class: 'primary big', disabled: !(e && !running && !S.starting && !e.missing_key), onclick: convertClicked},
      running ? 'Converting…' : partial ? 'Continue where you left off' : 'Convert to audiobook'));
    if (e && e.missing_key && !running) after.push(h('p', {class: 'help'}, `Add your ${PROVIDER[e.missing_key]} key first.`));
    if (S.startError) after.push(h('div', {class: 'msg bad'}, S.startError));
    after.push(...runPanel());
  }
  fill($('sum-card'), card);
  fill($('sum-after'), after);
  renderRun();
}

function renderPrice() {
  const unit = S.engine === 'elevenlabs' ? 'credits' : 'characters';
  fill($('sum-price'), CLOUD[S.engine] ? [
    h('div', {class: 'field'}, h('span', {}, `Your price in US dollars per 1,000 ${unit}`),
      h('input', {type: 'text', inputmode: 'decimal', autocomplete: 'off', value: S.prices[S.engine] ?? '', style: 'width:8em', 'aria-label': `Price per 1,000 ${unit}`,
        oninput: (ev) => {
          const v = ev.target.value.trim().replace(',', '.'), n = Number(v);
          ev.target.setAttribute('aria-invalid', v !== '' && !(Number.isFinite(n) && n >= 0) ? 'true' : 'false');
          if (v === '') delete S.prices[S.engine]; else if (Number.isFinite(n) && n >= 0) S.prices[S.engine] = n; else return;
          changed();
          if (S.sample && S.sample.q && !S.sample.done) later('requote', 500, () => askSample(S.sample.voice));  // its cost line changed
        }})),
    h('p', {class: 'help'}, 'Your plan decides this. Look it up on the provider\'s pricing page. It is saved on this computer so you only type it once.')] : null);
}

function summaryCard(e) {
  const voiceName = (S.cat && S.cat.voices.find((v) => v.id === S.voice) || {}).name || S.voice;
  const engine = (S.engines.find((x) => x.id === S.engine) || {}).label || S.engine;
  const rows = [
    ['Voice', `${voiceName}`], ['Engine', engine],
    ['Where your text goes', h('span', {class: 'badge ' + (e.sent_to.length ? 'cloud' : 'local')},
      e.sent_to.length ? `Sent over the internet to ${e.sent_to.join(' and ')}` : 'Stays on this computer')],
    ['Characters', fmt(e.chars)], ['Audiobook length', 'about ' + hm(e.audio_minutes)],
    ['Time to make it', e.todo_chars ? 'about ' + hm(Math.max(1, e.voice_minutes)) + ' (a rough guess)' : 'nothing left to make'],
  ];
  if (e.cached_chars) rows.push(['Already made earlier', `${Math.round(100 * e.cached_chars / Math.max(1, e.cached_chars + e.todo_chars))}%`]);
  const cost = [];
  if (!e.paid) cost.push('Free');
  if (e.voice_paid) cost.push(`${fmt(e.units)} ${e.unit}` + (e.voice_money != null ? ` ≈ ${money(e.voice_money)}` : ''));
  if (e.claude) cost.push('Claude: ' + (e.claude.usd != null ? `about ${money(e.claude.usd)}` : 'price not known'));
  rows.push(['Cost', h('span', {}, ...cost.map((c) => h('div', {}, c)))]);
  const after = [];
  if (e.paid && e.total_money != null) after.push(h('p', {}, h('strong', {}, `Total: about ${money(e.total_money)}`)));
  if (e.sent_to.length) after.push(h('div', {class: 'notice'}, h('strong', {}, 'Your book\'s text will be sent to ' + e.sent_to.join(' and ') + '.')));
  return {card: [h('dl', {}, rows.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]))], after};
}

// What changes every second is drawn into #runinfo; the Stop button sits outside it, so a click never lands on a
// node that was replaced a moment ago.
function runPanel() {
  const r = S.run;
  if (!r || r.status === 'idle' || (S.book && r.book !== S.book.id && r.status !== 'running')) return [];  // another book's result
  const out = [h('div', {id: 'runinfo'})];
  if (r.status === 'running') {
    out.push(h('button', {type: 'button', onclick: () => api('POST', '/api/cancel', {}).then((x) => { S.run = x.run; renderRun(); }).catch((e) => alert(e.message))}, 'Stop'));
    out.push(h('p', {class: 'help'}, 'You can close this tab and come back: it keeps going as long as the Book2Audio window stays open.'));
  }
  return out;
}

function renderRun() {
  const el = $('runinfo');
  if (!el) return;
  const old = el.querySelector('.steps'), top = old ? old.scrollTop : 0;
  fill(el, runInfo(S.run));
  const steps = el.querySelector('.steps'), now = steps && steps.querySelector('.now');
  if (steps) steps.scrollTop = now ? Math.max(0, now.offsetTop - steps.clientHeight / 2) : top;
}

function runInfo(r) {
  const out = [];
  const label = r.message || '';
  if (r.status === 'running') {
    const wait = r.percent == null || r.stage === 'start';
    out.push(h('h3', {}, 'Working on it'));
    out.push(h('div', {class: 'bar' + (wait ? ' wait' : ''), role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': r.percent || 0},
      h('div', {style: `width:${r.percent || 0}%`})));
    out.push(h('div', {}, label + (r.percent != null ? ` (${r.percent}%)` : '')));
    out.push(h('div', {class: 'muted'}, `Running for ${secs(r.elapsed || 0)}` + (r.eta ? `, about ${secs(r.eta)} to go` : '')));
    if (r.titles && r.titles.length > 1) {
      out.push(h('ul', {class: 'steps'}, r.titles.map((t, i) => h('li', {class: i + 1 < r.index ? 'did' : i + 1 === r.index ? 'now' : 'todo'},
        t, i + 1 === r.index && r.chunks ? ` — part ${r.chunk} of ${r.chunks}` : ''))));
    }
  } else if (r.status === 'done') {
    out.push(h('div', {class: 'msg ok'}, h('strong', {}, '✓ Your audiobook is ready.'), h('div', {}, `${r.file}, about ${hm(r.minutes || 0)} long, ${r.chapters} chapter${r.chapters === 1 ? '' : 's'}.`)));
    out.push(h('div', {class: 'row'},
      r.has_output ? h('button', {type: 'button', onclick: () => api('POST', '/api/open-folder', {}).catch((e) => alert(e.message))}, 'Show in folder') : null,
      r.has_output ? h('a', {href: `/api/download?id=${r.book}&t=${encodeURIComponent(TOKEN)}`, download: r.file}, h('button', {type: 'button'}, 'Download the .m4b')) : null));
    out.push(h('p', {class: 'help'}, `Saved in ${S.folder}. Open the .m4b file with any audiobook app (for example Apple Books, VLC or Audiobookshelf).`));
  } else {
    out.push(h('div', {class: 'msg ' + (r.status === 'stopped' ? 'info' : 'bad')}, r.message));
  }
  return out;
}

function convertClicked() {
  const e = S.est;
  if (!e) return;
  if (!e.paid) return start();
  const dlg = $('confirm');
  const cost = [];
  if (e.voice_paid) cost.push(`${fmt(e.units)} ${e.unit} of ${e.sent_to[0]}` + (e.voice_money != null ? ` (about ${money(e.voice_money)})` : ''));
  if (e.claude) cost.push('the Claude clean-up' + (e.claude.usd != null ? ` (about ${money(e.claude.usd)})` : ''));
  fill(dlg, h('h2', {id: 'confirm-title'}, 'Start and pay?'),
    h('p', {}, `Your book's text will be sent to ${e.sent_to.join(' and ')} over the internet.`),
    h('p', {}, 'This will use ', h('strong', {}, cost.join(' and ')), '.',
      e.total_money != null ? h('span', {}, ' Total: ', h('strong', {}, `about ${money(e.total_money)}`), '.') : ' Enter your price in the summary to see it in dollars.'),
    e.cached_chars ? h('p', {class: 'help'}, 'Parts already made earlier are not paid for again.') : null,
    h('div', {class: 'row'}, h('button', {type: 'button', onclick: () => dlg.close()}, 'Not now'),
      h('button', {type: 'button', class: 'primary', onclick: () => { dlg.close(); start(); }}, 'Yes, convert my book')));
  dlg.showModal();
}

async function start() {
  S.startError = ''; S.starting = true; renderSummary();
  try {
    S.run = (await api('POST', '/api/convert', {...payload(), quote: S.est.quote})).run;
    poll();
  } catch (e) { S.startError = e.message; }
  S.starting = false; renderSummary();
}

let polling = false;
function poll() {
  if (polling) return;
  polling = true;
  const tick = async () => {
    try { S.run = (await api('GET', '/api/state')).run; } catch (e) { polling = false; return; }
    if (S.run.status === 'running') { renderRun(); setTimeout(tick, 1000); } else { polling = false; renderSummary(); changed(); }
  };
  tick();
}

// ---------------------------------------------------------------------------------------------- upload and wiring
async function upload(file) {
  const err = $('book-error');
  err.hidden = true;
  if (!/\.(epub|pdf)$/i.test(file.name)) { err.textContent = 'Please choose a book that ends in .epub or .pdf.'; err.hidden = false; return; }
  $('loading').hidden = false;
  try {
    const out = await api('POST', `/api/upload?name=${encodeURIComponent(file.name)}`, null, file);
    stopAudio(); S.sample = null; S.startError = '';
    if (!S.run || S.run.status !== 'running') S.run = {status: 'idle'};
    takeBook(out.book);
    renderAll();
    changed();
  } catch (e) { err.textContent = e.message; err.hidden = false; }
  $('loading').hidden = true;
}

function wire() {
  const drop = $('drop');
  $('file').addEventListener('change', (e) => { if (e.target.files[0]) upload(e.target.files[0]); e.target.value = ''; });
  ['dragenter', 'dragover'].forEach((n) => drop.addEventListener(n, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((n) => drop.addEventListener(n, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => { if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); });
  window.addEventListener('dragover', (e) => e.preventDefault());   // a missed drop must not navigate away
  window.addEventListener('drop', (e) => e.preventDefault());
  $('all').onclick = () => { S.picked = new Set(S.book.chapters.filter((c) => !c.empty).map((c) => c.i)); renderChapters(); changed(); };
  $('none').onclick = () => { S.picked = new Set(); renderChapters(); changed(); };
  $('model').onchange = (e) => { S.model = e.target.value; changed(); };
  $('language').onchange = (e) => { S.language = e.target.value; S.voice = ''; loadVoices(); };
  $('claude-on').onchange = (e) => { S.claude.on = e.target.checked; renderClaude(); changed(); };
  document.querySelectorAll('input[name=cmode]').forEach((r) => r.addEventListener('change', (e) => { S.claude.mode = e.target.value; renderClaude(); changed(); }));
  $('condense').onchange = (e) => { S.claude.condense = e.target.checked; changed(); };
  $('cmodel').onchange = (e) => { S.claude.model = e.target.value; changed(); };
  $('recheck').onclick = () => { fill($('setup-body'), h('p', {class: 'muted'}, 'Checking…')); loadSetup(); };
  $('quit').onclick = async () => {
    if (!confirm('Close Book2Audio? Anything already made stays saved.')) return;
    try { await api('POST', '/api/quit', {}); stopped(); } catch (e) { alert(e.message); }
  };
}

wire();
init().catch((e) => document.body.prepend(h('div', {class: 'msg bad', style: 'margin:16px'}, e.message)));
