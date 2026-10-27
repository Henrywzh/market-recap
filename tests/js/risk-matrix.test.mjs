// RISK matrix: the pure helpers that arrange and describe its cells, and the
// page that draws them (18 cells, a placeholder, the drill-down opening and
// closing). The fixture follows the matrix contract in the build: one cell per
// row x column, a lead or null, and the members each cell opens.
// Rendered under node against a small fake DOM and a stub ECharts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cellsByRow, stateCounts, stateOf, stateWord, arrowFor, tagFor, isPlaceholder, scaleText, chipWord, countParts } from '../../web/js/risk-matrix.js';
import renderRisk, { fgMarkerPercent, stripSentence } from '../../web/js/tabs/risk.js';
import { breadthTone, BREADTH_LINES } from '../../web/js/tabs/risk-context.js';

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

// A Fear & Greed reading as the build writes it; the page reads these fields.
const SENTIMENT = {
  score: 24.5, rating: 'EXTREME FEAR', date: '2026-10-16', components_counted: 1, week_ago: 40.4, month_ago: 32, year_ago: 34.6,
  components: [{ key: 'momentum', label: 'Market momentum', value: 1.58, score: 18.4 }],
  history: { dates: ['2026-10-15', '2026-10-16'], score: [30, 24.5] },
};

// The RISK NOW strip: one lead per channel, in the build's channel order. Each is a
// matrix cell with the lines it is read against (banded).
const STRIP_CHANNELS = ['EQUITIES', 'VOLATILITY', 'RATES', 'CREDIT', 'CROSS-ASSET', 'CONDITIONS'];
const stripCell = (channel, extra) => ({
  row: 'strip', column: channel.toLowerCase(), lead: 'x', label: null, value: null, unit: null, date: '2026-10-27',
  risk_when: 'high', percentile: null, state: 'calm', state_prev: 'calm', change_1m: 0, worse_1m: null,
  scale: 'bands', bands: { elevated: 0, stressed: 0 }, spark: null, evidence: 'description', caution: null,
  note: null, pending: null, members: [], channel, ...extra,
});
const STRIP = [
  stripCell('EQUITIES', { lead: 'ndx_drawdown', label: 'NDX FROM 1Y HIGH', value: -5.04, unit: 'pct', risk_when: 'low', bands: { elevated: -10, stressed: -20 }, change_1m: -4.63, worse_1m: true, spark: { start: '2025-10-28', values: [0, -2, -5.04], lines: [{ state: 'elevated', value: -10 }, { state: 'stressed', value: -20 }] } }),
  stripCell('VOLATILITY', { lead: 'vix', label: 'VIX', value: 18.39, unit: 'pts', bands: { elevated: 25, stressed: 35 }, change_1m: 1.2, worse_1m: true, spark: { start: '2025-10-28', values: [14, 18.39], lines: [] } }),
  stripCell('RATES', { lead: 'move', label: 'MOVE', value: 97.87, unit: 'index', bands: { elevated: 120, stressed: 150 }, change_1m: -3, worse_1m: false }),
  stripCell('CREDIT', { lead: 'hy_oas_1m', label: 'HY OAS 1M CHANGE', value: 8, unit: 'bp', bands: { elevated: 50, stressed: 100 }, change_1m: 2, worse_1m: true }),
  stripCell('CROSS-ASSET', { lead: 'stock_bond_corr', label: 'STOCK–BOND CORR', value: 0.27, unit: 'corr', bands: { elevated: 0.2, stressed: 0.4 }, state: 'elevated', state_prev: 'calm', change_1m: 0.1, worse_1m: true }),
  stripCell('CONDITIONS', { lead: 'nfci', label: 'NFCI', value: -0.5, unit: 'index', bands: { elevated: 0, stressed: 0.5 }, change_1m: 0.02, worse_1m: true }),
];

// A fed_model as the build writes it, enough for the stocks-vs-bonds card.
const FED = {
  as_of: '2026-10-23', dates: ['2016-10-28', '2016-11-04'],
  indices: [{ key: 'SPX', operating: { spread_real10y_pct: 0.77, spread_real10y_percentile: 1.7, spread_baa_pct: -3.0, spread_baa_percentile: 3.6, history: { spread_real10y_pct: [1, 0.77], spread_baa_pct: [-1, -3] } } }],
};

// The default page carries the strip, as the build now writes it. `strip: null`
// or `[]` is the older page; `context` adds the fed model for the stocks card.
function fixture({ matrix = true, sentiment = { score: null }, strip = STRIP, context = null } = {}) {
  return {
    as_of: '2026-10-16',
    sentiment,
    sections: [{ key: 'all', label: 'ALL', horizon: 'tactical', tiles: TILE_KEYS.map(tile) }],
    ...(strip ? { strip } : {}),
    ...(matrix ? { matrix: { thresholds: { elevated: 75, stressed: 95 }, years: 10, rows: ROWS, columns: COLUMNS, cells: CELLS } } : {}),
    ...(context ? { context } : {}),
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
  // Chart disposal asks whether a host holds a chart's node: true for itself and its descendants.
  contains(node) { return node === this || this.children.some((c) => c.nodeType === 1 && c.contains(node)); }
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
// Matrix cells only: a strip tile wears the cell look too, so it is left out here.
const cellsOf = (root) => all(root, (n) => hasClass(n, 'risk-cell') && !hasClass(n, 'risk-strip-cell'));
const drillsOf = (root) => all(root, (n) => hasClass(n, 'risk-drill'));
const drillHost = (root) => all(root, (n) => hasClass(n, 'risk-drill-host'))[0];
const stripTilesOf = (root) => all(root, (n) => hasClass(n, 'risk-strip-cell'));
// The matrix's own fold: a direct child of the page, named by its summary.
const matrixFoldOf = (root) => root.children.find((c) => c.tagName === 'DETAILS' && textOf(c.children[0]).includes('RISK MATRIX'));

test('the page draws 6 rows of 3 cells, a placeholder with its pending text, and a summary count', () => withBrowser(async () => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  await openFold(matrixFoldOf(root));
  const rows = all(root, (n) => hasClass(n, 'risk-row'));
  assert.equal(rows.length, 6);
  assert.ok(rows.every((r) => r.children.filter((c) => hasClass(c, 'risk-cell')).length === 3));
  const cells = cellsOf(root);
  assert.equal(cells.length, 18);
  assert.ok(textOf(cells[2]).includes('Equity risk premium'), 'the placeholder shows its pending text');
  assert.equal(cells[2].listeners.click, undefined, 'a placeholder with no members does not open');
  assert.ok(textOf(root).includes('1 stressed'));
  assert.ok(textOf(root).includes('4 elevated'));
  assert.ok(textOf(root).includes('9 calm'));
  assert.ok(textOf(root).includes('4 no reading'));
  assert.ok(textOf(root).includes('RISK · AS OF 2026-10-16'));
  assert.ok(textOf(root).includes('RISK MATRIX'), 'the matrix has its own title');
}));

test('a cell opens its drill-down, a second click closes it, and only one is open at a time', () => withBrowser(async () => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  await openFold(matrixFoldOf(root));
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

test('a placeholder that names members still opens them under its pending text', () => withBrowser(async () => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  await openFold(matrixFoldOf(root));
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

test('the next events for a channel skip small ones and the past', async () => {
  const { upcomingFor } = await import('../../web/js/risk-matrix.js');
  const events = [
    { title: 'CPI', date: '2026-11-12', importance: 'high', lane: 'macro', channels: ['treasuries', 'equities'] },
    { title: 'Old', date: '2026-10-01', importance: 'high', lane: 'macro', channels: ['treasuries'] },
    { title: 'Claims', date: '2026-10-22', importance: 'low', lane: 'macro', channels: ['treasuries'] },
    { title: '5-Year Note auction', date: '2026-10-28', importance: 'medium', lane: 'macro', channels: ['treasuries'] },
    { title: 'AAPL earnings', date: '2026-10-29', importance: 'medium', lane: 'single_name', channels: ['equities'] },
  ];
  assert.deepEqual(upcomingFor(events, 'treasuries', '2026-10-19').map((e) => e.title), ['5-Year Note auction', 'CPI']);
  assert.deepEqual(upcomingFor(events, 'equities', '2026-10-19').map((e) => e.title), ['CPI']);
  assert.deepEqual(upcomingFor(null, 'credit', '2026-10-19'), []);
});

// ---------- state chips, summary tones, the Fear & Greed strip ----------

test('chip words and summary parts: capitals for the cell, a tone for each count', () => {
  assert.equal(chipWord(CELLS[4]), 'STRESSED');
  assert.equal(chipWord({ lead: 'x', state: 'very_rich' }), 'VERY RICH');
  assert.equal(chipWord(CELLS[2]), 'NO READING', 'a placeholder reads as no reading');
  assert.deepEqual(countParts({ stressed: 1, elevated: 2, calm: 0 }, ['stressed', 'elevated', 'calm']), [
    { text: '1 stressed', tone: 'down' }, { text: '2 elevated', tone: 'amber' }, { text: '0 calm', tone: '' },
  ]);
  assert.deepEqual(countParts({ rich: 1, very_rich: 2 }, ['rich', 'very_rich']).map((p) => p.tone), ['amber', 'down']);
});

test('the marker sits on the 0–100 bar, pinned at the ends, and absent without a score', () => {
  assert.equal(fgMarkerPercent(24.5), 24.5);
  assert.equal(fgMarkerPercent(-3), 0);
  assert.equal(fgMarkerPercent(120), 100);
  assert.equal(fgMarkerPercent(null), null);
  assert.equal(fgMarkerPercent(undefined), null);
});

test('every cell carries a state chip, and a calm chip is the quiet one', () => withBrowser(async () => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  await openFold(matrixFoldOf(root));
  const cells = cellsOf(root);
  const chips = (cell) => all(cell, (n) => hasClass(n, 'risk-chip'));
  assert.ok(cells.every((c) => chips(c).length === 1));
  assert.equal(chips(cells[1])[0].className, 'risk-chip risk-chip-calm');
  assert.equal(chips(cells[4])[0].className, 'risk-chip risk-chip-stressed');
  assert.equal(textOf(chips(cells[4])[0]), 'STRESSED');
}));

test('the Fear & Greed strip sits above the matrix, and opens onto its card', () => withBrowser(async () => {
  const root = new FakeNode('main');
  renderRisk(root, fixture({ sentiment: SENTIMENT }));
  const strip = root.children.find((c) => hasClass(c, 'fg-summary-fold'));
  const matrixTitle = root.children.indexOf(matrixFoldOf(root));
  assert.ok(strip && root.children.indexOf(strip) < matrixTitle, 'the strip sits above the matrix fold');
  assert.ok(textOf(strip).includes('EXTREME FEAR'), 'the strip shows the rating');
  assert.ok(!textOf(strip).includes('self-computed'), 'the card is not drawn until the strip opens');
  await openFold(strip);
  assert.ok(textOf(strip).includes('self-computed'));
}));

test('with no Fear & Greed score, the strip says UNAVAILABLE and says why when opened', () => withBrowser(async () => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  const strip = root.children.find((c) => hasClass(c, 'fg-summary-fold'));
  assert.ok(textOf(strip).includes('UNAVAILABLE'));
  await openFold(strip);
  assert.ok(textOf(strip).includes('not computed this session'));
}));

test('the first screen runs: the strip, what changed, the matrix fold, then the charts fold; no quick card', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderRisk(root, fixture({ sentiment: SENTIMENT }));
  const at = (pred) => root.children.findIndex(pred);
  const strip = at((c) => hasClass(c, 'fg-summary-fold'));
  const now = at((c) => hasClass(c, 'risk-strip-block'));
  const changed = at((c) => textOf(c.children?.[0]).includes('WHAT CHANGED THIS WEEK'));
  const matrixTitle = root.children.indexOf(matrixFoldOf(root));
  const detail = at((c) => c.tagName === 'DETAILS' && textOf(c.children[0]).includes('GAUGES, CREDIT'));
  assert.ok(strip < now && now < changed && changed < matrixTitle && matrixTitle < detail, 'in that order, before the charts fold');
  assert.equal(at((c) => textOf(c).includes('MARKET CONTEXT')), -1, 'no quick MARKET CONTEXT card on the page');
  assert.ok(textOf(root).includes('GAUGES, CREDIT, VOLATILITY & CORRELATION · CHARTS'));
}));

// ---------- READ THIS FIRST, WHAT CHANGED, the library fold ----------

const GAUGE_LABELS = ['VIX / VIX3M', 'HY spread', 'SPX vs 1Y high', 'SPX vs 200-day', 'NFCI'];
const cardOf = (root, title) => root.children.find((c) => textOf(c.children?.[0]).includes(title));
// A week with no change: every lead's state equals its state a week ago, and no crossings.
const quietWeek = (f) => ({ ...f, crossed: [], matrix: { ...f.matrix, cells: f.matrix.cells.map((c) => ({ ...c, state_prev: c.state })) } });
// Opens a fold the way a click does, then lets its scheduled drawing run.
async function openFold(fold) {
  fold.open = true;
  fold.listeners.toggle.forEach((fn) => fn());
  await flush();
}
const foldNamed = (root, title) => all(root, (n) => n.tagName === 'DETAILS' && textOf(n.children[0]).includes(title))[0];
const GAUGES_FOLD = 'GAUGES, CREDIT, VOLATILITY & CORRELATION';

// The gauges live in the charts fold, which is closed until opened.
test('the five gauges open in their order inside the charts fold, each with its label, state and meaning', () => withBrowser(async () => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  await openFold(foldNamed(root, GAUGES_FOLD));
  const gauges = all(root, (n) => hasClass(n, 'gauge'));
  assert.deepEqual(gauges.map((g) => textOf(g.children[0].children[0])), GAUGE_LABELS);
  assert.equal(all(root, (n) => hasClass(n, 'risk-grid') && n.children.length === 5).length, 1, 'five gauges in one grid');
  assert.ok(textOf(gauges[0]).includes('above 1.0 = inverted'), 'the VIX curve states its meaning');
  assert.ok(textOf(gauges[4]).includes('above 0 = tighter than average'), 'NFCI states its meaning');
  for (const g of gauges.filter((g) => !hasClass(g, 'missing'))) {
    assert.match(textOf(g.children[0]), /CALM|STRESSED|ELEVATED/, 'each reading has a state tag');
  }
}));

test('a gauge with no series in the build is a dash tile, and the page still draws', () => withBrowser(async () => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  await openFold(foldNamed(root, GAUGES_FOLD));
  const missing = all(root, (n) => hasClass(n, 'missing'));
  assert.equal(missing.length, 1);
  assert.ok(textOf(missing[0]).includes('SPX vs 200-day'));
  assert.ok(textOf(missing[0]).includes('not in this build'));
  assert.ok(textOf(missing[0]).includes('—'));
  assert.ok(!textOf(root).includes('NaN') && !textOf(root).includes('undefined'));
}));

test('clicking a gauge draws its history: the chart head names the picked gauge', () => withBrowser(async () => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  await openFold(foldNamed(root, GAUGES_FOLD));
  all(root, (n) => hasClass(n, 'gauge'))[1].click();
  const picked = all(root, (n) => hasClass(n, 'gauge') && hasClass(n, 'selected'));
  assert.equal(picked.length, 1, 'one gauge is selected');
  assert.ok(textOf(picked[0]).includes('HY spread'));
  assert.ok(textOf(root).includes('HY spread · daily for the last year'), 'the chart head names it');
}));

test('WHAT CHANGED lists a crossed series with NEW, and a matrix cell whose state moved', () => withBrowser(() => {
  const root = new FakeNode('main');
  const f = fixture();
  f.crossed = [{ key: 'hy_oas', label: 'HY OAS', section: 'credit', horizon: 'tactical', value: 390, unit: 'bp', crossed: 'into' }];
  renderRisk(root, f);
  const card = cardOf(root, 'WHAT CHANGED THIS WEEK');
  assert.ok(card, 'the card is on the page');
  assert.ok(textOf(card).includes('NEW'));
  assert.ok(textOf(card).includes('HY OAS · 390bp'));
  assert.ok(textOf(card).includes('stressed'), 'the matrix cell that moved is listed');
}));

test('a quiet week says so', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderRisk(root, quietWeek(fixture()));
  assert.ok(textOf(cardOf(root, 'WHAT CHANGED THIS WEEK')).includes('Nothing crossed a line this week.'));
}));

test('the library fold is closed by default and draws when opened, and it remembers its state', () => withBrowser(async () => {
  const store = {};
  const saved = globalThis.localStorage;
  globalThis.localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
  try {
    const root = new FakeNode('main');
    renderRisk(root, fixture());
    const library = (r) => foldNamed(r, 'LIBRARY');
    assert.equal(all(root, (n) => hasClass(n, 'risk-sections')).length, 0, 'nothing drawn while closed');
    assert.ok(!library(root).open, 'closed by default');
    await openFold(library(root));
    assert.ok(store['risk.fold.library'] === 'open', 'the open state is kept');
    assert.ok(all(root, (n) => hasClass(n, 'risk-sections')).length > 0, 'drawn on open');

    const again = new FakeNode('main');
    renderRisk(again, fixture());
    const reopened = library(again);
    assert.equal(reopened.open, true, 'a stored open fold opens again');
  } finally {
    if (saved === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = saved;
  }
}));

// ---------- the RISK NOW strip, the matrix fold, the stocks-vs-bonds card ----------

test('the strip sentence counts the calm channels and names each one that is not', () => {
  assert.equal(stripSentence(STRIP), '5 calm · 1 elevated (CROSS-ASSET: stock–bond corr 0.27)');
  assert.equal(stripSentence(STRIP.map((c) => ({ ...c, state: 'calm' }))), 'All six channels calm.');
  const grey = STRIP.map((c) => (c.channel === 'RATES' ? { ...c, lead: null, state: 'grey' } : c));
  assert.equal(stripSentence(grey), '4 calm · 1 no reading (RATES: move 97.87) · 1 elevated (CROSS-ASSET: stock–bond corr 0.27)');
});

test('breadth bar tone: healthy from 60, mixed from 40, weak below 40, and no reading has none', () => {
  assert.deepEqual(BREADTH_LINES, { healthy: 60, mixed: 40 });
  assert.equal(breadthTone(100), 'healthy');
  assert.equal(breadthTone(60), 'healthy');
  assert.equal(breadthTone(59.99), 'mixed');
  assert.equal(breadthTone(40), 'mixed');
  assert.equal(breadthTone(39.99), 'weak');
  assert.equal(breadthTone(0), 'weak');
  assert.equal(breadthTone(null), null);
  assert.equal(breadthTone(Number.NaN), null);
});

test('the strip draws six tiles, one per channel, in the build order, with its counting sentence', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  const tiles = stripTilesOf(root);
  assert.equal(tiles.length, 6);
  assert.deepEqual(tiles.map((t) => textOf(t.children[0])), STRIP_CHANNELS);
  assert.ok(textOf(root).includes('RISK NOW · ONE LEAD PER CHANNEL'));
  assert.ok(textOf(root).includes('5 calm · 1 elevated (CROSS-ASSET: stock–bond corr 0.27)'));
  assert.ok(tiles[4].className.split(' ').includes('elevated'), 'the tile takes its state tint');
  assert.ok(textOf(tiles[0]).includes('elev ≤ -10.0% · stress ≤ -20.0%'), 'the dim line names the lines');
}));

test('the matrix is a closed fold: nothing is drawn until it opens, then all 18 cells', () => withBrowser(async () => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  const fold = matrixFoldOf(root);
  assert.ok(fold, 'the fold sits on the page');
  assert.equal(textOf(fold.children[0]), 'ALL 18 LEADS · RISK MATRIX');
  assert.ok(!fold.open, 'closed by default');
  assert.equal(cellsOf(root).length, 0, 'the matrix is not drawn while closed');
  await openFold(fold);
  assert.equal(cellsOf(root).length, 18);
  assert.ok(textOf(fold).includes('4 elevated'));
}));

test('a strip tile opens the matrix fold, scrolls to it, and draws it once', () => withBrowser(async () => {
  const root = new FakeNode('main');
  renderRisk(root, fixture());
  const fold = matrixFoldOf(root);
  let scrolled = false;
  fold.scrollIntoView = () => { scrolled = true; };
  stripTilesOf(root)[4].click();
  assert.equal(fold.open, true, 'the fold opens');
  assert.equal(scrolled, true, 'the page scrolls to it');
  await flush();
  assert.equal(cellsOf(root).length, 18, 'the matrix is drawn');
  stripTilesOf(root)[0].click();
  assert.equal(cellsOf(root).length, 18, 'a second tile does not draw it again');
}));

test('without a strip, the page keeps its older first screen: the counts and the matrix, open', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderRisk(root, fixture({ strip: null }));
  assert.equal(stripTilesOf(root).length, 0);
  assert.equal(textOf(root).includes('RISK NOW'), false);
  assert.ok(textOf(root).includes('1 stressed'));
  assert.equal(cellsOf(root).length, 18, 'drawn on the first screen');
  assert.equal(matrixFoldOf(root), undefined, 'no fold');
}));

test('an empty strip falls back to the same older first screen', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderRisk(root, fixture({ strip: [] }));
  assert.equal(stripTilesOf(root).length, 0);
  assert.equal(cellsOf(root).length, 18);
}));

test('the stocks-vs-bonds card is open on the page, after the matrix, with no fed-model fold', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderRisk(root, fixture({ context: { fed_model: FED } }));
  const bonds = root.children.find((c) => textOf(c.children?.[0]).includes('STOCKS vs BONDS'));
  assert.ok(bonds, 'the card is on the page');
  assert.notEqual(bonds.tagName, 'DETAILS', 'it is not folded');
  assert.ok(root.children.indexOf(bonds) > root.children.indexOf(matrixFoldOf(root)), 'after the matrix');
  assert.equal(textOf(root).includes('VALUATION · EARNINGS'), false, 'the old valuation fold is gone');
}));
