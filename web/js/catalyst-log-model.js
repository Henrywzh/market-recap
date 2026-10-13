// UNSCHEDULED CATALYSTS: how the build's price and estimate moves read on the
// page. Pure, tested under node. The build measured every number; these
// functions phrase the pair of states and the analyst counts. Nothing here
// predicts, and a flat estimate soon after an event is a statement about those
// days: consensus averages move days to weeks after analysts do.

import { num, DASH } from './fmt.js';

const finite = (v) => v !== null && v !== undefined && Number.isFinite(v);
const MOVE = { down: 'fell', flat: 'barely moved', up: 'rose' };

const READING = {
  'down|flat': ['Prices fell and estimates have not moved: what investors will pay changed, not yet what analysts expect the companies to earn.', 'info'],
  'down|down': ['Prices fell and estimates were cut: expected earnings fell with them.', 'down'],
  'down|up': ['Prices fell while estimates rose: the market is paying less for earnings that analysts are raising.', 'warn'],
  'flat|flat': ['Neither prices nor estimates have moved much.', 'dim'],
  'flat|down': ['Estimates were cut with little move in prices.', 'warn'],
  'flat|up': ['Estimates rose with little move in prices.', 'dim'],
  'up|flat': ['Prices rose and estimates have not moved.', 'dim'],
  'up|down': ['Prices rose while estimates were cut.', 'warn'],
  'up|up': ['Prices and estimates both rose.', 'up'],
};

// The sentence for a basket's pair of states, with its tone. A basket with too
// few names carrying an estimate says so rather than guess the second half.
export function reading(state, periodLabel) {
  if (!state || !state.price) return { text: 'No price reading: the price history does not reach back to the event.', tone: 'dim' };
  if (!state.estimates) {
    const n = state.names_with_estimates || 0;
    return { text: `Prices ${MOVE[state.price]}. ${n} name${n === 1 ? '' : 's'} with a recorded estimate: too few to say whether estimates followed.`, tone: 'dim' };
  }
  const [text, tone] = READING[`${state.price}|${state.estimates}`];
  return { text: `${text} (${(periodLabel || 'this year').toLowerCase()} estimates)`, tone };
}

export function signed(v, digits = 1, unit = '%') {
  return finite(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${unit}` : DASH;
}

// "26↑ 1↓" for a count pair; a blank is a blank, never zero.
export function countPair(up, down) {
  return finite(up) || finite(down) ? `${finite(up) ? up : DASH}↑ ${finite(down) ? down : DASH}↓` : DASH;
}

export function countsText(counts) {
  if (!counts) return DASH;
  const seven = countPair(counts.up_7d, counts.down_7d);
  const thirty = countPair(counts.up_30d, counts.down_30d);
  return seven === DASH ? `30d ${thirty}` : `7d ${seven} · 30d ${thirty}`;
}

export const KIND = { demand: 'DEMAND', competition: 'COMPETITION', supply: 'SUPPLY' };

export function kindLabel(kind) {
  return KIND[kind] || (kind ? String(kind).toUpperCase() : null);
}

// A basket line for the table's foot: the median over the names with a figure and how many that is.
export function medianCell(summary, digits = 1) {
  if (!summary || !summary.n || !finite(summary.median)) return DASH;
  return `${signed(summary.median, digits)} (${summary.n})`;
}
