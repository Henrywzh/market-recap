import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseInput, prepareReverseInputs, scenarioError, scenarioValue, requiredMargin, impliedDiscountRate } from '../../web/js/reverse-dcf-math.js';

const settings = { excluded_sectors: ['Financials', 'Real Estate', 'Utilities'], excluded_subindustries: ['Biotechnology'], annual_max_age_days: 550, capital_warning_share: 0.1 };
const row = { ticker: 'TEST', sector: 'Industrials', sub_sector: 'Machinery', price: 10, ev: 1000, market_cap: 900, period_end: '2026-06-30', filed: '2026-08-01', debt_basis: 'long-term + current debt', operating_margin: 20 };
const annual = { ticker: 'TEST', columns: [{ period_end: '2026-06-30', filed: '2026-08-01' }], values: { revenue: [100], ebit: [20], capex: [10] } };
const scenario = { revenue: 100, baseMargin: 0.2, growth: 0.05, margin: 0.25, wacc: 0.1, tax: 0.25, netInvestment: 0.05, terminalGrowth: 0.025, terminalRoic: 0.15, years: 10, transitionYears: 5 };

test('blank and nonnumeric inputs stay missing, and zero is real', () => {
  assert.equal(parseInput(''), null); assert.equal(parseInput('  '), null);
  assert.equal(parseInput('bad'), null); assert.equal(parseInput('Infinity'), null);
  assert.equal(parseInput('0'), 0);
  assert.equal(parseInput(null), null); assert.equal(parseInput(false), null);
});
test('facts preserve dates, observed margin and published net claims', () => {
  const value = prepareReverseInputs(row, annual, '2026-10-16', settings);
  assert.deepEqual(value.issues, []); assert.equal(value.margin, 0.2);
  assert.equal(value.netClaims, 100); assert.equal(value.column.period_end, '2026-06-30');
});
test('specialised businesses and missing classifications do not enter operating template', () => {
  for (const sector of settings.excluded_sectors) assert.ok(prepareReverseInputs({ ...row, sector }, annual, '2026-10-16', settings).issues.length);
  assert.ok(prepareReverseInputs({ ...row, sub_sector: 'Biotechnology' }, annual, '2026-10-16', settings).issues.length);
  assert.ok(prepareReverseInputs({ ...row, sector: null }, annual, '2026-10-16', settings).issues.length);
});
test('missing debt does not become zero, while manual EV can be a separate assumption', () => {
  const v = prepareReverseInputs({ ...row, debt_basis: 'no debt tagged' }, annual, '2026-10-16', settings);
  assert.equal(v.workingEv, null); assert.equal(v.netClaims, null);
  assert.match(v.evReason, /missing debt is not zero/);
});
test('nonpositive EBIT, absent EBIT and current losses are blocked', () => {
  for (const ebit of [null, 0, -1]) {
    const v = prepareReverseInputs(row, { ...annual, values: { ...annual.values, ebit: [ebit] } }, '2026-10-16', settings);
    assert.ok(v.issues.length);
  }
  assert.ok(prepareReverseInputs({ ...row, operating_margin: -1 }, annual, '2026-10-16', settings).issues.length);
});
test('mismatched tickers, history alignment and future filings are blocked', () => {
  assert.ok(prepareReverseInputs(row, { ...annual, ticker: 'OTHER' }, '2026-10-16', settings).issues.length);
  assert.ok(prepareReverseInputs(row, { ...annual, values: { revenue: [], ebit: [20] } }, '2026-10-16', settings).issues.length);
  assert.ok(prepareReverseInputs(row, { ...annual, columns: [{ period_end: '2026-06-30', filed: '2026-10-20' }] }, '2026-10-16', settings).issues.length);
});
test('stale and future annual periods are blocked', () => {
  for (const period_end of ['2020-06-30', '2027-06-30', 'bad-date']) assert.ok(prepareReverseInputs(row, { ...annual, columns: [{ period_end, filed: '2026-08-01' }] }, '2026-10-16', settings).issues.length);
});
test('missing price or future valuation balance periods are blocked', () => {
  assert.ok(prepareReverseInputs({ ...row, price: null }, annual, '2026-10-16', settings).issues.length);
  assert.ok(prepareReverseInputs({ ...row, period_end: '2027-06-30' }, annual, '2026-10-16', settings).issues.length);
});
test('one-year result agrees with an independent NOPAT, reinvestment and continuing-value calculation', () => {
  const s = { ...scenario, years: 1, transitionYears: 1 };
  const revenue = 100 * 1.05;
  const explicit = (revenue * 0.25 * 0.75 - revenue * 0.05) / 1.1;
  const continuing = revenue * 1.025 * 0.25 * 0.75 * (1 - 0.025 / 0.15) / 0.075 / 1.1;
  assert.ok(Math.abs(scenarioValue(s).ev - explicit - continuing) < 1e-10);
});
test('zero-growth steady scenario has the independently calculated perpetuity value', () => {
  const s = { ...scenario, baseMargin: 0.2, margin: 0.2, growth: 0, netInvestment: 0, terminalGrowth: 0 };
  assert.ok(Math.abs(scenarioValue(s).ev - 100 * 0.2 * 0.75 / 0.1) < 1e-10);
});
test('margin ramps and explicit PV reconciles; first model year grows from run-rate, not an elapsed fiscal year', () => {
  const v = scenarioValue(scenario);
  assert.equal(v.path[0].revenue, 105);
  assert.ok(Math.abs(v.path[0].margin - 0.21) < 1e-12);
  assert.equal(v.path[4].margin, 0.25);
  assert.equal(v.path[9].margin, 0.25);
  assert.ok(Math.abs(v.path.reduce((sum, y) => sum + y.pv, 0) + v.terminalPv - v.ev) < 1e-10);
});
test('higher discount or reinvestment lowers EV for the positive-cash-flow control', () => {
  const v = scenarioValue(scenario).ev;
  assert.ok(scenarioValue({ ...scenario, wacc: 0.12 }).ev < v);
  assert.ok(scenarioValue({ ...scenario, netInvestment: 0.1 }).ev < v);
});
test('required margin reconstructs EV and never clamps an out-of-range root', () => {
  const target = scenarioValue(scenario).ev;
  const root = requiredMargin(scenario, target);
  assert.equal(root.status, 'solved'); assert.ok(Math.abs(root.value - scenario.margin) < 1e-12);
  assert.ok(Math.abs(scenarioValue({ ...scenario, margin: root.value }).ev - target) < 1e-10);
  assert.equal(requiredMargin(scenario, target * 1e8).status, 'outside-bounds');
  assert.equal(requiredMargin(scenario, null).status, 'invalid');
});
test('invalid WACC/growth, terminal reinvestment, nulls and horizons never generate infinities', () => {
  for (const patch of [{ wacc: 0.025 }, { terminalGrowth: -0.01 }, { terminalRoic: 0.01 }, { tax: 1 }, { netInvestment: null }, { years: 2.5 }, { years: 0 }, { transitionYears: 11 }, { growth: -1 }, { margin: 1.1 }]) {
    assert.ok(scenarioError({ ...scenario, ...patch }));
    assert.equal(scenarioValue({ ...scenario, ...patch }).ev, null);
  }
});
test('cash capex stays an observation, not the future net-investment parameter', () => {
  const a = prepareReverseInputs(row, annual, '2026-10-16', settings);
  const b = prepareReverseInputs(row, { ...annual, values: { ...annual.values, capex: [40] } }, '2026-10-16', settings);
  assert.notEqual(a.capexShare, b.capexShare);
  assert.equal(a.margin, b.margin);
  assert.ok(b.warnings.some((text) => /NOT calibrated/.test(text)));
});

test('the implied discount rate round-trips: at that rate the model EV equals the target', () => {
  const s = { revenue: 100, baseMargin: 0.2, growth: 0.03, margin: 0.22, wacc: 0.09, tax: 0.21, netInvestment: 0.02, terminalGrowth: 0.025, terminalRoic: 0.15, years: 10, transitionYears: 5 };
  const target = scenarioValue({ ...s, wacc: 0.071 }).ev;
  const implied = impliedDiscountRate(s, target);
  assert.equal(implied.status, 'solved');
  assert.ok(Math.abs(implied.value - 0.071) < 1e-5);
  // A price no rate above terminal growth reaches is named, not clamped.
  assert.equal(impliedDiscountRate(s, target * 1e6).status, 'below-range');
  assert.equal(impliedDiscountRate(s, 1e-9).status, 'above-range');
  assert.equal(impliedDiscountRate(s, null).status, 'invalid');
});
