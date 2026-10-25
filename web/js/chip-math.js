// Where a stock's shares traded, and an estimate of what its holders paid,
// from daily bars (artifacts/bars). No DOM, so it can be tested under node.
//
// VOLUME PROFILE: each session's volume spread over its own low-to-high range,
// summed by price over a window. The price that traded most (the point of
// control) and the band around it holding 70% of the volume (the value area)
// are counts, not a model.
//
// COST DISTRIBUTION: the same spread, but each session first turns over its
// share of the holdings -- volume / shares outstanding -- so a session's price
// fades as later sessions trade the stock again. The decay is an assumption
// (the one Chinese charting software uses), and a share traded by a market
// maker or a high-frequency desk counts as one changing hands, so it is an
// estimate of holders' cost, not a record of it.

const finite = (v) => typeof v === 'number' && Number.isFinite(v);

export const VALUE_AREA_SHARE = 0.7;

// Bins of equal width from min to max; centers ascending.
export function grid(min, max, count) {
  if (!finite(min) || !finite(max) || !(max > min) || count < 2) return null;
  const step = (max - min) / count;
  return { min, max, step, count, centers: Array.from({ length: count }, (_, i) => min + step * (i + 0.5)) };
}

// One session's weight per bin: a triangle over [low, high] peaking at the
// typical price (high + low + close) / 3, summing to 1.
export function spread(g, low, high, close) {
  if (!g || !finite(low) || !finite(high) || !finite(close)) return null;
  const lo = Math.max(Math.min(low, high), g.min);
  const hi = Math.min(Math.max(low, high), g.max);
  const index = (p) => Math.min(g.count - 1, Math.max(0, Math.floor((p - g.min) / g.step)));
  if (hi < lo) return null;
  const first = index(lo);
  const last = index(hi);
  if (last === first) return { first, weights: [1] };
  const peak = Math.min(hi, Math.max(lo, (low + high + close) / 3));
  const reach = Math.max(peak - lo, hi - peak, g.step);
  const weights = [];
  for (let i = first; i <= last; i += 1) weights.push(Math.max(0.05, 1 - Math.abs(g.centers[i] - peak) / reach));
  const total = weights.reduce((s, w) => s + w, 0);
  return { first, weights: weights.map((w) => w / total) };
}

// The range of prices bars [from, to] traded at.
export function priceRange(bars, from, to) {
  let min = Infinity;
  let max = -Infinity;
  for (let i = from; i <= to; i += 1) {
    if (finite(bars.low[i])) min = Math.min(min, bars.low[i]);
    if (finite(bars.high[i])) max = Math.max(max, bars.high[i]);
  }
  return finite(min) && finite(max) && max > min ? { min, max } : null;
}

export function volumeProfile(bars, from, to, g) {
  const out = new Array(g.count).fill(0);
  for (let i = from; i <= to; i += 1) {
    const v = bars.volume[i];
    if (!finite(v) || v <= 0) continue;
    const s = spread(g, bars.low[i], bars.high[i], bars.close[i]);
    if (!s) continue;
    s.weights.forEach((w, k) => { out[s.first + k] += v * w; });
  }
  return out;
}

// Holdings by price after bars [0, to], each session turning over volume /
// shares of them. Returns shares of holdings per bin (summing to 1) and the
// share of the total that fell outside the grid.
export function costDistribution(bars, to, g, shares) {
  if (!finite(shares) || shares <= 0) return null;
  const chips = new Array(g.count).fill(0);
  let outside = 0;
  for (let i = 0; i <= to; i += 1) {
    const v = bars.volume[i];
    if (!finite(v) || v <= 0 || !finite(bars.low[i]) || !finite(bars.high[i])) continue;
    const turnover = Math.min(1, v / shares);
    const keep = 1 - turnover;
    for (let k = 0; k < g.count; k += 1) chips[k] *= keep;
    outside *= keep;
    const s = spread(g, bars.low[i], bars.high[i], bars.close[i]);
    // A session entirely outside the grid still holds its shares, off the chart.
    if (!s || bars.high[i] < g.min || bars.low[i] > g.max) { outside += turnover; continue; }
    s.weights.forEach((w, k) => { chips[s.first + k] += turnover * w; });
  }
  const total = chips.reduce((a, b) => a + b, 0) + outside;
  if (!(total > 0)) return null;
  return { chips: chips.map((c) => c / total), outside: outside / total };
}

// The point of control and the value area: from the busiest bin, add whichever
// neighbour holds more until VALUE_AREA_SHARE of the volume is inside.
export function valueArea(profile, g, share = VALUE_AREA_SHARE) {
  const total = profile.reduce((a, b) => a + b, 0);
  if (!(total > 0)) return null;
  const poc = profile.indexOf(Math.max(...profile));
  let lo = poc;
  let hi = poc;
  let inside = profile[poc];
  while (inside < total * share && (lo > 0 || hi < profile.length - 1)) {
    const below = lo > 0 ? profile[lo - 1] : -1;
    const above = hi < profile.length - 1 ? profile[hi + 1] : -1;
    if (above >= below) { hi += 1; inside += profile[hi]; } else { lo -= 1; inside += profile[lo]; }
  }
  return { poc: g.centers[poc], low: g.min + lo * g.step, high: g.min + (hi + 1) * g.step, share: inside / total };
}

// Price at which the cumulative share of chips reaches q.
function quantile(chips, g, q) {
  let cumulative = 0;
  for (let k = 0; k < chips.length; k += 1) {
    if (cumulative + chips[k] >= q) {
      const into = chips[k] > 0 ? (q - cumulative) / chips[k] : 0;
      return g.min + (k + into) * g.step;
    }
    cumulative += chips[k];
  }
  return g.max;
}

// Average cost, the share held below the price (in profit), and the bands
// holding the middle 70% and 90% of the holdings, with the 90% band's width
// as a share of its midpoint (narrower = more concentrated).
export function costStats(distribution, g, price) {
  if (!distribution || !finite(price)) return null;
  const { chips } = distribution;
  const inside = chips.reduce((a, b) => a + b, 0);
  if (!(inside > 0)) return null;
  const scaled = chips.map((c) => c / inside);
  const average = scaled.reduce((s, c, k) => s + c * g.centers[k], 0);
  let profit = 0;
  scaled.forEach((c, k) => {
    const lo = g.min + k * g.step;
    if (lo + g.step <= price) profit += c;
    else if (lo < price) profit += c * ((price - lo) / g.step);
  });
  const band = (share) => [quantile(scaled, g, (1 - share) / 2), quantile(scaled, g, 1 - (1 - share) / 2)];
  const b90 = band(0.9);
  return {
    average, profitShare: profit, band70: band(0.7), band90: b90,
    concentration: (b90[1] - b90[0]) / ((b90[1] + b90[0]) / 2), outside: distribution.outside,
  };
}

// Index of the last bar on or before an ISO date (or the last bar).
export function indexAt(bars, date) {
  if (!date) return bars.dates.length - 1;
  let i = bars.dates.length - 1;
  while (i > 0 && bars.dates[i] > date) i -= 1;
  return i;
}
