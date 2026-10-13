// SIZE K: how the build's figures read on the page. Pure, tested under node.
// The build measured every number; these functions phrase them and pick a
// tone. Nothing here says which arm is right.

import { num, DASH } from './fmt.js';
import { sliceWindow, WINDOWS } from './windows.js';

const finite = (v) => v !== null && v !== undefined && Number.isFinite(v);

// The rolling-gap sentence: how often and how long the large arm led.
export function leadText(gap, bigName, smallName) {
  if (!gap || !finite(gap.share_big_ahead)) return null;
  const weeks = (n) => `${n} week${n === 1 ? '' : 's'}`;
  return `${bigName} beat ${smallName} in ${num(gap.share_big_ahead, 0)}% of the ${gap.window} windows since ${gap.first}; `
    + `the longest unbroken lead was ${weeks(gap.longest_big)}, the longest lag ${weeks(gap.longest_small)}.`;
}

// Distance from the ratio's own high and low, in the build's figures.
export function extremesText(ex) {
  if (!ex) return null;
  const from = (v) => `${v > 0 ? '+' : ''}${num(v, 1)}%`;
  return `${from(ex.from_high_pct)} from its high of ${num(ex.high, 2)}× (${ex.high_date}); ${from(ex.from_low_pct)} from its low of ${num(ex.low, 2)}× (${ex.low_date}).`;
}

// Calendar years, newest first; the part-years say what they are.
export function yearRows(years) {
  return [...(years || [])].reverse().map((y) => ({
    label: y.to_date ? `${y.year} (to date)` : y.partial_start ? `${y.year} (part)` : String(y.year),
    big: y.big, small: y.small, gap: y.gap,
    tone: !finite(y.gap) ? 'dim' : y.gap > 0 ? 'up' : 'down',
  }));
}

// How many of the complete calendar years the large arm won, as "12 of 22".
export function yearsWon(years) {
  const full = (years || []).filter((y) => !y.to_date && !y.partial_start && finite(y.gap));
  if (!full.length) return null;
  return { won: full.filter((y) => y.gap > 0).length, of: full.length };
}

export function wonText(w) {
  return w ? `${w.won} of ${w.of}` : DASH;
}

// The lookback window a reader picked, remembered per tab. Storage can be
// missing or refuse access (a private window), and a stored value this build
// does not recognise falls back to the default: neither may break the page.
export function readWindow(key, fallback) {
  try {
    const stored = globalThis.localStorage?.getItem(key);
    return WINDOWS.includes(stored) ? stored : fallback;
  } catch {
    return fallback;
  }
}

export function writeWindow(key, window) {
  try { globalThis.localStorage?.setItem(key, window); } catch { /* not kept; fine */ }
}

// The price ratio and each arm cut to the window. The ratio is =1 and each arm
// =100 at the window's first close, so every line reads as what happened inside
// the window; the ratio's own history is never rebased in the stat strip.
export function priceSeries(price, window) {
  return sliceWindow(price.dates, { ratio: price.ratio, big: price.big, small: price.small }, window,
    { ratio: 'ratio', big: 'index', small: 'index' });
}

// The rolling gap is already a return in percentage points, so it is cut and
// never rebased: a rebase would turn a lead of 3 points into a meaningless ratio.
export function gapSeries(gap, window) {
  return sliceWindow(gap.dates, { gap: gap.gap }, window);
}

// What the valuation cards are given for a view. An older build has no
// `fundamentals` at all, and a view may carry a note saying why it has none;
// either way the card states the reason rather than drawing nothing. An arm
// with no names says why too, and that reason wins over a generic one.
export function fundamentalsOf(view, fallbackReason = 'Valuation for these arms is not in this build.') {
  const f = view.fundamentals;
  if (!f) return { missing: view.fundamentals_note || fallbackReason };
  if (f.missing) return f;
  const arms = Array.isArray(f.arms) ? f.arms : [];
  if (arms.length === 2 && arms.every((a) => a.basket?.dates?.length)) return f;
  const reasons = [...new Set(arms.map((a) => a.missing).filter(Boolean))];
  return { missing: reasons.length ? reasons.join(' ') : (view.fundamentals_note || 'No filings history for both arms.') };
}
