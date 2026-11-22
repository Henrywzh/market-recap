// event_study: TRADE DESK -> EVENT LAB as a tool. What a ticker did after days
// like a chosen one, from its daily bars, under chosen filters and market
// backdrop, against every session in the same window.
//
// The page's own model decides everything that defines an event
// (web/js/event-lab-model.js: the trigger, the exclusions, declustering and the
// statistics; web/js/trade-conditions.js: the backdrop states, stretches, the
// random-draw check). Only two things are computed here:
//
// - readings(): the model's sessions() column by column. sessions() allocates an
//   array per session for its 20-day volatility and costs ~4 ms on SPY's 6,700
//   sessions; one call gets ~10 ms of CPU on the free plan. The arithmetic is the
//   same, in the same order, so the rows are identical: tests/js/mcp.test.mjs and
//   scripts/check_mcp.mjs compare them with sessions() on every deploy.
// - the reader's own filters the page fixes: RSI of any period, any moving average
//   with a distance band, the high of any window. With the page's settings (RSI 6,
//   the 50- or 200-day average, the 252-session high) they are the page's filters.
//
// Trade Desk belongs to another agent: this file imports its model and never
// changes it, and the deploy check fails if the model's shape moves.

import { rsi } from '../../web/js/technicals-math.js';
import { EXCLUSION_PRESETS, HORIZONS, PATH_KEYS, decluster, excluded, fires } from '../../web/js/event-lab-model.js';
import { likeToday, randomDrawShare, stateAt, stretches } from '../../web/js/trade-conditions.js';
import { cleanTicker } from '../../web/js/routes.js';
import { outputSchema } from '../context.mjs';
import { T } from '../schema.mjs';

// The page's sample-size bar (web/js/event-lab.js) when the artifact gives none.
const MIN_EVENTS = 30;
const MIN_STRETCHES = 5;
const STRETCH_GAP_DAYS = 91;
const RECENT = 10;
// The page's random-draw check costs 2,000 x events steps (~5 ms at 100 events).
// Up to this many events it is run exactly, with the page's seed; above it, the
// normal approximation of the same draw (without replacement) is reported instead,
// which at that size is within a point or two of the draws.
const EXACT_DRAW_EVENTS = 60;
const RECENT_KEYS = ['open1', 'close1', 'close5', 'close10', 'close20'];

const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const r3 = (v) => (finite(v) ? Math.round(v * 1000) / 1000 : null);
const r2 = (v) => (finite(v) ? Math.round(v * 100) / 100 : null);

// Simple moving average through each session, null until `n` closes; a missing
// close restarts the count. The same rule as event-lab-model.js's own (private) sma.
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

// event-lab-model.js's sessions(), as columns: the same fields, values and order of
// arithmetic, without the per-session arrays.
export function readings(bars) {
  const { dates, open, high, low, close } = bars;
  const n = dates.length;
  const rsi6 = rsi(close.map((v) => (finite(v) ? v : NaN)), 6);
  const ma50 = sma(close, 50); const ma200 = sma(close, 200);
  const peakPct = fromHigh(close, 252);
  const rows = new Array(n);
  const VOL = 20;
  for (let i = 0; i < n; i++) {
    const prev = i ? close[i - 1] : null;
    const ok = finite(prev) && prev > 0;
    // Sample standard deviation of the previous 20 close-to-close returns (%).
    let vol = null;
    if (i >= VOL + 1) {
      let sum = 0; let good = true;
      for (let k = i - VOL; k < i; k++) {
        if (!(finite(close[k]) && finite(close[k - 1]) && close[k - 1] > 0)) { good = false; break; }
        sum += (close[k] / close[k - 1] - 1) * 100;
      }
      if (good) {
        const mean = sum / VOL; let sq = 0;
        for (let k = i - VOL; k < i; k++) sq += ((close[k] / close[k - 1] - 1) * 100 - mean) ** 2;
        vol = Math.sqrt(sq / (VOL - 1));
      }
    }
    const closeRet = ok && finite(close[i]) ? (close[i] / prev - 1) * 100 : null;
    rows[i] = {
      i, date: dates[i],
      lowRet: ok && finite(low[i]) ? (low[i] / prev - 1) * 100 : null,
      highRet: ok && finite(high[i]) ? (high[i] / prev - 1) * 100 : null,
      gapRet: ok && finite(open[i]) ? (open[i] / prev - 1) * 100 : null,
      closeRet,
      sigma: finite(closeRet) && finite(vol) && vol > 0 ? closeRet / vol : null,
      rsi6: finite(rsi6[i]) ? rsi6[i] : null,
      vs50: finite(ma50[i]) ? (close[i] / ma50[i] - 1) * 100 : null,
      vs200: finite(ma200[i]) ? (close[i] / ma200[i] - 1) * 100 : null,
      fromHigh: peakPct[i],
    };
  }
  return rows;
}

// Every session's long outcome at each key, as the model's outcomes() gives it
// with no cost: the t0 close to session t0+x's open or close, in %. NaN = none.
export function outcomeColumns(bars) {
  const n = bars.dates.length; const cols = {};
  for (const x of HORIZONS) {
    for (const at of ['open', 'close']) {
      const col = new Float64Array(n).fill(NaN);
      const price = bars[at];
      for (let i = 0; i + x < n; i++) {
        const base = bars.close[i]; const p = price[i + x];
        if (finite(base) && base > 0 && finite(p) && p > 0) col[i] = (p / base - 1) * 100;
      }
      cols[`${at}${x}`] = col;
    }
  }
  return cols;
}

// The k-th smallest of v[0..n) (0-based), in place: Hoare quickselect.
function select(v, n, k) {
  let lo = 0; let hi = n - 1;
  while (hi > lo) {
    const pivot = v[(lo + hi) >> 1]; let i = lo; let j = hi;
    while (i <= j) {
      while (v[i] < pivot) i++;
      while (v[j] > pivot) j--;
      if (i <= j) { const t = v[i]; v[i] = v[j]; v[j] = t; i++; j--; }
    }
    if (k <= j) hi = j; else if (k >= i) lo = i; else return v[k];
  }
  return v[k];
}

// The model's stats() for one baseline column -- n, share > 0, mean and median
// (linear-interpolated, as the model's quantile()) -- without sorting: a sort of
// 5,600 sessions costs ~0.4 ms, fourteen of them most of a call's CPU. Sums can
// differ from the page's in the last binary digits; results are rounded to 0.001.
function baselineStats(col, eligible, side) {
  const v = new Float64Array(eligible.length); let n = 0; let sum = 0; let up = 0;
  for (const s of eligible) {
    const x = col[s.i];
    if (x === x) { const y = side * x; v[n++] = y; sum += y; if (y > 0) up++; }
  }
  if (!n) return { n: 0, hit: null, mean: null, median: null };
  const pos = (n - 1) / 2; const lo = Math.floor(pos);
  const a = select(v, n, lo);
  let median = a;
  if (pos > lo) { let b = Infinity; for (let k = lo + 1; k < n; k++) if (v[k] < b) b = v[k]; median = a + (b - a) * (pos - lo); }
  return { n, hit: up / n, mean: sum / n, median };
}

// Standard normal upper tail, for the large-sample form of the random-draw check.
function upperTail(z) {
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const d = 0.3989422804014327 * Math.exp(-z * z / 2);
  const p = d * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return z >= 0 ? p : 1 - p;
}

// Share of random draws of k sessions (without replacement) from every eligible
// session whose mean is at least the events' mean: exact draws, as the page runs
// them, for small samples; the normal approximation for large ones.
function drawCheck(col, eligible, side, k, observedMean) {
  const all = [];
  for (const s of eligible) { const x = col[s.i]; if (x === x) all.push(side * x); }
  const n = all.length;
  if (!(k > 0) || k >= n || !finite(observedMean)) return { share: null, method: null };
  if (k <= EXACT_DRAW_EVENTS) return { share: randomDrawShare(all, k, observedMean), method: '2,000 random draws (the page\'s check)' };
  let sum = 0; for (const x of all) sum += x;
  const mu = sum / n; let sq = 0; for (const x of all) sq += (x - mu) ** 2;
  const se = Math.sqrt(sq / n / k * (n - k) / (n - 1));
  return { share: se > 0 ? upperTail((observedMean - mu) / se) : null, method: 'normal approximation of the random draw (large sample)' };
}

// % from the highest close of the last `n` sessions (this one included), null
// until the window is full. The page's fromHigh is this with n = 252.
function fromHigh(close, n) {
  const out = new Array(close.length).fill(null);
  const highs = [];
  for (let i = 0; i < close.length; i++) {
    if (highs.length && highs[0] <= i - n) highs.shift();
    if (finite(close[i])) {
      while (highs.length && close[highs.at(-1)] <= close[i]) highs.pop();
      highs.push(i);
    }
    const peak = highs.length ? close[highs[0]] : -Infinity;
    out[i] = finite(close[i]) && i >= n - 1 && peak > 0 ? (close[i] / peak - 1) * 100 : null;
  }
  return out;
}

const inBand = (v, lo, hi) => finite(v) && (lo === undefined || v >= lo) && (hi === undefined || v <= hi);

// The reader's filters as per-session readings, computed once per call.
function custom(bars, filters) {
  const close = bars.close;
  const out = { rsi: null, ma: [], high: null };
  if (filters.rsi) out.rsi = { ...filters.rsi, period: filters.rsi.period || 6, values: rsi(close.map((v) => (finite(v) ? v : NaN)), filters.rsi.period || 6) };
  for (const m of filters.ma || []) {
    const avg = sma(close, m.period);
    out.ma.push({ ...m, values: avg.map((a, i) => (finite(a) && finite(close[i]) ? (close[i] / a - 1) * 100 : null)) });
  }
  if (filters.from_high) out.high = { ...filters.from_high, window: filters.from_high.window || 252, values: fromHigh(close, filters.from_high.window || 252) };
  return out;
}

function passes(i, read) {
  if (read.rsi && !inBand(read.rsi.values[i], read.rsi.min, read.rsi.max)) return false;
  for (const m of read.ma) {
    const v = m.values[i];
    if (!finite(v)) return false;
    if (m.side === 'above' && !(v > 0)) return false;
    if (m.side === 'below' && !(v < 0)) return false;
    if (!inBand(v, m.min_pct, m.max_pct)) return false;
  }
  if (read.high && !inBand(read.high.values[i], read.high.min, read.high.max)) return false;
  return true;
}

function backdropPasses(date, picks, conditions) {
  for (const [key, want] of Object.entries(picks)) {
    const c = conditions.find((x) => x.key === key);
    if (!c || stateAt(c.runs, date) !== want) return false;
  }
  return true;
}

// The model's stats() on a typed column (NaN = none): the same order, quantile
// rule and summation order, with a native sort instead of a comparator sort.
function columnStats(col) {
  const v = new Float64Array(col.length); let n = 0;
  for (let k = 0; k < col.length; k++) if (col[k] === col[k]) v[n++] = col[k];
  if (!n) return { n: 0, hit: null, mean: null, median: null, min: null, p25: null, p75: null, max: null };
  const sorted = v.subarray(0, n).sort();
  let sum = 0; let up = 0;
  for (let k = 0; k < n; k++) { sum += sorted[k]; if (sorted[k] > 0) up++; }
  const q = (x) => { const pos = (n - 1) * x; const lo = Math.floor(pos); const hi = Math.ceil(pos); return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo); };
  return { n, hit: up / n, mean: sum / n, median: q(0.5), min: sorted[0], p25: q(0.25), p75: q(0.75), max: sorted[n - 1] };
}

const statsOut = (s) => ({ n: s.n, share_positive: r3(s.hit), mean_pct: r3(s.mean), median_pct: r3(s.median), p25_pct: r3(s.p25), p75_pct: r3(s.p75), worst_pct: r3(s.min), best_pct: r3(s.max) });

// Per calendar year of the signal, at one outcome column.
function byYear(kept, col) {
  const groups = new Map();
  kept.forEach((e, k) => {
    if (col[k] !== col[k]) return;
    const y = e.date.slice(0, 4);
    if (!groups.has(y)) groups.set(y, []);
    groups.get(y).push(col[k]);
  });
  return [...groups.entries()].sort().map(([year, v]) => { const st = columnStats(v); return { year, n: st.n, share_positive: r3(st.hit), mean_pct: r3(st.mean), median_pct: r3(st.median) }; });
}

function checkFilters(filters) {
  const problems = [];
  if (filters.rsi && filters.rsi.min === undefined && filters.rsi.max === undefined) problems.push('filters.rsi needs min, max or both');
  for (const [i, m] of (filters.ma || []).entries()) {
    if (!m.side && m.min_pct === undefined && m.max_pct === undefined) problems.push(`filters.ma[${i}] needs side, min_pct or max_pct`);
  }
  if (filters.from_high && filters.from_high.min === undefined && filters.from_high.max === undefined) problems.push('filters.from_high needs min, max or both');
  return problems;
}

// The bars file for a typed symbol: as typed, then BRK.B as BRK-B.
async function loadBars(ctx, requested) {
  const clean = cleanTicker(requested);
  if (!clean) return null;
  for (const symbol of [clean, clean.replace(/^([A-Z]{1,6})\.([A-Z])$/, '$1-$2')]) {
    const bars = await ctx.read(`bars/${symbol}`);
    if (bars && Array.isArray(bars.dates) && bars.dates.length) {
      await ctx.get(`bars/${symbol}`, 'bars');
      return { symbol, bars };
    }
  }
  return null;
}

export async function eventStudy(ctx, args) {
  const filters = args.filters || {};
  const problems = checkFilters(filters);
  if (problems.length) throw new Error(`${problems.join('; ')}.`);
  const found = await loadBars(ctx, args.symbol);
  if (!found) throw new Error(`No daily bars for "${args.symbol}". Bars cover S&P 500 / Nasdaq-100 members and the watchlist (from 2016) and the broad funds such as SPY and QQQ (from 2000); write share classes either way (BRK.B or BRK-B).`);
  const { symbol, bars } = found;

  // Backdrop: the reader's states, or today's for every condition ("like today").
  const conditionsFile = (args.like_today || args.backdrop) ? await ctx.get('trade_conditions', 'backdrop') : await ctx.read('trade_conditions');
  const conditions = conditionsFile?.conditions || [];
  const picks = { ...(args.like_today ? likeToday(conditions) : {}), ...(args.backdrop || {}) };
  for (const [key, state] of Object.entries(picks)) {
    const c = conditions.find((x) => x.key === key);
    if (!c) throw new Error(`Unknown backdrop condition "${key}". Conditions: ${conditions.map((x) => x.key).join(', ') || 'none in this build'}.`);
    if (!(c.options || []).includes(state)) throw new Error(`Backdrop ${key} is one of ${(c.options || []).join(', ')}, not "${state}".`);
  }
  const settings = conditionsFile?.settings || {};
  const minEvents = settings.min_trades ?? MIN_EVENTS;
  const minStretches = settings.min_stretches ?? MIN_STRETCHES;
  const gapDays = settings.stretch_gap_days ?? STRETCH_GAP_DAYS;

  const exclude = args.exclude === undefined ? EXCLUSION_PRESETS.filter((p) => p.on) : EXCLUSION_PRESETS.filter((p) => args.exclude.includes(p.key));
  const trigger = { kind: args.trigger.kind, dir: args.trigger.direction === 'up' ? 1 : -1, size: Math.abs(args.trigger.size) };
  const side = args.side === 'short' ? -1 : 1;
  const costBps = args.cost_bps || 0;
  const gap = args.gap ?? 5;
  const focus = args.focus || 'close5';

  // The study, as event-lab-model.js's study() runs it, with the reader's filters.
  const rows = readings(bars);
  const cols = outcomeColumns(bars);
  const read = custom(bars, filters);
  const eligible = rows.filter((s) => s.i > 0 && (!args.from || s.date >= args.from) && !excluded(s.date, exclude));
  const raw = eligible.filter((s) => fires(s, trigger) && passes(s.i, read) && backdropPasses(s.date, picks, conditions));
  const kept = decluster(raw, gap);
  // As study() does: each event's long outcome, side applied, less the round-trip cost;
  // the baseline is every eligible session's, side applied, with no cost.
  const adjust = (v) => (finite(v) ? side * v - costBps / 100 : null);
  const evCols = Object.fromEntries(PATH_KEYS.map((k) => [k, Float64Array.from(kept, (e) => { const v = adjust(cols[k][e.i]); return v === null ? NaN : v; })]));
  const events = kept;
  const touchedOnly = trigger.kind === 'intraday' ? kept.filter((s) => (trigger.dir < 0 ? s.closeRet > -trigger.size : s.closeRet < trigger.size)).length : null;
  const nStretches = stretches(events.map((e) => ({ signal: e.date })), gapDays);

  const table = PATH_KEYS.map((k) => {
    const ev = columnStats(evCols[k]);
    const base = baselineStats(cols[k], eligible, side);
    return { at: k, events: statsOut(ev), every_session: { n: base.n, share_positive: r3(base.hit), mean_pct: r3(base.mean), median_pct: r3(base.median) },
      mean_minus_every_session_pp: finite(ev.mean) && finite(base.mean) ? r3(ev.mean - base.mean) : null };
  });
  const focusRow = columnStats(evCols[focus]);
  const { share, method } = drawCheck(cols[focus], eligible, side, focusRow.n, focusRow.mean);
  const shareText = share === null ? null : share >= 0.9995 ? 'Over 99.9%' : share < 0.0005 ? 'Under 0.1%' : `${Math.round(share * 1000) / 10}%`;
  const warnings = [];
  if (events.length < minEvents) warnings.push(`only ${events.length} events (the page asks for ${minEvents})`);
  if (nStretches < minStretches) warnings.push(`only ${nStretches} separate stretch${nStretches === 1 ? '' : 'es'} (the page asks for ${minStretches})`);

  // The last session, read the same way, so a reader can see whether today is a trigger day.
  const last = rows.at(-1);
  const latest = last ? {
    date: last.date, low_pct: r3(last.lowRet), high_pct: r3(last.highRet), gap_pct: r3(last.gapRet), close_pct: r3(last.closeRet), sigma: r2(last.sigma),
    rsi6: r2(last.rsi6), vs_50d_pct: r3(last.vs50), vs_200d_pct: r3(last.vs200), from_252d_high_pct: r3(last.fromHigh),
    custom: {
      rsi: read.rsi ? { period: read.rsi.period, value: r2(read.rsi.values[last.i]) } : null,
      ma: read.ma.map((m) => ({ period: m.period, vs_pct: r3(m.values[last.i]) })),
      from_high: read.high ? { window: read.high.window, pct: r3(read.high.values[last.i]) } : null,
    },
    fires_trigger: fires(last, trigger), passes_filters: passes(last.i, read), in_backdrop: backdropPasses(last.date, picks, conditions),
  } : null;

  ctx.note(...(conditionsFile?.notes || []));
  ctx.caveat(
    'Outcomes run from the trigger day\'s close to a later session\'s open or close (open1 = next open). Every filter and backdrop state is read at that close, as known then.',
    'What followed similar days, not a forecast or a trade signal. Compare with every_session, mind the sample size, and expect tails the averages hide.',
  );
  if (warnings.length) ctx.caveat(`Small sample: ${warnings.join(', ')}. Read as anecdote, not evidence.`);
  return {
    symbol, requested: args.symbol, url: ctx.link(`trade/${symbol}`),
    bars: { first: bars.dates[0], last: bars.dates.at(-1), sessions: bars.dates.length },
    applied: {
      trigger: args.trigger, filters, backdrop: picks, like_today: Boolean(args.like_today),
      exclude: exclude.map((p) => ({ key: p.key, label: p.label, from: p.from, to: p.to })),
      from: args.from ?? null, gap, side: side < 0 ? 'short' : 'long', cost_bps: costBps, focus,
    },
    counts: {
      sessions_in_window: eligible.length, window_first: eligible[0]?.date ?? null, window_last: eligible.at(-1)?.date ?? null,
      trigger_days: raw.length, events: events.length, separate_stretches: nStretches, touched_intraday_only: touchedOnly,
    },
    outcomes: table,
    focus: {
      at: focus, random_draw_share: r3(share),
      random_draw_method: method,
      reading: share === null ? 'The random-draw check needs at least one event and fewer events than sessions.'
        : share <= 0.05 ? `Only ${shareText.toLowerCase()} of random draws of ${focusRow.n} sessions averaged as much: these days were followed by better ${focus} returns than chance would give.`
          : share >= 0.95 ? `${shareText} of random draws of ${focusRow.n} sessions averaged at least as much: these days were followed by worse ${focus} returns than chance would give.`
            : `${shareText} of random draws of ${focusRow.n} sessions averaged at least as much: not distinguishable from a random pick of days.`,
      enough_sample: warnings.length === 0, warnings,
      by_year: byYear(kept, evCols[focus]),
    },
    latest_session: latest,
    recent_events: kept.map((e, k) => ({ e, k })).slice(-RECENT).reverse().map(({ e, k }) => ({
      date: e.date, low_pct: r3(e.lowRet), close_pct: r3(e.closeRet), gap_pct: r3(e.gapRet), sigma: r2(e.sigma), rsi6: r2(e.rsi6),
      outcomes_pct: Object.fromEntries(RECENT_KEYS.map((key) => [key, r3(evCols[key][k])])),
    })),
  };
}

const band = (lo, hi, extra = {}) => ({ ...extra, [lo]: { type: 'number' }, [hi]: { type: 'number' } });
const backdropProps = { fed: T.str, rates: T.str, trend: T.str, vix: T.str, breadth: T.str, quadrant: T.str };

export const eventStudyTool = {
  name: 'event_study',
  title: 'Event study',
  description: 'What one ticker did after days like a chosen one (TRADE DESK -> EVENT LAB, same model). trigger: kind intraday (low vs prior close), close, gap (open vs prior close) or sigma (close move in its own 20-day volatility), direction down or up, size in % or sigma. Optional filters read at that close: rsi {period 2-50 (default 6), min, max}; ma: up to 3 moving averages {period 5-250, side above|below, min_pct, max_pct as % distance}; from_high {window 20-756 sessions (default 252), min, max in % (<= 0)}. backdrop: market states (fed HIKING|HOLD|CUTTING, rates, trend, vix, breadth, quadrant; values are the page\'s labels) or like_today: true. Returns events vs every session in the same window at each next open/close to day 20, counts, separate stretches, a random-draw check and a sample-size verdict, results by year, the last session\'s readings (is today a trigger?) and the 10 latest events. Crisis periods are left out by default (exclude: [] keeps all). Bars: members from 2016, broad funds such as SPY from 2000.',
  inputSchema: T.obj({
    symbol: { type: 'string', minLength: 1, maxLength: 15, description: 'Ticker, e.g. NVDA, SPY or BRK.B.' },
    trigger: T.obj({
      kind: { type: 'string', enum: ['intraday', 'close', 'gap', 'sigma'] },
      direction: { type: 'string', enum: ['down', 'up'] },
      size: { type: 'number', minimum: 0.1, maximum: 50, description: '% (or sigma for kind sigma), at least this far.' },
    }, ['kind', 'direction', 'size']),
    filters: T.obj({
      rsi: T.obj(band('min', 'max', { period: { type: 'integer', minimum: 2, maximum: 50 } })),
      ma: { type: 'array', maxItems: 3, items: T.obj(band('min_pct', 'max_pct', { period: { type: 'integer', minimum: 5, maximum: 250 }, side: { type: 'string', enum: ['above', 'below'] } }), ['period']) },
      from_high: T.obj(band('min', 'max', { window: { type: 'integer', minimum: 20, maximum: 756 } })),
    }),
    backdrop: T.obj(backdropProps),
    like_today: { type: 'boolean', description: 'Set every backdrop condition to its state today (backdrop overrides single ones).' },
    exclude: { type: 'array', items: { type: 'string', enum: EXCLUSION_PRESETS.map((p) => p.key) }, description: `Periods to leave out. Default: ${EXCLUSION_PRESETS.filter((p) => p.on).map((p) => p.key).join(', ')}. [] keeps every period.` },
    from: { type: 'string', pattern: '^\\d{4}-\\d{2}-\\d{2}$', description: 'Only trigger days on or after this date.' },
    gap: { type: 'integer', minimum: 0, maximum: 60, description: 'One event per this many sessions (default 5; 0 keeps every trigger day).' },
    side: { type: 'string', enum: ['long', 'short'] },
    cost_bps: { type: 'number', minimum: 0, maximum: 200, description: 'Round-trip cost taken off each event outcome.' },
    focus: { type: 'string', enum: PATH_KEYS, description: 'Outcome for the random-draw check and by-year table, default close5.' },
  }, ['symbol', 'trigger']),
  outputSchema: outputSchema({
    symbol: T.str, url: T.str,
    bars: T.obj({ first: T.str, last: T.str, sessions: { type: 'integer' } }, ['first', 'last', 'sessions']),
    counts: T.obj({ sessions_in_window: { type: 'integer' }, trigger_days: { type: 'integer' }, events: { type: 'integer' }, separate_stretches: { type: 'integer' } }, ['events', 'separate_stretches']),
    outcomes: T.arr(T.obj({ at: T.str, events: T.obj({ n: { type: 'integer' }, mean_pct: T.num, share_positive: T.num }), every_session: T.obj({ mean_pct: T.num }) }, ['at', 'events', 'every_session'])),
    focus: T.obj({ at: T.str, random_draw_share: T.num, enough_sample: T.bool, warnings: T.arr(T.str) }, ['at', 'enough_sample', 'warnings']),
    latest_session: T.maybe(T.obj({ date: T.str, fires_trigger: T.bool, passes_filters: T.bool })),
    recent_events: T.arr(T.obj({ date: T.str, outcomes_pct: { type: 'object' } }, ['date'])),
  }, ['symbol', 'bars', 'counts', 'outcomes', 'focus', 'latest_session', 'recent_events']),
  run: eventStudy,
};
