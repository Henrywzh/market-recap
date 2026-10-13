// K-SHAPE: how the build's ratios read on the page. Pure, tested under node.
// The build measured every number; these functions only phrase them and pick a
// tone. Nothing here says which leg is right.

import { num, DASH } from './fmt.js';
import { sliceWindow } from './windows.js';

const finite = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits) => (finite(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}` : DASH);

export function ordinal(n) {
  if (!finite(n)) return DASH;
  const k = Math.round(n);
  const tail = k % 100;
  const suffix = tail >= 11 && tail <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[k % 10] || 'th');
  return `${k}${suffix}`;
}

// Where today's ratio sits among its own past weeks. High and low are
// descriptions of the history, not of value: the tone is only 'warn' at the
// extremes so that the eye finds them.
export function percentileView(p) {
  if (!finite(p)) return { text: DASH, tone: 'dim', title: 'too little history to place it' };
  const text = `${ordinal(p)} percentile`;
  const tone = p >= 85 ? 'warn' : p <= 15 ? 'info' : 'dim';
  return { text, tone, title: `today's ratio is at or above ${Math.round(p)}% of its own weeks` };
}

// "1.89×": the top leg's multiple over the bottom's.
export function multipleText(x) {
  return finite(x) ? `${num(x, 2)}×` : DASH;
}

// What the top leg is priced at against what it is expected to earn, in the
// build's own figures: the premium (or discount) in forward P/E, and the gap
// in consensus EPS growth for this fiscal year.
export function premiumView(now) {
  if (!now || !finite(now.pe_forward_ratio)) return { text: 'no forward multiple for both legs', premiumPct: null, growthGap: null };
  const premiumPct = (now.pe_forward_ratio - 1) * 100;
  const growthGap = finite(now.eps_growth_this_year_top) && finite(now.eps_growth_this_year_bottom) ? now.eps_growth_this_year_top - now.eps_growth_this_year_bottom : null;
  const pay = `${premiumPct >= 0 ? 'pays' : 'is priced'} ${num(Math.abs(premiumPct), 0)}% ${premiumPct >= 0 ? 'more' : 'less'} per dollar of earnings`;
  const grow = growthGap === null ? '' : `, against consensus EPS growth ${growthGap >= 0 ? 'ahead' : 'behind'} by ${num(Math.abs(growthGap), 1)} points`;
  return { text: `The top leg ${pay}${grow}.`, premiumPct, growthGap };
}

export function spreadRows(spreads) {
  return (spreads || []).map((s) => ({
    period: s.period, top: s.top, bottom: s.bottom, spread: s.spread,
    tone: !finite(s.spread) ? 'dim' : s.spread > 0 ? 'up' : 'down',
  }));
}

// A name's row: forward P/E with its source, and the figures the valuation tab
// has. A name outside the valuation universe says so, never a zero.
export function nameRow(n) {
  const source = n.forward_source === 'consensus' ? 'consensus only' : n.forward_source === 'valuation' ? 'valuation tab' : null;
  return {
    ticker: n.ticker, leg: n.leg,
    pe: finite(n.pe_forward) ? `${num(n.pe_forward, 1)}×` : DASH,
    peTitle: source ? `forward P/E: ${source}` : 'no forward multiple',
    percentile: finite(n.pe_percentile) ? ordinal(n.pe_percentile) : DASH,
    growth: signed(n.eps_growth_this_year, 1),
    revenue: signed(n.revenue_growth, 1),
    ret3m: n.ret_3m, ret1y: n.ret_1y,
    since: n.first_price,
  };
}

// The weeks of a ratio that are used, as a sentence for the chart note.
export function peRangeText(pe) {
  if (!pe) return null;
  return `median ${multipleText(pe.ratio_median)}, 10th to 90th percentile ${multipleText(pe.ratio_p10)} to ${multipleText(pe.ratio_p90)}, ${pe.dates_used} weeks`;
}

// The price ratio and the two legs cut to the window: the ratio is =1 and each
// leg =100 at the window's first close. Only the price charts are rebased.
export function legSeries(price, window) {
  return sliceWindow(price.dates, { ratio: price.ratio, top: price.top, bottom: price.bottom }, window,
    { ratio: 'ratio', top: 'index', bottom: 'index' });
}

// Trailing P/E medians and their ratio cut to the window, as readings: a P/E is
// never rebased, so the cut is all that changes.
export function peSeries(pe, window) {
  return sliceWindow(pe.dates, { ratio: pe.ratio, top: pe.top, bottom: pe.bottom }, window);
}

// Year-on-year EPS growth cut to the window; a growth rate is not rebased.
export function epsSeries(eps, window) {
  return sliceWindow(eps.dates, { top: eps.top, bottom: eps.bottom }, window);
}
