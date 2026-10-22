// MOVE CHECK: how extreme one close-to-close move is in a ticker's own history.
// Pure functions over the build's ticker closes; tabs/movecheck.js draws them.
//
// A return is taken over `horizon` sessions and skipped when either close is
// missing. The history a move is compared with includes the move's own
// session: a day that equals the move counts, and it is not the "last" day
// named, so the answer is about the earlier history.

export const HORIZONS = [1, 5, 20];
// Sessions in each lookback; null is the whole history.
export const LOOKBACKS = { ALL: null, '5Y': 1260, '1Y': 252 };
export const DEFAULT_GAP = 5;
const YEAR_MS = 365.25 * 864e5;
const MINUS = '−';

const finite = (value) => typeof value === 'number' && Number.isFinite(value);

// Close-to-close returns in percent over `horizon` sessions, dated by the
// closing session. A pair with a missing or zero start close is skipped.
export function returns(dates, close, horizon = 1) {
  if (!Number.isInteger(horizon) || horizon < 1) return [];
  const n = Math.min(dates?.length || 0, close?.length || 0);
  const out = [];
  for (let i = horizon; i < n; i += 1) {
    const start = close[i - horizon];
    const end = close[i];
    if (!finite(start) || !finite(end) || start === 0) continue;
    out.push({ date: dates[i], ret: (end / start - 1) * 100 });
  }
  return out;
}

export function latestMove(dates, close, horizon = 1) {
  const series = returns(dates, close, horizon);
  return series.length ? series[series.length - 1] : null;
}

// The last `sessions` entries of a return series (the whole series for null).
export function lastSessions(series, sessions = null) {
  const clean = (series || []).filter((r) => finite(r.ret));
  return sessions && sessions > 0 && clean.length > sessions ? clean.slice(-sessions) : clean;
}

// How a move compares with the returns in its window. `worse` counts every
// return at or beyond the move in its direction (falls: at or below; rises: at
// or above), the move's own session included. `date` is the move's session; it
// defaults to the last entry, and that entry is never the reported last worse day.
export function checkMove(series, move, { lookbackSessions = null, date = null } = {}) {
  const window = lastSessions(series, lookbackSessions);
  const n = window.length;
  const result = { n, worse: 0, share: null, percentile: null, perYear: null, lastWorse: null, years: null };
  if (!n) return result;
  const first = window[0].date;
  const last = window[n - 1].date;
  const span = (Date.parse(last) - Date.parse(first)) / YEAR_MS;
  result.years = finite(span) && span > 0 ? span : null;
  if (!finite(move)) return result;

  const beyond = (r) => (move < 0 ? r.ret <= move : r.ret >= move);
  let worse = 0;
  let below = 0;
  let equal = 0;
  for (const r of window) {
    if (beyond(r)) worse += 1;
    if (r.ret < move) below += 1;
    else if (r.ret === move) equal += 1;
  }
  const ownDate = date ?? last;
  let lastWorse = null;
  for (let i = n - 1; i >= 0; i -= 1) {
    if (i === n - 1 && window[i].date === ownDate) continue;
    if (beyond(window[i])) { lastWorse = window[i].date; break; }
  }

  return {
    n,
    worse,
    share: worse / n,
    // Mid-rank position of the move among the window's returns, 0 (lowest) to 100 (highest).
    percentile: ((below + equal / 2) / n) * 100,
    perYear: result.years ? worse / result.years : null,
    lastWorse,
    years: result.years,
  };
}

// The move in units of its own volatility: the stdev of the `window` daily
// returns before the move's session, scaled by the square root of the horizon.
// `daily` ends at the move's session. Null when there are too few returns or none varies.
export function sigmaOf(daily, move, window = 20, horizon = 1) {
  if (!finite(move) || !finite(horizon) || horizon < 1 || !Number.isInteger(window) || window < 2) return null;
  const clean = (daily || []).filter((r) => finite(r.ret));
  if (clean.length < window + 1) return null;
  const sample = clean.slice(-(window + 1), -1).map((r) => r.ret);
  const mean = sample.reduce((sum, v) => sum + v, 0) / window;
  const variance = sample.reduce((sum, v) => sum + (v - mean) ** 2, 0) / (window - 1);
  const sd = Math.sqrt(variance);
  if (!(sd > 0)) return null;
  return move / (sd * Math.sqrt(horizon));
}

// Episodes of days beyond the move (in its direction). Days within `gap`
// sessions of the previous one join its episode. Each episode gives its first
// day and its worst day (the furthest move, first occurrence on a tie), oldest first.
export function episodes(series, move, { gap = DEFAULT_GAP } = {}) {
  if (!finite(move) || !Array.isArray(series)) return [];
  const down = move < 0;
  const beyond = (r) => (down ? r.ret <= move : r.ret >= move);
  const out = [];
  let current = null;
  let lastIndex = -Infinity;
  series.forEach((r, i) => {
    if (!finite(r.ret) || !beyond(r)) return;
    if (!current || i - lastIndex > gap) {
      current = { start: r.date, worstDate: r.date, worst: r.ret };
      out.push(current);
    } else if (down ? r.ret < current.worst : r.ret > current.worst) {
      current.worst = r.ret;
      current.worstDate = r.date;
    }
    lastIndex = i;
  });
  return out;
}

function indexOfDate(dates, date) {
  return Array.isArray(dates) ? dates.indexOf(date) : -1;
}

// Percent from `date`'s close to the close `sessions` later. Null when the date
// is unknown, a close is missing, or the target lies beyond the last session.
export function forward(dates, close, date, sessions) {
  const i = indexOfDate(dates, date);
  if (i < 0 || !Number.isInteger(sessions) || sessions < 0) return null;
  const j = i + sessions;
  if (j >= Math.min(dates.length, close?.length || 0)) return null;
  if (!finite(close[i]) || !finite(close[j]) || close[i] === 0) return null;
  return (close[j] / close[i] - 1) * 100;
}

// The lowest close in the `sessions` after `date`, against its close, never above 0.
// Null when the window runs past the last session or holds no close.
export function maxDrawdownAfter(dates, close, date, sessions) {
  const i = indexOfDate(dates, date);
  if (i < 0 || !Number.isInteger(sessions) || sessions < 1) return null;
  const j = i + sessions;
  if (j >= Math.min(dates.length, close?.length || 0)) return null;
  if (!finite(close[i]) || close[i] === 0) return null;
  let low = 0;
  let seen = false;
  for (let k = i + 1; k <= j; k += 1) {
    if (!finite(close[k])) continue;
    seen = true;
    low = Math.min(low, (close[k] / close[i] - 1) * 100);
  }
  return seen ? low : null;
}

// Equal-width bins over the values and any `include` values (the move, so the
// marker falls on the axis). Counts cover the values only.
export function histogram(values, bins = 40, { include = [] } = {}) {
  const count = Number.isInteger(bins) && bins > 0 ? bins : 40;
  const data = (values || []).filter(finite);
  if (!data.length) return { edges: [], counts: [] };
  const extent = [...data, ...include.filter(finite)];
  let lo = Math.min(...extent);
  let hi = Math.max(...extent);
  if (lo === hi) { lo -= 0.5; hi += 0.5; }
  const width = (hi - lo) / count;
  const edges = Array.from({ length: count + 1 }, (_, k) => lo + k * width);
  const counts = new Array(count).fill(0);
  for (const x of data) {
    counts[Math.min(count - 1, Math.max(0, Math.floor((x - lo) / width)))] += 1;
  }
  return { edges, counts };
}

// The bin holding a value, clamped to the axis.
export function binIndex(edges, value) {
  if (!edges || edges.length < 2 || !finite(value)) return null;
  const count = edges.length - 1;
  const width = (edges[count] - edges[0]) / count;
  return Math.min(count - 1, Math.max(0, Math.floor((value - edges[0]) / width)));
}

export function median(values) {
  const sorted = (values || []).filter(finite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

// "+1.2%" or "−3.0%": a true minus, one decimal unless two are needed to tell the move apart.
export function signedPct(value) {
  if (!finite(value)) return '—';
  const digits = Math.abs(value * 10 - Math.round(value * 10)) < 1e-9 ? 1 : 2;
  const size = Math.abs(value).toFixed(digits);
  if (Number(size) === 0) return `${size}%`;
  return `${value < 0 ? MINUS : '+'}${size}%`;
}

export function horizonLabel(horizon) {
  return horizon === 1 ? '1 day' : `${horizon} sessions`;
}

export function ordinal(value) {
  const k = Math.round(value);
  const tens = k % 100;
  if (tens >= 11 && tens <= 13) return `${k}th`;
  return `${k}${{ 1: 'st', 2: 'nd', 3: 'rd' }[k % 10] || 'th'}`;
}

function percentileText(value) {
  if (value < 1) return 'under the 1st percentile';
  if (value > 99) return 'over the 99th percentile';
  return `the ${ordinal(value)} percentile`;
}

// Years in words; a window shorter than a year reads as a fraction.
function yearsText(years) {
  if (!finite(years)) return 'the history';
  return years >= 1 ? `${Math.round(years)} years` : `${years.toFixed(1)} years`;
}

function perYearText(value) {
  return value >= 2 ? `${Math.round(value)}` : value.toFixed(1);
}

// The page's headline, from the whole-history check of the move. Figures in
// the text are absent-safe: a missing figure reads as a dash, never NaN.
export function moveSentence({ ticker, horizon, move, date, all }) {
  const head = `${ticker} ${signedPct(move)} over ${horizonLabel(horizon)}${date ? ` (${date})` : ''}.`;
  if (!all || !all.n || !finite(move)) return `${head} Not enough history to place this move.`;
  const down = move < 0;
  const verb = down ? 'fell' : 'rose';
  if (!all.worse) return `${head} In ${yearsText(all.years)} of history no day ${verb} this far.`;
  const sharePct = `${(all.share * 100).toFixed(1)}%`;
  const detail = [
    `(${sharePct}, ${percentileText(all.percentile)})`,
    all.perYear === null ? null : `about ${perYearText(all.perYear)} a year`,
  ].filter(Boolean).join(', ');
  const last = all.lastWorse ? `the last was ${all.lastWorse}` : 'no earlier day was that far';
  const count = `${all.worse.toLocaleString('en-US')} of ${all.n.toLocaleString('en-US')} days`;
  const years = all.years === null ? '' : `In ${yearsText(all.years)} of history `;
  return `${head} ${years}${count} ${verb} further ${detail}; ${last}.`;
}
