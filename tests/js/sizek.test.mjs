import test from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/sizek-model.js';

test('the lead sentence states the share, the window and the longest runs in the build\'s figures', () => {
  const gap = { share_big_ahead: 56, window: '1Y', first: '2004-04-30', longest_big: 111, longest_small: 1 };
  assert.equal(M.leadText(gap, 'SPY', 'RSP'),
    'SPY beat RSP in 56% of the 1Y windows since 2004-04-30; the longest unbroken lead was 111 weeks, the longest lag 1 week.');
  assert.equal(M.leadText(null, 'SPY', 'RSP'), null);
  assert.equal(M.leadText({ share_big_ahead: null }, 'SPY', 'RSP'), null);
});

test('the extremes sentence gives the distance from the high and the low with their dates', () => {
  const t = M.extremesText({ high: 1.094, high_date: '2026-10-07', low: 0.757, low_date: '2015-04-06', from_high_pct: -1.0, from_low_pct: 43.1 });
  assert.match(t, /^-1\.0% from its high of 1\.09× \(2026-10-07\); \+43\.1% from its low of 0\.76× \(2015-04-06\)\.$/);
  assert.equal(M.extremesText(null), null);
});

test('calendar years run newest first, a part-year and the year to date say so, and only complete years are counted as won', () => {
  const years = [
    { year: 2003, big: 10, small: 12, gap: -2, partial_start: true, to_date: false },
    { year: 2004, big: 8, small: 6, gap: 2, partial_start: false, to_date: false },
    { year: 2005, big: 1, small: 5, gap: -4, partial_start: false, to_date: false },
    { year: 2006, big: 9, small: 3, gap: 6, partial_start: false, to_date: false },
    { year: 2007, big: 3, small: 1, gap: 2, partial_start: false, to_date: true },
  ];
  const rows = M.yearRows(years);
  assert.deepEqual(rows.map((r) => r.label), ['2007 (to date)', '2006', '2005', '2004', '2003 (part)']);
  assert.deepEqual(rows.map((r) => r.tone), ['up', 'up', 'down', 'up', 'down']);
  assert.deepEqual(M.yearsWon(years), { won: 2, of: 3 });                        // 2004 and 2006 of 2004-2006
  assert.equal(M.wonText(M.yearsWon(years)), '2 of 3');
  assert.equal(M.yearsWon([]), null);
  assert.equal(M.wonText(null), '—');
  assert.equal(M.yearRows([{ year: 2020, big: 1, small: null, gap: null }])[0].tone, 'dim');
});
