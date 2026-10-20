import { test } from 'node:test';
import assert from 'node:assert/strict';
import { historicalContext, summarize, scenarioCharts, marginReferenceState, industryComparators, openingGrowth, plausibleBox, growthWindow, marginScale } from '../../web/js/reverse-dcf-context.js';
import { scenarioValue } from '../../web/js/reverse-dcf-math.js';
import { historyOption, frontierOption, sensitivityOption } from '../../web/js/reverse-dcf-charts.js';

const cfg = { reference_years: 5, history_cagr_years: [3, 5], margin_bounds_pct: [0, 100], growth_grid_pct: [0, 5, 10],
  chart_growth_step_pct: 1, sensitivity_wacc_shifts_pp: [-2, 0, 2], sensitivity_investment_shifts_pp: [-2, 0, 2] };
const s = { revenue: 100e9, baseMargin: .2, margin: .25, growth: .05, wacc: .09, netInvestment: .05, tax: .25,
  terminalGrowth: .025, terminalRoic: .15, years: 10, transitionYears: 5 };
const annual = () => ({ columns: Array.from({ length: 6 }, (_, i) => ({ period_end: `${2020 + i}-06-30`, filed: `${2020 + i}-08-01` })),
  values: { revenue: Array.from({ length: 6 }, (_, i) => 100 * 1.1 ** i),
    ebit: Array.from({ length: 6 }, (_, i) => 20 * 1.1 ** i),
    cost_of_revenue: Array.from({ length: 6 }, (_, i) => 60 * 1.1 ** i), capex: [0, 2, 3, null, 5, 6] } });
const near = (a, b, tolerance = 1e-8) => assert.ok(Math.abs(a - b) < tolerance, `${a} vs ${b}`);
const base = { grid: {}, xAxis: { axisLabel: {} }, yAxis: { axisLabel: {} }, tooltip: {} };
const p = { blue: '#60a5fa', accent: '#e8a33d', purple: '#a78bfa', dim: '#999', text: '#fff' };

test('historical ratios come from matching annual amounts, gross profit can derive from revenue minus cost', () => {
  const context = historicalContext(annual(), '2026-10-16', cfg);
  assert.equal(context.rows.length, 6);
  assert.equal(context.rows[0].growth, null);
  near(context.rows[5].growth, 10);
  near(context.rows[5].operatingMargin, 20);
  near(context.rows[5].grossMargin, 40);
  assert.equal(context.rows[0].capexShare, 0);
  assert.equal(context.rows[3].capexShare, null);
  assert.equal(context.margin.n, 5);
  near(context.cagr[0].value, 10, .01);
  near(context.cagr[1].value, 10, .01);
});

test('summary excludes missing inputs, not zero, and uses the actual finite denominator', () => {
  assert.deepEqual(summarize([null, undefined, NaN, 0, 2, 4, 6]), { n: 4, min: 0, max: 6, median: 3 });
  assert.deepEqual(summarize([null]), { n: 0, min: null, max: null, median: null });
});

test('short / all-null history never creates growth or a ratio, including null cost', () => {
  const context = historicalContext({ columns: [{ period_end: '2025-06-30', filed: '2025-08-01' }], values: { revenue: [100], ebit: [null], cost_of_revenue: [null] } }, '2026-10-16', cfg);
  assert.equal(context.margin.n, 0);
  assert.equal(context.rows[0].grossMargin, null);
  assert.ok(context.cagr.every((c) => c.value === null));
});

test('missing / skipped / stub annual periods are not bridged to manufacture YoY or CAGR', () => {
  const missing = annual(); missing.values.revenue[3] = null;
  const a = historicalContext(missing, '2026-10-16', cfg);
  assert.equal(a.rows[3].growth, null);
  assert.equal(a.rows[4].growth, null);
  assert.equal(a.cagr[1].value, null);
  const skipped = annual(); skipped.columns[2].period_end = '2021-12-31';
  const b = historicalContext(skipped, '2026-10-16', cfg);
  assert.equal(b.rows[2].growth, null);
  assert.equal(b.rows[3].growth, null);
});

test('unfiled or future annual observations stay out of historical references', () => {
  const input = annual(); input.columns[5].filed = '2026-11-01';
  const h = historicalContext(input, '2026-10-16', cfg);
  assert.equal(h.rows.length, 5);
  assert.equal(h.cagr[1].value, null);
  input.columns[4].period_end = '2027-06-30';
  assert.equal(historicalContext(input, '2026-10-16', cfg).rows.length, 4);
});

test('explicit gross-profit zero is retained and not replaced by derived gross profit', () => {
  const input = annual(); input.values.gross_profit = [0, null, null, null, null, null];
  const h = historicalContext(input, '2026-10-16', cfg);
  assert.equal(h.rows[0].grossMargin, 0);
  near(h.rows[1].grossMargin, 40);
});

test('every frontier root reconstructs the working EV; chosen off-grid growth is represented', () => {
  const scenario = { ...s, growth: .056 };
  const { frontier } = scenarioCharts(scenario, 250e9, cfg);
  assert.equal(frontier.length, 3);
  assert.ok(frontier[0].points.some(([g]) => g === scenario.growth * 100));
  for (const curve of frontier) for (const [growth, margin] of curve.points) if (margin !== null) {
    near(scenarioValue({ ...scenario, wacc: curve.wacc, growth: growth / 100, margin: margin / 100 }).ev / 250e9, 1);
  }
});

test('invalid discount and investment combinations are gaps, not zero EV or clamped curves', () => {
  const input = { ...s, wacc: .03, netInvestment: 0 };
  const curves = scenarioCharts(input, 1e20, cfg);
  assert.ok(curves.frontier.every((c) => c.points.every(([, margin]) => margin === null)));
  assert.ok(curves.sensitivity.some((r) => r.netInvestment < 0 && r.ev === null && r.gap === null));
  assert.ok(curves.sensitivity.some((r) => r.wacc <= s.terminalGrowth && r.ev === null));
});

test('sensitivity values retain terminal share including >100%, without treating it as probability', () => {
  const result = scenarioCharts(s, 250e9, cfg);
  const center = result.sensitivity.find((r) => r.wacc === s.wacc && r.netInvestment === s.netInvestment);
  const v = scenarioValue(s);
  near(center.ev, v.ev);
  near(center.terminalShare, v.terminalPv / v.ev * 100);
  near(center.gap, (v.ev / 250e9 - 1) * 100);
  const negativeExplicit = scenarioCharts({ ...s, netInvestment: .25 }, 250e9, cfg).sensitivity;
  assert.ok(negativeExplicit.some((r) => r.ev > 0 && r.terminalShare > 100));
});

test('chart specification separates annual history, NOW proxy and model years; no forecast gross margins', () => {
  const h = historicalContext(annual(), '2026-10-16', cfg);
  const option = historyOption(base, p, h, s, scenarioValue(s), 'margin', '2026-10-16');
  assert.equal(option.xAxis.data[6], 'NOW 2026-10-16');
  assert.equal(option.xAxis.data.at(-1), 'M10');
  assert.ok(option.series[1].data.slice(6).every((v) => v === null));
  assert.ok(option.series[2].data.slice(0, 6).every((v) => v === null));
  assert.equal(option.series[2].lineStyle.type, 'dashed');
  assert.equal(option.series[0].connectNulls, false);
  const invalid = historyOption(base, p, h, { ...s, growth: null }, { error: 'invalid' }, 'growth', '2026-10-16');
  assert.equal(invalid.series.length, 1);
  assert.equal(invalid.xAxis.data.length, 6);
});

test('chart data and units agree with solved points and EV billions, including safe null tooltips', () => {
  const h = historicalContext(annual(), '2026-10-16', cfg);
  const curves = scenarioCharts(s, 250e9, cfg);
  const frontier = frontierOption(base, p, curves.frontier, h, s, cfg);
  assert.deepEqual(frontier.series[0].data, curves.frontier[0].points);
  assert.deepEqual(frontier.series.at(-1).data[0], [5, 25]);
  const sensitivity = sensitivityOption(base, p, curves.sensitivity, 250e9);
  near(sensitivity.series[0].data[0][1], curves.sensitivity[0].ev / 1e9);
  assert.equal(sensitivity.series[0].markLine.data[0].yAxis, 250);
  assert.doesNotThrow(() => sensitivity.tooltip.formatter({ value: [7, null], marker: '', seriesName: 'test' }));
});

test('sensitivity axis always includes working EV with padding, even outside all scenario values', () => {
  const rows = scenarioCharts(s, 250e9, cfg).sensitivity;
  const above = sensitivityOption(base, p, rows, 1e12);
  assert.ok(above.yAxis.max > 1000);
  assert.ok(above.yAxis.min < Math.min(...rows.map((r) => r.ev / 1e9)));
  const below = sensitivityOption(base, p, rows, 1e9);
  assert.ok(below.yAxis.min < 1);
  assert.ok(below.yAxis.max > Math.max(...rows.map((r) => r.ev / 1e9)));
  assert.equal(above.xAxis.scale, true);
});

test('frontier references outside solve bounds remain visible without changing or clamping solved roots', () => {
  const h = historicalContext(annual(), '2026-10-16', cfg);
  h.margin.median = -5;
  const options = frontierOption(base, p, [], h, { ...s, margin: .8 }, { ...cfg, margin_bounds_pct: [0, 50] });
  assert.ok(options.yAxis.min <= -5);
  assert.ok(options.yAxis.max >= 80);
});

test('color encodes own historical range, not cheapness, with neutral missing / thin data', () => {
  const stats = { n: 5, min: 20, max: 25, median: 22 };
  assert.deepEqual(marginReferenceState(40, stats, 5), { tone: 'above', label: 'ABOVE OWN HISTORY' });
  assert.equal(marginReferenceState(10, stats, 5).tone, 'below');
  assert.equal(marginReferenceState(22, stats, 5).tone, 'neutral');
  assert.equal(marginReferenceState(25.04, stats, 5).tone, 'neutral');
  assert.equal(marginReferenceState(25.06, stats, 5).tone, 'above');
  assert.equal(marginReferenceState(null, stats, 5).label, 'REFERENCE UNAVAILABLE');
  assert.equal(marginReferenceState(40, { ...stats, n: 1 }, 5).label, 'LIMITED HISTORY');
});

test('GICS comparators exclude selected issuer, duplicate classes, stale / future / missing data, with no sector fallback', () => {
  const company = { ticker: 'SELF', cik: 1, sector: 'Goods', sub_sector: 'Personal' };
  const peer = (ticker, cik, margin, extra = {}) => ({ ...company, ticker, cik, operating_margin: margin, period_end: '2026-06-30', filed: '2026-08-01', ...extra });
  const rows = [peer('SELF-B', '1', 99), peer('A', 2, 0), peer('A-B', 2, 99), peer('B', 3, -5),
    peer('X', 4, 80, { sub_sector: 'Different' }), peer('Y', 5, 50, { filed: '2027-01-01' }),
    peer('Z', 6, 70, { lagged: true }), peer('N', 7, null), peer('BAD', 8, 90, { period_end: 'bad' })];
  const result = industryComparators(rows, company, '2026-10-16', 3);
  assert.deepEqual(result.members.map((r) => r.ticker), ['A', 'B']);
  assert.equal(result.candidates, 6);
  assert.equal(result.median, null);
  assert.equal(result.thin, true);
  assert.equal(industryComparators([...rows, peer('C', 9, 10)], company, '2026-10-16', 3).median, 0);
  assert.equal(industryComparators(rows, { ticker: 'MISSING', sector: 'Goods' }, '2026-10-16', 3).usable, 0);
});

test('opening growth prefers the later analyst year, then the longest CAGR, then the shared default', () => {
  const consensus = { periods: [{ end: '2027-06-30', growth_pct: 2.14 }, { end: '2028-06-30', growth_pct: 3.04 }] };
  const history = { cagr: [{ years: 3, value: 4.0, start: 'a', end: 'b' }, { years: 5, value: 2.66, start: 'c', end: 'd' }] };
  assert.deepEqual([openingGrowth(consensus, history, 5).value, openingGrowth(consensus, history, 5).source], [3, 'consensus']);
  assert.deepEqual([openingGrowth(null, history, 5).value, openingGrowth(null, history, 5).origin], [2.7, 'COMPANY 5Y REVENUE CAGR']);
  assert.deepEqual([openingGrowth(null, { cagr: [{ years: 5, value: null }] }, 5).value, openingGrowth(null, null, 5).source], [5, 'default']);
});

test('the evidence box spans analyst low-high by reported margin range, and the window frames it', () => {
  const history = { margin: { n: 5, min: 22.1, max: 24.3 }, cagr: [{ value: 2.7 }] };
  const consensus = { periods: [{ growth_pct: 2.1, growth_low_pct: 1.6, growth_high_pct: 2.9 }, { growth_pct: 3.0, growth_low_pct: 1.0, growth_high_pct: 6.3 }] };
  const box = plausibleBox(consensus, history);
  assert.deepEqual(box, { growth: [1.0, 6.3], margin: [22.1, 24.3], growthSource: 'analyst low–high' });
  assert.deepEqual(plausibleBox(null, history).growth, [2.2, 3.2]);   // one CAGR, widened to a visible width
  assert.equal(plausibleBox(consensus, { margin: { n: 0 } }), null);
  assert.deepEqual(growthWindow(box, 3), [-3, 12]);
  assert.equal(growthWindow(null, null), null);
  assert.equal(marginScale([40.2, 24.3, 18]), 50);
  assert.equal(marginScale([5]), 30);
  assert.equal(marginScale([95]), 100);
});

test('the frontier draws the evidence box and fits its axes to the window', () => {
  const h = historicalContext(annual(), '2026-10-16', cfg);
  const box = { growth: [1, 6], margin: [20, 25] };
  const curves = scenarioCharts(s, 250e9, cfg, [-3, 12]);
  const option = frontierOption(base, p, curves.frontier, h, s, cfg, box);
  const area = option.series.at(-1).markArea.data[0];
  assert.deepEqual([area[0].xAxis, area[0].yAxis, area[1].xAxis, area[1].yAxis], [1, 20, 6, 25]);
  assert.equal(option.xAxis.min, -3);
  assert.equal(option.xAxis.max, 12);
  assert.ok(option.yAxis.max <= 100);
});
