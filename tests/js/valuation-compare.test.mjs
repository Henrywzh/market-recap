import test from 'node:test';
import assert from 'node:assert/strict';
import { PERIOD_TOLERANCE_DAYS, cashConversion, comparisonBasisNote, comparisonEvidence, daysApart, revenueForecast, sameIssuer, suggestPeer, valuationRankClass } from '../../web/js/valuation-compare-math.js';
import { comparisonCard } from '../../web/js/valuation-compare.js';

const asOf = '2026-10-23';
const forecast = (growth, end = '2027-12-31', observed = asOf) => ({ observed_market_date: observed,
  periods: [{ period: '+1y', end, growth_pct: growth }] });
const a = { ticker: 'A', cik: 1, name: 'Issuer A', sector: 'Goods', sub_sector: 'Household', market_cap: 200,
  period_end: '2026-06-30', filed: '2026-08-01', pe_forward: 30, pe: 25, pb: 5, ptbv: 8,
  roic: 20, roe: 25, rotce: 30, earnings_yield: 4, fcf_yield: 3, margin_stability: 1,
  net_debt_ebitda: 2, debt_basis: 'tagged', revenue_consensus: forecast(8), lagged: [] };
const b = { ...a, ticker: 'B', cik: 2, market_cap: 100, pe_forward: 20, roic: 10, net_debt_ebitda: 1,
  revenue_consensus: forecast(4) };
const compare = (aa = a, bb = b, extra = {}) => comparisonEvidence(aa, bb, { asOf, financialsSector: 'Financials', ...extra });
const metric = (result, key) => result.rows.find((r) => r.key === key);

test('premium is same-basis, with support and counterpoints oriented to the higher-multiple issuer', () => {
  const result = compare();
  assert.equal(result.premium, 50);
  assert.equal(result.leader, 'A');
  assert.equal(metric(result, 'growth').state, 'supports');
  assert.equal(metric(result, 'leverage').state, 'counterpoint');
  const swapped = compare(b, a);
  assert.ok(Math.abs(swapped.premium + 100 / 3) < 1e-10);
  assert.equal(swapped.leader, 'A');
  assert.equal(metric(swapped, 'growth').state, 'supports');
  assert.equal(metric(swapped, 'leverage').state, 'counterpoint');
  assert.equal(compare(a, b, { basis: 'pe' }).premium, 0);
});
test('null, zero, negative and nonnumeric multiples never become a valid premium', () => {
  for (const value of [null, undefined, 0, -10, NaN, '20']) {
    const result = compare({ ...a, pe_forward: value });
    assert.equal(result.primaryA, null);
    assert.equal(result.premium, null);
    assert.ok(result.rows.every((r) => r.state === 'unknown'));
  }
  assert.equal(compare(a, { ...b, pe_forward: 30.001 }).leader, null);
});
test('cash conversion uses a common market-cap denominator, retaining negative cash and rejecting loss earnings', () => {
  // $30 FCF / $40 NI, each expressed as a yield on $1,000 market cap.
  assert.equal(cashConversion({ fcf_yield: 3, earnings_yield: 4 }), 75);
  assert.equal(cashConversion({ fcf_yield: -2, earnings_yield: 4 }), -50);
  assert.equal(cashConversion({ fcf_yield: 0, earnings_yield: 4 }), 0);
  for (const earnings_yield of [null, 0, -4]) assert.equal(cashConversion({ fcf_yield: 3, earnings_yield }), null);
  assert.equal(cashConversion({ fcf_yield: null, earnings_yield: 4 }), null);
  for (const key of ['cash_conversion', 'margin_stability']) assert.equal(metric(compare(), key).state, 'context');
});
test('peer suggestions use classification and size and exclude alternate classes of the same issuer', () => {
  assert.equal(sameIssuer(a, { ...a, ticker: 'A-B', cik: '0001' }), true);
  assert.equal(sameIssuer({ ticker: 'X', cik: '' }, { ticker: 'Y', cik: '' }), false);
  const peers = [{ ...b, ticker: 'NEAR', market_cap: 190 }, { ...a, ticker: 'A-B' },
    { ...b, ticker: 'OTHER', sub_sector: 'Other', market_cap: 200 }, b];
  assert.equal(suggestPeer(peers, a).ticker, 'NEAR');
  assert.equal(suggestPeer([{ ...b, sector: 'Other' }], a), null);
  assert.ok(compare(a, { ...b, cik: 1 }).rows.every((r) => r.state === 'unknown'));
});
test('different or absent industry labels withhold directional evidence', () => {
  for (const patch of [{ sub_sector: 'Other' }, { sub_sector: null }, { sector: 'Other' }]) {
    const result = compare(a, { ...b, ...patch });
    assert.ok(result.rows.every((r) => r.state === 'unknown'));
    assert.equal(result.premium, 50); // descriptive values stay available.
  }
});
test('future, missing and invalid statement dates block evidence; different TTM windows do not compare returns', () => {
  for (const patch of [{ filed: '2026-10-24' }, { period_end: '2026-12-31' }, { filed: null }, { period_end: '2026-02-30' }]) {
    assert.ok(compare(a, { ...b, ...patch }).rows.every((r) => r.state === 'unknown'));
  }
  const result = compare(a, { ...b, period_end: '2026-03-31' });
  assert.equal(metric(result, 'capital_return').state, 'unknown');
  assert.match(metric(result, 'capital_return').reason, /period ends 91 days apart/);
  assert.equal(metric(result, 'growth').state, 'supports');
  assert.equal(metric(compare({ ...a, lagged: ['ebit'] }), 'capital_return').state, 'unknown');
  assert.equal(metric(compare({ ...a, debt_basis: 'no debt tagged' }), 'leverage').state, 'unknown');
});
test('period ends within the tolerance compare, stating the gap (52/53-week fiscal calendars)', () => {
  // HD and LOW: quarters ending 2026-08-02 and 2026-07-31.
  const result = compare({ ...a, period_end: '2026-08-02', filed: '2026-09-01' }, { ...b, period_end: '2026-07-31', filed: '2026-09-01' });
  assert.equal(metric(result, 'capital_return').state, 'supports');
  assert.match(metric(result, 'capital_return').reason, /2 days apart/);
  assert.equal(metric(result, 'leverage').state, 'counterpoint');
  assert.equal(daysApart('2026-08-02', '2026-07-31'), 2);
  assert.equal(PERIOD_TOLERANCE_DAYS, 45);
  const late = compare(a, { ...b, revenue_consensus: forecast(4, '2028-01-30') });
  assert.equal(metric(late, 'growth').state, 'supports');
  assert.match(metric(late, 'growth').reason, /30 days apart/);
});
test('price-implied growth over consensus: a smaller excess supports the higher multiple', () => {
  const result = compare({ ...a, implied_growth: 12, consensus_growth: 10 }, { ...b, implied_growth: 9, consensus_growth: 4 });
  const row = metric(result, 'expectations');
  assert.equal(row.a, 2);
  assert.equal(row.b, 5);
  assert.equal(row.unit, 'pp');
  assert.equal(row.state, 'supports');
  assert.match(row.note, /A 12.0% implied \/ 10.0% consensus; B 9.0% implied \/ 4.0% consensus/);
  assert.equal(metric(compare({ ...a, implied_growth: 20, consensus_growth: 5 }, { ...b, implied_growth: 6, consensus_growth: 5 }), 'expectations').state, 'counterpoint');
  const missing = metric(compare({ ...a, implied_growth: null, consensus_growth: 10 }, b), 'expectations');
  assert.equal(missing.state, 'unknown');
  assert.match(missing.note, /A — implied/);
});
test('FY forecast dates must align and observations must not postdate prices; no current-FY substitution', () => {
  for (const revenue_consensus of [forecast(4, '2027-06-30'), forecast(4, '2027-12-31', '2026-10-24'),
    forecast(4, '2027-12-31', null), null]) {
    assert.equal(metric(compare(a, { ...b, revenue_consensus }), 'growth').state, 'unknown');
  }
  assert.equal(revenueForecast({ revenue_consensus: { periods: [{ period: '0y', end: '2026-12-31', growth_pct: 9 }] } }), null);
});
test('book comparisons are gated and financial PTBV uses ROTCE without inventing credit-risk coverage', () => {
  assert.ok(compare(a, b, { basis: 'pb' }).rows.every((r) => r.state === 'unknown'));
  const result = compare({ ...a, sector: 'Financials' }, { ...b, sector: 'Financials' }, { basis: 'ptbv' });
  assert.equal(metric(result, 'capital_return').label, 'ROTCE · TTM');
  assert.equal(metric(result, 'asset_quality').state, 'unknown');
  assert.equal(metric(result, 'cash_conversion'), undefined);
});
test('adjusted trailing P/E uses the published measure, preserving adjustment bases and missingness', () => {
  const aa = { ...a, pe_operating: 30, pe_basis: 'operating' };
  const bb = { ...b, pe_operating: 20, pe_basis: 'operating' };
  assert.equal(compare(aa, bb, { basis: 'pe_operating' }).premium, 50);
  assert.equal(metric(compare(aa, bb, { basis: 'pe_operating' }), 'growth').state, 'supports');
  const mismatch = compare(aa, { ...bb, pe_basis: 'ex_gains' }, { basis: 'pe_operating' });
  assert.ok(mismatch.rows.every((r) => r.state === 'unknown'));
  assert.match(mismatch.issue, /Adjusted earnings bases differ/);
  assert.equal(compare(aa, { ...bb, pe_operating: null }, { basis: 'pe_operating' }).premium, null);
  assert.match(comparisonBasisNote('pe_operating', aa, { ...bb, pe_basis: 'ex_gains' }), /excluding equity-security gains/);
  assert.match(comparisonBasisNote('pe_forward', a, b), /next-12-month EPS/);
});
test('valuation ranks have non-buy/sell colors; quality keeps its distinct rank styling', () => {
  assert.equal(valuationRankClass(.95, 'valuation'), 'valuation-lower');
  assert.equal(valuationRankClass(.05, 'valuation'), 'valuation-higher');
  assert.equal(valuationRankClass(.95, 'quality'), 'up');
  assert.equal(valuationRankClass(null, 'valuation'), '');
});

class Node {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.nodeType = 1; this.children = []; this.attrs = {}; this.listeners = {}; this.textContent = ''; this.value = ''; }
  setAttribute(k, v) { this.attrs[k] = v; if (k === 'value') this.value = v; }
  addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
}
const all = (n) => [n, ...(n.children || []).flatMap(all)];
const text = (n) => [n.textContent || n.text || '', ...(n.children || []).map(text)].join(' ');
test('comparison controls redraw, swap, change basis and clear invalid names without hidden replacement', () => {
  const saved = globalThis.document;
  globalThis.document = { createElement: (tag) => new Node(tag), createTextNode: (s) => ({ nodeType: 3, text: s }) };
  try {
    const root = comparisonCard({ as_of: asOf, rows: [a, b] }, { selectedTicker: 'A' });
    const input = (label) => all(root).find((n) => n.attrs?.['aria-label'] === label);
    const button = (label) => all(root).find((n) => n.tagName === 'BUTTON' && n.textContent === label);
    assert.match(text(root), /A AT 50.0% PREMIUM TO B/);
    button('SWAP').listeners.click[0]();
    assert.match(text(root), /B AT 33.3% DISCOUNT TO A/);
    const basis = input('Comparison valuation measure'); basis.value = 'pe'; basis.listeners.change[0]();
    assert.match(text(root), /NO VISIBLE MULTIPLE PREMIUM/);
    const company = input('Compare company A'); company.value = 'NOT-COVERED'; company.listeners.change[0]();
    assert.match(text(root), /Unknown or blank names are not replaced/);
    assert.doesNotMatch(text(root), /NO VISIBLE MULTIPLE PREMIUM|DIMENSION/);
    company.value = 'A'; company.listeners.change[0]();
    button('SUGGEST PEER').listeners.click[0]();
    assert.equal(input('Compare company B').value, 'B');
    assert.equal(comparisonCard({ rows: [] }), null);
    const folded = comparisonCard({ as_of: asOf, rows: [a, b] }, { fold: true });
    assert.equal(folded.tagName, 'DETAILS');
    assert.equal(folded.attrs.open, undefined);
    assert.equal(comparisonCard({ as_of: asOf, rows: [a, b] }, { fold: true, open: true }).attrs.open, '');
  } finally { if (saved === undefined) delete globalThis.document; else globalThis.document = saved; }
});
