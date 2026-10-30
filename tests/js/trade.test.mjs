import { test } from 'node:test';
import assert from 'node:assert/strict';
import { anchorScorecard, closeLevels, optionRange, priceLadder, sentimentScorecard, sizePosition, trendScorecard } from '../../web/js/trade-math.js';
import renderTrade from '../../web/js/tabs/trade.js';

test('levels are close-based and require the complete window', () => {
  const levels = closeLevels(Array.from({ length: 60 }, (_, i) => i + 1));
  assert.deepEqual(levels.twenty, { low: 40, high: 59 });
  assert.equal(levels.sixty, null);
  assert.deepEqual(closeLevels(Array.from({ length: 61 }, (_, i) => i + 1)).sixty, { low: 1, high: 60 });
  assert.equal(closeLevels([1, 2]).twenty, null);
  assert.equal(levels.moving[20], 50.5);
  assert.equal(levels.moving[200], null);
});

test('daily bars supply a dated gap, Wilder ATR and dollar liquidity only with coverage', () => {
  const dates = Array.from({ length: 21 }, (_, i) => `2026-09-${String(i + 1).padStart(2, '0')}`);
  const close = Array(21).fill(100);
  const ohlcv = { dates: dates.slice(1), close: Array(20).fill(100), open: Array(20).fill(102), high: Array(20).fill(104),
    low: Array(20).fill(99), volume: Array(20).fill(1000) };
  const levels = closeLevels(close, ohlcv, dates);
  assert.equal(levels.atr14, 5);
  assert.equal(levels.adv20, 100000);
  assert.equal(levels.gap.day, '2026-09-21');
  assert.ok(Math.abs(levels.gap.pct - 2) < 1e-10);
  assert.equal(levels.gap.filled_intraday, true);
  assert.equal(closeLevels(close, { ...ohlcv, volume: Array(20).fill(null) }, dates).adv20, null);
});

test('option range refuses stale or absent straddle snapshots', () => {
  const options = { snapshot_day: '2026-09-28', term: [{ days: 7, expiry: '2026-10-05', straddle_pct: 4 }] };
  assert.deepEqual(optionRange(options, 100, '2026-09-28'), {
    expiry: '2026-10-05', days: 7, move_pct: 4, lower: 96, upper: 104, snapshot_day: '2026-09-28',
  });
  assert.equal(optionRange(options, 100, '2026-09-29'), null);
  assert.equal(optionRange({ ...options, term: [] }, 100, '2026-09-28'), null);
});

test('sizing honors both risk and notional caps and rejects invalid stops', () => {
  assert.equal(sizePosition({ account: 10000, riskPct: 1, entry: 100, stop: 95, maxPct: 10 }).shares, 10);
  assert.equal(sizePosition({ account: 10000, riskPct: 1, entry: 100, stop: 95, maxPct: 100 }).shares, 20);
  assert.equal(sizePosition({ account: '10000', riskPct: '1', entry: '100', stop: '95', maxPct: '20' }).shares, 20);
  assert.equal(sizePosition({ account: 10000, riskPct: 1, entry: 100, stop: 100 }), null);
  assert.equal(sizePosition({ account: 10000, riskPct: 1, entry: 100, stop: 105, side: 'short' }).shares, 20);
  assert.equal(sizePosition({ account: 10000, riskPct: 1, entry: 100, stop: 95, side: 'short' }), null);
  assert.deepEqual(sizePosition({ account: 10000, riskPct: 1, entry: 100, stop: 95, maxPct: 100,
    advUsd: 50000, participationPct: 1, spreadBps: 10 }), {
    shares: 5, notional: 500, riskBudget: 100, plannedLoss: 25, perShareRisk: 5,
    spreadCost: 0.5, cappedBy: 'liquidity',
  });
});

test('scorecard enters the next close, waits for outcomes and avoids overlapping same-state windows', () => {
  const result = anchorScorecard({ exposure: [1, 1, 1, 1, 1, 1], spy: [1, 100, 110, 120, 130, 140] }, [2]);
  const on = result.find((r) => r.label === 'RISK-ON');
  assert.equal(on.count, 1);
  assert.ok(Math.abs(on.mean_pct - 20) < 1e-10);
  assert.equal(on.baseline_count, 1);
  assert.equal(on.baseline_pct, on.mean_pct);
  assert.equal(on.difference_pct, 0);
  assert.equal(result.find((r) => r.label === 'RISK-OFF').hit_rate, null);
  assert.equal(trendScorecard({ scorecard_history: { dates: ['1', '2', '3', '4', '5', '6'],
    score: [1, 1, 1, 1, 1, 1], close: [1, 100, 110, 120, 130, 140] } }, [2])[0].count, 1);
  assert.deepEqual(trendScorecard({ history: { score: { values: [1, 1] }, close: { values: [1, 2] } } }), []);
});

test('sentiment scorecard joins on date instead of row position', () => {
  const dates = ['d1', 'd2', 'd3', 'd4', 'd5'];
  const result = sentimentScorecard({ dates: ['d2', 'd4'], score: [10, 90] },
    { dates, spy: [100, 100, 110, 120, 130] }, [1]);
  assert.equal(result.find((r) => r.label === 'EXTREME FEAR').count, 1);
  assert.equal(result.find((r) => r.label === 'EXTREME FEAR').mean_pct, 100 * (120 / 110 - 1));
  assert.equal(result.find((r) => r.label === 'EXTREME GREED').count, 0);
});

test('levels read traded closes when the OHLC companion has them', () => {
  const dates = Array.from({ length: 30 }, (_, i) => `d${i}`);
  const adjusted = Array.from({ length: 30 }, (_, i) => 90 + i);          // total-return basis
  const traded = Array.from({ length: 30 }, (_, i) => 100 + i);           // what printed
  const levels = closeLevels(adjusted, { dates, close: traded, open: traded, high: traded, low: traded, volume: traded }, dates);
  assert.equal(levels.basis, 'traded');
  assert.deepEqual(levels.twenty, { low: 109, high: 128 });
  assert.equal(closeLevels(adjusted).basis, 'total_return');
});

test('the ladder sorts every level by price with its distance from the close', () => {
  const levels = { close: 100, twenty: { low: 95, high: 104 }, sixty: null, year: null,
    moving: { 20: 99, 50: null, 200: 90 }, atr14: 2.1 };
  const ladder = priceLadder(levels, { lower: 96, upper: 104.5 });
  assert.deepEqual(ladder.map((r) => r.label), ['IMPLIED HIGH', '+2 ATR', '20D HIGH', '20D AVG', 'IMPLIED LOW', '−2 ATR', '20D LOW', '200D AVG']);
  assert.ok(Math.abs(ladder.find((r) => r.label === '200D AVG').distance_pct + 10) < 1e-9);
  assert.deepEqual(priceLadder(null), []);
});

// --- the page: SETUPS & SIZE with the trade plan, under node against a small fake DOM -----

class FakeNode {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this._value = undefined;
  }
  get value() {
    if (this._value !== undefined) return this._value;
    if (this.tagName === 'SELECT') return this.children.find((c) => c.tagName === 'OPTION')?.attrs.value ?? '';
    return this.attrs.value ?? '';
  }
  set value(v) { this._value = String(v); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener() {}
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  querySelector(selector) {
    return this.children.map((c) => findNode(c, (n) => n.tagName === selector.toUpperCase())).find(Boolean) ?? null;
  }
  querySelectorAll() { return []; }
  select() {}
}

function findNode(node, predicate) {
  if (predicate(node)) return node;
  for (const child of node.children || []) {
    const hit = findNode(child, predicate);
    if (hit) return hit;
  }
  return null;
}

function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.text;
  const own = [node.textContent || '', node.attrs?.value || '', node.attrs?.href || ''];
  return [...own, ...(node.children || []).map(textOf)].filter(Boolean).join(' ');
}

const fakeDocument = () => ({
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
  documentElement: new FakeNode('html'),
  body: new FakeNode('body'),
  hidden: false,
  addEventListener() {},
  removeEventListener() {},
});

const STUBS = ['document', 'window', 'fetch', 'requestAnimationFrame', 'getComputedStyle', 'localStorage'];

// Charts are stubbed: the option builders run, and nothing is drawn.
async function withPage(run) {
  const saved = Object.fromEntries(STUBS.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const define = (key, value) => Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  const chart = { setOption() {}, dispose() {}, resize() {}, getModel: () => null };
  define('document', fakeDocument());
  define('window', { echarts: { init: () => chart } });
  define('fetch', async (url) => (url.endsWith('SPY.json')
    ? { ok: true, json: async () => fixtureTicker() } : { ok: false, status: 404, json: async () => ({}) }));
  define('requestAnimationFrame', (fn) => { fn(); return 0; });
  define('getComputedStyle', () => ({ getPropertyValue: () => '' }));
  define('localStorage', { getItem: () => null, setItem() {}, removeItem() {} });
  try {
    return await run();
  } finally {
    for (const key of STUBS) {
      if (saved[key]) Object.defineProperty(globalThis, key, saved[key]);
      else delete globalThis[key];
    }
  }
}

// Sixty sessions of closes from 400 up to 429.5, so the last close is 429.5.
function fixtureTicker(count = 60) {
  const dates = Array.from({ length: count }, (_, i) => new Date(Date.UTC(2026, 6, 1) + i * 864e5).toISOString().slice(0, 10));
  const close = dates.map((_, i) => 400 + 0.5 * i);
  return { as_of: dates.at(-1), dates, close,
    ohlcv: { dates, open: close, high: close.map((c) => c + 2), low: close.map((c) => c - 2), close, volume: close.map(() => 1e6) } };
}

const BAD = /NaN|undefined|\[object Object\]/;

test('the trade plan card renders its headline, outcomes and sensitivity with no bad figures', async () => {
  const ctx = { arg: 'SPY', setArg() {}, loadArtifact: async () => { throw new Error('not in this fixture'); } };
  await withPage(async () => {
    const page = new FakeNode('div');
    renderTrade(page, { available: ['SPY'] }, null, ctx);
    const planTab = findNode(page, (n) => n.tagName === 'BUTTON' && textOf(n) === 'TRADE PLAN');
    (planTab.listeners.click || []).forEach((fn) => fn());
    const settle = async (done) => { for (let i = 0; i < 50 && !done(); i += 1) await new Promise((r) => setTimeout(r, 0)); };
    await settle(() => textOf(page).includes('SPY · data as of'));
    const plan = findNode(page, (n) => n.className === 'card' && textOf(n).startsWith('TRADE PLAN'));
    const review = findNode(page, (n) => n.className === 'card' && textOf(n).startsWith('REVIEW'));
    const fieldIn = (label) => findNode(plan, (n) => n.className === 'field' && n.children[0]?.textContent === label)?.children[1];
    const setValue = (label, value) => {
      const node = fieldIn(label);
      node.value = value;
      (node.listeners.input || []).forEach((fn) => fn());
    };

    assert.ok(textOf(plan).includes('SPY · data as of 2026-08-29'));
    assert.ok(textOf(plan).includes('Enter the side, entry, stop, target, horizon and costs'));
    assert.equal(fieldIn('ENTRY ($)').value, '429.5');   // prefilled from the last close

    setValue('STOP ($)', '420');
    setValue('TARGET ($)', '450');
    setValue('SLIPPAGE (BPS / SIDE)', '5');
    setValue('P · TARGET HIT (%)', '60');
    setValue('P · STOP HIT (%)', '40');
    setValue('P · HORIZON ENDS (%)', '20');
    assert.ok(textOf(plan).includes('Weights must sum to 100%; they sum to 120.0%'));

    setValue('P · TARGET HIT (%)', '40');
    const text = textOf(plan);
    assert.ok(text.includes('Success rate needed to break even'));
    assert.ok(text.includes('HORIZON ENDS, NEITHER HIT'));
    assert.ok(text.includes('Expected value from your weights, not a forecast'));
    assert.ok(text.includes('Costs: commission per share per side'));
    assert.doesNotMatch(text, BAD);
    assert.ok(findNode(page, (n) => n.tagName === 'A' && n.attrs.href === '#technicals/SPY'));
    assert.ok(findNode(page, (n) => n.tagName === 'A' && n.attrs.href === '#movecheck/SPY'));
    assert.ok(findNode(page, (n) => n.tagName === 'A' && n.attrs.href === '#ticker/SPY'));
    assert.ok(textOf(review).includes('Load a plan file'));
    assert.doesNotMatch(textOf(review), BAD);
  });
});
