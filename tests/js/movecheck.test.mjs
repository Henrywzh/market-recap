// MOVE CHECK: the model on hand-made series, and the page rendered from a
// fixture under node against a small fake DOM (no charting library, no network).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/movecheck-model.js';
import renderMoveCheck from '../../web/js/tabs/movecheck.js';

const near = (actual, expected, eps = 1e-9) => assert.ok(Math.abs(actual - expected) < eps, `${actual} != ${expected}`);
const dayAt = (i, start = '2020-01-01') => new Date(Date.parse(`${start}T00:00:00Z`) + i * 864e5).toISOString().slice(0, 10);
const dated = (rets, start) => rets.map((ret, i) => ({ date: dayAt(i, start), ret }));

// --- returns and the latest move -------------------------------------------------

test('returns are close-to-close percent, dated by the closing session, and skip a pair with a missing close', () => {
  const dates = ['a', 'b', 'c', 'd', 'e'];
  const close = [100, 102, null, 99, 97.02];
  const one = M.returns(dates, close, 1);
  assert.deepEqual(one.map((r) => r.date), ['b', 'e']);
  near(one[0].ret, 2);
  near(one[1].ret, -2);
});

test('a multi-session return skips any pair that touches a missing close', () => {
  // 'e' is 101 against 99 two sessions back, but 'c' is missing; the pair from 'c' to 'e' is dropped.
  const series = M.returns(['a', 'b', 'c', 'd', 'e'], [100, 102, null, 99, 101], 2);
  assert.deepEqual(series.map((r) => r.date), ['d']);
  near(series[0].ret, (99 / 102 - 1) * 100);
});

test('a zero start close and a bad horizon give no returns', () => {
  assert.deepEqual(M.returns(['a', 'b'], [0, 5], 1), []);
  assert.deepEqual(M.returns(['a', 'b'], [1, 2], 0), []);
  assert.deepEqual(M.returns(['a', 'b'], [1, 2], 1.5), []);
});

test('the latest move is the last return, and null with no usable pair', () => {
  near(M.latestMove(['a', 'b', 'c'], [10, 9, 8.1], 1).ret, -10);
  assert.equal(M.latestMove(['a', 'b'], [null, null], 1), null);
  assert.equal(M.latestMove([], [], 1), null);
});

// --- checking a move -------------------------------------------------------------

const falls = dated([-1, -2, -3, -1, 0.5]);

test('a fall counts the returns at or below the move, the tie included, and reports the last day beyond it', () => {
  const r = M.checkMove(falls, -3);
  assert.equal(r.n, 5);
  assert.equal(r.worse, 1);
  near(r.share, 0.2);
  near(r.percentile, 10);
  assert.equal(r.lastWorse, dayAt(2));
});

test('the move\'s own session counts as beyond, but it is not the last worse day when it is the latest', () => {
  const series = dated([-1, -3.5, -2, -3]);
  const r = M.checkMove(series, -3);
  assert.equal(r.worse, 2);
  assert.equal(r.lastWorse, dayAt(1));
});

test('a move that is not the latest session can name its own date as the last worse day', () => {
  assert.equal(M.checkMove(falls, -3, { date: dayAt(2) }).lastWorse, dayAt(2));
});

test('a rise counts the returns at or above the move, with the percentile from the bottom', () => {
  const series = dated([0.5, 2, 1, -1, 3]);
  const r = M.checkMove(series, 1);
  assert.equal(r.worse, 3);
  near(r.share, 0.6);
  near(r.percentile, 50);
  assert.equal(r.lastWorse, dayAt(2));
});

test('a lookback keeps only the last sessions, and a window with no day beyond the move says so', () => {
  const r = M.checkMove(falls, -3, { lookbackSessions: 2 });
  assert.equal(r.n, 2);
  assert.equal(r.worse, 0);
  assert.equal(r.lastWorse, null);
  near(r.share, 0);
});

test('per year is the days beyond the move over the years the window covers', () => {
  const series = [{ date: '2020-01-01', ret: -2 }, { date: '2022-01-01', ret: -1 }];
  const r = M.checkMove(series, -1.5);
  const years = 731 / 365.25;
  near(r.years, years);
  near(r.perYear, 1 / years);
});

test('an empty window or a move that is not a number gives no figures', () => {
  const empty = M.checkMove([], -3);
  assert.equal(empty.n, 0);
  assert.equal(empty.share, null);
  assert.equal(empty.percentile, null);
  assert.equal(M.checkMove(falls, NaN).share, null);
});

// --- volatility -----------------------------------------------------------------

test('a move is measured against the twenty daily returns before its own session', () => {
  const alternating = Array.from({ length: 21 }, (_, i) => ({ date: dayAt(i), ret: i % 2 ? -1 : 1 }));
  const sd = Math.sqrt(20 / 19);
  near(M.sigmaOf(alternating, -2.05), -2.05 / sd, 1e-9);
  // The last entry is the move's own day, so changing it changes nothing.
  const changed = alternating.map((r, i) => (i === 20 ? { ...r, ret: 50 } : r));
  near(M.sigmaOf(changed, -2.05), -2.05 / sd, 1e-9);
});

test('a longer horizon scales the volatility by the square root of its sessions', () => {
  const alternating = Array.from({ length: 21 }, (_, i) => ({ date: dayAt(i), ret: i % 2 ? -1 : 1 }));
  near(M.sigmaOf(alternating, -2.05, 20, 4), -2.05 / (Math.sqrt(20 / 19) * 2), 1e-9);
});

test('too little data, no variation or no move gives no sigma', () => {
  const short = Array.from({ length: 20 }, (_, i) => ({ date: dayAt(i), ret: i % 2 ? -1 : 1 }));
  assert.equal(M.sigmaOf(short, -2), null);
  const flat = Array.from({ length: 25 }, (_, i) => ({ date: dayAt(i), ret: 0.5 }));
  assert.equal(M.sigmaOf(flat, -2), null);
  assert.equal(M.sigmaOf(flat, null), null);
});

// --- episodes -------------------------------------------------------------------

test('days beyond the move merge when they are within five sessions, and each episode gives its worst day', () => {
  const series = dated([-1, -3.5, -4, -1, -1, -1, -1, -1, -1, -3.2, -1, -5, -1]);
  assert.deepEqual(M.episodes(series, -3), [
    { start: dayAt(1), worstDate: dayAt(2), worst: -4 },
    { start: dayAt(9), worstDate: dayAt(11), worst: -5 },
  ]);
});

test('the gap is inclusive: five sessions apart merge, six do not', () => {
  const five = dated([-4, -1, -1, -1, -1, -4.5]);
  assert.deepEqual(M.episodes(five, -3), [{ start: dayAt(0), worstDate: dayAt(5), worst: -4.5 }]);
  const six = dated([-4, -1, -1, -1, -1, -1, -4.5]);
  assert.equal(M.episodes(six, -3).length, 2);
});

test('a rise gathers the days at or above it, and a tie keeps the first worst day', () => {
  const rise = M.episodes(dated([0, 3, 1, 2.5]), 2);
  assert.deepEqual(rise, [{ start: dayAt(1), worstDate: dayAt(1), worst: 3 }]);
  assert.deepEqual(M.episodes(dated([-4, -4]), -3), [{ start: dayAt(0), worstDate: dayAt(0), worst: -4 }]);
});

test('no day beyond the move gives no episodes', () => {
  assert.deepEqual(M.episodes(dated([-1, 0.5, 2]), -3), []);
  assert.deepEqual(M.episodes(null, -3), []);
});

// --- forward returns and drawdown -------------------------------------------------

const DATES = Array.from({ length: 10 }, (_, i) => `d${i}`);

test('a forward return runs from the date\'s close to the close the sessions later', () => {
  const close = [100, 101, null, 103, 104, 105, 106, 107, 108, 109];
  near(M.forward(DATES, close, 'd0', 3), 3);
  near(M.forward(DATES, close, 'd0', 1), 1);
  assert.equal(M.forward(DATES, close, 'd2', 1), null, 'a missing start close');
  assert.equal(M.forward(DATES, close, 'd0', 2), null, 'a missing end close');
  assert.equal(M.forward(DATES, close, 'd8', 2), null, 'beyond the last session');
  assert.equal(M.forward(DATES, close, 'nope', 1), null, 'an unknown date');
});

test('the worst close after a date, against its close, never above zero', () => {
  const dates = Array.from({ length: 8 }, (_, i) => `d${i}`);
  const close = [100, 105, 90, null, 95, 120, 80, 85];
  near(M.maxDrawdownAfter(dates, close, 'd0', 3), -10);
  assert.equal(M.maxDrawdownAfter(dates, close, 'd0', 1), 0, 'a higher close is not a drawdown');
  near(M.maxDrawdownAfter(dates, close, 'd4', 2), (80 / 95 - 1) * 100);
  assert.equal(M.maxDrawdownAfter(dates, close, 'd6', 2), null, 'the window runs past the end');
  assert.equal(M.maxDrawdownAfter(['a', 'b', 'c'], [100, null, null], 'a', 2), null, 'no close in the window');
  assert.ok(M.maxDrawdownAfter(dates, [100, 110, 120, 130, 140, 150, 160, 170], 'd0', 3) <= 0);
});

// --- histogram ------------------------------------------------------------------

test('a histogram counts each value once, the top edge in the last bin', () => {
  const h = M.histogram([1, 2, 2, 3, 10], 3);
  assert.deepEqual(h.edges, [1, 4, 7, 10]);
  assert.deepEqual(h.counts, [4, 0, 1]);
  assert.equal(h.counts.reduce((a, b) => a + b, 0), 5);
});

test('the axis can stretch to include a value the counts leave out, such as the move', () => {
  const h = M.histogram([1, 2, 2, 3, 10], 3, { include: [-5] });
  assert.deepEqual(h.edges, [-5, 0, 5, 10]);
  assert.deepEqual(h.counts, [0, 4, 1]);
});

test('an empty or one-valued histogram is still well formed', () => {
  assert.deepEqual(M.histogram([], 5), { edges: [], counts: [] });
  assert.deepEqual(M.histogram([null, NaN, 1], 1).counts, [1]);
  const same = M.histogram([2, 2], 2);
  assert.deepEqual(same.counts, [0, 2]);
  assert.equal(same.edges.length, 3);
});

test('a value is placed in its bin, clamped to the axis', () => {
  const edges = [1, 4, 7, 10];
  assert.equal(M.binIndex(edges, 0), 0);
  assert.equal(M.binIndex(edges, 4), 1);
  assert.equal(M.binIndex(edges, 10), 2);
  assert.equal(M.binIndex(edges, null), null);
});

// --- text ------------------------------------------------------------------------

test('a figure prints a true minus, a plus on a rise, and a dash when absent', () => {
  assert.equal(M.signedPct(-3), '−3.0%');
  assert.equal(M.signedPct(0.5), '+0.5%');
  assert.equal(M.signedPct(-2.9873), '−2.99%');
  assert.equal(M.signedPct(0), '0.0%');
  assert.equal(M.signedPct(NaN), '—');
  assert.equal(M.signedPct(null), '—');
});

test('ordinals take the teen and the 1-2-3 endings right', () => {
  assert.deepEqual([1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111].map(M.ordinal), ['1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '101st', '111th']);
});

const ALL = { n: 2515, worse: 61, share: 61 / 2515, percentile: 2.41, perYear: 6.1, lastWorse: '2026-08-14', years: 9.99 };

test('the headline reads as the page states it, for a fall', () => {
  assert.equal(
    M.moveSentence({ ticker: 'QQQ', horizon: 1, move: -3, date: '2026-10-21', all: ALL }),
    'QQQ −3.0% over 1 day (2026-10-21). In 10 years of history 61 of 2,515 days fell further '
      + '(2.4%, the 2nd percentile), about 6 a year; the last was 2026-08-14.',
  );
});

test('the headline reads for a rise, and names the horizon in sessions', () => {
  const text = M.moveSentence({ ticker: 'SPY', horizon: 5, move: 3, date: '2026-10-21', all: { ...ALL, percentile: 97.6 } });
  assert.equal(text, 'SPY +3.0% over 5 sessions (2026-10-21). In 10 years of history 61 of 2,515 days rose further '
    + '(2.4%, the 98th percentile), about 6 a year; the last was 2026-08-14.');
});

test('the headline says when no day was as far, and when there was no earlier day', () => {
  const none = M.moveSentence({ ticker: 'QQQ', horizon: 1, move: -9, date: '2026-10-21', all: { ...ALL, worse: 0, lastWorse: null } });
  assert.equal(none, 'QQQ −9.0% over 1 day (2026-10-21). In 10 years of history no day fell this far.');
  const first = M.moveSentence({ ticker: 'QQQ', horizon: 1, move: -3, date: '2026-10-21',
    all: { n: 500, worse: 1, share: 0.002, percentile: 0.1, perYear: 0.5, lastWorse: null, years: 2 } });
  assert.equal(first, 'QQQ −3.0% over 1 day (2026-10-21). In 2 years of history 1 of 500 days fell further '
    + '(0.2%, under the 1st percentile), about 0.5 a year; no earlier day was that far.');
});

test('the headline is a plain sentence when there is no history to place the move in', () => {
  assert.equal(M.moveSentence({ ticker: 'QQQ', horizon: 1, move: -3, date: '2026-10-21', all: null }),
    'QQQ −3.0% over 1 day (2026-10-21). Not enough history to place this move.');
});

// --- the page ----------------------------------------------------------------------

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
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener() {}
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

const fakeDocument = () => ({
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
});

// Everything a reader would see: text, attributes and option labels included.
function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.text;
  const own = [node.textContent || '', node.attrs?.value || '', node.attrs?.['aria-label'] || ''];
  return [...own, ...(node.children || []).map(textOf)].filter(Boolean).join(' ');
}

function findNode(node, predicate) {
  if (predicate(node)) return node;
  for (const child of node.children || []) {
    const hit = findNode(child, predicate);
    if (hit) return hit;
  }
  return null;
}

async function withBrowser(run) {
  const saved = { document: globalThis.document, window: globalThis.window };
  globalThis.document = fakeDocument();
  globalThis.window = {};
  try {
    return await run();
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
}

// A year of closes with a sine wobble, a missing close mid-way and a 3% fall on the last session.
function fixtureTicker(count = 300) {
  const dates = Array.from({ length: count }, (_, i) => dayAt(i));
  const close = Array.from({ length: count }, (_, i) => 100 * (1 + 0.01 * Math.sin(i)) + i * 0.05);
  close[50] = null;
  close[count - 1] = close[count - 2] * 0.97;
  return { ticker: 'FIX', dates, close };
}

function ctxWith(payloads, arg = 'FIX') {
  const calls = { setArg: [] };
  const ctx = {
    arg,
    calls,
    loadArtifact: async (name) => {
      const key = name.replace(/^tickers\//, '');
      if (!payloads[key]) throw new Error(`${key}.json returned 404`);
      return payloads[key];
    },
    setArg: (next) => calls.setArg.push(next),
  };
  return ctx;
}

const BAD = /NaN|undefined|\[object Object\]/;

test('the page renders the headline, stats, histogram and episodes with no bad figures', async () => {
  const ctx = ctxWith({ FIX: fixtureTicker(), SPY: fixtureTicker(120) });
  const data = { available: ['FIX', 'SPY'] };
  const text = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, data, null, ctx);
    return textOf(root);
  });
  assert.ok(text.includes('FIX'), 'names the ticker');
  assert.ok(text.includes('fell further'), 'a fall is read as a fall');
  assert.ok(text.includes('EPISODES BEYOND THIS MOVE'));
  assert.ok(text.includes('IN TODAY\'S VOLATILITY'));
  assert.ok(text.includes('Description, not a signal'));
  assert.ok(!BAD.test(text), `bad figure in page text: ${text.match(BAD)?.[0]}`);
  assert.deepEqual(ctx.calls.setArg, ['FIX'], 'the hash keeps the ticker');
});

test('a button press re-runs the check at another horizon, with the box set to that horizon\'s latest move', async () => {
  const ctx = ctxWith({ FIX: fixtureTicker(), SPY: fixtureTicker(120) });
  const data = { available: ['FIX', 'SPY'] };
  await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, data, null, ctx);
    const fiveDay = findNode(root, (n) => n.tagName === 'BUTTON' && n.textContent === '5D');
    assert.ok(fiveDay, 'the 5D button is there');
    fiveDay.listeners.click[0]();
    await new Promise((resolve) => setTimeout(resolve, 0));
    const text = textOf(root);
    assert.ok(text.includes('over 5 sessions'), 'the headline names five sessions');
    assert.ok(!BAD.test(text));
  });
});

test('a short history says so in words, and an unknown ticker is named', async () => {
  const tiny = { dates: ['2026-01-01', '2026-01-02'], close: [10, null] };
  const data = { available: ['TINY', 'FIX'] };
  const short = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, data, null, ctxWith({ TINY: tiny }, 'TINY'));
    return textOf(root);
  });
  assert.ok(short.includes('Not enough history for TINY'));
  assert.ok(!BAD.test(short));

  const missing = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, data, null, ctxWith({ FIX: fixtureTicker() }, 'NOPE'));
    return textOf(root);
  });
  assert.ok(missing.includes('FIX'), 'an unknown ticker falls back to the first in the build');
  assert.ok(!BAD.test(missing));
});

test('a ticker whose file fails to load says so, without a bad figure', async () => {
  const data = { available: ['FIX', 'SPY'] };
  const text = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, data, null, ctxWith({}, 'SPY'));
    return textOf(root);
  });
  assert.ok(text.includes('SPY could not be loaded'));
  assert.ok(!BAD.test(text));
});
