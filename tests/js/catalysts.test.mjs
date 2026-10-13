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
