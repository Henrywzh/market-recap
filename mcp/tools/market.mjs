// market_snapshot: one call for "what is the market doing and how risky does
// it look". It reads several panels' artifacts and keeps to numbers they hold.

import { statePresentation } from '../../web/js/market-state-model.js';
import { outputSchema } from '../context.mjs';
import { T } from '../schema.mjs';
import { finite, latestPoint, pick, text } from '../util.mjs';

const RETURNS = ['1D', '1W', '1M', 'YTD'];

function indices(overview, ctx) {
  const rows = ctx.need(overview?.stocks, 'indices', 'overview.json has no index rows');
  if (!rows) return null;
  return rows.map((r) => ({
    key: r.key, label: r.label, last: finite(r.last), date: r.date ?? null,
    returns_pct: Object.fromEntries(RETURNS.map((p) => [p, finite(r[p])])),
    from_high_pct: finite(r.from_high_pct), high_date: r.high_date ?? null,
  }));
}

function breadth(overview, ctx) {
  const rows = ctx.need(overview?.breadth, 'breadth', 'overview.json has no breadth rows');
  if (!rows) return null;
  return rows.map((b) => ({
    key: b.key, label: b.label, members: b.members ?? null,
    advancers_decliners: Object.fromEntries(['1D', '1W', '1M'].map((p) => [p, b[p] ? pick(b[p], ['up', 'down']) : null])),
    above_50d_pct: finite(b.above_50d), above_200d_pct: finite(b.above_200d),
    new_highs: b.new_highs ?? null, new_lows: b.new_lows ?? null,
  }));
}

// The same ACTIVE / CAUTION rule the page uses, imported rather than copied,
// so the two cannot disagree about which conditions hold.
function marketState(state, ctx) {
  if (!state?.states) {
    ctx.missing('market_state', 'market_state.json is not published in this build');
    return null;
  }
  const holding = state.states.filter((s) => s.active_now);
  ctx.note('Conditions: ACTIVE means the rule holds today; CAUTION means it holds and the build found a clear adverse difference in what followed such days (a 95% range excluding zero). It describes history, not a forecast.');
  return {
    as_of: state.as_of ?? null,
    conditions: holding.map((s) => {
      const view = statePresentation(s);
      return { key: s.key, label: s.label, level: view.label, rule: s.rule, reason: view.reason, days_now: s.days_now ?? null, history_days: s.days ?? null, episodes: s.episodes ?? null };
    }),
    not_active: state.states.filter((s) => !s.active_now).map((s) => s.label),
    readings: (state.readings || []).map((r) => ({ key: r.key, label: r.label, value: finite(r.value), unit: r.unit ?? null })),
  };
}

function riskTile(section, tile) {
  return {
    key: tile.key, label: tile.label, section: section.label, horizon: section.horizon ?? null,
    value: finite(tile.value), unit: tile.unit ?? null, date: tile.date ?? null,
    pct_1y: finite(tile.pct_1y), threshold: finite(tile.threshold), risk_when: tile.risk_when ?? null,
    breach: tile.breach === true, core: tile.core === true, error: tile.error ?? null,
  };
}

function riskTiles(risk, ctx) {
  if (!risk?.sections) {
    ctx.missing('risk tiles', 'risk.json is not published in this build');
    return null;
  }
  const tiles = risk.sections.flatMap((s) => (s.tiles || []).map((t) => riskTile(s, t)));
  const sentiment = risk.sentiment ? { score: finite(risk.sentiment.score), rating: risk.sentiment.rating ?? null, date: risk.sentiment.date ?? null } : null;
  return {
    as_of: risk.as_of ?? null,
    core_tiles: tiles.filter((t) => t.core),
    breaches: tiles.filter((t) => t.breach).map((t) => pick(t, ['key', 'label', 'section', 'value', 'unit', 'threshold'])),
    other_tile_count: tiles.filter((t) => !t.core).length,
    fear_greed: sentiment,
  };
}

function putCall(positioning, ctx) {
  const block = positioning?.index_put_call;
  if (!block?.series) {
    ctx.missing('index put/call', 'positioning.json has no index put/call block');
    return null;
  }
  ctx.note(text(block.method, 500));
  return {
    as_of: block.as_of ?? null,
    series: block.series.map((s) => ({
      key: s.key, label: s.label, scope: s.scope ?? null, status: s.status ?? null,
      daily: latestPoint(s.dates, s.windows?.['1D']?.values),
      avg_1w: latestPoint(s.dates, s.windows?.['1W']?.values),
      avg_1m: latestPoint(s.dates, s.windows?.['1M']?.values),
    })),
  };
}

function blackout(positioning, ctx) {
  const b = positioning?.blackout;
  if (!b) {
    ctx.missing('buyback blackout', 'positioning.json has no blackout block');
    return null;
  }
  const windows = b.momentum?.windows || [];
  const week = windows.find((w) => w.key === '7D') || null;
  if (!week) ctx.missing('buyback blackout next-7D change', 'positioning.json carries no 7D momentum window');
  ctx.caveat('Buyback blackout is an estimate from report dates and a fixed window, not observed buyback flow, and not a sell signal.');
  return {
    as_of: b.as_of ?? null, level_pct: finite(b.now_pct), peak_pct: finite(b.peak_pct), peak_date: b.peak_date ?? null,
    next_7d_schedule_change_pp: finite(week?.ahead_delta_pp),
    members: b.members ?? null, scheduled_reports: b.scheduled ?? null, projected_reports: b.projected ?? null,
  };
}

function rotation(sectorsFile, ctx) {
  const rows = ctx.need(sectorsFile?.sectors, 'sector rotation', 'sectors.json has no sector rows');
  if (!rows) return null;
  const sectors = rows.map((s) => ({
    key: s.key, label: s.label, weight_pct: finite(s.weight), quadrant: s.quadrant ?? null,
    returns_pct: { '1D': finite(s.returns?.['1D']), '1M': finite(s.returns?.['1M']), '3M': finite(s.returns?.['3M']) },
    vs_index_pp: { '1M': finite(s.vs_index?.['1M']), '3M': finite(s.vs_index?.['3M']) },
    above_200d_pct: finite(s.above_200d),
  }));
  const ranked = sectors.filter((s) => s.vs_index_pp['1M'] !== null).sort((a, b) => b.vs_index_pp['1M'] - a.vs_index_pp['1M']);
  return {
    as_of: sectorsFile.as_of ?? null, benchmark: sectorsFile.benchmark?.label ?? null,
    leaders_1m: ranked.slice(0, 3).map((s) => s.label), laggards_1m: ranked.slice(-3).reverse().map((s) => s.label),
    by_quadrant: sectors.reduce((acc, s) => { (acc[s.quadrant || 'unknown'] ||= []).push(s.label); return acc; }, {}),
    sectors,
  };
}

export async function marketSnapshot(ctx) {
  await ctx.loadSlice('snapshot');
  const overview = await ctx.get('overview', 'indices and breadth');
  const state = await ctx.get('market_state', 'market-state conditions');
  const risk = await ctx.get('risk', 'risk tiles');
  const positioning = await ctx.get('positioning', 'index put/call and buyback blackout');
  const sectorsFile = await ctx.get('sectors', 'sector rotation');
  ctx.note('Each section carries its own as_of; the panels refresh on different schedules.');
  ctx.caveat('Descriptive market data, not advice or a trading signal.');
  return {
    indices: indices(overview, ctx),
    equal_weight_minus_cap_pp: overview?.equal_vs_cap?.gap_pp ?? null,
    breadth: breadth(overview, ctx),
    market_state: marketState(state, ctx),
    risk: riskTiles(risk, ctx),
    index_put_call: putCall(positioning, ctx),
    buyback_blackout: blackout(positioning, ctx),
    sector_rotation: rotation(sectorsFile, ctx),
  };
}

const returnsSchema = { type: 'object' };

export const marketSnapshotTool = {
  name: 'market_snapshot',
  title: 'Market snapshot',
  description: 'Where the US market stands after the latest session: index levels and returns, breadth, which market-state conditions hold (ACTIVE or CAUTION, with the rule), the core risk tiles and any threshold breaches, index put/call, the estimated buyback-blackout level and its change over the next 7 days, and sector rotation. Read-only; every section names its own date.',
  inputSchema: T.obj(),
  outputSchema: outputSchema({
    indices: T.maybe(T.arr(T.obj({ key: T.str, label: T.str, last: T.num, date: T.strNull, returns_pct: returnsSchema, from_high_pct: T.num }, ['key', 'label']))),
    equal_weight_minus_cap_pp: T.maybe({ type: 'object' }),
    breadth: T.maybe(T.arr(T.obj({ key: T.str, members: T.int, above_50d_pct: T.num, above_200d_pct: T.num }, ['key']))),
    market_state: T.maybe(T.obj({
      conditions: T.arr(T.obj({ key: T.str, label: T.str, level: { enum: ['ACTIVE', 'CAUTION'] }, rule: T.str }, ['key', 'label', 'level', 'rule'])),
      not_active: T.arr(T.str),
      readings: T.arr(T.obj({ key: T.str, label: T.str, value: T.num }, ['key'])),
    }, ['conditions', 'not_active'])),
    risk: T.maybe(T.obj({
      core_tiles: T.arr(T.obj({ key: T.str, label: T.str, value: T.num, breach: T.bool }, ['key', 'label', 'breach'])),
      breaches: T.arr(T.obj({ key: T.str, label: T.str }, ['key', 'label'])),
      fear_greed: T.maybe(T.obj({ score: T.num, rating: T.strNull })),
    }, ['core_tiles', 'breaches'])),
    index_put_call: T.maybe(T.obj({ series: T.arr(T.obj({ key: T.str, label: T.str }, ['key', 'label'])) }, ['series'])),
    buyback_blackout: T.maybe(T.obj({ level_pct: T.num, peak_pct: T.num, next_7d_schedule_change_pp: T.num }, ['level_pct'])),
    sector_rotation: T.maybe(T.obj({
      leaders_1m: T.arr(T.str), laggards_1m: T.arr(T.str),
      sectors: T.arr(T.obj({ key: T.str, label: T.str, quadrant: T.strNull }, ['key', 'label'])),
    }, ['sectors'])),
  }, ['indices', 'breadth', 'market_state', 'risk', 'index_put_call', 'buyback_blackout', 'sector_rotation']),
  run: marketSnapshot,
};
