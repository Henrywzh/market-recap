// unusual_moves: stocks whose own part of the last session's move (after the
// market and its sector) was beyond the build's threshold, plus the
// technology sell-off flag when it is active.

import { unusualRows } from '../../web/js/moves-card.js';
import { outputSchema } from '../context.mjs';
import { T } from '../schema.mjs';
import { capList, finite, text } from '../util.mjs';

const DEFAULT_LIMIT = 20;

function compact(r) {
  return {
    symbol: r.ticker, name: r.name ?? null, sector: r.sector ?? null, direction: r.z_own < 0 ? 'down' : 'up',
    return_pct: finite(r.ret_pct), own_pct: finite(r.own_pct), own_z: finite(r.z_own), z: finite(r.z),
    market_pct: finite(r.market_pct), sector_pct: finite(r.sector_pct),
    gap_pct: finite(r.gap_pct), session_pct: finite(r.intraday_pct), volume_ratio: finite(r.volume_ratio),
    reported: r.reported ?? null, tags: r.tags ?? null,
    range_factor: finite(r.range_factor), range_reason: r.range_reason ?? null,
  };
}

function selloff(flag, ctx) {
  if (!flag) {
    ctx.missing('technology sell-off flag', 'moves.json carries no sector_selloff block');
    return null;
  }
  if (!flag.active) return { active: false, fund: flag.fund ?? null, z: finite(flag.z), market_z: finite(flag.spy_z) };
  const h = flag.history || {};
  return {
    active: true, fund: flag.fund ?? null, z: finite(flag.z), market_z: finite(flag.spy_z), losers: flag.losers || [],
    history: { days: h.days ?? null, since: h.since ?? null, until: h.until ?? null, five_day_bp: h.five_day ?? null, twenty_day_bp: h.twenty_day ?? null },
  };
}

export async function unusualMoves(ctx, args = {}) {
  await ctx.loadSlice('unusual');
  const data = await ctx.get('moves', 'MOVES');
  const limit = Math.min(args.limit || DEFAULT_LIMIT, 100);
  const direction = args.direction ? args.direction.toUpperCase() : 'ALL';
  const rows = data ? unusualRows(data, direction) : [];
  const page = capList(rows, limit);
  ctx.note(text(data?.note, 700));
  ctx.caveat('Unusual means large against the stock\'s own recent volatility after removing market and sector, not that it is news or a signal. Ranges are spreads of past outcomes, not forecasts.');
  return {
    session: data?.as_of ?? null,
    threshold_sigma: data?.settings?.threshold_sigma ?? null,
    direction: direction.toLowerCase(),
    total_unusual: rows.length,
    moves: page.items.map(compact),
    more_moves: page.more,
    how_to_get_more: page.more ? 'Raise `limit` (up to 100) or set `direction` to up or down.' : null,
    technology_selloff: selloff(data?.sector_selloff, ctx),
  };
}

export const unusualMovesTool = {
  name: 'unusual_moves',
  title: 'Unusual moves',
  description: 'S&P 500 members whose own part of the last session\'s move (after market and sector) was at least the build\'s sigma threshold, largest first, with the market/sector/own split, gap vs session, volume and the calibration of their 5-session range; also whether the technology-only sell-off flag is active. Read-only and descriptive.',
  inputSchema: T.obj({
    direction: { type: 'string', enum: ['up', 'down'], description: 'Only rises or only falls. Default both.' },
    limit: { type: 'integer', minimum: 1, maximum: 100, description: `Names returned, default ${DEFAULT_LIMIT}.` },
  }),
  outputSchema: outputSchema({
    session: T.strNull, threshold_sigma: T.num, direction: T.str, total_unusual: { type: 'integer' },
    moves: T.arr(T.obj({ symbol: T.str, direction: { enum: ['up', 'down'] }, own_pct: T.num, own_z: T.num, return_pct: T.num }, ['symbol', 'direction'])),
    more_moves: { type: 'integer' }, how_to_get_more: T.strNull,
    technology_selloff: T.maybe(T.obj({ active: T.bool }, ['active'])),
  }, ['total_unusual', 'moves', 'more_moves', 'technology_selloff']),
  run: unusualMoves,
};
