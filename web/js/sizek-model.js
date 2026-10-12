// SIZE K: how the build's figures read on the page. Pure, tested under node.
// The build measured every number; these functions phrase them and pick a
// tone. Nothing here says which arm is right.

import { num, DASH } from './fmt.js';

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
