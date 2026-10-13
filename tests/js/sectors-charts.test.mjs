// SECTORS charts-first pages: the pure helpers behind their charts, on small fixtures.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/sectors-model.js';

const SUBS = [
  { key: 'XLK-S', label: 'Semiconductors', weight: 16.4, vs_index: { '1M': 1.4, '3M': -1.0, YTD: 54.0, '1Y': 65.2 }, pe_percentile: 60 },
  { key: 'XLK-SS', label: 'Systems Software', weight: 12.0, vs_index: { '1M': 3.0, '3M': 7.7, YTD: 40.7, '1Y': 51.2 }, pe_percentile: 80 },
  { key: 'XLK-THSP', label: 'Technology Hardware, Storage & Peripherals', weight: 4.0, vs_index: { '1M': -2.0, '3M': null, YTD: 10, '1Y': 5 }, pe_percentile: 20 },
  { key: 'XLK-EC', label: 'Electronic Components', weight: 1.0, vs_index: { '1M': 0.5, '3M': 2.0, YTD: 8, '1Y': 9 }, pe_percentile: null },
  { key: 'XLK-ICOS', label: 'IT Consulting & Other Services', weight: 0.5, vs_index: { '1M': 4.0, '3M': 1.0, YTD: 3, '1Y': 2 }, pe_percentile: 45 },
];

test('a short label keeps its first clause, without the words in brackets, and a long one gets an ellipsis', () => {
  assert.equal(M.shortName('Packaged Foods & Meats'), 'Packaged Foods & Meats');
  assert.equal(M.shortName('Diversified Banks, Inc'), 'Diversified Banks');
  assert.equal(M.shortName('Oil & Gas (Integrated)'), 'Oil & Gas');
  assert.equal(M.shortName('Soft Drinks & Non-alcoholic Beverages'), 'Soft Drinks & Non-alc…');
  assert.equal(M.shortName('Soft Drinks & Non-alcoholic Beverages').length, 22);
  assert.equal(M.shortName(null), '');
});

test('a sector name has a short form for the charts, and an unknown one is kept as it is', () => {
  assert.equal(M.sectorShort('Information Technology'), 'Info Tech');
  assert.equal(M.sectorShort('Energy'), 'Energy');
});

test('the sub-industry bars are the period\'s excess return, largest first, with a missing figure left off', () => {
  const rows = M.subBars(SUBS, '3M');
  assert.deepEqual(rows.map((r) => r.key), ['XLK-SS', 'XLK-EC', 'XLK-ICOS', 'XLK-S']);
  assert.deepEqual(rows.map((r) => r.value), [7.7, 2, 1, -1]);
  assert.equal(rows[0].full, 'Systems Software');
  assert.equal(rows[0].label, 'Systems Software');
  assert.equal(M.subBars(SUBS, '5Y').length, 0);
  assert.deepEqual(M.subBars(undefined, '3M'), []);
});

test('the map plots a sub-industry only where it has both a return and a P/E percentile', () => {
  const { points, off } = M.subMapPoints(SUBS, '3M');
  assert.deepEqual(points.map((p) => p.key), ['XLK-S', 'XLK-SS', 'XLK-ICOS']);
  // Technology Hardware has no 3M return and Electronic Components no P/E percentile.
  assert.deepEqual(off, ['Technology Hardware', 'Electronic Components']);
  const semis = points[0];
  assert.equal(semis.x, -1);
  assert.equal(semis.y, 60);
  assert.equal(semis.full, 'Semiconductors');
});

test('the map\'s bubbles grow with the square root of weight, so area follows weight, the heaviest at the top size', () => {
  const sized = M.withSizes([{ weight: 16 }, { weight: 4 }], 8, 36);
  assert.equal(sized[0].size, 36);
  assert.equal(sized[1].size, 18);
  // A light sub-industry never shrinks below the smallest bubble.
  const { points } = M.subMapPoints(SUBS, '1M');
  assert.ok(points.find((p) => p.key === 'XLK-ICOS').size >= 8);
  assert.equal(points.find((p) => p.key === 'XLK-S').size, 36);
});

test('a point with no weight is drawn at the smallest size, and sizes never shrink below it', () => {
  const sized = M.withSizes([{ weight: 9 }, { weight: 0 }, { weight: null }, { weight: 1 }], 8, 36);
  assert.equal(sized[0].size, 36);
  assert.equal(sized[1].size, 8);
  assert.equal(sized[2].size, 8);
  assert.equal(sized[3].size, 12);
  assert.deepEqual(M.withSizes([]), []);
});

const MEMBERS = [
  { ticker: 'AAPL', name: 'Apple', weight: 7, returns: { '3M': 12 }, revision_90d: 3 },
  { ticker: 'MSFT', name: 'Microsoft', weight: 6, returns: { '3M': 4 }, revision_90d: -1 },
  { ticker: 'NVDA', name: 'NVIDIA', weight: 5, returns: { '3M': null }, revision_90d: 8 },
  { ticker: 'AVGO', name: 'Broadcom', weight: 2, returns: { '3M': 9 }, revision_90d: null },
  { ticker: 'AMD', name: 'AMD', weight: 0.5, returns: { '3M': 2 }, revision_90d: 1 },
];

test('the names chart is the name\'s return less the index\'s, against its 90-day revision, and labels the heaviest', () => {
  const { points, off } = M.nameMapPoints(MEMBERS, '3M', 3, 2);
  assert.deepEqual(points.map((p) => p.ticker), ['AAPL', 'MSFT', 'AMD']);
  assert.deepEqual(points.map((p) => p.x), [9, 1, -1]);
  assert.deepEqual(points.map((p) => p.y), [3, -1, 1]);
  assert.deepEqual(points.map((p) => p.named), [true, true, false]);
  assert.deepEqual(off, ['NVDA', 'AVGO']);
});

test('the names chart draws nothing against a missing index return', () => {
  const { points, off } = M.nameMapPoints(MEMBERS, '3M', null);
  assert.deepEqual(points, []);
  assert.equal(off.length, MEMBERS.length);
});

test('a symmetric axis holds every value with a tenth to spare, in round steps, and a unit axis when empty', () => {
  assert.deepEqual(M.symmetricRange([]), [-1, 1]);
  assert.deepEqual(M.symmetricRange([3.2, -4]), [-4.5, 4.5]);
  assert.deepEqual(M.symmetricRange([33, -12]), [-40, 40]);
  assert.deepEqual(M.symmetricRange([null, undefined, 2]), [-2.5, 2.5]);
  assert.deepEqual(M.symmetricRange([100, -40]), [-150, 150]);
});

test('the P/E band is the ten-year median and the middle half, with the current reading', () => {
  const band = M.bandOf({ median: 26.1, p25: 23.4, p75: 29.9, p10: 20, p90: 33, current: 27.3, percentile: 62.5, weeks: 520 });
  assert.deepEqual(band, { median: 26.1, p25: 23.4, p75: 29.9, current: 27.3, percentile: 62.5, weeks: 520 });
});

test('a band with no stats, or without its median and quartiles, is null; a missing reading stays null', () => {
  assert.equal(M.bandOf(null), null);
  assert.equal(M.bandOf({ median: 20, p25: null, p75: 25 }), null);
  const partial = M.bandOf({ median: 20, p25: 18, p75: 25, current: null, percentile: undefined });
  assert.equal(partial.current, null);
  assert.equal(partial.percentile, null);
  assert.equal(partial.weeks, null);
});

test('the valuation path comes out in build order, with the NTM stage marked and a missing growth left null', () => {
  const bars = M.pathBars({
    stages: [
      { key: 'ntm', pe: 19.4, growth: 11.8 },
      { key: 'fy_prev', pe: 28.5, growth: null },
      { key: 'fy0', pe: 21.7, growth: 31.2 },
    ],
    companies: 484,
  });
  assert.deepEqual(bars.map((b) => b.key), ['fy_prev', 'fy0', 'ntm', 'fy1']);
  assert.deepEqual(bars.map((b) => b.label), ['LAST FY', 'THIS FY', 'NEXT 12M', 'NEXT FY']);
  assert.deepEqual(bars.map((b) => b.ntm), [false, false, true, false]);
  assert.deepEqual(bars.map((b) => b.pe), [28.5, 21.7, 19.4, null]);
  assert.deepEqual(bars.map((b) => b.growth), [null, 31.2, 11.8, null]);
});

test('no valuation path gives no bars, so the page can say there is none', () => {
  assert.deepEqual(M.pathBars(null), []);
  assert.deepEqual(M.pathBars({ stages: [] }), []);
  assert.deepEqual(M.pathBars({}), []);
});

test('the longest of the date lists is the one the window switch reads', () => {
  assert.deepEqual(M.longestDates(['2025-01-01'], ['2024-01-01', '2024-06-01']), ['2024-01-01', '2024-06-01']);
  assert.deepEqual(M.longestDates(undefined, null, ['2026-01-01']), ['2026-01-01']);
  assert.deepEqual(M.longestDates(undefined, 'not a list'), []);
});

test('the chart periods and default window are the ones the page offers', () => {
  assert.deepEqual(M.CHART_PERIODS, ['1M', '3M', 'YTD', '1Y']);
  assert.equal(M.DEFAULT_CHART_PERIOD, '3M');
  assert.equal(M.DEFAULT_WINDOW, '1Y');
  assert.equal(M.NAMED_LIMIT, 8);
});
