// SECTORS: how the hub's artifact is read. Pure, tested under node. Nothing
// here fetches or draws: the build measured every figure, and these functions
// find each page's members, order them, and phrase what a flag or a report
// date means. A missing figure stays missing (null), never a zero.

import { DASH } from './fmt.js';

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
