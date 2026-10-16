// The RAMP TOKENOMICS card's arithmetic. Pure: no DOM and no fmt.js import, so
// node can run the tests. Weekly series are aligned with `weeks` (oldest first),
// prices with `prices.dates`. A null is a gap, a day or week with no figure; it
// is never counted as zero. A reported zero stays 0.

const DAY_MS = 86400000;
// The range switch: calendar days back from the last date. ALL is no cut.
export const RANGES = ['3M', '6M', '1Y', 'ALL'];
const RANGE_DAYS = { '3M': 92, '6M': 182, '1Y': 365 };
// The BY MODEL chart shows this many models at first.
const TOP_MODELS = 8;
export const UNITS = { VOLUME: 'billion tokens', SPEND: 'USD million', PRICE: 'USD per million tokens' };
const TOKEN_KEYS = { ALL: 'all_tokens', 'UNCACHED INPUT': 'uncached_input', OUTPUT: 'output' };
// The same em dash fmt.js exports as DASH; this module cannot import fmt.js.
const DASH = '—';

const isNumber = (v) => typeof v === 'number' && Number.isFinite(v);
const isObject = (v) => v !== null && typeof v === 'object';
const arr = (v) => (Array.isArray(v) ? v : []);

// A column aligned to n dates: a missing or non-numeric day is null.
function aligned(values, n) {
  const src = arr(values);
  return Array.from({ length: n }, (_, i) => (isNumber(src[i]) ? src[i] : null));
}

// value * 100 / total. Null when either is a gap, or when the total is not above zero.
function shareOf(value, total) {
  return isNumber(value) && isNumber(total) && total > 0 ? (value * 100) / total : null;
}

// Each value as a share of the matching total. The total is the sum over every
// reported series, so a subset of series still divides by the full total.
export function shareSeries(values, total) {
  const t = arr(total);
  return arr(values).map((v, i) => shareOf(v, t[i]));
}

// Index of the first date inside the range, cut from the last date by calendar
// days. ALL, an unknown label, or no dates give 0.
export function rangeStartIndex(dates, label) {
  const d = arr(dates);
  if (!d.length || !Object.hasOwn(RANGE_DAYS, label)) return 0;
  const end = Date.parse(d[d.length - 1]);
  if (!Number.isFinite(end)) return 0;
  const cut = new Date(end - RANGE_DAYS[label] * DAY_MS).toISOString().slice(0, 10);
  const index = d.findIndex((x) => x >= cut);
  return index < 0 ? 0 : index;
}

// Values for a log axis: anything not above zero is a gap, never a zero.
export function logValues(values) {
  return arr(values).map((v) => (isNumber(v) && v > 0 ? v : null));
}

// Series names must be unique (the legend's selection is keyed by name). A
// repeated name gets its maker, then its key, appended.
function uniqueNames(rows) {
  const counts = new Map();
  for (const r of rows) counts.set(r.name, (counts.get(r.name) ?? 0) + 1);
  const taken = new Set();
  return rows.map((r) => {
    let name = counts.get(r.name) > 1 ? `${r.name} (${r.maker ?? r.key})` : r.name;
    while (taken.has(name)) name = `${name} (${r.key})`;
    taken.add(name);
    return { ...r, name };
  });
}

function makerSeries(list, n, unit) {
  const rows = arr(list).filter(isObject).map((m) => ({
    key: String(m.key ?? m.name ?? ''),
    name: String(m.name ?? m.key ?? ''),
    maker: null,
    values: aligned(m.values, n),
  }));
  return uniqueNames(rows).map(({ key, name, values }) => ({ key, name, values, unit }));
}

function modelSeries(list, n, unit) {
  const rows = arr(list).filter(isObject).map((m) => ({
    key: String(m.key ?? m.label ?? ''),
    name: String(m.label ?? m.key ?? ''),
    maker: m.maker == null ? null : String(m.maker),
    values: aligned(m.values, n),
  }));
  return uniqueNames(rows).map(({ key, name, values }) => ({ key, name, values, unit }));
}

// The series the chart and table draw, for one metric. VOLUME and SPEND: by
// maker or by model, with the total over every reported series. PRICE: the
// observed price for one token type, by maker, with no total.
// Returns { dates, series: [{key, name, values, unit}], total, unitLabel }.
export function pickSeries(payload, { metric = 'VOLUME', breakdown = 'BY MAKER', tokenType = 'ALL' } = {}) {
  const p = isObject(payload) ? payload : {};
  if (metric === 'PRICE') {
    const prices = isObject(p.prices) ? p.prices : {};
    const dates = arr(prices.dates);
    const types = isObject(prices.types) ? prices.types : {};
    const key = Object.hasOwn(TOKEN_KEYS, tokenType) ? TOKEN_KEYS[tokenType] : 'all_tokens';
    const unitLabel = prices.unit ?? UNITS.PRICE;
    return { dates, series: makerSeries(types[key], dates.length, unitLabel), total: null, unitLabel };
  }
  const block = (metric === 'SPEND' ? p.spend : p.volume) || {};
  const dates = arr(p.weeks);
  const unitLabel = block.unit ?? UNITS[metric === 'SPEND' ? 'SPEND' : 'VOLUME'];
  const total = Array.isArray(block.total) ? aligned(block.total, dates.length) : null;
  const series = breakdown === 'BY MODEL'
    ? modelSeries(block.models, dates.length, unitLabel)
    : makerSeries(block.makers, dates.length, unitLabel);
  return { dates, series, total, unitLabel };
}

// The index of the latest date on which any series has a figure; -1 if none does.
export function latestIndex(series) {
  let last = -1;
  for (const s of arr(series)) {
    arr(isObject(s) ? s.values : null).forEach((v, i) => {
      if (isNumber(v) && i > last) last = i;
    });
  }
  return last;
}

// The series the chart shows before anyone clicks the legend, as a set of keys.
// BY MAKER: the payload's default makers, in their configured order, if present
// (every series when the build names none). BY MODEL: the TOP_MODELS largest
// figures on the latest date with data; a model with no figure on that date is
// not ranked.
export function defaultVisible(seriesList, payload, breakdown) {
  const list = arr(seriesList).filter(isObject);
  if (breakdown === 'BY MODEL') {
    const i = latestIndex(list);
    if (i < 0) return new Set();
    const ranked = list
      .map((s) => ({ key: s.key, v: arr(s.values)[i] }))
      .filter((r) => isNumber(r.v))
      .sort((a, b) => b.v - a.v);
    return new Set(ranked.slice(0, TOP_MODELS).map((r) => r.key));
  }
  const keys = new Set(list.map((s) => s.key));
  const wanted = isObject(payload) && Array.isArray(payload.default_makers) && payload.default_makers.length
    ? payload.default_makers
    : null;
  return wanted ? new Set(wanted.filter((k) => keys.has(k))) : keys;
}

// The table: every series on the latest date with data (the latest week, or the
// latest day for prices), largest value first, gaps last. A gap has a null value
// and a null share. The share divides by `total` (null for prices).
// Returns [{key, name, value, share}].
export function latestRows(series, total) {
  const i = latestIndex(series);
  const t = arr(total);
  const rows = arr(series).filter(isObject).map((s) => {
    const raw = i < 0 ? null : arr(s.values)[i];
    const value = isNumber(raw) ? raw : null;
    return { key: s.key, name: s.name, value, share: shareOf(value, t[i]) };
  });
  return rows.sort((a, b) => (a.value === null) - (b.value === null) || b.value - a.value);
}

// Decimals by size: below 1, three; below 10, two; below 100, one; else none.
// Zero prints without decimals.
function places(a) {
  if (a === 0 || a >= 100) return 0;
  return a >= 10 ? 1 : a >= 1 ? 2 : 3;
}

// The figure rounded to the places it would print with.
const roundTo = (a, d) => Math.round(a * 10 ** d) / 10 ** d;

// Decimals for a figure after rounding it: 99.96 prints as 100, not 100.0, and
// 0.9996 prints with two decimals as 1.00, not three as 1.000.
const digitsFor = (a) => places(roundTo(a, places(a)));

// A number with exactly d decimals and thousands separators; a value that rounds
// to zero prints as zero, never as a negative zero.
function fixed(v, d) {
  const x = Math.abs(v) < 0.5 * 10 ** -d ? 0 : v;
  return x.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

// A figure in the small unit, or in the large one (1,000 of the small) once it
// would print as 1,000 or more: 999.9 reads as 1.00 of the large unit.
function scaled(v, small, large) {
  const a = Math.abs(v);
  if (roundTo(a, places(a)) < 1000) return `${fixed(v, digitsFor(a))}${small}`;
  const x = v / 1000;
  return `${fixed(x, digitsFor(Math.abs(x)))}${large}`;
}

// Volume is in billions of tokens: 412B, or 1.25T above 1,000.
export function formatVolume(v) {
  return isNumber(v) ? scaled(v, 'B', 'T') : DASH;
}

// Spend is in $ millions: $412M, or $1.25B above 1,000.
export function formatSpend(v) {
  if (!isNumber(v)) return DASH;
  return `${v < 0 ? '-' : ''}$${scaled(Math.abs(v), 'M', 'B')}`;
}

// A price in $ per million tokens, as a bare number: $3.00, or $0.512 below $1.
// Prices always carry two decimals, so they read as money.
export function formatPriceValue(v) {
  if (!isNumber(v)) return DASH;
  const a = Math.abs(v);
  return `$${fixed(v, a !== 0 && a < 1 ? 3 : 2)}`;
}

// The same price with its unit: $3.00 per M tokens.
export function formatPrice(v) {
  return isNumber(v) ? `${formatPriceValue(v)} per M tokens` : DASH;
}

// A share of the reported sample, in percent: 23.5%, or 0.412% below 1.
export function formatShare(v) {
  return isNumber(v) ? `${fixed(v, digitsFor(Math.abs(v)))}%` : DASH;
}

// MONTHLY ARR: the weekly figures re-cut by calendar month.
// A spend month is annualised by this many days.
export const ANNUAL_DAYS = 365;
// The mode control's labels. MONTHLY ARR is not offered for PRICE.
export const MODES = ['WEEKLY', 'MONTHLY ARR'];

// Whether the mode control applies: VOLUME and SPEND have a monthly view; PRICE is already a price per token.
export function modeAvailable(metric) {
  return metric !== 'PRICE';
}

// The calendar days in a 'YYYY-MM' month.
function daysIn(month) {
  const [y, m] = month.split('-').map(Number);
  return new Date(Date.UTC(y, m, 0)).getUTCDate();
}

// Every 'YYYY-MM' from `first` to `last`, both included, gaps included.
function monthsBetween(first, last) {
  const out = [];
  for (let m = first; m <= last; ) {
    out.push(m);
    const [y, mo] = m.split('-').map(Number);
    m = mo === 12 ? `${y + 1}-01` : `${y}-${String(mo + 1).padStart(2, '0')}`;
  }
  return out;
}

// Each reported weekly value spread over the seven calendar days that end on its
// week-ending date, as a map from 'YYYY-MM-DD' to that day's share. A null week
// has no days in the map.
function dayValues(weeks, values) {
  const vals = arr(values);
  const out = new Map();
  arr(weeks).forEach((week, i) => {
    const v = vals[i];
    const end = Date.parse(week);
    if (!isNumber(v) || !Number.isFinite(end)) return;
    for (let k = 0; k < 7; k += 1) out.set(new Date(end - k * DAY_MS).toISOString().slice(0, 10), v / 7);
  });
  return out;
}

// Each weekly value spread over the seven calendar days that end on its
// week-ending date, so a week that straddles a month boundary splits by days. A
// null week covers no days (a gap). A reported zero covers its days with 0. Per
// calendar month, from the first covered day's month to the last's: perDay is
// the sum of the covered days' shares over the number of covered days (null when
// there are none), and partial is true when fewer days are covered than the
// month has. A month between two others with no covered days stays listed.
// Returns { months, perDay, daysCovered, daysInMonth, partial }.
export function monthlyFromWeekly(weeks, values) {
  const share = dayValues(weeks, values);
  const days = [...share.keys()].sort();
  if (!days.length) return { months: [], perDay: [], daysCovered: [], daysInMonth: [], partial: [] };
  const months = monthsBetween(days[0].slice(0, 7), days[days.length - 1].slice(0, 7));
  const rows = months.map((month) => {
    let sum = 0;
    let covered = 0;
    for (const day of days) {
      if (day.startsWith(month)) {
        sum += share.get(day);
        covered += 1;
      }
    }
    return { perDay: covered ? sum / covered : null, covered, total: daysIn(month) };
  });
  return {
    months,
    perDay: rows.map((r) => r.perDay),
    daysCovered: rows.map((r) => r.covered),
    daysInMonth: rows.map((r) => r.total),
    partial: rows.map((r) => r.covered < r.total),
  };
}

// A block's series on one shared month axis: the widest span of any series' own
// months (and the total's), where a month a series does not cover is a gap.
// SPEND is annualised (perDay * ANNUAL_DAYS, $M a year); VOLUME stays the mean day.
// The total is put on the same axis. A null total gives null shares.
// Shares: each series' share of the month's total, in percent. The numerator
// is the series' figures on the days it and the total both report; the
// denominator is the total on every day the total reports that month. Where a
// series reports every week the total does, this is its monthly value over the
// monthly total. A gap counts for nothing in the numerator, so a month with gaps
// reads low (the partial marker flags it), and the shares never sum past 100.
// Null when the series shares no day with the total that month.
// Returns { months, series: [{key, name, values, partial, shares}], total: values | null }.
export function monthlyView(weeks, series, total, metric) {
  const list = arr(series).filter(isObject);
  const parts = list.map((s) => monthlyFromWeekly(weeks, s.values));
  const totalPart = total === null || total === undefined ? null : monthlyFromWeekly(weeks, total);
  const spanned = [...parts, totalPart].filter((p) => p && p.months.length);
  const months = spanned.length
    ? monthsBetween(spanned.map((p) => p.months[0]).sort()[0], spanned.map((p) => p.months.at(-1)).sort().at(-1))
    : [];
  const scale = metric === 'SPEND' ? ANNUAL_DAYS : 1;
  const onAxis = (part) => {
    const at = new Map(part ? part.months.map((m, i) => [m, i]) : []);
    const cells = months.map((m) => {
      const i = at.get(m);
      if (i === undefined) return { value: null, partial: true };
      const perDay = part.perDay[i];
      return { value: perDay === null ? null : perDay * scale, partial: part.partial[i] };
    });
    return { values: cells.map((c) => c.value), partial: cells.map((c) => c.partial) };
  };
  // The total's day shares, and each series' over the same days.
  const totalDays = dayValues(weeks, total);
  const sharesOf = (values) => {
    const days = dayValues(weeks, values);
    return months.map((m) => {
      let num = 0;
      let den = 0;
      let shared = 0;
      for (const [day, t] of totalDays) {
        if (!day.startsWith(m)) continue;
        den += t;
        if (days.has(day)) {
          num += days.get(day);
          shared += 1;
        }
      }
      return shared && den > 0 ? (num * 100) / den : null;
    });
  };
  return {
    months,
    series: list.map((s, k) => ({ key: s.key, name: s.name, ...onAxis(parts[k]), shares: sharesOf(s.values) })),
    total: totalPart ? onAxis(totalPart).values : null,
  };
}
