// SIZE & STYLE and K-SHAPE pages, rendered under node against a small fake DOM
// and a stub ECharts. The checks: the valuation block and the ratio chart are
// drawn at once, the DETAIL fold is closed and its charts wait until it opens,
// and an open fold stays open when the window switch rebuilds the page.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { detailFold } from '../../web/js/sizek-model.js';
import { el } from '../../web/js/fmt.js';

class FakeNode {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this.open = false;
  }
  setAttribute(key, value) {
    this.attrs[key] = String(value);
    if (key === 'open') this.open = true;
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type) { (this.listeners[type] || []).forEach((fn) => fn({ type })); }
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
  globalThis.window = { echarts: { init: (node) => { node.inits = (node.inits || 0) + 1; return { setOption() {}, resize() {}, dispose() {} }; } } };
  return Promise.resolve().then(run).finally(() => {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  });
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

// Every node under `node`, with whether it sits inside a DETAILS element.
function walk(node, visit, inside = false) {
  for (const child of node.children || []) {
    if (!child || child.nodeType !== 1) continue;
    visit(child, inside);
    walk(child, visit, inside || child.tagName === 'DETAILS');
  }
}

function collect(root) {
  const charts = { outside: [], folded: [] };
  const folds = [];
  const buttons = [];
  walk(root, (node, inside) => {
    if (node.className === 'chart') (inside ? charts.folded : charts.outside).push(node);
    if (node.tagName === 'DETAILS') folds.push(node);
    if (node.tagName === 'BUTTON') buttons.push(node);
  });
  return { charts, folds, buttons };
}

const DATES = ['2020-12-31', '2021-06-30', '2025-10-10', '2026-01-02', '2026-07-13', '2026-09-14', '2026-10-12'];
const RATIO = [1, 1.1, 1.2, 1.15, 1.3, 1.25, 1.4];

// One arm of a pair: a flat-ish price and a P/E that moves with it, so the
// valuation block has a split to draw.
function arm(key, label, price, pe) {
  return { key, label, basket: { dates: DATES, price, pe, earnings: price.map((p, i) => p / pe[i]), coverage: 1, names: [], stats: {} } };
}

function sizekData() {
  const big = [10, 11, 12, 11.5, 13, 12.5, 14];
  const small = [10, 10, 10, 10, 10, 10, 10];
  return {
    as_of: '2026-10-12', settings: {},
    inputs: { prices_through: '2026-10-12', no_prices: [] }, notes: [],
    views: [{
      key: 'value_growth', label: 'VALUE / GROWTH', big_name: 'IWD', small_name: 'IWF', big_arm: 'VALUE', small_arm: 'GROWTH', note: null,
      price: {
        dates: DATES, big, small, ratio: RATIO, since: '2020-12-31', through: '2026-10-12', sessions: 1500,
        ratio_now: 1.4, ratio_percentile: 80, extremes: { from_high_pct: 0, high: 1.4, high_date: '2026-10-12', from_low_pct: 40, low: 1.0, low_date: '2020-12-31' },
        spreads: [{ period: '1M', top: 1, bottom: 0.5, spread: 0.5 }],
      },
      gap: { window: '1Y', dates: DATES, gap: [0, 1, -1, 2, 0.5, -0.5, 1], windows: 7, first: '2021-06-30', now: 1, percentile: 60, share_big_ahead: 55, longest_big: 2, longest_small: 1 },
      years: [{ year: 2021, big: 10, small: 5, gap: 5, partial_start: false, to_date: false }],
      fundamentals: { arms: [arm('big', 'VALUE', big, [10, 11, 12, 11.5, 13, 12.5, 14]), arm('small', 'GROWTH', small, [20, 20, 20, 20, 20, 20, 20])] },
    }],
  };
}

function kshapeData() {
  const top = [10, 11, 12, 13, 14, 15, 16];
  const bottom = [20, 19, 18, 18, 17, 17, 16];
  return {
    as_of: '2026-10-12', settings: { pe_min_share: 0.5, pe_cap: 100 },
    inputs: { prices_through: '2026-10-12', valuation_built: true }, notes: [],
    views: [{
      key: 'cruise', label: 'CRUISE', top: ['VIK'], bottom: ['CCL'], note: null,
      price: { dates: DATES, top, bottom, ratio: top.map((v, i) => v / bottom[i] / (top[0] / bottom[0])), since: '2020-12-31', ratio_now: 1.5, ratio_percentile: 70, sessions: 1500, spreads: [{ period: '1M', top: 1, bottom: 0, spread: 1 }] },
      pe: {
        dates: DATES, top, bottom, ratio: [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1], covered: { top: ['VIK'], bottom: ['CCL'] },
        now: { ratio: 1.1, top: 16, bottom: 14.5 }, ratio_median: 0.9, ratio_p10: 0.6, ratio_p90: 1.1, dates_used: 7, ratio_percentile: 80,
      },
      eps: { dates: DATES.slice(1), top: [5, 6, 7, 8, 9, 10], bottom: [1, 2, 3, 4, 5, 6], gap: [4, 4, 4, 4, 4, 4], latest: '2026-06-30' },
      names: [{ ticker: 'VIK', leg: 'top', pe_forward: 19.8, forward_source: 'consensus', pe_percentile: 60, eps_growth_this_year: 24.2, revenue_growth: 9, ret_3m: -2, ret_1y: 30, first_price: '2024-05-01' }],
      now: { pe_forward_ratio: 1.5, pe_forward_top: 19.8, pe_forward_bottom: 13.2, eps_growth_this_year_top: 24.2, eps_growth_this_year_bottom: 8 },
      fundamentals: { arms: [arm('top', 'TOP', top, [10, 11, 12, 13, 14, 15, 16]), arm('bottom', 'BOTTOM', bottom, [20, 19, 18, 18, 17, 17, 16])] },
    }],
  };
}

// The chart nodes of a page that were drawn: the main flow and the fold.
function drawnCounts(root) {
  const { charts, folds } = collect(root);
  return {
    outside: charts.outside.filter((c) => c.inits).length,
    folded: charts.folded.filter((c) => c.inits).length,
    foldCount: folds.length,
    charts,
    folds,
  };
}

test('the DETAIL fold starts closed, and it holds its charts until the reader opens it', async () => {
  await withBrowser(async () => {
    let painted = 0;
    const state = { open: false };
    const node = detailFold(state, () => { painted += 1; }, [el('div', { text: 'inside' })]);
    await flush();
    assert.equal(painted, 0, 'a closed fold draws nothing');
    assert.equal(node.tagName, 'DETAILS');
    assert.equal(node.className, 'fold pair-detail');
    assert.equal(node.children[0].textContent, 'DETAIL');
    node.open = true;
    node.dispatch('toggle');
    assert.equal(painted, 1);
    assert.equal(state.open, true);
    node.open = false;
    node.dispatch('toggle');
    assert.equal(painted, 1, 'closing does not draw');
    assert.equal(state.open, false);
  });
});

test('an open fold is drawn when it is built, so a window switch keeps its charts', async () => {
  await withBrowser(async () => {
    let painted = 0;
    const node = detailFold({ open: true }, () => { painted += 1; }, []);
    await flush();
    assert.equal(painted, 1);
    assert.equal(node.attrs.open, '');
  });
});

test('SIZE & STYLE: the ratio and valuation charts are drawn, the folded charts wait for the fold', async () => {
  await withBrowser(async () => {
    const mod = await import('../../web/js/tabs/sizek.js');
    const root = new FakeNode('div');
    mod.default(root, sizekData(), {}, {});
    await flush();
    const before = drawnCounts(root);
    assert.equal(before.foldCount, 1, 'one fold on the page');
    assert.equal(before.folds[0].open, false, 'the fold is closed');
    assert.equal(before.folds[0].children[0].textContent, 'DETAIL');
    assert.ok(before.outside >= 1, 'the ratio chart and the valuation charts are drawn');
    assert.equal(before.folded, 0, 'no folded chart is drawn while closed');

    before.folds[0].open = true;
    before.folds[0].dispatch('toggle');
    await flush();
    const after = drawnCounts(root);
    assert.ok(after.folded >= 2, 'the arm chart and the rolling gap are drawn when the fold opens');
  });
});

test('SIZE & STYLE: a window switch rebuilds the page and keeps the fold open', async () => {
  await withBrowser(async () => {
    const mod = await import('../../web/js/tabs/sizek.js');
    const root = new FakeNode('div');
    mod.default(root, sizekData(), {}, {});
    await flush();
    let drawn = drawnCounts(root);
    drawn.folds[0].open = true;
    drawn.folds[0].dispatch('toggle');
    await flush();
    const host = root.children[root.children.length - 1];
    const oneYear = collect(host).buttons.find((b) => b.textContent === '1Y');
    assert.ok(oneYear, 'the 1Y window is offered');
    oneYear.dispatch('click');
    await flush();
    drawn = drawnCounts(root);
    assert.equal(drawn.folds[0].open, true, 'the fold stays open after the switch');
    assert.ok(drawn.folded >= 2, 'the folded charts are drawn again for the new window');
  });
});

test('K-SHAPE: the ratio and valuation charts are drawn, the legs, P/E and EPS charts wait for the fold', async () => {
  await withBrowser(async () => {
    const mod = await import('../../web/js/tabs/kshape.js');
    const root = new FakeNode('div');
    mod.default(root, kshapeData(), {}, {});
    await flush();
    const before = drawnCounts(root);
    assert.equal(before.foldCount, 1);
    assert.equal(before.folds[0].open, false);
    assert.ok(before.outside >= 1);
    assert.equal(before.folded, 0);
    before.folds[0].open = true;
    before.folds[0].dispatch('toggle');
    await flush();
    const after = drawnCounts(root);
    assert.ok(after.folded >= 3, 'the legs chart, the P/E charts and the EPS chart are drawn on opening');
  });
});

// All the text under a node, as one string.
function textOf(node) {
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(textOf)].join(' ');
}

test('SIZE & STYLE and K-SHAPE: the VALUATION block names the two arms, and an arm with no filings gives the page\'s reason', async () => {
  await withBrowser(async () => {
    const sizek = await import('../../web/js/tabs/sizek.js');
    const kshape = await import('../../web/js/tabs/kshape.js');
    const size = new FakeNode('div');
    sizek.default(size, sizekData(), {}, {});
    await flush();
    assert.match(textOf(size), /VALUATION\s+VALUE against GROWTH/);

    const kshapeRoot = new FakeNode('div');
    kshape.default(kshapeRoot, kshapeData(), {}, {});
    await flush();
    assert.match(textOf(kshapeRoot), /VALUATION\s+TOP against BOTTOM/);

    const missing = sizekData();
    missing.views[0].fundamentals = { missing: 'IWF holdings could not be fetched.' };
    const reason = new FakeNode('div');
    sizek.default(reason, missing, {}, {});
    await flush();
    assert.match(textOf(reason), /VALUATION\s+VALUE against GROWTH: what the market pays, what the business earns\s+IWF holdings could not be fetched\./);
    assert.doesNotMatch(textOf(reason), /no filings history, so no valuation/, 'the block\'s own line is not used in place of the reason');
  });
});

test('K-SHAPE: a leg left out for lack of filings is named under the valuation block', async () => {
  await withBrowser(async () => {
    const kshape = await import('../../web/js/tabs/kshape.js');
    const data = kshapeData();
    data.views[0].fundamentals.arms[1].note = 'Left out for lack of a filings history: CCL.';
    const root = new FakeNode('div');
    kshape.default(root, data, {}, {});
    await flush();
    assert.match(textOf(root), /Left out for lack of a filings history: CCL\./);
  });
});
