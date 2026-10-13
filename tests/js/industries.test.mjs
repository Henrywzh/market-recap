// INDUSTRIES: what a filter keeps, how a column sorts, which tags a row carries.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/industries-model.js';
import { splitThin } from '../../web/js/tabs/industries.js';

const row = (label, sector, one, extra = {}) => ({
  label, sector, members: 6, weight: 1,
  returns: { '1M': one, '3M': null, '6M': null },
  down_share: 100, drawdown: null, above_ma: null,
  revision: { '30d': null, '90d': null }, forward_pe: { median: null }, pe_percentile: { median: null },
  evidence: { sold_off: false, estimates_cut: null, cheap_vs_own_history: null },
  ...extra,
});

const ROWS = [
  row('Banks', 'Financials', -9, { evidence: { sold_off: true, estimates_cut: false, cheap_vs_own_history: true } }),
  row('Casinos', 'Consumer Discretionary', -18, { evidence: { sold_off: true, estimates_cut: true, cheap_vs_own_history: true } }),
  row('Semis', 'Information Technology', 9),
  row('Brokers', 'Financials', -15, { evidence: { sold_off: true, estimates_cut: null, cheap_vs_own_history: null } }),
];

test('SOLD OFF keeps sold-off groups; the held filter also needs estimates known and not cut', () => {
  assert.deepEqual(M.applyFilters(ROWS, { filter: 'sold_off' }).map((r) => r.label), ['Banks', 'Casinos', 'Brokers']);
  // Unknown estimates (null) are not "held": the filter does not guess.
  assert.deepEqual(M.applyFilters(ROWS, { filter: 'sold_off_held' }).map((r) => r.label), ['Banks']);
});

test('the sector filter combines with the evidence filter', () => {
  assert.deepEqual(M.applyFilters(ROWS, { filter: 'sold_off', sector: 'Financials' }).map((r) => r.label), ['Banks', 'Brokers']);
});

test('an unknown filter id keeps everything', () => {
  assert.equal(M.applyFilters(ROWS, { filter: 'nope' }).length, ROWS.length);
});

test('a missing reading sorts last whichever way the column runs', () => {
  const rows = [row('A', 'S', -1, { drawdown: null }), row('B', 'S', -2, { drawdown: -30 }), row('C', 'S', -3, { drawdown: -10 })];
  assert.deepEqual(M.sortRows(rows, 'drawdown', false).map((r) => r.label), ['B', 'C', 'A']);
  assert.deepEqual(M.sortRows(rows, 'drawdown', true).map((r) => r.label), ['C', 'B', 'A']);
});

test('sorting by name is alphabetical and does not mutate the input', () => {
  const copy = [...ROWS];
  assert.deepEqual(M.sortRows(ROWS, 'label', false).map((r) => r.label), ['Banks', 'Brokers', 'Casinos', 'Semis']);
  assert.deepEqual(ROWS, copy);
});

const SETTINGS = { sold_off_return_pct: -6, sold_off_down_share: 0.8, estimates_cut_30d_pct: -0.5, estimates_cut_90d_pct: 0, cheap_percentile: 50 };

test('a flag that is unknown carries no tag instead of a verdict', () => {
  assert.deepEqual(M.evidenceTags(ROWS[3], SETTINGS).map((t) => t.text), ['SOLD OFF']);
  assert.deepEqual(M.evidenceTags(ROWS[2], SETTINGS), []);
});

test('estimates held and cut are different tags, and the tags name their thresholds', () => {
  assert.deepEqual(M.evidenceTags(ROWS[0], SETTINGS).map((t) => t.text), ['SOLD OFF', 'EST HELD', 'P/E LOW']);
  assert.deepEqual(M.evidenceTags(ROWS[1], SETTINGS).map((t) => t.text), ['SOLD OFF', 'EST CUT', 'P/E LOW']);
  assert.match(M.evidenceTags(ROWS[0], SETTINGS)[0].title, /-6%/);
});

test('sectors are listed once, sorted', () => {
  assert.deepEqual(M.sectorsOf(ROWS), ['Consumer Discretionary', 'Financials', 'Information Technology']);
});

test('a thin sub-industry is left off the table and counted; a sector is never hidden', () => {
  const rows = [{ label: 'Thin A', thin: true }, { label: 'Solid', thin: false }, { label: 'Thin B', thin: true }];
  const sub = splitThin(rows, 'sub_industries');
  assert.deepEqual(sub.shown.map((r) => r.label), ['Solid']);
  assert.equal(sub.hidden, 2);
  const sectors = splitThin(rows, 'sectors');
  assert.equal(sectors.shown.length, 3);
  assert.equal(sectors.hidden, 0);
});
