// Display geometry only: observed vendor growth values, never a fitted range.
import { finite } from './reverse-dcf-math.js';

export function consensusGrowthRanges(periods) {
  const rows = periods.map((period) => {
    const mean = finite(period.growth_pct) ? period.growth_pct : null;
    const low = finite(period.growth_low_pct) ? period.growth_low_pct : null;
    const high = finite(period.growth_high_pct) ? period.growth_high_pct : null;
    const invalid = Boolean(period.range_issue) || (low !== null && high !== null
      && (low > high || (mean !== null && (mean < low || mean > high))));
    const hasRange = !invalid && low !== null && high !== null;
    return { period, mean, low: hasRange ? low : null, high: hasRange ? high : null, hasRange, invalid };
  });
  const values = rows.flatMap((r) => [r.mean, r.low, r.high]).filter(finite);
  if (!values.length) return { min: null, max: null, rows: rows.map((r) => ({ ...r, geometry: null })) };
  const lower = Math.min(0, ...values), upper = Math.max(0, ...values);
  const pad = (upper - lower || 1) * .1;
  const min = lower - pad, max = upper + pad;
  const at = (v) => (v - min) / (max - min) * 100;
  return { min, max, rows: rows.map((r) => ({ ...r, geometry: {
    zeroAt: at(0), meanAt: r.mean === null ? null : at(r.mean),
    lowAt: r.hasRange ? at(r.low) : null, width: r.hasRange ? at(r.high) - at(r.low) : null,
  } })) };
}
