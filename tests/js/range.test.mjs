// History-range switch: which ranges are offered and where each one cuts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as R from '../../web/js/range.js';

function weekly(from, weeks) {
  const start = Date.parse(from);
  return Array.from({ length: weeks }, (_, i) => new Date(start + i * 7 * 86400000).toISOString().slice(0, 10));
}

test('ten years of weekly data offers every range', () => {
  assert.deepEqual(R.availableRanges(weekly('2016-09-30', 522)), ['6M', '1Y', '3Y', '5Y', 'MAX']);
});

test('a range the data cannot fill is not offered', () => {
  // A year and a few days: 1Y would draw the same chart as MAX.
  assert.deepEqual(R.availableRanges(weekly('2025-09-19', 54)), ['6M', 'MAX']);
  assert.deepEqual(R.availableRanges(['2026-09-25']), ['MAX']);
  assert.deepEqual(R.availableRanges([]), ['MAX']);
});

test('a range cuts at calendar days back from the last date', () => {
  const dates = ['2025-01-01', '2025-06-01', '2025-12-01', '2026-03-01', '2026-06-01'];
  assert.equal(R.rangeStart(dates, '1Y'), 1);   // on or after 2025-06-01
  assert.equal(R.rangeStart(dates, '6M'), 2);   // on or after 2025-12-01
  assert.equal(R.rangeStart(dates, 'MAX'), 0);
  assert.equal(R.rangeStart(dates, 'nope'), 0);
});

test('slicing keeps every column aligned with its dates', () => {
  const dates = ['2025-01-01', '2025-06-01', '2025-12-01', '2026-03-01', '2026-06-01'];
  const out = R.sliceRange(dates, { a: [1, 2, 3, 4, 5], b: [10, 20, 30, 40, 50] }, '6M');
  assert.deepEqual(out, { dates: ['2025-12-01', '2026-03-01', '2026-06-01'], a: [3, 4, 5], b: [30, 40, 50] });
});

test('the preferred range falls back to MAX when the data is too short', () => {
  assert.equal(R.initialRange(weekly('2016-09-30', 522), '5Y'), '5Y');
  assert.equal(R.initialRange(weekly('2025-09-19', 54), '1Y'), 'MAX');
});
