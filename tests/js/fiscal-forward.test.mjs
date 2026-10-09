// Yahoo's fiscal-year forward P/E history: what the chart and the table are drawn from.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as FF from '../../web/js/fiscal-forward.js';

const point = (date, pe, horizon, rolled = false, series = 'monthly') => ({ date, pe, horizon, rolled, series });
const goldman = {
  year_end_month: 12,
  points: [
    point('2025-08-31', 17.09, 4), point('2025-09-30', 15.22, 15, true), point('2025-12-31', 15.85, 12),
    point('2026-06-30', 17.18, 6), point('2026-08-31', 15.87, 4),
  ],
  annual: [{ date: '2024-12-31', pe: 13.89 }, { date: '2025-12-31', pe: 15.85 }],
  latest: point('2026-08-31', 15.87, 4),
  year_ago: { date: '2025-08-31', pe: 17.09, change_pct: -7.1 },
  missing_months: ['2026-07'],
  unread: [],
};

test('the chart gets one date axis, the line and the year-end markers on it', () => {
  const data = FF.chartData(goldman);
  assert.deepEqual(data.dates, ['2024-12-31', '2025-08-31', '2025-09-30', '2025-12-31', '2026-06-30', '2026-08-31']);
  assert.deepEqual(data.line, [null, 17.09, 15.22, 15.85, 17.18, 15.87]);   // no line point at a year end Yahoo's monthly series lacks
  assert.deepEqual(data.annual, [13.89, null, null, 15.85, null, null]);
  assert.deepEqual(data.rolled, ['2025-09-30']);
  assert.equal(data.horizon['2025-09-30'], 15);
  // The time axis gets real dates, so four-year-old year ends are not drawn beside last month's point.
  assert.deepEqual(data.annualPairs, [['2024-12-31', 13.89], ['2025-12-31', 15.85]]);
  assert.equal(data.linePairs.length, 5);
});

test('the tooltip says how far ahead the EPS is, and flags the roll and the year ends', () => {
  const data = FF.chartData(goldman);
  assert.match(FF.tooltipText('2025-09-30', data), /15\.2x · EPS 15 months ahead/);
  assert.match(FF.tooltipText('2025-09-30', data), /moved to the next fiscal year/);
  assert.match(FF.tooltipText('2025-12-31', data), /fiscal year end: 15\.9x, 12 months ahead/);
  assert.equal(FF.tooltipText('1999-01-01', data), '');
});

test('the table names the horizon, compares the same month, lists year ends, and names the gap', () => {
  const rows = Object.fromEntries(FF.tableRows(goldman));
  assert.equal(rows['Forward P/E, Yahoo (fiscal-year EPS)'], '15.9x · 4 months ahead · 2026-08-31');
  assert.equal(rows['Same month a year earlier'], '17.1x (2025-08-31) · -7% at the same horizon');
  assert.equal(rows['At fiscal year ends (12 months ahead)'], 'Dec 2024 13.9x · Dec 2025 15.9x');
  assert.equal(rows['No Yahoo point for'], '2026-07');
});

test('the long rows wrap so one of them cannot widen the whole table', () => {
  const rows = FF.tableRows(goldman);
  assert.ok(rows.every(([, , wrap]) => wrap === true));
});

test('what is not there is a dash, not a zero', () => {
  const bare = { points: [], annual: [], latest: null, year_ago: null, missing_months: [], unread: ['annual'] };
  const rows = Object.fromEntries(FF.tableRows(bare));
  assert.equal(rows['Forward P/E, Yahoo (fiscal-year EPS)'], '—');
  assert.equal(rows['Same month a year earlier'], '—');
  assert.equal(rows['At fiscal year ends (12 months ahead)'], '—');
  assert.equal(rows['Not read from Yahoo'], 'annual');
  const noHorizon = FF.tableRows({ ...goldman, latest: point('2026-08-31', 15.87, null) })[0][1];
  assert.match(noHorizon, /horizon unknown/);
});

test('the axis stops short of a spike but not when nothing sticks out', () => {
  const calm = [14, 15, 16, 15, 14, 17, 16, 15, 14, 16, 17, 15, 16];       // a year of month ends
  assert.equal(FF.axisCap(calm), null);
  const cap = FF.axisCap([...calm, 3333]);                                // Boeing's near-zero EPS
  assert.ok(cap > 30 && cap < 60, `cap ${cap}`);
});

test('several extreme points in a row do not set the cap themselves', () => {
  // Boeing: ordinary multiples of 34-60, then 833x, 909x and 3,333x within a year.
  const boeing = [34, 60, 59, 61, 58, 60, 62, 59, 60, 833, 909, 3333, 61, 60];
  const cap = FF.axisCap(boeing);
  assert.ok(cap >= 100 && cap < 250, `cap ${cap}`);
});

test('too few points to say what a spike is: no cap, the true range is drawn', () => {
  assert.equal(FF.axisCap([14, 15, 16, 3333]), null);
  assert.equal(FF.axisCap([10, 12], 1.6), null);
  assert.equal(FF.axisCap([null, undefined, 14, 15, 16, 15, 14]), null);
});

test('the quantile interpolates, as the history charts do', () => {
  assert.equal(FF.quantile([1, 2, 3, 4], 0.5), 2.5);
  assert.equal(FF.quantile([5], 0.9), 5);
  assert.equal(FF.quantile([], 0.5), null);
});
