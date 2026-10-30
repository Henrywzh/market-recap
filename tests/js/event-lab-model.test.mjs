import test from 'node:test';
import assert from 'node:assert/strict';
import { sessions, fires, passes, decluster, outcomes, stats, study, byYear, rollingMedian, toCsv, excluded } from '../../web/js/event-lab-model.js';

// 300 flat sessions at 100, with a −5% intraday low on day 250 that closes −1%, and
// a −6% close on day 260; the price then climbs 1 a day.
function bars() {
  const n = 300;
  const dates = Array.from({ length: n }, (_, i) => new Date(Date.UTC(2020, 0, 1) + i * 864e5).toISOString().slice(0, 10));
  const close = Array.from({ length: n }, (_, i) => 100 + (i % 2) * 0.5);
  close[250] = 99; close[260] = close[259] * 0.94;
  for (let i = 261; i < n; i++) close[i] = close[i - 1] + 1;
  const open = close.map((c, i) => (i ? close[i - 1] : c));
  const high = close.map((c, i) => Math.max(c, open[i]) + 0.1);
  const low = close.map((c, i) => Math.min(c, open[i]) - 0.1);
  low[250] = close[249] * 0.95;
  return { dates, open, high, low, close };
}

test('sessions read the intraday low, close move, RSI and averages as of each close', () => {
  const b = bars(); const s = sessions(b);
  assert.ok(Math.abs(s[250].lowRet - -5) < 1e-9);
  assert.ok(s[250].closeRet > -1.5 && s[250].closeRet < 0);
  assert.equal(s[0].lowRet, null);
  assert.equal(s[100].vs200, null);
  assert.ok(Number.isFinite(s[260].vs200) && Number.isFinite(s[260].rsi6) && s[260].rsi6 < 30);
});

test('triggers by kind, direction and size', () => {
  const s = sessions(bars());
  assert.ok(fires(s[250], { kind: 'intraday', dir: -1, size: 4 }));
  assert.ok(!fires(s[250], { kind: 'close', dir: -1, size: 4 }));
  assert.ok(fires(s[260], { kind: 'close', dir: -1, size: 4 }));
  assert.ok(!fires(s[260], { kind: 'close', dir: 1, size: 4 }));
});

test('conditions are ANDed; an unknown reading fails the condition', () => {
  const s = sessions(bars());
  assert.ok(passes(s[260], { rsi: { op: 'lt', value: 30 } }));
  assert.ok(!passes(s[260], { rsi: { op: 'gt', value: 30 } }));
  assert.ok(!passes(s[100], { trend: 'above200' }));
  const conditions = [{ key: 'fed', runs: [['2020-01-01', 'HOLD'], ['2020-09-01', 'CUTTING']] }];
  assert.ok(passes(s[260], { backdrop: { fed: 'CUTTING' }, conditions }));
  assert.ok(!passes(s[100], { backdrop: { fed: 'CUTTING' }, conditions }));
});

test('decluster keeps the first trigger and skips any within the gap', () => {
  const ev = [0, 2, 4, 9, 10, 20].map((i) => ({ i }));
  assert.deepEqual(decluster(ev, 5).map((e) => e.i), [0, 9, 20]);
  assert.deepEqual(decluster(ev, 0).map((e) => e.i), [0, 2, 4, 9, 10, 20]);
});

test('outcomes run from the t0 close to day-x open and close, with cost and side', () => {
  const b = bars();
  const o = outcomes(b, 260, { horizons: [1, 5] });
  assert.ok(Math.abs(o.close1 - ((b.close[261] / b.close[260] - 1) * 100)) < 1e-12);
  assert.ok(Math.abs(o.open1 - ((b.open[261] / b.close[260] - 1) * 100)) < 1e-12);
  const short = outcomes(b, 260, { horizons: [1], side: -1, costBps: 10 });
  assert.ok(Math.abs(short.close1 - (-o.close1 - 0.1)) < 1e-12);
  assert.equal(outcomes(b, 298, { horizons: [5] }).close5, null);
});

test('stats use linear quantiles like pandas', () => {
  const s = stats([4, 1, 3, 2, NaN, null]);
  assert.deepEqual([s.n, s.min, s.max, s.median, s.p25, s.p75, s.mean, s.hit], [4, 1, 4, 2.5, 1.75, 3.25, 2.5, 1]);
  assert.equal(stats([]).n, 0);
});

test('a study finds events, honours exclusions and reports the baseline', () => {
  const b = bars();
  const all = study(b, { trigger: { kind: 'intraday', dir: -1, size: 4 }, gap: 0 });
  assert.deepEqual(all.events.map((e) => e.i), [250, 260]);
  assert.equal(all.touchedOnly, 1);            // day 250 touched −5% but closed −1%
  assert.equal(all.summary.close1.n, 2);
  assert.ok(all.baseline.close1.n > 250);
  const cut = study(b, { trigger: { kind: 'intraday', dir: -1, size: 4 }, gap: 0, exclude: [{ from: b.dates[255], to: b.dates[265] }] });
  assert.deepEqual(cut.events.map((e) => e.i), [250]);
  assert.ok(excluded('2020-03-01', [{ from: '2020-02-20', to: '2020-06-30' }]));
  const one = study(b, { trigger: { kind: 'intraday', dir: -1, size: 4 }, gap: 20 });
  assert.deepEqual(one.events.map((e) => e.i), [250]);
  assert.equal(one.raw, 2);
});

test('years, rolling median and CSV', () => {
  const ev = [['2019-05-01', 1], ['2019-06-01', -3], ['2020-01-02', 2]].map(([date, v]) => ({ date, out: { close5: v } }));
  assert.deepEqual(byYear(ev, 'close5').map((y) => [y.year, y.n, y.mean]), [['2019', 2, -1], ['2020', 1, 2]]);
  assert.deepEqual(rollingMedian(ev, 'close5', 2), [null, -1, -0.5]);
  const csv = toCsv([{ date: '2020-01-02', lowRet: -4.5, closeRet: -1, gapRet: 0, sigma: null, rsi6: 22, vs50: 1, vs200: 2, fromHigh: -3, out: { close1: 1.5 } }], 'QQQ');
  assert.ok(csv.split('\n')[1].startsWith('QQQ,2020-01-02,-4.500,-1.000,0.000,,22.0,'));
});
