import { test } from 'node:test';
import assert from 'node:assert/strict';
import { availableSeries, notShownNote, putCallReading } from '../../web/js/put-call-model.js';
import { availableRanges, rangeStart } from '../../web/js/range.js';

test('short history looks do not change default chart ranges', () => {
  const dates = ['2025-01-01', '2026-10-06'];
  assert.deepEqual(availableRanges(dates, { short: true }), ['1M', '3M', '6M', 'YTD', '1Y', 'MAX']);
  assert.deepEqual(availableRanges(dates), ['6M', '1Y', 'MAX']);
  assert.deepEqual(availableRanges(['2026-06-01', '2026-10-06'], { short: true }), ['1M', '3M', 'MAX']);
});

test('YTD uses the series year, excludes the preceding December', () => {
  assert.equal(rangeStart(['2025-12-31', '2026-01-02', '2026-10-06'], 'YTD'), 1);
});

test('range statistics use only visible observations; no stale latest or missing-to-zero', () => {
  const row = { dates: ['2025-12-31', '2026-01-02', '2026-10-05', '2026-10-06'], windows: {
    '1D': { values: [100, 0, 2, null] }, '1W': { values: [50, 5, 1, null] },
  } };
  const result = putCallReading(row, '1W', 'YTD');
  assert.deepEqual(result.values, [5, 1, null]);
  assert.equal(result.median, 3);
  assert.equal(result.latest, null);
  assert.equal(result.percentile, null);
  assert.equal(result.observed, 2);
  assert.equal(result.missing, 1);
});

test('zero ratio is valid and ties use midrank', () => {
  const row = { dates: ['2026-10-01', '2026-10-02', '2026-10-05'], windows: { '1D': { values: [0, 0, 0] } } };
  const result = putCallReading(row, '1D', 'MAX');
  assert.equal(result.latest, 0);
  assert.equal(result.percentile, 50);
  assert.equal(result.observations, 3);
});

test('unavailable series are skipped; old artifacts may still carry summary fields', () => {
  const series = [
    { key: 'spx', status: 'ok', label: 'SPX + SPXW' },
    { key: 'other', status: 'unavailable', label: 'Other' },
  ];
  assert.deepEqual(availableSeries(series).map((row) => row.key), ['spx']);
  assert.deepEqual(availableSeries(undefined), []);
  // A stale per-window latest in an old artifact must not replace the value recomputed from the windows.
  const row = { dates: ['2026-10-05', '2026-10-06'], latest: 999, median: 999, percentile: 99,
    windows: { '1D': { values: [1, 2] } } };
  const result = putCallReading(row, '1D', 'MAX');
  assert.equal(result.latest, 2);
  assert.equal(result.median, 1.5);
});

test('licensed series left out of the artifact are named once with their reason', () => {
  assert.equal(notShownNote([]), null);
  assert.equal(notShownNote(undefined), null);
  assert.equal(notShownNote([{ key: 'ndx', label: 'NDX family', reason: 'public display permission not recorded' }]),
    'NDX family: not shown -- public display permission not recorded');
});
