import test from 'node:test';
import assert from 'node:assert/strict';
import { consensusGrowthRanges } from '../../web/js/consensus-growth-ranges.js';

test('fiscal-year bars share one scale, with the mean positioned in actual growth units', () => {
  const result = consensusGrowthRanges([
    { growth_pct: 3.2, growth_low_pct: 2, growth_high_pct: 4.2 },
    { growth_pct: 3.2, growth_low_pct: 1.7, growth_high_pct: 5.2 },
  ]);
  const [first, second] = result.rows;
  assert.equal(first.geometry.meanAt, second.geometry.meanAt);
  assert.ok(second.geometry.width > first.geometry.width);
  const reconstructed = result.min + first.geometry.meanAt / 100 * (result.max - result.min);
  assert.ok(Math.abs(reconstructed - 3.2) < 1e-10);
  assert.ok(first.geometry.zeroAt < first.geometry.lowAt);
});
test('missing mean keeps the band without a fabricated midpoint; missing range keeps the mean without a band', () => {
  const result = consensusGrowthRanges([
    { growth_pct: null, growth_low_pct: 2, growth_high_pct: 4 },
    { growth_pct: 3, growth_low_pct: null, growth_high_pct: 4 },
  ]);
  assert.equal(result.rows[0].hasRange, true);
  assert.equal(result.rows[0].geometry.meanAt, null);
  assert.equal(result.rows[1].mean, 3);
  assert.equal(result.rows[1].hasRange, false);
  assert.equal(result.rows[1].geometry.width, null);
});
test('zero, negative growth and equal endpoints are genuine values, not gaps', () => {
  const { rows } = consensusGrowthRanges([
    { growth_pct: 0, growth_low_pct: -1, growth_high_pct: 1 },
    { growth_pct: -2, growth_low_pct: -2, growth_high_pct: -2 },
  ]);
  assert.equal(rows[0].geometry.meanAt, rows[0].geometry.zeroAt);
  assert.equal(rows[1].hasRange, true);
  assert.equal(rows[1].geometry.width, 0);
  assert.ok(rows[1].geometry.meanAt < rows[1].geometry.zeroAt);
});
test('invalid vendor ranges are withheld rather than reordered or clipped to the mean', () => {
  for (const period of [
    { growth_pct: 3, growth_low_pct: 4, growth_high_pct: 2 },
    { growth_pct: 6, growth_low_pct: 2, growth_high_pct: 4 },
    { growth_pct: 3, growth_low_pct: 2, growth_high_pct: 4, range_issue: 'vendor inconsistency' },
  ]) {
    const row = consensusGrowthRanges([period]).rows[0];
    assert.equal(row.invalid, true);
    assert.equal(row.hasRange, false);
    assert.equal(row.mean, period.growth_pct);
    assert.equal(row.low, null);
  }
});
test('all-missing growth has no invented scale, dot or band', () => {
  const result = consensusGrowthRanges([{ growth_pct: null, growth_low_pct: null, growth_high_pct: null }]);
  assert.equal(result.min, null);
  assert.equal(result.max, null);
  assert.equal(result.rows[0].geometry, null);
});
