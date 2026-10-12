import test from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/europe-model.js';

test('a London price is in pence, others carry their currency, and a missing price is a dash', () => {
  assert.equal(M.priceText(1234.4, 'GBp'), '1,234p');
  assert.equal(M.priceText(45.678, 'EUR'), '45.68 EUR');
  assert.equal(M.priceText(10552.1, 'CHF'), '10,552 CHF');
  assert.equal(M.priceText(null, 'EUR'), '—');
  assert.equal(M.multipleText(12.34), '12.3×');
  assert.equal(M.multipleText(undefined), '—');
  assert.equal(M.multipleText(1035), '>100×');
  assert.equal(M.growthText({ eps_growth: 12.4 }), '+12%');
  assert.equal(M.growthText({ eps_growth: null, eps_growth_out_of_range: true }), 'n/m');
  assert.equal(M.growthText({ eps_growth: null }), '—');
  assert.deepEqual([true, false, null].map(M.flagText), ['▲', '▼', '—']);
});

test('sorting puts a missing value last in either direction and sorts text by locale', () => {
  const rows = [{ n: 'b', v: 2 }, { n: 'a', v: null }, { n: 'c', v: 5 }, { n: 'd', v: undefined }, { n: 'e', v: 1 }];
  assert.deepEqual(M.sortRows(rows, (r) => r.v, 'desc').map((r) => r.n), ['c', 'b', 'e', 'a', 'd']);
  assert.deepEqual(M.sortRows(rows, (r) => r.v, 'asc').map((r) => r.n), ['e', 'b', 'c', 'a', 'd']);
  assert.deepEqual(M.sortRows(rows, (r) => r.n, 'asc').map((r) => r.n), ['a', 'b', 'c', 'd', 'e']);
  assert.deepEqual(M.sortRows([], (r) => r.v), []);
  assert.equal(rows.length, 5);          // the input is not reordered
  assert.equal(rows[0].n, 'b');
});

test('the columns read the build\'s fields and the sector filter counts biggest first', () => {
  const r = { symbol: 'HSBA.L', name: 'HSBC', sector: 'Financials', last: 1000, returns: { '1D': 1.2, '1M': -2, '3M': 3, YTD: 4, '1Y': 38 }, drawdown_pct: -5, forward_pe: 9.9, trailing_pe: 11, eps_growth: 4.1 };
  const got = Object.fromEntries(M.NAME_COLUMNS.map((c) => [c.key, c.get(r)]));
  assert.deepEqual([got.symbol, got['1D'], got['1Y'], got.dd, got.fpe, got.g], ['HSBA.L', 1.2, 38, -5, 9.9, 4.1]);
  assert.deepEqual(M.sectorCounts([{ sector: 'B' }, { sector: 'A' }, { sector: 'B' }, { sector: 'C' }]), [{ sector: 'B', n: 2 }, { sector: 'A', n: 1 }, { sector: 'C', n: 1 }]);
});

test('a multiple against the group median, and the median itself, skip what is missing', () => {
  assert.equal(M.againstMedian(12, 10), '+20% vs median');
  assert.equal(M.againstMedian(8, 10), '-20% vs median');
  assert.equal(M.againstMedian(null, 10), null);
  assert.equal(M.againstMedian(5, 0), null);
  assert.equal(M.medianOf([3, null, 1, undefined, 2]), 2);
  assert.equal(M.medianOf([1, 2, 3, 4]), 2.5);
  assert.equal(M.medianOf([null]), null);
});
