import { rangeStart } from './range.js';

const valid = (v) => typeof v === 'number' && Number.isFinite(v);

// A series the source could not supply has no values to draw or summarise.
export function availableSeries(series) {
  return (series || []).filter((row) => row && row.status !== 'unavailable');
}

// Licensed series left out of the artifact, as one line for the method fold.
export function notShownNote(disabled) {
  const lines = (disabled || []).map((d) => `${d.label}: not shown -- ${d.reason}`);
  return lines.length ? lines.join(' · ') : null;
}

// Smooth before slicing: a 21-session mean still needs the preceding sessions.
export function putCallReading(row, window, range) {
  const start = rangeStart(row.dates, range);
  const dates = row.dates.slice(start);
  const values = row.windows[window].values.slice(start);
  const sorted = values.filter(valid).sort((a, b) => a - b);
  const n = sorted.length;
  const latest = valid(values.at(-1)) ? values.at(-1) : null;
  const median = n ? (sorted[Math.floor((n - 1) / 2)] + sorted[Math.floor(n / 2)]) / 2 : null;
  const percentile = latest === null || !n ? null : 100 * (sorted.filter((v) => v < latest).length + sorted.filter((v) => v === latest).length / 2) / n;
  const daily = row.windows['1D'].values.slice(start);
  const observed = daily.filter(valid).length;
  return { dates, values, latest, median, percentile, observations: n, observed, expected: dates.length, missing: dates.length - observed };
}
