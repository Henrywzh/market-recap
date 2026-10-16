import test from 'node:test';
import assert from 'node:assert/strict';
import { partRows, rangeText, unusualRows } from '../../web/js/moves-card.js';

test('parts share one scale and keep their sign', () => {
  const rows = partRows({ market_pct: 0.5, sector_pct: -0.25, own_pct: -2, beta_market: 1.2, beta_sector: null });
  assert.deepEqual(rows.map((r) => [r.label, r.width, r.negative]), [['Market', 25, false], ['Sector', 13, true], ['Own', 100, true]]);
  assert.equal(rows[0].beta, 1.2);
  assert.equal(partRows({ market_pct: null, sector_pct: 0, own_pct: 0 })[0].width, 0);
});

test('range text uses the outer quantile pairs and needs both ends', () => {
  const range = { bands: [0.05, 0.16, 0.5, 0.84, 0.95].map((q, i) => ({ q, pct: [-6, -3, 0.1, 3.2, 7][i], price: [94, 97, 100, 103, 107][i] })) };
  assert.deepEqual(rangeText(range), { wide: '-6.0% to +7.0%', widePrices: '$94.00 – $107.00', narrow: '-3.0% to +3.2%' });
  assert.equal(rangeText({ bands: [{ q: 0.5, pct: 0, price: 1 }] }), null);
  assert.equal(rangeText(null), null);
});

test('unusual names are filtered by the own part and sorted by its size', () => {
  const data = { settings: { threshold_sigma: 2 }, rows: [
    { ticker: 'A', z_own: -2.5 }, { ticker: 'B', z_own: 3.1 }, { ticker: 'C', z_own: 1.9 }, { ticker: 'D', z_own: null }] };
  assert.deepEqual(unusualRows(data).map((r) => r.ticker), ['B', 'A']);
  assert.deepEqual(unusualRows(data, 'DOWN').map((r) => r.ticker), ['A']);
  assert.deepEqual(unusualRows(data, 'UP').map((r) => r.ticker), ['B']);
});
