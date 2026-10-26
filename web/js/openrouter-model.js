// The OpenRouter card's arithmetic. Pure: no DOM and no fmt.js import, so
// node can run the tests. Series are daily and oldest first. A null is a day
// with no figure; it is never counted as zero.

const DAY_MS = 86400000;
// Calendar days back from the last date: the same cuts range.js makes for the
// page's own history switch, so the same label means the same window here.
const RANGE_DAYS = { '1M': 31, '3M': 92, '6M': 182, '1Y': 365 };
export const RANGES = ['1M', '3M', '6M', 'YTD', '1Y'];

const isNumber = (v) => typeof v === 'number' && Number.isFinite(v);

// Trailing mean over seven days. Null until seven days exist, and null
// wherever any of the seven is missing: a gap is not a zero.
export function rolling7(values) {
  return values.map((_, i) => {
    if (i < 6) return null;
    const window = values.slice(i - 6, i + 1);
    if (!window.every(isNumber)) return null;
    return window.reduce((a, b) => a + b, 0) / 7;
  });
}

const monthOf = (date) => date.slice(0, 7);

function nextMonth(month) {
  const [y, m] = month.split('-').map(Number);
  return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`;
}

// Every calendar month from the first date's to the last date's, gaps included.
export function monthSpan(dates) {
  if (!dates || !dates.length) return [];
  const last = monthOf(dates[dates.length - 1]);
  const out = [];
  for (let m = monthOf(dates[0]); m <= last; m = nextMonth(m)) out.push(m);
  return out;
}

// Calendar days in a 'YYYY-MM' month.
export function daysInMonth(month) {
  const [y, m] = month.split('-').map(Number);
  return new Date(Date.UTC(y, m, 0)).getUTCDate();
}

// Per calendar month: the mean of the days that have a figure, how many
// days have one, and whether that is fewer than every calendar day. A month
// with no figure at all has a null mean and is partial.
function monthlyMeans(dates, values) {
  return monthSpan(dates).map((month) => {
    let sum = 0;
    let days = 0;
    dates.forEach((date, i) => {
      const v = values ? values[i] : undefined;
      if (monthOf(date) === month && isNumber(v)) {
        sum += v;
        days += 1;
      }
    });
    return { month, mean: days ? sum / days : null, days, partial: days < daysInMonth(month) };
  });
}

// Estimated annual run-rate per month, in $ millions a year. dailyRevenueK is
// in $ thousands a day, so the month's mean day times 365, over 1000.
export function monthlyArr(dates, dailyRevenueK) {
  const rows = monthlyMeans(dates, dailyRevenueK);
  return {
    months: rows.map((r) => r.month),
    arrM: rows.map((r) => (r.mean === null ? null : (r.mean * 365) / 1000)),
    partial: rows.map((r) => r.partial),
    days: rows.map((r) => r.days),
  };
}

// Average tokens per day in each month, in billions a day. No annualising.
export function monthlyAvgTokens(dates, dailyTokensB) {
  const rows = monthlyMeans(dates, dailyTokensB);
  return {
    months: rows.map((r) => r.month),
    avgB: rows.map((r) => r.mean),
    partial: rows.map((r) => r.partial),
  };
}

// Index of the first date inside the range, cut from the last date. YTD runs
// from 1 January of the last date's year. Unknown labels and MAX give 0.
export function rangeCut(dates, label) {
  if (!dates || !dates.length) return 0;
  const last = dates[dates.length - 1];
  let cut;
  if (label === 'YTD') cut = `${last.slice(0, 4)}-01-01`;
  else if (Object.hasOwn(RANGE_DAYS, label)) cut = new Date(Date.parse(last) - RANGE_DAYS[label] * DAY_MS).toISOString().slice(0, 10);
  else return 0;
  const index = dates.findIndex((d) => d >= cut);
  return index < 0 ? 0 : index;
}

// Values for a log axis: anything not above zero is a gap, never a zero.
export function logValues(values) {
  return values.map((v) => (isNumber(v) && v > 0 ? v : null));
}

// The legend's starting selection, by provider name: the default slugs are
// shown, the rest start hidden. With no default slugs every provider is shown.
export function legendSelection(providers, defaultSlugs) {
  const wanted = Array.isArray(defaultSlugs) && defaultSlugs.length ? new Set(defaultSlugs) : null;
  return Object.fromEntries(providers.map((p) => [p.name, !wanted || wanted.has(p.slug)]));
}

// A provider's daily column; a missing one reads as no figure on every day.
function dailyOf(p, key, dates) {
  return Array.isArray(p[key]) ? p[key] : dates.map(() => null);
}

// The all-authors line: OpenRouter's own total over every model author, not
// the sum of the providers drawn (on 2026-10-22 the eight drawn were 72% of
// tokens). Its slug is not a provider's, so its legend entry is its own.
export const TOTAL_NAME = 'ALL AUTHORS';
export const TOTAL_SLUG = 'total';

// What the charts draw. metric: 'revenue' | 'tokens'. mode: 'DAILY' (the
// trailing 7-day mean, cut to the range after smoothing) or 'MONTHLY' (every
// month: $M a year for revenue, B a day for tokens). Each series keeps its
// index in the full provider list so its colour does not move when toggled.
// The total comes last, marked ``total``, when the build carries one.
export function openrouterSeries(or, { metric, mode, range }) {
  const dates = or.dates || [];
  const providers = or.providers || [];
  const key = metric === 'revenue' ? 'revenue_k' : 'tokens_b';
  const totalDaily = Array.isArray(or[`total_${key}`]) ? or[`total_${key}`] : null;
  const columns = [
    ...providers.map((p, index) => ({ slug: p.slug, name: p.name, index, daily: dailyOf(p, key, dates) })),
    ...(totalDaily ? [{ slug: TOTAL_SLUG, name: TOTAL_NAME, index: providers.length, daily: totalDaily, total: true }] : []),
  ];
  const mark = (c, rest) => ({ slug: c.slug, name: c.name, index: c.index, ...(c.total ? { total: true } : {}), ...rest });
  if (mode === 'MONTHLY') {
    const labels = monthSpan(dates);
    const series = columns.map((c) => {
      const m = metric === 'revenue' ? monthlyArr(dates, c.daily) : monthlyAvgTokens(dates, c.daily);
      return mark(c, { values: metric === 'revenue' ? m.arrM : m.avgB, partial: m.partial });
    });
    return { labels, series };
  }
  const start = rangeCut(dates, range);
  const labels = dates.slice(start);
  const series = columns.map((c) => mark(c, { values: rolling7(c.daily).slice(start), partial: labels.map(() => false) }));
  return { labels, series };
}
