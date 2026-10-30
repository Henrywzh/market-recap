// Descriptive event study, using volatility known before each return begins.
import * as M from './movecheck-model.js';

export const EVENT_FORWARD = [1, 3, 5, 10, 20];

export function eventStudy(dates, close, { horizon = 1, mode = 'sigma', threshold = -2, lookback = null, volWindow = 20 } = {}) {
  const returns = M.returns(dates, close, horizon);
  const daily = M.returns(dates, close, 1);
  const dayIndex = new Map(daily.map((r, i) => [r.date, i]));
  const observations = returns.map((r) => {
    const end = dayIndex.get(r.date);
    // The horizon's first daily return is end-horizon+1; use only earlier returns.
    const stop = end - horizon + 1;
    const past = daily.slice(Math.max(0, stop - volWindow), stop);
    const z = stop >= volWindow && past.length === volWindow ? M.sigmaOf([...past, { ret: r.ret }], r.ret, volWindow, horizon) : null;
    return { ...r, z };
  });
  const windowed = lookback ? observations.slice(-lookback) : observations;
  const eligible = mode === 'sigma' ? windowed.filter((r) => Number.isFinite(r.z)) : windowed;
  const down = threshold < 0;
  const candidates = windowed.map((r) => {
    const v = mode === 'sigma' ? r.z : r.ret;
    return { ...r, ret: Number.isFinite(v) && (down ? v <= threshold : v >= threshold) ? r.ret : null };
  });
  const latest = dates?.at(-1);
  const episodes = M.episodes(candidates, down ? -Number.MIN_VALUE : Number.MIN_VALUE)
    .filter((e) => e.worstDate !== latest)
    .map((e) => ({ ...e, forward: EVENT_FORWARD.map((n) => M.forward(dates, close, e.worstDate, n)),
      drawdown: M.maxDrawdownAfter(dates, close, e.worstDate, 20) }));
  const baseline = eligible.map((r) => ({ forward: EVENT_FORWARD.map((n) => M.forward(dates, close, r.date, n)) }));
  const summarize = (rows, index) => {
    const values = rows.map((r) => r.forward[index]).filter(Number.isFinite);
    return { n: values.length, median: M.median(values), share: values.length ? values.filter((v) => v > 0).length / values.length : null };
  };
  const signals = candidates.filter((r) => Number.isFinite(r.ret)).map((r) => r.date);
  return { eligible: eligible.length, events: episodes, signals, latest: observations.at(-1) || null,
    rows: EVENT_FORWARD.map((days, i) => ({ days, events: summarize(episodes, i), baseline: summarize(baseline, i) })) };
}

// Post-signal execution intervals. Open-close: +1 open to +N close.
// Other modes: +1 selected entry to +(N+1) selected exit. No same-close entries.
// Keep the exported name for existing callers; default remains open-close.
// Price bars are split-adjusted; dividends, financing and borrow are not included.
export function simulateNextOpen(signals, bars, { sessions = 5, side = 1, costBps = 10, execution = 'open-close' } = {}) {
  if (!bars?.dates || !bars.open || !bars.close) return [];
  if (!['open-close', 'close-close', 'open-open', 'close-open'].includes(execution)) return [];
  const indexes = new Map(bars.dates.map((d, i) => [d, i]));
  const trades = [];
  let lastExit = -1;
  for (const date of signals) {
    const i = indexes.get(date);
    if (i === undefined || i <= lastExit) continue;
    const entry = i + 1;
    const exit = i + sessions + (execution === 'open-close' ? 0 : 1);
    if (exit >= bars.dates.length) continue;
    const buy = execution.startsWith('open-') ? bars.open[entry] : bars.close[entry];
    const sell = execution.endsWith('-open') ? bars.open[exit] : bars.close[exit];
    if (!(Number.isFinite(buy) && buy > 0 && Number.isFinite(sell) && sell > 0)) continue;
    trades.push({ signal: date, entry: bars.dates[entry], exit: bars.dates[exit],
      ret: side * (sell / buy - 1) * 100 - costBps / 100 });
    lastExit = exit;
  }
  return trades;
}
