// RISK matrix: the pure helpers that arrange and describe its cells, and the
// page that draws them (18 cells, a placeholder, the drill-down opening and
// closing). The fixture follows the matrix contract in the build: one cell per
// row x column, a lead or null, and the members each cell opens.
// Rendered under node against a small fake DOM and a stub ECharts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cellsByRow, stateCounts, stateOf, stateWord, arrowFor, tagFor, isPlaceholder, scaleText } from '../../web/js/risk-matrix.js';
import renderRisk from '../../web/js/tabs/risk.js';

const ROWS = [
  { key: 'equities', label: 'EQUITIES' }, { key: 'treasuries', label: 'TREASURIES' }, { key: 'credit', label: 'CREDIT' },
  { key: 'volatility', label: 'VOLATILITY' }, { key: 'cross_asset', label: 'CROSS-ASSET' }, { key: 'macro', label: 'MACRO' },
];
const COLUMNS = [
  { key: 'structure', label: 'STRUCTURE' }, { key: 'technical', label: 'TECHNICAL' }, { key: 'fundamental', label: 'FUNDAMENTAL / PREMIUM' },
];

// A cell as the build writes it. Placeholders carry lead null and their pending text.
function cell(row, column, extra) {
  return {
    row, column, lead: null, label: null, value: null, unit: null, date: null, risk_when: null, percentile: null,
    state: 'grey', state_prev: null, change_1m: null, worse_1m: null, evidence: 'description', caution: null,
    note: null, pending: '—', members: [], ...extra,
  };
}

const CELLS = [
  cell('equities', 'structure', { lead: 'vix_term', label: 'VIX / VIX3M', value: 0.975, unit: 'ratio', date: '2026-10-16', risk_when: 'high', percentile: 91.2, state: 'elevated', state_prev: 'calm', change_1m: 0.03, worse_1m: true, pending: null, members: ['vix_term', 'vix9d_term', 'skew', 'vx_front', 'put_call', 'cftc_es', 'cftc_nq'] }),
  cell('equities', 'technical', { lead: 'spx_drawdown', label: 'S&P 500 FROM HIGH', value: -4.2, unit: 'pct', date: '2026-10-16', risk_when: 'low', percentile: 12, state: 'calm', state_prev: 'calm', change_1m: 1.1, worse_1m: false, evidence: 'tested', pending: null, members: ['spx_drawdown', 'spx_vs_200d', 'breadth_200d', 'rv20', 'realised_corr', 'cor1m', 'dispersion'] }),
  cell('equities', 'fundamental', { pending: 'Equity risk premium: forward earnings yield less the real yield (next step)' }),
  cell('treasuries', 'structure', { pending: 'Auction tails (next step)', members: ['cftc_zn'] }),
  cell('treasuries', 'technical', { lead: 'move', label: 'MOVE', value: 110, unit: 'index', date: '2026-10-16', risk_when: 'high', percentile: 97, state: 'stressed', state_prev: 'elevated', change_1m: 4.1, worse_1m: true, pending: null, members: ['move'] }),
  cell('treasuries', 'fundamental', { lead: 'real_10y', label: 'REAL 10Y', value: 1.9, unit: 'pct', date: '2026-10-16', risk_when: 'high', percentile: 80, state: 'elevated', state_prev: 'elevated', change_1m: -0.05, worse_1m: false, pending: null, note: 'Term premium to follow (next step)', members: ['real_10y'] }),
  cell('credit', 'structure', { lead: 'hyg_ief', label: 'HYG / IEF', value: 0.82, unit: 'ratio', date: '2026-10-16', risk_when: 'low', percentile: 40, state: 'calm', state_prev: 'calm', change_1m: -0.01, worse_1m: true, pending: null, members: ['hyg_ief', 'lqd_ief'] }),
  cell('credit', 'technical', { lead: 'baa10y_4w', label: 'HY OAS · 20 SESSIONS', value: 45, unit: 'bp', date: '2026-10-16', risk_when: 'high', percentile: 60, state: 'calm', state_prev: 'calm', change_1m: 12, worse_1m: true, pending: null, members: ['hy_oas'] }),
  cell('credit', 'fundamental', { lead: 'hy_oas', label: 'HY OAS', value: 390, unit: 'bp', date: '2026-10-16', risk_when: 'high', percentile: 88, state: 'elevated', state_prev: 'calm', change_1m: 25, worse_1m: true, pending: null, members: ['hy_oas', 'ccc_oas', 'ig_oas', 'baa10y'] }),
  cell('volatility', 'structure', { lead: 'vvix', label: 'VVIX', value: 92.1, unit: 'index', date: '2026-10-16', risk_when: 'high', percentile: 70, state: 'calm', state_prev: 'calm', change_1m: -2, worse_1m: false, pending: null, members: ['vvix', 'vx_front'] }),
  cell('volatility', 'technical', { lead: 'vix', label: 'VIX', value: 14.8, unit: 'pts', date: '2026-10-16', risk_when: 'high', percentile: 35, state: 'calm', state_prev: 'calm', change_1m: -0.5, worse_1m: false, evidence: 'tested', pending: null, members: ['vix', 'rv20'] }),
  cell('volatility', 'fundamental', { lead: 'vrp', label: 'VARIANCE RISK PREMIUM', value: 3.2, unit: 'pts', date: '2026-10-16', risk_when: 'low', percentile: 20, state: 'calm', state_prev: 'calm', change_1m: 0.4, worse_1m: false, pending: null, members: ['vrp'] }),
  cell('cross_asset', 'structure', { lead: 'dxy_3m', label: 'DXY 3M', value: 2.1, unit: 'pct', date: '2026-10-16', risk_when: 'high', percentile: 85, state: 'elevated', state_prev: 'calm', change_1m: 0.5, worse_1m: true, pending: null, members: ['dxy_3m'] }),
  cell('cross_asset', 'technical', { pending: 'Stock–bond correlation (next step)' }),
  cell('cross_asset', 'fundamental', { lead: 'copper_oil', label: 'COPPER / OIL', value: -0.41, unit: 'index', date: '2026-10-16', risk_when: 'low', percentile: 18, state: 'calm', state_prev: 'calm', change_1m: -0.1, worse_1m: true, evidence: 'candidate', caution: 'failed out of sample', pending: null, members: ['copper_oil', 'ovx'] }),
  cell('macro', 'structure', { lead: 'net_liquidity', label: 'NET LIQUIDITY', value: 5.81, unit: 'index', date: '2026-10-16', risk_when: 'low', percentile: 55, state: 'calm', state_prev: 'calm', change_1m: 0, worse_1m: null, pending: null, members: ['net_liquidity'] }),
  cell('macro', 'technical', { pending: '—' }),
  cell('macro', 'fundamental', { lead: 'nfci', label: 'NFCI', value: -0.32, unit: 'index', date: '2026-10-16', risk_when: 'high', percentile: 66, state: 'calm', state_prev: 'calm', change_1m: 0.02, worse_1m: true, pending: null, note: 'OFR Financial Stress Index to follow (next step)', members: ['nfci'] }),
];

// The tiles the cells open. Members without a tile here are simply not drawn.
const TILE_KEYS = ['vix_term', 'vix9d_term', 'spx_drawdown', 'move', 'real_10y', 'hy_oas', 'nfci', 'copper_oil', 'vix'];
const tile = (key) => ({
  key, label: key.toUpperCase(), core: false, unit: 'pts', value: 1, date: '2026-10-16', pct_1y: 50, pct_long: 50,
  since: '2016-01-01', risk_when: 'high', threshold: 2, breach: false, change_1d: 0, change_1w: 0,
  history: { dates: ['2016-01-04', '2026-10-16'], values: [1, 2] }, recent: { dates: ['2026-10-15', '2026-10-16'], values: [1, 2] },
  spark: null, sources: [], note: null,
});

function fixture({ matrix = true } = {}) {
  return {
    as_of: '2026-10-16',
    sentiment: { score: null },
    sections: [{ key: 'all', label: 'ALL', horizon: 'tactical', tiles: TILE_KEYS.map(tile) }],
    ...(matrix ? { matrix: { thresholds: { elevated: 75, stressed: 95 }, years: 10, rows: ROWS, columns: COLUMNS, cells: CELLS } } : {}),
  };
}

const matrix = fixture().matrix;

// ---------- pure helpers ----------

test('cells group by row in config order, three to a row, with a missing cell left as null', () => {
  const rows = cellsByRow(matrix);
  assert.deepEqual(rows.map((r) => r.key), ROWS.map((r) => r.key));
  assert.ok(rows.every((r) => r.cells.length === 3));
  assert.equal(rows[0].cells[0].lead, 'vix_term');
  assert.equal(rows[5].cells[2].lead, 'nfci');
  const gap = cellsByRow({ ...matrix, cells: CELLS.filter((c) => !(c.row === 'macro' && c.column === 'structure')) });
  assert.equal(gap[5].cells[0], null, 'a missing cell does not shift its neighbours');
  assert.equal(gap[5].cells[1].lead, null);
});

test('a placeholder or an unknown state reads as grey; a real state is kept', () => {
  assert.equal(isPlaceholder(CELLS[2]), true);
  assert.equal(stateOf(CELLS[2]), 'grey');
  assert.equal(stateOf(null), 'grey');
  assert.equal(stateOf({ lead: 'x', state: 'purple' }), 'grey');
  assert.equal(stateOf(CELLS[4]), 'stressed');
  assert.equal(stateOf(CELLS[0]), 'elevated');
});

test('the state counts add up to the cell count', () => {
  assert.deepEqual(stateCounts(CELLS), { stressed: 1, elevated: 4, calm: 9, unrated: 0, grey: 4, very_rich: 0, rich: 0, fair: 0, cheap: 0 });
  assert.equal(Object.values(stateCounts(CELLS)).reduce((a, b) => a + b, 0), 18);
});

test('the one-month arrow shows the value direction, toned by whether it moved toward risk', () => {
  assert.deepEqual(arrowFor(CELLS[0]), { arrow: '↑', tone: 'worse', word: 'worse over the month' });
  assert.deepEqual(arrowFor(CELLS[1]), { arrow: '↑', tone: 'better', word: 'better over the month' });
  assert.deepEqual(arrowFor({ change_1m: -0.5, worse_1m: false }), { arrow: '↓', tone: 'better', word: 'better over the month' });
  assert.deepEqual(arrowFor({ change_1m: -0.5, worse_1m: true }), { arrow: '↓', tone: 'worse', word: 'worse over the month' });
  assert.equal(arrowFor(CELLS[15]).arrow, '→', 'an unchanged lead gets a flat arrow');
  assert.equal(arrowFor({ change_1m: null, worse_1m: null }), null);
  assert.equal(arrowFor({ change_1m: 0.2, worse_1m: null }), null, 'no tone without a direction');
  assert.equal(arrowFor(null), null);
});

test('evidence and caution tags: a description has none, a caution is a warn tag', () => {
  assert.deepEqual(tagFor(CELLS[0]), [], 'a plain description carries no tag');
  assert.deepEqual(tagFor(CELLS[1]), [{ text: 'TESTED', tone: 'info', title: null }]);
  assert.deepEqual(tagFor(CELLS[14]), [
    { text: 'CANDIDATE', tone: 'dim', title: null },
    { text: 'FAILED OOS', tone: 'warn', title: 'failed out of sample' },
  ]);
  assert.deepEqual(tagFor(null), []);
});

// ---------- the page, under a fake DOM ----------

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
  click() { (this.listeners.click || []).forEach((fn) => fn({ type: 'click' })); }
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

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

// Installs the fake DOM, ECharts and the frame clock, runs the test, then lets
// any scheduled drawing finish before the globals are restored.
async function withBrowser(run) {
  const saved = {
    document: globalThis.document, window: globalThis.window, getComputedStyle: globalThis.getComputedStyle,
    requestAnimationFrame: globalThis.requestAnimationFrame,
  };
  globalThis.document = fakeDocument();
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
  globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
  globalThis.window = { echarts: { init: () => ({ setOption() {}, resize() {}, dispose() {}, on() {}, getModel() {} }) } };
  try {
    await run();
    await flush();
    await flush();
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

// Every node below `node` (inclusive) that satisfies the test, in document order.
function all(node, test) {
  const found = test(node) ? [node] : [];
  for (const child of node.children || []) if (child.nodeType === 1) found.push(...all(child, test));
  return found;
}

const hasClass = (node, name) => (node.className || '').split(/\s+/).includes(name);
const cellsOf = (root) => all(root, (n) => hasClass(n, 'risk-cell'));
const drillsOf = (root) => all(root, (n) => hasClass(n, 'risk-drill'));
const drillHost = (root) => all(root, (n) => hasClass(n, 'risk-drill-host'))[0];

test('the page draws 6 rows of 3 cells, a placeholder with its pending text, and a summary count', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  const rows = all(root, (n) => hasClass(n, 'risk-row'));
  assert.equal(rows.length, 6);
  assert.ok(rows.every((r) => r.children.filter((c) => hasClass(c, 'risk-cell')).length === 3));
  const cells = cellsOf(root);
  assert.equal(cells.length, 18);
  assert.ok(textOf(cells[2]).includes('Equity risk premium'), 'the placeholder shows its pending text');
  assert.equal(cells[2].listeners.click, undefined, 'a placeholder with no members does not open');
  assert.ok(textOf(root).includes('1 stressed · 4 elevated · 9 calm · 4 no reading'));
  assert.ok(textOf(root).includes('RISK · MATRIX · AS OF 2026-10-16'));
}));

test('a cell opens its drill-down, a second click closes it, and only one is open at a time', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  let cells = cellsOf(root);
  assert.equal(drillsOf(root).length, 0);
  cells[0].click();
  assert.equal(cells[0].attrs['aria-expanded'], 'true');
  assert.equal(drillsOf(root).length, 1);
  assert.ok(textOf(drillsOf(root)[0]).includes('Colour: the lead'), 'the drill states the colour rule');
  assert.ok(textOf(drillsOf(root)[0]).includes('elevated from the 75th, stressed from the 95th'), 'the rule names both lines');
  cells = cellsOf(root);
  cells[1].click();
  assert.equal(cells[0].attrs['aria-expanded'], 'false', 'opening another cell closes the first');
  assert.equal(cells[1].attrs['aria-expanded'], 'true');
  assert.equal(drillsOf(root).length, 1, 'still one drill-down');
  cells[1].click();
  assert.equal(cells[1].attrs['aria-expanded'], 'false');
  assert.equal(drillHost(root).children.length, 0, 'the same cell again closes it');
}));

test('a placeholder that names members still opens them under its pending text', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  const cells = cellsOf(root);
  assert.equal(cells[3].tagName, 'BUTTON');
  cells[3].click();
  assert.equal(drillsOf(root).length, 1);
  assert.ok(textOf(drillHost(root)).includes('No series to draw'), 'cftc_zn has no tile in this fixture');
}));

test('with no matrix in the build, the page says so and still draws the rest', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderRisk(root, fixture({ matrix: false }));
  assert.equal(cellsOf(root).length, 0);
  assert.ok(textOf(root).includes('The risk matrix was not built for this session.'));
  assert.ok(textOf(root).includes('ALL 9 SERIES BY GROUP'));
}));

test('a lead shown but not coloured has its own bucket and words', async () => {
  const cell = { lead: 'copper_oil', state: 'unrated', scale: 'none' };
  assert.equal(stateOf(cell), 'unrated');
  assert.equal(stateWord('unrated'), 'not coloured');
  assert.deepEqual(stateCounts([cell, { lead: null }]), { stressed: 0, elevated: 0, calm: 0, unrated: 1, grey: 1, very_rich: 0, rich: 0, fair: 0, cheap: 0 });
});

test('the scale text names the fixed lines, the percentile rule, or neither', async () => {
  const matrix = { years: 10, thresholds: { elevated: 75, stressed: 95 } };
  const banded = { lead: 'hyg_ief', scale: 'bands', risk_when: 'low', bands: { elevated: -2, stressed: -5 } };
  assert.match(scaleText(banded, matrix, (v) => `${v}%`), /elevated ≤ -2%, stressed ≤ -5%/);
  assert.match(scaleText({ lead: 'dxy_3m', scale: 'percentile' }, matrix), /last 10 years.*75th.*95th/);
  assert.match(scaleText({ lead: 'copper_oil', scale: 'none' }, matrix), /^Not coloured/);
  assert.equal(scaleText({ lead: null }, matrix), null);
});

test('a VALUATION cell reads in its own words and its own rule', () => {
  const cell = { lead: 'ecy', column: 'valuation', state: 'very_rich', scale: 'valuation', since: '1960-01-01' };
  assert.equal(stateOf(cell), 'very_rich');
  assert.equal(stateWord('very_rich'), 'very rich');
  const text = scaleText(cell, { valuation: { cheap: 25, rich: 75, very_rich: 90 } });
  assert.match(text, /since 1960/);
  assert.match(text, /rich when thinner than 75%.*very rich from 90%.*cheap when wider than 75%/);
  assert.match(text, /not the timing/);
});
