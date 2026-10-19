// CATALYSTS: the earnings-weight grid's shape, read from the build's catalysts.json.
import test from 'node:test';
import assert from 'node:assert/strict';
import { heatmapModel } from '../../web/js/tabs/catalysts.js';

test('a build with no grid gives no model, so the card is left out', () => {
  assert.equal(heatmapModel(undefined), null);
  assert.equal(heatmapModel(null), null);
  assert.equal(heatmapModel({ dates: [], rows: [] }), null);
  assert.equal(heatmapModel({ dates: ['2026-10-14'] }), null);
});

test('the shading is scaled to the largest cell, and a grid with no weight scales to a floor', () => {
  const grid = {
    dates: ['2026-10-14', '2026-10-15'],
    day_totals: [3, null],
    rows: [
      { sector: 'Financials', total: 3, cells: [{ w: 2, n: 5, top: ['JPM'] }, null] },
      { sector: 'Energy', total: 0.5, cells: [{ w: 0.5, n: 1, top: ['XOM'] }, null] },
    ],
  };
  const model = heatmapModel(grid);
  assert.equal(model.max, 2);
  assert.equal(model.dates.length, 2);
  assert.equal(heatmapModel({ dates: ['2026-10-14'], rows: [{ sector: 'X', cells: [null] }] }).max, 0.01);
});

test('an event is filtered by what it is and by what it hits', async () => {
  const { matchesTags } = await import('../../web/js/tabs/catalysts.js');
  const cpi = { category: 'macro_data', channels: ['treasuries', 'equities', 'macro'] };
  assert.equal(matchesTags(cpi, { category: 'all', channel: 'all' }), true);
  assert.equal(matchesTags(cpi, { category: 'macro_data', channel: 'treasuries' }), true);
  assert.equal(matchesTags(cpi, { category: 'market_structure', channel: 'all' }), false);
  assert.equal(matchesTags(cpi, { category: 'all', channel: 'credit' }), false);
  assert.equal(matchesTags({}, {}), true, 'an older build with no tags is never hidden by default');
});

test('the importance title says how it was set', async () => {
  const { importanceTitle } = await import('../../web/js/tabs/catalysts.js');
  const cpi = { importance: 'high', importance_basis: { kind: 'measured', text: '2-year yield moved 1.54x an ordinary day' } };
  assert.equal(importanceTitle(cpi), 'high importance · 2-year yield moved 1.54x an ordinary day');
  assert.equal(importanceTitle({ importance: 'low' }), 'low importance');
});

test('a release says what it has done, and names undetectable effects instead of a number', async () => {
  const { responseLines } = await import('../../web/js/tabs/catalysts.js');
  const cpi = {
    measure: 'cpi', scale: 0.148, unit: 'pp', since: '2016-01-20', regime: 'rates',
    size: { n: 121, dy2_release: 5.35, dy2_other: 3.47, spy_release: 0.86, spy_other: 0.82 },
    per_sd: { dy2_bp: { slope: 3.88, t: 5.04, n: 121, detected: true },
              spy_pct: { slope: -0.326, t: -2.76, n: 121, detected: true },
              spy_pct_rates_driven: { slope: -0.577, t: -3.0, n: 42, detected: true } },
  };
  const lines = responseLines(cpi);
  assert.match(lines[0], /moves 5\.4bp on average \(3\.5bp on other days\) · SPY 1\.05× .* 121 releases since 2016/);
  assert.equal(lines[1], 'A surprise 1 SD above the forecast (0.15pp): 2-year yield +3.9bp · SPY −0.33%');
  assert.match(lines[2], /Rates are driving stocks now; in such markets SPY has moved −0\.58% per SD \(t -3\.0, 42 releases\)/);
  const payrolls = { ...cpi, unit: 'k', scale: 83, regime: 'growth',
    per_sd: { dy2_bp: { slope: 2.05, t: 3.8, detected: true }, spy_pct: { slope: 0.067, t: 0.86, detected: false } } };
  assert.match(responseLines(payrolls)[1], /\(83k\): 2-year yield \+2\.1bp · SPY not detectable \(t 0\.9\)/);
  assert.match(responseLines(payrolls)[2], /^Growth is driving stocks now/);
  assert.deepEqual(responseLines(null), []);
});

test('an earnings row shows its past and implied moves when EVIDENCE has them', async () => {
  const { earningsMove } = await import('../../web/js/tabs/catalysts.js');
  const aapl = { mean_abs_move: 2.46, options: { implied_move: { straddle_pct: 5.67, expiry: '2026-11-06' } } };
  const move = earningsMove(aapl);
  assert.equal(move.past, 2.46);
  assert.equal(move.implied, 5.67);
  assert.equal(move.tone, 'down', 'options price well above its past moves');
  assert.equal(earningsMove({ mean_abs_move: 3.1 }).implied, null);
  assert.equal(earningsMove({}), null);
  assert.equal(earningsMove(undefined), null);
});
