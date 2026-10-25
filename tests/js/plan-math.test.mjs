import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  breakevenHeadline, planFileName, planMarkdown, planOutcomes, planSensitivity, planToJson,
  journalSummary, readPlanFile, readReviews, reviewMarkdown, reviewResult, reviewToJson, toNumber,
} from '../../web/js/plan-math.js';

const near = (actual, expected, eps = 1e-9) => assert.ok(Math.abs(actual - expected) < eps, `${actual} != ${expected}`);

// Long SPY-like plan: entry 100, stop 95 (R = 5), target 110 (gain 10).
const long = (extra = {}) => ({ side: 'long', entry: 100, stop: 95, target: 110, horizon: 10,
  commission: 0, slippageBps: 0, pTarget: 0.4, pStop: 0.4, pTime: 0.2, ...extra });

test('blank is not entered and text is NaN, never zero', () => {
  assert.equal(toNumber(''), null);
  assert.equal(toNumber('   '), null);
  assert.equal(toNumber(null), null);
  assert.equal(toNumber(' 2.5 '), 2.5);
  assert.ok(Number.isNaN(toNumber('abc')));
});

test('long without costs: gains, losses, reward:risk and breakevens by hand', () => {
  const m = planOutcomes(long());
  assert.equal(m.ok, true);
  assert.deepEqual(m.errors, []);
  near(m.riskPerShare, 5);
  near(m.target.grossPerShare, 10);
  near(m.target.netPerShare, 10);
  near(m.target.grossPct, 10);
  near(m.stop.grossPerShare, -5);
  near(m.stop.netPerShare, -5);
  near(m.stop.netPct, -5);
  near(m.time.netPerShare, 0);
  near(m.rewardRisk, 2);
  // p* = L / (G + L) = 5 / 15, the time exit ignored.
  near(m.breakevenSuccess, 1 / 3);
  // With a 20% horizon-end share and zero horizon return, the target share among resolved trades is 1/3,
  // so the target success rate needed is 0.8 x 1/3 = 0.2667.
  near(m.breakevenWithTime.targetShare, 1 / 3);
  near(m.breakevenWithTime.successRate, 0.8 / 3);
  assert.equal(m.breakevenWithTime.feasible, true);
  // EV = 0.4 x 10 - 0.4 x 5 + 0.2 x 0 = 2 per share = 0.4 R.
  near(m.expected.perShare, 2);
  near(m.expected.r, 0.4);
  assert.equal(m.expected.position, null);
  assert.equal(planOutcomes(long({ shares: 100 })).expected.position, 200);
});

test('costs: commission per side and slippage on each leg, worked for a long', () => {
  // c = $0.01 per share per side, s = 10 bps. Round trip exiting at X: 0.02 + 0.001 x (100 + X).
  // Target (X=110): cost 0.23, so G_net = 10 - 0.23 = 9.77.
  // Stop (X=95): cost 0.215, so L_net = 5 + 0.215 = 5.215.
  const m = planOutcomes(long({ commission: 0.01, slippageBps: 10 }));
  near(m.target.costPerShare, 0.23);
  near(m.target.netPerShare, 9.77);
  near(m.target.netPct, 9.77);
  near(m.stop.costPerShare, 0.215);
  near(m.stop.netPerShare, -5.215);
  near(m.rewardRisk, 9.77 / 5.215);
  near(m.breakevenSuccess, 5.215 / 14.985);
  near(m.breakevenSuccess, 0.3480147, 1e-6);
  // EV = 0.4 x 9.77 - 0.4 x 5.215 = 1.822 ... with the time share at 0.2 and a zero return the time leg costs 0.22.
  // 0.4 x 9.77 - 0.4 x 5.215 + 0.2 x (-0.22) = 1.822 - 0.044 = 1.778.
  near(m.expected.perShare, 1.778);
  near(m.expected.r, 1.778 / 5);
});

test('the horizon-end return is a position return and the time exit is priced at its own exit', () => {
  // Long, r = +5%, c = $0.01, s = 10 bps, weights 30 / 50 / 20.
  // Exit at 105: gross 5, cost 0.02 + 0.001 x 205 = 0.225, so M_net = 4.775.
  const m = planOutcomes(long({ commission: 0.01, slippageBps: 10, timeReturnPct: 5, pTarget: 0.3, pStop: 0.5, pTime: 0.2 }));
  near(m.time.exit, 105);
  near(m.time.grossPerShare, 5);
  near(m.time.costPerShare, 0.225);
  near(m.time.netPerShare, 4.775);
  near(m.time.returnPct, 5);
  // EV = 0.3 x 9.77 - 0.5 x 5.215 + 0.2 x 4.775 = 2.931 - 2.6075 + 0.955 = 1.2785.
  near(m.expected.perShare, 1.2785);
  near(m.expected.r, 1.2785 / 5);
  // With the horizon share fixed, the success rate that makes EV zero is p = (1 - p_t) q, q from the formula.
  const p = m.breakevenWithTime.successRate;
  near(m.breakevenWithTime.targetShare, (5.215 - 0.2 * 4.775 / 0.8) / 14.985);
  near(p * 9.77 - (0.8 - p) * 5.215 + 0.2 * 4.775, 0, 1e-9);
});

test('a short mirrors the long: stop above entry, target below, gains when the price falls', () => {
  // Entry 100, stop 105 (R = 5), target 90 (gain 10); return +5% means the price falls to 95.
  const m = planOutcomes({ side: 'short', entry: 100, stop: 105, target: 90, horizon: 5,
    commission: 0, slippageBps: 0, timeReturnPct: 5, pTarget: 0.5, pStop: 0.5, pTime: 0 });
  assert.equal(m.ok, true);
  near(m.target.grossPerShare, 10);
  near(m.stop.grossPerShare, -5);
  near(m.time.exit, 95);
  near(m.time.grossPerShare, 5);
  near(m.rewardRisk, 2);
  near(m.breakevenSuccess, 1 / 3);
  // Zero horizon share: the time-exit breakeven equals the plain one.
  near(m.breakevenWithTime.successRate, 1 / 3);
  // EV = 0.5 x 10 - 0.5 x 5 = 2.5 per share, 0.5 R.
  near(m.expected.r, 0.5);
});

test('validation: wrong-side stops and targets, non-positive prices, horizon, shares and costs', () => {
  const stopAbove = planOutcomes({ ...long(), stop: 102 });
  assert.equal(stopAbove.ok, false);
  assert.ok(stopAbove.errors.some((e) => e.includes('stop must sit below')));
  assert.equal(stopAbove.riskPerShare, null);

  const targetBelow = planOutcomes({ ...long(), target: 99 });
  assert.ok(targetBelow.errors.some((e) => e.includes('target must sit above')));

  const shortTargetAbove = planOutcomes({ side: 'short', entry: 100, stop: 105, target: 101, horizon: 5 });
  assert.ok(shortTargetAbove.errors.some((e) => e.includes('target must sit below')));

  assert.ok(planOutcomes({ ...long(), entry: 0 }).errors.some((e) => e.includes('positive prices')));
  assert.ok(planOutcomes({ ...long(), entry: '' }).errors.some((e) => e.includes('positive prices')));
  assert.ok(planOutcomes({ ...long(), horizon: 0 }).errors.some((e) => e.includes('Horizon')));
  assert.ok(planOutcomes({ ...long(), shares: 1.5 }).errors.some((e) => e.includes('Shares')));
  assert.ok(planOutcomes({ ...long(), commission: -0.01 }).errors.some((e) => e.includes('Commission')));
  assert.ok(planOutcomes({ ...long(), commission: '' }).errors.some((e) => e.includes('Commission')));
  assert.ok(planOutcomes({ ...long(), timeReturnPct: -100 }).errors.some((e) => e.includes('zero or below')));
  // Slippage of 100% of the price per side leaves no room between stop and target.
  assert.ok(planOutcomes({ ...long(), slippageBps: 10000 }).errors.some((e) => e.includes('no room')));
});

test('validation: weights must sum to 1, and are optional only as a set', () => {
  const off = planOutcomes({ ...long(), pTarget: 0.5, pStop: 0.4, pTime: 0.2 });
  assert.equal(off.ok, false);
  assert.ok(off.errors.some((e) => e.includes('sum to 100%') && e.includes('110.0%')));
  // The price outputs stay, the expected value does not.
  near(off.target.netPerShare, 10);
  assert.equal(off.expected, null);
  assert.equal(off.breakevenWithTime, null);

  const partial = planOutcomes({ ...long(), pTime: '' });
  assert.ok(partial.errors.some((e) => e.includes('Enter all three')));

  const blank = planOutcomes({ ...long(), pTarget: '', pStop: '', pTime: '' });
  assert.equal(blank.ok, true);
  assert.equal(blank.expected, null);
  assert.equal(blank.breakevenWithTime, null);
  near(blank.breakevenSuccess, 1 / 3);
});

test('breakeven with the horizon end: out of reach when even every target hit loses', () => {
  // Target 101 (gain 1), costs $0.60 a side: G_net = 1 - 1.2 = -0.2, L_net = 5 + 1.2 = 6.2.
  const m = planOutcomes({ ...long({ commission: 0.6, pTarget: 0.5, pStop: 0.5, pTime: 0 }), target: 101 });
  assert.ok(m.breakevenSuccess > 1);
  near(m.breakevenSuccess, 6.2 / 6);
  assert.match(breakevenHeadline(m.breakevenSuccess), /^Out of reach/);
  assert.equal(breakevenHeadline(null), null);
  assert.equal(breakevenHeadline(0.38), 'Success rate needed to break even: 38.0% — does your evidence support at least that?');
});

test('the sensitivity grid turns from negative to positive, with missing combinations left null', () => {
  const s = planSensitivity(long());
  assert.equal(s.rates.length, 19);
  const m1 = s.rows.find((r) => r.multiple === 1);
  const at = (rate) => m1.cells[s.rates.findIndex((r) => Math.abs(r - rate) < 1e-9)];
  // With the horizon share at 0.2, EV in R at target distance 1 is (15p - 4) / 5.
  near(at(0.25), -0.05);
  near(at(0.3), 0.1);
  near(at(0.4), 0.4);
  near(at(0.8), 1.6);
  // A success rate of 85% leaves -5% for the stop once the 20% horizon share is taken: no such cell.
  assert.equal(at(0.85), null);
  assert.equal(at(0.95), null);
  // The breakeven success rate with the horizon share is where the row crosses zero, 4/15 = 26.7%.
  assert.ok(at(0.25) < 0 && at(0.3) > 0);
  near(m1.breakevenSuccess, 5 / 15);
  // A 2x target gains 20: EV = (25p - 4) / 5 in R, zero at 16%, so 15% is -0.05 R and 20% is +0.2 R.
  const m2 = s.rows.find((r) => r.multiple === 2);
  near(m2.target, 120);
  near(m2.cells[s.rates.findIndex((r) => Math.abs(r - 0.15) < 1e-9)], -0.05);
  near(m2.cells[s.rates.findIndex((r) => Math.abs(r - 0.2) < 1e-9)], 0.2);
});

test('the sensitivity cell at the user point equals the expected value on the card', () => {
  const input = long({ commission: 0.01, slippageBps: 10 });
  const s = planSensitivity(input);
  const base = planOutcomes(input);
  const cell = s.rows.find((r) => r.multiple === 1).cells[s.rates.findIndex((r) => Math.abs(r - 0.4) < 1e-9)];
  near(cell, base.expected.r, 1e-12);
});

test('the sensitivity is null for an invalid plan and uses a zero horizon share when weights are blank', () => {
  assert.equal(planSensitivity({ ...long(), stop: 102 }), null);
  assert.equal(planSensitivity({ ...long(), pTarget: 0.9 }), null);
  const blank = planSensitivity({ ...long(), pTarget: '', pStop: '', pTime: '' });
  // Horizon share zero: the 95% row is feasible and the stop share is 0.05 x 5 = 0.25 of loss.
  const m1 = blank.rows.find((r) => r.multiple === 1);
  near(m1.cells[blank.rates.findIndex((r) => Math.abs(r - 0.95) < 1e-9)], (9.5 - 0.25) / 5);
});

test('plan/v1 round trip: JSON out and back in gives the same review R', () => {
  const input = long({ shares: 100, commission: 0.01, slippageBps: 10 });
  const plan = planToJson({ ticker: 'SPY', created: '2026-10-25T14:00:00.000Z', dataAsOf: '2026-10-23', input,
    thesis: { why: 'pullback to the 20-day average', evidence: 'none tested', whatWouldProveWrong: 'a close below 95' } });
  const text = JSON.stringify(plan);
  const back = readPlanFile(JSON.parse(text));
  assert.equal(back.ok, true);
  assert.equal(back.plan.ticker, 'SPY');
  assert.equal(back.plan.dataAsOf, '2026-10-23');
  assert.equal(back.plan.thesis.whatWouldProveWrong, 'a close below 95');
  assert.equal(back.plan.input.shares, 100);
  assert.deepEqual(planOutcomes(back.plan.input).expected, planOutcomes(input).expected);
  assert.equal(JSON.parse(text).review && Object.keys(JSON.parse(text).review).length, 0);

  // Long, 100 shares: fills 100.5 in and 104 out, costs $30 in total.
  // Per share (104 - 100.5) - 30/100 = 3.2; R = 3.2 / 5 = 0.64; total 320.
  const review = reviewResult({ side: back.plan.input.side, plannedEntry: back.plan.input.entry,
    plannedStop: back.plan.input.stop, actualEntry: 100.5, actualExit: 104, shares: 100, costs: 30 });
  near(review.realisedPerShare, 3.2);
  near(review.r, 0.64);
  near(review.realisedTotal, 320);

  const out = reviewToJson({ plan: back.plan, created: '2026-10-30T10:00:00.000Z',
    actual: { entry: 100.5, exit: 104, shares: 100, costs: 30 }, followedPlan: 'partly',
    whatChanged: 'sold half at 103', thesisOutcome: 'supported' });
  near(out.result.r, 0.64);
  assert.equal(out.schema, 'review/v1');
  assert.equal(out.execution.followed_plan, 'partly');
});

test('a plan file that is not plan/v1, or whose inputs no longer validate, is refused', () => {
  assert.equal(readPlanFile({ schema: 'plan/v0' }).ok, false);
  assert.equal(readPlanFile(null).ok, false);
  const plan = planToJson({ ticker: 'SPY', created: 'x', input: long() });
  plan.inputs.stop = 105;
  const refused = readPlanFile(JSON.parse(JSON.stringify(plan)));
  assert.equal(refused.ok, false);
  assert.match(refused.error, /stop must sit below/);
});

test('a short review: a fall from 100 to 97 with a planned stop at 105 is +0.6 R', () => {
  const review = reviewResult({ side: 'short', plannedEntry: 100, plannedStop: 105, actualEntry: 100, actualExit: 97 });
  near(review.realisedPerShare, 3);
  near(review.r, 0.6);
  assert.equal(reviewResult({ side: 'long', plannedEntry: 100, plannedStop: 95, actualEntry: 100, actualExit: 99, costs: null }), null);
  assert.equal(reviewResult({ side: 'long', plannedEntry: 100, plannedStop: 95, actualEntry: 100, actualExit: 99, costs: -1 }), null);
});

test('file names use the local calendar date, and the Markdown carries no bad figures', () => {
  assert.equal(planFileName('plan', 'SPY', new Date(2026, 9, 25, 12).toISOString()), 'plan-SPY-2026-10-25.json');
  const plan = planToJson({ ticker: 'SPY', created: '2026-10-25T14:00:00.000Z', dataAsOf: '2026-10-23',
    input: long({ commission: 0.01, slippageBps: 10, shares: 100 }), thesis: { why: 'w' } });
  const md = planMarkdown(JSON.parse(JSON.stringify(plan)));
  assert.match(md, /Horizon ends, neither hit/);
  assert.match(md, /Expected value from your weights/);
  assert.doesNotMatch(md, /NaN|undefined|null|\[object Object\]/);
  const blank = planToJson({ ticker: 'SPY', created: 'x', input: { side: 'long' } });
  assert.match(planMarkdown(blank), /No valid outputs/);
  assert.match(reviewMarkdown({ ticker: 'SPY', plan_created: 'a', created: 'b', result: null,
    execution: { followed_plan: null, what_changed: '' }, judgement: { thesis_outcome: null } }), /No result/);
});

test('the journal reads review files in date order and keeps execution and judgement apart', () => {
  const review = (created, r, followed, thesis) => ({ schema: 'review/v1', ticker: 'NVDA', created, result: { r },
    execution: { followed_plan: followed }, judgement: { thesis_outcome: thesis } });
  const { rows, skipped } = readReviews([
    review('2026-03-01', -1, 'no', 'refuted'), review('2026-01-01', 2, 'yes', 'supported'),
    review('2026-02-01', -1, 'yes', 'supported'), { schema: 'plan/v1' }, review('2026-04-01', null, 'yes', null),
  ]);
  assert.equal(skipped, 2);
  assert.deepEqual(rows.map((x) => x.r), [2, -1, -1]);
  const s = journalSummary(rows);
  assert.equal(s.n, 3);
  assert.ok(Math.abs(s.winRate - 1 / 3) < 1e-12);
  assert.equal(s.expectancy, 0);
  assert.deepEqual(s.cumulative, [2, 1, 0]);
  assert.equal(s.maxDrawdown, -2);
  assert.deepEqual(s.byFollowed.yes, { n: 2, mean: 0.5 });
  assert.deepEqual(s.byFollowed.no, { n: 1, mean: -1 });
  assert.equal(s.byThesis.refuted.mean, -1);
  assert.equal(journalSummary([]), null);
});
