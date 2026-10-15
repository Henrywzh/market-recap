// Number formats for chart axes and tooltips. Pure functions, so node tests can
// run them; charts.js reads each value axis's tick spacing and passes it here.
// Never more than three decimals on a chart; absence is an em dash.

import { DASH } from './fmt.js';

const MAX_DECIMALS = 3;

// The fewest decimals (0..3) in which every multiple of `step` prints exactly:
// 0.05 -> 2, 0.5 -> 1, 5 -> 0, 0.001 -> 3, 0.0004 -> 3 (finer than the cap).
// No usable step gives the cap, so nothing is lost.
export function decimalsForStep(step) {
  if (!Number.isFinite(step) || step <= 0) return MAX_DECIMALS;
  for (let d = 0; d < MAX_DECIMALS; d += 1) {
    const scaled = step * 10 ** d;
    if (Math.abs(scaled - Math.round(scaled)) <= 1e-9 * Math.max(1, scaled)) return d;
  }
  return MAX_DECIMALS;
}

// A negative zero prints as zero: "-0.00" on an axis reads as a fall.
function withoutNegativeZero(text) {
  return /^-0(\.0*)?$/.test(text) ? text.slice(1) : text;
}

// A readable number: at most `maxDecimals`, trailing zeros dropped.
export function formatValue(value, maxDecimals = MAX_DECIMALS) {
  if (!Number.isFinite(value)) return DASH;
  const digits = Math.max(0, Math.min(20, Math.floor(maxDecimals)));
  const rounded = Number(value.toFixed(digits));
  return String(rounded === 0 ? 0 : rounded);
}

// An axis label for a tick: the decimals its spacing needs. With no usable
// step, the value is shown as formatValue shows it.
export function formatTick(value, step) {
  if (!Number.isFinite(value)) return DASH;
  if (!Number.isFinite(step) || step <= 0) return formatValue(value);
  return withoutNegativeZero(value.toFixed(decimalsForStep(step)));
}

// The step of the 1, 2 or 5 times a power of ten nearest (max - min) / targetTicks:
// the spacing a value axis draws with about targetTicks intervals. Null for an
// empty or non-finite range.
export function niceStepFromRange(min, max, targetTicks = 5) {
  const span = max - min;
  if (!Number.isFinite(span) || span <= 0 || !(targetTicks >= 1)) return null;
  const raw = span / targetTicks;
  const exp = Math.floor(Math.log10(raw));
  const f = raw / 10 ** exp; // in [1, 10)
  const scaled = (n, e) => (e >= 0 ? n * 10 ** e : n / 10 ** -e);
  if (f < 1.5) return scaled(1, exp);
  if (f < 3) return scaled(2, exp);
  if (f < 7) return scaled(5, exp);
  return scaled(1, exp + 1);
}
