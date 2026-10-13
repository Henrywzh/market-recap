// SECTORS pages: the VALUATION section is the shared block, set against the
// S&P 500 (a sector) or the parent sector (a sub-industry); the valuation path
// card follows it directly, and the top strip keeps three figures. Rendered
// under node against a small fake DOM and a stub ECharts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import renderSectors from '../../web/js/tabs/sectors.js';

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
    this.open = false;
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type) { (this.listeners[type] || []).forEach((fn) => fn({ type })); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  querySelectorAll() { return []; }
}

const fakeDocument = () => ({
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
  documentElement: new FakeNode('html'),
});

// Installs the fake DOM, ECharts and the frame clock for one test, then restores them.
function withBrowser(run) {
  const saved = {
    document: globalThis.document, window: globalThis.window, getComputedStyle: globalThis.getComputedStyle,
    requestAnimationFrame: globalThis.requestAnimationFrame,
  };
  globalThis.document = fakeDocument();
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
  globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
  globalThis.window = { echarts: { init: () => ({ setOption() {}, resize() {}, dispose() {}, on() {} }) } };
  return Promise.resolve().then(run).finally(() => {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  });
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

// The text a node holds, its own and its children's, in reading order.
function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(textOf)].filter(Boolean).join(' ');
}

// Every node under `node` with the given class name, in reading order.
function withClass(node, className, found = []) {
  for (const child of node.children || []) {
    if (!child || child.nodeType !== 1) continue;
    if (child.className === className) found.push(child);
    withClass(child, className, found);
  }
  return found;
}

const DATES = ['2024-10-04', '2025-04-04', '2025-10-03', '2026-04-03', '2026-10-02'];
const PATH = {
  companies: 2, coverage: 0.5,
  stages: [
    { key: 'fy_prev', pe: 20, growth: null }, { key: 'fy0', pe: 19, growth: 5 },
    { key: 'ntm', pe: 18, growth: 3 }, { key: 'fy1', pe: 17, growth: 8 },
  ],
};

// A page file as the build writes it: a valuation history, its outlook, its
// fiscal-year history and its relative line. `scale` moves the P/E so two
// pages differ.
function page(scale) {
  return {
    valuation: {
      dates: DATES,
      pe: [18, 19, 20, 21, 22].map((v) => v * scale),
      stats: { median: 19 * scale, p25: 18 * scale, p75: 21 * scale, current: 22 * scale, percentile: 80, weeks: 520 },
      price: [100, 105, 110, 120, 130].map((v) => v * scale),
      earnings: [5.5, 5.5, 5.5, 5.7, 5.9],
    },
    outlook: { forward_pe: 19 * scale, eps_growth_next: 8, revenue_growth: 5 },
    history: { years: [2023, 2024, 2025], revenue_growth: [3, 4, 5], gross_margin: [40, 41, 42], operating_margin: [20, 21, 22] },
    relative: { dates: DATES, basket: [100, 103, 101, 105, 110] },
  };
}

const data = {
  as_of: '2026-10-12',
  benchmark: { returns: { '1M': 1, '3M': 2, YTD: 5, '1Y': 9 } },
  sectors: [{
    key: 'XLP', label: 'Consumer Staples', etf: 'XLP', members: 2, weight: 4.9,
    returns: { '1M': 1.5, '3M': 0.5, YTD: 7, '1Y': 6 }, vs_index: { '1M': 0.5, '3M': -1.5, YTD: 2, '1Y': -3 },
    above_200d: 60, median_drawdown: -5, revision: { '90d': 1 }, forward_pe: 19, pe_percentile: 40,
    theme: null, quadrant: 'lagging', evidence: {}, best: null, worst: null, path: PATH,
  }],
  sub_industries: [{
    key: 'XLP-PFM', label: 'Packaged Foods & Meats', sector_key: 'XLP', members: 2, weight: 2.0, thin: false, theme: null,
    returns: { '1M': 2, '3M': 1, YTD: 6, '1Y': 5 }, vs_index: { '1M': 1, '3M': -1, YTD: 1, '1Y': -4 },
    above_200d: 50, median_drawdown: -4, revision: { '90d': 0.5 }, forward_pe: 17, pe_percentile: 35, path: null,
  }],
  members: [
    { ticker: 'PEP', name: 'PepsiCo', sector_key: 'XLP', sub_key: 'XLP-PFM', weight: 1.0, returns: { '1M': 1, '3M': 2, YTD: 3, '1Y': 4 },
      drawdown: -3, above_200d: true, revision_90d: 0.5, forward_pe: 19, pe_percentile: 30, next_report: null, monitor: null },
    { ticker: 'GIS', name: 'General Mills', sector_key: 'XLP', sub_key: 'XLP-PFM', weight: 0.5, returns: { '1M': -1, '3M': -2, YTD: -3, '1Y': -4 },
      drawdown: -12, above_200d: false, revision_90d: -1, forward_pe: 14, pe_percentile: 20, next_report: null, monitor: null },
  ],
  themes: [],
  notes: [],
};

// A loader over a map of page files; a value that is an Error stands for a failed load.
function ctxWith(pages, arg) {
  return {
    arg,
    loadArtifact: async (name) => {
      if (!(name in pages)) throw new Error(`${name}.json returned 404`);
      if (pages[name] instanceof Error) throw pages[name];
      return pages[name];
    },
  };
}

async function renderPage(arg, pages) {
  const root = new FakeNode('div');
  await renderSectors(root, data, {}, ctxWith(pages, arg));
  await flush();
  return root;
}

// The section title that opens the valuation block on a page.
const valuationTitle = (root) => root.children.find((node) => node.tagName === 'H2' && textOf(node).startsWith('2 · VALUATION'));

test('a sector page sets its valuation against the S&P 500, in one block under section 2', () => withBrowser(async () => {
  const root = await renderPage('XLP', { 'sectors/XLP': page(1), 'sectors/MARKET': page(1.2) });
  const title = valuationTitle(root);
  assert.ok(title, 'the section 2 title is on the page');
  assert.match(textOf(title), /Cons Staples against S&P 500/);
  assert.equal(withClass(root, 'card').filter((c) => textOf(c).includes('VALUATION PATH')).length, 1);
}));

test('the valuation path card follows the block directly; the block ends where the path begins', () => withBrowser(async () => {
  const root = await renderPage('XLP', { 'sectors/XLP': page(1), 'sectors/MARKET': page(1.2) });
  const titleAt = root.children.indexOf(valuationTitle(root));
  const pathAt = root.children.findIndex((node) => textOf(node).includes('VALUATION PATH · CONSENSUS'));
  const insideAt = root.children.findIndex((node) => textOf(node).startsWith('3 · INSIDE THE SECTOR'));
  assert.ok(titleAt >= 0 && pathAt > titleAt && pathAt < insideAt, 'title, then path, then section 3');
  // The block's last part is its comparison note, and the path card sits right after it.
  assert.equal(root.children[pathAt - 1].className, 'field-note');
}));

test('the top strip keeps the index figures and ABOVE 200D; the valuation figures appear once, in the block', () => withBrowser(async () => {
  const root = await renderPage('XLP', { 'sectors/XLP': page(1), 'sectors/MARKET': page(1.2) });
  const labels = withClass(root, 'stat-label').map((n) => textOf(n));
  assert.ok(labels.includes('ABOVE 200D'));
  assert.ok(labels.includes('VS S&P 500 · 3M'));
  assert.ok(labels.includes('VS S&P 500 · YTD'));
  assert.equal(labels.filter((l) => l === 'FORWARD P/E · NTM').length, 1);
  assert.equal(labels.filter((l) => l === 'EPS GROWTH · NEXT FY').length, 1);
  assert.equal(labels.filter((l) => l === 'REVENUE GROWTH · TTM').length, 1);
  assert.equal(labels.includes('TRAILING P/E · PERCENTILE'), false);
}));

test('a sub-industry page is set against its sector, with the same block', () => withBrowser(async () => {
  const root = await renderPage('XLP-PFM', { 'sectors/XLP-PFM': page(1), 'sectors/XLP': page(1.2) });
  const title = valuationTitle(root);
  assert.ok(title);
  assert.match(textOf(title), /Packaged Foods & Meats against Cons Staples/);
  assert.equal(root.children.some((node) => textOf(node).startsWith('3 · INSIDE THE SECTOR')), false);
}));

test('a page whose own history failed says so in one line, and the benchmark failing is named', () => withBrowser(async () => {
  const failed = await renderPage('XLP', { 'sectors/XLP': new Error('HTTP 404'), 'sectors/MARKET': page(1.2) });
  assert.equal(valuationTitle(failed), undefined);
  assert.match(textOf(failed), /Consumer Staples's history is unavailable: HTTP 404\./);

  const noBenchmark = await renderPage('XLP', { 'sectors/XLP': page(1), 'sectors/MARKET': new Error('HTTP 500') });
  assert.ok(valuationTitle(noBenchmark), 'the page still shows its own valuation');
  assert.match(textOf(noBenchmark), /S&P 500's history is unavailable: HTTP 500\./);
}));

test('a page file with no valuation parts gives the block\'s one gap line, not a broken section', () => withBrowser(async () => {
  const root = await renderPage('XLP', { 'sectors/XLP': {}, 'sectors/MARKET': page(1.2) });
  assert.ok(valuationTitle(root));
  assert.match(textOf(root), /Cons Staples: no filings history, so no valuation\./);
}));
