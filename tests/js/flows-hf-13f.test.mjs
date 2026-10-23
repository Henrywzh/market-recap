// The FLOWS hedge-fund 13F section, rendered under node against a small fake DOM
// and a stub ECharts. The checks: the text helpers (signs, zeros, dashes), the
// unavailable and empty states, the cards and method fold, no NaN or undefined in
// the page text, and the sign colouring of the sector tilt.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  section, dollarsText, holdersText, ratioText, tiltText, optionsText, metaLine, methodNotes, tiltOption,
} from '../../web/js/flows-hf-13f.js';

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

// Installs the fake DOM and ECharts, runs the test, then restores the globals.
async function withBrowser(run) {
  const saved = {
    document: globalThis.document, window: globalThis.window,
    requestAnimationFrame: globalThis.requestAnimationFrame, getComputedStyle: globalThis.getComputedStyle,
  };
  globalThis.document = fakeDocument();
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
  globalThis.requestAnimationFrame = undefined;
  globalThis.window = { echarts: { init: () => ({ setOption() {}, resize() {}, dispose() {}, on() {}, getModel() {} }) } };
  try {
    await run();
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

function all(node, test) {
  const found = test(node) ? [node] : [];
  for (const child of node.children || []) if (child.nodeType === 1) found.push(...all(child, test));
  return found;
}

const BAD = /NaN|undefined|\[object Object\]/;

const SAMPLE = {
  period: '2026-06-30', period_label: 'Q2 2026', prior_period: '2026-03-31', prior_label: 'Q1 2026',
  deadline: '2026-08-14', prices_as_of: '2026-10-22', sp_weight_as_of: '2026-10-22',
  filers: {
    configured: 48, in_aggregate: 44, read: 44, read_prior: 44,
    list: [{ label: 'Lone Pine Capital', style: 'fundamental', read: true }, { label: 'Trian Fund Management', style: 'activist', read: true }],
    excluded_style: ['Citadel Advisors'],
  },
  n_funds: 44, total_value_bn: 457.17,
  concentration_top10_pct: 29.7,
  outside_sp500: { names: 1573, value_share_pct: 38.9 },
  options: { put_rows: 143, call_rows: 124, put_value_bn: 14.75, call_value_bn: 2.83 },
  crowded: [
    { ticker: 'AMZN', sector: 'Consumer Discretionary', funds: 24, value_bn: 15.45, hf_pct: 3.38, sp_pct: 3.85, ratio: 0.88 },
    { ticker: 'V', sector: 'Financials', funds: 13, value_bn: 16.11, hf_pct: 3.52, sp_pct: 1.04, ratio: 3.39 },
    { ticker: 'CCC', sector: 'Health Care', funds: 1, value_bn: 0.1, hf_pct: null, sp_pct: 0, ratio: null },
  ],
  moves: {
    common_funds: 44,
    adds: [{ ticker: 'STX', d_holders: 7, d_value: 1297637183.7 }],
    cuts: [{ ticker: 'NVDA', d_holders: -5, d_value: -1638569805.1 }],
    adds_by_holders: [], cuts_by_holders: [],
  },
  sector_tilt: [
    { sector: 'Industrials', hf_pct: 16.9, sp_pct: 8.0, tilt_pts: 8.9 },
    { sector: 'Information Technology', hf_pct: 27.5, sp_pct: 38.2, tilt_pts: -10.7 },
  ],
};

test('signs and dashes: a missing figure is a dash, a real zero is a zero', () => {
  assert.equal(dollarsText(3.66e9), '+$3.66bn');
  assert.equal(dollarsText(-3.1e8), '−$310m');
  assert.equal(dollarsText(null), '—');
  assert.equal(holdersText(2), '+2');
  assert.equal(holdersText(-5), '−5');
  assert.equal(holdersText(0), '0');
  assert.equal(holdersText(undefined), '—');
  assert.equal(ratioText(0.88), '0.88×');
  assert.equal(ratioText(NaN), '—');
  assert.equal(tiltText(8.9), '+8.9 pts');
  assert.equal(tiltText(-10.7), '−10.7 pts');
});

test('options are a line of their own, puts and calls in billions', () => {
  assert.equal(optionsText(SAMPLE.options), 'puts $14.8bn across 143 lines · calls $2.8bn across 124 lines');
  assert.equal(optionsText(null), '—');
});

test('the header line names the quarter, the deadline and the price date', () => {
  const line = metaLine(SAMPLE);
  assert.match(line, /44 of 44 funds filed/);
  assert.match(line, /filings due 2026-08-14/);
  assert.match(line, /2026-10-22 close/);
});

test('the method notes say what is a proxy and what is excluded', () => {
  const notes = methodNotes(SAMPLE).join(' ');
  assert.match(notes, /A proxy, not a census/);
  assert.match(notes, /Citadel Advisors/);
  assert.match(notes, /Long equity only/);
  assert.match(notes, /price moves do not count/);
  assert.doesNotMatch(notes, BAD);
});

test('an unavailable build is a card with the reason, not a blank', async () => {
  await withBrowser(() => {
    const cards = section({ unavailable: 'SSGA: unreachable' });
    assert.equal(cards.length, 1);
    assert.match(textOf(cards[0]), /Not built this session: SSGA: unreachable\./);
  });
});

test('a null section is also a card with a gap', async () => {
  await withBrowser(() => {
    const cards = section(null);
    assert.match(textOf(cards[0]), /Not built this session\./);
  });
});

test('the section renders the crowded table, the move tables and the method fold', async () => {
  await withBrowser(() => {
    const cards = section(SAMPLE);
    assert.equal(cards.length, 1);
    const text = textOf(cards[0]);
    assert.match(text, /HEDGE FUNDS · 13F CROWDING \(Q2 2026\)/);
    assert.match(text, /MOST CROWDED S&P 500 NAMES/);
    assert.match(text, /MOST ADDED/);
    assert.match(text, /MOST CUT/);
    assert.match(text, /\+\$3\.66bn|\+\$1\.30bn/);
    assert.doesNotMatch(text, BAD);

    const links = all(cards[0], (n) => n.tagName === 'A');
    assert.ok(links.some((a) => a.textContent === 'AMZN' && a.attrs.href.startsWith('#')));
    const folds = all(cards[0], (n) => n.tagName === 'DETAILS' && (n.className || '').includes('sx-fold'));
    assert.equal(folds.length, 1);
    assert.equal(folds[0].children[0].textContent, 'Method & limits');
  });
});

test('a quarter with no crowded names says so rather than drawing an empty table', async () => {
  await withBrowser(() => {
    const cards = section({ ...SAMPLE, crowded: [] });
    assert.match(textOf(cards[0]), /No S&P 500 holdings read for this quarter\./);
  });
});

test('the missing ratio shows a dash and a zero index weight never shows a ratio', async () => {
  await withBrowser(() => {
    const text = textOf(section(SAMPLE)[0]);
    assert.match(text, /CCC/);
    assert.doesNotMatch(text, /Infinity/);
  });
});

test('the sector tilt colours positive tilts up and negative tilts down', () => {
  const palette = { text: '#t', dim: '#d', faint: '#f', border: '#b', up: '#U', down: '#D', accent: '#a', blue: '#bl' };
  const option = tiltOption(SAMPLE.sector_tilt, palette);
  const colours = option.series[0].data.map((d) => d.itemStyle.color);
  assert.deepEqual(colours, ['#U', '#D']);
  assert.deepEqual(option.yAxis.data, ['Industrials', 'Information Technology']);
});
