// EVENT LAB: what a ticker did after days like a chosen one, from its daily bars.
// Every event is measured from the signal session's close (t0) to a later
// session's open or close; every filter is read at that close, as known then.
import { rsi } from './technicals-math.js';
import { stateAt } from './trade-conditions.js';

export const HORIZONS = [1, 2, 3, 4, 5, 10, 20];

// Periods a reader may leave out, by signal date. `from`/`to` inclusive.
export const EXCLUSION_PRESETS = [
  { key: 'dotcom', label: 'Dot-com bust', from: '2000-03-10', to: '2002-10-09' },
  { key: 'gfc', label: 'Financial crisis', from: '2007-10-09', to: '2009-06-30' },
  { key: 'covid', label: 'COVID crash', from: '2020-02-20', to: '2020-06-30' },
  { key: 'bear2022', label: '2022 bear market', from: '2022-01-03', to: '2022-10-12' },
  { key: 'tariff2025', label: 'April 2025 tariffs', from: '2025-04-02', to: '2025-04-30' },
];

const finite = (v) => typeof v === 'number' && Number.isFinite(v);

// Simple moving average of the close through each session; null until `n` closes.
function sma(values, n) {
  const out = new Array(values.length).fill(null);
  let sum = 0; let count = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (!finite(v)) { sum = 0; count = 0; continue; }
    sum += v; count++;
    if (count > n) sum -= values[i - n];
    if (count >= n) out[i] = sum / n;
  }
  return out;
}

// Sample standard deviation of the previous `n` daily close-to-close returns (%).
function priorVol(close, i, n = 20) {
  if (i < n + 1) return null;
  const r = [];
  for (let k = i - n; k < i; k++) {
    if (!(finite(close[k]) && finite(close[k - 1]) && close[k - 1] > 0)) return null;
    r.push((close[k] / close[k - 1] - 1) * 100);
  }
  const mean = r.reduce((a, b) => a + b, 0) / n;
  return Math.sqrt(r.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1));
}

// One row per session with what was known at its close.
export function sessions(bars) {
  const { dates, open, high, low, close } = bars;
  const rsi6 = rsi(close.map((v) => (finite(v) ? v : NaN)), 6);
  const ma50 = sma(close, 50); const ma200 = sma(close, 200);
  const rows = [];
  let peak = -Infinity; const window = [];
  for (let i = 0; i < dates.length; i++) {
    const prev = i ? close[i - 1] : null;
    const ok = finite(prev) && prev > 0;
    window.push(close[i]); if (window.length > 252) window.shift();
    peak = Math.max(...window.filter(finite));
    const vol = priorVol(close, i);
    const closeRet = ok && finite(close[i]) ? (close[i] / prev - 1) * 100 : null;
    rows.push({
      i, date: dates[i],
      lowRet: ok && finite(low[i]) ? (low[i] / prev - 1) * 100 : null,
      highRet: ok && finite(high[i]) ? (high[i] / prev - 1) * 100 : null,
      gapRet: ok && finite(open[i]) ? (open[i] / prev - 1) * 100 : null,
      closeRet,
      sigma: finite(closeRet) && finite(vol) && vol > 0 ? closeRet / vol : null,
      rsi6: finite(rsi6[i]) ? rsi6[i] : null,
      vs50: finite(ma50[i]) ? (close[i] / ma50[i] - 1) * 100 : null,
      vs200: finite(ma200[i]) ? (close[i] / ma200[i] - 1) * 100 : null,
      fromHigh: finite(close[i]) && window.length >= 252 && peak > 0 ? (close[i] / peak - 1) * 100 : null,
    });
  }
  return rows;
}

// Does session `s` fire the trigger? kind: intraday | close | gap | sigma; dir -1 fall, +1 rise.
export function fires(s, { kind = 'intraday', dir = -1, size = 4 } = {}) {
  const value = kind === 'intraday' ? (dir < 0 ? s.lowRet : s.highRet)
    : kind === 'close' ? s.closeRet : kind === 'gap' ? s.gapRet : s.sigma;
  if (!finite(value)) return false;
  return dir < 0 ? value <= -Math.abs(size) : value >= Math.abs(size);
}

const compare = (value, op, limit) => finite(value) && (op === 'lt' ? value < limit : op === 'le' ? value <= limit
  : op === 'gt' ? value > limit : value >= limit);

// filters: { rsi: {op, value}, trend: 'above50'|'below50'|'above200'|'below200', fromHigh: {op, value},
//   backdrop: {key: state}, conditions: [...] }
export function passes(s, filters = {}) {
  if (filters.rsi && !compare(s.rsi6, filters.rsi.op, filters.rsi.value)) return false;
  if (filters.trend) {
    const v = filters.trend.endsWith('50') ? s.vs50 : s.vs200;
    if (!finite(v) || (filters.trend.startsWith('above') ? v <= 0 : v >= 0)) return false;
  }
  if (filters.fromHigh && !compare(s.fromHigh, filters.fromHigh.op, filters.fromHigh.value)) return false;
  for (const [key, want] of Object.entries(filters.backdrop || {})) {
    const c = (filters.conditions || []).find((x) => x.key === key);
    if (!c || stateAt(c.runs, s.date) !== want) return false;
  }
  return true;
}

export const excluded = (date, ranges) => (ranges || []).some((r) => date >= r.from && date <= r.to);

// Keep the first event, then skip any that fire within `gap` sessions of the last kept one.
export function decluster(events, gap) {
  if (!(gap > 0)) return events.slice();
  const out = []; let last = -Infinity;
  for (const e of events) if (e.i - last > gap) { out.push(e); last = e.i; }
  return out;
}

// t0 close -> session t0+x open and close, in %, less a round-trip cost; side -1 flips the sign.
export function outcomes(bars, i, { horizons = HORIZONS, costBps = 0, side = 1 } = {}) {
  const base = bars.close[i]; const out = {};
  for (const x of horizons) {
    const j = i + x;
    for (const at of ['open', 'close']) {
      const p = j < bars.dates.length ? bars[at][j] : null;
      out[`${at}${x}`] = finite(base) && base > 0 && finite(p) && p > 0 ? side * (p / base - 1) * 100 - costBps / 100 : null;
    }
  }
  return out;
}

// Linear-interpolated quantile (pandas' default) of sorted values.
function quantile(sorted, q) {
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * q; const lo = Math.floor(pos); const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

export function stats(values) {
  const v = values.filter(finite).sort((a, b) => a - b);
  if (!v.length) return { n: 0, hit: null, mean: null, median: null, min: null, p25: null, p75: null, max: null };
  return { n: v.length, hit: v.filter((x) => x > 0).length / v.length, mean: v.reduce((a, b) => a + b, 0) / v.length,
    median: quantile(v, 0.5), min: v[0], p25: quantile(v, 0.25), p75: quantile(v, 0.75), max: v.at(-1) };
}

// The whole study. Returns events (with outcomes), per-horizon stats for events and
// for every eligible session (baseline), and the raw count before declustering.
export function study(bars, { trigger, filters = {}, exclude = [], gap = 5, from = null, costBps = 0, side = 1 } = {}) {
  const rows = sessions(bars);
  const eligible = rows.filter((s) => s.i > 0 && (!from || s.date >= from) && !excluded(s.date, exclude));
  const raw = eligible.filter((s) => fires(s, trigger) && passes(s, filters));
  const kept = decluster(raw, gap);
  const events = kept.map((s) => ({ ...s, out: outcomes(bars, s.i, { costBps, side }) }));
  const keys = HORIZONS.flatMap((x) => [`open${x}`, `close${x}`]);
  const summary = Object.fromEntries(keys.map((k) => [k, stats(events.map((e) => e.out[k]))]));
  const base = eligible.map((s) => outcomes(bars, s.i, { costBps: 0, side }));
  const baseValues = Object.fromEntries(keys.map((k) => [k, base.map((o) => o[k]).filter(finite)]));
  const baseline = Object.fromEntries(keys.map((k) => [k, stats(baseValues[k])]));
  const touchedOnly = trigger?.kind === 'intraday' ? kept.filter((s) => (trigger.dir < 0 ? s.closeRet > -Math.abs(trigger.size) : s.closeRet < Math.abs(trigger.size))).length : null;
  return { events, summary, baseline, baseValues, raw: raw.length, eligible: eligible.length, touchedOnly,
    first: eligible[0]?.date || null, last: eligible.at(-1)?.date || null };
}

// Per calendar year of the signal: n, mean and share > 0 for one outcome key.
export function byYear(events, key) {
  const groups = new Map();
  for (const e of events) {
    const v = e.out[key]; if (!finite(v)) continue;
    const y = e.date.slice(0, 4);
    if (!groups.has(y)) groups.set(y, []);
    groups.get(y).push(v);
  }
  return [...groups.entries()].sort().map(([year, v]) => ({ year, ...stats(v) }));
}

// Median of the last `window` events' outcome at each event (null until `window` events).
export function rollingMedian(events, key, window = 10) {
  const values = events.map((e) => e.out[key]);
  return values.map((_, i) => {
    if (i + 1 < window) return null;
    const v = values.slice(i + 1 - window, i + 1).filter(finite).sort((a, b) => a - b);
    return v.length ? quantile(v, 0.5) : null;
  });
}

export function toCsv(events, ticker) {
  const cols = HORIZONS.flatMap((x) => [`open${x}`, `close${x}`]);
  const head = ['ticker', 'date', 'low_pct', 'close_pct', 'gap_pct', 'sigma', 'rsi6', 'vs50_pct', 'vs200_pct', 'from_1y_high_pct', ...cols.map((c) => `${c}_pct`)];
  const f = (v, d = 3) => (finite(v) ? v.toFixed(d) : '');
  const lines = events.map((e) => [ticker, e.date, f(e.lowRet), f(e.closeRet), f(e.gapRet), f(e.sigma, 2), f(e.rsi6, 1), f(e.vs50), f(e.vs200), f(e.fromHigh), ...cols.map((c) => f(e.out[c]))].join(','));
  return [head.join(','), ...lines].join('\n');
}
