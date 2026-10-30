// EVENT LAB: what a ticker did after days like a chosen one, from its daily bars.
// Every event is measured from the signal session's close (t0) to a later
// session's open or close; every filter is read at that close, as known then.
import { rsi } from './technicals-math.js';
import { stateAt } from './trade-conditions.js';

export const HORIZONS = [1, 2, 3, 4, 5, 10, 20];

// Periods a reader may leave out, by signal date. `from`/`to` inclusive. `on`: left
// out by default (one-off shocks); 2022's inflation and rate rise stays in unless chosen.
export const EXCLUSION_PRESETS = [
  { key: 'dotcom', label: 'Dot-com bust', from: '2000-03-10', to: '2002-10-09', on: true },
  { key: 'gfc', label: 'Financial crisis', from: '2007-10-09', to: '2009-06-30', on: true },
  { key: 'covid', label: 'COVID crash', from: '2020-02-20', to: '2020-06-30', on: true },
  { key: 'rates2022', label: '2022 inflation & rate hikes', from: '2022-01-03', to: '2022-10-12', on: false },
  { key: 'tariff2025', label: 'April 2025 tariffs', from: '2025-04-02', to: '2025-04-30', on: true },
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
  // Highest close of the last 252 sessions: indices of falling closes, oldest first.
  const highs = [];
  for (let i = 0; i < dates.length; i++) {
    const prev = i ? close[i - 1] : null;
    const ok = finite(prev) && prev > 0;
    if (highs.length && highs[0] <= i - 252) highs.shift();
    if (finite(close[i])) {
      while (highs.length && close[highs.at(-1)] <= close[i]) highs.pop();
      highs.push(i);
    }
    const peak = highs.length ? close[highs[0]] : -Infinity;
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
      fromHigh: finite(close[i]) && i >= 251 && peak > 0 ? (close[i] / peak - 1) * 100 : null,
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
// What does not change with the settings, computed once per set of bars: the
// sessions, every session's long outcome, and baselines by window and exclusions.
const prepared = new WeakMap();
function prepare(bars) {
  let p = prepared.get(bars);
  if (!p) {
    const rows = sessions(bars);
    p = { rows, out: rows.map((s) => outcomes(bars, s.i)), baselines: new Map() };
    prepared.set(bars, p);
  }
  return p;
}

const KEYS = HORIZONS.flatMap((x) => [`open${x}`, `close${x}`]);

export function study(bars, { trigger, filters = {}, exclude = [], gap = 5, from = null, costBps = 0, side = 1 } = {}) {
  const { rows, out, baselines } = prepare(bars);
  const eligible = rows.filter((s) => s.i > 0 && (!from || s.date >= from) && !excluded(s.date, exclude));
  const raw = eligible.filter((s) => fires(s, trigger) && passes(s, filters));
  const kept = decluster(raw, gap);
  const adjust = (v) => (finite(v) ? side * v - costBps / 100 : null);
  const events = kept.map((s) => ({ ...s, out: Object.fromEntries(KEYS.map((k) => [k, adjust(out[s.i][k])])) }));
  const summary = Object.fromEntries(KEYS.map((k) => [k, stats(events.map((e) => e.out[k]))]));
  const baseKey = JSON.stringify([from, exclude.map((r) => [r.from, r.to]), side]);
  if (!baselines.has(baseKey)) {
    const baseValues = Object.fromEntries(KEYS.map((k) => [k, eligible.map((s) => out[s.i][k]).filter(finite).map((v) => side * v)]));
    baselines.set(baseKey, { baseValues, baseline: Object.fromEntries(KEYS.map((k) => [k, stats(baseValues[k])])) });
  }
  const { baseValues, baseline } = baselines.get(baseKey);
  const touchedOnly = trigger?.kind === 'intraday' ? kept.filter((s) => (trigger.dir < 0 ? s.closeRet > -Math.abs(trigger.size) : s.closeRet < Math.abs(trigger.size))).length : null;
  return { events, summary, baseline, baseValues, raw: raw.length, eligible: eligible.length, touchedOnly,
    first: eligible[0]?.date || null, last: eligible.at(-1)?.date || null };
}

// The path from the t0 close (0%) through each later open and close, in order, for
// a chart: labels, and per point the events' range, quartiles, mean and share > 0,
// with every session's share > 0 beside it.
export const PATH_KEYS = HORIZONS.flatMap((x) => [`open${x}`, `close${x}`]);
export function path(result) {
  const zero = { min: 0, p25: 0, median: 0, p75: 0, max: 0, mean: 0, hit: null, baseHit: null, n: result.events.length };
  const points = PATH_KEYS.map((k) => {
    const s = result.summary[k];
    return { min: s.min, p25: s.p25, median: s.median, p75: s.p75, max: s.max, mean: s.mean, hit: s.hit, baseHit: result.baseline[k].hit, n: s.n };
  });
  return { labels: ['t0 CLOSE', ...PATH_KEYS.map((k) => `D${k.replace(/\D/g, '')} ${k.startsWith('open') ? 'O' : 'C'}`)],
    points: [zero, ...points] };
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

// Share above zero of the last `window` events' outcome at each event (null until `window`).
export function rollingShare(events, key, window = 10) {
  return events.map((_, i) => {
    if (i + 1 < window) return null;
    const v = events.slice(i + 1 - window, i + 1).map((e) => e.out[key]).filter(finite);
    return v.length ? v.filter((x) => x > 0).length / v.length : null;
  });
}

export function toCsv(events, ticker) {
  const cols = HORIZONS.flatMap((x) => [`open${x}`, `close${x}`]);
  const head = ['ticker', 'date', 'low_pct', 'close_pct', 'gap_pct', 'sigma', 'rsi6', 'vs50_pct', 'vs200_pct', 'from_1y_high_pct', ...cols.map((c) => `${c}_pct`)];
  const f = (v, d = 3) => (finite(v) ? v.toFixed(d) : '');
  const lines = events.map((e) => [ticker, e.date, f(e.lowRet), f(e.closeRet), f(e.gapRet), f(e.sigma, 2), f(e.rsi6, 1), f(e.vs50), f(e.vs200), f(e.fromHigh), ...cols.map((c) => f(e.out[c]))].join(','));
  return [head.join(','), ...lines].join('\n');
}
