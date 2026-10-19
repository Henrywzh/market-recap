// The earnings and forward card's year-over-year EPS growth, and the TICKER
// VALUATION block's operating/reported switch on the trailing P/E band.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { epsGrowth } from '../../web/js/tabs/valuation.js';
import { companyValuation } from '../../web/js/tabs/ticker.js';

class FakeNode {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.className = '';
    this.textContent = '';
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
}

// Installs the fake DOM and ECharts for one test, and puts the globals back after.
function withBrowser(run) {
  const saved = {
    document: globalThis.document, window: globalThis.window, getComputedStyle: globalThis.getComputedStyle,
  };
  globalThis.document = {
    createElement: (tag) => new FakeNode(tag),
    createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
    documentElement: new FakeNode('html'),
  };
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
  globalThis.window = { echarts: { init: () => ({ setOption() {}, resize() {}, dispose() {} }) } };
  return Promise.resolve().then(run).finally(() => {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  });
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function textOf(node) {
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(textOf)].join(' ');
}

test('EPS growth is each filing against the TTM EPS in force 364 days earlier', () => {
  const eps = [
    { filed: '2023-02-01', reported: 1.0 },
    { filed: '2023-05-01', reported: 1.1 },
    { filed: '2024-02-01', reported: 1.5 },
    { filed: '2024-05-01', reported: -0.2 },
    { filed: '2024-08-01', reported: 0.9 },
  ];
  // Before any filing a year back there is nothing to compare with; a loss on either side is no growth rate.
  assert.deepEqual(epsGrowth(eps), [null, null, 50, null, -18.2]);
});

test('EPS growth reads the leading basis, and a missing figure is a gap', () => {
  const eps = [
    { filed: '2023-02-01', reported: 2.0, operating: 1.5 },
    { filed: '2024-02-01', reported: 2.2, operating: null },
  ];
  assert.deepEqual(epsGrowth(eps, 'reported'), [null, 10]);
  assert.deepEqual(epsGrowth(eps, 'operating'), [null, null]);
  assert.deepEqual(epsGrowth([{ filed: 'not a date', reported: 1 }]), [null]);
});

const ROW = { ticker: 'AAPL', sector: 'Information Technology', pe_history: true, pe_forward: 20.5, eps_fy0: 6, eps_fy1: 6.6, revenue_growth: 31.2 };
const STATS = { current: 36.5, percentile: 62, median: 32.8, p25: 28, p75: 35, p10: 25, p90: 40, max: 44 };
const VALUATION = {
  dates: ['2024-01-05', '2024-01-12', '2024-01-19'],
  pe: [30, 33, 36.5],
  stats: STATS,
  basis: 'operating',
  close: [100, 105, 110],
  alternate: { basis: 'reported', pe: [31, 34, 38], stats: { ...STATS, current: 38, percentile: 70 } },
};
const ctxWith = (files) => ({
  loadArtifact: async (name) => {
    if (!(name in files)) throw new Error(`${name}.json returned 404`);
    return files[name];
  },
});

test('a company with a second earnings basis gets the switch, and the title names the active basis', async () => {
  await withBrowser(async () => {
    const ctx = ctxWith({ 'valuation/AAPL': VALUATION });
    const nodes = await companyValuation(ctx, 'AAPL', ROW, null);
    await flush();
    const text = nodes.map(textOf).join(' ');
    assert.match(text, /TRAILING P\/E · OPERATING 36\.5× · 62nd OF ITS OWN TEN YEARS/);
    assert.match(text, /OPERATING\s+REPORTED/, 'the switch offers both bases');
  });
});

test('a company with one basis, and every other block, keeps the plain title', async () => {
  await withBrowser(async () => {
    const ctx = ctxWith({ 'valuation/AAPL': { ...VALUATION, alternate: undefined } });
    const nodes = await companyValuation(ctx, 'AAPL', ROW, null);
    await flush();
    const text = nodes.map(textOf).join(' ');
    assert.match(text, /TRAILING P\/E · 36\.5× · 62nd OF ITS OWN TEN YEARS/);
    assert.doesNotMatch(text, /TRAILING P\/E · OPERATING/);
  });
});
