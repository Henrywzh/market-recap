// TODAY's live unusual-move check, kept apart from the DOM so it can be tested
// under node. It turns a live quote into the same two numbers the build gives
// each name: its return in units of its own volatility (z), and its own part
// after the market and its sector are taken out (z_own). The formulas follow
// the build (compute/moves.py): own = ret - beta_market * market
// - beta_sector * (sector - market); a name with no sector fund has no sector
// part, and a name whose sector fund did not quote cannot have its own part
// worked out, so it gets no z_own rather than a guess.

import { isStale } from './live-model.js';

const finite = (value) => typeof value === 'number' && Number.isFinite(value);
const sizeOf = (value) => (finite(value) ? Math.abs(value) : 0);

// The sector part in percent, 0 when the name has no sector fund, or null when
// it has one but the fund's price is missing.
function sectorPart(row, sectorQuote, market) {
  if (!finite(row.beta_sector)) return 0;
  const sector = sectorQuote?.change_pct;
  if (!finite(sector) || !finite(market)) return null;
  return row.beta_sector * (sector - market);
}

// The live z and own part of one name. Each figure is null when its inputs are
// missing, never zero: "no price" and "no move" are different statements.
export function liveZ(row, quote, spyQuote, sectorQuote) {
  const ret = quote?.change_pct;
  const market = spyQuote?.change_pct;
  const z = finite(ret) && finite(row.sigma_pct) && row.sigma_pct > 0 ? ret / row.sigma_pct : null;
  const sector = finite(ret) && finite(market) && finite(row.beta_market) ? sectorPart(row, sectorQuote, market) : null;
  const own = sector === null ? null : ret - row.beta_market * market - sector;
  const zOwn = own !== null && finite(row.sigma_own_pct) && row.sigma_own_pct > 0 ? own / row.sigma_own_pct : null;
  return { ret_pct: finite(ret) ? ret : null, z, own_pct: own, z_own: zOwn };
}

// Beyond the threshold on either measure, the same rule the build uses.
export function isUnusualZ(found, threshold) {
  return (finite(found.z) && Math.abs(found.z) >= threshold)
    || (finite(found.z_own) && Math.abs(found.z_own) >= threshold);
}

// Every quote by its symbol, for the heat-map board and the sector board together.
export function quotesBySymbol(bodies) {
  const map = new Map();
  bodies.forEach((body) => (body?.quotes || []).forEach((quote) => {
    if (quote?.symbol && !quote.error) map.set(quote.symbol, quote);
  }));
  return map;
}

// The names beyond the threshold right now, strongest first, capped at the
// build's max_items. Rows with no quote are left out, not counted as calm.
export function liveUnusual(rows, quotes, live) {
  const threshold = live.threshold_sigma ?? 2;
  const spy = quotes.get(live.market ?? 'SPY');
  const found = [];
  (rows || []).forEach((row) => {
    const quote = quotes.get(row.ticker);
    if (!quote || !finite(quote.change_pct)) return;
    const fund = live.sector_funds?.[row.sector] ?? null;
    const measured = liveZ(row, quote, spy, fund ? quotes.get(fund) : null);
    if (!isUnusualZ(measured, threshold)) return;
    found.push({
      ticker: row.ticker,
      name: row.name ?? row.ticker,
      sector: row.sector ?? null,
      time: quote.time ?? null,
      ...measured,
      strength: Math.max(sizeOf(measured.z), sizeOf(measured.z_own)),
    });
  });
  found.sort((a, b) => b.strength - a.strength || a.ticker.localeCompare(b.ticker));
  return found.slice(0, live.max_items ?? 12);
}

// The live list is shown only while the session is open and the market's quote
// is fresh; a closed or stale session shows the build's close instead.
export function liveIsCurrent(heat, market, nowMs) {
  if (heat?.session?.open !== true) return false;
  if (!market || !finite(market.change_pct)) return false;
  return !isStale(market, heat, nowMs);
}

// What the MOVES block shows: the live list with the quote time, or null when
// the build's close should stand (no live config, no moves, no current quotes).
export function liveView({ moves, heat, etfs }, live, nowMs = Date.now()) {
  if (!live || !moves || !heat || !etfs) return null;
  const quotes = quotesBySymbol([heat, etfs]);
  const market = quotes.get(live.market ?? 'SPY');
  if (!liveIsCurrent(heat, market, nowMs)) return null;
  return { items: liveUnusual(moves, quotes, live), time: market.time ?? null };
}
