// K-SHAPE: the windowed series of the price legs, the P/E and the EPS growth.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { legSeries, peSeries, epsSeries } from '../../web/js/kshape-model.js';

const DATES = ['2020-12-31', '2021-06-30', '2025-10-10', '2026-01-02', '2026-07-13', '2026-09-14', '2026-10-12'];

test('the price ratio is rebased to 1 and each leg to 100 at the window\'s first close', () => {
  const price = { dates: DATES, ratio: [1, 2, 2, 4, 8, 6, 2], top: [10, 20, 20, 40, 80, 60, 20], bottom: [10, 10, 10, 10, 10, 10, 10] };
  const cut = legSeries(price, '1Y');
  assert.deepEqual(cut.dates, DATES.slice(2));
  assert.deepEqual(cut.series.ratio, [1, 2, 4, 3, 1]);
  assert.deepEqual(cut.series.top, [100, 200, 400, 300, 100]);
  assert.deepEqual(cut.series.bottom, [100, 100, 100, 100, 100]);
});

test('P/E medians and EPS growth are cut to the window and never rebased', () => {
  const pe = { dates: DATES, ratio: [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1], top: [10, 11, 12, 13, 14, 15, 16], bottom: [20, 20, 20, 20, 20, 20, 20] };
  const cut = peSeries(pe, '1Y');
  assert.deepEqual(cut.dates, DATES.slice(2));
  assert.deepEqual(cut.series.ratio, [0.7, 0.8, 0.9, 1.0, 1.1]);
  assert.deepEqual(cut.series.top, [12, 13, 14, 15, 16]);
  assert.deepEqual(cut.series.bottom, [20, 20, 20, 20, 20]);
  const eps = { dates: ['2025-03-31', '2025-06-30', '2025-09-30', '2025-12-31'], top: [5, -2, 8, 12], bottom: [1, 1, null, 3] };
  const grown = epsSeries(eps, '3M');   // from the last EPS date, the window starts on 2025-09-30
  assert.deepEqual(grown.dates, ['2025-09-30', '2025-12-31']);
  assert.deepEqual(grown.series.top, [8, 12]);
  assert.deepEqual(grown.series.bottom, [null, 3]);
});

test('a series that starts after the window\'s cut is shown from its own first date, not dropped', () => {
  const pe = { dates: DATES.slice(3), ratio: [1, 2, 3, 4], top: [1, 2, 3, 4], bottom: [4, 3, 2, 1] };
  const cut = peSeries(pe, '5Y');
  assert.deepEqual(cut.dates, DATES.slice(3));
  assert.deepEqual(cut.series.ratio, [1, 2, 3, 4]);
});

test('the K-SHAPE tab loads under node and exports its renderer', async () => {
  const mod = await import('../../web/js/tabs/kshape.js');
  assert.equal(typeof mod.default, 'function');
});
