import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MIN_POINTS,
  ordinal,
  percentileOf,
  percentileText,
  rollingPercentile,
  rollingPoints,
  stocksBondsCard,
  stocksBondsModel,
  stocksBondsSummary,
  toneFor,
  wordFor,
} from '../../web/js/stocks-bonds.js';

test('percentile is the share of finite values at or below the latest, latest included', () => {
  assert.equal(percentileOf([1, 2, 3, 4], 3), 75);
  assert.equal(percentileOf([1, null, 2, undefined, 3, 4], 1), 25);
  assert.equal(percentileOf([5, 6], 1), 0);
});

test('percentile is null when there is nothing to rank against', () => {
  assert.equal(percentileOf([], 1), null);
  assert.equal(percentileOf([null, null], 1), null);
  assert.equal(percentileOf([1, 2], null), null);
  assert.equal(percentileOf([1, 2], Number.NaN), null);
});

test('word mapping: each cut-off belongs to the word named at it', () => {
  assert.equal(wordFor(0), 'very dear');
  assert.equal(wordFor(10), 'very dear');
  assert.equal(wordFor(10.01), 'dear');
  assert.equal(wordFor(25), 'dear');
  assert.equal(wordFor(25.01), 'middle');
  assert.equal(wordFor(74.99), 'middle');
  assert.equal(wordFor(75), 'cheap');
  assert.equal(wordFor(89.99), 'cheap');
  assert.equal(wordFor(90), 'very cheap');
  assert.equal(wordFor(100), 'very cheap');
  assert.equal(wordFor(null), null);
});

test('tone groups the words into dear, cheap and middle', () => {
  assert.equal(toneFor('very dear'), 'dear');
  assert.equal(toneFor('dear'), 'dear');
  assert.equal(toneFor('very cheap'), 'cheap');
  assert.equal(toneFor('cheap'), 'cheap');
  assert.equal(toneFor('middle'), 'middle');
  assert.equal(toneFor(null), null);
});

test('rolling percentile keeps nulls and ranks only once the window holds the minimum', () => {
  const out = rollingPercentile([1, null, 2, 3], 2);
  assert.deepEqual(out, [null, null, 100, 100]);
  assert.equal(rollingPercentile([1, 2], MIN_POINTS).every((v) => v === null), true);
});

test('rolling percentile is expanding: a reading uses only the values up to its own date', () => {
  // The value at index 0 is unaffected by the later values.
  const short = rollingPercentile([1, 2], 1);
  const long = rollingPercentile([1, 2, 9, -5], 1);
  assert.equal(short[0], long[0]);
  assert.equal(short[1], long[1]);
  // The first reading is its own whole window: 100. A later low value ranks at the bottom.
  assert.deepEqual(rollingPercentile([1, 2, 3, 0], 1), [100, 100, 100, 25]);
  assert.deepEqual(rollingPercentile([5, 1], 1), [100, 50]);
});

test('rolling points pair dates with ranks, starting once the window is full, and drop nulls', () => {
  // Rising values with one gap at index 55: the ranks sit at the top. The
  // window first holds 52 values at index 51.
  const dates = Array.from({ length: 60 }, (_, i) => `d${i}`);
  const values = Array.from({ length: 60 }, (_, i) => (i === 55 ? null : i));
  const points = rollingPoints(dates, values);
  assert.equal(points.length, 8);
  assert.equal(points[0][0], 'd51');
  assert.equal(points.some(([d]) => d === 'd55'), false);
  assert.ok(points.every(([, rank]) => rank === 100));
});

test('ordinal and percentile text: whole numbers with the right suffix, and the span named', () => {
  assert.equal(ordinal(1), '1st');
  assert.equal(ordinal(2), '2nd');
  assert.equal(ordinal(3), '3rd');
  assert.equal(ordinal(11), '11th');
  assert.equal(ordinal(12), '12th');
  assert.equal(ordinal(21), '21st');
  assert.equal(ordinal(1.72), '2nd');
  assert.equal(percentileText({ percentile: 12.4, span: '2016' }), '12th pct since 2016');
  assert.equal(percentileText({ percentile: null, span: '2016' }), '—');
});

test('summary counts the measures in the dearest quarter, and never averages', () => {
  const m = (percentile) => ({ percentile });
  assert.equal(
    stocksBondsSummary([m(1.7), m(0), m(10), m(60)]),
    '3 of 4 measures put stocks in the dearest quarter of their history vs bonds',
  );
  assert.equal(
    stocksBondsSummary([m(80), m(50), m(20)]),
    '1 of 3 measures put stocks in the dearest quarter of their history vs bonds',
  );
  assert.equal(
    stocksBondsSummary([m(10)]),
    '1 of 1 measure put stocks in the dearest quarter of their history vs bonds',
  );
  assert.equal(stocksBondsSummary([m(null), m(undefined)]), null);
  assert.equal(stocksBondsSummary([]), null);
});

const dates = ['2016-10-28', '2016-11-04', '2016-11-11'];
const fixture = {
  sections: [{
    tiles: [
      {
        key: 'ecy', value: 0.86, date: '2026-10-22', pct_long: 10, since: '1962-01-02',
        history: { dates, values: [0.5, 0.9, 0.86] },
      },
      {
        key: 'erp_damodaran', value: 3.7, date: '2026-10-01', pct_long: 0, since: '2008-09-01',
        history: { dates, values: [4, 5, 3.7] },
      },
    ],
  }],
  context: {
    fed_model: {
      as_of: '2026-10-23',
      dates,
      indices: [
        {
          key: 'SPX',
          operating: {
            spread_real10y_pct: 0.7672, spread_real10y_percentile: 1.7241,
            spread_baa_pct: -3.0128, spread_baa_percentile: 3.6398,
            history: { spread_real10y_pct: [1, 2, 0.7672], spread_baa_pct: [-1, -2, -3.0128] },
          },
        },
        {
          key: 'NDX',
          operating: {
            spread_real10y_pct: 0.087, spread_real10y_percentile: 2.1073,
            spread_baa_pct: -3.693, spread_baa_percentile: 5.5556,
            history: { spread_real10y_pct: [0.1, 0.2, 0.087], spread_baa_pct: [-3, -3.5, -3.693] },
          },
        },
      ],
    },
  },
};

test('model: four measures, provided percentiles used, tiles ranked over their full span', () => {
  const model = stocksBondsModel(fixture);
  assert.deepEqual(model.measures.map((m) => m.key), ['real', 'erp', 'ecy', 'credit']);
  const [real, erp, ecy, credit] = model.measures;
  assert.equal(real.percentile, 1.7241);
  assert.equal(real.word, 'very dear');
  assert.equal(real.span, '2016');
  assert.equal(credit.percentile, 3.6398);
  assert.equal(erp.percentile, 0);
  assert.equal(erp.span, '2008');
  assert.equal(ecy.percentile, 10);
  assert.equal(ecy.word, 'very dear');
  assert.equal(ecy.span, '1962');
  assert.equal(model.summary, '4 of 4 measures put stocks in the dearest quarter of their history vs bonds');
});

test('model: the NDX switch changes only the two fed-model measures', () => {
  const model = stocksBondsModel(fixture, 'NDX');
  const [real, erp, ecy, credit] = model.measures;
  assert.equal(real.value, 0.087);
  assert.equal(real.scope, 'NDX');
  assert.equal(credit.value, -3.693);
  assert.equal(erp.scope, 'SPX');
  assert.equal(erp.value, 3.7);
  assert.equal(ecy.value, 0.86);
});

test('model: a measure whose source is missing is kept as an empty entry, not dropped', () => {
  const model = stocksBondsModel({ sections: fixture.sections });
  assert.equal(model.measures.length, 4);
  assert.equal(model.measures[0].value, null);
  assert.equal(model.measures[0].points.length, 0);
  assert.equal(model.measures[1].value, 3.7);
});

test('card returns null with no fed_model and no tiles, before any DOM work', () => {
  assert.equal(stocksBondsCard(undefined), null);
  assert.equal(stocksBondsCard(null), null);
  assert.equal(stocksBondsCard({}), null);
  assert.equal(stocksBondsCard({ sections: [{ tiles: [] }], context: {} }), null);
  assert.equal(stocksBondsModel({ context: {}, sections: [] }), null);
});
