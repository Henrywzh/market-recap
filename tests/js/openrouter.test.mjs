// The OpenRouter card's arithmetic: smoothing, the monthly run-rate, the range
// cuts and the series the charts draw.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/openrouter-model.js';

// Every calendar day from `from` to `to`, inclusive.
function span(from, to) {
  const out = [];
  for (let t = Date.parse(from); t <= Date.parse(to); t += 86400000) out.push(new Date(t).toISOString().slice(0, 10));
  return out;
}

const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} is not ${b}`);

test('rolling7 is a trailing seven-day mean, null until seven days exist', () => {
  assert.deepEqual(M.rolling7([1, 2, 3, 4, 5, 6, 7, 8]), [null, null, null, null, null, null, 4, 5]);
  assert.equal(M.rolling7([1, 1, 1, 1, 1, 1, 2])[6], 8 / 7);
  assert.deepEqual(M.rolling7([]), []);
});

test('rolling7 treats a missing day as missing, not as zero', () => {
  // The null at index 2 sits in the windows ending at 6, 7 and 8: those are null.
  // The window ending at 9 (days 3 to 9) is complete.
  assert.deepEqual(M.rolling7([1, 2, null, 4, 5, 6, 7, 8, 9, 10]), [null, null, null, null, null, null, null, null, null, 7]);
});

// February has 28 days, one of them (the 10th) without a figure.
// Days in January: the 30th and 31st only. March: the 5th only. April: all.
// May: the 1st to the 10th only.
const monthDates = [...span('2026-01-30', '2026-01-31'), ...span('2026-02-01', '2026-02-28'), '2026-03-05', ...span('2026-04-01', '2026-04-30'), ...span('2026-05-01', '2026-05-10')];
const monthRevenueK = monthDates.map((d) => {
  if (d === '2026-01-30') return 10;
  if (d === '2026-01-31') return 20;
  if (d === '2026-02-10') return null;
  if (d === '2026-03-05') return 200;
  return 100;
});

test('monthlyArr annualises the mean day of the days with data, in $ millions a year', () => {
  const m = M.monthlyArr(monthDates, monthRevenueK);
  assert.deepEqual(m.months, ['2026-01', '2026-02', '2026-03', '2026-04', '2026-05']);
  assert.deepEqual(m.days, [2, 27, 1, 30, 10]);
  assert.deepEqual(m.partial, [true, true, true, false, true]);
  // January mean $15k a day: 15 x 365 = $5,475k. February: the 27 days with data all at 100, not 28 with a zero.
  assert.deepEqual(m.arrM, [5.475, 36.5, 73, 36.5, 36.5]);
});

test('monthlyArr: a month with no dates between two others is a gap, not a zero, and is partial', () => {
  const m = M.monthlyArr(['2026-01-31', '2026-03-01'], [5, 7]);
  assert.deepEqual(m.months, ['2026-01', '2026-02', '2026-03']);
  assert.deepEqual(m.days, [1, 0, 1]);
  assert.deepEqual(m.arrM, [1.825, null, 2.555]);
  assert.deepEqual(m.partial, [true, true, true]);
});

test('monthlyArr: a provider with no figure in a month has a null run-rate', () => {
  const m = M.monthlyArr(['2026-01-01', '2026-01-02'], [null, null]);
  assert.deepEqual(m, { months: ['2026-01'], arrM: [null], partial: [true], days: [0] });
  assert.deepEqual(M.monthlyArr(['2026-01-01', '2026-01-31'], undefined).arrM, [null]);
});

test('monthlyAvgTokens is the mean day in each month, with no annualising', () => {
  const t = M.monthlyAvgTokens(monthDates, monthRevenueK);
  assert.deepEqual(t.months, ['2026-01', '2026-02', '2026-03', '2026-04', '2026-05']);
  assert.deepEqual(t.avgB, [15, 100, 200, 100, 100]);
  assert.deepEqual(t.partial, [true, true, true, false, true]);
});

test('rangeCut: 1M, 3M, 6M and 1Y cut at calendar days back from the last date; YTD at 1 January', () => {
  const all = span('2025-01-01', '2026-10-14');
  const at = (label) => all[M.rangeCut(all, label)];
  assert.equal(at('1M'), '2026-09-13');   // 31 days back
  assert.equal(at('3M'), '2026-07-14');   // 92 days back
  assert.equal(at('6M'), '2026-04-15');   // 182 days back
  assert.equal(at('YTD'), '2026-01-01');  // the last date's year
  assert.equal(at('1Y'), '2025-10-14');   // 365 days back
});

test('rangeCut takes the first date on or after the cut when days are missing', () => {
  const sparse = ['2026-04-14', '2026-04-16', '2026-10-14'];
  assert.equal(M.rangeCut(sparse, '6M'), 1);   // cut 2026-04-15: the 16th is the first on or after it
  assert.equal(M.rangeCut(sparse, '1Y'), 0);   // cut 2025-10-14: everything is inside
  assert.equal(M.rangeCut(sparse, '1M'), 2);   // cut 2026-09-13: only the last date
});

test('rangeCut gives 0 for MAX, an unknown label, and no dates', () => {
  const all = span('2025-01-01', '2026-10-14');
  assert.equal(M.rangeCut(all, 'MAX'), 0);
  assert.equal(M.rangeCut(all, 'nope'), 0);
  assert.equal(M.rangeCut(all, 'constructor'), 0);
  assert.equal(M.rangeCut([], '1M'), 0);
  assert.deepEqual(M.RANGES, ['1M', '3M', '6M', 'YTD', '1Y']);
});

test('logValues turns anything not above zero into a gap', () => {
  assert.deepEqual(M.logValues([null, 0, -1, 2.5, undefined, 1e-6]), [null, null, null, 2.5, null, 1e-6]);
});

test('legendSelection shows the default slugs and hides the rest; with no defaults it shows all', () => {
  const providers = [{ slug: 'openai', name: 'OpenAI' }, { slug: 'x-ai', name: 'xAI' }];
  assert.deepEqual(M.legendSelection(providers, ['openai']), { OpenAI: true, xAI: false });
  assert.deepEqual(M.legendSelection(providers, undefined), { OpenAI: true, xAI: true });
  assert.deepEqual(M.legendSelection(providers, []), { OpenAI: true, xAI: true });
});

test('openrouterSeries: daily values are smoothed on the full history, then cut to the range', () => {
  // 1 December 2025 to 10 January 2026: 41 days, revenue 1, 2, ... 41.
  const dates = span('2025-12-01', '2026-01-10');
  const revenueK = dates.map((_, i) => i + 1);
  const or = {
    dates,
    providers: [
      { slug: 'openai', name: 'OpenAI', revenue_k: revenueK, tokens_b: revenueK.map((v) => v / 10) },
      { slug: 'x-ai', name: 'xAI', revenue_k: dates.map(() => null), tokens_b: dates.map(() => null) },
    ],
    default_slugs: ['openai'],
  };
  // 1M cuts at 10 December (index 9). Its window reaches back to 4 December: mean of 4 to 10.
  const daily = M.openrouterSeries(or, { metric: 'revenue', mode: 'DAILY', range: '1M' });
  assert.equal(daily.labels.length, 32);
  assert.equal(daily.labels[0], '2025-12-10');
  assert.equal(daily.series[0].name, 'OpenAI');
  assert.equal(daily.series[0].index, 0);
  assert.equal(daily.series[0].values[0], 7);
  assert.equal(daily.series[0].values[6], 13);   // the 16th: mean of 10 to 16
  assert.ok(daily.series[1].values.every((v) => v === null));
  assert.ok(daily.series[1].partial.every((p) => p === false));
});

test('openrouterSeries: monthly values are the run-rate per month, partial months flagged', () => {
  const dates = span('2025-12-01', '2026-01-10');
  const revenueK = dates.map((_, i) => i + 1);
  const or = {
    dates,
    providers: [
      { slug: 'openai', name: 'OpenAI', revenue_k: revenueK, tokens_b: revenueK.map((v) => v / 10) },
      { slug: 'x-ai', name: 'xAI', revenue_k: dates.map(() => null), tokens_b: dates.map(() => null) },
    ],
    default_slugs: ['openai'],
  };
  const arr = M.openrouterSeries(or, { metric: 'revenue', mode: 'MONTHLY', range: '1M' });
  assert.deepEqual(arr.labels, ['2025-12', '2026-01']);
  near(arr.series[0].values[0], 5.84);       // December: mean 16 (1 to 31) x 365 / 1000
  near(arr.series[0].values[1], 13.3225);    // January: mean 36.5 (32 to 41) x 365 / 1000
  assert.deepEqual(arr.series[0].partial, [false, true]);
  assert.deepEqual(arr.series[1].values, [null, null]);
  assert.deepEqual(arr.series[1].partial, [true, true]);

  const tokens = M.openrouterSeries(or, { metric: 'tokens', mode: 'MONTHLY', range: '1M' });
  near(tokens.series[0].values[0], 1.6);
  near(tokens.series[0].values[1], 3.65);
});

test('openrouterSeries tolerates a build with no providers or no dates', () => {
  assert.deepEqual(M.openrouterSeries({}, { metric: 'revenue', mode: 'DAILY', range: '6M' }), { labels: [], series: [] });
  assert.deepEqual(M.openrouterSeries({ dates: [] , providers: []}, { metric: 'tokens', mode: 'MONTHLY' }), { labels: [], series: [] });
});

test('openrouterSeries: the all-authors total comes last, smoothed and run-rated like the providers', () => {
  const dates = span('2025-12-01', '2026-01-10');
  const revenueK = dates.map((_, i) => i + 1);
  const or = {
    dates,
    providers: [{ slug: 'openai', name: 'OpenAI', revenue_k: revenueK, tokens_b: revenueK.map((v) => v / 10) }],
    // Every author, so more than the providers drawn.
    total_revenue_k: revenueK.map((v) => v * 2),
    total_tokens_b: revenueK.map((v) => v / 5),
  };
  const daily = M.openrouterSeries(or, { metric: 'revenue', mode: 'DAILY', range: '1M' });
  const total = daily.series.at(-1);
  assert.equal(total.name, M.TOTAL_NAME);
  assert.equal(total.slug, M.TOTAL_SLUG);
  assert.ok(total.total && !daily.series[0].total);
  assert.equal(total.index, 1);
  assert.equal(total.values[0], 14);                 // twice OpenAI's 7
  const tokens = M.openrouterSeries(or, { metric: 'tokens', mode: 'MONTHLY' });
  near(tokens.series.at(-1).values[0], 3.2);         // twice OpenAI's 1.6
  // A build without totals draws the providers alone.
  delete or.total_revenue_k;
  assert.equal(M.openrouterSeries(or, { metric: 'revenue', mode: 'DAILY', range: '1M' }).series.length, 1);
});
