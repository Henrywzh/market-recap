// The POSITIONING page's trend followers, rendered under node against a small
// fake DOM and a stub ECharts. The checks: the model position and its answer
// sentences, the flows table, the sign of the dollar ranges, a missing reading
// that shows a dash rather than a throw, the trend check, and the blackout card
// moved to the end of the page.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import renderPositioning, { flowText, scenarioSentences } from '../../web/js/tabs/positioning.js';

class FakeNode {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this.style = {};
    this.classList = { add() {} };
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  querySelectorAll() { return []; }
  get isConnected() { return true; }
}

const fakeDocument = () => ({
  createElement: (tag) => new FakeNode(tag),
  createElementNS: (ns, tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
  documentElement: new FakeNode('html'),
  body: { contains: () => true },
});

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

// Installs the fake DOM, ECharts and the frame clock, runs the test, then lets
// any scheduled drawing finish before the globals are restored.
async function withBrowser(run) {
  const saved = {
    document: globalThis.document, window: globalThis.window, getComputedStyle: globalThis.getComputedStyle,
    requestAnimationFrame: globalThis.requestAnimationFrame,
  };
  globalThis.document = fakeDocument();
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
  globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
  globalThis.window = { echarts: { init: () => ({ setOption() {}, resize() {}, dispose() {}, on() {}, getModel() {} }) } };
  try {
    await run();
    await flush();
    await flush();
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
}

function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(textOf)].filter(Boolean).join(' ');
}

// Every node below `node` (inclusive) that satisfies the test, in document order.
function all(node, test) {
  const found = test(node) ? [node] : [];
  for (const child of node.children || []) if (child.nodeType === 1) found.push(...all(child, test));
  return found;
}

const hasClass = (node, name) => (node.className || '').split(/\s+/).includes(name);

const BAD = /NaN|undefined|\[object Object\]/;

// Weekdays from 2025 with a gentle rise, as ISO dates and values.
function series(count, start = 100, step = 0.4) {
  const dates = [];
  const day = new Date(Date.UTC(2025, 0, 2));
  while (dates.length < count) {
    if (day.getUTCDay() % 6 !== 0) dates.push(day.toISOString().slice(0, 10));
    day.setUTCDate(day.getUTCDate() + 1);
  }
  return { dates, values: dates.map((_, i) => Number((start + i * step).toFixed(2))) };
}

// Position changes by move (in sigmas) and sessions: a flat five sessions adds 6 points, a 2-sigma fall cuts 40.
const CHANGE = { 1: { '-2': -14, '-1': -7, 0: 1, 1: 7, 2: 15 }, 5: { '-2': -40, '-1': -18, 0: 6, 1: 20, 2: 38 } };

function scenarioRows() {
  return [1, 5].flatMap((sessions) => [-2, -1, 0, 1, 2].map((moveSd) => {
    const change = CHANGE[sessions][moveSd];
    return {
      sessions, move_sd: moveSd, move_pct: moveSd * sessions * 0.8, close: 7659.44,
      position: 62 + change, position_change: change, vc_change: -moveSd * 2,
      flow_bn_low: (change / 100) * 80, flow_bn_high: (change / 100) * 160,
    };
  }));
}

function trendFixture({ scenarios = scenarioRows(), position = 62, unavailable = false } = {}) {
  const position_history = series(300, 40, 0.1);
  const vol_history = series(300, 50, 0.05);
  const close = series(300, 7000, 2);
  return {
    key: 'SPX', label: 'S&P 500', symbol: '^GSPC', as_of: '2026-10-16',
    close: 7659.44, score: 1, state: 'LONG',
    flips: [{ lookback: '1M', sessions: 21, return_pct: 0.28, signal: 1, flip_level: 7650.5, distance_pct: -0.12 }],
    averages: [{ window: 50, level: 7706.42, distance_pct: 0.61, above: false }],
    history: { score: series(300, 0, 0.01), close },
    scorecard_history: { dates: [], score: [], close: [] },
    model: {
      position, vol_60d: 12.1, vol_20d: 10.2, leverage: 1.24, vol_control: 55.1,
      room: { to_max_long: position === null ? null : 100 - position, to_max_short: position === null ? null : position + 100 },
      scenarios, flow_assumption_bn: [80, 160],
      history: { position: position_history, vol_control: vol_history },
    },
    ...(unavailable ? { model: undefined } : {}),
  };
}

function payload(overrides = {}) {
  return {
    as_of: '2026-10-16',
    trend: [trendFixture()],
    short_interest: { unavailable: 'FINRA not built in this test' },
    blackout: { unavailable: 'not built in this test' },
    insiders: { unavailable: 'not built in this test' },
    lookbacks: { '1M': 21, '3M': 63, '6M': 126, '12M': 252 },
    index_put_call: null,
    trend_check: {
      etf: 'DBMF', window: 63, dates: ['2026-10-14', '2026-10-15', '2026-10-16'], beta: [0.48, 0.5, 0.52],
      position: [60, 61, 62], as_of: '2026-10-16', beta_now: 0.52, corr_with_model: 0.42, corr_levels: 0.55,
    },
    ...overrides,
  };
}

async function render(data) {
  const root = new FakeNode('main');
  await withBrowser(() => { renderPositioning(root, data); });
  return root;
}

test('the trend card gives the model position, the answer sentences and the flows table, with no bad figures', async () => {
  const root = new FakeNode('main');
  await withBrowser(() => { renderPositioning(root, payload()); });
  const text = textOf(root);
  assert.match(text, /\+62% of max long/);
  assert.match(text, /room to max long: 38 pts/);
  assert.match(text, /If the S&P 500 is flat for 5 sessions, the model ADDS 6 pts \(calmer volatility\): about \$4\.8–9\.6bn of buying\./);
  assert.match(text, /A 2σ drop over 5 sessions makes the model CUTS 40 pts: about \$32–64bn of selling\./);
  assert.doesNotMatch(text, BAD);
  const flows = all(root, (n) => hasClass(n, 'pos-flows'))[0];
  assert.ok(flows, 'the flows table is drawn');
  const body = all(flows, (n) => n.tagName === 'TBODY')[0];
  assert.equal(body.children.length, 5, 'five moves: −2σ, −1σ, flat, +1σ, +2σ');
});

test('dollar ranges carry the sign of the buying or selling and dash when there is no estimate', () => {
  assert.equal(flowText(4.8, 9.6), '+$4.8–9.6bn');
  assert.equal(flowText(-32, -64), '-$32–64bn');
  assert.equal(flowText(0, 0), '$0bn');
  assert.equal(flowText(null, null), '—');
  assert.equal(flowText(undefined, 3), '—');
});

test('a missing scenario gives no sentence and a dash, never a throw or a bad figure', async () => {
  const sparse = trendFixture({ scenarios: scenarioRows().filter((r) => !(r.sessions === 5 && r.move_sd === 2)) });
  assert.deepEqual(scenarioSentences(sparse), []);
  const data = payload({ trend: [trendFixture({ scenarios: [], position: null })] });
  const root = await render(data);
  const text = textOf(root);
  assert.match(text, /No scenario reading for this index\./);
  assert.match(text, /—/);
  assert.doesNotMatch(text, BAD);
});

test('the blackout card is last, under its convention title, with the convention note', async () => {
  const data = payload({
    blackout: { unavailable: undefined, as_of: '2026-10-16', now_pct: 40, share_pct: [], dates: [], before_days: 30,
      after_days: 2, projected: 3, weight_covered_pct: 80, scheduled: 10, missing: 1, momentum: {} },
  });
  const root = await render(data);
  const titles = all(root, (n) => hasClass(n, 'section-title')).map((n) => n.textContent);
  assert.equal(titles.at(-1), 'BUYBACK BLACKOUT');
  assert.ok(titles.indexOf('TREND FOLLOWERS') < titles.indexOf('BUYBACK BLACKOUT'));
  const text = textOf(root);
  assert.match(text, /S&P 500 WEIGHT IN A BUYBACK BLACKOUT · ESTIMATED BY CONVENTION/);
  assert.match(text, /A convention, not data: no company publishes its window/);
});

test('the trend check states its correlation, or the reason it is missing', async () => {
  const root = await render(payload());
  const text = textOf(root);
  assert.match(text, /CHECK: LISTED TREND ETF \(DBMF\) EQUITY BETA · 63-SESSION/);
  assert.match(text, /beta now 0\.52 as of 2026-10-16 · corr with the model: levels 0\.55 · quarterly changes 0\.42/);
  assert.doesNotMatch(text, BAD);

  const missing = await render(payload({ trend_check: { unavailable: 'Yahoo returned 502' } }));
  const missingText = textOf(missing);
  assert.match(missingText, /Not built this session: Yahoo returned 502\./);
  assert.doesNotMatch(missingText, BAD);
});
