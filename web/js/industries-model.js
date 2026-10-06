// INDUSTRIES: which rows a filter keeps, how a column sorts, which evidence tags a row carries.
// Pure functions, tested under node; the view only draws what these return.

export const LEVELS = [
  { id: 'sub_industries', label: 'SUB-INDUSTRIES' },
  { id: 'sectors', label: 'SECTORS' },
];

// A filter keeps rows by evidence the build already computed against the
// thresholds in config; nothing here decides what counts as sold off.
export const FILTERS = [
  { id: 'all', label: 'ALL', keep: () => true },
  { id: 'sold_off', label: 'SOLD OFF', keep: (r) => r.evidence.sold_off === true },
  { id: 'sold_off_held', label: 'SOLD OFF · ESTIMATES HELD',
    keep: (r) => r.evidence.sold_off === true && r.evidence.estimates_cut === false },
];

// Column key -> the value a row sorts on.
export const VALUE = {
  label: (r) => r.label,
  members: (r) => r.members,
  weight: (r) => r.weight,
  r1M: (r) => r.returns['1M'],
  r3M: (r) => r.returns['3M'],
  r6M: (r) => r.returns['6M'],
  down_share: (r) => r.down_share,
  drawdown: (r) => r.drawdown,
  above_ma: (r) => r.above_ma,
  rev30: (r) => r.revision['30d'],
  rev90: (r) => r.revision['90d'],
  forward_pe: (r) => r.forward_pe.median,
  pe_percentile: (r) => r.pe_percentile.median,
};

const present = (v) => v !== null && v !== undefined && !Number.isNaN(v);

export function applyFilters(rows, { filter = 'all', sector = '' } = {}) {
  const keep = (FILTERS.find((f) => f.id === filter) || FILTERS[0]).keep;
  return rows.filter((r) => keep(r) && (!sector || r.sector === sector));
}

// A reading that is missing sorts last whichever way the column runs.
export function sortRows(rows, key, descending) {
  const read = VALUE[key] || VALUE.r1M;
  return [...rows].sort((a, b) => {
    const av = read(a);
    const bv = read(b);
    if (!present(av) && !present(bv)) return 0;
    if (!present(av)) return 1;
    if (!present(bv)) return -1;
    const order = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
    return descending ? -order : order;
  });
}

// Evidence a row carries, as tags. A flag that could not be computed shows no
// tag at all: its absence is the em dash in its column, never a verdict.
export function evidenceTags(row, settings) {
  const e = row.evidence;
  const tags = [];
  if (e.sold_off === true) {
    tags.push({
      text: 'SOLD OFF', tone: 'down',
      title: `median 1M return at or below ${settings.sold_off_return_pct}% and at least ${Math.round(settings.sold_off_down_share * 100)}% of names down`,
    });
  }
  if (e.estimates_cut === true) {
    tags.push({
      text: 'EST CUT', tone: 'warn',
      title: `median FY1 EPS revision below ${settings.estimates_cut_30d_pct}% (30d) or ${settings.estimates_cut_90d_pct}% (90d)`,
    });
  } else if (e.estimates_cut === false) {
    tags.push({ text: 'EST HELD', tone: 'info', title: 'median FY1 EPS revisions are not below the thresholds' });
  }
  if (e.cheap_vs_own_history === true) {
    tags.push({ text: 'P/E LOW', tone: 'info', title: `median P/E percentile against its own ten years is at or below ${settings.cheap_percentile}` });
  }
  return tags;
}

// The sectors present, for the filter's menu.
export function sectorsOf(rows) {
  return [...new Set(rows.map((r) => r.sector).filter(Boolean))].sort();
}
