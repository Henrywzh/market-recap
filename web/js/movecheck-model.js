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
// The worst drawdown is read over this many sessions after the day.
export const DRAWDOWN_SESSIONS = 20;
// Bucket edges for SIMILAR SETUPS: VIX level, and the drop from the 1Y high in percent.
export const VIX_EDGES = [15, 20, 30];
export const DRAWDOWN_EDGES = [5, 10, 20];
// Fewer episodes than this in a bucket are too few to read.
export const SETUP_MIN = 5;
// The episode bootstrap: resamples, a fixed seed so every run gives the same interval, the
// fewest episodes that get an interval at all, and the count below which it is called wide.
export const BOOTSTRAP_RESAMPLES = 2000;
export const BOOTSTRAP_SEED = 1;
export const INTERVAL_MIN = 5;
export const INTERVAL_WIDE = 20;
// Overnight gaps: the percentiles read off the data, and the size (percent) that counts as large.
export const GAP_PERCENTILES = [1, 5, 50, 95, 99];
export const GAP_LARGE = 2;
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

// The same two figures from a session's index, so a whole history can be read in one pass.
function forwardFrom(dates, close, i, sessions) {
  const j = i + sessions;
  if (j >= Math.min(dates.length, close?.length || 0)) return null;
  if (!finite(close[i]) || !finite(close[j]) || close[i] === 0) return null;
  return (close[j] / close[i] - 1) * 100;
}

function drawdownFrom(dates, close, i, sessions) {
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

// Percent from `date`'s close to the close `sessions` later. Null when the date
// is unknown, a close is missing, or the target lies beyond the last session.
export function forward(dates, close, date, sessions) {
  const i = indexOfDate(dates, date);
  if (i < 0 || !Number.isInteger(sessions) || sessions < 0) return null;
  return forwardFrom(dates, close, i, sessions);
}

// The lowest close in the `sessions` after `date`, against its close, never above 0.
// Null when the window runs past the last session or holds no close.
export function maxDrawdownAfter(dates, close, date, sessions) {
  const i = indexOfDate(dates, date);
  if (i < 0 || !Number.isInteger(sessions) || sessions < 1) return null;
  return drawdownFrom(dates, close, i, sessions);
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

// The follow-up figures over rows (episodes or start days): at each FORWARD_SESSIONS
// horizon the median and the share up, each over the rows that have that return, and
// the median worst drawdown. `n` counts the values behind each figure.
export function followUp(rows) {
  const list = rows || [];
  const column = (values) => {
    const data = values.filter(finite);
    return { n: data.length, median: median(data), share: share(data) };
  };
  const drawdown = list.map((r) => r.drawdown).filter(finite);
  return {
    n: list.length,
    forward: FORWARD_SESSIONS.map((_, k) => column(list.map((r) => r.forward[k]))),
    drawdown: { n: drawdown.length, median: median(drawdown) },
  };
}

// Every start day, read as an episode is: its forward returns and worst drawdown.
// Used as the baseline: what followed on any day in the same window.
export function dayRows(dates, close, days) {
  const at = new Map((dates || []).map((d, i) => [d, i]));
  return (days || []).map((date) => {
    const i = at.has(date) ? at.get(date) : -1;
    return {
      date,
      forward: FORWARD_SESSIONS.map((s) => (i < 0 ? null : forwardFrom(dates, close, i, s))),
      drawdown: i < 0 ? null : drawdownFrom(dates, close, i, DRAWDOWN_SESSIONS),
    };
  });
}

// Episodes minus all days, figure by figure, in percentage points: a share's gap
// is scaled from a fraction to points. Null wherever either side is missing.
export function compareFollowUp(episodes, baseline) {
  const diff = (x, y, scale = 1) => (finite(x) && finite(y) ? (x - y) * scale : null);
  return {
    forward: episodes.forward.map((f, k) => ({
      median: diff(f.median, baseline.forward[k].median),
      share: diff(f.share, baseline.forward[k].share, 100),
    })),
    drawdown: diff(episodes.drawdown.median, baseline.drawdown.median),
  };
}

// A small seeded PRNG (mulberry32): the same seed gives the same resamples on every run.
function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// The value at percentile p (0–100) of an ascending array, interpolated between neighbours.
function quantile(sorted, p) {
  const at = ((sorted.length - 1) * p) / 100;
  const lo = Math.floor(at);
  const hi = Math.ceil(at);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (at - lo);
}

// The 5th and 95th percentiles of a list of values, or null for none.
function interval(values) {
  if (!values.length) return null;
  const sorted = Float64Array.from(values).sort();
  return [quantile(sorted, 5), quantile(sorted, 95)];
}

// A 90% interval for the median and the share up at each horizon, from resampling
// the episodes with replacement. Episodes are the independent events, so they are
// what is resampled. Null with fewer than INTERVAL_MIN episodes.
export function bootstrapFollowUp(rows, { resamples = BOOTSTRAP_RESAMPLES, seed = BOOTSTRAP_SEED } = {}) {
  const list = rows || [];
  const n = list.length;
  if (n < INTERVAL_MIN) return null;
  const rng = mulberry32(seed);
  // NaN marks a missing return; typed arrays keep the resamples fast enough to rerun on each check.
  const columns = FORWARD_SESSIONS.map((_, k) => Float64Array.from(list, (r) => (finite(r.forward[k]) ? r.forward[k] : NaN)));
  const buffer = new Float64Array(n);
  const medians = FORWARD_SESSIONS.map(() => []);
  const shares = FORWARD_SESSIONS.map(() => []);
  for (let b = 0; b < resamples; b += 1) {
    const picks = Array.from({ length: n }, () => Math.floor(rng() * n));
    FORWARD_SESSIONS.forEach((_, k) => {
      let count = 0;
      let up = 0;
      for (const p of picks) {
        const v = columns[k][p];
        if (Number.isNaN(v)) continue;
        buffer[count] = v;
        count += 1;
        if (v > 0) up += 1;
      }
      if (!count) return;
      const sorted = buffer.subarray(0, count).sort();
      const mid = count >> 1;
      medians[k].push(count % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2);
      shares[k].push(up / count);
    });
  }
  return {
    n,
    forward: FORWARD_SESSIONS.map((_, k) => ({ median: interval(medians[k]), share: interval(shares[k]) })),
  };
}

// Years the episodes' worst days fall in, first and last; null with none.
export function episodeYears(rows) {
  const years = (rows || []).map((r) => Number(String(r.worstDate).slice(0, 4))).filter(finite);
  return years.length ? { first: Math.min(...years), last: Math.max(...years) } : null;
}

// The ISO day halfway between two ISO days, or null when either is not a date.
export function midDate(from, to) {
  const a = Date.parse(from);
  const b = Date.parse(to);
  if (!finite(a) || !finite(b)) return null;
  return new Date((a + b) / 2).toISOString().slice(0, 10);
}

// The episodes before the lookback's middle date, and on or after it, by their worst day.
// Both are empty when the lookback has no usable first and last session.
export function halves(rows, from, to) {
  const middle = midDate(from, to);
  if (!middle) return { middle: null, earlier: [], later: [] };
  return {
    middle,
    earlier: (rows || []).filter((r) => r.worstDate < middle),
    later: (rows || []).filter((r) => r.worstDate >= middle),
  };
}

// The summary the episode table and the setups use: n and the +5 and +20 figures
// and the median drawdown, over rows (episodes).
function summarize(rows) {
  const f = followUp(rows);
  return {
    n: f.n,
    median5: f.forward[1].median,
    positive5: f.forward[1].share,
    median20: f.forward[2].median,
    positive20: f.forward[2].share,
    medianDrawdown: f.drawdown.median,
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

// Overnight gap in percent: the open against the prior session's close. A session
// with a missing open or close, or a zero prior close, has no gap.
export function overnightGaps(bars) {
  const { dates, open, close } = bars || {};
  if (!Array.isArray(dates) || !Array.isArray(open) || !Array.isArray(close)) return [];
  const n = Math.min(dates.length, open.length, close.length);
  const out = [];
  for (let i = 1; i < n; i += 1) {
    const prior = close[i - 1];
    if (!finite(open[i]) || !finite(prior) || prior === 0) continue;
    out.push({ date: dates[i], gap: (open[i] / prior - 1) * 100 });
  }
  return out;
}

// The empirical gap percentiles, the share with a gap beyond `threshold` either way,
// the five largest gaps up and down, and where the latest session's gap sits. Null with no gaps.
export function gapSummary(gaps, { threshold = GAP_LARGE } = {}) {
  const data = (gaps || []).filter((g) => finite(g.gap));
  if (!data.length) return null;
  const sorted = Float64Array.from(data.map((g) => g.gap)).sort();
  const latest = data[data.length - 1];
  return {
    n: data.length,
    from: data[0].date,
    to: latest.date,
    percentiles: GAP_PERCENTILES.map((p) => ({ p, value: quantile(sorted, p) })),
    shareLarge: data.filter((g) => Math.abs(g.gap) > threshold).length / data.length,
    up: data.filter((g) => g.gap > 0).sort((a, b) => b.gap - a.gap).slice(0, 5),
    down: data.filter((g) => g.gap < 0).sort((a, b) => a.gap - b.gap).slice(0, 5),
    latest: { date: latest.date, gap: latest.gap, percentile: percentileOf(data.map((g) => g.gap), latest.gap) },
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
