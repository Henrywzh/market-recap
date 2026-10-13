// The TICKER page's VALUATION block, drawn under node against a small fake DOM
// and a stub ECharts: the company's own figures beside its sector's, and the
// block's gap lines where an artifact does not cover the name.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { companyOutlook, companyValuation } from '../../web/js/tabs/ticker.js';

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

const fakeDocument = () => ({
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
  documentElement: new FakeNode('html'),
});

// Installs the fake DOM and ECharts for one test, and puts the globals back after.
function withBrowser(run) {
  const saved = {
    document: globalThis.document, window: globalThis.window, getComputedStyle: globalThis.getComputedStyle,
  };
  globalThis.document = fakeDocument();
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

// All the text under a node, as one string.
function textOf(node) {
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(textOf)].join(' ');
}

// A loader that answers from `files` and fails for any other artifact, as the
// build's loader does for a name it did not write.
const ctxWith = (files) => ({
  loadArtifact: async (name) => {
    if (!(name in files)) throw new Error(`${name}.json returned 404`);
    return files[name];
  },
});

const ROW = { ticker: 'AAPL', sector: 'Information Technology', pe_history: { basis: 'operating' }, pe_forward: 20.5, eps_fy0: 6, eps_fy1: 6.6, revenue_growth: 31.2 };

const VALUATION = {
  dates: ['2024-01-05', '2024-01-12', '2024-01-19'],
  pe: [30, 33, 36.5],
  stats: { current: 36.5, percentile: 62, median: 32.8, p25: 28, p75: 35, p10: 25, p90: 40 },
  close: [100, 105, 110],
};

const SECTOR_PAGE = {
  valuation: { dates: ['2024-01-05', '2024-01-12'], pe: [25, 26], price: [1, 1.1], earnings: [0.04, 0.042], stats: { current: 26, median: 24, p25: 22, p75: 27 } },
  outlook: { forward_pe: 19.6, eps_growth_next: 14.2, revenue_growth: 12.8 },
  history: { years: [2024, 2025], revenue_growth: [null, 9.1], gross_margin: [null, null], operating_margin: [18, 19] },
};

const FINANCIALS = {
  columns: [{ fiscal_year: 2024 }, { fiscal_year: 2025 }],
  values: { revenue: [100, 120], gross_profit: [40, 50], ebit: [20, 30] },
};

test('a company\'s outlook is its forward P/E, its next-year EPS growth and its revenue growth; a loss gives no growth', () => {
  const outlook = companyOutlook(ROW);
  assert.equal(outlook.forward_pe, 20.5);
  assert.ok(Math.abs(outlook.eps_growth_next - 10) < 1e-9, 'EPS growth from 6.0 to 6.6 is 10%');
  assert.equal(outlook.revenue_growth, 31.2);
  assert.equal(companyOutlook({ eps_fy0: -2, eps_fy1: 1 }).eps_growth_next, null);
  assert.deepEqual(companyOutlook({}), { forward_pe: null, eps_growth_next: null, revenue_growth: null });
});

test('the TICKER valuation block sets the company beside its sector, from its own artifacts', async () => {
  await withBrowser(async () => {
    const ctx = ctxWith({
      'valuation/AAPL': VALUATION,
      'financials/AAPL': FINANCIALS,
      sectors: { sectors: [{ key: 'XLK', label: 'Information Technology' }] },
      'sectors/XLK': SECTOR_PAGE,
    });
    const sectors = await ctx.loadArtifact('sectors');
    const nodes = await companyValuation(ctx, 'AAPL', ROW, sectors);
    await flush();
    const text = nodes.map(textOf).join(' ');
    assert.match(text, /VALUATION\s+AAPL against Information Technology/);
    assert.match(text, /36\.5×/, 'the trailing P/E is the company\'s own');
    assert.match(text, /20\.5× vs 19\.6×/, 'forward P/E beside the sector\'s');
    assert.match(text, /OPERATING MARGIN · FY2025\s+25\.0% vs 19\.0%/, 'operating margin by fiscal year, beside the sector\'s');
    assert.doesNotMatch(text, /no filings history, so no valuation/);
  });
});

test('a company with no artifacts of its own still gets the block, with its gaps named rather than a failure', async () => {
  await withBrowser(async () => {
    const ctx = ctxWith({});
    const nodes = await companyValuation(ctx, 'XYZ', { ticker: 'XYZ', sector: 'Energy', pe_forward: null }, null);
    await flush();
    const text = nodes.map(textOf).join(' ');
    assert.match(text, /VALUATION\s+XYZ against Energy/);
    assert.match(text, /Too little P\/E history to draw/);
    assert.match(text, /No annual filings to total\./);
  });
});

test('a sector page without its price series still gives the strip; the comparison cards need both series', async () => {
  await withBrowser(async () => {
    const sectors = { sectors: [{ key: 'XLK', label: 'Information Technology' }] };
    const ctx = ctxWith({
      'valuation/AAPL': VALUATION,
      'sectors/XLK': { valuation: { dates: ['2024-01-05'], pe: [25] }, outlook: { forward_pe: 19.6 }, history: null },
    });
    const nodes = await companyValuation(ctx, 'AAPL', ROW, sectors);
    await flush();
    assert.match(nodes.map(textOf).join(' '), /20\.5× vs 19\.6×/);
  });
});

test('a name without a P/E history or statements asks for neither file', async () => {
  await withBrowser(async () => {
    const asked = [];
    const ctx = { loadArtifact: async (name) => { asked.push(name); throw new Error('missing'); } };
    await companyValuation(ctx, 'BRK-B', { ticker: 'BRK-B', sector: 'Financials', pe_history: false }, null, { available: [{ ticker: 'AAPL' }] });
    assert.deepEqual(asked, []);
  });
});
