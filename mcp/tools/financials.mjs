// financials: one company's filed statements -- ten fiscal years, or its last
// quarters -- with the ratios the FINANCIALS view shows, and its trailing-twelve-
// month margins from the VALUATION row. Values are the artifacts' own: nothing
// is recomputed here.

import { cleanTicker, resolveTicker } from '../../web/js/routes.js';
import { outputSchema } from '../context.mjs';
import { T } from '../schema.mjs';
import { finite } from '../util.mjs';
import { resolveSymbol } from './ticker.mjs';

const DEFAULT_QUARTERS = 8;
const MAX_QUARTERS = 24;

// The build's key for a typed symbol: the names every other tool knows first,
// then the companies FINANCIALS extracted (it can cover a name the panels lack).
async function resolve(ctx, requested, index) {
  const symbol = await resolveSymbol(ctx, requested);
  if (symbol) return symbol;
  const clean = cleanTicker(requested);
  if (!clean) return null;
  // Skipped names resolve too, so the reply can say why they have no statements.
  const names = new Set([...(index?.available || []).map((a) => a.ticker), ...Object.keys(index?.skipped || {})]);
  const dashed = resolveTicker(clean, (s) => names.has(s));
  return names.has(dashed) ? dashed : null;
}

const series = (values, key, from) => (Array.isArray(values?.[key]) ? values[key].slice(from).map(finite) : null);

// Statement groups in the index's order, each line with its label, unit and values.
function statements(index, values, from) {
  const groups = index?.statements && typeof index.statements === 'object' ? Object.entries(index.statements) : [];
  return Object.fromEntries(groups.map(([key, group]) => [key, {
    label: group.label ?? key,
    lines: (group.items || []).filter((item) => Array.isArray(values?.[item.key])).map((item) => ({
      key: item.key, label: item.label ?? item.key, unit: item.unit ?? null, values: series(values, item.key, from),
    })),
  }]));
}

function ratios(index, values, from) {
  return (index?.ratios || []).filter((r) => Array.isArray(values?.[r.key])).map((r) => ({
    key: r.key, label: r.label ?? r.key, unit: r.unit ?? null, values: series(values, r.key, from),
  }));
}

// The trailing-twelve-month margins on the same basis as the P/E in `ticker`.
function ttm(row, ctx) {
  if (!row) { ctx.missing('ttm', 'no VALUATION row for this symbol, so no trailing-twelve-month figures'); return null; }
  return {
    period_end: row.period_end ?? null, filed: row.filed ?? null,
    revenue_growth_pct: finite(row.revenue_growth), gross_margin_pct: finite(row.gross_margin), operating_margin_pct: finite(row.operating_margin),
    net_margin_pct: finite(row.net_margin), fcf_margin_pct: finite(row.fcf_margin), roic_pct: finite(row.roic), roe_pct: finite(row.roe),
    net_debt_ebitda: finite(row.net_debt_ebitda), interest_coverage: finite(row.interest_coverage),
  };
}

export async function financials(ctx, args) {
  const period = args.period || 'annual';
  const index = await ctx.get('financials', 'statements index');
  const symbol = await resolve(ctx, args.symbol, index);
  if (!symbol) {
    throw new Error(`No data for "${args.symbol}". It covers S&P 500 and Nasdaq-100 members; use the search tool to find a symbol, and write share classes either way (BRK.B or BRK-B).`);
  }
  const file = await ctx.read(`financials/${symbol}`);
  if (!file) {
    // The build's reason may already start with the symbol ("ASML: no annual ...").
    const reason = String(index?.skipped?.[symbol] || '').replace(new RegExp(`^${symbol.replace(/[.-]/g, '\\$&')}:\\s*`), '');
    throw new Error(`No filed statements for ${symbol}: ${reason || 'the build did not extract this company'}.`);
  }
  await ctx.get(`financials/${symbol}`, 'statements');
  await ctx.loadSlice(`ticker/${symbol}`);
  const valuation = await ctx.get('valuation', 'ttm');
  const row = (valuation?.rows || []).find((r) => r.ticker === symbol) || null;
  ctx.note(index?.note);
  ctx.caveat(
    'Figures are as most recently filed: a restated year shows its restated value, and each period says when it was last filed. A null is a line the filer did not tag, never a zero.',
    'Lists run oldest to newest; values[i] belongs to periods[i].',
  );

  let periods, values, from = 0, derived = null;
  if (period === 'quarterly') {
    const q = file.quarters || {};
    const count = Math.min(MAX_QUARTERS, args.quarters || DEFAULT_QUARTERS);
    const columns = q.columns || [];
    from = Math.max(0, columns.length - count);
    periods = columns.slice(from).map((c) => ({ label: c.label ?? null, fiscal_year: c.fiscal_year ?? null, quarter: c.quarter ?? null, period_end: c.period_end ?? null, filed: c.filed ?? null }));
    values = { ...(q.values || {}), ...(q.ratios || {}) };
    // Three-month figures worked out from year-to-date filings, by line: only lines with any.
    derived = Object.fromEntries(Object.entries(q.derived || {})
      .map(([key, flags]) => [key, (flags || []).slice(from).map(Boolean)])
      .filter(([, flags]) => flags.some(Boolean)));
    ctx.caveat('A quarter marked in `derived` was worked out from year-to-date figures (for example Q4 = fiscal year - nine months), not filed as a three-month figure.');
  } else {
    const columns = file.columns || [];
    periods = columns.map((c) => ({ label: c.fiscal_year != null ? `FY${c.fiscal_year}` : null, fiscal_year: c.fiscal_year ?? null, period_end: c.period_end ?? null, filed: c.filed ?? null }));
    values = { ...(file.values || {}), ...(file.ratios || {}) };
  }
  if (!periods.length) ctx.missing('periods', `financials/${symbol}.json has no ${period} columns`);

  return {
    symbol, requested: args.symbol, period, url: ctx.link(`ticker/${symbol}`),
    identity: { name: file.name ?? row?.name ?? null, sector: file.sector ?? row?.sector ?? null, entity_name: file.entity_name ?? null, cik: file.cik ?? null, source_url: file.source_url ?? null },
    periods,
    statements: statements(index, values, from),
    ratios: ratios(index, values, from),
    derived,
    ttm: ttm(row, ctx),
  };
}

const line = T.obj({ key: T.str, label: T.str, unit: T.strNull, values: T.arr(T.num) }, ['key', 'label', 'values']);

export const financialsTool = {
  name: 'financials',
  title: 'Company financials',
  description: 'One S&P 500 / Nasdaq-100 company\'s filed statements from its own SEC XBRL facts: income statement, balance sheet and cash flow line by line, with revenue growth, gross / operating / net / FCF margins, ROE, ROA, ROIC, net debt and interest coverage. `period` annual (default: up to ten fiscal years) or quarterly (the last `quarters`, default 8, at most 24). Every period says when it was last filed. Also `ttm`: trailing-twelve-month margins and returns on the same basis as the P/E in `ticker`. Lists run oldest to newest. IFRS filers are not extracted.',
  inputSchema: T.obj({
    symbol: { type: 'string', minLength: 1, maxLength: 15, description: 'Ticker, e.g. NVDA or BRK.B.' },
    period: { type: 'string', enum: ['annual', 'quarterly'], description: 'annual (default) or quarterly.' },
    quarters: { type: 'integer', minimum: 1, maximum: MAX_QUARTERS, description: `Quarterly only: how many of the latest quarters, default ${DEFAULT_QUARTERS}.` },
  }, ['symbol']),
  outputSchema: outputSchema({
    symbol: T.str, requested: T.str, period: T.str, url: T.str,
    identity: T.obj({ name: T.strNull, sector: T.strNull, source_url: T.strNull }, ['name', 'sector']),
    periods: T.arr(T.obj({ label: T.strNull, fiscal_year: T.int, period_end: T.strNull, filed: T.strNull }, ['period_end', 'filed'])),
    statements: { type: 'object' },
    ratios: T.arr(line),
    derived: T.maybe(T.obj()),
    ttm: T.maybe(T.obj({ period_end: T.strNull, gross_margin_pct: T.num, operating_margin_pct: T.num, net_margin_pct: T.num, fcf_margin_pct: T.num, roic_pct: T.num })),
  }, ['symbol', 'period', 'periods', 'statements', 'ratios', 'ttm']),
  run: financials,
};
