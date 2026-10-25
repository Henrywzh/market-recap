// Trade plan arithmetic: what a planned trade depends on, priced after costs,
// and what the user's own scenario weights make of it. Pure and DOM-free. Every
// input is an assumption the user typed: nothing here is a forecast, a
// historical hit rate or a recommendation, and nothing is fetched or stored.

export const PLAN_SCHEMA = 'plan/v1';
export const REVIEW_SCHEMA = 'review/v1';

// Success rates 5%..95% and target distances as multiples of the entered target.
export const DEFAULT_RATES = Array.from({ length: 19 }, (_, i) => (i + 1) / 20);
export const DEFAULT_MULTIPLES = [0.5, 0.75, 1, 1.25, 1.5, 2];

// Units. Prices in dollars. Commission in $ per share per side. Slippage in
// basis points of the price on each leg. Weights as fractions (0.4 = 40%).
// The horizon-end return in percent of entry. R is the initial risk per
// share, |entry - stop|, before costs: the unit every result is read in.

// Blank means "not entered" (null), never zero. Text that is not a number is NaN.
export function toNumber(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string' && value.trim() === '') return null;
  return typeof value === 'number' ? value : Number(String(value).trim());
}

const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const price = (v) => finite(v) && v > 0;
const nonNegative = (v) => finite(v) && v >= 0;

// A round trip that exits at X costs 2 x commission + slippage x (entry + X):
// the entry leg and the exit leg each pay the slippage on their own price.
const roundTrip = (exit, entry, commission, slippageBps) => 2 * commission + (slippageBps / 1e4) * (entry + exit);

const EMPTY = { riskPerShare: null, entry: null, side: null, target: null, stop: null, time: null,
  rewardRisk: null, breakevenSuccess: null, breakevenWithTime: null, weights: null, expected: null };

// The plan's numbers. `ok` is false whenever `errors` is not empty; outputs are
// null until the prices, side, horizon and costs validate, and the expected
// value is null until the weights are entered and valid.
//
// Per share, a target hit earns G = d(T - E) and a stop hit loses L = d(E - S)
// = R, where d = +1 long and -1 short. Net of costs: G_net = G - cost(T) and
// L_net = L + cost(S). The horizon end pays M = E r - cost(E(1 + d r)), with r
// the position return.
export function planOutcomes(input = {}) {
  const side = input.side;
  const d = side === 'short' ? -1 : 1;
  const entry = toNumber(input.entry);
  const stop = toNumber(input.stop);
  const target = toNumber(input.target);
  const horizon = toNumber(input.horizon);
  const shares = toNumber(input.shares);
  const commission = toNumber(input.commission);
  const slippageBps = toNumber(input.slippageBps);
  const timeReturnPct = toNumber(input.timeReturnPct) ?? 0;

  // Core errors stop the outputs; weight errors only drop the expected value.
  const coreErrors = [];
  if (side !== 'long' && side !== 'short') coreErrors.push('Choose long or short.');
  if (![entry, stop, target].every(price)) {
    coreErrors.push('Entry, stop and target must be positive prices.');
  } else if (side === 'long' || side === 'short') {
    if (d * (stop - entry) >= 0) coreErrors.push(`For a ${side}, the stop must sit ${side === 'long' ? 'below' : 'above'} the entry.`);
    if (d * (target - entry) <= 0) coreErrors.push(`For a ${side}, the target must sit ${side === 'long' ? 'above' : 'below'} the entry.`);
  }
  if (!Number.isInteger(horizon) || horizon < 1) coreErrors.push('Horizon must be a whole number of sessions, 1 or more.');
  if (shares !== null && (!Number.isInteger(shares) || shares < 1)) coreErrors.push('Shares must be a whole number, or blank.');
  if (!nonNegative(commission)) coreErrors.push('Commission per share is needed: enter 0 if there is none.');
  if (!nonNegative(slippageBps)) coreErrors.push('Slippage in bps per side is needed: enter 0 if there is none.');
  if (!finite(timeReturnPct)) coreErrors.push('The horizon-end return must be a number, or blank for 0%.');
  const timeReturn = finite(timeReturnPct) ? timeReturnPct / 100 : 0;
  if (price(entry) && finite(timeReturn) && !(entry * (1 + d * timeReturn) > 0)) {
    coreErrors.push('The horizon-end return takes the price to zero or below.');
  }

  // Weights are optional as a set: all blank means no expected value.
  const weightErrors = [];
  const weightIn = [input.pTarget, input.pStop, input.pTime].map(toNumber);
  let weights = null;
  if (!weightIn.every((w) => w === null)) {
    const sum = weightIn.reduce((a, b) => a + (b ?? 0), 0);
    if (weightIn.some((w) => !finite(w))) weightErrors.push('Enter all three weights (target, stop, horizon end), or leave all blank.');
    else if (weightIn.some((w) => w < 0 || w > 1)) weightErrors.push('Each weight must be between 0% and 100%.');
    else if (Math.abs(sum - 1) > 1e-9) weightErrors.push(`Weights must sum to 100%; they sum to ${(100 * sum).toFixed(1)}%.`);
    else weights = { pTarget: weightIn[0], pStop: weightIn[1], pTime: weightIn[2] };
  }
  const errors = [...coreErrors, ...weightErrors];
  if (coreErrors.length) return { ...EMPTY, ok: false, errors };

  const timeExit = entry * (1 + d * timeReturn);
  const gainGross = d * (target - entry);
  const lossGross = d * (entry - stop);
  const gainCost = roundTrip(target, entry, commission, slippageBps);
  const lossCost = roundTrip(stop, entry, commission, slippageBps);
  const timeCost = roundTrip(timeExit, entry, commission, slippageBps);
  const gainNet = gainGross - gainCost;
  const lossNet = lossGross + lossCost;
  const timeGross = entry * timeReturn;
  const timeNet = timeGross - timeCost;
  const span = gainNet + lossNet;
  if (!(span > 0)) {
    errors.push('Costs leave no room between the stop and the target.');
    return { ...EMPTY, ok: false, errors };
  }

  const leg = (gross, net, exit, cost) => ({
    exit, costPerShare: cost, grossPerShare: gross, netPerShare: net,
    grossPct: 100 * gross / entry, netPct: 100 * net / entry,
  });

  // Share of the target among trades that resolve, given the horizon-end share:
  // EV = (1 - p_t)(q(G+L) - L) + p_t M = 0 solves to q = (L - p_t M / (1 - p_t)) / (G + L).
  let breakevenWithTime = null;
  if (weights && weights.pTime < 1) {
    const targetShare = (lossNet - (weights.pTime * timeNet) / (1 - weights.pTime)) / span;
    breakevenWithTime = { targetShare, successRate: (1 - weights.pTime) * targetShare,
      feasible: targetShare >= 0 && targetShare <= 1 };
  }

  let expected = null;
  if (weights) {
    const contributions = { target: weights.pTarget * gainNet, stop: -weights.pStop * lossNet,
      time: weights.pTime * timeNet };
    const perShare = contributions.target + contributions.stop + contributions.time;
    expected = { perShare, r: perShare / lossGross, position: shares === null ? null : perShare * shares, contributions };
  }

  return {
    ok: errors.length === 0,
    errors,
    riskPerShare: lossGross,
    entry,
    side,
    target: leg(gainGross, gainNet, target, gainCost),
    stop: leg(-lossGross, -lossNet, stop, lossCost),
    time: { ...leg(timeGross, timeNet, timeExit, timeCost), returnPct: 100 * timeReturn },
    rewardRisk: gainNet / lossNet,
    breakevenSuccess: lossNet / span,
    breakevenWithTime,
    weights,
    expected,
  };
}

// EV in R over success rate x target distance, with the horizon-end share held
// at the entered weight (0 when blank). The stop share is what is left after
// the success rate and the horizon share: 1 - p - p_t. Cells where that is
// negative are null, so a missing combination is never read as a zero.
export function planSensitivity(input = {}, { rates = DEFAULT_RATES, multiples = DEFAULT_MULTIPLES } = {}) {
  const model = planOutcomes(input);
  if (!model.target || model.errors.length) return null;
  const d = model.side === 'short' ? -1 : 1;
  const { entry, riskPerShare: R } = model;
  const pTime = model.weights?.pTime ?? 0;
  const commission = toNumber(input.commission);
  const slippageBps = toNumber(input.slippageBps);
  const lossNet = -model.stop.netPerShare;
  const timeNet = model.time.netPerShare;
  const rows = multiples.map((multiple) => {
    const exit = entry + d * multiple * (model.target.exit - entry);
    const gainNet = d * (exit - entry) - roundTrip(exit, entry, commission, slippageBps);
    const span = gainNet + lossNet;
    const cells = rates.map((p) => {
      const stopShare = 1 - p - pTime;
      if (stopShare < -1e-9) return null;
      return (p * gainNet - Math.max(stopShare, 0) * lossNet + pTime * timeNet) / R;
    });
    return { multiple, target: exit, breakevenSuccess: span > 0 ? lossNet / span : null, cells };
  });
  return { rates, multiples, rows };
}

// One sentence the card headlines: the question, not the expected value.
export function breakevenHeadline(breakeven) {
  if (!finite(breakeven)) return null;
  if (breakeven > 1) return 'Out of reach: after costs a target hit loses money, so no success rate breaks even.';
  return `Success rate needed to break even: ${(100 * breakeven).toFixed(1)}% — does your evidence support at least that?`;
}

// What a closed trade made after its actual costs, in units of the plan's
// initial risk per share. Costs are the total in dollars for the position.
export function reviewResult({ side, plannedEntry, plannedStop, actualEntry, actualExit, shares = 1, costs = 0 }) {
  const d = side === 'short' ? -1 : 1;
  const risk = Math.abs(plannedEntry - plannedStop);
  const n = shares ?? 1;
  if ((side !== 'long' && side !== 'short') || !price(plannedEntry) || !price(plannedStop) || !(risk > 0)
    || !price(actualEntry) || !price(actualExit) || !finite(n) || n <= 0 || !nonNegative(costs)) return null;
  const perShare = d * (actualExit - actualEntry) - costs / n;
  return { riskPerShare: risk, realisedPerShare: perShare, realisedTotal: perShare * n, r: perShare / risk };
}

// ------------------------------------------------------------ file formats

const pnlJson = (leg) => ({ exit: leg.exit, gross_per_share: leg.grossPerShare, net_per_share: leg.netPerShare,
  gross_pct: leg.grossPct, net_pct: leg.netPct, cost_per_share: leg.costPerShare });

// The plan as a file: inputs as typed, outputs as computed, thesis text, and
// an empty review block that the review export fills in its own file.
export function planToJson({ ticker, created, dataAsOf = null, input, thesis = {} }) {
  const model = planOutcomes(input);
  return {
    schema: PLAN_SCHEMA,
    ticker,
    created,
    data_as_of: dataAsOf,
    inputs: {
      side: input.side ?? null,
      entry: toNumber(input.entry),
      stop: toNumber(input.stop),
      target: toNumber(input.target),
      horizon_sessions: toNumber(input.horizon),
      shares: toNumber(input.shares),
      commission_per_share: toNumber(input.commission),
      slippage_bps: toNumber(input.slippageBps),
      p_target: toNumber(input.pTarget),
      p_stop: toNumber(input.pStop),
      p_time: toNumber(input.pTime),
      time_return_pct: toNumber(input.timeReturnPct) ?? 0,
    },
    outputs: model.target ? {
      risk_per_share: model.riskPerShare,
      target: pnlJson(model.target),
      stop: pnlJson(model.stop),
      horizon_end: { ...pnlJson(model.time), return_pct: model.time.returnPct },
      reward_risk_after_costs: model.rewardRisk,
      breakeven_success: model.breakevenSuccess,
      breakeven_success_with_horizon_end: model.breakevenWithTime && {
        target_share_of_resolved: model.breakevenWithTime.targetShare,
        success_rate: model.breakevenWithTime.successRate,
        feasible: model.breakevenWithTime.feasible,
      },
      expected_from_your_weights: model.expected && {
        per_share: model.expected.perShare, in_r: model.expected.r, position: model.expected.position,
      },
    } : null,
    thesis: {
      why: thesis.why ?? '',
      evidence: thesis.evidence ?? '',
      what_would_prove_wrong: thesis.whatWouldProveWrong ?? '',
    },
    review: {},
  };
}

// Reads a plan/v1 object back into the form's input shape. The inputs are run
// through planOutcomes again, so a hand-edited file cannot load a broken plan.
export function readPlanFile(obj) {
  if (!obj || obj.schema !== PLAN_SCHEMA || typeof obj.ticker !== 'string') return { ok: false, error: 'Not a plan/v1 file.' };
  const i = obj.inputs || {};
  const input = { side: i.side, entry: i.entry, stop: i.stop, target: i.target, horizon: i.horizon_sessions,
    shares: i.shares, commission: i.commission_per_share, slippageBps: i.slippage_bps, pTarget: i.p_target,
    pStop: i.p_stop, pTime: i.p_time, timeReturnPct: i.time_return_pct };
  const model = planOutcomes(input);
  if (!model.ok) return { ok: false, error: `The plan's inputs do not validate: ${model.errors.join(' ')}` };
  return { ok: true, plan: { ticker: obj.ticker, created: obj.created ?? null, dataAsOf: obj.data_as_of ?? null,
    input, thesis: { why: obj.thesis?.why ?? '', evidence: obj.thesis?.evidence ?? '',
      whatWouldProveWrong: obj.thesis?.what_would_prove_wrong ?? '' } } };
}

// The review file: what was done against the plan, the result in R, and the
// judgement recorded on its own line, because the two are separate questions.
export function reviewToJson({ plan, created, actual, followedPlan = null, whatChanged = '', thesisOutcome = null }) {
  const result = reviewResult({
    side: plan.input.side, plannedEntry: plan.input.entry, plannedStop: plan.input.stop,
    actualEntry: actual.entry, actualExit: actual.exit,
    shares: actual.shares ?? plan.input.shares ?? 1, costs: actual.costs,
  });
  return {
    schema: REVIEW_SCHEMA,
    ticker: plan.ticker,
    plan_created: plan.created,
    created,
    actual: { entry: actual.entry ?? null, exit: actual.exit ?? null, shares: actual.shares ?? null, costs_total: actual.costs ?? null },
    result: result && { risk_per_share: result.riskPerShare, realised_per_share: result.realisedPerShare,
      realised_total: result.realisedTotal, r: result.r },
    execution: { followed_plan: followedPlan, what_changed: whatChanged },
    judgement: { thesis_outcome: thesisOutcome },
  };
}

// plan-SPY-2026-10-25.json, dated in the reader's own calendar.
export function planFileName(kind, ticker, created) {
  const d = new Date(created);
  const pad = (n) => String(n).padStart(2, '0');
  return `${kind}-${ticker}-${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}.json`;
}

// ------------------------------------------------------------ text export

const f = (v, digits = 2) => (finite(v) ? v.toFixed(digits) : '—');
const signed = (v, digits = 2) => (finite(v) ? `${v > 0 ? '+' : ''}${v.toFixed(digits)}` : '—');

export function planMarkdown(plan) {
  const o = plan.outputs;
  const i = plan.inputs;
  const lines = [`# Trade plan: ${plan.ticker} (${i.side ?? '—'})`, '',
    `Created ${plan.created} · data as of ${plan.data_as_of ?? '—'}`, '',
    'Your assumptions, not a forecast. No historical success rate is filled in: none of these entry/exit rules has been tested.', ''];
  lines.push(`Entry ${f(i.entry)} · stop ${f(i.stop)} · target ${f(i.target)} · horizon ${i.horizon_sessions ?? '—'} sessions`
    + ` · commission ${f(i.commission_per_share)} $/share/side · slippage ${f(i.slippage_bps, 1)} bps/side`, '');
  if (!o) return [...lines, 'No valid outputs: the inputs do not validate.'].join('\n');
  lines.push('| Outcome | Per share | After costs | % of entry, after costs | Your weight |', '|---|---|---|---|---|',
    `| Target hit | ${signed(o.target.gross_per_share)} | ${signed(o.target.net_per_share)} | ${signed(o.target.net_pct)}% | ${f(i.p_target !== null ? 100 * i.p_target : null, 1)}% |`,
    `| Stop hit | ${signed(o.stop.gross_per_share)} | ${signed(o.stop.net_per_share)} | ${signed(o.stop.net_pct)}% | ${f(i.p_stop !== null ? 100 * i.p_stop : null, 1)}% |`,
    `| Horizon ends, neither hit | ${signed(o.horizon_end.gross_per_share)} | ${signed(o.horizon_end.net_per_share)} | ${signed(o.horizon_end.net_pct)}% | ${f(i.p_time !== null ? 100 * i.p_time : null, 1)}% |`, '');
  lines.push(`Reward:risk after costs 1 : ${f(o.reward_risk_after_costs)} · breakeven success ignoring horizon end ${f(100 * o.breakeven_success, 1)}%`
    + (o.breakeven_success_with_horizon_end ? ` · with horizon end ${f(100 * o.breakeven_success_with_horizon_end.success_rate, 1)}%` : ''));
  if (o.expected_from_your_weights) {
    lines.push(`Expected value from your weights: ${signed(o.expected_from_your_weights.per_share)} per share, ${signed(o.expected_from_your_weights.in_r)} R`);
  }
  lines.push('', '## Thesis', `Why this trade: ${plan.thesis.why}`, `Evidence: ${plan.thesis.evidence}`,
    `What would prove it wrong: ${plan.thesis.what_would_prove_wrong}`);
  return lines.join('\n');
}

export function reviewMarkdown(review) {
  const r = review.result;
  return [`# Trade review: ${review.ticker}`, '',
    `Plan created ${review.plan_created} · review created ${review.created}`, '',
    r ? `Realised ${signed(r.realised_per_share)} per share after actual costs = ${signed(r.r)} R (initial risk ${f(r.risk_per_share)} per share).`
      : 'No result: enter the actual entry, exit and costs.',
    '',
    `Followed the plan: ${review.execution.followed_plan ?? '—'}`,
    `What changed: ${review.execution.what_changed || '—'}`,
    `Thesis: ${review.judgement.thesis_outcome ?? '—'}`, '',
    'Execution and judgement are recorded separately. A loss can be a sound decision, and a gain does not prove the reasoning.'].join('\n');
}
