import test from 'node:test';
import assert from 'node:assert/strict';
import { costDistribution, costStats, grid, priceRange, spread, valueArea, volumeProfile } from '../../web/js/chip-math.js';
import { chipView } from '../../web/js/chip-card.js';

const close = (a, b) => Math.abs(a - b) < 1e-9;
const bars = (rows) => ({
  dates: rows.map((_, i) => `2025-01-${String(i + 1).padStart(2, '0')}`),
  open: rows.map((r) => r[2]), high: rows.map((r) => r[0]), low: rows.map((r) => r[1]),
  close: rows.map((r) => r[2]), volume: rows.map((r) => r[3]),
});

test('a session spreads its volume over its own range, peaking at the typical price, summing to one', () => {
  const g = grid(0, 10, 10);
  const s = spread(g, 2, 6, 5.5);
  assert.equal(s.first, 2);
  assert.equal(s.weights.length, 5);
  assert.ok(close(s.weights.reduce((a, b) => a + b, 0), 1));
  const peak = s.weights.indexOf(Math.max(...s.weights));
  assert.equal(s.first + peak, 4); // typical price (6 + 2 + 5.5) / 3 = 4.5 is in bin 4
  assert.deepEqual(spread(g, 3.2, 3.4, 3.3), { first: 3, weights: [1] });
});

test('volume profile: point of control and a value area holding 70% of the volume', () => {
  const b = bars([[11, 9, 10, 100], [11, 9, 10, 100], [21, 19, 20, 50], [31, 29, 30, 10]]);
  const range = priceRange(b, 0, 3);
  assert.deepEqual(range, { min: 9, max: 31 });
  const g = grid(range.min, range.max, 22);
  const profile = volumeProfile(b, 0, 3, g);
  assert.ok(close(profile.reduce((a, c) => a + c, 0), 260));
  const area = valueArea(profile, g);
  assert.ok(area.poc > 9 && area.poc < 11);
  assert.ok(area.share >= 0.7);
  assert.ok(area.low <= 9.5 && area.high < 19);
});

test('cost distribution: later sessions replace earlier holdings by their turnover', () => {
  const b = bars([[11, 9, 10, 500], [21, 19, 20, 500], [21, 19, 20, 500]]);
  const g = grid(5, 25, 20);
  const d = costDistribution(b, 2, g, 1000);
  // 50% turnover a day: 0.5 at 10; then 0.25 / 0.5 at 10 / 20; then 0.125 / 0.75, so 1/7 and 6/7 of what is held.
  const low = d.chips.slice(0, 10).reduce((a, c) => a + c, 0);
  const high = d.chips.slice(10).reduce((a, c) => a + c, 0);
  assert.ok(close(low, 1 / 7) && close(high, 6 / 7));
  const s = costStats(d, g, 15);
  assert.ok(close(s.profitShare, 1 / 7)); // only the holdings bought near 10 are below a 15 close
  assert.ok(s.average > 18 && s.average < 19);
  assert.ok(s.band90[0] < 10 && s.band90[1] > 20);
  assert.equal(costDistribution(b, 2, g, null), null);
});

test('holdings bought outside the shown prices are counted, not dropped', () => {
  const b = bars([[51, 49, 50, 500], [21, 19, 20, 500]]);
  const d = costDistribution(b, 1, grid(10, 30, 20), 1000);
  assert.ok(close(d.outside, 1 / 3)); // 0.25 still held from 50, 0.5 bought near 20
  assert.ok(close(d.chips.reduce((a, c) => a + c, 0) + d.outside, 1));
});

test('chip view: a window ending on a picked session, volume or cost mode', () => {
  const b = bars(Array.from({ length: 30 }, (_, i) => [11 + i, 9 + i, 10 + i, 100]));
  const v = chipView(b, { sessions: 10, end: 19, mode: 'volume', shares: null });
  assert.equal(v.from, 10);
  assert.equal(v.date, '2025-01-20');
  assert.ok(v.area.poc > 18 && v.area.poc < 30);
  const c = chipView(b, { sessions: 10, end: null, mode: 'cost', shares: 1000 });
  assert.equal(c.last, 29);
  assert.ok(c.stats.profitShare > 0.5);
  assert.equal(chipView(b, { sessions: 10, mode: 'cost', shares: null }), null);
});
