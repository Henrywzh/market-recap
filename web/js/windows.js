// Lookback windows for any dated series: which windows a series is long enough
// for, where each starts, and the series cut to it -- rebased at its start when
// it is a level (an index to 100, a ratio to 1) and left as is when it is a
// reading (a P/E, a gap in percentage points). Dates are ISO strings.
//
// A window starts at the last date on or before its cut (the close a return
// over that window is measured from), so a 1Y line starts a year before the
// last date, and YTD starts at the previous year's last close.

import { periodSwitch } from './fmt.js';

export const WINDOWS = ['1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', '10Y', 'MAX'];
const MONTHS = { '1M': 1, '3M': 3, '6M': 6, '1Y': 12, '3Y': 36, '5Y': 60, '10Y': 120 };

function iso(date) {
  return date.toISOString().slice(0, 10);
}

// The cut date for a window ending at `last`, or null for MAX.
export function windowCut(last, window) {
  if (window === 'MAX') return null;
  const end = new Date(`${last}T00:00:00Z`);
  if (window === 'YTD') return iso(new Date(Date.UTC(end.getUTCFullYear(), 0, 0)));
  const months = MONTHS[window];
  if (!months) throw new Error(`unknown window ${window}`);
  const cut = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() - months, end.getUTCDate()));
  return iso(cut);
}

// Index of the window's base point in `dates`: the last date on or before the
// cut. -1 when the series starts after the cut (the window is not available).
export function baseIndex(dates, window) {
  if (!dates.length) return -1;
  const cut = windowCut(dates[dates.length - 1], window);
  if (cut === null) return 0;
  if (dates[0] > cut) return -1;
  let lo = 0;
  let hi = dates.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (dates[mid] <= cut) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

// The windows a series covers, in order; MAX always.
export function availableWindows(dates, windows = WINDOWS) {
  return windows.filter((w) => w === 'MAX' || baseIndex(dates, w) >= 0);
}

// The window to show: the wanted one when the series covers it, else the
// longest covered window shorter than it, else MAX.
export function pickWindow(dates, wanted, windows = WINDOWS) {
  const covered = availableWindows(dates, windows);
  if (covered.includes(wanted)) return wanted;
  const shorter = windows.slice(0, windows.indexOf(wanted)).filter((w) => covered.includes(w));
  return shorter.length ? shorter[shorter.length - 1] : 'MAX';
}

// {dates, series} cut to the window. `rebase` maps a series name to 'index'
// (=100 at its first value in the window), 'ratio' (=1) or nothing (as is).
export function sliceWindow(dates, series, window, rebase = {}) {
  const start = Math.max(0, baseIndex(dates, window));
  const out = { dates: dates.slice(start), series: {} };
  Object.entries(series).forEach(([name, values]) => {
    const cut = (values || []).slice(start);
    const mode = rebase[name];
    if (!mode) {
      out.series[name] = cut;
      return;
    }
    const base = cut.find((v) => v !== null && v !== undefined && Number.isFinite(v) && v !== 0);
    const scale = mode === 'index' ? 100 : 1;
    out.series[name] = cut.map((v) => (base === undefined || v === null || v === undefined || !Number.isFinite(v) ? null : (scale * v) / base));
  });
  return out;
}

// One value series re-indexed onto another series' dates (null where absent).
export function alignTo(dates, otherDates, values) {
  const at = new Map(otherDates.map((d, i) => [d, values[i]]));
  return dates.map((d) => (at.has(d) ? at.get(d) : null));
}

// The switch: only the windows the series covers.
export function windowSwitch(dates, current, onPick, windows = WINDOWS) {
  return periodSwitch(availableWindows(dates, windows), current, onPick);
}
