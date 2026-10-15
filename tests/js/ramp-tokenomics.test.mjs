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
