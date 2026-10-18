// SECTORS overview: the sector valuation comparison sits directly under the value
// card, the second switch is called Industries, and the old compare fold is gone.
// Rendered under node against a small fake DOM and a stub ECharts.
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

// Installs the fake DOM, ECharts and the frame clock for one test, then restores them.
function withBrowser(run) {
  const saved = {
    document: globalThis.document, window: globalThis.window, getComputedStyle: globalThis.getComputedStyle,
    requestAnimationFrame: globalThis.requestAnimationFrame,
  };
  globalThis.document = fakeDocument();
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
  globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
  globalThis.window = { echarts: { init: () => ({ setOption() {}, resize() {}, dispose() {}, on() {}, getModel() {} }) } };
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

const data = {
  as_of: '2026-10-12',
  benchmark: { returns: { '1M': 1, '3M': 2, YTD: 5, '1Y': 9 } },
  sectors: [{
    key: 'XLP', label: 'Consumer Staples', etf: 'XLP', members: 2, weight: 4.9,
    returns: { '1M': 1.5, '3M': 0.5, YTD: 7, '1Y': 6 }, vs_index: { '1M': 0.5, '3M': -1.5, YTD: 2, '1Y': -3 },
    above_200d: 60, median_drawdown: -5, revision: { '90d': 1 }, forward_pe: 19, pe_percentile: 40,
    theme: null, quadrant: 'lagging', evidence: {}, best: null, worst: null, path: null,
  }],
  sub_industries: [{
    key: 'XLP-PFM', label: 'Packaged Foods & Meats', sector_key: 'XLP', members: 2, weight: 2.0, thin: false, theme: null,
    returns: { '1M': 2, '3M': 1, YTD: 6, '1Y': 5 }, vs_index: { '1M': 1, '3M': -1, YTD: 1, '1Y': -4 },
    above_200d: 50, median_drawdown: -4, revision: { '90d': 0.5 }, forward_pe: 17, pe_percentile: 35, path: null,
  }],
  members: [
    { ticker: 'PEP', name: 'PepsiCo', sector_key: 'XLP', sub_key: 'XLP-PFM', weight: 1.0, returns: { '1M': 1, '3M': 2, YTD: 3, '1Y': 4 },
      drawdown: -3, above_200d: true, revision_90d: 0.5, forward_pe: 19, pe_percentile: 30, next_report: null, monitor: null },
  ],
  themes: [{ key: 'ai', label: 'AI infrastructure', proxy: 'SMH', members: ['NVDA'] }],
  notes: [],
};

// A loader over a map of artifacts; a name missing from the map stands for a 404.
function ctxWith(artifacts) {
  return {
    arg: undefined,
    loadArtifact: async (name) => {
      if (!(name in artifacts)) throw new Error(`${name}.json returned 404`);
      return artifacts[name];
    },
  };
}

async function renderHub(artifacts) {
  const root = new FakeNode('div');
  await renderSectors(root, data, {}, ctxWith(artifacts));
  await flush();
  return root;
}

const overviewOf = (root) => root.children.find((node) => node.attrs?.id === 'sector-view-overview');

test('the second switch is called Industries, after Rotation & sectors', () => withBrowser(async () => {
  const root = await renderHub({ valuation: null });
  const nav = root.children.find((node) => node.className === 'view-switch');
  assert.deepEqual(nav.children.map((button) => button.textContent), ['Rotation & sectors', 'Industries']);
  assert.equal(nav.children[1].attrs['aria-controls'], 'sector-view-industries');
}));

test('the overview has no compare fold, and the valuation comparison sits under the value card', () => withBrowser(async () => {
  const root = await renderHub({ valuation: null });
  assert.ok(!textOf(root).includes('Compare aggregate sector valuations'), 'the old fold is gone from the hub');
  const overview = overviewOf(root);
  const valueAt = overview.children.findIndex((node) => textOf(node).includes('VALUATION & EARNINGS GROWTH'));
  assert.ok(valueAt >= 0, 'the value card is on the overview');
  // The next node is the valuation host; the section title is drawn into it once its file loads.
  const host = overview.children[valueAt + 1];
  assert.equal(host.children[0].tagName, 'H2', 'the valuation section title follows the value card');
  assert.match(textOf(host.children[0]), /^VALUATION/);
  // The cross-sector themes card still comes after the valuation.
  const themesAt = overview.children.findIndex((node) => textOf(node).includes('CROSS-SECTOR THEMES'));
  assert.equal(themesAt, valueAt + 2, 'the themes card follows the valuation comparison');
}));

test('a valuation file that fails leaves a line in its place and the rest of the overview in place', () => withBrowser(async () => {
  const root = await renderHub({});
  const overview = overviewOf(root);
  const valueAt = overview.children.findIndex((node) => textOf(node).includes('VALUATION & EARNINGS GROWTH'));
  const host = overview.children[valueAt + 1];
  assert.match(textOf(host), /VALUATION/, 'the valuation section keeps its title');
  assert.match(textOf(host), /Index and sector P\/E were not built/, 'and says the comparison is missing');
  assert.ok(overview.children.some((node) => textOf(node).includes('CROSS-SECTOR THEMES')));
}));
