// Edge cases of the browser-side indicators. Parity with pandas is checked
// from pytest (tests/test_technicals_parity.py); these pin down behaviour
// pandas has no opinion on.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as T from '../../web/js/technicals-math.js';

test('an average is null until its window has formed, never a partial mean', () => {
  assert.deepEqual(T.sma([1, 2, 3, 4], 3), [null, null, 2, 3]);
});

test('z-score bands cover the line without gaps or overlap', () => {
  for (let i = 1; i < T.ZSCORE_BANDS.length; i += 1) {
    assert.equal(T.ZSCORE_BANDS[i].low, T.ZSCORE_BANDS[i - 1].high);
  }
  assert.equal(T.bandFor(-0.5).label, '-0.5 to 0.5');
  assert.equal(T.bandFor(2.0).label, '> 2.0');
  assert.equal(T.bandFor(null), null);
});

test('forward returns exclude the unfinished tail', () => {
  const values = Array.from({ length: 30 }, (_, i) => 100 + Math.sin(i) * 5 + i);
  const rows = T.forwardReturnByBand(values, 5, 10);
  const counted = rows.reduce((s, r) => s + r.count, 0);
  assert.equal(counted, 30 - 10 - 4); // 4 sessions before the 5-day z-score forms
});

test('a ratio uses shared dates only', () => {
  const left = { dates: ['a', 'b', 'c'], close: [10, 20, 30] };
  const right = { dates: ['b', 'c', 'd'], close: [4, 5, 6] };
  assert.deepEqual(T.ratioSeries(left, right), { dates: ['b', 'c'], ratio: [5, 6] });
});

test('a display period starts one session before its window, and YTD at the prior year-end', () => {
  const dates = ['2025-12-30', '2025-12-31', '2026-01-02', '2026-01-05'];
  assert.equal(T.viewStart(dates, 2), 1);
  assert.equal(T.viewStart(dates, null), 1);
  assert.equal(T.viewStart(dates, 50), 0);
});

test('moving-average periods are parsed, deduplicated and bounded', () => {
  assert.deepEqual(T.parseWindows('200, 20 50,20', { max: 400 }), [20, 50, 200]);
  assert.throws(() => T.parseWindows('20, x', { max: 400 }));
  assert.throws(() => T.parseWindows('1', { max: 400 }));
  assert.throws(() => T.parseWindows('500', { max: 400 }));
});

test('slope verdicts name every value', () => {
  assert.equal(T.slopeVerdict(25), 'STRONG UPTREND');
  assert.equal(T.slopeVerdict(0), 'FLAT');
  assert.equal(T.slopeVerdict(-25), 'STRONG DOWNTREND');
  assert.equal(T.slopeVerdict(null), null);
});

test('RSI is null until period changes exist, then names the deepest line and its run', () => {
  const falling = [10, 9, 8, 7, 6, 5, 4, 3, 2];
  const series = T.rsi(falling, 6);
  assert.deepEqual(series.slice(0, 6), [null, null, null, null, null, null]);
  assert.equal(series[6], 0);
  assert.deepEqual(T.rsiReading(series), { value: 0, line: 20, verdict: 'DEEPLY OVERSOLD', days: 3 });
  assert.deepEqual(T.rsiReading([null, 25, 40, 29]), { value: 29, line: 30, verdict: 'OVERSOLD', days: 1 });
  assert.equal(T.rsiReading([50, 31]).line, null);
  assert.equal(T.rsiReading([50, null]), null);
});

test('a range starts at its window, YTD at the prior year-end, MAX at the first session', () => {
  const dates = ['2025-12-30', '2025-12-31', '2026-01-02', '2026-01-05'];
  assert.equal(T.rangeStart(dates, 'YTD'), 1);
  assert.equal(T.rangeStart(dates, '1M'), 0);
  assert.equal(T.rangeStart(dates, 'MAX'), 0);
  const long = Array.from({ length: 2600 }, (_, i) => `d${String(i).padStart(4, '0')}`);
  assert.equal(T.rangeStart(long, '1Y'), 2600 - 1 - 252);
  assert.equal(T.rangeStart(long, '2Y'), 2600 - 1 - 504);
  assert.equal(T.rangeStart(long, '10Y'), 2600 - 1 - 2520);
  assert.throws(() => T.rangeStart(long, '2W'));
});

test('a range is within the bars when its first session is on or after their first date', () => {
  const dates = Array.from({ length: 600 }, (_, i) => `d${String(i).padStart(4, '0')}`);
  assert.equal(T.rangeWithin(dates, '1Y', 'd0100'), true);   // starts at d0347
  assert.equal(T.rangeWithin(dates, '2Y', 'd0100'), false);  // starts at d0095
  assert.equal(T.rangeWithin(dates, 'MAX', 'd0000'), true);
  assert.equal(T.rangeWithin(dates, 'MAX', 'd0001'), false);
});

test('the change on a session is against the one before, null without it', () => {
  assert.ok(Math.abs(T.change([100, 110], 1) - 10) < 1e-9);
  assert.equal(T.change([100, 110], 0), null);
  assert.equal(T.change([null, 110], 1), null);
  assert.equal(T.change([0, 110], 1), null);
});

test('52-week extremes need a full year and skip missing sessions', () => {
  assert.deepEqual(T.stats52w(Array(251).fill(1)), { high: null, low: null });
  const values = Array.from({ length: 252 }, (_, i) => (i === 0 ? null : i));
  assert.deepEqual(T.stats52w(values), { high: 251, low: 1 });
  assert.deepEqual(T.stats52w([1, 2, 3].concat(Array(249).fill(null))), { high: 3, low: 1 });
  assert.deepEqual(T.stats52w(Array(252).fill(null)), { high: null, low: null });
});

test('relative volume is today over the mean of the 20 sessions before it', () => {
  assert.equal(T.relVolume([...Array(20).fill(100), 300], 20), 3);
  assert.equal(T.relVolume([...Array(20).fill(100), null], 20), null);
  assert.equal(T.relVolume([null, ...Array(19).fill(100), 300], 20), null);
  assert.equal(T.relVolume(Array(20).fill(100), 20), null);
  assert.equal(T.relVolume([], 20), null);
});

test('the visible extent covers the window only, skips missing values and pads by the span', () => {
  const series = { low: [1, 5, null, 2], high: [9, 6, 7, 3], lines: [[null, 4, 4, 4]] };
  assert.deepEqual(T.visibleExtent(series, 1, 2, 0), { min: 4, max: 7 });
  const padded = T.visibleExtent(series, 1, 2, 0.04);
  assert.ok(Math.abs(padded.min - (4 - 0.04 * 3)) < 1e-9);
  assert.ok(Math.abs(padded.max - (7 + 0.04 * 3)) < 1e-9);
  assert.equal(T.visibleExtent({ low: [null], high: [null], lines: [[null]] }, 0, 0, 0.04), null);
  assert.equal(T.visibleExtent(series, 5, 9, 0), null);
});
