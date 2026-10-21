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

test('trailSummary says raised, cut or held, from what to what, and when', () => {
  const up = V.trailSummary(V.trailLevels(5.94, { '90d': 8.2, '60d': 0.1, '30d': 0.1, '7d': 0 }));
  assert.equal(up.verb, 'raised');
  near(up.from, 5.94 / 1.082);
  assert.equal(up.span, '90 days');
  assert.equal(up.when, '2-3 months ago');
  const down = V.trailSummary(V.trailLevels(2.9, { '90d': -5.6, '60d': -5.5, '30d': -0.2, '7d': 0 }));
  assert.equal(down.verb, 'cut');
  assert.equal(V.trailSummary(V.trailLevels(5, { '90d': 0.2, '30d': 0 })).verb, 'held');
  assert.equal(V.trailSummary([]), null);
});

test('trailSummary leaves out when for a change spread over the windows', () => {
  const spread = V.trailSummary(V.trailLevels(5.94, { '90d': 6, '60d': 4, '30d': 2, '7d': 1 }));
  assert.equal(spread.verb, 'raised');
  assert.equal(spread.when, null);
});

test('shortDate gives month and two-digit year, null for junk', () => {
  assert.deepEqual(V.shortDate('2026-07-14'), { month: 'Jul', year: "'26" });
  assert.equal(V.shortDate('nope'), null);
  assert.equal(V.shortDate(null), null);
});

test('surpriseRows runs oldest to newest, counts beats and rises, skips reports without both figures', () => {
  const r = V.surpriseRows([
    { date: '2026-07-14', surprise_pct: 9.8, move_pct: 2.5 },
    { date: '2026-04-14', surprise_pct: 8.2, move_pct: -0.8 },
    { date: '2026-01-13', surprise_pct: -3, move_pct: -4 },
    { date: '2025-10-14', surprise_pct: null, move_pct: 1 },
  ]);
  assert.equal(r.n, 3);
  assert.equal(r.beats, 2);
  assert.equal(r.roseOnBeat, 1);
  assert.deepEqual(r.rows.map((x) => x.date), ['2026-01-13', '2026-04-14', '2026-07-14']);
  assert.equal(V.surpriseRows(null).n, 0);
});

test('the report scale takes the actual in when it lands outside the analysts range', () => {
  const inside = V.scorecardScale(1.91, 2.10, 2.02, 2.00);
  assert.equal(inside.range, true);
  assert.equal(inside.actualOutside, false);
  const above = V.scorecardScale(1.91, 2.10, 2.02, 2.25);
  assert.equal(above.actualOutside, true);
  assert.ok(above.actualAt > above.boxLeft + above.boxWidth, 'the marker sits right of the box');
  assert.ok(above.actualAt <= 100 && above.consensusAt < above.actualAt);
  const below = V.scorecardScale(1.91, 2.10, 2.02, 1.5);
  assert.ok(below.actualAt < below.boxLeft && below.actualAt >= 0);
});

test('a report scale without a range still places the consensus and the actual; nothing gives none', () => {
  const bare = V.scorecardScale(null, null, 12.9e9, 13.28e9);
  assert.equal(bare.range, false);
  assert.equal(bare.boxWidth, 0);
  assert.ok(bare.consensusAt < bare.actualAt);
  assert.equal(bare.actualOutside, false);
  assert.equal(V.scorecardScale(2.10, 1.91, 2.02, 2.0).range, false, 'a range that runs backwards is no range');
  assert.equal(V.scorecardScale(null, null, null, null), null);
});

test('the move band is the implied ± around zero, the move on the same scale, flagged outside it', () => {
  const inside = V.moveBandGeometry(5, -4);
  assert.equal(inside.half, 5);
  assert.equal(inside.outside, false);
  assert.ok(inside.bandLeft < 50 && inside.bandLeft + inside.bandWidth > 50, 'the band straddles zero');
  assert.ok(inside.moveAt < 50 && inside.moveAt > inside.bandLeft, 'a -4 move is left of zero, inside the band');
  const outside = V.moveBandGeometry(5, 8);
  assert.equal(outside.outside, true);
  assert.ok(outside.moveAt <= 100 && outside.moveAt > outside.bandLeft + outside.bandWidth);
  assert.equal(V.moveBandGeometry(null, 3), null);
  assert.equal(V.moveBandGeometry(5, null), null);
});
