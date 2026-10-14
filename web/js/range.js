// The history-range switch (6M · 1Y · 3Y · 5Y · MAX) shared by every
// history chart. A range is calendar days back from the chart's own last
// date, so a weekly and a daily series cut at the same place. Ranges the
// data cannot fill are not offered; MAX is everything the artifact carries.

import { periodSwitch } from './fmt.js';

export const RANGES = [['6M', 182], ['1Y', 365], ['3Y', 1096], ['5Y', 1826], ['MAX', null]];
const DAY_MS = 86400000;
// A range is offered only if the data reaches this far past it; a "1Y" on a
// year and a week of data would draw the same chart as MAX.
const SLACK_DAYS = 20;
const SHORT_RANGES = [['1M', 31], ['3M', 92], ['6M', 182], ['YTD', 'YTD'], ['1Y', 365], ['MAX', null]];

const days = (label) => ([...RANGES, ...SHORT_RANGES].find(([l]) => l === label) || [null, null])[1];

export function spanDays(dates) {
  if (!dates || dates.length < 2) return 0;
  return (Date.parse(dates[dates.length - 1]) - Date.parse(dates[0])) / DAY_MS;
}

// Labels worth offering for this span, MAX always last.
export function availableRanges(dates, { short = false } = {}) {
  const span = spanDays(dates);
  return (short ? SHORT_RANGES : RANGES).filter(([, d]) => {
    if (d === 'YTD') return dates?.length > 1 && dates[0] <= `${dates.at(-1).slice(0, 4)}-01-07`;
    return d === null || d + (short ? 0 : SLACK_DAYS) < span;
  }).map(([l]) => l);
}

// Index of the first date inside the range (0 for MAX or an unknown label).
export function rangeStart(dates, label) {
  const d = days(label);
  if (!d || !dates || !dates.length) return 0;
  const cut = d === 'YTD' ? Date.parse(`${dates.at(-1).slice(0, 4)}-01-01`) : Date.parse(dates[dates.length - 1]) - d * DAY_MS;
  const index = dates.findIndex((x) => Date.parse(x) >= cut);
  return index < 0 ? 0 : index;
}

// Cut the dates and every parallel array in `columns` to the range.
export function sliceRange(dates, columns, label) {
  const start = rangeStart(dates, label);
  const out = {};
  for (const [key, values] of Object.entries(columns)) out[key] = (values || []).slice(start);
  return { dates: (dates || []).slice(start), ...out };
}

// The label to show first: the preferred one if the data can fill it.
export function initialRange(dates, preferred) {
  const offered = availableRanges(dates);
  return offered.includes(preferred) ? preferred : 'MAX';
}

// The switch itself. `dates` decides which ranges are offered.
export function rangeSwitch(dates, active, onPick, options) {
  const node = periodSwitch(availableRanges(dates, options), active, onPick);
  node.classList.add('range-switch');
  return node;
}
