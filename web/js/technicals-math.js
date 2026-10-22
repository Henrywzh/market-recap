// Technical indicators, one definition each.
//
// The TECHNICALS tab lets the reader choose the moving averages, the slope
// window and the period, so the indicators are computed here, in the browser,
// from the close history the build bakes -- and only here. A Python copy for
// the defaults and a JavaScript copy for the controls would be two claims
// about what a 200-day z-score is.
//
// Pure functions over plain arrays; no DOM. `node --test web/js` exercises
// them. Arrays are aligned with the dates they came with, and a value that
// cannot be formed yet is null, never 0 or the first available number.

export const TRADING_DAYS_PER_YEAR = 252;

// Bands are labels for a distance, not predictions. The wording stays
// descriptive ("deeply extended") rather than directional ("sell").
export const ZSCORE_BANDS = [
  { low: -Infinity, high: -2.0, label: '< -2.0', verdict: 'DEEPLY OVERSOLD' },
  { low: -2.0, high: -1.5, label: '-2.0 to -1.5', verdict: 'OVERSOLD' },
  { low: -1.5, high: -0.5, label: '-1.5 to -0.5', verdict: 'BELOW TREND' },
  { low: -0.5, high: 0.5, label: '-0.5 to 0.5', verdict: 'AT TREND' },
  { low: 0.5, high: 1.5, label: '0.5 to 1.5', verdict: 'ABOVE TREND' },
  { low: 1.5, high: 2.0, label: '1.5 to 2.0', verdict: 'DEEPLY OVERBOUGHT' },
  { low: 2.0, high: Infinity, label: '> 2.0', verdict: 'EXTREMELY OVERBOUGHT' },
];

// Annualised slope of the long average, in percent, and what it is called.
// Checked in order; the first threshold the slope clears names it.
export const SLOPE_VERDICTS = [
  { above: 20, verdict: 'STRONG UPTREND' },
  { above: 2, verdict: 'UPTREND' },
  { above: -2, verdict: 'FLAT' },
  { above: -20, verdict: 'DOWNTREND' },
  { above: -Infinity, verdict: 'STRONG DOWNTREND' },
];

const finite = (v) => v !== null && v !== undefined && Number.isFinite(v);

export function sma(values, window) {
  const out = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i += 1) {
    sum += values[i];
    if (i >= window) sum -= values[i - window];
    if (i + 1 >= window) out[i] = sum / window;
  }
  return out;
}

// Sample standard deviation (n - 1), the pandas default the band was defined with.
export function rollingStd(values, window) {
  const out = new Array(values.length).fill(null);
  if (window < 2) return out;
  for (let i = window - 1; i < values.length; i += 1) {
    let mean = 0;
    for (let j = i - window + 1; j <= i; j += 1) mean += values[j];
    mean /= window;
    let squares = 0;
    for (let j = i - window + 1; j <= i; j += 1) squares += (values[j] - mean) ** 2;
    out[i] = Math.sqrt(squares / (window - 1));
  }
  return out;
}

// Exponential average seeded on the first value (pandas `adjust=False`).
export function ema(values, span) {
  const k = 2 / (span + 1);
  const out = [];
  values.forEach((v, i) => out.push(i === 0 ? v : v * k + out[i - 1] * (1 - k)));
  return out;
}

// MACD with explicit spans. No defaults: 12/26/9 and 8/17/9 are different
// indicators that plot on the same axis.
export function macd(values, { fast, slow, signal }) {
  const fastLine = ema(values, fast);
  const slowLine = ema(values, slow);
  const line = fastLine.map((v, i) => v - slowLine[i]);
  const signalLine = ema(line, signal);
  return { macd: line, signal: signalLine, histogram: line.map((v, i) => v - signalLine[i]) };
}

// Distance from the long average measured in that average's own noise.
export function zscore(values, window) {
  const mean = sma(values, window);
  const sigma = rollingStd(values, window);
  return values.map((v, i) => (finite(mean[i]) && sigma[i] > 0 ? (v - mean[i]) / sigma[i] : null));
}

export function band(values, window, sigmaMultiple) {
  const mean = sma(values, window);
  const sigma = rollingStd(values, window);
  return {
    upper: mean.map((m, i) => (finite(m) && finite(sigma[i]) ? m + sigmaMultiple * sigma[i] : null)),
    lower: mean.map((m, i) => (finite(m) && finite(sigma[i]) ? m - sigmaMultiple * sigma[i] : null)),
  };
}

export function bandFor(value) {
  if (!finite(value)) return null;
  return ZSCORE_BANDS.find((b) => value >= b.low && value < b.high) || null;
}

export function slopeVerdict(annualisedPct) {
  if (!finite(annualisedPct)) return null;
  return SLOPE_VERDICTS.find((s) => annualisedPct > s.above).verdict;
}

// Per-day percent change of an average over `lookback` sessions: "is the
// trend turning".
export function smaSlope(values, window, lookback) {
  const average = sma(values, window);
  return average.map((v, i) => {
    const before = i >= lookback ? average[i - lookback] : null;
    return finite(v) && finite(before) && before !== 0 ? ((v / before - 1) / lookback) * 100 : null;
  });
}

// Slope of the average over the last `lookback` sessions, compounded to a year.
export function annualisedSlope(values, window, lookback) {
  const average = sma(values, window);
  const end = average[average.length - 1];
  const start = average[average.length - 1 - lookback];
  if (!finite(end) || !finite(start) || start <= 0) return null;
  const daily = (end / start) ** (1 / lookback) - 1;
  return ((1 + daily) ** TRADING_DAYS_PER_YEAR - 1) * 100;
}

function median(sorted) {
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

// What followed each z-score band in this sample. A description of history
// with its row count attached, not a probability. The last `horizon`
// sessions are excluded: their forward window has not finished.
export function forwardReturnByBand(values, zWindow, horizon) {
  const z = zscore(values, zWindow);
  const buckets = ZSCORE_BANDS.map(() => []);
  for (let i = 0; i + horizon < values.length; i += 1) {
    const b = bandFor(z[i]);
    if (!b) continue;
    buckets[ZSCORE_BANDS.indexOf(b)].push((values[i + horizon] / values[i] - 1) * 100);
  }
  return ZSCORE_BANDS.map((b, k) => {
    const returns = buckets[k];
    if (!returns.length) return { band: b.label, count: 0, mean: null, median: null, hitRate: null };
    const sorted = [...returns].sort((x, y) => x - y);
    return {
      band: b.label,
      count: returns.length,
      mean: returns.reduce((s, v) => s + v, 0) / returns.length,
      median: median(sorted),
      hitRate: (returns.filter((v) => v > 0).length / returns.length) * 100,
    };
  });
}

// Two close histories on their shared dates, as a ratio.
export function ratioSeries(left, right) {
  const denominators = new Map(right.dates.map((d, i) => [d, right.close[i]]));
  const dates = [];
  const ratio = [];
  left.dates.forEach((d, i) => {
    const denominator = denominators.get(d);
    if (finite(denominator) && denominator !== 0 && finite(left.close[i])) {
      dates.push(d);
      ratio.push(left.close[i] / denominator);
    }
  });
  return { dates, ratio };
}

// Index of the first session shown for a display period: every indicator is
// computed on the full history first, so a 200-day average is already formed
// on the first day of a 1Y chart. `sessions === null` means YTD.
export function viewStart(dates, sessions) {
  if (sessions === null) {
    const year = dates[dates.length - 1].slice(0, 4);
    const first = dates.findIndex((d) => d.slice(0, 4) === year);
    return Math.max(0, first - 1);
  }
  return Math.max(0, dates.length - 1 - sessions);
}

// "20, 50 200" -> [20, 50, 200]; rejects anything that is not a positive whole number.
export function parseWindows(text, { max }) {
  const parts = String(text).split(/[\s,]+/).filter(Boolean);
  const windows = parts.map(Number);
  if (!windows.length || windows.some((w) => !Number.isInteger(w) || w < 2 || w > max)) {
    throw new Error(`Moving-average periods must be whole numbers from 2 to ${max}`);
  }
  return [...new Set(windows)].sort((a, b) => a - b);
}

// Wilder's RSI, seeded with a simple average of the first `period` changes
// (the classic definition; pandas' ewm seeds differently). The first value
// needs `period` price changes. src/market_recap/compute/oversold.py holds the
// same definition for TODAY's watch list, and the parity test keeps them equal.
export function rsi(values, period) {
  const out = new Array(values.length).fill(null);
  if (values.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i += 1) {
    const change = values[i] - values[i - 1];
    gain += Math.max(change, 0);
    loss += Math.max(-change, 0);
  }
  gain /= period;
  loss /= period;
  const level = (g, l) => (l === 0 ? (g === 0 ? 50 : 100) : 100 - 100 / (1 + g / l));
  out[period] = level(gain, loss);
  for (let i = period + 1; i < values.length; i += 1) {
    const change = values[i] - values[i - 1];
    gain = ((period - 1) * gain + Math.max(change, 0)) / period;
    loss = ((period - 1) * loss + Math.max(-change, 0)) / period;
    out[i] = level(gain, loss);
  }
  return out;
}

// Lines are labels for how stretched a fall is, not rebound calls: below 20
// was not followed by clearly different returns from below 30 in the lab
// (quantamental-lab docs/rsi6_below20_v1.md). Deepest first.
export const RSI_LINES = [
  { below: 20, verdict: 'DEEPLY OVERSOLD' },
  { below: 30, verdict: 'OVERSOLD' },
];

// The latest RSI, the deepest line it is under, and for how many closes in a row.
export function rsiReading(series, lines = RSI_LINES) {
  const last = series.length - 1;
  if (last < 0 || !finite(series[last])) return null;
  const value = series[last];
  const hit = [...lines].sort((a, b) => a.below - b.below).find((l) => value < l.below);
  if (!hit) return { value, line: null, verdict: null, days: 0 };
  let days = 0;
  for (let i = last; i >= 0 && finite(series[i]) && series[i] < hit.below; i -= 1) days += 1;
  return { value, line: hit.below, verdict: hit.verdict, days };
}

// The display windows the TECHNICALS controls offer, in sessions. YTD is
// calendar-based (see viewStart); MAX is the whole history.
export const RANGES = [
  { key: '1M', sessions: 21 },
  { key: '3M', sessions: 63 },
  { key: '6M', sessions: 126 },
  { key: 'YTD', sessions: null },
  { key: '1Y', sessions: TRADING_DAYS_PER_YEAR },
  { key: '2Y', sessions: TRADING_DAYS_PER_YEAR * 2 },
  { key: '3Y', sessions: TRADING_DAYS_PER_YEAR * 3 },
  { key: '5Y', sessions: TRADING_DAYS_PER_YEAR * 5 },
  { key: '10Y', sessions: TRADING_DAYS_PER_YEAR * 10 },
  { key: 'MAX', sessions: Infinity },
];

// First index shown for a range key, on the same rule as viewStart.
export function rangeStart(dates, key) {
  const range = RANGES.find((r) => r.key === key);
  if (!range) throw new Error(`unknown range ${key}`);
  return viewStart(dates, range.sessions);
}

// True when a range's first shown session is on or after the first bar of a
// shorter series (candles cover fewer sessions than the close history).
export function rangeWithin(dates, key, firstDate) {
  const start = rangeStart(dates, key);
  return dates.length > 0 && dates[start] >= firstDate;
}

// Percent change of a value against the one before it; null when either is missing.
export function change(values, index) {
  const now = values[index];
  const before = index > 0 ? values[index - 1] : null;
  return finite(now) && finite(before) && before !== 0 ? (now / before - 1) * 100 : null;
}

// The y-axis range for a window of sessions [from, to] (inclusive): the lowest
// and highest of the `low` and `high` arrays and of each line, missing values
// skipped, padded by `pad` of the span on each side. Null when nothing is finite.
export function visibleExtent({ low = [], high = [], lines = [] }, from, to, pad = 0) {
  const a = Math.max(0, from);
  const seen = [...low.slice(a, to + 1), ...high.slice(a, to + 1), ...lines.flatMap((line) => line.slice(a, to + 1))]
    .filter(finite);
  if (!seen.length) return null;
  const min = Math.min(...seen);
  const max = Math.max(...seen);
  const span = max - min || Math.abs(max) || 1;
  return { min: min - pad * span, max: max + pad * span };
}

// Highest and lowest value over the last `window` sessions, missing sessions
// skipped. Null until the history holds a full window.
export function stats52w(values, window = TRADING_DAYS_PER_YEAR) {
  if (values.length < window) return { high: null, low: null };
  const recent = values.slice(-window).filter(finite);
  if (!recent.length) return { high: null, low: null };
  return { high: Math.max(...recent), low: Math.min(...recent) };
}

// Today's volume over the mean of the `n` sessions before it. Null when today
// or any of those sessions is missing.
export function relVolume(volume, n = 20) {
  const last = volume.length - 1;
  if (last < n || !finite(volume[last])) return null;
  const prior = volume.slice(last - n, last);
  if (!prior.every(finite)) return null;
  const average = prior.reduce((s, v) => s + v, 0) / n;
  return average > 0 ? volume[last] / average : null;
}
