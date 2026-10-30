// Market backdrop conditions for the Trade Desk's event study: look up the state
// each condition was in at a signal's close, keep the signals that match, and
// say how much a conditioned result can be trusted (trades, separate stretches,
// how often a random draw of as many trades did as well).

// runs: [[first_date, state], ...] sorted; the state holds from that date on.
export function stateAt(runs, date) {
  let lo = 0; let hi = (runs?.length || 0) - 1; let found = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (runs[mid][0] <= date) { found = runs[mid][1]; lo = mid + 1; } else hi = mid - 1;
  }
  return found;
}

// picks: { key: state } for the conditions that are set; others are ignored.
// A signal whose state is unknown for a set condition is dropped, not kept.
export function matchSignals(signals, conditions, picks) {
  const active = (conditions || []).filter((c) => picks?.[c.key]);
  if (!active.length) return signals.slice();
  return signals.filter((date) => active.every((c) => stateAt(c.runs, date) === picks[c.key]));
}

// Trades closer together than gapDays (calendar, signal to signal) are one stretch.
export function stretches(trades, gapDays = 91) {
  let count = 0; let last = null;
  for (const t of trades) {
    const day = Date.parse(t.signal);
    if (last === null || (day - last) / 864e5 > gapDays) count++;
    last = day;
  }
  return count;
}

export function summary(trades) {
  const r = trades.map((t) => t.ret);
  if (!r.length) return { n: 0, mean: null, median: null, win: null, total: null };
  const sorted = [...r].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  const total = r.reduce((c, v) => c * (1 + v / 100), 1);
  return { n: r.length, mean: r.reduce((a, b) => a + b, 0) / r.length,
    median: sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2,
    win: r.filter((v) => v > 0).length / r.length, total: (total - 1) * 100 };
}

function rng(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

// Share of random draws of k trades (without replacement) from all trades whose
// mean return is at least the conditioned mean. Small = the condition picked
// better trades than chance would; near 50% = no different from a random pick.
export function randomDrawShare(allReturns, k, observedMean, { draws = 2000, seed = 20261030 } = {}) {
  const n = allReturns.length;
  if (!(k > 0) || k >= n || !Number.isFinite(observedMean)) return null;
  const next = rng(seed); const pool = allReturns.slice(); let beat = 0;
  for (let d = 0; d < draws; d++) {
    let sum = 0;
    for (let i = 0; i < k; i++) {
      const j = i + Math.floor(next() * (n - i));
      [pool[i], pool[j]] = [pool[j], pool[i]];
      sum += pool[i];
    }
    if (sum / k >= observedMean - 1e-12) beat++;
  }
  return beat / draws;
}

// Today's state for every condition that has one: the "like today" preset.
export function likeToday(conditions) {
  return Object.fromEntries((conditions || []).filter((c) => c.today).map((c) => [c.key, c.today]));
}
