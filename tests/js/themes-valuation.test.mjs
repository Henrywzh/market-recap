// THEMES: each group's VALUATION block against the S&P 500, the one line that
// says which bellwethers it is built from, and the reason a group with too few
// names gives instead. Rendered under node against a small fake DOM and a stub ECharts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import renderThemes, { valuationNote, themeValuation } from '../../web/js/tabs/themes.js';

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
  body: { contains: () => true },
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

function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(textOf)].filter(Boolean).join(' ');
}

const DATES = ['2024-10-04', '2025-10-03', '2026-10-02'];

// A VALUATION basket as the build writes it: weekly P/E history, its outlook and its history.
const basket = {
  valuation: {
    dates: DATES, pe: [18, 20, 22],
    stats: { median: 20, p25: 19, p75: 21, current: 22, percentile: 75, weeks: 150 },
    price: [100, 110, 120], earnings: [5.5, 5.5, 5.45],
  },
  outlook: { forward_pe: 21, eps_growth_next: 9, revenue_growth: 6 },
  history: { years: [2024, 2025], revenue_growth: [4, 6], gross_margin: [30, 31], operating_margin: [12, 13] },
};

// Two groups: CRUISE has a basket built from three names with one left out; DEFENSE
// has too few names with filings, so it carries only the reason.
const data = {
  as_of: '2026-10-12',
  calendar_days: 42,
  groups: [
    {
      key: 'cruise', label: 'Cruise lines', proxy: 'CRUZ', proxy_is_etf: false,
      calendar: [], bellwethers: [], pairs: [], run_in: {},
      ...basket, valuation_names: ['CCL', 'RCL', 'NCLH'], valuation_missing: ['VIK'],
    },
    {
      key: 'defense', label: 'Defense primes', proxy: 'ITA', proxy_is_etf: true,
      calendar: [], bellwethers: [], pairs: [], run_in: {},
      valuation_note: 'Fewer than two names with filings in this build, so no P/E basket.',
    },
  ],
  studies: {},
};

const MARKET = {
  valuation: { dates: DATES, pe: [16, 17, 18], stats: { median: 17, p25: 16, p75: 18, current: 18, percentile: 60, weeks: 520 },
    price: [100, 105, 110], earnings: [6, 6.2, 6.1] },
  outlook: { forward_pe: 19.5, eps_growth_next: 12, revenue_growth: 7 },
  history: { years: [2024, 2025], revenue_growth: [5, 6], gross_margin: [44, 45], operating_margin: [23, 24] },
};

function ctxWith(arg) {
  return {
    arg,
    loadArtifact: async (name) => {
      if (name === 'sectors/MARKET') return MARKET;
      throw new Error(`${name}.json returned 404`);
    },
  };
}

test('the note names the bellwethers a basket is built from, and any left out', () => {
  assert.equal(valuationNote({ valuation: {}, valuation_names: ['CCL', 'RCL'], valuation_missing: ['VIK'] }),
    'Built from CCL, RCL, weighted by market value. Left out: VIK.');
  assert.equal(valuationNote({ valuation: {}, valuation_names: ['CCL'], valuation_missing: [] }), 'Built from CCL, weighted by market value.');
  // An older build with no names still says how it is weighted.
  assert.equal(valuationNote({ valuation: {} }), 'Weighted by market value.');
});

test('a group with no basket gives the build\'s own reason, or a plain one when it gives none', () => {
  assert.equal(valuationNote({ valuation: null, valuation_note: 'Too few names.' }), 'Too few names.');
  assert.equal(valuationNote({}), 'No P/E basket for this theme in this build.');
});

test('a group with nothing at all gives one gap line, carrying the build\'s reason', () => withBrowser(() => {
  const nodes = themeValuation({ label: 'Defense primes', valuation_note: 'Too few names.' }, { page: MARKET, error: null });
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].className, 'gap');
  assert.equal(textOf(nodes[0]), 'Too few names.');
}));

test('a theme whose S&P 500 page will not load keeps its own section and says why in one line', () => withBrowser(() => {
  const nodes = themeValuation(data.groups[0], { page: null, error: 'HTTP 500' });
  assert.ok(nodes.some((n) => n.tagName === 'H2'), 'the theme\'s own section is still drawn');
  assert.ok(nodes.some((n) => textOf(n) === "S&P 500's history is unavailable: HTTP 500."));
}));

test('a theme with a basket draws its VALUATION sub-tab against the S&P 500 and names its bellwethers', () => withBrowser(async () => {
  const root = new FakeNode('div');
  await renderThemes(root, data, {}, ctxWith('CRUISE.VALUATION'));
  await flush();
  const title = root.children.flatMap((n) => n.children || []).find((n) => n.tagName === 'H2' && textOf(n).startsWith('VALUATION'));
  assert.ok(title, 'the VALUATION section is on the theme page');
  assert.match(textOf(title), /Cruise lines against S&P 500/);
  assert.match(textOf(root), /Built from CCL, RCL, NCLH, weighted by market value\. Left out: VIK\./);
}));

test('the theme with too few names shows its reason in one line, and no VALUATION section', () => withBrowser(async () => {
  const root = new FakeNode('div');
  await renderThemes(root, data, {}, ctxWith('DEFENSE.VALUATION'));
  await flush();
  const text = textOf(root);
  assert.match(text, /Fewer than two names with filings in this build, so no P\/E basket\./);
  const titles = root.children.flatMap((n) => n.children || []).filter((n) => n.tagName === 'H2' && textOf(n).startsWith('VALUATION'));
  assert.equal(titles.length, 0);
}));
