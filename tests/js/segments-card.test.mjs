import test from 'node:test';
import assert from 'node:assert/strict';
import { bands, measureBands, periodTable, previousIndex, yearAgoIndex } from '../../web/js/segments-card.js';

const periods = [
  { end: '2025-03-31', label: 'Q1 FY2025', reconciled: true },
  { end: '2025-06-30', label: 'Q2 FY2025', reconciled: true },
  { end: '2026-03-31', label: 'Q1 FY2026', reconciled: true },
  { end: '2026-06-30', label: 'Q2 FY2026', reconciled: false },
];
const series = {
  periods,
  members: [{ key: 'cloud', label: 'Cloud' }, { key: 'ads', label: 'Ads' }],
  revenue: { cloud: [10, 12, 15, 18], ads: [90, 88, 95, 96] },
  profit: { cloud: [-1, 0, 2, 3.6], ads: [30, 29, 33, 33.6] },
  total_revenue: [100, 100, 110, 120],
  total_profit: [27, 27, 30, 33],
  unallocated: [-2, -2, -5, -4.2],
};

test('the year-ago period is the same quarter last year, not the previous quarter', () => {
  assert.equal(yearAgoIndex(periods, 3), 1);
  assert.equal(yearAgoIndex(periods, 2), 0);
  assert.equal(yearAgoIndex(periods, 1), null);
});

test('period table: growth, share and margin against the year-ago quarter, with the gaps the members leave', () => {
  const t = periodTable(series, 3);
  assert.equal(t.yearAgo.label, 'Q2 FY2025');
  const cloud = t.members.find((r) => r.key === 'cloud');
  assert.equal(cloud.growth, 50);
  assert.equal(cloud.share, 15);
  assert.equal(cloud.shareChange, 3);
  assert.ok(Math.abs(cloud.margin - 20) < 1e-9);
  assert.ok(Math.abs(cloud.marginChange - 20) < 1e-9);
  assert.equal(t.members[0].key, 'ads');  // largest first
  assert.equal(t.residual, 6);  // not reconciled: total less the members
  assert.equal(t.unallocated, -4.2);
  assert.ok(Math.abs(t.totalGrowth - 20) < 1e-9);
  assert.ok(Math.abs(t.totalMargin - 27.5) < 1e-9);
  assert.equal(periodTable(series, 1).residual, null);
});

test('bands: the largest members drawn, the rest one Other band', () => {
  const many = {
    periods,
    members: ['a', 'b', 'c', 'd'].map((key) => ({ key, label: key.toUpperCase() })),
    revenue: { a: [1, 1, 1, 1], b: [5, 5, 5, 5], c: [null, 2, 2, 2], d: [3, null, null, 4] },
  };
  const out = bands(many, 3);
  assert.deepEqual(out.map((b) => b.label), ['B', 'D', 'Other (2)']);
  assert.deepEqual(out[2].values, [1, 3, 3, 3]);  // A + C
  assert.equal(bands(many, 4).length, 4);
});

test('the quarter before is 80 to 100 days back, else none', () => {
  assert.equal(previousIndex(periods, 3), 2);
  assert.equal(previousIndex(periods, 2), null);  // nine months after Q2 FY2025
  assert.equal(previousIndex(periods, 1), 0);
  assert.equal(previousIndex(periods, 0), null);
});

test('period table: quarter-on-quarter growth, profit growth from a positive base and profit share', () => {
  const t = periodTable(series, 3);
  const cloud = t.members.find((r) => r.key === 'cloud');
  assert.ok(Math.abs(cloud.qoq - 20) < 1e-9);  // 15 -> 18
  assert.equal(cloud.profitGrowth, null);  // from a profit of 0
  assert.ok(Math.abs(cloud.profitShare - 3.6 / 37.2 * 100) < 1e-9);
  assert.ok(Math.abs(t.members.find((r) => r.key === 'ads').profitGrowth - 15.862068965517) < 1e-6);
  assert.ok(Math.abs(t.totalQoq - 100 * (120 / 110 - 1)) < 1e-9);
  assert.ok(Math.abs(t.totalProfitGrowth - 100 * (33 / 27 - 1)) < 1e-9);
});

test('measured bands: dollars, shares adding to 100, growth inside its cap', () => {
  const list = bands(series);
  const value = measureBands(list, periods, 'value');
  assert.deepEqual(value.find((b) => b.label === 'Cloud').values, [10e-9, 12e-9, 15e-9, 18e-9]);
  const shares = measureBands(list, periods, 'share');
  periods.forEach((_, i) => assert.ok(Math.abs(shares.reduce((s, b) => s + b.values[i], 0) - 100) < 1e-9));
  const yoy = measureBands(list, periods, 'yoy').find((b) => b.label === 'Cloud').values;
  assert.deepEqual(yoy, [null, null, 50, 50]);
  const qoq = measureBands(list, periods, 'qoq').find((b) => b.label === 'Cloud').values;
  assert.deepEqual(qoq.map((v) => (v === null ? null : Math.round(v * 1e6) / 1e6)), [null, 20, null, 20]);
  // Profit: ranked by size, growth from a loss left out, a jump past the cap too.
  const profit = measureBands(bands(series, 8, 'profit'), periods, 'yoy');
  assert.deepEqual(profit.find((b) => b.label === 'Cloud').values, [null, null, null, null]);
  const jump = measureBands([{ label: 'X', values: [1, 1, 5, 5] }], periods, 'yoy')[0].values;
  assert.deepEqual(jump, [null, null, null, null]);  // +400%: a base effect
});
