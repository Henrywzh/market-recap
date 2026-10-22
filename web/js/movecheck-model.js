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
// Forward returns after an episode's worst day, in sessions.
export const FORWARD_SESSIONS = [1, 5, 20];
// Bucket edges for SIMILAR SETUPS: VIX level, and the drop from the 1Y high in percent.
export const VIX_EDGES = [15, 20, 30];
export const DRAWDOWN_EDGES = [5, 10, 20];
// Fewer episodes than this in a bucket are too few to read.
export const SETUP_MIN = 5;
const YEAR_MS = 365.25 * 864e5;
const DAY_MS = 864e5;
// How far back a VIX level may be taken when its own date has none.
const CALENDAR_SLACK_DAYS = 5;
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

// Years in words; a window shorter than a year reads as a fraction.
function yearsText(years) {
  if (!finite(years)) return 'the history';
  return years >= 1 ? `${Math.round(years)} years` : `${years.toFixed(1)} years`;
}

function perYearText(value) {
  return value >= 2 ? `${Math.round(value)}` : value.toFixed(1);
}

// Index of the last date on or before `date` (ISO dates sort by day), or -1.
function lastOnOrBefore(dates, date) {
  let lo = 0;
  let hi = dates.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (dates[mid] <= date) { found = mid; lo = mid + 1; } else { hi = mid - 1; }
  }
  return found;
}

function sessionIndex(dates, date) {
  return Array.isArray(dates) ? dates.indexOf(date) : -1;
}

// Percent the close the session before `date` sits below the highest close in
// the `lookback` sessions ending there (0 or below). Null unless the whole
// window is in the build, so a short history never gives a partial high.
export function drawdownBefore(dates, close, date, lookback = 252) {
  const i = sessionIndex(dates, date) - 1;
  if (i < 0 || !Number.isInteger(lookback) || lookback < 1 || i - lookback + 1 < 0) return null;
  if (!finite(close[i])) return null;
  let high = -Infinity;
  for (let k = i - lookback + 1; k <= i; k += 1) {
    if (finite(close[k])) high = Math.max(high, close[k]);
  }
  if (!finite(high) || high === 0) return null;
  return (close[i] / high - 1) * 100;
}

// Percent change over the `sessions` before `date`'s session: from the close
// `sessions` back to the close the session before. Null when either is missing.
export function returnBefore(dates, close, date, sessions = 20) {
  const i = sessionIndex(dates, date);
  if (i < 0 || !Number.isInteger(sessions) || sessions < 1) return null;
  const end = i - 1;
  const start = i - 1 - sessions;
  if (start < 0 || !finite(close[end]) || !finite(close[start]) || close[start] === 0) return null;
  return (close[end] / close[start] - 1) * 100;
}

// The value on `date`; else the last one before it within five calendar days
// (a VIX close on a day the index did not publish); else null.
export function valueOn(dates, values, date) {
  if (!Array.isArray(dates) || !Array.isArray(values) || !dates.length) return null;
  const day = Date.parse(date);
  if (!Number.isFinite(day)) return null;
  for (let j = lastOnOrBefore(dates, date); j >= 0; j -= 1) {
    if (day - Date.parse(dates[j]) > CALENDAR_SLACK_DAYS * DAY_MS) break;
    if (finite(values[j])) return values[j];
  }
  return null;
}

// Mid-rank percentile (0 lowest, 100 highest) of `value` among the finite
// `values`, ties counted half. Pass the history up to the date it is read on.
export function percentileOf(values, value) {
  if (!finite(value)) return null;
  const data = (values || []).filter(finite);
  if (!data.length) return null;
  let below = 0;
  let equal = 0;
  for (const x of data) {
    if (x < value) below += 1;
    else if (x === value) equal += 1;
  }
  return ((below + equal / 2) / data.length) * 100;
}

// The context of an episode's day: the ticker's drop from its 1Y high and its
// prior 20-session return, and the VIX level, its percentile since the VIX
// history began and its change from the session before. `vix` is
// { dates, close } or null; a missing part is null.
export function contextOn({ dates, close, vix = null, date }) {
  const usable = vix && Array.isArray(vix.dates) && Array.isArray(vix.close) ? vix : null;
  const i = sessionIndex(dates, date);
  const previous = i > 0 ? dates[i - 1] : null;
  const level = usable ? valueOn(usable.dates, usable.close, date) : null;
  const before = usable && previous ? valueOn(usable.dates, usable.close, previous) : null;
  const k = level === null ? -1 : lastOnOrBefore(usable.dates, date);
  return {
    fromHigh: drawdownBefore(dates, close, date),
    prior20: returnBefore(dates, close, date, 20),
    vix: level,
    vixPct: k < 0 ? null : percentileOf(usable.close.slice(0, k + 1), level),
    vixChange: level !== null && before !== null ? level - before : null,
  };
}

// Which bucket a value is in: how many of the edges it reaches (0 below the first).
export function bucketOf(value, edges) {
  if (!finite(value) || !Array.isArray(edges)) return null;
  return edges.filter((edge) => value >= edge).length;
}

// The drop from the 1Y high as a bucket: the size of the drop, so 0 is within 5%.
export function drawdownBucket(fromHigh) {
  return finite(fromHigh) ? bucketOf(-fromHigh, DRAWDOWN_EDGES) : null;
}

function share(values) {
  const data = values.filter(finite);
  return data.length ? data.filter((v) => v > 0).length / data.length : null;
}

// n, and the median and the share positive of the +5 and +20 session returns,
// and the median max drawdown, over rows (episodes).
function summarize(rows) {
  const at = (session) => rows.map((r) => r.forward[FORWARD_SESSIONS.indexOf(session)]);
  return {
    n: rows.length,
    median5: median(at(5)),
    positive5: share(at(5)),
    median20: median(at(20)),
    positive20: share(at(20)),
    medianDrawdown: median(rows.map((r) => r.drawdown)),
  };
}

// Episodes whose VIX bucket and drop-from-high bucket match today's, and all
// episodes for comparison. Rows carry fromHigh, vix, forward (FORWARD_SESSIONS
// order) and drawdown; `today` carries fromHigh and vix.
export function similarSetups(rows, today) {
  const vixBucket = bucketOf(today?.vix, VIX_EDGES);
  const ddBucket = drawdownBucket(today?.fromHigh);
  const matches = (r) => vixBucket !== null && ddBucket !== null
    && bucketOf(r.vix, VIX_EDGES) === vixBucket && drawdownBucket(r.fromHigh) === ddBucket;
  return {
    vixBucket,
    drawdownBucket: ddBucket,
    matched: summarize((rows || []).filter(matches)),
    all: summarize(rows || []),
  };
}

// The page's headline, from the whole-history check of the move. Figures in
// the text are absent-safe: a missing figure reads as a dash, never NaN.
export function moveSentence({ ticker, horizon, move, date, all }) {
  const head = `${ticker} ${signedPct(move)} over ${horizonLabel(horizon)}${date ? ` (${date})` : ''}.`;
  if (!all || !all.n || !finite(move)) return `${head} Not enough history to place this move.`;
  const down = move < 0;
  const verb = down ? 'fell' : 'rose';
  if (!all.worse) return `${head} In ${yearsText(all.years)} of history no day ${verb} this far.`;
  // "Only" where the move is rare; a common one is stated plainly.
  const shareText = `${(all.share * 100).toFixed(1)}%`;
  const sharePhrase = all.share < 0.001 ? 'Fewer than 0.1%' : all.share < 0.05 ? `Only ${shareText}` : shareText;
  const span = all.years === null ? 'of trading days' : `of trading days in ${yearsText(all.years)}`;
  const rate = all.perYear === null ? '' : ` (about ${perYearText(all.perYear)} a year)`;
  const last = all.lastWorse ? `the last was ${all.lastWorse}` : 'no earlier day was that far';
  return `${head} ${sharePhrase} ${span} ${verb} this far or further${rate}; ${last}.`;
}
