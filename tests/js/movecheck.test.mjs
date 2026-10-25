// MOVE CHECK: the model on hand-made series, and the page rendered from a
// fixture under node against a small fake DOM (no charting library, no network).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/movecheck-model.js';
import renderMoveCheck from '../../web/js/tabs/movecheck.js';

const near = (actual, expected, eps = 1e-9) => assert.ok(Math.abs(actual - expected) < eps, `${actual} != ${expected}`);
const dayAt = (i, start = '2020-01-01') => new Date(Date.parse(`${start}T00:00:00Z`) + i * 864e5).toISOString().slice(0, 10);
const dated = (rets, start) => rets.map((ret, i) => ({ date: dayAt(i, start), ret }));

// --- returns and the latest move -------------------------------------------------

test('returns are close-to-close percent, dated by the closing session, and skip a pair with a missing close', () => {
  const dates = ['a', 'b', 'c', 'd', 'e'];
  const close = [100, 102, null, 99, 97.02];
  const one = M.returns(dates, close, 1);
  assert.deepEqual(one.map((r) => r.date), ['b', 'e']);
  near(one[0].ret, 2);
  near(one[1].ret, -2);
});

test('a multi-session return skips any pair that touches a missing close', () => {
  // 'e' is 101 against 99 two sessions back, but 'c' is missing; the pair from 'c' to 'e' is dropped.
  const series = M.returns(['a', 'b', 'c', 'd', 'e'], [100, 102, null, 99, 101], 2);
  assert.deepEqual(series.map((r) => r.date), ['d']);
  near(series[0].ret, (99 / 102 - 1) * 100);
});

test('a zero start close and a bad horizon give no returns', () => {
  assert.deepEqual(M.returns(['a', 'b'], [0, 5], 1), []);
  assert.deepEqual(M.returns(['a', 'b'], [1, 2], 0), []);
  assert.deepEqual(M.returns(['a', 'b'], [1, 2], 1.5), []);
});

test('the latest move is the last return, and null with no usable pair', () => {
  near(M.latestMove(['a', 'b', 'c'], [10, 9, 8.1], 1).ret, -10);
  assert.equal(M.latestMove(['a', 'b'], [null, null], 1), null);
  assert.equal(M.latestMove([], [], 1), null);
});

// --- checking a move -------------------------------------------------------------

const falls = dated([-1, -2, -3, -1, 0.5]);

test('a fall counts the returns at or below the move, the tie included, and reports the last day beyond it', () => {
  const r = M.checkMove(falls, -3);
  assert.equal(r.n, 5);
  assert.equal(r.worse, 1);
  near(r.share, 0.2);
  near(r.percentile, 10);
  assert.equal(r.lastWorse, dayAt(2));
});

test('the move\'s own session counts as beyond, but it is not the last worse day when it is the latest', () => {
  const series = dated([-1, -3.5, -2, -3]);
  const r = M.checkMove(series, -3);
  assert.equal(r.worse, 2);
  assert.equal(r.lastWorse, dayAt(1));
});

test('a move that is not the latest session can name its own date as the last worse day', () => {
  assert.equal(M.checkMove(falls, -3, { date: dayAt(2) }).lastWorse, dayAt(2));
});

test('a rise counts the returns at or above the move, with the percentile from the bottom', () => {
  const series = dated([0.5, 2, 1, -1, 3]);
  const r = M.checkMove(series, 1);
  assert.equal(r.worse, 3);
  near(r.share, 0.6);
  near(r.percentile, 50);
  assert.equal(r.lastWorse, dayAt(2));
});

test('a lookback keeps only the last sessions, and a window with no day beyond the move says so', () => {
  const r = M.checkMove(falls, -3, { lookbackSessions: 2 });
  assert.equal(r.n, 2);
  assert.equal(r.worse, 0);
  assert.equal(r.lastWorse, null);
  near(r.share, 0);
});

test('per year is the days beyond the move over the years the window covers', () => {
  const series = [{ date: '2020-01-01', ret: -2 }, { date: '2022-01-01', ret: -1 }];
  const r = M.checkMove(series, -1.5);
  const years = 731 / 365.25;
  near(r.years, years);
  near(r.perYear, 1 / years);
});

test('an empty window or a move that is not a number gives no figures', () => {
  const empty = M.checkMove([], -3);
  assert.equal(empty.n, 0);
  assert.equal(empty.share, null);
  assert.equal(empty.percentile, null);
  assert.equal(M.checkMove(falls, NaN).share, null);
});

// --- volatility -----------------------------------------------------------------

test('a move is measured against the twenty daily returns before its own session', () => {
  const alternating = Array.from({ length: 21 }, (_, i) => ({ date: dayAt(i), ret: i % 2 ? -1 : 1 }));
  const sd = Math.sqrt(20 / 19);
  near(M.sigmaOf(alternating, -2.05), -2.05 / sd, 1e-9);
  // The last entry is the move's own day, so changing it changes nothing.
  const changed = alternating.map((r, i) => (i === 20 ? { ...r, ret: 50 } : r));
  near(M.sigmaOf(changed, -2.05), -2.05 / sd, 1e-9);
});

test('a longer horizon scales the volatility by the square root of its sessions', () => {
  const alternating = Array.from({ length: 21 }, (_, i) => ({ date: dayAt(i), ret: i % 2 ? -1 : 1 }));
  near(M.sigmaOf(alternating, -2.05, 20, 4), -2.05 / (Math.sqrt(20 / 19) * 2), 1e-9);
});

test('too little data, no variation or no move gives no sigma', () => {
  const short = Array.from({ length: 20 }, (_, i) => ({ date: dayAt(i), ret: i % 2 ? -1 : 1 }));
  assert.equal(M.sigmaOf(short, -2), null);
  const flat = Array.from({ length: 25 }, (_, i) => ({ date: dayAt(i), ret: 0.5 }));
  assert.equal(M.sigmaOf(flat, -2), null);
  assert.equal(M.sigmaOf(flat, null), null);
});

// --- episodes -------------------------------------------------------------------

test('days beyond the move merge when they are within five sessions, and each episode gives its worst day', () => {
  const series = dated([-1, -3.5, -4, -1, -1, -1, -1, -1, -1, -3.2, -1, -5, -1]);
  assert.deepEqual(M.episodes(series, -3), [
    { start: dayAt(1), worstDate: dayAt(2), worst: -4 },
    { start: dayAt(9), worstDate: dayAt(11), worst: -5 },
  ]);
});

test('the gap is inclusive: five sessions apart merge, six do not', () => {
  const five = dated([-4, -1, -1, -1, -1, -4.5]);
  assert.deepEqual(M.episodes(five, -3), [{ start: dayAt(0), worstDate: dayAt(5), worst: -4.5 }]);
  const six = dated([-4, -1, -1, -1, -1, -1, -4.5]);
  assert.equal(M.episodes(six, -3).length, 2);
});

test('a rise gathers the days at or above it, and a tie keeps the first worst day', () => {
  const rise = M.episodes(dated([0, 3, 1, 2.5]), 2);
  assert.deepEqual(rise, [{ start: dayAt(1), worstDate: dayAt(1), worst: 3 }]);
  assert.deepEqual(M.episodes(dated([-4, -4]), -3), [{ start: dayAt(0), worstDate: dayAt(0), worst: -4 }]);
});

test('no day beyond the move gives no episodes', () => {
  assert.deepEqual(M.episodes(dated([-1, 0.5, 2]), -3), []);
  assert.deepEqual(M.episodes(null, -3), []);
});

// --- forward returns and drawdown -------------------------------------------------

const DATES = Array.from({ length: 10 }, (_, i) => `d${i}`);

test('a forward return runs from the date\'s close to the close the sessions later', () => {
  const close = [100, 101, null, 103, 104, 105, 106, 107, 108, 109];
  near(M.forward(DATES, close, 'd0', 3), 3);
  near(M.forward(DATES, close, 'd0', 1), 1);
  assert.equal(M.forward(DATES, close, 'd2', 1), null, 'a missing start close');
  assert.equal(M.forward(DATES, close, 'd0', 2), null, 'a missing end close');
  assert.equal(M.forward(DATES, close, 'd8', 2), null, 'beyond the last session');
  assert.equal(M.forward(DATES, close, 'nope', 1), null, 'an unknown date');
});

test('the worst close after a date, against its close, never above zero', () => {
  const dates = Array.from({ length: 8 }, (_, i) => `d${i}`);
  const close = [100, 105, 90, null, 95, 120, 80, 85];
  near(M.maxDrawdownAfter(dates, close, 'd0', 3), -10);
  assert.equal(M.maxDrawdownAfter(dates, close, 'd0', 1), 0, 'a higher close is not a drawdown');
  near(M.maxDrawdownAfter(dates, close, 'd4', 2), (80 / 95 - 1) * 100);
  assert.equal(M.maxDrawdownAfter(dates, close, 'd6', 2), null, 'the window runs past the end');
  assert.equal(M.maxDrawdownAfter(['a', 'b', 'c'], [100, null, null], 'a', 2), null, 'no close in the window');
  assert.ok(M.maxDrawdownAfter(dates, [100, 110, 120, 130, 140, 150, 160, 170], 'd0', 3) <= 0);
});

// --- histogram ------------------------------------------------------------------

test('a histogram counts each value once, the top edge in the last bin', () => {
  const h = M.histogram([1, 2, 2, 3, 10], 3);
  assert.deepEqual(h.edges, [1, 4, 7, 10]);
  assert.deepEqual(h.counts, [4, 0, 1]);
  assert.equal(h.counts.reduce((a, b) => a + b, 0), 5);
});

test('the axis can stretch to include a value the counts leave out, such as the move', () => {
  const h = M.histogram([1, 2, 2, 3, 10], 3, { include: [-5] });
  assert.deepEqual(h.edges, [-5, 0, 5, 10]);
  assert.deepEqual(h.counts, [0, 4, 1]);
});

test('an empty or one-valued histogram is still well formed', () => {
  assert.deepEqual(M.histogram([], 5), { edges: [], counts: [] });
  assert.deepEqual(M.histogram([null, NaN, 1], 1).counts, [1]);
  const same = M.histogram([2, 2], 2);
  assert.deepEqual(same.counts, [0, 2]);
  assert.equal(same.edges.length, 3);
});

test('a value is placed in its bin, clamped to the axis', () => {
  const edges = [1, 4, 7, 10];
  assert.equal(M.binIndex(edges, 0), 0);
  assert.equal(M.binIndex(edges, 4), 1);
  assert.equal(M.binIndex(edges, 10), 2);
  assert.equal(M.binIndex(edges, null), null);
});

// --- text ------------------------------------------------------------------------

test('a figure prints a true minus, a plus on a rise, and a dash when absent', () => {
  assert.equal(M.signedPct(-3), '−3.0%');
  assert.equal(M.signedPct(0.5), '+0.5%');
  assert.equal(M.signedPct(-2.9873), '−2.99%');
  assert.equal(M.signedPct(0), '0.0%');
  assert.equal(M.signedPct(NaN), '—');
  assert.equal(M.signedPct(null), '—');
});

test('ordinals take the teen and the 1-2-3 endings right', () => {
  assert.deepEqual([1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111].map(M.ordinal), ['1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '101st', '111th']);
});

const ALL = { n: 2515, worse: 61, share: 61 / 2515, percentile: 2.41, perYear: 6.1, lastWorse: '2026-08-14', years: 9.99 };

test('the headline leads with the share of days, for a fall', () => {
  assert.equal(
    M.moveSentence({ ticker: 'QQQ', horizon: 1, move: -3, date: '2026-10-21', all: ALL }),
    'QQQ −3.0% over 1 day (2026-10-21). Only 2.4% of trading days in 10 years fell this far or further '
      + '(about 6 a year); the last was 2026-08-14.',
  );
});

test('a common move is stated plainly, without "Only"', () => {
  const common = { ...ALL, worse: 381, share: 381 / 2511, perYear: 38 };
  const text = M.moveSentence({ ticker: 'QQQ', horizon: 1, move: 1.21, date: '2026-10-19', all: common });
  assert.ok(text.includes('(2026-10-19). 15.2% of trading days'), text);
});

test('the headline reads for a rise, and names the horizon in sessions', () => {
  const text = M.moveSentence({ ticker: 'SPY', horizon: 5, move: 3, date: '2026-10-21', all: { ...ALL, percentile: 97.6 } });
  assert.equal(text, 'SPY +3.0% over 5 sessions (2026-10-21). Only 2.4% of trading days in 10 years rose this far or further '
    + '(about 6 a year); the last was 2026-08-14.');
});

test('the headline says when no day was as far, and when there was no earlier day', () => {
  const none = M.moveSentence({ ticker: 'QQQ', horizon: 1, move: -9, date: '2026-10-21', all: { ...ALL, worse: 0, lastWorse: null } });
  assert.equal(none, 'QQQ −9.0% over 1 day (2026-10-21). In 10 years of history no day fell this far.');
  const first = M.moveSentence({ ticker: 'QQQ', horizon: 1, move: -3, date: '2026-10-21',
    all: { n: 500, worse: 1, share: 0.002, percentile: 0.1, perYear: 0.5, lastWorse: null, years: 2 } });
  assert.equal(first, 'QQQ −3.0% over 1 day (2026-10-21). Only 0.2% of trading days in 2 years fell this far or further '
    + '(about 0.5 a year); no earlier day was that far.');
});

test('a share under a tenth of a percent reads as fewer than that, and a missing window drops its years', () => {
  const tiny = M.moveSentence({ ticker: 'QQQ', horizon: 1, move: -9, date: '2026-10-21',
    all: { n: 9000, worse: 3, share: 3 / 9000, percentile: 0.01, perYear: null, lastWorse: '1987-10-19', years: null } });
  assert.equal(tiny, 'QQQ −9.0% over 1 day (2026-10-21). Fewer than 0.1% of trading days fell this far or further; '
    + 'the last was 1987-10-19.');
});

test('the headline is a plain sentence when there is no history to place the move in', () => {
  assert.equal(M.moveSentence({ ticker: 'QQQ', horizon: 1, move: -3, date: '2026-10-21', all: null }),
    'QQQ −3.0% over 1 day (2026-10-21). Not enough history to place this move.');
});

// --- episode context ------------------------------------------------------------

const CONTEXT_DATES = Array.from({ length: 10 }, (_, i) => `d${i}`);
const CONTEXT_CLOSE = [100, 110, 105, 120, 118, 115, 130, 128, 127, 125];

test('the drop from the high is taken on the session before, against the highest close in the full year', () => {
  const dates = Array.from({ length: 300 }, (_, i) => dayAt(i));
  const close = Array.from({ length: 300 }, (_, i) => (i === 250 ? 200 : 100));
  near(M.drawdownBefore(dates, close, dayAt(260)), -50);
  // A year is not all in the build: no partial high.
  assert.equal(M.drawdownBefore(CONTEXT_DATES, CONTEXT_CLOSE, 'd9'), null);
  assert.equal(M.drawdownBefore(CONTEXT_DATES, CONTEXT_CLOSE, 'd1', 2), null, 'the window runs before the first session');
  assert.equal(M.drawdownBefore(CONTEXT_DATES, CONTEXT_CLOSE, 'nope', 2), null);
  near(M.drawdownBefore(CONTEXT_DATES, CONTEXT_CLOSE, 'd3', 3), (105 / 110 - 1) * 100, 1e-9);
  assert.equal(M.drawdownBefore(CONTEXT_DATES, [100, 110, null, 120], 'd3', 3), null, 'a missing close on the session before');
});

test('the return over the sessions before the move runs from the close back to the close the session before', () => {
  near(M.returnBefore(CONTEXT_DATES, CONTEXT_CLOSE, 'd3', 2), 5);
  assert.equal(M.returnBefore(CONTEXT_DATES, CONTEXT_CLOSE, 'd2', 2), null, 'too early in the history');
  assert.equal(M.returnBefore(CONTEXT_DATES, [100, 110, 105, 120, 118, null, 130], 'd6', 3), null, 'a missing close');
});

test('a value on a date, else the last one before it within five calendar days', () => {
  const vd = ['2020-01-02', '2020-01-03', '2020-01-06'];
  const vv = [10, null, 12];
  assert.equal(M.valueOn(vd, vv, '2020-01-02'), 10);
  assert.equal(M.valueOn(vd, vv, '2020-01-03'), 10, 'a missing value falls back to the day before');
  assert.equal(M.valueOn(vd, vv, '2020-01-04'), 10, 'a Saturday takes the last session before it');
  assert.equal(M.valueOn(vd, vv, '2020-01-06'), 12);
  assert.equal(M.valueOn(vd, vv, '2020-01-15'), null, 'nothing within five days');
  assert.equal(M.valueOn(vd, vv, '2019-12-01'), null, 'before the history');
  assert.equal(M.valueOn(vd, vv, 'nope'), null);
  assert.equal(M.valueOn(null, null, '2020-01-02'), null);
});

test('a percentile is the mid-rank among the finite values, and null with none', () => {
  near(M.percentileOf([1, 2, 3, 4, 5], 3), 50);
  near(M.percentileOf([1, 2, 3], 0), 0);
  near(M.percentileOf([1, 2, 3], 9), 100);
  near(M.percentileOf([null, 2, 3], 2), 25);
  assert.equal(M.percentileOf([], 1), null);
  assert.equal(M.percentileOf([1, 2], null), null);
});

test('the context of a day gives the drop, the prior return, and the VIX level, its percentile and its change', () => {
  const isoDates = CONTEXT_DATES.map((_, i) => dayAt(i));
  const vix = { dates: isoDates, close: [10, 12, 11, 14, 13, 15, 9, 16, 17, 18] };
  const c = M.contextOn({ dates: isoDates, close: CONTEXT_CLOSE, vix, date: dayAt(5) });
  assert.equal(c.fromHigh, null, 'a short history has no full year');
  assert.equal(c.prior20, null);
  assert.equal(c.vix, 15);
  near(c.vixChange, 2, 1e-9);
  near(c.vixPct, (5 + 0.5) / 6 * 100, 1e-9);
  const none = M.contextOn({ dates: isoDates, close: CONTEXT_CLOSE, vix: null, date: dayAt(5) });
  assert.equal(none.vix, null);
  assert.equal(none.vixPct, null);
  assert.equal(none.vixChange, null);
});

test('buckets count the edges a value reaches, and the drop is bucketed by its size', () => {
  assert.equal(M.bucketOf(14.9, M.VIX_EDGES), 0);
  assert.equal(M.bucketOf(15, M.VIX_EDGES), 1);
  assert.equal(M.bucketOf(19.99, M.VIX_EDGES), 1);
  assert.equal(M.bucketOf(20, M.VIX_EDGES), 2);
  assert.equal(M.bucketOf(30, M.VIX_EDGES), 3);
  assert.equal(M.bucketOf(null, M.VIX_EDGES), null);
  assert.equal(M.drawdownBucket(-3), 0);
  assert.equal(M.drawdownBucket(-5), 1);
  assert.equal(M.drawdownBucket(-10), 2);
  assert.equal(M.drawdownBucket(-25), 3);
  assert.equal(M.drawdownBucket(0), 0);
  assert.equal(M.drawdownBucket(undefined), null);
});

test('similar setups match on both buckets, and summarise the forward returns and the drawdown', () => {
  const rows = [
    { vix: 12, fromHigh: -2, forward: [1, 3, 5], drawdown: -1 },
    { vix: 13, fromHigh: -3, forward: [0, 2, -1], drawdown: -2 },
    { vix: 14, fromHigh: -1, forward: [-1, 4, 6], drawdown: -3 },
    { vix: 16, fromHigh: -12, forward: [2, -2, 10], drawdown: -15 },
    { vix: 40, fromHigh: -25, forward: [3, -4, 1], drawdown: -30 },
    { vix: 11, fromHigh: -4, forward: [0.5, 1, 2], drawdown: -6 },
  ];
  const s = M.similarSetups(rows, { vix: 12, fromHigh: -2 });
  assert.equal(s.vixBucket, 0);
  assert.equal(s.drawdownBucket, 0);
  assert.equal(s.matched.n, 4);
  near(s.matched.median5, 2.5);
  near(s.matched.positive5, 1);
  near(s.matched.median20, 3.5);
  near(s.matched.positive20, 0.75);
  near(s.matched.medianDrawdown, -2.5);
  assert.equal(s.all.n, 6);
  near(s.all.median5, 1.5);
  near(s.all.positive5, 4 / 6);
  near(s.all.median20, 3.5);
  near(s.all.medianDrawdown, -4.5);
  const noVix = M.similarSetups(rows, { vix: null, fromHigh: -2 });
  assert.equal(noVix.matched.n, 0, 'no VIX today, nothing matches');
  assert.equal(noVix.all.n, 6);
});

// --- against all days -----------------------------------------------------------------

test('every start day reads the same forward returns and worst drawdown an episode would, and a day past the data reads none', () => {
  const dates = Array.from({ length: 25 }, (_, i) => `d${i}`);
  const close = Array.from({ length: 25 }, (_, i) => (i === 5 ? 80 : 100));
  const rows = M.dayRows(dates, close, ['d0', 'd24', 'nope']);
  near(rows[0].forward[0], 0);
  near(rows[0].forward[1], -20);
  near(rows[0].forward[2], 0);
  near(rows[0].drawdown, -20);
  assert.deepEqual(rows[1].forward, [null, null, null], 'no session after the last');
  assert.equal(rows[1].drawdown, null);
  assert.deepEqual(rows[2].forward, [null, null, null], 'an unknown day');
  near(rows[0].drawdown, M.maxDrawdownAfter(dates, close, 'd0', 20));
});

test('the follow-up figures are the median and the share up of each horizon over the rows that have it', () => {
  const rows = [
    { forward: [1, -1, null], drawdown: -2 },
    { forward: [-3, 2, 8], drawdown: -6 },
    { forward: [3, null, null], drawdown: null },
  ];
  const f = M.followUp(rows);
  assert.equal(f.n, 3);
  assert.deepEqual(f.forward.map((x) => x.n), [3, 2, 1]);
  near(f.forward[0].median, 1);
  near(f.forward[0].share, 2 / 3);
  near(f.forward[1].median, 0.5);
  near(f.forward[1].share, 0.5);
  near(f.forward[2].median, 8);
  near(f.forward[2].share, 1);
  assert.equal(f.drawdown.n, 2);
  near(f.drawdown.median, -4);
  const none = M.followUp([]);
  assert.equal(none.n, 0);
  assert.equal(none.forward[0].median, null);
  assert.equal(none.drawdown.median, null);
});

test('the difference is episodes minus all days in points, and a share is scaled from a fraction to points', () => {
  const episodes = { n: 4, forward: [{ n: 4, median: 2, share: 0.5 }, { n: 4, median: -1, share: 0.25 }, { n: 0, median: null, share: null }],
    drawdown: { n: 4, median: -5 } };
  const baseline = { n: 100, forward: [{ n: 100, median: 0.5, share: 0.25 }, { n: 100, median: 0.5, share: 0.5 }, { n: 90, median: 1, share: 0.6 }],
    drawdown: { n: 100, median: -3 } };
  const d = M.compareFollowUp(episodes, baseline);
  near(d.forward[0].median, 1.5);
  near(d.forward[0].share, 25);
  near(d.forward[1].median, -1.5);
  near(d.forward[1].share, -25);
  assert.equal(d.forward[2].median, null, 'no episode figure, no difference');
  assert.equal(d.forward[2].share, null);
  near(d.drawdown, -2);
});

test('an interval is null under five episodes, and collapses to the value when every episode is alike', () => {
  const alike = (k) => Array.from({ length: k }, () => ({ forward: [2, 2, 2], drawdown: -1 }));
  assert.equal(M.bootstrapFollowUp(alike(4)), null);
  const flat = M.bootstrapFollowUp(alike(6), { resamples: 200 });
  assert.equal(flat.n, 6);
  assert.deepEqual(flat.forward[0], { median: [2, 2], share: [1, 1] });
});

test('the episode interval is the same on every run, and brackets the median of a spread of episodes', () => {
  const rows = Array.from({ length: 12 }, (_, i) => ({ forward: [i - 5.5, i - 5.5, i - 5.5], drawdown: -i }));
  const a = M.bootstrapFollowUp(rows);
  assert.deepEqual(a, M.bootstrapFollowUp(rows), 'a fixed seed');
  const [lo, hi] = a.forward[2].median;
  assert.ok(lo < 0 && hi > 0, `${lo}..${hi} should bracket the median of 0`);
  assert.ok(lo < hi);
  const [slo, shi] = a.forward[0].share;
  assert.ok(slo <= 0.5 && shi >= 0.5, `${slo}..${shi} should bracket the share of 0.5`);
});

test('the episodes span their worst days\' first and last years, and none gives null', () => {
  const rows = [{ worstDate: '2011-08-08' }, { worstDate: '2026-02-03' }, { worstDate: '2019-05-01' }];
  assert.deepEqual(M.episodeYears(rows), { first: 2011, last: 2026 });
  assert.equal(M.episodeYears([]), null);
});

test('the middle date is halfway between two dates, and the halves split on it by worst day', () => {
  assert.equal(M.midDate('2020-01-01', '2020-01-11'), '2020-01-06');
  assert.equal(M.midDate('2020-01-01', 'nope'), null);
  const rows = ['2020-01-02', '2020-01-05', '2020-01-06', '2020-01-10'].map((worstDate) => ({ worstDate }));
  const h = M.halves(rows, '2020-01-01', '2020-01-11');
  assert.equal(h.middle, '2020-01-06');
  assert.deepEqual(h.earlier.map((r) => r.worstDate), ['2020-01-02', '2020-01-05']);
  assert.deepEqual(h.later.map((r) => r.worstDate), ['2020-01-06', '2020-01-10'], 'the middle day is in the later half');
  assert.deepEqual(M.halves(rows, 'x', 'y'), { middle: null, earlier: [], later: [] });
});

// --- overnight gaps ----------------------------------------------------------------

test('an overnight gap is the open against the prior close, and a session missing a price has none', () => {
  const bars = {
    dates: ['d0', 'd1', 'd2', 'd3', 'd4'],
    open: [100, 103.02, null, 99.96, 99.96],
    close: [100, 102, 102, 0, 101],
  };
  const g = M.overnightGaps(bars);
  assert.deepEqual(g.map((r) => r.date), ['d1', 'd3']);
  near(g[0].gap, 3.02);
  near(g[1].gap, -2);
  assert.deepEqual(M.overnightGaps({}), []);
});

test('gap percentiles interpolate between neighbours, the share counts gaps beyond two per cent, and the latest sits at its percentile', () => {
  const gaps = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((gap, i) => ({ date: dayAt(i), gap }));
  const s = M.gapSummary(gaps);
  assert.equal(s.n, 10);
  assert.equal(s.from, dayAt(0));
  assert.equal(s.to, dayAt(9));
  const at = (p) => s.percentiles.find((x) => x.p === p).value;
  near(at(5), 1.45);
  near(at(50), 5.5);
  near(at(95), 9.55);
  near(s.shareLarge, 0.8, 1e-12);
  assert.deepEqual(s.up.map((g) => g.gap), [10, 9, 8, 7, 6]);
  assert.deepEqual(s.down, []);
  assert.equal(s.latest.date, dayAt(9));
  near(s.latest.percentile, 95);
});

test('the largest gaps down are the most negative, and no gap either way leaves that list empty', () => {
  const s = M.gapSummary([{ date: 'a', gap: -3 }, { date: 'b', gap: -1 }, { date: 'c', gap: 0.5 }]);
  assert.deepEqual(s.down.map((g) => g.gap), [-3, -1]);
  assert.deepEqual(s.up.map((g) => g.gap), [0.5]);
  assert.equal(M.gapSummary([]), null);
});

// --- the page----------------------------------------------------------------------

class FakeNode {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this.style = {};
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener() {}
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

const fakeDocument = () => ({
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
});

// Everything a reader would see: text, attributes and option labels included.
function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.text;
  const own = [node.textContent || '', node.attrs?.value || '', node.attrs?.['aria-label'] || ''];
  return [...own, ...(node.children || []).map(textOf)].filter(Boolean).join(' ');
}

function findNode(node, predicate) {
  if (predicate(node)) return node;
  for (const child of node.children || []) {
    const hit = findNode(child, predicate);
    if (hit) return hit;
  }
  return null;
}

async function withBrowser(run) {
  const saved = { document: globalThis.document, window: globalThis.window };
  globalThis.document = fakeDocument();
  globalThis.window = {};
  try {
    return await run();
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
}

// A year of closes with a sine wobble, a missing close mid-way and a 3% fall on the last session.
function fixtureTicker(count = 300) {
  const dates = Array.from({ length: count }, (_, i) => dayAt(i));
  const close = Array.from({ length: count }, (_, i) => 100 * (1 + 0.01 * Math.sin(i)) + i * 0.05);
  close[50] = null;
  close[count - 1] = close[count - 2] * 0.97;
  return { ticker: 'FIX', dates, close };
}

function ctxWith(payloads, arg = 'FIX') {
  const calls = { setArg: [] };
  const ctx = {
    arg,
    calls,
    loadArtifact: async (name) => {
      const key = name.replace(/^tickers\//, '');
      if (!payloads[key]) throw new Error(`${key}.json returned 404`);
      return payloads[key];
    },
    setArg: (next) => calls.setArg.push(next),
  };
  return ctx;
}

const BAD = /NaN|undefined|\[object Object\]/;

test('the page renders the headline, stats, histogram and episodes with no bad figures', async () => {
  const ctx = ctxWith({ FIX: fixtureTicker(), SPY: fixtureTicker(120) });
  const data = { available: ['FIX', 'SPY'] };
  const text = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, data, null, ctx);
    return textOf(root);
  });
  assert.ok(text.includes('FIX'), 'names the ticker');
  assert.ok(text.includes('fell this far or further'), 'a fall is read as a fall');
  assert.ok(text.includes('EPISODES BEYOND THIS MOVE'));
  assert.ok(text.includes('IN TODAY\'S VOLATILITY'));
  assert.ok(text.includes('Description, not a signal'));
  assert.ok(!BAD.test(text), `bad figure in page text: ${text.match(BAD)?.[0]}`);
  assert.deepEqual(ctx.calls.setArg, ['FIX'], 'the hash keeps the ticker');
});

test('a button press re-runs the check at another horizon, with the box set to that horizon\'s latest move', async () => {
  const ctx = ctxWith({ FIX: fixtureTicker(), SPY: fixtureTicker(120) });
  const data = { available: ['FIX', 'SPY'] };
  await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, data, null, ctx);
    const fiveDay = findNode(root, (n) => n.tagName === 'BUTTON' && n.textContent === '5D');
    assert.ok(fiveDay, 'the 5D button is there');
    fiveDay.listeners.click[0]();
    await new Promise((resolve) => setTimeout(resolve, 0));
    const text = textOf(root);
    assert.ok(text.includes('over 5 sessions'), 'the headline names five sessions');
    assert.ok(!BAD.test(text));
  });
});

test('a short history says so in words, and an unknown ticker is named', async () => {
  const tiny = { dates: ['2026-01-01', '2026-01-02'], close: [10, null] };
  const data = { available: ['TINY', 'FIX'] };
  const short = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, data, null, ctxWith({ TINY: tiny }, 'TINY'));
    return textOf(root);
  });
  assert.ok(short.includes('Not enough history for TINY'));
  assert.ok(!BAD.test(short));

  const missing = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, data, null, ctxWith({ FIX: fixtureTicker() }, 'NOPE'));
    return textOf(root);
  });
  assert.ok(missing.includes('FIX'), 'an unknown ticker falls back to the first in the build');
  assert.ok(!BAD.test(missing));
});

test('a ticker whose file fails to load says so, without a bad figure', async () => {
  const data = { available: ['FIX', 'SPY'] };
  const text = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, data, null, ctxWith({}, 'SPY'));
    return textOf(root);
  });
  assert.ok(text.includes('SPY could not be loaded'));
  assert.ok(!BAD.test(text));
});

test('the page reads the VIX history and shows the episode context, the setups and the move row', async () => {
  const vix = { dates: isoDays(300), close: Array.from({ length: 300 }, (_, i) => 15 + Math.sin(i) * 3) };
  const ctx = ctxWith({ FIX: fixtureTicker(), 'context/vix': vix });
  const data = { available: ['FIX'] };
  const text = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, data, null, ctx);
    return textOf(root);
  });
  assert.ok(text.includes('SIMILAR SETUPS'));
  assert.ok(text.includes('MATCHING TODAY'));
  assert.ok(text.includes('ALL EPISODES'));
  assert.ok(text.includes('FROM 1Y HIGH'));
  assert.ok(!text.includes('VIX history was not available'));
  assert.ok(!BAD.test(text), `bad figure in page text: ${text.match(BAD)?.[0]}`);
});

test('without the VIX file the VIX columns are dashes and a note says so', async () => {
  const ctx = ctxWith({ FIX: fixtureTicker() });
  const data = { available: ['FIX'] };
  const text = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, data, null, ctx);
    return textOf(root);
  });
  assert.ok(text.includes('VIX history was not available in this build'));
  assert.ok(!BAD.test(text), `bad figure in page text: ${text.match(BAD)?.[0]}`);
});

function isoDays(count) {
  return Array.from({ length: count }, (_, i) => dayAt(i));
}

// Every tenth session falls 4% and the rest rise 0.2%; the last session falls 3%. The falls are ten sessions
// apart, so the episodes are known: floor((count - 2) / 10) of them.
function stepTicker(count = 300) {
  const dates = Array.from({ length: count }, (_, i) => dayAt(i));
  const close = [100];
  for (let i = 1; i < count; i += 1) {
    const r = i === count - 1 ? -3 : i % 10 === 0 ? -4 : 0.2;
    close.push(close[i - 1] * (1 + r / 100));
  }
  return { ticker: 'STEP', dates, close };
}

// Opens a little off each close, so the gaps follow the day's moves and a missing close leaves a missing open.
function barsOf({ dates, close }) {
  return { ticker: 'X', dates, close, open: close.map((c, i) => (c === null ? null : c * (1 + 0.001 * Math.sin(i)))) };
}

test('the move links to the ticker page, its technicals and the trade desk', async () => {
  const ctx = ctxWith({ FIX: fixtureTicker() });
  await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, { available: ['FIX'] }, null, ctx);
    for (const href of ['#ticker/FIX', '#technicals/FIX', '#trade/FIX']) {
      assert.ok(findNode(root, (n) => n.tagName === 'A' && n.attrs.href === href), `a link to ${href}`);
    }
    assert.ok(textOf(root).includes('TRADE DESK'));
  });
});

test('the episodes are set against all days, with the baseline, the difference, the interval, the years and the two periods', async () => {
  const ctx = ctxWith({ STEP: stepTicker(300), 'bars/STEP': barsOf(stepTicker(300)) });
  const text = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, { available: ['STEP'] }, null, ctx);
    return textOf(root);
  });
  assert.ok(text.includes('EPISODES AGAINST ALL DAYS'));
  assert.ok(text.includes('ALL DAYS (BASELINE)'));
  assert.ok(text.includes('DIFFERENCE'));
  assert.ok(text.includes('N = 29 independent episodes'), text.match(/N = [^.]*/)?.[0]);
  assert.ok(text.includes('5th to 95th percentile'));
  assert.ok(!text.includes('interval is wide'), 'twenty-nine episodes is not wide');
  assert.ok(text.includes('CONSISTENCY ACROSS TWO PERIODS'));
  assert.ok(text.includes('EARLIER (before'));
  assert.ok(text.includes('LATER (from'));
  assert.ok(text.includes('Episodes span 2020 to 2020.'));
  assert.ok(!BAD.test(text), `bad figure in page text: ${text.match(BAD)?.[0]}`);
});

test('under twenty episodes the interval is called wide, and under five it is not shown', async () => {
  const few = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, { available: ['STEP'] }, null, ctxWith({ STEP: stepTicker(120) }, 'STEP'));
    return textOf(root);
  });
  assert.ok(few.includes('N = 11 independent episodes'));
  assert.ok(few.includes('Under 20 episodes, so the interval is wide.'));

  const fewer = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, { available: ['STEP'] }, null, ctxWith({ STEP: stepTicker(45) }, 'STEP'));
    return textOf(root);
  });
  assert.ok(fewer.includes('N = 4 independent episodes: no interval'));
  assert.ok(!fewer.includes('5th to 95th percentile'));
  assert.ok(!BAD.test(fewer), `bad figure in page text: ${fewer.match(BAD)?.[0]}`);
});

test('the overnight gaps card shows the latest gap, the share beyond two per cent, the percentiles and the largest gaps', async () => {
  const ctx = ctxWith({ STEP: stepTicker(300), 'bars/STEP': barsOf(stepTicker(300)) });
  const text = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, { available: ['STEP'], bars: ['STEP'] }, null, ctx);
    return textOf(root);
  });
  assert.ok(text.includes('OVERNIGHT GAPS'));
  assert.ok(text.includes('LATEST GAP'));
  assert.ok(text.includes('SESSIONS OVER 2%'));
  assert.ok(text.includes('LARGEST GAPS UP'));
  assert.ok(text.includes('LARGEST GAPS DOWN'));
  assert.ok(text.includes('Empirical percentiles, no fitted curve'));
  assert.ok(!BAD.test(text), `bad figure in page text: ${text.match(BAD)?.[0]}`);
});

test('a ticker without daily bars gets a one-line note in the gap card, and nothing else breaks', async () => {
  const text = await withBrowser(async () => {
    const root = new FakeNode('div');
    await renderMoveCheck(root, { available: ['FIX', 'SPY'], bars: ['SPY'] }, null, ctxWith({ FIX: fixtureTicker() }));
    return textOf(root);
  });
  assert.ok(text.includes('FIX has no daily bars in this build, so there are no overnight gaps.'));
  assert.ok(text.includes('EPISODES BEYOND THIS MOVE'));
  assert.ok(!BAD.test(text));
});
