// EUROPE: how the build's numbers read on the page. Pure, tested under node.

import { num, DASH } from './fmt.js';

const finite = (v) => v !== null && v !== undefined && Number.isFinite(v);

// A price with its currency: London quotes in pence, shown as "1,234p".
export function priceText(value, currency) {
  if (!finite(value)) return DASH;
  if (currency === 'GBp') return `${num(value, 0)}p`;
  return currency ? `${num(value, value >= 1000 ? 0 : 2)} ${currency}` : num(value, value >= 1000 ? 0 : 2);
}

// A multiple; one over 100 is a profit near zero, shown as ">100×".
export function multipleText(v) {
  if (!finite(v)) return DASH;
  return v > 100 ? '>100×' : `${num(v, 1)}×`;
}

// Consensus EPS growth: a figure beyond the build's cap is "n/m", not a number.
export function growthText(r) {
  if (finite(r.eps_growth)) return `${r.eps_growth > 0 ? '+' : ''}${num(r.eps_growth, 0)}%`;
  return r.eps_growth_out_of_range ? 'n/m' : DASH;
}

export function flagText(v) {
  return v === true ? '▲' : v === false ? '▼' : DASH;
}

// Rows sorted by a column; a missing value goes last whichever way the sort runs.
export function sortRows(rows, getter, direction = 'desc') {
  const sign = direction === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = getter(a), y = getter(b);
    const mx = x === null || x === undefined || (typeof x === 'number' && !Number.isFinite(x));
    const my = y === null || y === undefined || (typeof y === 'number' && !Number.isFinite(y));
    if (mx && my) return 0;
    if (mx) return 1;
    if (my) return -1;
    if (typeof x === 'string') return sign * x.localeCompare(y);
    return sign * (x - y);
  });
}

// The columns of the names table: label, how to read a row, and the sort's first direction.
export const NAME_COLUMNS = [
  { key: 'symbol', label: 'SYMBOL', get: (r) => r.symbol, first: 'asc' },
  { key: 'name', label: 'NAME', get: (r) => r.name, first: 'asc' },
  { key: 'sector', label: 'SECTOR', get: (r) => r.sector, first: 'asc' },
  { key: 'price', label: 'PRICE', get: (r) => r.last, first: 'desc' },
  { key: '1D', label: '1D', get: (r) => r.returns?.['1D'], first: 'desc' },
  { key: '1M', label: '1M', get: (r) => r.returns?.['1M'], first: 'desc' },
  { key: '3M', label: '3M', get: (r) => r.returns?.['3M'], first: 'desc' },
  { key: 'YTD', label: 'YTD', get: (r) => r.returns?.YTD, first: 'desc' },
  { key: '1Y', label: '1Y', get: (r) => r.returns?.['1Y'], first: 'desc' },
  { key: 'dd', label: 'FROM 52W HIGH', get: (r) => r.drawdown_pct, first: 'asc' },
  { key: 'fpe', label: 'FWD P/E', get: (r) => r.forward_pe, first: 'asc' },
  { key: 'tpe', label: 'TRAIL P/E', get: (r) => r.trailing_pe, first: 'asc' },
  { key: 'g', label: 'EPS G', get: (r) => r.eps_growth, first: 'desc' },
];

// The sectors in a list of rows, for the filter: name and count, biggest first.
export function sectorCounts(rows) {
  const by = new Map();
  rows.forEach((r) => by.set(r.sector, (by.get(r.sector) || 0) + 1));
  return [...by.entries()].map(([sector, n]) => ({ sector, n })).sort((a, b) => b.n - a.n || a.sector.localeCompare(b.sector));
}

// What a name's forward multiple says against the group's median, in the build's
// own figures: "x% above the group's median"; blank without both.
export function againstMedian(value, median) {
  if (!finite(value) || !finite(median) || median <= 0) return null;
  const pct = (value / median - 1) * 100;
  return `${pct >= 0 ? '+' : ''}${num(pct, 0)}% vs median`;
}

export function medianOf(values) {
  const v = values.filter(finite).sort((a, b) => a - b);
  if (!v.length) return null;
  const mid = Math.floor(v.length / 2);
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
}

// MARKET-CAP MAP: the FTSE 100 and EURO STOXX 50 members as a treemap. Area is
// market cap, colour is the chosen window's return. Pure, so it is tested under node.

// The windows the map offers, shortest first. A universe shows only those its names carry.
export const MAP_PERIODS = ['1D', '1W', '1M', '3M', 'YTD', '1Y'];

// Each window saturates its colour at its own move: a day's and a year's are
// not comparable on one scale, so a 3% day and a 3% year look different.
const MAP_CAP = { '1D': 3, '1W': 6, '1M': 10, '3M': 15, YTD: 20, '1Y': 30 };

export function mapColourCap(period) {
  return MAP_CAP[period] ?? 10;
}

export function mapPeriods(names) {
  return MAP_PERIODS.filter((p) => names.some((n) => Object.hasOwn(n.returns || {}, p)));
}

// The currency a market cap is quoted in. A London price is in pence, but the
// build's London caps are in pounds (3i's comes to about 25bn, not 2,500bn).
export function marketCapCurrency(currency) {
  return currency === 'GBp' ? 'GBP' : currency || '';
}

// A market cap in billions of the name's currency, e.g. "27.7bn EUR".
export function marketCapText(value, currency) {
  if (!finite(value)) return DASH;
  return `${num(value / 1e9, 1)}bn ${marketCapCurrency(currency)}`.trim();
}

// The members with a usable market cap, grouped by sector for the treemap. A
// member with no positive, finite cap has no area to draw, so it is left out
// and counted in `missing`. A missing return for the window gets a grey tile.
export function mapGroups(names, period, colour) {
  const groups = new Map();
  let missing = 0;
  names.forEach((n) => {
    if (!finite(n.market_cap) || n.market_cap <= 0) {
      missing += 1;
      return;
    }
    const ret = finite(n.returns?.[period]) ? n.returns[period] : null;
    const sector = n.sector || 'Other';
    if (!groups.has(sector)) groups.set(sector, []);
    groups.get(sector).push({
      key: n.symbol,
      value: n.market_cap,
      color: colour(ret),
      label: String(n.symbol).split('.')[0],
      sublabel: ret === null ? DASH : `${ret > 0 ? '+' : ''}${num(ret, 1)}%`,
      payload: { symbol: n.symbol, name: n.name, sector, currency: n.currency, market_cap: n.market_cap, ret, period },
    });
  });
  const grouped = [...groups].map(([group, items]) => ({ group, items }));
  return { groups: grouped, sized: names.length - missing, missing, total: names.length };
}

// The note under the map: how many members are left out, and what the figures are.
export function mapNote(shaped) {
  const left = shaped.missing
    ? `${shaped.missing} of ${shaped.total} members have no market cap in the build and are left out.`
    : `All ${shaped.total} members are sized.`;
  return `${left} Returns are in local currency; market caps are as Yahoo reports them.`;
}
