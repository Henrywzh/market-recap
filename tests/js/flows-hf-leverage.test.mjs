// The FLOWS hedge-fund leverage section: the number formats (a true minus, $tn above
// a trillion, a dash for absence, ordinal percentiles), the chart line set, and the
// section cards for a built payload and for an unavailable one. Rendered against a
// small fake DOM; no ECharts, so the charts draw nothing and only their nodes are checked.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  section, chartLines, dollarBnText, levelText, changeText, ordinal,
} from '../../web/js/flows-hf-leverage.js';

class FakeNode {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.className = '';
    this.textContent = '';
    this.listeners = {};
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
}

const fakeDocument = () => ({
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
});

// All visible text under a node, in document order, as one string.
function textOf(node) {
  if (node.nodeType === 3) return node.text;
  const own = node.textContent || '';
  return own + node.children.map(textOf).join(' ');
}

function withDom(run) {
  const saved = { document: globalThis.document, window: globalThis.window, rAF: globalThis.requestAnimationFrame };
  globalThis.document = fakeDocument();
  globalThis.window = {};
  delete globalThis.requestAnimationFrame;
  try {
    return run();
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
}

const DASH = '—';

test('dollar amounts in $bn read in $tn above a trillion, with a true minus', () => {
  assert.equal(dollarBnText(6194), '$6.19tn');
  assert.equal(dollarBnText(310), '$310bn');
  assert.equal(dollarBnText(1054, true), '+$1.05tn');
  assert.equal(dollarBnText(-310, true), '−$310bn');
  assert.equal(dollarBnText(-310), '−$310bn');
  assert.equal(dollarBnText(0.2, true), '$0bn');   // rounds to zero: no sign
  assert.equal(dollarBnText(null), DASH);
  assert.equal(dollarBnText(Number.NaN), DASH);
});

test('a level prints in its own unit; absence is a dash, never a zero', () => {
  assert.equal(levelText('x', 2.52), '2.52x');
  assert.equal(levelText('%', 37.6), '37.6%');
  assert.equal(levelText('$bn', 6194), '$6.19tn');
  assert.equal(levelText('x', undefined), DASH);
  assert.equal(levelText('%', null), DASH);
});

test('changes carry a true minus, a percentage in brackets, and points for percent series', () => {
  assert.equal(changeText('x', -0.04, -1.7), '−0.04x (−1.7%)');
  assert.equal(changeText('%', -1.0, null), '−1.0 pts');
  assert.equal(changeText('$bn', 1054, 20.5), '+$1.05tn (+20.5%)');
  assert.equal(changeText('x', null, null), DASH);
  assert.equal(changeText('x', 0, 0), '0.00x (0.0%)');
});

test('percentiles read as ordinals, with the teens handled', () => {
  assert.equal(ordinal(91), '91st pct');
  assert.equal(ordinal(12), '12th pct');
  assert.equal(ordinal(11), '11th pct');
  assert.equal(ordinal(13), '13th pct');
  assert.equal(ordinal(22), '22nd pct');
  assert.equal(ordinal(103), '103rd pct');
  assert.equal(ordinal(null), DASH);
});

const payload = () => ({
  source: { latest_period: '2026-06-30', lag: 'Quarter-end data. Lag line.', vintage: 'current', dataset: 'fpf', url: 'https://example.test/' },
  series: [
    { id: 'gross_leverage', label: 'Gross assets ÷ net assets', unit: 'x', dates: ['2026-03-31', '2026-06-30'], values: [2.56, 2.52],
      latest: { value: 2.52, q_change: -0.04, q_change_pct: -1.7, y_change: -0.08, y_change_pct: -3.2, percentile: 91 } },
    { id: 'equity_net_pct_nav', label: 'Net equity exposure, % of net assets', unit: '%', dates: ['2026-03-31', '2026-06-30'], values: [38.6, 37.6],
      latest: { value: 37.6, q_change: -1.0, q_change_pct: null, y_change: -4.0, y_change_pct: null, percentile: 46 } },
    { id: 'equity_long', label: 'Long equity exposure (notional)', unit: '$bn', dates: ['2026-03-31', '2026-06-30'], values: [5140, 6194],
      latest: { value: 6194, q_change: 1054, q_change_pct: 20.5, y_change: 1553, y_change_pct: 33.5, percentile: 100 } },
    { id: 'equity_short', label: 'Short equity exposure (notional)', unit: '$bn', dates: ['2026-03-31', '2026-06-30'], values: [3212, 4121],
      latest: { value: 4121, q_change: 909, q_change_pct: 28.3, y_change: 1373, y_change_pct: 50, percentile: 100 } },
    { id: 'equity_down20', label: 'Change in net assets if equities fall 20% (median fund)', unit: '%', dates: ['2026-03-31', '2026-06-30'], values: [-5, -7],
      latest: { value: -7, q_change: -2, q_change_pct: null, y_change: -1, y_change_pct: null, percentile: 37 } },
    { id: 'equity_borrowing', label: 'Borrowing, equity strategy funds', unit: '$bn', dates: ['2026-03-31', '2026-06-30'], values: [1752, 2091],
      latest: { value: 2091, q_change: 339, q_change_pct: 19.3, y_change: 600, y_change_pct: 40.2, percentile: 100 } },
  ],
});

test('chart lines: leverage against net exposure on two axes; flows in $bn', () => {
  const lines = chartLines(payload());
  assert.deepEqual(lines.leverage.map((l) => l.axis), [0, 1]);
  assert.deepEqual(lines.flows.map((l) => l.name), [
    'long equity exposure', 'short equity exposure', 'borrowing, equity strategy funds',
  ]);
  assert.deepEqual(chartLines({ series: [] }), { leverage: [], flows: [] });
});

test('an unavailable section is one card that says why, with no figures', () => withDom(() => {
  const nodes = section({ unavailable: 'data.financialresearch.gov: HTTP 503' });
  assert.equal(nodes.length, 1);
  const text = textOf(nodes[0]);
  assert.match(text, /HEDGE FUNDS · LEVERAGE AND EQUITY EXPOSURE \(FORM PF\)/);
  assert.match(text, /Not built this session: data\.financialresearch\.gov: HTTP 503\./);
}));

test('a built section renders its table, charts and method fold without placeholder text', () => withDom(() => {
  const nodes = section(payload());
  const text = textOf(nodes[0]);
  for (const bad of ['NaN', 'undefined', '[object Object]', 'null']) assert.ok(!text.includes(bad), `found ${bad}`);
  for (const header of ['SERIES', 'LATEST', 'Q/Q', 'Y/Y', 'PCTILE']) assert.ok(text.includes(header), header);
  assert.ok(text.includes('2.52x'));
  assert.ok(text.includes('$6.19tn'));
  assert.ok(text.includes('91st pct'));
  assert.ok(text.includes('Method & limits'));
  // Percentage-unit series have no percentage change: a dash in the bracket place, not a percent.
  assert.ok(text.includes('−1.0 pts'));
  // Two charts' nodes and a fold.
  const charts = nodes[0].children.filter((c) => c.className === 'chart');
  assert.equal(charts.length, 2);
  const folds = nodes[0].children.filter((c) => c.tagName === 'DETAILS');
  assert.equal(folds.length, 1);
  assert.equal(folds[0].className, 'sx-fold');
}));

test('a payload with no series says so', () => withDom(() => {
  const text = textOf(section({ source: {}, series: [] })[0]);
  assert.match(text, /No Form PF series in this build\./);
}));
