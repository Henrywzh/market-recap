import test from 'node:test';
import assert from 'node:assert/strict';
import { surpriseState, heatCell, historyMonths, contributionSteps, aiCoverage } from '../../web/js/cpi-model.js';
import { weightWidth, recordConsensus, recordCalendarFetched } from '../../web/js/inflation-ui.js';

test('official weight bars use the same 0–100 scale and never turn missing into zero', () => {
  assert.equal(weightWidth(100), 100);
  assert.equal(weightWidth(35.6), 35.6);
  assert.equal(weightWidth(0), 0);
  for (const value of [null, undefined, NaN, Infinity, -1, 100.01, '35']) assert.equal(weightWidth(value), null);
});

test('surprise is directional inflation news, not an automatic equity return signal', () => {
  assert.equal(surpriseState(null).label, 'NO CONSENSUS');
  assert.equal(surpriseState(0).label, 'IN LINE');
  assert.equal(surpriseState(.1).label, 'ABOVE CONSENSUS');
  assert.equal(surpriseState(-.1).label, 'BELOW CONSENSUS');
});

test('heatmap preserves missing and zero, scales raw moves separately from percentiles', () => {
  assert.equal(heatCell({ mom: null }, 'mom').value, null);
  assert.equal(heatCell({ mom: 0 }, 'mom').value, 0);
  assert.equal(heatCell({ mom: -.2 }, 'mom').warm, false);
  assert.equal(heatCell({ percentile: 100 }, 'percentile').strength, 1);
  assert.equal(heatCell({ percentile: 50 }, 'percentile').strength, 0);
  assert.deepEqual(historyMonths([{ history: { observations: [{ month: '2026-07' }, { month: '2026-09' }] } },
    { history: { observations: [{ month: '2026-08' }] } }], 2), ['2026-08', '2026-09']);
});

test('official effects reconcile transparently, without adding parents to their children', () => {
  const data = { components: [
    { key: 'food', label: 'Food', effect_pp: .006 }, { key: 'energy', label: 'Energy', effect_pp: .377 },
    { key: 'core', label: 'Core', effect_pp: .265 }, { key: 'shelter', label: 'Shelter', effect_pp: .138 },
  ], contributions: { keys: ['food', 'energy', 'core'], residual_pp: -.048, headline_mom: .6 } };
  const steps = contributionSteps(data);
  assert.equal(steps.length, 5);
  assert.ok(Math.abs(steps.at(-2).after - .6) < 1e-10);
  assert.ok(!steps.some((s) => s.label === 'Shelter'));
  assert.equal(steps[3].official, false);
  assert.equal(steps[3].label, 'Rounding');
  assert.equal(steps[4].label, 'Headline');
  assert.deepEqual(contributionSteps({ ...data, contributions: { ...data.contributions, residual_pp: null } }), []);
});

test('negative effects and negative headlines retain their true start and end', () => {
  const steps = contributionSteps({ components: [{ key: 'energy', label: 'Energy', effect_pp: -.3 }],
    contributions: { keys: ['energy'], residual_pp: .1, headline_mom: -.2 } });
  assert.equal(steps[0].base, -.3);
  assert.equal(steps[0].height, .3);
  assert.equal(steps.at(-1).base, -.2);
});

const effects = [
  { key: 'food', label: 'Food', effect_pp: .006 }, { key: 'energy', label: 'Energy', effect_pp: .377 },
  { key: 'core', label: 'Core', effect_pp: .265 },
];

test('with the unrounded index, the last bar is the index change and the bridge is aggregation', () => {
  const steps = contributionSteps({ components: effects, contributions: { keys: ['food', 'energy', 'core'],
    headline_mom: .6, residual_pp: -.048, headline_mom_index: .648 + .012, residual_index_pp: .012 } });
  assert.deepEqual(steps.map((s) => s.label), ['Food', 'Energy', 'Core', 'Aggregation', 'Headline (index)']);
  assert.equal(steps[3].bridge, 'aggregation');
  assert.equal(steps[3].official, false);
  assert.equal(steps.at(-1).indexed, true);
  assert.ok(Math.abs(steps.at(-1).after - .66) < 1e-10);
  assert.ok(Math.abs(steps[3].value - .012) < 1e-10);
});

test('the rounded headline is not the bar once the unrounded index is present', () => {
  const steps = contributionSteps({ components: effects, contributions: { keys: ['food', 'energy', 'core'],
    headline_mom: .6, residual_pp: -.048, headline_mom_index: .66, residual_index_pp: .012 } });
  assert.equal(steps.at(-1).value, .66);
  assert.notEqual(steps.at(-1).value, .6);
});

test('an incomplete index pair falls back to the rounded bridge, not a mixed one', () => {
  const steps = contributionSteps({ components: effects, contributions: { keys: ['food', 'energy', 'core'],
    headline_mom: .6, residual_pp: -.048, headline_mom_index: .66, residual_index_pp: null } });
  assert.equal(steps[3].label, 'Rounding');
  assert.equal(steps.at(-1).label, 'Headline');
  assert.equal(steps.at(-1).value, .6);
  assert.equal(steps.at(-1).indexed, false);
});

test('the index bridge does not need the rounded headline, and absent data stays absent', () => {
  const steps = contributionSteps({ components: effects, contributions: { keys: ['food', 'energy', 'core'],
    headline_mom: null, residual_pp: null, headline_mom_index: .66, residual_index_pp: .012 } });
  assert.equal(steps.at(-1).label, 'Headline (index)');
  assert.deepEqual(contributionSteps({ components: effects, contributions: { keys: ['food'], residual_pp: null } }), []);
  assert.deepEqual(contributionSteps({ components: effects }), []);
  assert.deepEqual(contributionSteps({}), []);
});

test('PPI pending on release day is expected coverage, not a failure', () => {
  const series = [{ status: 'ok' }, { status: 'pending' }, { status: 'pending' }, { status: 'ok' }, { status: 'pending' }];
  const expected = aiCoverage({ month: '2026-09', ai_pending_expected: true, ai_series: series });
  assert.equal(expected.expected, true);
  assert.equal(expected.text, 'Release day: FRED usually posts these industry series a day after BLS · 2/5 updated');
  const plain = aiCoverage({ month: '2026-09', ai_series: series });
  assert.equal(plain.expected, false);
  assert.equal(plain.text, '2/5 series updated through 2026-09 · BLS via FRED · monthly NSA');
  assert.equal(aiCoverage({ month: '2026-09', ai_pending_expected: true, ai_series: [{ status: 'ok' }] }).expected, false);
});

test('release history reads consensus from the calendar list first, then from old comparisons', () => {
  const legacy = { consensus_retrieved_at: '2026-10-15T13:51Z', values: { comparisons: [{ key: 'headline', consensus: .3 }] } };
  assert.equal(recordConsensus(legacy, { key: 'headline', consensus: .3 }), .3);
  assert.equal(recordCalendarFetched(legacy, { key: 'headline' }), '2026-10-15T13:51Z');
  const version = { consensus_retrieved_at: 'record', calendar: [{ key: 'headline', consensus: .2, consensus_retrieved_at: 'entry' }] };
  assert.equal(recordConsensus(version, { key: 'headline', consensus: .3 }), .2);
  assert.equal(recordCalendarFetched(version, { key: 'headline' }), 'entry');
  assert.equal(recordConsensus(version, { key: 'core', consensus: .3 }), .3);
  assert.equal(recordConsensus({ calendar: [{ key: 'headline', consensus: null }] }, { key: 'headline', consensus: .3 }), null);
  assert.equal(recordCalendarFetched({}, { key: 'headline' }), null);
});
