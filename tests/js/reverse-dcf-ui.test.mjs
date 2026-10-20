import { test } from 'node:test';
import assert from 'node:assert/strict';
import render from '../../web/js/tabs/reverse-dcf.js';

class Node {
  constructor(tag) { this.nodeType = 1; this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.listeners = {}; this.textContent = ''; this.value = ''; }
  setAttribute(key, value) { this.attrs[key] = String(value); if (key === 'value') this.value = String(value); }
  getAttribute(key) { return this.attrs[key]; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  append(...nodes) { nodes.forEach((node) => { node.parent = this; this.children.push(node); }); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  after(node) { const p = this.parent; p.children.splice(p.children.indexOf(this) + 1, 0, node); node.parent = p; }
}
const text = (n) => [n.textContent || n.text || '', ...(n.children || []).map(text)].join(' ');
const all = (n) => [n, ...(n.children || []).flatMap(all)];
const byId = (root, id) => all(root).find((n) => n.attrs?.id === id);
const button = (root, label) => all(root).find((n) => n.tagName === 'BUTTON' && n.textContent === label);
const settings = { excluded_sectors: ['Financials', 'Real Estate', 'Utilities'], excluded_subindustries: ['Biotechnology'], annual_max_age_days: 550, capital_warning_share: 0.1, growth_pct: 5, wacc_pct: 9, tax_pct: 25, terminal_growth_pct: 2.5, terminal_roic_pct: 15, net_investment_pct: 5, years: 10, margin_transition_years: 5, growth_grid_pct: [0, 5, 10], margin_grid_pct: [10, 20, 30], margin_bounds_pct: [0, 100] };
Object.assign(settings, { reference_years: 5, peer_min_count: 3, peer_max_age_days: 400, history_cagr_years: [3, 5], chart_growth_step_pct: 1, sensitivity_wacc_shifts_pp: [-2, 0, 2], sensitivity_investment_shifts_pp: [-2, 0, 2] });
const row = { ticker: 'TEST', name: 'Test issuer', sector: 'Industrials', sub_sector: 'Machinery', price: 10, ev: 150e9, market_cap: 140e9, period_end: '2026-06-30', filed: '2026-08-01', debt_basis: 'long-term + current debt', operating_margin: 20 };
const annual = { ticker: 'TEST', columns: [{ period_end: '2026-06-30', filed: '2026-08-01' }], values: { revenue: [100e9], ebit: [20e9], capex: [2e9] }, source_url: 'https://data.sec.gov/' };

async function fixture(run, { rows = [row], files = {}, asOf = '2026-10-16', manifestDate = asOf, override, reverse = settings, data = {} } = {}) {
  const saved = globalThis.document;
  globalThis.document = { createElement: (tag) => new Node(tag), createTextNode: (s) => ({ nodeType: 3, text: String(s) }) };
  const root = new Node('main');
  const requests = [];
  const defaults = { valuation: { as_of: asOf, rows }, financials: { as_of: asOf, available: rows.map((r) => ({ ticker: r.ticker, name: r.name })) }, 'financials/TEST': annual, ...files };
  const ctx = { arg: 'TEST', setArg() {}, loadArtifact: async (key) => { requests.push(key); if (override) return override(key, defaults); if (!(key in defaults)) throw new Error('missing file'); return defaults[key]; } };
  try { await render(root, { reverse, as_of: asOf, ...data }, { as_of: manifestDate }, ctx); await run(root, requests, ctx); }
  finally { if (saved === undefined) delete globalThis.document; else globalThis.document = saved; }
}

test('real financials metadata uses ticker objects and draws a populated scenario map', async () => fixture(async (root, requests) => {
  assert.ok(requests.includes('financials/TEST'));
  assert.match(text(root), /REQUIRED MARGIN/);
  assert.equal(all(root).filter((n) => n.className?.includes('reverse-cell')).length, 9);
  assert.doesNotMatch(text(root), /NaN|undefined|not extracted/);
}));
test('editing WACC changes the result and reset restores the assumptions', async () => fixture(async (root) => {
  const before = text(all(root).find((n) => n.className === 'reverse-results'));
  const input = byId(root, 'reverse-wacc'); input.value = '12'; input.listeners.input[0]();
  assert.notEqual(text(all(root).find((n) => n.className === 'reverse-results')), before);
  button(root, 'RESET ASSUMPTIONS').listeners.click[0]();
  assert.equal(byId(root, 'reverse-wacc').value, 9);
}));
test('clearing a required input removes results rather than converting blank to zero', async () => fixture(async (root) => {
  const input = byId(root, 'reverse-netInvestment'); input.value = ''; input.listeners.input[0]();
  assert.match(text(root), /No scenario map/);
  assert.doesNotMatch(text(all(root).find((n) => n.className === 'reverse-results')), /REQUIRED MARGIN/);
}));
test('selecting a grid cell updates the real scenario inputs', async () => fixture(async (root) => {
  const cell = all(root).find((n) => n.attrs?.['aria-label']?.startsWith('Growth 10%, margin 30%'));
  cell.listeners.click[0]();
  assert.equal(byId(root, 'reverse-growth').value, 10);
  assert.equal(byId(root, 'reverse-margin').value, 30);
}));
test('specialised businesses have no operating controls or stale map', async () => fixture(async (root) => {
  assert.match(text(root), /specialised model/);
  assert.equal(byId(root, 'reverse-wacc'), undefined);
}, { rows: [{ ...row, sector: 'Financials' }] }));
test('unknown debt leaves EV empty until an explicit manual assumption is entered', async () => fixture(async (root) => {
  assert.equal(byId(root, 'reverse-ev').value, '');
  assert.match(text(root), /No scenario map/);
  assert.match(text(root), /MISSING PROXY · REVIEW REQUIRED/);
  const ev = byId(root, 'reverse-ev'); ev.value = '150'; ev.listeners.input[0]();
  assert.match(text(root), /REQUIRED MARGIN/);
}, { rows: [{ ...row, debt_basis: 'no debt tagged' }] }));
test('different input sessions block the model; an older consistent pair is labelled', async () => {
  await fixture(async (root) => { assert.match(text(root), /artifact sessions differ/); assert.equal(byId(root, 'reverse-wacc'), undefined); }, { files: { financials: { as_of: '2026-10-15' } } });
  await fixture(async (root) => { assert.match(text(root), /HISTORICAL INPUT SNAPSHOT/); assert.ok(byId(root, 'reverse-wacc')); }, { manifestDate: '2026-10-19' });
});
test('unknown ticker clears the previous company without making an unlisted request', async () => fixture(async (root, requests) => {
  const input = byId(root, 'reverse-ticker'); input.value = 'UNKNOWN';
  await button(root, 'LOAD').listeners.click[0]();
  assert.match(text(root), /no replacement ticker/);
  assert.equal(byId(root, 'reverse-wacc'), undefined);
  assert.ok(!requests.includes('financials/UNKNOWN'));
}));
test('late company responses do not overwrite a more recent selection', async () => {
  let resolveSlow;
  await fixture(async (root) => {
    const input = byId(root, 'reverse-ticker');
    input.value = 'SLOW'; const pending = button(root, 'LOAD').listeners.click[0]();
    input.value = 'TEST'; await button(root, 'LOAD').listeners.click[0]();
    resolveSlow({ ...annual, ticker: 'SLOW' }); await pending;
    assert.match(text(root), /Test issuer/);
    assert.equal(input.value, 'TEST');
  }, { rows: [row, { ...row, ticker: 'SLOW', name: 'Slow issuer' }], override: (key, files) => key === 'financials/SLOW' ? new Promise((resolve) => { resolveSlow = resolve; }) : Promise.resolve(files[key]) });
});

test('assumption origins are explicit, edit updates origin, reset restores historical seed / shared default', async () => fixture(async (root) => {
  assert.match(text(root), /SHARED ILLUSTRATIVE DEFAULT/);
  assert.match(text(root), /COMPANY HISTORY · STARTING SEED/);
  const wacc = byId(root, 'reverse-wacc'); wacc.value = '12'; wacc.listeners.input[0]();
  assert.match(text(root), /USER SCENARIO/);
  button(root, 'RESET ASSUMPTIONS').listeners.click[0]();
  assert.doesNotMatch(text(root), /USER SCENARIO/);
}));

test('a short history does not invent CAGR, peer benchmarks or probability', async () => fixture(async (root) => {
  assert.match(text(root), /3Y CAGR —/);
  assert.match(text(root), /5Y CAGR —/);
  assert.match(text(root), /not confidence intervals/);
  assert.match(text(root), /FY revenue consensus unavailable/);
  assert.match(text(root), /TERMINAL PV \/ MODEL EV/);
}));

test('historical selector preserves the scenario and numeric sensitivity source updates with WACC', async () => fixture(async (root) => {
  const before = text(root);
  const selector = byId(root, 'reverse-history-metric'); selector.value = 'growth'; selector.listeners.change[0]();
  assert.equal(byId(root, 'reverse-wacc').value, '9');
  const wacc = byId(root, 'reverse-wacc'); wacc.value = '12'; wacc.listeners.input[0]();
  assert.notEqual(text(root), before);
  assert.match(text(root), /14.0%/); // +2 pp WACC row, not stale initial 11%.
}));

test('required margin beyond historical gross margin is a conditional structure warning, not a valuation verdict', async () => fixture(async (root) => {
  const ev = byId(root, 'reverse-ev'); ev.value = '800'; ev.listeners.input[0]();
  assert.match(text(root), /price-required operating margin also exceeds the latest gross margin/);
  assert.match(text(root), /different growth \/ discount \/ investment assumptions/);
}, { files: { 'financials/TEST': { ...annual, values: { ...annual.values, cost_of_revenue: [60e9] } } } }));

test('changing horizon updates history description instead of retaining initial model-year label', async () => fixture(async (root) => {
  const years = byId(root, 'reverse-years'); years.value = '7'; years.listeners.input[0]();
  assert.match(text(root), /M1–M7 scenario/);
  assert.doesNotMatch(text(root), /M1–M10 scenario/);
}));

test('older config metadata requests a rebuild instead of inventing reference settings or throwing', async () => fixture(async (root, requests) => {
  assert.match(text(root), /Rebuild DCF metadata/);
  assert.equal(requests.length, 0);
  assert.equal(byId(root, 'reverse-wacc'), undefined);
}, { reverse: { ...settings, history_cagr_years: undefined } }));

test('guided reading order leads with history, then conditional requirements, then sensitivity', async () => fixture(async (root) => {
  const copy = text(root);
  const one = copy.indexOf('01 · WHAT HAS THE COMPANY DELIVERED?');
  const two = copy.indexOf('02 · WHAT DOES THIS PRICE REQUIRE?');
  const three = copy.indexOf('03 · HOW SENSITIVE IS THE ANSWER?');
  assert.ok(one > 0 && one < two && two < three);
  assert.match(copy, /not forecasts or a cheap \/ expensive verdict/);
  assert.ok(copy.indexOf('IMPLIED DISCOUNT RATE') > two && copy.indexOf('IMPLIED DISCOUNT RATE') < copy.indexOf('REQUIRED MARGIN'));
  assert.ok(copy.indexOf('DETAILS & AUDIT') > three);
  assert.ok(!byId(root, 'reverse-editor').open);
  assert.ok(!byId(root, 'reverse-history-fold').open);
  assert.ok(!byId(root, 'reverse-sensitivity-fold').open);
}));

test('a missing EV opens the assumption editor and advanced EV field instead of hiding the repair', async () => fixture(async (root) => {
  assert.equal(byId(root, 'reverse-editor').open, true);
  assert.match(text(byId(root, 'reverse-sensitivity-summary')), /Complete valid scenario inputs and working EV/);
}, { rows: [{ ...row, debt_basis: 'no debt tagged' }] }));

test('assumption summary follows edits and reset; audit EV gap stays out of the primary result', async () => fixture(async (root) => {
  assert.match(text(byId(root, 'reverse-assumption-summary')), /Opening scenario/);
  const wacc = byId(root, 'reverse-wacc'); wacc.value = '12'; wacc.listeners.input[0]();
  assert.match(text(byId(root, 'reverse-assumption-summary')), /Edited scenario.*WACC 12.0%/);
  const primary = all(root).find((n) => n.className === 'reverse-results');
  assert.doesNotMatch(text(primary), /ENTERPRISE VALUE GAP|SELECTED SCENARIO EV/);
  assert.match(text(root), /ENTERPRISE VALUE GAP/);
  button(root, 'RESET ASSUMPTIONS').listeners.click[0]();
  assert.match(text(byId(root, 'reverse-assumption-summary')), /Opening scenario.*WACC 9.0%/);
}));

test('fold toggles preserve edited scenario values instead of resetting inputs', async () => fixture(async (root) => {
  const growth = byId(root, 'reverse-growth'); growth.value = '8'; growth.listeners.input[0]();
  for (const id of ['reverse-history-fold', 'reverse-sensitivity-fold']) {
    const fold = byId(root, id); fold.open = true; fold.listeners.toggle[0]();
    assert.equal(byId(root, 'reverse-growth').value, '8');
  }
}));

test('dated FY revenue consensus shows ranges / revenue analyst count and warns when newer than price', async () => fixture(async (root) => {
  const copy = text(root);
  assert.match(copy, /after the 2026-10-16 price session/);
  assert.equal(String(byId(root, 'reverse-growth').value), '2.1');   // opens on the analysts' fiscal-year growth
  assert.match(copy, /ANALYST FY REVENUE GROWTH/);
  assert.match(copy, /2027-06-30/);
  assert.match(copy, /2.1%/);
  assert.match(copy, /1.5% to 2.9%/);
  assert.match(copy, /REVENUE ANALYSTS/);
  assert.match(copy, /Forward|forward operating-margin consensus/);
  assert.match(copy, /not a probability interval/);
}, { rows: [{ ...row, revenue_consensus: { source: 'Yahoo earningsTrend (unofficial)', observed_at: '2026-10-17T21:11:43Z', observed_market_date: '2026-10-17',
  periods: [{ end: '2027-06-30', growth_pct: 2.1, growth_low_pct: 1.5, growth_high_pct: 2.9, analysts: 22 }] } }] }));

test('short historical sample gets neutral color, not a spurious cheap / expensive verdict', async () => fixture(async (root) => {
  const primary = all(root).find((n) => n.className === 'reverse-results');
  assert.match(text(primary), /LIMITED HISTORY/);
  assert.ok(all(primary).some((n) => n.className === 'stat reverse-reference-neutral'));
  assert.doesNotMatch(text(primary), /BUY|SELL|UNDERVALUED|OVERVALUED/);
}));

test('thin industry group exposes members and suppresses an unreliable peer median', async () => fixture(async (root) => {
  assert.match(text(root), /Thin sample: fewer than 3; no peer median shown/);
  assert.match(text(root), /PEER1/);
  assert.match(text(root), /TTM OP MARGIN/);
  assert.match(text(root), /not validated business-model peers/);
}, { rows: [row, { ...row, ticker: 'PEER1', operating_margin: 10 }, { ...row, ticker: 'PEER2', operating_margin: -2 }] }));

test('the headline gives the implied discount rate against the 10-year yield, and the bar marks the requirement', async () => fixture(async (root) => {
  const primary = all(root).find((n) => n.className === 'reverse-results');
  assert.match(text(primary), /IMPLIED DISCOUNT RATE \d+\.\d%/);
  assert.match(text(primary), /10Y Treasury 5.1%/);
  const bar = all(primary).find((n) => n.className === 'reverse-bar');
  assert.ok(bar);
  assert.ok(all(bar).some((n) => String(n.className).startsWith('reverse-bar-required')));
  assert.match(text(bar), /own range 20.0–20.0%/);
}, { data: { risk_free_rate: 5.09 } }));
