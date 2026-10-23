import test from 'node:test';
import assert from 'node:assert/strict';
import {
  signedNum, signedBn, signedPct, ordinal, percentileText, zText,
  trendCheckLine, categoryRows, chartLines, CHART_CATEGORIES,
} from '../../web/js/flows-cot.js';

const MINUS = '−';

test('signed figures use a true minus sign and never print a missing value as zero', () => {
  assert.equal(signedNum(-408726, 0), `${MINUS}408,726`);
  assert.equal(signedNum(9220, 0), '+9,220');
  assert.equal(signedNum(0.004, 2), '0.00');
  for (const v of [null, undefined, NaN, Infinity]) {
    assert.equal(signedNum(v), '—');
    assert.equal(signedBn(v), '—');
    assert.equal(signedPct(v), '—');
  }
  assert.equal(signedBn(41.5), '+$41.50bn');
  assert.equal(signedBn(-235.08), `${MINUS}$235.08bn`);
  assert.equal(signedPct(-21.16), `${MINUS}21.2%`);
});

test('percentiles read as ordinals, teens included', () => {
  assert.equal(ordinal(1), '1st');
  assert.equal(ordinal(2), '2nd');
  assert.equal(ordinal(3), '3rd');
  assert.equal(ordinal(11), '11th');
  assert.equal(ordinal(12), '12th');
  assert.equal(ordinal(13), '13th');
  assert.equal(ordinal(21), '21st');
  assert.equal(ordinal(69.2), '69th');
  assert.equal(percentileText(91.4), '91st pct');
  assert.equal(percentileText(null), '—');
});

test('z is signed to two decimals', () => {
  assert.equal(zText(0.33), 'z +0.33');
  assert.equal(zText(-1.23), `z ${MINUS}1.23`);
  assert.equal(zText(undefined), '—');
});

test('the trend check puts asset managers first, leveraged money beside them, and is labelled a check', () => {
  const check = {
    window_weeks: 156, position_as_of: '2026-10-22',
    categories: [
      { key: 'asset_mgr', label: 'Asset managers', n: 156, corr_levels: 0.32, corr_changes_4w: 0.5 },
      { key: 'lev_money', label: 'Leveraged money', n: 156, corr_levels: -0.48, corr_changes_4w: null },
    ],
  };
  const line = trendCheckLine(check);
  assert.match(line, /156 weekly reports/);
  assert.match(line, /Asset managers: four-week changes \+0\.50, levels \+0\.32; Leveraged money: four-week changes —, levels −0\.48/);
  assert.match(line, /2026-10-22/);
  assert.match(line, /A check, not a validation\.$/);
  assert.equal(trendCheckLine({ unavailable: 'positioning panel not built this session' }),
    'Trend check not built this session: positioning panel not built this session.');
  assert.equal(trendCheckLine(undefined), 'Trend check not built this session.');
  assert.equal(trendCheckLine({ categories: [] }), 'Trend check not built this session.');
  assert.doesNotMatch(line, /NaN|undefined|\[object/);
});

const contract = {
  label: 'S&P 500 E-MINI',
  history: {
    dates: ['2026-09-01', '2026-09-08', '2026-09-15', '2026-09-22', '2026-09-29'],
    categories: {
      dealer: [-30, -31, -29, -28, -31],
      asset_mgr: [45, 46, 47, 48, 47],
      lev_money: [-20, -21, -19, -22, -21],
      other: [0.5, -0.2, 0.1, 0.6, -0.5],
      nonrept: [5, 5, 5, 5, 5],
    },
  },
  categories: [
    { key: 'dealer', label: 'Dealers', net: -602358, net_usd_bn: -235.08, net_pct_oi: -31.18, change_1w: -1517, pctile_3y: 69.2, z_3y: 0.33 },
    { key: 'asset_mgr', label: 'Asset managers', net: 915835, net_usd_bn: 357.43, net_pct_oi: 47.41, change_1w: 9220, pctile_3y: 69.2, z_3y: 0.66 },
    { key: 'lev_money', label: 'Leveraged money', net: -408726, net_usd_bn: null, net_pct_oi: -21.16, change_1w: null, pctile_3y: null, z_3y: null },
    { key: 'other', label: 'Other reportables', net: -11079, net_usd_bn: -4.32, net_pct_oi: -0.57, change_1w: -9387, pctile_3y: 26.3, z_3y: -0.6 },
    { key: 'nonrept', label: 'Non-reportables', net: 106328, net_usd_bn: 41.5, net_pct_oi: 5.5, change_1w: -4677, pctile_3y: 69.9, z_3y: 0.59 },
  ],
};

test('the table rows follow the category order and show missing values as dashes, not zeros', () => {
  const rows = categoryRows(contract);
  assert.deepEqual(rows.map((r) => r.key), ['dealer', 'asset_mgr', 'lev_money', 'other', 'nonrept']);
  const lev = rows.find((r) => r.key === 'lev_money');
  assert.equal(lev.usd, '—');
  assert.equal(lev.change, '—');
  assert.equal(lev.pctile, '—');
  assert.equal(lev.z, '—');
  assert.equal(rows[0].net, `${MINUS}602,358`);
  assert.equal(rows[1].usd, '+$357.43bn');
  for (const row of rows) for (const v of Object.values(row)) assert.doesNotMatch(String(v), /NaN|undefined|\[object/);
});

test('the chart plots the four named categories and slices them to the range', () => {
  assert.deepEqual(CHART_CATEGORIES, ['dealer', 'asset_mgr', 'lev_money', 'other']);
  const lines = chartLines(contract, contract.history.dates, 'MAX');
  assert.deepEqual(lines.map((l) => l.key), CHART_CATEGORIES);
  assert.equal(lines[2].label, 'Leveraged money');
  assert.deepEqual(lines[2].values, [-20, -21, -19, -22, -21]);
  assert.equal(lines[0].dates.length, 5);
});
