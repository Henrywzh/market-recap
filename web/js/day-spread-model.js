// THE DAY'S SPREAD (INDICES): how an index's members moved in one session,
// as a histogram, kept apart from the DOM so it can be tested under node.
// The index's own move is a weighted average; the histogram shows whether
// the members moved with it or a few heavy names carried it.

const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const key = (ticker) => String(ticker || '').toUpperCase().replace('.', '-');

// members: [{ticker, name, sector, weight, ret}] from the build's 1D returns,
// or from live quotes (``quotes``: Map symbol -> {change_pct}) when given.
// A member with no move is left out and counted as missing, never as zero.
export function members(constituents, quotes = null) {
  const out = []; let missing = 0;
  for (const c of constituents || []) {
    const live = quotes ? quotes.get(key(c.ticker)) : null;
    const ret = quotes ? live?.change_pct : c.returns?.['1D'];
    if (!finite(ret)) { missing += 1; continue; }
    out.push({ ticker: c.ticker, name: c.name, sector: c.sector, weight: finite(c.weight) ? c.weight : 0, ret });
  }
  return { members: out, missing };
}

// Bins of ``width`` percent with edges on multiples of it, so 0 is an edge and
// no bin mixes risers with fallers; moves past ±``clip`` share the end bins
// (their own moves stay in the bin's list, for the tooltip).
export function bins(list, { width = null, clip = null } = {}) {
  if (!list.length) return { width: 0.5, clip: 0, bins: [] };
  const sorted = list.map((m) => m.ret).sort((a, b) => a - b);
  const at = (q) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(q * (sorted.length - 1))))];
  // The range holds the middle 96% of members, never past ±10%: a handful of
  // outliers must not squeeze everyone else into a few bars.
  const span = Math.min(10, Math.max(Math.abs(at(0.02)), Math.abs(at(0.98))));
  const w = width ?? (span > 5 ? 0.5 : 0.25);
  const edge = clip ?? Math.max(w * 4, Math.ceil(span / w) * w);
  const count = Math.round((2 * edge) / w);
  const out = Array.from({ length: count }, (_, i) => {
    const lo = -edge + i * w;
    return { lo, hi: lo + w, center: lo + w / 2, count: 0, weight: 0, names: [] };
  });
  for (const m of list) {
    const i = Math.min(count - 1, Math.max(0, Math.floor((m.ret + edge) / w)));
    out[i].count += 1; out[i].weight += m.weight; out[i].names.push(m);
  }
  out.forEach((b) => b.names.sort((a, c) => c.weight - a.weight));
  return { width: w, clip: edge, bins: out };
}

const median = (values) => {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b); const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
};

// The day in numbers: how many rose and fell, the typical member against the
// weighted move, and how much of that move the heaviest names account for.
export function summary(list, { top = 10 } = {}) {
  const total = list.reduce((a, m) => a + m.weight, 0);
  const weighted = total > 0 ? list.reduce((a, m) => a + m.weight * m.ret, 0) / total : null;
  const heavy = [...list].sort((a, b) => b.weight - a.weight).slice(0, top)
    .map((m) => ({ ...m, contribution: total > 0 ? (m.weight * m.ret) / total : null }));
  const heavyPart = heavy.reduce((a, m) => a + (m.contribution ?? 0), 0);
  return {
    n: list.length,
    up: list.filter((m) => m.ret > 0).length,
    down: list.filter((m) => m.ret < 0).length,
    flat: list.filter((m) => m.ret === 0).length,
    median: median(list.map((m) => m.ret)),
    equal: list.length ? list.reduce((a, m) => a + m.ret, 0) / list.length : null,
    weighted,
    heavy,
    heavy_part: weighted === null ? null : heavyPart,
    rest_part: weighted === null ? null : weighted - heavyPart,
    heavy_weight: total > 0 ? heavy.reduce((a, m) => a + m.weight, 0) / total * 100 : null,
  };
}

// Rows for the heavy names above the bars, so labels at nearby moves do not
// sit on each other: each takes the lowest row whose last label is far enough left.
export function labelRows(heavy, gap) {
  const ends = [];
  return [...heavy].sort((a, b) => a.ret - b.ret).map((m) => {
    let row = ends.findIndex((end) => m.ret - end >= gap);
    if (row < 0) { row = ends.length; ends.push(m.ret); } else ends[row] = m.ret;
    return { ...m, row };
  });
}

// One line for the card: is it a broad day or a narrow one?
export function verdict(s) {
  if (!s.n || s.weighted === null || s.median === null) return null;
  const gap = s.weighted - s.median;
  const share = s.up / s.n;
  const breadth = share >= 0.8 ? 'broad rise' : share <= 0.2 ? 'broad fall' : share >= 0.6 ? 'most rose' : share <= 0.4 ? 'most fell' : 'split day';
  if (Math.abs(gap) < 0.4) return `${breadth}: the typical member moved with the index`;
  return `${breadth}: the index ${gap > 0 ? 'did better' : 'did worse'} than its typical member by ${Math.abs(gap).toFixed(1)} points, the heaviest names ${gap > 0 ? 'holding it up' : 'pulling it down'}`;
}
