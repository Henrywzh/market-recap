import test from 'node:test';
import assert from 'node:assert/strict';
import { windowCut, baseIndex, availableWindows, pickWindow, sliceWindow, alignTo } from '../../web/js/windows.js';
import { joinArms, decompose } from '../../web/js/basket-view.js';

const DATES = ['2020-12-31', '2021-06-30', '2025-10-10', '2026-01-02', '2026-07-13', '2026-09-14', '2026-10-12'];

test('a window starts at the last date on or before its cut', () => {
  assert.equal(windowCut('2026-10-12', '1M'), '2026-09-12');
  assert.equal(windowCut('2026-10-12', 'YTD'), '2025-12-31');
  assert.equal(windowCut('2026-10-12', 'MAX'), null);
  assert.equal(DATES[baseIndex(DATES, '1M')], '2026-07-13');
  assert.equal(DATES[baseIndex(DATES, '1Y')], '2025-10-10');
  assert.equal(DATES[baseIndex(DATES, 'YTD')], '2025-10-10');
  assert.equal(baseIndex(DATES, '10Y'), -1);
});

test('only the windows a series covers are offered', () => {
  assert.deepEqual(availableWindows(DATES), ['1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', 'MAX']);
  assert.equal(pickWindow(DATES, '10Y'), '5Y');
  assert.equal(pickWindow(DATES, '1Y'), '1Y');
});

test('levels are rebased at the window start, readings are not', () => {
  const out = sliceWindow(DATES, { level: [1, 2, 4, 5, 8, 6, 10], pe: [9, 9, 9, 9, 9, 9, 20] }, '1Y', { level: 'index' });
  assert.deepEqual(out.dates, DATES.slice(2));
  assert.deepEqual(out.series.level, [100, 125, 200, 150, 250]);
  assert.deepEqual(out.series.pe, [9, 9, 9, 9, 20]);
  const ratio = sliceWindow(DATES, { r: [null, 2, null, 4, 8, 6, 2] }, '1Y', { r: 'ratio' });
  assert.deepEqual(ratio.series.r, [null, 1, 2, 1.5, 0.5]);
  assert.deepEqual(alignTo(['a', 'b', 'c'], ['c', 'a'], [3, 1]), [1, null, 3]);
});

test('a ratio of two baskets splits into multiple and earnings', () => {
  const basket = (price, pe) => ({ dates: DATES, price, pe, earnings: price.map((p, i) => p / pe[i]) });
  const fundamentals = { arms: [
    { label: 'A', basket: basket([100, 110, 120, 130, 140, 150, 160], [20, 20, 22, 24, 24, 24, 25]) },
    { label: 'B', basket: basket([100, 100, 100, 100, 100, 100, 100], [10, 10, 10, 10, 10, 10, 10]) },
  ] };
  const joined = joinArms(fundamentals);
  const parts = decompose(joined, 'MAX');
  assert.ok(Math.abs((1 + parts.price / 100) - (1 + parts.multiple / 100) * (1 + parts.earnings / 100)) < 1e-9);
  assert.ok(Math.abs(parts.price - 60) < 1e-9);
  assert.ok(Math.abs(parts.multiple - 25) < 1e-9);
});

test('the split is withheld where today\'s names do not track the real ratio', async () => {
  const { tracking, trackedWindows, TRACKING_PP } = await import('../../web/js/basket-view.js');
  const joined = { dates: DATES, priceRatio: [1, 1, 1, 1, 1.02, 1.03, 1.03] };
  const reference = { dates: DATES, ratio: [2, 1.5, 1, 1, 1.02, 1.03, 1.02] };
  assert.equal(tracking(joined, reference, '3M').ok, true);
  const long = tracking(joined, reference, 'YTD');
  assert.ok(long.ok && Math.abs(long.gap) <= TRACKING_PP);
  assert.equal(tracking(joined, reference, '5Y').ok, false);
  assert.ok(!trackedWindows(joined, reference).includes('5Y'));
});

test('the attribution bars add up to the ratio\'s change', async () => {
  const { joinArms, attributionRow, attributionRows, premiumView } = await import('../../web/js/basket-view.js');
  const basket = (price, pe) => ({ dates: DATES, price, pe, earnings: price.map((p, i) => p / pe[i]) });
  const joined = joinArms({ arms: [
    { label: 'A', basket: basket([100, 110, 120, 130, 140, 150, 160], [20, 20, 22, 24, 24, 24, 25]) },
    { label: 'B', basket: basket([100, 100, 100, 100, 100, 100, 100], [10, 10, 10, 10, 10, 10, 10]) },
  ] });
  const row = attributionRow(joined, null, 'MAX');
  assert.ok(Math.abs(row.multiple + row.earnings - row.total) < 1e-9);
  assert.ok(Math.abs(row.total - 60) < 1e-9);
  // Multiple +25% and earnings +28% of a +60% move: log shares 0.223 and 0.247 of 0.470.
  assert.ok(Math.abs(row.multiple - (60 * Math.log(1.25)) / Math.log(1.6)) < 1e-9);
  assert.ok(attributionRows(joined, null).every((r) => r.ok));
  const view = premiumView(joined, null);
  assert.equal(view.now, 150);
});
