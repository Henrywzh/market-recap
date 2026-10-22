// FUNDAMENTAL TRENDS: the pure model (annual, quarterly, TTM, one-off and derived
// flags, $B conversion, the default mode) and a render smoke test of the grid
// against a fake DOM and a stub ECharts, as the other tab tests do.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MODES, defaultMode, hasQuarters, pointNotes, seriesFor } from '../../web/js/fundamentals-model.js';
import { renderStatements } from '../../web/js/tabs/financials.js';

const B = 1e9;
const near = (actual, expected, digits = 6) => assert.ok(Math.abs(actual - expected) < 10 ** -digits, `${actual} != ${expected}`);
const billions = (list) => list.map((v) => (v === null ? null : v * B));

// Three fiscal years. FY2023 has a net margin far below its operating margin
// (a one-off), and no short-term investments were tagged.
const annualCompany = () => ({
  columns: [
    { fiscal_year: 2023, period_end: '2023-09-30', filed: '2023-11-01' },
    { fiscal_year: 2024, period_end: '2024-09-30', filed: '2024-11-01' },
    { fiscal_year: 2025, period_end: '2025-09-30', filed: '2025-11-01' },
  ],
  values: {
    revenue: billions([100, 120, 150]),
    eps_diluted: [1.5, 2.0, 2.5],
    net_income: billions([2, 18, 30]),
    cash: billions([10, 12, 14]),
    short_term_investments: [null, null, null],
    total_debt: billions([30, 32, 34]),
    debt_current: billions([5, 0, 1]),
  },
  ratios: {
    revenue_growth: [null, 20, 25],
    gross_margin: [40, 41, 42],
    operating_margin: [20, 22, 25],
    net_margin: [2, 15, 20],
    free_cash_flow: billions([20, 25, 33]),
    fcf_margin: [20, 20.8, 22],
    roe: [10, 12, 14],
    roic: [9, 11, 13],
    net_debt: billions([20, 22, 21]),
  },
});

// Eight quarters, FY2025 Q1 to FY2026 Q4. Revenue 10..17 $B; FY2025 Q4 is
// derived (the year less nine months). Operating margin is 25 throughout;
// net margin is 20 except Q1 (10, a one-off). Index 1 is missing when `gap`.
function quarterCompany({ gap = false } = {}) {
  const revenue = [10, 11, 12, 13, 14, 15, 16, 17];
  const series = (fn) => revenue.map((r, i) => fn(r, i));
  const quarters = {
    columns: revenue.map((_, i) => ({
      period_end: `${2025 + Math.floor(i / 4)}-${String((i % 4) * 3 + 3).padStart(2, '0')}-28`,
      label: `FY${2025 + Math.floor(i / 4)} Q${(i % 4) + 1}`,
      fiscal_year: 2025 + Math.floor(i / 4),
      quarter: (i % 4) + 1,
      filed: '2026-01-01',
    })),
    values: {
      revenue: series((r, i) => (gap && i === 1 ? null : r * B)),
      gross_profit: series((r) => r * 0.4 * B),
      ebit: series((r) => r * 0.25 * B),
      net_income: series((r, i) => (i === 0 ? 1 * B : r * 0.2 * B)),
      eps_diluted: series((r) => r / 10),
      operating_cash_flow: series((r) => r * 0.3 * B),
      capex: series((r) => r * 0.05 * B),
      cash: series(() => 20 * B),
      short_term_investments: series(() => 5 * B),
      total_debt: series(() => 30 * B),
      debt_current: series(() => 2 * B),
    },
    derived: {
      revenue: series((_, i) => i === 3),
      net_income: series((_, i) => i === 3),
      operating_cash_flow: series(() => false),
    },
    ratios: {
      revenue_growth: [null, null, null, null, 40, 36, 33, 30],
      gross_margin: series(() => 40),
      operating_margin: series(() => 25),
      net_margin: series((_, i) => (i === 0 ? 10 : 20)),
      free_cash_flow: series((r) => r * 0.25 * B),
      fcf_margin: series(() => 25),
      roe: series((_, i) => 10 + i),
      roic: series((_, i) => 8 + i),
      net_debt: series(() => 3 * B),
    },
  };
  return { ...annualCompany(), quarters };
}

test('the modes are annual, quarterly and ttm, and an unknown mode is refused', () => {
  assert.deepEqual(MODES, ['annual', 'quarterly', 'ttm']);
  assert.throws(() => seriesFor(annualCompany(), 'monthly'), /unknown fundamentals mode/);
});

test('annual series labels fiscal years, converts money to $B and keeps percentages', () => {
  const s = seriesFor(annualCompany(), 'annual');
  assert.equal(s.mode, 'annual');
  assert.deepEqual(s.labels, ['FY23', 'FY24', 'FY25']);
  assert.deepEqual(s.revenue, [100, 120, 150]);
  assert.deepEqual(s.netIncome, [2, 18, 30]);
  assert.deepEqual(s.fcf, [20, 25, 33]);
  assert.deepEqual(s.netDebt, [25, 20, 21]);
  assert.deepEqual(s.growth, [null, 20, 25]);
  assert.deepEqual(s.gross, [40, 41, 42]);
  assert.deepEqual(s.operating, [20, 22, 25]);
  assert.deepEqual(s.net, [2, 15, 20]);
  assert.deepEqual(s.eps, [1.5, 2.0, 2.5]);
  assert.deepEqual(s.roe, [10, 12, 14]);
  assert.deepEqual(s.roic, [9, 11, 13]);
});

test('cash adds short-term investments and debt adds the current portion; a missing piece counts as zero', () => {
  const s = seriesFor(annualCompany(), 'annual');
  assert.deepEqual(s.cash, [10, 12, 14]);
  assert.deepEqual(s.debt, [35, 32, 35]);
  const noCash = annualCompany();
  noCash.values.cash[1] = null;
  assert.equal(seriesFor(noCash, 'annual').cash[1], null);
});

test('a one-off year is one whose net margin sits more than ten points from its operating margin', () => {
  const s = seriesFor(annualCompany(), 'annual');
  assert.deepEqual(s.oneOff, [true, false, false]);
  const missing = annualCompany();
  missing.ratios.net_margin = [null, null, null];
  assert.deepEqual(seriesFor(missing, 'annual').oneOff, [false, false, false]);
});

test('quarterly labels read FY quarter as 2026Q2 and carry the derived flags', () => {
  const s = seriesFor(quarterCompany(), 'quarterly');
  assert.equal(s.labels.length, 8);
  assert.equal(s.labels[0], '2025Q1');
  assert.equal(s.labels[7], '2026Q4');
  assert.deepEqual(s.revenue, [10, 11, 12, 13, 14, 15, 16, 17]);
  assert.deepEqual(s.derived, [false, false, false, true, false, false, false, false]);
  assert.deepEqual(s.oneOff, [true, false, false, false, false, false, false, false]);
  assert.equal(s.fcf[0], 2.5);
  assert.equal(s.growth[4], 40);
  assert.equal(s.netDebt[0], s.debt[0] - s.cash[0]);
  assert.equal(s.cash[0], 25);
});

test('TTM sums the last four quarters, recomputes margins, and starts at the first full window', () => {
  const s = seriesFor(quarterCompany(), 'ttm');
  assert.equal(s.labels.length, 5);
  assert.equal(s.labels[0], '2025Q4');
  assert.equal(s.labels[4], '2026Q4');
  assert.deepEqual(s.revenue, [46, 50, 54, 58, 62]);
  assert.equal(s.operating[4], 25);
  near(s.net[4], 20);
  assert.equal(s.gross[0], 40);
  near(s.fcf[0], 11.5);
  near(s.eps[0], 4.6);
  assert.equal(s.roe[0], 13);
  assert.equal(s.roic[0], 11);
  assert.equal(s.cash[4], 25);
  assert.equal(s.debt[4], 32);
  assert.equal(s.netDebt[4], 7);
  assert.deepEqual(s.derived, [true, true, true, true, false]);
});

test('TTM growth is against the TTM four quarters back', () => {
  const s = seriesFor(quarterCompany(), 'ttm');
  near(s.growth[4], (62 / 46 - 1) * 100);
  assert.equal(s.growth[0], null);
});

test('a missing quarter leaves every TTM window that contains it null', () => {
  const s = seriesFor(quarterCompany({ gap: true }), 'ttm');
  assert.equal(s.revenue[0], null);
  assert.equal(s.revenue[1], null);
  assert.equal(s.operating[0], null);
  assert.equal(s.net[1], null);
  assert.equal(s.fcfMargin[0], null);
  near(s.fcf[0], 11.5);
  assert.equal(s.revenue[2], 54);
  assert.equal(s.growth[4], null);
  assert.equal(s.oneOff[0], false);
});

test('a company with no quarters yields empty series rather than a crash', () => {
  const s = seriesFor(annualCompany(), 'quarterly');
  assert.deepEqual(s.labels, []);
  assert.deepEqual(s.revenue, []);
  assert.deepEqual(seriesFor(annualCompany(), 'ttm').labels, []);
});

test('defaultMode is quarterly when the artifact has quarters, annual otherwise', () => {
  assert.equal(hasQuarters(quarterCompany()), true);
  assert.equal(defaultMode(quarterCompany()), 'quarterly');
  assert.equal(defaultMode(annualCompany()), 'annual');
  assert.equal(hasQuarters({ quarters: { columns: [] } }), false);
  assert.equal(defaultMode({ quarters: { columns: [] } }), 'annual');
});

test('pointNotes names the derived year and the one-off margin gap for each period', () => {
  const quarterly = pointNotes(seriesFor(quarterCompany(), 'quarterly'));
  assert.deepEqual(quarterly[3], ['derived: year less nine months']);
  assert.deepEqual(quarterly[0], ['net income includes large non-operating or tax items']);
  assert.deepEqual(quarterly[1], []);
  const ttm = pointNotes(seriesFor(quarterCompany(), 'ttm'));
  assert.deepEqual(ttm[0], ['derived: includes a derived quarter']);
  assert.deepEqual(pointNotes(seriesFor(annualCompany(), 'annual'))[0], ['net income includes large non-operating or tax items']);
});

test('no series ever carries NaN, undefined or an object for a missing artifact', () => {
  const bare = { columns: [{ fiscal_year: 2025, period_end: '2025-09-30' }], values: {}, ratios: {} };
  for (const mode of MODES) {
    const text = JSON.stringify(seriesFor(bare, mode));
    assert.doesNotMatch(text, /NaN|undefined|Infinity/);
  }
  assert.deepEqual(seriesFor(bare, 'annual').revenue, [null]);
});

// ---- render smoke test ---------------------------------------------------

class FakeNode {
  constructor(tag) { this.nodeType = 1; this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.listeners = {}; this.className = ''; this.textContent = ''; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  get innerHTML() { return ''; }
  set innerHTML(_) { this.children = []; }
}
const all = (node, test) => [node, ...(node.children || []).flatMap((c) => (c.nodeType === 1 ? all(c, test) : []))].filter(test);
const textOf = (node) => (node.nodeType === 3 ? node.text : [node.textContent || '', ...(node.children || []).map(textOf)].filter(Boolean).join(' '));
const buttonNamed = (root, label) => all(root, (n) => n.tagName === 'BUTTON' && n.textContent === label)[0];

async function withBrowser(company, run) {
  const saved = {
    document: globalThis.document, window: globalThis.window, getComputedStyle: globalThis.getComputedStyle, fetch: globalThis.fetch,
  };
  const options = [];
  const connects = [];
  let inits = 0;
  globalThis.document = {
    createElement: (tag) => new FakeNode(tag),
    createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
    documentElement: new FakeNode('html'),
    body: { contains: () => true },
  };
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
  globalThis.window = {
    echarts: {
      init: () => {
        inits += 1;
        return { setOption(option) { options.push(option); }, resize() {}, dispose() {}, on() {}, getModel() { return null; } };
      },
      connect: (group) => connects.push(group),
    },
  };
  globalThis.fetch = async () => ({ ok: true, json: async () => company });
  const data = {
    statements: { income: { label: 'INCOME STATEMENT', items: [{ key: 'revenue', label: 'Revenue', unit: 'USD' }] } },
    ratios: [{ key: 'revenue_growth', label: 'Revenue growth', unit: 'pct' }],
    note: 'Fixture.',
  };
  try {
    const host = new FakeNode('div');
    const status = await renderStatements(host, 'TEST', data);
    await run({ host, status, options, connects, inits: () => inits });
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
}

const fixtureCompany = (withQuarters) => {
  const base = annualCompany();
  Object.assign(base, { ticker: 'TEST', name: 'Test Co', sector: 'Industrials', entity_name: 'TEST CO', cik: 1, source_ciks: [1], source_url: 'https://example.invalid/' });
  return withQuarters ? { ...base, quarters: quarterCompany().quarters } : base;
};

test('the FUNDAMENTAL TRENDS card draws six charts, defaults to QUARTERLY, and TTM redraws in place', () => withBrowser(fixtureCompany(true), async ({ host, options, connects, inits }) => {
  const text = textOf(host);
  assert.match(text, /FUNDAMENTAL TRENDS/);
  assert.doesNotMatch(text, /NaN|undefined|\[object Object\]/);
  assert.equal(options.length, 6);
  assert.deepEqual(connects, ['fundamental-trends']);
  const quarterly = buttonNamed(host, 'QUARTERLY');
  assert.equal(quarterly.attrs['aria-pressed'], 'true');
  assert.equal(quarterly.attrs.disabled, undefined);
  const before = inits();
  buttonNamed(host, 'TTM').listeners.click[0]();
  assert.equal(inits() - before, 6);
  assert.equal(buttonNamed(host, 'TTM').attrs['aria-pressed'], 'true');
  assert.equal(options.at(-1).xAxis.data.length, 5);
}));

test('the tooltip carries the derived and one-off notes; the one-off quarter gets a marker on net margin', () => withBrowser(fixtureCompany(true), async ({ options }) => {
  const revenue = options[0];
  const tip = revenue.tooltip.formatter([{ seriesName: 'Revenue', value: 10, marker: '', dataIndex: 0, axisValue: '2025Q1' }]);
  assert.match(tip, /2025Q1/);
  assert.match(tip, /net income includes large non-operating or tax items/);
  const derived = revenue.tooltip.formatter([{ seriesName: 'Revenue', value: 13, marker: '', dataIndex: 3, axisValue: '2025Q4' }]);
  assert.match(derived, /derived: year less nine months/);
  const margins = options[1];
  const net = margins.series.find((s) => s.name === 'Net margin');
  assert.equal(net.markPoint.data.length, 1);
  assert.deepEqual(net.markPoint.data[0].coord, [0, 10]);
}));

test('without quarters the grid opens on ANNUAL and the quarterly views are disabled with a reason', () => withBrowser(fixtureCompany(false), async ({ host, options }) => {
  assert.equal(options.length, 6);
  const quarterly = buttonNamed(host, 'QUARTERLY');
  assert.equal(quarterly.attrs.disabled, '');
  assert.match(quarterly.attrs.title, /not built/);
  assert.equal(buttonNamed(host, 'TTM').attrs.disabled, '');
  assert.equal(buttonNamed(host, 'ANNUAL').attrs['aria-pressed'], 'true');
  assert.deepEqual(options[0].xAxis.data, ['FY23', 'FY24', 'FY25']);
  quarterly.listeners.click[0]();
  assert.equal(options.length, 6);
  assert.equal(buttonNamed(host, 'ANNUAL').attrs['aria-pressed'], 'true');
}));
