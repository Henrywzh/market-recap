// The RAMP TOKENOMICS card's arithmetic: shares, range cuts, the series the chart
// draws, the default legend selection, the latest-week table and the formatters.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/ramp-tokenomics-model.js';

const DAY = 86400000;

// Every Sunday from `from` to `to`, inclusive.
function weekly(from, to) {
  const out = [];
  for (let t = Date.parse(from); t <= Date.parse(to); t += 7 * DAY) out.push(new Date(t).toISOString().slice(0, 10));
  return out;
}

const WEEKS = ['2026-09-20', '2026-09-27', '2026-10-04', '2026-10-11'];

const PAYLOAD = {
  weeks: WEEKS,
  volume: {
    unit: 'billion tokens',
    total: [100, 200, null, 400],
    makers: [
      { key: 'openai', name: 'OpenAI', values: [30, 60, null, 120] },
      { key: 'anthropic', name: 'Anthropic', values: [10, 0, 5, null] },
      { key: 'google', name: 'Google', values: [null, null, null, 40] },
      { key: 'xai', name: 'xAI', values: [5, 10, 15, 20] },
      { key: 'mistral', name: 'Mistral', values: [1, 1, 1, 1] },
    ],
    models: [
      { key: 'openai · gpt-5', maker: 'openai', label: 'GPT-5', values: [30, 60, null, 120] },
      { key: 'anthropic · claude-sonnet-4', maker: 'anthropic', label: 'Claude Sonnet 4', values: [10, 0, 5, null] },
      { key: 'google · gemini-2', maker: 'google', label: 'Gemini 2', values: [null, null, null, 40] },
      { key: 'openai · gpt-4o', maker: 'openai', label: 'GPT-4o', values: [5, 10, 15, 20] },
    ],
  },
  spend: {
    unit: 'USD million',
    total: [1000, 2000, 3000, 4000],
    makers: [
      { key: 'openai', name: 'OpenAI', values: [300, 600, 900, 1200] },
      { key: 'anthropic', name: 'Anthropic', values: [null, 100, 100, 100] },
    ],
    models: [{ key: 'openai · gpt-5', maker: 'openai', label: 'GPT-5', values: [300, 600, 900, 1200] }],
  },
  prices: {
    unit: 'USD per million tokens',
    dates: ['2026-10-10', '2026-10-11', '2026-10-12'],
    types: {
      all_tokens: [
        { key: 'anthropic', name: 'Anthropic', values: [3, 3, null] },
        { key: 'openai', name: 'OpenAI', values: [2.5, 2.5, 2.4] },
      ],
      uncached_input: [{ key: 'anthropic', name: 'Anthropic', values: [3, 3, 3] }],
      output: [{ key: 'openai', name: 'OpenAI', values: [10, 10, 0] }],
    },
  },
  default_makers: ['openai', 'anthropic', 'google', 'xai', 'deepseek'],
  models_shown: 4,
  models_total: 480,
  latest_week: '2026-10-11',
  captured_at: '2026-10-14T06:00:00Z',
  stale_days: 3,
  commit: { sha: 'abcdef1234567', date: '2026-10-13' },
};

const names = (s) => s.series.map((x) => x.name);

test('shareSeries: a gap stays null, a reported zero stays 0, a missing or non-positive total is a gap', () => {
  assert.deepEqual(M.shareSeries([30, null, 0, 5, 10], [100, 100, 100, null, 0]), [30, null, 0, null, null]);
  assert.deepEqual(M.shareSeries([5], [-1]), [null]);
  assert.deepEqual(M.shareSeries([5, 6], undefined), [null, null]);
  assert.deepEqual(M.shareSeries(undefined, [1, 2]), []);
});

test('logValues: anything not above zero is a gap on a log axis, a positive value is kept', () => {
  assert.deepEqual(M.logValues([null, 0, -1, 2.5, undefined, 1e-6]), [null, null, null, 2.5, null, 1e-6]);
  assert.deepEqual(M.logValues(undefined), []);
});

test('shareSeries: a subset of series still divides by the full total', () => {
  // OpenAI's 120 is 30% of the 400 reported that week, whatever else is drawn.
  assert.deepEqual(M.shareSeries([120, 40], [400, 400]), [30, 10]);
  const volume = M.pickSeries(PAYLOAD, { metric: 'VOLUME', breakdown: 'BY MAKER' });
  const openai = volume.series.filter((s) => s.key === 'openai');
  assert.deepEqual(M.latestRows(openai, volume.total).map((r) => r.share), [30]);
});

test('rangeStartIndex: 3M, 6M and 1Y cut 92, 182 and 365 calendar days back from the last date; ALL is no cut', () => {
  const all = weekly('2025-01-12', '2026-10-11');
  const at = (label) => all[M.rangeStartIndex(all, label)];
  assert.equal(at('3M'), '2026-07-12');  // cut 2026-07-11, a Saturday: the first Sunday on or after it
  assert.equal(at('6M'), '2026-04-12');  // cut 2026-04-12 exactly
  assert.equal(at('1Y'), '2025-10-12');  // cut 2025-10-11, a Saturday
  assert.equal(at('ALL'), '2025-01-12');
  assert.deepEqual(M.RANGES, ['3M', '6M', '1Y', 'ALL']);
});

test('rangeStartIndex: a sparse series takes the first date on or after the cut; unknown labels, no dates and bad dates give 0', () => {
  assert.equal(M.rangeStartIndex(['2026-04-11', '2026-04-19', '2026-10-11'], '6M'), 1);
  assert.equal(M.rangeStartIndex([], '3M'), 0);
  assert.equal(M.rangeStartIndex(WEEKS, 'YTD'), 0);
  assert.equal(M.rangeStartIndex(WEEKS, 'constructor'), 0);
  assert.equal(M.rangeStartIndex(['not a date'], '3M'), 0);
});

test('pickSeries: VOLUME by maker keeps every maker, gaps as null, zeros as zeros, with the full total', () => {
  const s = M.pickSeries(PAYLOAD, { metric: 'VOLUME', breakdown: 'BY MAKER' });
  assert.deepEqual(s.dates, WEEKS);
  assert.deepEqual(s.total, [100, 200, null, 400]);
  assert.equal(s.unitLabel, 'billion tokens');
  assert.deepEqual(names(s), ['OpenAI', 'Anthropic', 'Google', 'xAI', 'Mistral']);
  assert.deepEqual(s.series.map((x) => x.key), ['openai', 'anthropic', 'google', 'xai', 'mistral']);
  assert.deepEqual(s.series[1].values, [10, 0, 5, null]);
  assert.deepEqual(s.series[0], { key: 'openai', name: 'OpenAI', values: [30, 60, null, 120], unit: 'billion tokens' });
});

test('pickSeries: VOLUME by model lists the shipped models with their labels, and keeps the full total', () => {
  const s = M.pickSeries(PAYLOAD, { metric: 'VOLUME', breakdown: 'BY MODEL' });
  assert.deepEqual(names(s), ['GPT-5', 'Claude Sonnet 4', 'Gemini 2', 'GPT-4o']);
  assert.deepEqual(s.series.map((x) => x.key), ['openai · gpt-5', 'anthropic · claude-sonnet-4', 'google · gemini-2', 'openai · gpt-4o']);
  assert.deepEqual(s.series[0].values, [30, 60, null, 120]);
  assert.deepEqual(s.total, [100, 200, null, 400]);
});

test('pickSeries: a model label shared by two makers gets its maker appended, so legend names stay unique', () => {
  const s = M.pickSeries({
    weeks: ['2026-10-11'],
    volume: { models: [
      { key: 'openai · gpt-4o', maker: 'openai', label: 'GPT-4o', values: [1] },
      { key: 'x · gpt-4o', maker: 'x', label: 'GPT-4o', values: [2] },
    ] },
  }, { metric: 'VOLUME', breakdown: 'BY MODEL' });
  assert.deepEqual(names(s), ['GPT-4o (openai)', 'GPT-4o (x)']);
});

test('pickSeries: SPEND by maker and by model use the spend unit and total', () => {
  const byMaker = M.pickSeries(PAYLOAD, { metric: 'SPEND', breakdown: 'BY MAKER' });
  assert.deepEqual(names(byMaker), ['OpenAI', 'Anthropic']);
  assert.deepEqual(byMaker.series[1].values, [null, 100, 100, 100]);
  assert.deepEqual(byMaker.total, [1000, 2000, 3000, 4000]);
  assert.equal(byMaker.unitLabel, 'USD million');
  assert.equal(byMaker.series[0].unit, 'USD million');

  const byModel = M.pickSeries(PAYLOAD, { metric: 'SPEND', breakdown: 'BY MODEL' });
  assert.deepEqual(names(byModel), ['GPT-5']);
  assert.deepEqual(byModel.total, [1000, 2000, 3000, 4000]);
});

test('pickSeries: PRICE is by maker for one token type, with no total; the breakdown is ignored', () => {
  const all = M.pickSeries(PAYLOAD, { metric: 'PRICE', tokenType: 'ALL' });
  assert.deepEqual(all.dates, ['2026-10-10', '2026-10-11', '2026-10-12']);
  assert.deepEqual(names(all), ['Anthropic', 'OpenAI']);
  assert.deepEqual(all.series[0].values, [3, 3, null]);
  assert.deepEqual(all.series[1].values, [2.5, 2.5, 2.4]);
  assert.equal(all.total, null);
  assert.equal(all.unitLabel, 'USD per million tokens');
  assert.equal(all.series[1].unit, 'USD per million tokens');

  assert.deepEqual(names(M.pickSeries(PAYLOAD, { metric: 'PRICE', breakdown: 'BY MODEL', tokenType: 'ALL' })), ['Anthropic', 'OpenAI']);

  const uncached = M.pickSeries(PAYLOAD, { metric: 'PRICE', tokenType: 'UNCACHED INPUT' });
  assert.deepEqual(names(uncached), ['Anthropic']);
  assert.deepEqual(uncached.series[0].values, [3, 3, 3]);

  const output = M.pickSeries(PAYLOAD, { metric: 'PRICE', tokenType: 'OUTPUT' });
  assert.deepEqual(names(output), ['OpenAI']);
  assert.deepEqual(output.series[0].values, [10, 10, 0]);   // a reported zero stays 0

  // An unknown token type reads as ALL.
  assert.deepEqual(M.pickSeries(PAYLOAD, { metric: 'PRICE', tokenType: 'nope' }).series, all.series);
});

test('pickSeries: an unknown metric reads as VOLUME by maker, and a bare payload gives empty series, not a throw', () => {
  assert.deepEqual(M.pickSeries(PAYLOAD, { metric: 'nope' }), M.pickSeries(PAYLOAD, { metric: 'VOLUME', breakdown: 'BY MAKER' }));
  assert.deepEqual(M.pickSeries({}, {}), { dates: [], series: [], total: null, unitLabel: 'billion tokens' });
  assert.deepEqual(M.pickSeries(undefined), { dates: [], series: [], total: null, unitLabel: 'billion tokens' });
  assert.deepEqual(M.pickSeries(null, { metric: 'PRICE' }), { dates: [], series: [], total: null, unitLabel: 'USD per million tokens' });
  // A maker with no values reads as a gap on every week; a missing total is null.
  const gap = M.pickSeries({ weeks: ['2026-10-04', '2026-10-11'], volume: { makers: [{ key: 'x', name: 'X' }] } }, {});
  assert.deepEqual(gap.series[0].values, [null, null]);
  assert.equal(gap.total, null);
});

test('defaultVisible: BY MAKER shows the default makers present, in configured order; every maker when none are named', () => {
  const s = M.pickSeries(PAYLOAD, { metric: 'VOLUME', breakdown: 'BY MAKER' }).series;
  assert.deepEqual([...M.defaultVisible(s, PAYLOAD, 'BY MAKER')], ['openai', 'anthropic', 'google', 'xai']);
  assert.deepEqual([...M.defaultVisible([...s].reverse(), PAYLOAD, 'BY MAKER')], ['openai', 'anthropic', 'google', 'xai']);
  assert.deepEqual([...M.defaultVisible(s, {}, 'BY MAKER')], ['openai', 'anthropic', 'google', 'xai', 'mistral']);
});

test('defaultVisible: BY MODEL shows the eight largest on the latest week with data, and no more', () => {
  const last = [5, 90, 10, 70, 30, 60, 20, 80, 40, 50];
  const series = last.map((v, i) => ({ key: `m${i}`, name: `M${i}`, values: [1, 1, 1, v] }));
  assert.deepEqual([...M.defaultVisible(series, {}, 'BY MODEL')], ['m1', 'm7', 'm3', 'm5', 'm9', 'm8', 'm4', 'm6']);
  assert.equal(M.defaultVisible(series, {}, 'BY MODEL').size, 8);
});

test('defaultVisible: a model with no figure on the latest week is not ranked, however large it was before', () => {
  const last = [5, 90, 10, 70, 30, 60, 20, 80, 40, 50];
  const series = last.map((v, i) => ({ key: `m${i}`, name: `M${i}`, values: [1, 1, 1, v] }));
  const withGap = series.map((s, i) => (i === 9 ? { ...s, values: [999, 999, 999, null] } : s));
  assert.deepEqual([...M.defaultVisible(withGap, {}, 'BY MODEL')], ['m1', 'm7', 'm3', 'm5', 'm8', 'm4', 'm6', 'm2']);
  assert.deepEqual([...M.defaultVisible(series.slice(0, 3), {}, 'BY MODEL')], ['m1', 'm2', 'm0']);
  assert.deepEqual([...M.defaultVisible([], {}, 'BY MODEL')], []);
});

test('latestRows: the latest week with any figure, largest first, gaps last; shares use the full total', () => {
  const s = M.pickSeries(PAYLOAD, { metric: 'VOLUME', breakdown: 'BY MAKER' });
  const rows = M.latestRows(s.series, s.total);
  assert.deepEqual(rows.map((r) => r.name), ['OpenAI', 'Google', 'xAI', 'Mistral', 'Anthropic']);
  assert.deepEqual(rows.map((r) => r.value), [120, 40, 20, 1, null]);
  assert.deepEqual(rows.map((r) => r.share), [30, 10, 5, 0.25, null]);
  assert.equal(M.formatVolume(rows.at(-1).value), '—');
});

test('latestRows: with no figure on the latest week, it reads the week before; a reported zero is a value, not a gap', () => {
  const back = M.latestRows([{ key: 'a', name: 'A', values: [1, 2, null, null] }], [10, 20, null, null]);
  assert.deepEqual(back, [{ key: 'a', name: 'A', value: 2, share: 10 }]);
  const zero = M.latestRows([{ key: 'a', name: 'A', values: [null, 0] }, { key: 'b', name: 'B', values: [null, null] }], [null, 10]);
  assert.deepEqual(zero, [
    { key: 'a', name: 'A', value: 0, share: 0 },
    { key: 'b', name: 'B', value: null, share: null },
  ]);
});

test('latestRows: prices have no share, and the latest day is the last day with a figure', () => {
  const p = M.pickSeries(PAYLOAD, { metric: 'PRICE', tokenType: 'ALL' });
  const rows = M.latestRows(p.series, p.total);
  assert.deepEqual(rows, [
    { key: 'openai', name: 'OpenAI', value: 2.4, share: null },
    { key: 'anthropic', name: 'Anthropic', value: null, share: null },
  ]);
});

test('latestRows: nothing to show gives no rows, and a series with no figure at all gives gaps', () => {
  assert.deepEqual(M.latestRows([], null), []);
  assert.deepEqual(M.latestRows([{ key: 'a', name: 'A', values: [null] }], [5]), [{ key: 'a', name: 'A', value: null, share: null }]);
});

test('formatVolume: billions, with trillions from 1,000 once rounding reads 1,000; decimals by size; a gap is an em dash', () => {
  assert.equal(M.formatVolume(0), '0B');
  assert.equal(M.formatVolume(0.5), '0.500B');
  assert.equal(M.formatVolume(12.345), '12.3B');
  assert.equal(M.formatVolume(99.96), '100B');
  assert.equal(M.formatVolume(412.4), '412B');
  assert.equal(M.formatVolume(999.4), '999B');
  assert.equal(M.formatVolume(999.9), '1.00T');   // would print 1,000B: it is 1.00T
  assert.equal(M.formatVolume(1000), '1.00T');
  assert.equal(M.formatVolume(1234), '1.23T');
  assert.equal(M.formatVolume(null), '—');
  assert.equal(M.formatVolume(undefined), '—');
  assert.equal(M.formatVolume(NaN), '—');
  assert.equal(M.formatVolume('12'), '—');
});

test('formatSpend: $ millions, with $B from 1,000 once rounding reads 1,000; a gap is an em dash', () => {
  assert.equal(M.formatSpend(5), '$5.00M');
  assert.equal(M.formatSpend(412.4), '$412M');
  assert.equal(M.formatSpend(999.4), '$999M');
  assert.equal(M.formatSpend(999.9), '$1.00B');
  assert.equal(M.formatSpend(1000), '$1.00B');
  assert.equal(M.formatSpend(1234.5), '$1.23B');
  assert.equal(M.formatSpend(null), '—');
});

test('formatPrice: $ with two decimals (three below $1), per million tokens; a gap is an em dash', () => {
  assert.equal(M.formatPrice(3), '$3.00 per M tokens');
  assert.equal(M.formatPrice(0.5123), '$0.512 per M tokens');
  assert.equal(M.formatPrice(0), '$0.00 per M tokens');
  assert.equal(M.formatPrice(75), '$75.00 per M tokens');
  assert.equal(M.formatPrice(null), '—');
  assert.equal(M.formatPriceValue(3), '$3.00');
  assert.equal(M.formatPriceValue(undefined), '—');
});

test('formatShare: percent by size; a gap is an em dash', () => {
  assert.equal(M.formatShare(23.456), '23.5%');
  assert.equal(M.formatShare(100), '100%');
  assert.equal(M.formatShare(0.4123), '0.412%');
  assert.equal(M.formatShare(0), '0%');
  assert.equal(M.formatShare(null), '—');
});

test('formatters never print more than three decimals', () => {
  for (const v of [0.0001, 0.5, 9.9999, 99.999, 999.999, 12345.678, 0.99996]) {
    for (const text of [M.formatVolume(v), M.formatSpend(v), M.formatShare(v), M.formatPrice(v)]) {
      assert.doesNotMatch(text, /\.\d{4,}/, text);
    }
  }
});

// MONTHLY ARR. Weeks end on Sundays; a week covers the seven days ending on it.
const SEPT_WEEKS = ['2026-09-06', '2026-09-13', '2026-09-20', '2026-09-27', '2026-10-04'];

test('monthlyFromWeekly: a week that straddles a month boundary splits by days (5 days to July, 2 to August)', () => {
  const m = M.monthlyFromWeekly(['2026-08-02'], [70]);
  assert.deepEqual(m.months, ['2026-07', '2026-08']);
  assert.deepEqual(m.daysCovered, [5, 2]);
  assert.deepEqual(m.perDay, [10, 10]);
  assert.deepEqual(m.daysInMonth, [31, 31]);
  assert.deepEqual(m.partial, [true, true]);
  // Two weeks: July's 12 covered days are 7 at 20 a day and 5 at 10 a day.
  const two = M.monthlyFromWeekly(['2026-07-26', '2026-08-02'], [140, 70]);
  assert.deepEqual(two.daysCovered, [12, 2]);
  assert.equal(two.perDay[0], 190 / 12);
  assert.equal(two.perDay[1], 10);
});

test('monthlyFromWeekly: a null week covers no days and leaves its month partial; perDay averages only the covered days', () => {
  // Week to 6 Sep covers 31 Aug to 6 Sep at 10 a day; the week to 13 Sep is null; the week to 20 Sep covers 14 to 20 Sep at 20 a day.
  const m = M.monthlyFromWeekly(['2026-09-06', '2026-09-13', '2026-09-20'], [70, null, 140]);
  assert.deepEqual(m.months, ['2026-08', '2026-09']);
  assert.deepEqual(m.daysCovered, [1, 13]);
  assert.equal(m.perDay[1], 200 / 13);
  assert.deepEqual(m.partial, [true, true]);
});

test('monthlyFromWeekly: a reported zero covers its days with 0, so it is not a gap', () => {
  const m = M.monthlyFromWeekly(['2026-08-02'], [0]);
  assert.deepEqual(m.daysCovered, [5, 2]);
  assert.deepEqual(m.perDay, [0, 0]);
});

test('monthlyFromWeekly: a history that starts or ends mid-month is partial at that end; a whole month is not', () => {
  // Covers 14 to 30 Sep (17 days) and 1 to 4 Oct (4 days).
  const edges = M.monthlyFromWeekly(['2026-09-20', '2026-09-27', '2026-10-04'], [70, 70, 70]);
  assert.deepEqual(edges.months, ['2026-09', '2026-10']);
  assert.deepEqual(edges.daysCovered, [17, 4]);
  assert.deepEqual(edges.perDay, [10, 10]);
  assert.deepEqual(edges.partial, [true, true]);
  // The five weeks cover every day of September.
  const whole = M.monthlyFromWeekly(SEPT_WEEKS, [70, 70, 70, 70, 70]);
  assert.deepEqual(whole.months, ['2026-08', '2026-09', '2026-10']);
  assert.deepEqual(whole.daysCovered, [1, 30, 4]);
  assert.deepEqual(whole.partial, [true, false, true]);
});

test('monthlyFromWeekly: the month in progress is partial', () => {
  // The latest week ends on 11 October, so the month has 11 of its 31 days.
  const m = M.monthlyFromWeekly(['2026-10-04', '2026-10-11'], [70, 70]);
  assert.deepEqual(m.months, ['2026-09', '2026-10']);
  assert.deepEqual(m.daysCovered, [3, 11]);
  assert.deepEqual(m.partial, [true, true]);
});

test('monthlyFromWeekly: a month between two with data, and no covered day, is listed with a null perDay', () => {
  const m = M.monthlyFromWeekly(['2026-06-07', '2026-09-27'], [70, 70]);
  assert.deepEqual(m.months, ['2026-06', '2026-07', '2026-08', '2026-09']);
  assert.deepEqual(m.perDay, [10, null, null, 10]);
  assert.deepEqual(m.daysCovered, [7, 0, 0, 7]);
  assert.deepEqual(m.partial, [true, true, true, true]);
});

test('monthlyFromWeekly: leading gaps do not start the axis; no figures give empty lists', () => {
  assert.deepEqual(M.monthlyFromWeekly(['2026-06-07', '2026-09-27'], [null, 70]).months, ['2026-09']);
  assert.deepEqual(M.monthlyFromWeekly(['2026-06-07'], [null]), { months: [], perDay: [], daysCovered: [], daysInMonth: [], partial: [] });
  assert.deepEqual(M.monthlyFromWeekly(undefined, undefined), { months: [], perDay: [], daysCovered: [], daysInMonth: [], partial: [] });
});

test('monthlyView: SPEND is the mean day times 365 ($M a year); VOLUME stays the mean day', () => {
  const values = [70, 140, 140, 140, 70];   // Sep's 30 days: 17 a day on average; Aug and Oct: 10 a day
  const spend = M.monthlyView(SEPT_WEEKS, [{ key: 'a', name: 'A', values }], null, 'SPEND');
  assert.equal(M.ANNUAL_DAYS, 365);
  assert.deepEqual(spend.months, ['2026-08', '2026-09', '2026-10']);
  assert.deepEqual(spend.series[0].values, [3650, 6205, 3650]);
  const volume = M.monthlyView(SEPT_WEEKS, [{ key: 'a', name: 'A', values }], null, 'VOLUME');
  assert.deepEqual(volume.series[0].values, [10, 17, 10]);
  assert.deepEqual(volume.series[0].partial, [true, false, true]);
});

test('monthlyView: shares of the month sum to 100 over the series that report with the total', () => {
  const a = [70, 140, 140, 140, 70];
  const b = [70, 70, 70, 70, 70];
  const total = a.map((v, i) => v + b[i]);
  const view = M.monthlyView(SEPT_WEEKS, [{ key: 'a', name: 'A', values: a }, { key: 'b', name: 'B', values: b }], total, 'VOLUME');
  assert.deepEqual(view.total, [20, 27, 20]);
  const shares = view.series.map((s) => s.shares);
  assert.deepEqual(shares[0].map((x) => Math.round(x * 1e6) / 1e6), [50, 62.962963, 50]);
  view.months.forEach((_, i) => {
    assert.ok(Math.abs(shares[0][i] + shares[1][i] - 100) < 1e-9, `month ${view.months[i]}`);
  });
  // With no total, shares are gaps.
  const none = M.monthlyView(SEPT_WEEKS, [{ key: 'a', name: 'A', values: a }], null, 'VOLUME');
  assert.equal(none.total, null);
  assert.deepEqual(M.shareSeries(none.series[0].values, none.total), [null, null, null]);
});

test('monthlyView: a share is the series over the month\'s total; a gap in the series counts for nothing, so it reads low, never above 100', () => {
  // The total is 70, 140, 140, 140, 70 a week. The series has the same figures
  // except the week to 13 Sep, which it does not report. September's total is
  // 510 (30 days); the series reports 370 of it, so its share is 370 / 510.
  const total = [70, 140, 140, 140, 70];
  const series = [70, null, 140, 140, 70];
  const view = M.monthlyView(SEPT_WEEKS, [{ key: 'a', name: 'A', values: series }], total, 'VOLUME');
  assert.deepEqual(view.months, ['2026-08', '2026-09', '2026-10']);
  assert.equal(view.series[0].shares[0], 100);
  assert.ok(Math.abs(view.series[0].shares[1] - 3700 / 51) < 1e-9);
  assert.equal(view.series[0].shares[2], 100);
  // A series that shares no day with the total in a month has a null share.
  const none = M.monthlyView(['2026-06-07'], [{ key: 'a', name: 'A', values: [null] }], [70], 'VOLUME');
  assert.deepEqual(none.series[0].shares, [null]);
});

test('monthlyView: one month axis for every series, so a series with no figure in a month reads as a gap', () => {
  const view = M.monthlyView(['2026-06-07', '2026-09-27'], [
    { key: 'a', name: 'A', values: [70, 70] },
    { key: 'b', name: 'B', values: [null, 70] },
  ], null, 'VOLUME');
  assert.deepEqual(view.months, ['2026-06', '2026-07', '2026-08', '2026-09']);
  assert.deepEqual(view.series[0].values, [10, null, null, 10]);
  assert.deepEqual(view.series[1].values, [null, null, null, 10]);
  assert.deepEqual(view.series[1].partial, [true, true, true, true]);
});

test('modeAvailable: the monthly view is offered for VOLUME and SPEND, not for PRICE', () => {
  assert.equal(M.modeAvailable('VOLUME'), true);
  assert.equal(M.modeAvailable('SPEND'), true);
  assert.equal(M.modeAvailable('PRICE'), false);
  assert.deepEqual(M.MODES, ['WEEKLY', 'MONTHLY ARR']);
});
