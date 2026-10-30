// Each session's close-to-close return and its size in units of the prior
// `volWindow` sessions' volatility (null until there are that many).
import * as M from './movecheck-model.js';

export function dailyMoves(dates, close, volWindow = 20) {
  const daily = M.returns(dates, close, 1);
  return daily.map((r, i) => ({ ...r,
    z: i >= volWindow ? M.sigmaOf(daily.slice(i - volWindow, i + 1), r.ret, volWindow, 1) : null }));
}

// How often a value this far out happened: the share of finite values at or below
// a negative `x` (at or above a positive one), with the count. Null for zero or none.
export function tailShare(values, x) {
  if (!Number.isFinite(x) || x === 0) return null;
  const v = values.filter(Number.isFinite);
  if (!v.length) return null;
  const hits = v.filter((y) => (x < 0 ? y <= x : y >= x)).length;
  return { hits, n: v.length, share: hits / v.length };
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
