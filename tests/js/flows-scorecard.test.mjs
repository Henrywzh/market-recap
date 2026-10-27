// The FLOWS scorecard rows, their order, freshness and direction, built from a
// trimmed copy of the real artifacts/flows.json (as of 2026-10-22). The module is
// pure, so these run under node with no DOM.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  scorecardRows, sortRows, holderBars, percentileOf, directionOf, daysBetween, isStale,
  bnText, signedPct, levelPctText, ordinalText, recentValues,
} from '../../web/js/flows-scorecard.js';

const MINUS = '−';

// Trimmed from artifacts/flows.json: the US equity ETF aggregate, the ES leveraged-money
// category, the Z.1 latest quarter with the last twelve quarters of four holder groups,
// the SPX buyback quarters and the Form PF net equity exposure.
const real = {
  as_of: '2026-10-22',
  etf: {
    aggregates: [{
      name: 'US equity',
      latest_date: '2026-10-22',
      latest: { flow_1w: -11211791890, flow_1m: 24420681923, pct_rank_1w: 7 },
      rolling_20: [50332707383, 26321905035, 6061127289],
    }],
  },
  cot: {
    report_date: '2026-10-13',
    contracts: [{
      key: 'es',
      categories: [{ key: 'lev_money', label: 'Leveraged money', net_pct_oi: -21.16, change_1w: 6361, pctile_3y: 14.1, net_usd_bn: -159.51 }],
      history: { categories: { lev_money: [-14.99, -15.59, -13.23, -13.58, -15.41, -15.51, -16.46, -11.98, -19.86, -19.65, -21.48, -21.16] } },
    }],
  },
  z1: {
    latest_quarter: '2026Q2',
    latest_quarter_end: '2026-06-30',
    latest: [
      { key: 'households', label: 'Households (residual sector)', q_bn: 350.49, pctile_4q: 100 },
      { key: 'mutual_funds', label: 'Mutual funds', q_bn: -222.96, pctile_4q: 0.7 },
      { key: 'etfs', label: 'ETFs', q_bn: 393.13, pctile_4q: 100 },
      { key: 'pensions', label: 'Pension funds', q_bn: -37.11, pctile_4q: 58.2 },
      { key: 'insurers', label: 'Insurers', q_bn: -77.62, pctile_4q: 3.4 },
      { key: 'rest_of_world', label: 'Rest of world', q_bn: 410.24, pctile_4q: 100 },
      { key: 'broker_dealers', label: 'Broker-dealers', q_bn: -33.29, pctile_4q: 4.8 },
      { key: 'other', label: 'Other', q_bn: -52.32, pctile_4q: 18.5 },
      { key: 'total', label: 'Total, all sectors', q_bn: 730.55, pctile_4q: 100 },
    ],
    history: {
      groups: {
        households: [222.14, 138.5, 377.72, 389.12, 295.86, 342.17, 197.33, -56.4, 419.64, 263.46, 490.02, 350.49],
        mutual_funds: [-73.97, -125.9, -123.04, -103.57, -141.4, -146.61, -191.74, -139.0, -521.52, -221.56, -197.55, -222.96],
        pensions: [-79.07, -77.7, -124.46, -136.2, -143.52, -117.13, 36.24, -25.71, 164.31, -84.75, -91.04, -37.11],
        rest_of_world: [-47.92, -65.0, -57.68, -30.27, 164.33, 102.32, -18.14, 316.42, 151.56, 196.84, -21.74, 410.24],
      },
    },
  },
  demand_pipeline: {
    buybacks: {
      indices: {
        SPX: {
          history: {
            quarterly: [
              { period: '2024Q1', date: '2024-03-31', covered_sum_bn: 217.781, coverage_pct: 74.0, period_ended: true },
              { period: '2024Q2', date: '2024-06-30', covered_sum_bn: 210.628, coverage_pct: 73.6, period_ended: true },
              { period: '2024Q3', date: '2024-09-30', covered_sum_bn: 213.378, coverage_pct: 76.2, period_ended: true },
              { period: '2024Q4', date: '2024-12-31', covered_sum_bn: 220.664, coverage_pct: 75.6, period_ended: true },
              { period: '2025Q1', date: '2025-03-31', covered_sum_bn: 252.314, coverage_pct: 76.2, period_ended: true },
              { period: '2025Q2', date: '2025-06-30', covered_sum_bn: 229.236, coverage_pct: 77.2, period_ended: true },
              { period: '2025Q3', date: '2025-09-30', covered_sum_bn: 220.75, coverage_pct: 74.4, period_ended: true },
              { period: '2025Q4', date: '2025-12-31', covered_sum_bn: 231.706, coverage_pct: 72.4, period_ended: true },
              { period: '2026Q1', date: '2026-03-31', covered_sum_bn: 258.59, coverage_pct: 72.0, period_ended: true },
              { period: '2026Q2', date: '2026-06-30', covered_sum_bn: 280.728, coverage_pct: 74.0, period_ended: true },
              // Partial coverage: left out of the history and of the latest reading.
              { period: '2026Q3', date: '2026-09-30', covered_sum_bn: 82.152, coverage_pct: 24.8, period_ended: true },
              { period: '2026Q4', date: '2026-12-31', covered_sum_bn: 1.088, coverage_pct: 0.4, period_ended: false },
            ],
          },
        },
      },
    },
  },
  hf_leverage: {
    latest: [{ id: 'equity_net_pct_nav', value: 37.6, q_change: -1.0, percentile: 46, period: '2026-06-30' }],
    series: [{ id: 'equity_net_pct_nav', values: [36.0, 38.3, 39.9, 39.6, 41.2, 42.2, 40.8, 41.6, 42.2, 43.7, 38.6, 37.6] }],
  },
};

const rowsFor = (inputs = real) => scorecardRows({
  asOf: inputs.as_of,
  etf: inputs.etf,
  cot: inputs.cot,
  z1: inputs.z1,
  buybacks: inputs.demand_pipeline?.buybacks,
  hfLeverage: inputs.hf_leverage,
});

test('signed billions and percentages carry a true minus and no sign on an exposure level', () => {
  assert.equal(bnText(350.49), '+$350.5bn');
  assert.equal(bnText(-11.21), `${MINUS}$11.2bn`);
  assert.equal(bnText(1163.6), '+$1,163.6bn');
  assert.equal(bnText(-0.31), `${MINUS}$310m`);
  assert.equal(bnText(null), '—');
  assert.equal(signedPct(-21.16), `${MINUS}21.2%`);
  assert.equal(levelPctText(37.6), '37.6%');
  assert.equal(levelPctText(undefined), '—');
});

test('ordinals take the right suffix, teens included', () => {
  assert.equal(ordinalText(1), '1st');
  assert.equal(ordinalText(2), '2nd');
  assert.equal(ordinalText(3), '3rd');
  assert.equal(ordinalText(7), '7th');
  assert.equal(ordinalText(12), '12th');
  assert.equal(ordinalText(21), '21st');
  assert.equal(ordinalText(null), '—');
});

test('direction is buy above zero, sell below, flat at zero, and no reading gives null', () => {
  assert.equal(directionOf(1), 'buy');
  assert.equal(directionOf(-0.5), 'sell');
  assert.equal(directionOf(0), 'flat');
  assert.equal(directionOf(null), null);
  assert.equal(directionOf(undefined), null);
});

test('percentile ranks the latest within its own history, ties counted half, nothing under eight points', () => {
  // 12 points, 7 below 350.49, itself one: (7 + 0.5) / 12 = 62.5, rounded to 63.
  assert.equal(percentileOf(350.49, [222.14, 138.5, 377.72, 389.12, 295.86, 342.17, 197.33, -56.4, 419.64, 263.46, 490.02, 350.49]), 63);
  assert.equal(percentileOf(5, [1, 2, 3]), null);
  assert.equal(percentileOf(null, [1, 2, 3, 4, 5, 6, 7, 8]), null);
});

test('day gaps read as UTC calendar days and a missing date gives null', () => {
  assert.equal(daysBetween('2026-10-22', '2026-10-22'), 0);
  assert.equal(daysBetween('2026-10-22', '2026-06-30'), 114);
  assert.equal(daysBetween('2026-10-22', 'not a date'), null);
  assert.equal(daysBetween(null, '2026-10-22'), null);
});

test('stale is past the frequency threshold only, and an unknown frequency is never stale', () => {
  assert.equal(isStale('daily', 3), false);
  assert.equal(isStale('daily', 4), true);
  assert.equal(isStale('weekly', 10), false);
  assert.equal(isStale('weekly', 11), true);
  assert.equal(isStale('quarterly', 140), false);
  assert.equal(isStale('quarterly', 141), true);
  assert.equal(isStale('calendar', 999), false);
  assert.equal(isStale('daily', null), false);
});

test('recent values keep their gaps and a series with no number gives null', () => {
  assert.deepEqual(recentValues([1, null, 3, 4], 2), [3, 4]);
  assert.equal(recentValues([null, undefined], 5), null);
  assert.equal(recentValues(undefined, 5), null);
});

test('the real build gives one row per participant, fastest frequency first, then furthest from its median', () => {
  const rows = rowsFor();
  assert.deepEqual(rows.map((r) => r.key), [
    'etf_us_equity',
    'futures_lev_money_es',
    'z1_rest_of_world',
    'companies_spx_buybacks',
    'z1_mutual_funds',
    'z1_pensions',
    'z1_households',
    'hedge_net_equity_form_pf',
  ]);
  assert.deepEqual(rows.map((r) => r.frequency), ['daily', 'weekly', 'quarterly', 'quarterly', 'quarterly', 'quarterly', 'quarterly', 'quarterly']);
});

test('ETF row: the US equity week in dollars, a sell, its rank, and its own as-of date', () => {
  const [etf] = rowsFor();
  assert.equal(etf.label, 'ETF flows (US equity)');
  assert.equal(etf.text, `${MINUS}$11.2bn 1W`);
  assert.equal(etf.unit, '$bn');
  assert.ok(Math.abs(etf.latest - -11.2117918) < 1e-6);
  assert.equal(etf.direction, 'sell');
  assert.equal(etf.percentile, 7);
  assert.equal(etf.asOf, '2026-10-22');
  assert.equal(etf.lagDays, 0);
  assert.equal(etf.stale, false);
  assert.equal(etf.section, 'etf');
});

test('ES row: leveraged money as % of open interest; direction is the week\'s change in contracts', () => {
  const es = rowsFor().find((r) => r.key === 'futures_lev_money_es');
  assert.equal(es.text, `${MINUS}21.2% OI`);
  assert.equal(es.direction, 'buy'); // +6,361 contracts this week
  assert.equal(es.percentile, 14.1);
  assert.equal(es.asOf, '2026-10-13');
  assert.equal(es.lagDays, 9);
  assert.equal(es.stale, false); // weekly: 9 days is inside 10
  assert.equal(es.section, 'futures');
});

test('Z.1 rows: quarterly, percentile of the quarter within its own history, section is the investor demand view', () => {
  const rows = rowsFor();
  const households = rows.find((r) => r.key === 'z1_households');
  assert.equal(households.text, '+$350.5bn · 2026Q2');
  assert.equal(households.direction, 'buy');
  assert.equal(households.percentile, 63);
  assert.equal(households.asOf, '2026-06-30');
  assert.equal(households.lagDays, 114);
  assert.equal(households.stale, false);
  assert.equal(households.section, 'demand');

  const mutual = rows.find((r) => r.key === 'z1_mutual_funds');
  assert.equal(mutual.direction, 'sell');
  assert.equal(mutual.percentile, 13);
  assert.equal(rows.find((r) => r.key === 'z1_rest_of_world').label, 'Foreign investors');
});

test('buyback row: the last completed quarter with enough issuer coverage, not the partial one after it', () => {
  const bb = rowsFor().find((r) => r.key === 'companies_spx_buybacks');
  assert.equal(bb.text, '+$280.7bn · 2026Q2');
  assert.equal(bb.latest, 280.728);
  assert.equal(bb.asOf, '2026-06-30');
  assert.equal(bb.direction, 'buy');
  assert.equal(bb.percentile, 95); // (9 below + 0.5) / 10
  assert.equal(bb.section, 'buybacks');
});

test('Form PF row: the exposure level is unsigned, its direction is the quarter\'s change', () => {
  const hf = rowsFor().find((r) => r.key === 'hedge_net_equity_form_pf');
  assert.equal(hf.text, '37.6% of NAV');
  assert.equal(hf.direction, 'sell');
  assert.equal(hf.percentile, 46);
  assert.equal(hf.section, 'hedge');
});

test('rows are not stale on the build date and go stale when the page moves on', () => {
  assert.equal(rowsFor().some((r) => r.stale), false);
  const later = rowsFor({ ...real, as_of: '2026-11-30' });
  const stale = Object.fromEntries(later.map((r) => [r.key, r.stale]));
  assert.equal(stale.etf_us_equity, true); // 39 days behind a daily source
  assert.equal(stale.futures_lev_money_es, true); // 48 days behind a weekly source
  assert.equal(stale.z1_households, true); // 153 days behind a quarterly source
  const two = rowsFor({ ...real, as_of: '2026-10-24' });
  assert.equal(two.find((r) => r.key === 'etf_us_equity').stale, false); // two days: inside three
});

test('missing inputs drop their rows and never invent numbers', () => {
  const noCot = rowsFor({ ...real, cot: undefined });
  assert.equal(noCot.some((r) => r.key === 'futures_lev_money_es'), false);
  const noMutual = {
    ...real,
    z1: { ...real.z1, latest: real.z1.latest.filter((r) => r.key !== 'mutual_funds') },
  };
  assert.equal(rowsFor(noMutual).some((r) => r.key === 'z1_mutual_funds'), false);
  const noBuyHistory = {
    ...real,
    demand_pipeline: { buybacks: { indices: { SPX: { history: { quarterly: [] } } } } },
  };
  assert.equal(rowsFor(noBuyHistory).some((r) => r.key === 'companies_spx_buybacks'), false);
  assert.deepEqual(rowsFor({}), []);
  assert.deepEqual(rowsFor({ as_of: '2026-10-22', etf: { unavailable: 'no feed' } }), []);
});

test('an unknown frequency sorts after the known ones and a missing percentile sorts last within its group', () => {
  const rows = sortRows([
    { key: 'q1', frequency: 'quarterly', percentile: 60 },
    { key: 'q2', frequency: 'quarterly', percentile: null },
    { key: 'd1', frequency: 'daily', percentile: 50 },
    { key: 'q3', frequency: 'quarterly', percentile: 90 },
  ]);
  assert.deepEqual(rows.map((r) => r.key), ['d1', 'q3', 'q1', 'q2']);
});

test('last-quarter bars: holder groups only, largest buyer first, total and issuer lines left out', () => {
  const bars = holderBars(real.z1);
  assert.equal(bars.quarter, '2026Q2');
  assert.deepEqual(bars.bars.map((b) => b.key), [
    'rest_of_world', 'etfs', 'households', 'broker_dealers', 'pensions', 'other', 'insurers', 'mutual_funds',
  ]);
  assert.equal(bars.bars[0].value, 410.24);
  assert.equal(bars.bars.at(-1).value, -222.96);
  assert.equal(holderBars({ latest: [] }), null);
  assert.equal(holderBars(undefined), null);
});

test('each percentile names the history it ranks against, and Form PF is exposure, not buying', () => {
  const rows = rowsFor();
  for (const row of rows.filter((r) => r.percentile != null)) assert.ok(row.span, row.key);
  const hf = rows.find((r) => r.key === 'hedge_net_equity_form_pf');
  if (hf) assert.equal(hf.exposure, true);
});
