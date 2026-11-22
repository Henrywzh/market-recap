// screen: the VALUATION table (every S&P 500 / Nasdaq-100 member, from its own
// filings) filtered and sorted by the reader's conditions. A filter, not a
// ranking: the order is the one the reader asked for, never a score.

import { outputSchema } from '../context.mjs';
import { T } from '../schema.mjs';
import { finite } from '../util.mjs';

// The metrics a reader can filter, sort or show: the table's own (labels come
// from the artifact's `metrics` list) and the row fields beside them.
export const TABLE_METRICS = [
  'pe', 'pe_operating', 'pe_forward', 'pe_percentile', 'pe_vs_median', 'ev_ebitda', 'ev_sales', 'pb', 'ptbv', 'ptbv_percentile',
  'fcf_yield', 'dividend_yield', 'shareholder_yield', 'implied_growth', 'consensus_growth',
  'roe', 'rotce', 'roic', 'gross_profitability', 'operating_margin', 'revenue_growth', 'accruals', 'net_debt_ebitda',
  'interest_coverage', 'piotroski', 'margin_stability',
];
const EXTRA = {
  market_cap: { label: 'Market cap', unit: 'usd', better: null },
  price: { label: 'Price', unit: 'usd', better: null },
  gross_margin: { label: 'Gross margin (TTM)', unit: 'pct', better: 'high' },
  net_margin: { label: 'Net margin (TTM)', unit: 'pct', better: 'high' },
  fcf_margin: { label: 'FCF margin (TTM)', unit: 'pct', better: 'high' },
};
export const SCREEN_METRICS = [...TABLE_METRICS, ...Object.keys(EXTRA)];
// The row fields the adapter reads; src/market_recap/mcp_slices.py keeps the same.
export const SCREEN_ROW_KEYS = ['ticker', 'name', 'sector', 'sub_sector', 'indices', 'period_end', ...SCREEN_METRICS];

const DEFAULT_FIELDS = ['market_cap', 'pe', 'pe_forward', 'operating_margin', 'revenue_growth'];
const MAX_FIELDS = 12;
const DEFAULT_LIMIT = 25;
const MAX_LIMIT = 100;

function definitions(valuation) {
  const listed = new Map((valuation?.metrics || []).map((m) => [m.key, m]));
  return (key) => {
    const m = listed.get(key) || EXTRA[key] || {};
    return { key, label: m.label ?? key, unit: m.unit ?? null, lower_is_cheaper_or_better: m.better === 'low' ? true : m.better === 'high' ? false : null };
  };
}

const norm = (s) => String(s || '').trim().toLowerCase();

// A GICS sector or sub-industry by its name: exact first, then a part of it.
function sectorFilter(rows, wanted) {
  const w = norm(wanted);
  const exact = rows.filter((r) => norm(r.sector) === w || norm(r.sub_sector) === w);
  if (exact.length) return exact;
  return rows.filter((r) => norm(r.sector).includes(w) || norm(r.sub_sector).includes(w));
}

function passes(value, filter) {
  if (filter.min !== undefined && value < filter.min) return false;
  if (filter.max !== undefined && value > filter.max) return false;
  return true;
}

export async function screen(ctx, args) {
  await ctx.loadSlice('screen');
  const valuation = await ctx.get('valuation', 'table');
  if (!valuation) return { url: ctx.link('valuation'), universe: 0, matched: 0, excluded_missing: {}, metrics: [], rows: [] };
  const define = definitions(valuation);
  const filters = args.filters || [];
  const bad = filters.filter((f) => f.min === undefined && f.max === undefined).map((f) => f.metric);
  if (bad.length) throw new Error(`Each filter needs min, max or both: ${bad.join(', ')}.`);

  let rows = (valuation.rows || []).filter((r) => r && typeof r.ticker === 'string');
  if (args.index) rows = rows.filter((r) => (r.indices || []).includes(args.index));
  if (args.sector) {
    const found = sectorFilter(rows, args.sector);
    if (!found.length) {
      const sectors = [...new Set((valuation.rows || []).map((r) => r.sector).filter(Boolean))].sort();
      throw new Error(`No sector or sub-industry matches "${args.sector}". Sectors: ${sectors.join(', ')}; a sub-industry name (e.g. Semiconductors) also works.`);
    }
    rows = found;
  }
  const universe = rows.length;

  // A row without the filtered value is left out, and counted, never treated as a pass.
  const excluded = {};
  for (const f of filters) {
    const kept = rows.filter((r) => finite(r[f.metric]) !== null);
    if (kept.length < rows.length) excluded[f.metric] = (excluded[f.metric] || 0) + rows.length - kept.length;
    rows = kept.filter((r) => passes(r[f.metric], f));
  }

  const sort = args.sort || 'market_cap';
  const better = define(sort).lower_is_cheaper_or_better;
  const order = args.order || (better === true ? 'asc' : 'desc');
  const sign = order === 'asc' ? 1 : -1;
  rows = [...rows].sort((a, b) => {
    const x = finite(a[sort]), y = finite(b[sort]);
    if (x === null || y === null) return (x === null) - (y === null) || a.ticker.localeCompare(b.ticker);
    return sign * (x - y) || a.ticker.localeCompare(b.ticker);
  });

  const fields = [...new Set([...DEFAULT_FIELDS, ...filters.map((f) => f.metric), sort, ...(args.fields || [])])].slice(0, MAX_FIELDS);
  const limit = args.limit || DEFAULT_LIMIT;
  ctx.note(valuation.note);
  ctx.caveat(
    'A filter over filed figures, not a ranking or a recommendation: rows are in the order asked for.',
    'Flows are trailing twelve months from each company\'s latest 10-Q / 10-K, so a row\'s period_end can trail another\'s by a quarter.',
    'P/E is blank when trailing earnings are negative; margins, EV multiples and ROIC are blank for the Financials sector. A row missing a filtered value is left out and counted in excluded_missing.',
  );
  return {
    url: ctx.link('valuation'),
    universe, matched: rows.length, excluded_missing: excluded,
    applied: { index: args.index ?? null, sector: args.sector ?? null, filters, sort, order },
    metrics: fields.map(define),
    rows: rows.slice(0, limit).map((r) => ({
      ticker: r.ticker, name: r.name ?? null, sector: r.sector ?? null, sub_sector: r.sub_sector ?? null, indices: r.indices ?? [], period_end: r.period_end ?? null,
      values: Object.fromEntries(fields.map((k) => [k, finite(r[k])])),
    })),
    more: Math.max(0, rows.length - limit),
  };
}

const metric = { type: 'string', enum: SCREEN_METRICS };

export const screenTool = {
  name: 'screen',
  title: 'Screen companies',
  description: 'Filter and sort every S&P 500 / Nasdaq-100 member on the VALUATION table\'s filed figures: P/E (TTM, operating, forward NTM, percentile and gap to its own 10-year history), EV/EBITDA, EV/sales, P/B, FCF and dividend yield, gross / operating / net / FCF margin (TTM), ROE, ROIC, revenue growth, net debt/EBITDA, interest coverage, Piotroski, the growth the price implies, market cap. Example: sector "Semiconductors", filters [{metric: "operating_margin", min: 30}, {metric: "pe_vs_median", max: 0}], sort "pe_forward". Percent metrics are in percent (30 = 30%). Default sort market cap, largest first; default order follows the metric (cheapest first for multiples). Returns `matched` and up to `limit` rows; `more` says how many were left out.',
  inputSchema: T.obj({
    filters: { type: 'array', maxItems: 10, items: T.obj({ metric, min: { type: 'number' }, max: { type: 'number' } }, ['metric']), description: 'Conditions that must all hold; each has min, max or both.' },
    sector: { type: 'string', minLength: 2, maxLength: 60, description: 'GICS sector or sub-industry name, e.g. Information Technology, Semiconductors, Banks.' },
    index: { type: 'string', enum: ['SPX', 'NDX'], description: 'Members of one index only.' },
    sort: { ...metric, description: 'Metric to sort by; default market_cap.' },
    order: { type: 'string', enum: ['asc', 'desc'] },
    fields: { type: 'array', maxItems: 8, items: metric, description: 'Extra metrics to show for each row.' },
    limit: { type: 'integer', minimum: 1, maximum: MAX_LIMIT, description: `Rows to return, default ${DEFAULT_LIMIT}.` },
  }),
  outputSchema: outputSchema({
    url: T.str, universe: { type: 'integer' }, matched: { type: 'integer' }, excluded_missing: { type: 'object' },
    metrics: T.arr(T.obj({ key: T.str, label: T.str, unit: T.strNull }, ['key', 'label'])),
    rows: T.arr(T.obj({ ticker: T.str, name: T.strNull, sector: T.strNull, values: { type: 'object' } }, ['ticker', 'values'])),
  }, ['universe', 'matched', 'metrics', 'rows']),
  run: screen,
};
