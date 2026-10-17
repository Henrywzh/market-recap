// macro: inflation release cards, the Treasury curve, and commodities.

import { outputSchema } from '../context.mjs';
import { T } from '../schema.mjs';
import { capList, finite, pick, text } from '../util.mjs';

export const MACRO_KINDS = ['cpi', 'ppi', 'rates', 'commodities'];

const comparison = (c) => ({
  label: c.label, basis: c.basis ?? null, actual: finite(c.actual), consensus: finite(c.consensus), surprise_pp: finite(c.surprise_pp),
  previous: finite(c.previous), consensus_provenance: c.consensus_provenance ?? null,
});

const component = (c) => ({
  label: c.label, weight_pct: finite(c.weight_pct), mom_pct: finite(c.mom), yoy_pct: finite(c.yoy), previous_mom_pct: finite(c.previous_mom),
});

// CPI and PPI have the same card shape: the release's comparison with
// consensus, its components, and the persistence/momentum measures.
function inflationCard(card, label, ctx) {
  if (!card || card.status === 'unavailable') {
    ctx.missing(label, `macro.json has no ${label} card`);
    return null;
  }
  ctx.note(text(card.note, 600), text(card.refresh_note, 200));
  (Object.entries(card.failed_sources || {})).forEach(([k, why]) => ctx.missing(`${label} source ${k}`, text(String(why), 200)));
  const persistence = card.persistence || card.momentum || [];
  const components = capList((card.components || []).map(component), 14);
  return {
    month: card.month ?? null, published_at: card.published_at ?? null, status: card.status ?? null, source_url: card.source_url ?? null,
    release_vs_consensus: (card.comparisons || []).map(comparison),
    components: components.items, more_components: components.more,
    persistence: persistence.map((p) => ({
      label: p.label, value: finite(p.value ?? p.ann_3m), unit: p.unit ?? (p.ann_3m !== undefined ? '3M ann. %' : null), latest_month: p.latest_month ?? null, status: p.status ?? null,
      ...(p.ann_6m !== undefined ? { ann_6m: finite(p.ann_6m) } : {}),
    })),
    ai_related_series: (card.ai_series || []).map((s) => ({ label: s.label, mom_pct: finite(s.mom), yoy_pct: finite(s.yoy), month: s.latest_month ?? null })),
  };
}

function curve(fixed, ctx) {
  if (!fixed?.curves) { ctx.missing('rates', 'fixed_income.json is not published in this build'); return null; }
  ctx.note(text(fixed.note, 500));
  const curves = fixed.curves.map((c) => ({ label: c.label, date: c.date ?? null, yields_pct: Object.fromEntries((fixed.tenors || []).map((t, i) => [t, finite(c.values?.[i])])) }));
  return {
    tenors: fixed.tenors || [],
    curves,
    changes_bp: (fixed.rows || []).map((r) => ({ tenor: r.tenor, yield_pct: finite(r.yield_pct), ...Object.fromEntries((fixed.change_columns || []).map((c) => [c, finite(r[c])])) })),
    spreads_bp: (fixed.spreads || []).map((s) => pick(s, ['label', 'bps', '1D', '1W', '1M', 'YTD'])),
  };
}

function commodities(macro, ctx) {
  const block = macro?.commodities;
  if (!block?.rows) { ctx.missing('commodities', 'macro.json has no commodities block'); return null; }
  return block.rows.map((r) => ({
    label: r.label, symbol: r.symbol, price: finite(r.price), status: r.status ?? null,
    returns_pct: Object.fromEntries((block.periods || []).map((p) => [p, finite(r[p])])),
  }));
}

export async function macro(ctx, args) {
  const kind = args.kind;
  if (kind !== 'rates') await ctx.loadSlice(`macro/${kind}`);
  const result = { kind, url: ctx.link('rates'), release: null, curve: null, commodities: null, rates_context: null };
  if (kind === 'rates') {
    const [fixed, overview] = await Promise.all([ctx.get('fixed_income', 'Treasury curve'), ctx.get('overview', 'recent rates')]);
    result.curve = curve(fixed, ctx);
    result.rates_context = overview?.rates ? overview.rates.map((r) => ({ label: r.label, value: finite(r.value), date: r.date ?? null, change_1d_bp: finite(r.change_1d_bp), change_1m_bp: finite(r.change_1m_bp) })) : null;
    ctx.caveat('The curve is the Treasury\'s published par yields, which can lag the session by a day; see each curve\'s date.');
  } else if (kind === 'commodities') {
    const data = await ctx.get('macro', 'commodities');
    result.commodities = commodities(data, ctx);
    ctx.note(text(data?.note, 500));
    ctx.caveat('Prices are Yahoo front-month futures or ETF proxies, not spot prints.');
  } else {
    const data = await ctx.get('macro', kind.toUpperCase());
    result.release = inflationCard(data?.[kind], kind.toUpperCase(), ctx);
    ctx.caveat('Consensus is a retrospective calendar value where marked, not a frozen pre-release snapshot; histories are the current FRED vintage.');
  }
  return result;
}

export const macroTool = {
  name: 'macro',
  title: 'Macro',
  description: 'Macro cards by kind: cpi or ppi (latest release against consensus, components, persistence and momentum measures), rates (Treasury par curve now, a week and a month ago, start of year; changes and spreads in basis points), or commodities (front-month futures and ETF proxies with returns). Read-only.',
  inputSchema: T.obj({ kind: { type: 'string', enum: MACRO_KINDS, description: 'cpi, ppi, rates or commodities.' } }, ['kind']),
  outputSchema: outputSchema({
    kind: { enum: MACRO_KINDS }, url: T.str,
    release: T.maybe(T.obj({
      month: T.strNull, published_at: T.strNull,
      release_vs_consensus: T.arr(T.obj({ label: T.str, actual: T.num, consensus: T.num })),
      components: T.arr(T.obj({ label: T.str, mom_pct: T.num, yoy_pct: T.num })),
      persistence: T.arr(T.obj({ label: T.str, value: T.num })),
    }, ['release_vs_consensus', 'components'])),
    curve: T.maybe(T.obj({ tenors: T.arr(T.str), curves: T.arr(T.obj({ label: T.str, date: T.strNull, yields_pct: { type: 'object' } }, ['label'])), spreads_bp: T.arr(T.obj({ label: T.str, bps: T.num })) }, ['tenors', 'curves'])),
    commodities: T.maybe(T.arr(T.obj({ label: T.str, symbol: T.str, price: T.num }, ['label', 'symbol']))),
    rates_context: T.maybe(T.arr(T.obj({ label: T.str, value: T.num }, ['label']))),
  }, ['kind', 'release', 'curve', 'commodities']),
  run: macro,
};
