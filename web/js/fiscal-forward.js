// Yahoo's own forward P/E history for one company, as the ticker artifact carries it
// (`fiscal_forward`, built in compute/valuation.py). Pure functions: the chart and
// the table in tabs/valuation.js are drawn from what these return.
//
// This is a different measure from the recorded next-twelve-months multiple: Yahoo's
// EPS is a fiscal year's consensus that moves to the next year three months before the
// year ends, so each point looks 4 to 15 months ahead. Nothing here joins the two.

import { DASH, num } from './fmt.js';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const present = (v) => v !== null && v !== undefined;

// Linear-interpolated quantile of an ascending list; null for an empty one.
export function quantile(sorted, q) {
  if (!sorted.length) return null;
  const position = (sorted.length - 1) * q;
  const low = Math.floor(position);
  const high = Math.ceil(position);
  return sorted[low] + (sorted[high] - sorted[low]) * (position - low);
}

// Yahoo's history is a year or two of points, and a company whose EPS has collapsed (Boeing)
// can have several extreme ones in a row. The 90th percentile then lands on a spike; the 75th
// stays on the ordinary values as long as fewer than a quarter of the points are extreme.
const MIN_POINTS_TO_CAP = 8;
const CAP_PERCENTILE = 0.75;
export const AXIS_CAP_FACTOR = 2.5;

// The y-axis top when near-zero earnings would flatten the rest: AXIS_CAP_FACTOR times the
// 75th percentile, or null when nothing sticks out (or there are too few points to say).
// The table keeps the true range.
export function axisCap(values) {
  const sorted = values.filter((v) => present(v) && v > 0).sort((a, b) => a - b);
  if (sorted.length < MIN_POINTS_TO_CAP) return null;
  const cap = quantile(sorted, CAP_PERCENTILE) * AXIS_CAP_FACTOR;
  return sorted[sorted.length - 1] > cap ? Math.ceil(cap) : null;
}

const monthYear = (date) => `${MONTHS[Number(date.slice(5, 7)) - 1]} ${date.slice(0, 4)}`;

// Series for the chart, on one date axis: the monthly and quarterly points as a line,
// the fiscal year ends (exactly twelve months ahead) as separate markers.
export function chartData(fiscal) {
  const points = fiscal.points || [];
  const annual = fiscal.annual || [];
  const dates = [...new Set([...points.map((p) => p.date), ...annual.map((a) => a.date)])].sort();
  const byDate = new Map(points.map((p) => [p.date, p]));
  const yearEnd = new Map(annual.map((a) => [a.date, a.pe]));
  return {
    dates,
    // [date, value] pairs for a time axis: the year ends are four years apart from the
    // monthly points, and an even spacing by index would draw them as neighbours.
    linePairs: points.map((p) => [p.date, p.pe]),
    annualPairs: annual.map((a) => [a.date, a.pe]),
    line: dates.map((d) => (byDate.has(d) ? byDate.get(d).pe : null)),
    annual: dates.map((d) => (yearEnd.has(d) ? yearEnd.get(d) : null)),
    rolled: points.filter((p) => p.rolled).map((p) => p.date),
    horizon: Object.fromEntries(points.filter((p) => present(p.horizon)).map((p) => [p.date, p.horizon])),
  };
}

// What the axis tooltip says for one date.
export function tooltipText(date, data) {
  const i = data.dates.indexOf(date);
  if (i < 0) return '';
  const parts = [`<b>${date}</b>`];
  if (present(data.line[i])) {
    const horizon = data.horizon[date];
    parts.push(`${num(data.line[i], 1)}x` + (present(horizon) ? ` · EPS ${horizon} months ahead` : ''));
    if (data.rolled.includes(date)) parts.push('EPS moved to the next fiscal year');
  }
  if (present(data.annual[i])) parts.push(`fiscal year end: ${num(data.annual[i], 1)}x, 12 months ahead`);
  return parts.join('<br>');
}

// Rows for the history table: [label, text, wrap]. The long ones wrap so they do not widen
// the whole table beyond its card.
export function tableRows(fiscal) {
  const latest = fiscal.latest;
  const ago = fiscal.year_ago;
  const rows = [[
    'Forward P/E, Yahoo (fiscal-year EPS)',
    latest && present(latest.pe)
      ? `${num(latest.pe, 1)}x · ${present(latest.horizon) ? `${latest.horizon} months ahead` : 'horizon unknown'} · ${latest.date}`
      : DASH,
    true,
  ], [
    'Same month a year earlier',
    ago && present(ago.pe)
      ? `${num(ago.pe, 1)}x (${ago.date})` + (present(ago.change_pct) ? ` · ${ago.change_pct > 0 ? '+' : ''}${num(ago.change_pct, 0)}% at the same horizon` : '')
      : DASH,
    true,
  ], [
    'At fiscal year ends (12 months ahead)',
    (fiscal.annual || []).length
      ? fiscal.annual.map((a) => `${monthYear(a.date)} ${present(a.pe) ? `${num(a.pe, 1)}x` : DASH}`).join(' · ')
      : DASH,
    true,
  ]];
  const missing = fiscal.missing_months || [];
  if (missing.length) rows.push(['No Yahoo point for', missing.join(', '), true]);
  if ((fiscal.unread || []).length) rows.push(['Not read from Yahoo', fiscal.unread.join(', '), true]);
  return rows;
}
