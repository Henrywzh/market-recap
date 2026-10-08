// The event card's drawings: where a range puts its marks, how the estimate
// trail is rebuilt and worded, how the report-day moves are laid out.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as V from '../../web/js/event-visuals.js';

const near = (a, b, tol = 0.01) => assert.ok(Math.abs(a - b) <= tol, `${a} is not within ${tol} of ${b}`);

test('a range puts low before the consensus before high, and the reference outside it when it is', () => {
  const g = V.rangeGeometry(5.59, 6.23, 5.94, 5.07);
  assert.ok(g.refAt < g.boxLeft, 'a year-ago figure below the low sits left of the box');
  assert.ok(g.boxLeft < g.pointAt && g.pointAt < g.boxLeft + g.boxWidth);
  assert.equal(g.outside, false);
  assert.ok(g.refAt >= 0 && g.boxLeft + g.boxWidth <= 100);
});

test('a consensus outside its own range is flagged, and the axis still contains it', () => {
  const g = V.rangeGeometry(5.59, 6.23, 6.5);
  assert.equal(g.outside, true);
  assert.ok(g.pointAt <= 100 && g.pointAt > g.boxLeft + g.boxWidth);
});

test('a range with a missing figure draws nothing rather than guessing', () => {
  assert.equal(V.rangeGeometry(null, 6.23, 5.94), null);
  assert.equal(V.rangeGeometry(5.59, 6.23, null), null);
  assert.equal(V.rangeGeometry(6.5, 6.23, 6.3), null);
});

test('the trail rebuilds each window from the change to now', () => {
  const levels = V.trailLevels(5.9072, { '7d': -0.1, '30d': 0.0, '60d': 0.0, '90d': 8.2 });
  assert.deepEqual(levels.map((p) => p.label), ['90d', '60d', '30d', '7d', 'now']);
  near(levels[0].value, 5.9072 / 1.082, 1e-9);
  assert.equal(levels[4].value, 5.9072);
});

test('a window with no reading is left out; no estimate means no trail', () => {
  const levels = V.trailLevels(10, { '7d': null, '30d': 2, '60d': undefined, '90d': 5 });
  assert.deepEqual(levels.map((p) => p.label), ['90d', '30d', 'now']);
  assert.deepEqual(V.trailLevels(null, { '90d': 5 }), []);
  assert.deepEqual(V.trailLevels(10, null), []);
});

test('the trail text names the net change and where it happened', () => {
  const levels = V.trailLevels(5.9072, { '7d': -0.1, '30d': 0.0, '60d': 0.0, '90d': 8.2 });
  assert.match(V.trailText(levels), /^\+8\.2% over 90d · most of it between 90d and 60d ago$/);
});

test('a change spread across the windows is not placed in one of them; a flat trail says flat', () => {
  const spread = V.trailLevels(110, { '7d': 1, '30d': 3, '60d': 6, '90d': 10 });
  assert.doesNotMatch(V.trailText(spread), /most of it/);
  const flat = V.trailLevels(100, { '7d': 0.1, '30d': -0.2, '60d': 0.1, '90d': 0.2 });
  assert.equal(V.trailText(flat), 'flat over 90d');
  assert.equal(V.trailText([]), null);
});

test('revision shares add to 100 and an empty month has none', () => {
  const s = V.splitShares(2, 1);
  near(s.up, 66.67, 0.01); near(s.down, 33.33, 0.01);
  assert.equal(V.splitShares(0, 0), null);
  assert.equal(V.splitShares(null, undefined), null);
  assert.deepEqual(V.splitShares(3, null), { up: 100, down: 0 });
});

test('the reaction bars run oldest to newest and mark a beat the stock sold', () => {
  const history = [
    { date: '2026-07-14', move_pct: 2.5, surprise_pct: 9.8 },
    { date: '2026-04-14', move_pct: -0.82, surprise_pct: 8.2 },
    { date: '2026-01-13', move_pct: -4.19, surprise_pct: -2 },
    { date: '2025-10-14', move_pct: null, surprise_pct: 5 },
  ];
  const { scale, bars } = V.moveBars(history);
  assert.deepEqual(bars.map((b) => b.date), ['2026-01-13', '2026-04-14', '2026-07-14']);
  assert.equal(scale, 4.19);
  assert.deepEqual(bars.map((b) => b.fell), [false, true, false], 'a miss that fell is not "beat then fell"');
});

test('no reports gives no bars and a zero scale', () => {
  assert.deepEqual(V.moveBars([]), { scale: 0, bars: [] });
  assert.deepEqual(V.moveBars(null), { scale: 0, bars: [] });
});

test('priceGeometry: the last year, change from the start, dots on report days', () => {
  const dates = Array.from({ length: 300 }, (_, i) => `d${i}`);
  const close = dates.map((_, i) => 100 + i);
  const g = V.priceGeometry(dates, close, [{ date: 'd299', move: 3 }, { date: 'd10', move: -2 }, { date: 'd290', move: null }]);
  assert.equal(g.points.length, 252);
  assert.equal(g.first, 'd48');
  assert.equal(g.high, 399);
  assert.equal(g.fromHigh, 0);
  assert.ok(Math.abs(g.ret - (399 / 148 - 1) * 100) < 1e-9);
  assert.deepEqual(g.marks.map((m) => m.date), ['d299']);
  assert.equal(g.marks[0].x, 100);
  assert.equal(g.marks[0].y, 0);
});

test('priceGeometry: too little or ragged data draws nothing', () => {
  assert.equal(V.priceGeometry(['a', 'b'], [1, 2]), null);
  assert.equal(V.priceGeometry(['a'], [1, 2]), null);
  assert.equal(V.priceGeometry(null, null), null);
});

test('sectorHue: known sectors fixed, unknown stable, none null', () => {
  assert.equal(V.sectorHue('Financials'), 48);
  assert.equal(V.sectorHue('Odd Sector'), V.sectorHue('Odd Sector'));
  assert.equal(V.sectorHue(null), null);
});
