// The session cards moved from OVERVIEW to INDICES: each renders from a small
// overview.json fixture without throwing, keeps its labels, and the wrapper
// returns one card per available input. Rendered under node against a fake DOM
// and a stub ECharts, as the other tab tests are.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { breadthCard, contributionsCard, performanceCard, sessionCards, volatilityLine, volReading } from '../../web/js/session-cards.js';

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
    this.hidden = false;
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
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
  documentElement: new FakeNode('html'),
  body: { contains: () => true },
});

// Installs the fake DOM and ECharts for one test, lets the deferred draws run,
// then restores the globals.
function withBrowser(run) {
  const saved = {
    document: globalThis.document, window: globalThis.window, getComputedStyle: globalThis.getComputedStyle,
    requestAnimationFrame: globalThis.requestAnimationFrame,
  };
  globalThis.document = fakeDocument();
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
  globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
  globalThis.window = { echarts: { init: () => ({ setOption() {}, resize() {}, dispose() {}, on() {}, getModel() {} }) } };
  return Promise.resolve().then(run)
    .then(() => new Promise((resolve) => setTimeout(resolve, 5)))
    .finally(() => {
      for (const [key, value] of Object.entries(saved)) {
        if (value === undefined) delete globalThis[key];
        else globalThis[key] = value;
      }
    });
}

function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(textOf)].filter(Boolean).join(' ');
}

const cardTitle = (node) => node?.children?.[0]?.children?.[0]?.textContent;

const dist = (flat) => ({
  edges: [1, 2, 4],
  up: [40, 20, 10, 5],
  down: [30, 15, 8, 3],
  flat,
  members: 500,
});

const overview = {
  as_of: '2026-10-16',
  breadth: [
    { key: 'SPX', label: 'S&P 500', members: 503, '1D': { up: 300, down: 200 }, '1W': { up: 260, down: 240 }, '1M': { up: 250, down: 250 },
      above_50d: 55, above_200d: 61, new_highs: 12, new_lows: 4 },
  ],
  breadth_history: { dates: ['2026-10-14', '2026-10-15', '2026-10-16'], above_50d: [50, 53, 55], above_200d: [58, 60, 61] },
  distribution: { '1D': dist(3), '1W': dist(1), '1M': dist(0) },
  contributions: {
    date: '2026-10-16',
    total_pp: 0.42,
    leaders: [{ ticker: 'NVDA', return_pct: 3.1, contribution_pp: 0.35 }],
    laggards: [{ ticker: 'XOM', return_pct: -2.2, contribution_pp: -0.08 }],
    sectors: [
      { sector: 'Information Technology', contribution_pp: 0.3 },
      { sector: 'Energy', contribution_pp: -0.1 },
    ],
  },
  performance: {
    dates: ['2026-06-30', '2026-07-01', '2026-07-02', '2026-07-03'],
    series: { SPY: [100, 101, 102, 103], QQQ: [100, 102, 101, 104], IWM: [100, 99, 98, 100], RSP: [100, 100, 101, 101] },
  },
  equal_vs_cap: { gap_pp: { '1M': -1.2, '3M': 0.4, YTD: -3.1 } },
  vol: { date: '2026-10-16', move: 92.4, move_pct_1y: 80, move_threshold: 110, vix: 14.2, vix_pct_1y: 20,
    ratio: 6.5, ratio_pct: 40, ratio_since: '2018-01-05', reading: 'rates' },
};

test('the breadth card keeps its headline labels and the wider-window fold', () => withBrowser(() => {
  const node = breadthCard(overview.breadth, overview.breadth_history, overview.distribution);
  const text = textOf(node);
  assert.equal(cardTitle(node), 'BREADTH');
  for (const label of ['Up / down · today', 'Above 50-day average', 'Above 200-day average', 'New 52-week highs / lows']) {
    assert.ok(text.includes(label), `missing row ${label}`);
  }
  assert.ok(text.includes('MORE BREADTH'), 'the wider windows sit behind the fold');
  assert.ok(text.includes('S&P 500 MEMBERS BY SIZE OF MOVE'));
}));

test('breadth with no members says so in place of the table', () => withBrowser(() => {
  const node = breadthCard([], null, null);
  assert.ok(textOf(node).includes('No member closes in this build.'));
}));

test('the contributions card names the day, the total and the leaders', () => withBrowser(() => {
  const node = contributionsCard(overview.contributions);
  const text = textOf(node);
  assert.equal(cardTitle(node), 'WHAT MOVED THE S&P 500');
  assert.ok(text.includes('2026-10-16'));
  assert.ok(text.includes('NVDA +0.35'));
  assert.ok(text.includes('XOM -0.08'));
  assert.ok(text.includes('Information Technology +0.30'));
}));

test('no contributions gives no card', () => withBrowser(() => {
  assert.equal(contributionsCard(null), null);
}));

test('the performance card carries the four lines and the equal-vs-cap gap', () => withBrowser(() => {
  const node = performanceCard(overview.performance, overview.equal_vs_cap);
  const text = textOf(node);
  assert.equal(cardTitle(node), 'PERFORMANCE · SPY QQQ IWM RSP');
  assert.ok(text.includes('Equal weight vs cap weight (RSP − SPY)'));
  assert.ok(text.includes('1M -1.2pp'));
}));

test('a missing index history says so', () => withBrowser(() => {
  const node = performanceCard(null, null);
  assert.ok(textOf(node).includes('No index history in this build.'));
}));

test('the volatility line states the reading, the levels and their rank in the year', () => withBrowser(() => {
  const node = volatilityLine(overview.vol);
  const text = textOf(node);
  assert.ok(text.includes('BOND VS EQUITY VOLATILITY'));
  assert.ok(text.includes('RATES STRESS, EQUITIES CALM'));
  assert.ok(text.includes('MOVE 92.4 (1Y 80th)'));
  assert.ok(text.includes('VIX 14.2 (1Y 20th)'));
  assert.ok(text.includes('its line on RISK is 110'));
}));

test('an unknown reading draws no volatility line', () => withBrowser(() => {
  assert.equal(volatilityLine({ ...overview.vol, reading: 'nonsense' }), null);
  assert.equal(volReading(null), null);
}));

test('sessionCards returns the four cards in reading order', () => withBrowser(() => {
  const nodes = sessionCards(overview);
  assert.equal(nodes.length, 4);
  assert.equal(cardTitle(nodes[0]), 'BREADTH');
  assert.equal(cardTitle(nodes[1]), 'WHAT MOVED THE S&P 500');
  assert.equal(cardTitle(nodes[2]), 'PERFORMANCE · SPY QQQ IWM RSP');
  assert.ok(textOf(nodes[3]).includes('BOND VS EQUITY VOLATILITY'));
}));

test('sessionCards drops a card whose input is absent instead of leaving a hole', () => withBrowser(() => {
  const nodes = sessionCards({ ...overview, contributions: null, vol: null });
  assert.equal(nodes.length, 2);
  assert.equal(cardTitle(nodes[0]), 'BREADTH');
  assert.equal(cardTitle(nodes[1]), 'PERFORMANCE · SPY QQQ IWM RSP');
}));
