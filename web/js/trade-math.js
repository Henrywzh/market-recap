// Pure calculations for the trade desk. Inputs are the existing baked closes,
// option snapshots and anchor history; nothing here fetches a second feed.

const finite = (v) => typeof v === 'number' && Number.isFinite(v);

export function closeLevels(closes, ohlcv = null, dates = null) {
  const clean = (closes || []).filter(finite);
  if (!clean.length) return null;
  const last = clean.at(-1);
  const window = (n) => clean.length > n
    ? { low: Math.min(...clean.slice(-n - 1, -1)), high: Math.max(...clean.slice(-n - 1, -1)) }
    : null;
  const moving = Object.fromEntries([20, 50, 200].map((n) => [n, clean.length >= n
    ? clean.slice(-n).reduce((sum, v) => sum + v, 0) / n : null]));
  const bar = tradeBarReadings(ohlcv, dates, closes);
  return { close: last, previous: clean.length > 1 ? clean.at(-2) : null,
    twenty: window(20), sixty: window(60), year: window(252), moving, ...bar, sessions: clean.length };
}

export function tradeBarReadings(ohlcv, dates, closes) {
  if (!ohlcv?.dates?.length || !Array.isArray(dates) || !Array.isArray(closes))
    return { atr14: null, adv20: null, gap: null };
  const index = new Set(dates);
  const bars = ohlcv.dates.map((day, i) => ({ day, open: ohlcv.open?.[i], high: ohlcv.high?.[i],
    low: ohlcv.low?.[i], volume: ohlcv.volume?.[i], close: index.has(day) ? ohlcv.close?.[i] : null,
    previous: i > 0 && index.has(ohlcv.dates[i - 1]) ? ohlcv.close?.[i - 1] : null }));
  let atr = null;
  let seed = [];
  for (const b of bars) {
    if (![b.high, b.low, b.previous].every(finite) || b.high < b.low || b.previous <= 0) {
      atr = null; seed = []; continue;
    }
    const tr = Math.max(b.high - b.low, Math.abs(b.high - b.previous), Math.abs(b.low - b.previous));
    if (atr === null) {
      seed.push(tr);
      if (seed.length === 14) atr = seed.reduce((sum, v) => sum + v, 0) / 14;
    } else atr = (13 * atr + tr) / 14;
  }
  const tail = bars.slice(-20);
  const adv20 = tail.length === 20 && tail.every((b) => finite(b.close) && b.close > 0
    && finite(b.volume) && b.volume > 0)
    ? tail.reduce((sum, b) => sum + b.close * b.volume, 0) / 20 : null;
  const last = bars.at(-1);
  const gap = last && finite(last.open) && finite(last.previous) && last.previous > 0
    && finite(last.high) && finite(last.low)
    ? { day: last.day, pct: 100 * (last.open / last.previous - 1),
      filled_intraday: last.open >= last.previous ? last.low <= last.previous : last.high >= last.previous }
    : null;
  return { atr14: atr, adv20, gap };
}

export function optionRange(options, close, asOf) {
  if (!finite(close) || close <= 0 || !options || options.snapshot_day !== asOf) return null;
  const row = (options.term || []).find((r) => r.days >= 2 && finite(r.straddle_pct) && r.straddle_pct > 0);
  if (!row) return null;
  const move = close * row.straddle_pct / 100;
  return { expiry: row.expiry, days: row.days, move_pct: row.straddle_pct,
    lower: close - move, upper: close + move, snapshot_day: options.snapshot_day };
}

export function sizePosition({ account, riskPct, entry, stop, maxPct = 100, side = 'long',
  advUsd = null, participationPct = 1, spreadBps = null }) {
  const [equity, risk, price, stopPrice, notionalPct, participation] =
    [account, riskPct, entry, stop, maxPct, participationPct].map(Number);
  if ([equity, risk, price, stopPrice, notionalPct].some((v) => !Number.isFinite(v))
      || equity <= 0 || risk <= 0 || risk > 100 || price <= 0 || stopPrice <= 0
      || notionalPct <= 0 || notionalPct > 100
      || !Number.isFinite(participation) || participation <= 0 || participation > 100
      || !['long', 'short'].includes(side) || (side === 'long' && stopPrice >= price)
      || (side === 'short' && stopPrice <= price)) return null;
  const riskBudget = equity * risk / 100;
  const perShareRisk = Math.abs(price - stopPrice);
  const riskShares = Math.floor(riskBudget / perShareRisk);
  const notionalShares = Math.floor(equity * notionalPct / 100 / price);
  const liquidityShares = finite(advUsd) && advUsd > 0 ? Math.floor(advUsd * participation / 100 / price) : Infinity;
  const shares = Math.min(riskShares, notionalShares, liquidityShares);
  const spread = spreadBps === null || spreadBps === '' ? null : Number(spreadBps);
  if (spread !== null && (!Number.isFinite(spread) || spread < 0)) return null;
  return { shares, notional: shares * price, riskBudget, plannedLoss: shares * perShareRisk,
    perShareRisk, spreadCost: spread === null ? null : shares * price * spread / 10000,
    cappedBy: liquidityShares <= Math.min(riskShares, notionalShares) ? 'liquidity'
      : notionalShares < riskShares ? 'notional' : 'risk' };
}

// EOD signal at i; assume entry at next session's close and exit h sessions
// later. The same class cannot contribute overlapping outcome windows.
export function stateScorecard(values, closes, states, horizons = [5, 20, 60]) {
  return horizons.flatMap((horizon) => {
    const baseline = [];
    for (let i = 0; i + horizon + 1 < Math.min(values.length, closes.length); i += horizon + 1) {
      const entry = closes[i + 1];
      const exit = closes[i + 1 + horizon];
      if (finite(values[i]) && finite(entry) && finite(exit) && entry > 0)
        baseline.push(100 * (exit / entry - 1));
    }
    const baselineMean = baseline.length ? baseline.reduce((a, b) => a + b, 0) / baseline.length : null;
    return states.map(({ label, match, direction }) => {
    const outcomes = [];
    let nextEligible = 0;
    for (let i = 0; i + horizon + 1 < Math.min(values.length, closes.length); i += 1) {
      if (i < nextEligible || !finite(values[i]) || !match(values[i])) continue;
      const entry = closes[i + 1];
      const exit = closes[i + 1 + horizon];
      if (!finite(entry) || !finite(exit) || entry <= 0) continue;
      outcomes.push(100 * (exit / entry - 1));
      nextEligible = i + horizon + 1;
    }
    const mean = outcomes.length ? outcomes.reduce((a, b) => a + b, 0) / outcomes.length : null;
    return { label, horizon, count: outcomes.length, baseline_count: baseline.length,
      hit_rate: outcomes.length ? 100 * outcomes.filter((r) => r * direction > 0).length / outcomes.length : null,
      baseline_hit_rate: baseline.length ? 100 * baseline.filter((r) => r * direction > 0).length / baseline.length : null,
      mean_pct: mean, baseline_pct: baselineMean,
      difference_pct: mean === null || baselineMean === null ? null : mean - baselineMean };
    });
  });
}

export function anchorScorecard(history, horizons = [5, 20, 60]) {
  return stateScorecard(history?.exposure || [], history?.spy || [], [
    { label: 'RISK-ON', match: (v) => v >= 0.75, direction: 1 },
    { label: 'RISK-OFF', match: (v) => v <= 0.25, direction: -1 },
  ], horizons);
}

export function trendScorecard(trend, horizons = [5, 20, 60]) {
  const full = trend?.scorecard_history;
  if (!full?.dates?.length || full.dates.length !== full.score?.length || full.dates.length !== full.close?.length)
    return [];
  return stateScorecard(full.score, full.close, [
    { label: 'LONG', match: (v) => v >= 0.5, direction: 1 },
    { label: 'SHORT', match: (v) => v <= -0.5, direction: -1 },
  ], horizons);
}

export function sentimentScorecard(sentiment, priceHistory, horizons = [5, 20, 60]) {
  const scores = new Map((sentiment?.dates || []).map((day, i) => [day, sentiment.score?.[i]]));
  const dates = priceHistory?.dates || [];
  const values = dates.map((day) => scores.get(day) ?? null);
  return stateScorecard(values, priceHistory?.spy || [], [
    { label: 'EXTREME FEAR', match: (v) => v <= 25, direction: 1 },
    { label: 'EXTREME GREED', match: (v) => v >= 75, direction: -1 },
  ], horizons);
}

export function earningsProximity(events, asOf, days = 30) {
  const end = new Date(`${asOf}T12:00:00Z`).getTime() + days * 86400000;
  return (events || []).filter((e) => e.event_type === 'earnings' && e.symbol && e.date >= asOf
    && new Date(`${e.date}T12:00:00Z`).getTime() <= end)
    .sort((a, b) => a.date.localeCompare(b.date));
}
