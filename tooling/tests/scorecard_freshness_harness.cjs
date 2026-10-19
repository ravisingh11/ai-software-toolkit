// Exercise the shipped inline script with controlled transport and lifecycle events.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const base = input.baseline;
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function fixture() {
  const events = {}, docEvents = {}, timers = new Map(), intervals = new Map(), calls = [];
  let next = 1, assigned;
  const panel = {dataset: {snapshot: JSON.stringify(base)}};
  const status = {textContent: 'Freshness not checked'};
  const refresh = {addEventListener: (_, fn) => { refresh.click = fn; }};
  const document = {hidden: false, getElementById: id => ({'snapshot-freshness': panel,
    'snapshot-freshness-status': status, 'snapshot-refresh': refresh})[id],
    addEventListener: (event, fn) => { docEvents[event] = fn; }};
  const window = {location: {href: 'https://example.test/repo/?other=1#size-title',
    assign: url => { assigned = url; }}, addEventListener: (event, fn) => { events[event] = fn; }};
  vm.runInNewContext(input.script, {document, window, URL, AbortController, Date,
    setTimeout: fn => { const id = next++; timers.set(id, fn); return id; },
    clearTimeout: id => timers.delete(id),
    setInterval: fn => { const id = next++; intervals.set(id, fn); return id; },
    clearInterval: id => intervals.delete(id),
    fetch: (url, options) => new Promise((resolve, reject) => calls.push({url, options, resolve, reject}))});
  const response = (value, code = 200, contentType = 'application/json') => ({status: code,
    headers: {get: () => contentType}, json: async () => value});
  return {panel, status, refresh, document, window, events, docEvents, timers, intervals, calls,
    response, assigned: () => assigned};
}
async function outcome(value, expected, code = 200, contentType) {
  const f = fixture();
  f.calls[0].resolve(f.response(value, code, contentType)); await flush();
  assert.equal(f.panel.dataset.freshness, expected);
  return f;
}
(async () => {
  const current = await outcome(base, 'current');
  assert.match(current.status.textContent, /does not verify current main/);
  const newer = {...base, source_run_id: base.source_run_id + 1,
    subject_digest: 'sha256:' + 'b'.repeat(64), published_at: '2026-10-20T12:00:00Z'};
  await outcome(newer, 'stale');
  await outcome({...base, source_run_id: base.source_run_id - 1, published_at: newer.published_at}, 'unknown');
  await outcome({...base, source_run_attempt: 2, published_at: newer.published_at}, 'stale');
  await outcome({...base, published_at: newer.published_at}, 'stale');
  await outcome({...base, source_run_id: base.source_run_id - 1,
    source_run_created_at: '2026-10-17T12:00:00Z'}, 'unknown');
  for (const bad of [null, [], {}, {...base, version: 2}, {...base, operation: 'release'},
    {...base, repository: 'evil/repo'}, {...base, subject_digest: 'sha256:bad'},
    {...base, subject_digest: newer.subject_digest, published_at: newer.published_at},
    {...base, source_run_id: true}, {...base, source_run_id: Number.MAX_SAFE_INTEGER + 1},
    {...base, source_run_attempt: 0}, {...base, source_run_created_at: '2026-02-30T12:00:00Z'},
    {...base, published_at: 'bad'}, {...base, published_at: '2026-10-17T12:00:00Z'}]) {
    await outcome(bad, 'unknown');
  }
  await outcome(base, 'unknown', 500);
  await outcome(base, 'unknown', 200, 'text/html');
  const offline = fixture(); offline.calls[0].reject(new Error('offline')); await flush();
  assert.equal(offline.panel.dataset.freshness, 'unknown');
  const timeout = fixture(); [...timeout.timers.values()][0](); await flush();
  assert.equal(timeout.panel.dataset.freshness, 'unknown');
  assert.equal(timeout.calls[0].options.signal.aborted, true);
  timeout.calls[0].resolve(timeout.response(base)); await flush();
  assert.equal(timeout.panel.dataset.freshness, 'unknown');
  const f = fixture();
  assert.equal(f.calls[0].options.cache, 'no-store');
  assert.equal(f.calls[0].options.mode, 'same-origin');
  assert.equal(f.calls[0].options.redirect, 'error');
  assert.match(f.calls[0].url, /^https:\/\/example.test\/repo\/scorecard.json\?_snapshot_check=/);
  f.events.focus(); f.events.pageshow(); [...f.intervals.values()][0]();
  assert.equal(f.calls.length, 1);
  f.document.hidden = true; f.docEvents.visibilitychange();
  assert.equal(f.intervals.size, 0); assert.equal(f.calls[0].options.signal.aborted, true);
  f.events.focus(); assert.equal(f.calls.length, 1);
  f.document.hidden = false; f.docEvents.visibilitychange();
  assert.equal(f.calls.length, 2);
  f.calls[1].resolve(f.response(newer)); await flush();
  f.calls[0].resolve(f.response(base)); await flush();
  assert.equal(f.panel.dataset.freshness, 'stale');
  f.events.focus(); f.calls[2].reject(new Error('offline')); await flush();
  assert.equal(f.panel.dataset.freshness, 'stale'); assert.match(f.status.textContent, /recheck failed/);
  f.events.focus(); f.calls[3].resolve(f.response(base)); await flush();
  assert.equal(f.panel.dataset.freshness, 'stale');
  f.events.pagehide(); assert.equal(f.intervals.size, 0);
  f.events.pageshow(); assert.equal(f.calls.length, 5);
  let prevented = false; f.refresh.click({preventDefault: () => { prevented = true; }});
  assert.ok(prevented); const target = new URL(f.assigned());
  assert.equal(target.origin, 'https://example.test'); assert.equal(target.pathname, '/repo/');
  assert.equal(target.hash, '#size-title'); assert.equal(target.searchParams.get('other'), '1');
  assert.ok(target.searchParams.get('_snapshot_refresh'));
  console.log('Freshness behavior: current, newer, attempts, malformed, offline, timeout, lifecycle, races and refresh passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
