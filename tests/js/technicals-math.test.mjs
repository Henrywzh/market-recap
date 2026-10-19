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
