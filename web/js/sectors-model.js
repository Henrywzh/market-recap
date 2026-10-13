// SECTORS: how the hub's artifact is read. Pure, tested under node. Nothing
// here fetches or draws: the build measured every figure, and these functions
// find each page's members, order them, and phrase what a flag or a report
// date means. A missing figure stays missing (null), never a zero.

import { DASH } from './fmt.js';
import { alignTo } from './windows.js';

export const PERIODS = ['1D', '1W', '1M', '3M', 'YTD', '1Y'];
export const DEFAULT_PERIOD = '1M';
// A report this many days ahead or fewer is listed on the reports table.
export const REPORT_WINDOW_DAYS = 42;

const DAY_MS = 86400000;
const finite = (v) => v !== null && v !== undefined && Number.isFinite(v);
const missing = (v) => v === null || v === undefined || v === '' || (typeof v === 'number' && !Number.isFinite(v));

// Which page an argument names: the hub (no argument), one sector ('XLP'),
// one sub-industry ('XLP-SDNB'), or nothing the build knows ('unknown').
export function levelOf(arg, data) {
  const key = arg ? String(arg).trim().toUpperCase() : '';
  if (!key) return { level: 'hub', sector: null, sub: null };
  const sectors = data?.sectors || [];
  const sector = sectors.find((s) => s.key === key);
  if (sector) return { level: 'sector', sector, sub: null };
  const sub = (data?.sub_industries || []).find((s) => s.key === key);
  if (sub) return { level: 'sub', sector: sectors.find((s) => s.key === sub.sector_key) || null, sub };
  return { level: 'unknown', sector: null, sub: null };
}

// Rows ordered by a column, a missing value last whichever way the column
// runs. `column` is a property name or a function that reads the value.
export function sortRows(rows, column, direction = 'desc') {
  const read = typeof column === 'function' ? column : (row) => row?.[column];
  const sign = direction === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = read(a);
    const y = read(b);
    const mx = missing(x);
    const my = missing(y);
    if (mx && my) return 0;
    if (mx) return 1;
    if (my) return -1;
    if (typeof x === 'string') return sign * x.localeCompare(String(y));
    return sign * (Number(x) - Number(y));
  });
}

// The names of a sector, or of one sub-industry, heaviest first.
export function membersOf(data, { sectorKey = null, subKey = null } = {}) {
  const keep = (m) => {
    if (subKey) return m.sub_key === subKey;
    if (sectorKey) return m.sector_key === sectorKey;
    return true;
  };
  return sortRows((data?.members || []).filter(keep), 'weight', 'desc');
}

// The sub-industries of a sector, heaviest first.
export function subsOf(data, sectorKey) {
  return sortRows((data?.sub_industries || []).filter((s) => s.sector_key === sectorKey), 'weight', 'desc');
}

// Names that report after the session and within `days` of it, soonest first
// (ties by ticker). A report on the session's own date is not upcoming.
export function upcoming(members, asOf, days = REPORT_WINDOW_DAYS) {
  const start = Date.parse(asOf);
  if (!Number.isFinite(start)) return [];
  return (members || [])
    .filter((m) => m?.next_report?.date)
    .map((m) => ({ m, ahead: (Date.parse(m.next_report.date) - start) / DAY_MS }))
    .filter(({ ahead }) => Number.isFinite(ahead) && ahead > 0 && ahead <= days)
    .sort((a, b) => a.ahead - b.ahead || String(a.m.ticker).localeCompare(String(b.m.ticker)))
    .map(({ m }) => m);
}

// The build's report timing, in the words a reader scans: before the open,
// after the close, or a date with no confirmed time. Null when unknown.
export function timingLabel(timing) {
  if (timing === 'before_open' || timing === 'bmo') return 'BMO';
  if (timing === 'after_close' || timing === 'amc') return 'AMC';
  if (timing === 'scheduled') return 'TBC';
  return null;
}

export function timingTitle(timing) {
  return {
    BMO: 'reports before the open',
    AMC: 'reports after the close',
    TBC: 'date set, time of day not confirmed',
  }[timingLabel(timing)] || '';
}

const QUADRANTS = {
  leading: { label: 'LEADING', tone: 'up' },
  weakening: { label: 'WEAKENING', tone: 'warn' },
  lagging: { label: 'LAGGING', tone: 'down' },
  improving: { label: 'IMPROVING', tone: 'info' },
};

// The rotation quadrant's tag, or null when the build has none.
export function quadrantTag(quadrant) {
  return QUADRANTS[quadrant] ? { ...QUADRANTS[quadrant] } : null;
}

// The evidence flags a row carries, as tags. A flag that is not true shows no
// tag; a flag the build could not compute (null) shows none either.
const FLAGS = [
  ['sold_off', 'SOLD OFF', 'down', 'median 1M return sharply down, most names down'],
  ['estimates_cut', 'EST CUT', 'warn', 'median FY1 EPS revisions below the build\'s threshold'],
  ['cheap_vs_own_history', 'P/E LOW', 'info', 'median P/E at the low end of its own ten years'],
];
export function evidenceFlags(evidence) {
  return FLAGS.filter(([key]) => evidence?.[key] === true)
    .map(([, text, tone, title]) => ({ text, tone, title }));
}

// The best and worst names over a period, from the members that have a return
// for it. Both are null when no member has one.
export function extremesOf(members, period) {
  const priced = (members || []).filter((m) => finite(m?.returns?.[period]));
  if (!priced.length) return { best: null, worst: null };
  const ordered = sortRows(priced, (m) => m.returns[period], 'desc');
  const pick = (m) => ({ ticker: m.ticker, return: m.returns[period] });
  return { best: pick(ordered[0]), worst: pick(ordered[ordered.length - 1]) };
}

// Sub-industries that carry a THEMES group of their own.
export function themedSubs(data, sectorKey) {
  return subsOf(data, sectorKey).filter((s) => s.theme);
}

// 22 -> "22nd". A missing value is a dash.
export function ordinal(value) {
  if (!finite(value)) return DASH;
  const n = Math.round(value);
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
  return `${n}${suffix}`;
}

// A name above its 200-day average is a tick, below it a cross, unknown a dash.
export function boolMark(value) {
  if (value === true) return '✓';
  if (value === false) return '✗';
  return DASH;
}

// The columns of a names table. `get` reads the sort value from a member row;
// `first` is the direction a column takes on its first click (numbers
// descending, text ascending). `period` is the return column's period.
export function nameColumns(period, { withSub = true, financials = false, subLabel = {} } = {}) {
  const sort200 = (m) => (m.above_200d === true ? 1 : m.above_200d === false ? 0 : null);
  const cols = [
    { key: 'ticker', label: 'TICKER', get: (m) => m.ticker, first: 'asc' },
    { key: 'name', label: 'NAME', get: (m) => m.name, first: 'asc' },
  ];
  if (withSub) cols.push({ key: 'sub', label: 'SUB-INDUSTRY', get: (m) => subLabel[m.sub_key] || m.sub_key, first: 'asc' });
  cols.push(
    { key: 'weight', label: 'WEIGHT', get: (m) => m.weight, first: 'desc' },
    { key: 'ret', label: `${period} RETURN`, get: (m) => m.returns?.[period], first: 'desc' },
    { key: 'y1', label: '1Y', get: (m) => m.returns?.['1Y'], first: 'desc' },
    { key: 'high', label: 'FROM HIGH', get: (m) => m.drawdown, first: 'desc' },
    { key: 'a200', label: '200D', get: sort200, first: 'desc' },
    { key: 'rev', label: 'REV 90D', get: (m) => m.revision_90d, first: 'desc' },
    { key: 'pe', label: 'FWD P/E', get: (m) => m.forward_pe, first: 'desc' },
    { key: 'pctl', label: 'P/E PCTL', get: (m) => m.pe_percentile, first: 'desc' },
  );
  if (financials) {
    cols.push(
      { key: 'ptbv', label: 'P/TBV', get: (m) => m.ptbv, first: 'desc' },
      { key: 'ptbvPctl', label: 'P/TBV PCTL', get: (m) => m.ptbv_percentile, first: 'desc' },
    );
  }
  cols.push(
    { key: 'next', label: 'NEXT REPORT', get: (m) => m.next_report?.date ?? null, first: 'asc' },
    { key: 'monitor', label: 'MONITOR', get: (m) => (m.monitor?.queued === true ? 1 : m.monitor ? 0 : null), first: 'desc' },
  );
  return cols;
}

// --- Charts-first pages: a sector or sub-industry's charts. Pure: the page
// draws what these return, and a missing figure stays out of the picture.

// The periods the page's charts offer, short enough to read at a glance.
export const CHART_PERIODS = ['1M', '3M', 'YTD', '1Y'];
export const DEFAULT_CHART_PERIOD = '3M';
// The lookback window a page opens on when the reader has not picked one.
export const DEFAULT_WINDOW = '1Y';
// How many of the heaviest names carry a label on the names chart.
export const NAMED_LIMIT = 8;
// The valuation path's stages, in the order the build carries them.
export const PATH_STAGES = [
  { key: 'fy_prev', label: 'LAST FY' },
  { key: 'fy0', label: 'THIS FY' },
  { key: 'ntm', label: 'NEXT 12M' },
  { key: 'fy1', label: 'NEXT FY' },
];

const SECTOR_SHORT = {
  'Communication Services': 'Comm Services',
  'Consumer Discretionary': 'Cons Discretionary',
  'Consumer Staples': 'Cons Staples',
  'Information Technology': 'Info Tech',
};

// A sector's name short enough for a chart's title or legend.
export function sectorShort(label) {
  return SECTOR_SHORT[label] || label;
}

// A label short enough for a chart axis: the part before a comma, without the
// words in brackets, cut to `max` characters with an ellipsis.
export function shortName(label, max = 22) {
  const text = String(label ?? '').replace(/\([^)]*\)/g, '').split(',')[0].replace(/\s+/g, ' ').trim();
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

// The bars: each sub-industry's return against the S&P 500 over the period,
// largest first. A sub-industry with no figure for the period is left off.
export function subBars(subs, period) {
  return (subs || [])
    .filter((s) => finite(s?.vs_index?.[period]))
    .map((s) => ({ key: s.key, label: shortName(s.label), full: s.label, value: s.vs_index[period] }))
    .sort((a, b) => b.value - a.value);
}

// Bubble diameters: area in proportion to weight, the heaviest at `max`
// pixels, and a point with no weight at `min`.
export function withSizes(points, min = 8, max = 36) {
  const top = Math.max(0, ...points.map((p) => (finite(p.weight) && p.weight > 0 ? p.weight : 0)));
  return points.map((p) => {
    const share = finite(p.weight) && p.weight > 0 && top > 0 ? p.weight / top : 0;
    return { ...p, size: share ? Math.max(min, max * Math.sqrt(share)) : min };
  });
}

// The sub-industries on the map: x is the excess return over the period (pp),
// y the P/E's place in its own ten years (0 to 100). One missing either is not
// drawn at a made-up place; it is listed apart as `off`.
export function subMapPoints(subs, period) {
  const points = [];
  const off = [];
  for (const s of subs || []) {
    const x = s?.vs_index?.[period];
    const y = s?.pe_percentile;
    if (finite(x) && finite(y)) points.push({ key: s.key, full: s.label, label: shortName(s.label), x, y, weight: s.weight });
    else off.push(shortName(s.label, 40));
  }
  return { points: withSizes(points), off };
}

// The names on the map: x is the name's return over the period less the
// index's (pp), y its FY1 EPS revision over 90 days (%). The heaviest `limit`
// names are labelled. A name missing either figure is listed apart as `off`.
export function nameMapPoints(members, period, benchmarkReturn, limit = NAMED_LIMIT) {
  const points = [];
  const off = [];
  for (const m of members || []) {
    const ret = m?.returns?.[period];
    const rev = m?.revision_90d;
    if (finite(ret) && finite(benchmarkReturn) && finite(rev)) {
      points.push({ key: m.ticker, ticker: m.ticker, full: m.name || m.ticker, label: m.ticker, x: ret - benchmarkReturn, y: rev, weight: m.weight });
    } else {
      off.push(m.ticker);
    }
  }
  const named = new Set(sortRows(points, 'weight', 'desc').slice(0, limit).map((p) => p.ticker));
  return { points: withSizes(points).map((p) => ({ ...p, named: named.has(p.ticker) })), off };
}

// A symmetric axis around zero that holds every value, with a tenth to spare,
// rounded up to a round step. No values gives a unit axis.
export function symmetricRange(values) {
  const reach = Math.max(0, ...(values || []).filter(finite).map((v) => Math.abs(v)));
  const want = reach > 0 ? reach * 1.1 : 1;
  // Half-decade steps, so a reach of 110 gives 150 rather than 200.
  const step = 10 ** Math.floor(Math.log10(want)) / 2;
  const top = Math.ceil(want / step) * step;
  return [-top, top];
}

// The P/E band a page draws, from its basket's stats: the ten-year median, the
// middle half of its weekly readings (25th to 75th percentile), and the
// current reading with its place among them. Null when there are no stats.
export function bandOf(stats) {
  if (!stats || !finite(stats.median) || !finite(stats.p25) || !finite(stats.p75)) return null;
  return {
    median: stats.median,
    p25: stats.p25,
    p75: stats.p75,
    current: finite(stats.current) ? stats.current : null,
    percentile: finite(stats.percentile) ? stats.percentile : null,
    weeks: finite(stats.weeks) ? stats.weeks : null,
  };
}

// The valuation path as four bars in the build's order. Each carries its P/E
// and the earnings growth from the stage before it; a missing figure stays
// null. No path at all is an empty list.
export function pathBars(path) {
  const stages = Array.isArray(path?.stages) ? path.stages : [];
  if (!stages.length) return [];
  return PATH_STAGES.map(({ key, label }) => {
    const stage = stages.find((s) => s?.key === key) || {};
    return {
      key,
      label,
      ntm: key === 'ntm',
      pe: finite(stage.pe) ? stage.pe : null,
      growth: finite(stage.growth) ? stage.growth : null,
    };
  });
}

// The longest of several date lists. A page's window switch offers what its
// longest series covers, so a short series does not hide the long one.
export function longestDates(...lists) {
  return lists.reduce((best, dates) => (Array.isArray(dates) && dates.length > best.length ? dates : best), []);
}

// --- A page against its comparison: the valuation section's two arms ---------
// Each arm is the page's own valuation history and its outlook (forward P/E,
// growth). An older page file has no outlook: the arm then has none, and the
// section shows dashes for it rather than failing.

// Why a page's valuation is missing: its history failed to load, or the build
// has too few names with filings for a P/E history.
export function reasonOf(loaded, label) {
  return loaded.error
    ? `${label}'s history is unavailable: ${loaded.error}.`
    : `${label} has too few names with filings for a P/E history.`;
}

export function comparisonOf(own, ownLabel, other, otherLabel) {
  if (!own.page?.valuation) return { missing: reasonOf(own, ownLabel) };
  if (!other.page?.valuation) return { missing: reasonOf(other, otherLabel) };
  return {
    arms: [
      { key: 'a', label: ownLabel, basket: own.page.valuation, outlook: own.page.outlook },
      { key: 'b', label: otherLabel, basket: other.page.valuation, outlook: other.page.outlook },
    ],
  };
}

// The ratio the decomposition must track (basket-view.js): the page's
// index-weighted basket over the S&P 500's (a sub-industry: over its sector's).
// Not the SPDR fund: its single-name caps and dividends differ from the sector
// for reasons that have nothing to do with which names it holds.
export function referenceOf(own, other, isSector) {
  const r = own.page?.relative;
  if (!r?.dates?.length) return null;
  if (isSector) return { dates: r.dates, ratio: r.basket, label: 'the index-weighted basket' };
  const s = other.page?.relative;
  if (!s?.dates?.length) return null;
  const parent = alignTo(r.dates, s.dates, s.basket);
  return {
    dates: r.dates,
    ratio: r.basket.map((v, i) => (finite(v) && finite(parent[i]) && parent[i] !== 0 ? v / parent[i] : null)),
    label: 'the index-weighted baskets',
  };
}
