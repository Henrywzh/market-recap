// Intraday quotes for the live strip and the boards: GET /api/quotes.
//
// The only server-side code on the site, and deliberately small. It fetches
// exactly the symbols in /live.json (written from config/dashboard.toml and
// the heat-map artifact by site.build), so it cannot be used to proxy anything
// else, and it answers every reader from one fetch per cache window: the strip
// every `server_cache_seconds`, a board (the heat map, the index charts)
// every `board_cache_seconds`.
//
// Sources were chosen by measurement (2026-09-24/25, from Cloudflare's edge):
// Yahoo's v8 chart answered every call in ~45 ms with prices a few seconds
// old; CNBC's quote service carried the Treasury yields ~15 s behind. Nasdaq
// (2-3 s per call) and Cboe (15-minute delay) were not used. CNBC began
// refusing Cloudflare's servers on 2026-10-12 (HTTP 403), so the strip's yields
// are Cboe's yield indexes (^FVX, ^TNX, ^TYX) through Yahoo. A source that
// fails leaves its rows null with the reason: the page shows a dash, never a
// number from somewhere else.

const CLIENT = 'market-recap-live/0.1 (+https://market-recap-b5p.pages.dev)';
const TIMEOUT_MS = 4000;

// One copy per isolate. Cloudflare may run several, so this bounds the
// request rate per isolate rather than globally -- enough at this traffic.
const memo = new Map();

export function parseYahooChart(payload) {
  const result = payload?.chart?.result?.[0];
  const meta = result?.meta;
  if (!meta || typeof meta.regularMarketPrice !== 'number') {
    const reason = payload?.chart?.error?.description || 'no price in response';
    return { error: reason };
  }
  const price = meta.regularMarketPrice;
  const prev = typeof meta.chartPreviousClose === 'number' ? meta.chartPreviousClose
    : typeof meta.previousClose === 'number' ? meta.previousClose : null;
  const regular = meta.currentTradingPeriod?.regular;
  const timestamps = result?.timestamp || [];
  const closes = result?.indicators?.quote?.[0]?.close || [];
  const extended = (period) => {
    if (!period || !Number.isFinite(period.start) || !Number.isFinite(period.end)) return null;
    for (let i = timestamps.length - 1; i >= 0; i -= 1) {
      if (timestamps[i] >= period.start && timestamps[i] < period.end && Number.isFinite(closes[i])) {
        return { price: closes[i], time: timestamps[i] };
      }
    }
    return null;
  };
  const pre = extended(meta.currentTradingPeriod?.pre);
  const post = extended(meta.currentTradingPeriod?.post);
  return {
    price,
    previous_close: prev,
    change: prev === null ? null : price - prev,
    change_pct: prev ? (price / prev - 1) * 100 : null,
    time: typeof meta.regularMarketTime === 'number' ? meta.regularMarketTime : null,
    pre_price: pre?.price ?? null,
    pre_time: pre?.time ?? null,
    post_price: post?.price ?? null,
    post_time: post?.time ?? null,
    session: regular && typeof regular.start === 'number'
      ? { start: regular.start, end: regular.end }
      : null,
  };
}

const numberIn = (text) => {
  if (typeof text !== 'string' && typeof text !== 'number') return null;
  const value = parseFloat(String(text).replace(/[%,]/g, ''));
  return Number.isFinite(value) ? value : null;
};

// CNBC quotes a yield as "5.158%" and its change in percentage points
// ("-0.004"); the page shows yields with the change in basis points.
export function parseCnbcRates(payload) {
  let rows = payload?.FormattedQuoteResult?.FormattedQuote;
  if (rows && !Array.isArray(rows)) rows = [rows];
  const out = new Map();
  (rows || []).forEach((row) => {
    const yieldPct = numberIn(row.last);
    const changePts = numberIn(row.change);
    const stamp = row.last_time ? Date.parse(row.last_time.replace(/([+-]\d{2})(\d{2})$/, '$1:$2')) : NaN;
    out.set(row.symbol, yieldPct === null ? { error: 'no yield in response' } : {
      price: yieldPct,
      change_bp: changePts === null ? null : Math.round(changePts * 1000) / 10,
      time: Number.isFinite(stamp) ? Math.floor(stamp / 1000) : null,
    });
  });
  return out;
}

// Open if now falls inside the regular session any answering quote reports.
// Yahoo moves the period to the next session after the close, which also
// covers weekends and exchange holidays without a calendar here.
export function sessionState(quotes, nowSeconds) {
  const period = quotes.map((q) => q.session).find(Boolean) || null;
  if (!period) return { open: null, start: null, end: null };
  return { open: nowSeconds >= period.start && nowSeconds < period.end, start: period.start, end: period.end };
}

async function getJson(url) {
  const response = await fetch(url, {
    headers: { 'User-Agent': CLIENT, Accept: 'application/json' },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

const why = (error) => (error?.name === 'TimeoutError' ? `no answer in ${TIMEOUT_MS / 1000}s` : String(error?.message || error));

async function yahooQuote(entry) {
  const intraday = entry.kind === 'premarket';
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(entry.symbol)}`
    + (intraday ? '?interval=1m&range=1d&includePrePost=true' : '?interval=1d&range=1d');
  try {
    return { ...entry, source: 'Yahoo', ...parseYahooChart(await getJson(url)) };
  } catch (error) {
    return { ...entry, source: 'Yahoo', error: why(error) };
  }
}

async function cnbcRates(entries) {
  if (!entries.length) return [];
  const symbols = entries.map((e) => e.symbol).join('|');
  const url = `https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=${encodeURIComponent(symbols)}`
    + '&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1';
  try {
    const parsed = parseCnbcRates(await getJson(url));
    return entries.map((e) => ({ ...e, source: 'CNBC', ...(parsed.get(e.symbol) || { error: 'symbol missing from response' }) }));
  } catch (error) {
    return entries.map((e) => ({ ...e, source: 'CNBC', error: why(error) }));
  }
}

// A Cboe yield index through Yahoo (^TNX is the 10-year yield in percent) as
// a rate row: the yield with its change in basis points.
export function yahooRate(quote) {
  if (quote.error) return { symbol: quote.symbol, label: quote.label, kind: quote.kind, source: quote.source, error: quote.error };
  return { symbol: quote.symbol, label: quote.label, kind: quote.kind, source: quote.source, price: quote.price,
    change_bp: Number.isFinite(quote.change) ? Math.round(quote.change * 1000) / 10 : null, time: quote.time };
}

// The strip's yields, each from the source its entry names, in the contract's order.
async function rateRows(entries) {
  const yahoo = entries.filter((e) => e.source === 'yahoo');
  const cnbc = entries.filter((e) => e.source !== 'yahoo');
  const [fromYahoo, fromCnbc] = await Promise.all([yahoo.length ? yahooSpark(yahoo) : [], cnbcRates(cnbc)]);
  const bySymbol = new Map([...fromYahoo.map(yahooRate), ...fromCnbc].map((q) => [q.symbol, q]));
  return entries.map((e) => bySymbol.get(e.symbol));
}

// Yahoo's spark answers up to SPARK_BATCH symbols in one call, with each
// one's day of 5-minute closes, its previous close and its session. One call
// per batch keeps a 500-name heat map inside the 50 sub-requests a Pages
// Function may make.
export const SPARK_BATCH = 20;

export function parseSpark(payload) {
  const out = new Map();
  if (!payload || typeof payload !== 'object' || payload.spark) return out;   // {spark: {error}} is a refusal
  for (const [symbol, row] of Object.entries(payload)) {
    const times = Array.isArray(row?.timestamp) ? row.timestamp : [];
    const closes = Array.isArray(row?.close) ? row.close : [];
    let at = -1;
    for (let i = Math.min(times.length, closes.length) - 1; i >= 0; i -= 1) {
      if (Number.isFinite(closes[i])) { at = i; break; }
    }
    const prev = Number.isFinite(row?.previousClose) ? row.previousClose
      : Number.isFinite(row?.chartPreviousClose) ? row.chartPreviousClose : null;
    if (at < 0) { out.set(symbol, { error: 'no price in response' }); continue; }
    const price = closes[at];
    out.set(symbol, {
      price,
      previous_close: prev,
      change: prev === null ? null : price - prev,
      change_pct: prev ? (price / prev - 1) * 100 : null,
      time: times[at],
      // Yahoo's latest price including pre-market and after-hours trades.
      // The spark call refuses includePrePost, but carries this field; the
      // page reads it only outside the regular session.
      extended_price: Number.isFinite(row?.fulldayPrice) ? row.fulldayPrice : null,
      session: Number.isFinite(row?.start) && Number.isFinite(row?.end) ? { start: row.start, end: row.end } : null,
      series: { t: times.slice(0, at + 1), c: closes.slice(0, at + 1).map((v) => (Number.isFinite(v) ? v : null)) },
    });
  }
  return out;
}

export function batches(list, size = SPARK_BATCH) {
  const out = [];
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size));
  return out;
}

async function yahooSpark(entries, { series = false } = {}) {
  const parsed = new Map();
  const failed = new Map();
  await Promise.all(batches(entries).map(async (batch) => {
    const symbols = batch.map((e) => e.symbol).join(',');
    const url = `https://query1.finance.yahoo.com/v8/finance/spark?symbols=${encodeURIComponent(symbols)}&range=1d&interval=5m`;
    try {
      parseSpark(await getJson(url)).forEach((value, key) => parsed.set(key, value));
    } catch (error) {
      batch.forEach((e) => failed.set(e.symbol, why(error)));
    }
  }));
  return entries.map((e) => {
    const quote = parsed.get(e.symbol) || { error: failed.get(e.symbol) || 'symbol missing from response' };
    if (!series) delete quote.series;
    return { ...e, source: 'Yahoo', ...quote };
  });
}

// --- Nasdaq, when Yahoo goes quiet ------------------------------------------
// 2026-11-05: Yahoo's prices stopped at 12:10 New York for every symbol while
// the market traded on, and the page fell back to the close. A quote older than
// `stale_after_seconds` in an open session (or missing) is asked of Nasdaq's
// quote endpoint instead, for the small boards only: one call per symbol at
// 1-3 s each, under a cap, never the 500-name heat map. Nasdaq quotes NDX but
// not the S&P 500, Russell 2000 or Dow, so those move by their ETF's change
// on Yahoo's previous close and say so (`proxy`). VIX, futures and the dollar
// have no Nasdaq quote and stay as they are, marked stale.
const NASDAQ_CLIENT = 'market-recap-live/0.1';   // Nasdaq's edge drops a User-Agent carrying a URL
const NASDAQ_TIMEOUT_MS = 6000;
export const NASDAQ_CAP = 24;
const NASDAQ_INDEX = { '^GSPC': ['SPY', 'etf'], '^NDX': ['NDX', 'index'], '^RUT': ['IWM', 'etf'], '^DJI': ['DIA', 'etf'] };
const FALLBACK_BOARDS = new Set(['today', 'indices', 'sector_etfs']);

// The Nasdaq symbol and asset classes to try for one of ours, or null for none.
export function nasdaqTarget(symbol) {
  if (NASDAQ_INDEX[symbol]) {
    const [target, asset] = NASDAQ_INDEX[symbol];
    return { symbol: target, assets: [asset], proxy: target !== symbol.replace('^', '') ? target : null };
  }
  if (!/^[A-Z][A-Z.-]{0,5}$/.test(symbol)) return null;   // ^VIX, CL=F, DX-Y.NYB
  return { symbol: symbol.replace('-', '.'), assets: ['etf', 'stocks'], proxy: null };
}

const MONTHS = { Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5, Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11 };

// "Nov 5, 2026 1:17 PM ET" as epoch seconds, New York's offset on that day.
export function nasdaqTime(text) {
  const m = /^(\w{3}) (\d{1,2}), (\d{4}) (\d{1,2}):(\d{2}) (AM|PM)/.exec(String(text || ''));
  if (!m || MONTHS[m[1]] === undefined) return null;
  const hour = (Number(m[4]) % 12) + (m[6] === 'PM' ? 12 : 0);
  const wall = Date.UTC(Number(m[3]), MONTHS[m[1]], Number(m[2]), hour, Number(m[5]));
  const name = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', timeZoneName: 'shortOffset' })
    .formatToParts(new Date(wall + 5 * 3600e3)).find((p) => p.type === 'timeZoneName')?.value || 'GMT-5';
  const [, sign, hours, minutes] = /GMT([+-])(\d{1,2})(?::(\d{2}))?/.exec(name) || [null, '-', '5', '0'];
  const offset = (sign === '-' ? -1 : 1) * (Number(hours) * 60 + Number(minutes || 0));
  return Math.floor((wall - offset * 60e3) / 1000);
}

export function parseNasdaqQuote(payload) {
  const primary = payload?.data?.primaryData;
  const price = numberIn(String(primary?.lastSalePrice ?? '').replace('$', ''));
  if (price === null) return { error: payload?.status?.bCodeMessage?.[0]?.errorMessage || 'no price in response' };
  const change = numberIn(primary.netChange);
  const prev = change === null ? null : price - change;
  return { price, previous_close: prev, change, change_pct: numberIn(primary.percentageChange) ?? (prev ? (price / prev - 1) * 100 : null),
    time: nasdaqTime(primary.lastTradeTimestamp) };
}

async function nasdaqQuote(target) {
  let last = 'no answer';
  for (const asset of target.assets) {
    try {
      const response = await fetch(`https://api.nasdaq.com/api/quote/${encodeURIComponent(target.symbol)}/info?assetclass=${asset}`, {
        headers: { 'User-Agent': NASDAQ_CLIENT, Accept: 'application/json' }, signal: AbortSignal.timeout(NASDAQ_TIMEOUT_MS),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const quote = parseNasdaqQuote(await response.json());
      if (!quote.error) return quote;
      last = quote.error;
    } catch (error) {
      last = error?.name === 'TimeoutError' ? `no answer in ${NASDAQ_TIMEOUT_MS / 1000}s` : String(error?.message || error);
    }
  }
  return { error: last };
}

// A stale Yahoo row with Nasdaq's figures, or null to keep the Yahoo row.
export function nasdaqRow(row, quote, target) {
  if (quote.error || !Number.isFinite(quote.time) || (Number.isFinite(row.time) && quote.time <= row.time)) return null;
  const out = { ...row, source: target.proxy ? `Nasdaq (via ${target.proxy})` : 'Nasdaq', stale_source: { source: row.source, time: row.time ?? null } };
  delete out.error;
  if (target.proxy) {
    // The index moved by its ETF's change, from the index's own previous close.
    const prev = Number.isFinite(row.previous_close) ? row.previous_close : null;
    out.proxy = target.proxy;
    out.change_pct = quote.change_pct;
    out.price = prev !== null && Number.isFinite(quote.change_pct) ? prev * (1 + quote.change_pct / 100) : null;
    out.change = out.price === null ? null : out.price - prev;
  } else {
    Object.assign(out, { price: quote.price, previous_close: quote.previous_close, change: quote.change, change_pct: quote.change_pct });
  }
  out.time = quote.time;
  out.extended_price = out.price;
  return out;
}

// Replace the rows Yahoo left stale with Nasdaq's, while the session is open.
export async function fillStale(quotes, session, staleAfter, nowMs, { cap = NASDAQ_CAP, ask = nasdaqQuote } = {}) {
  if (session?.open !== true) return quotes;
  const now = Math.floor(nowMs / 1000);
  const stale = quotes.map((q, i) => [q, i]).filter(([q]) => (q.error || !Number.isFinite(q.time) || now - q.time > staleAfter)
    && q.kind !== 'rate' && nasdaqTarget(q.symbol)).slice(0, cap);
  const out = quotes.slice();
  await Promise.all(stale.map(async ([q, i]) => {
    const target = nasdaqTarget(q.symbol);
    out[i] = nasdaqRow(q, await ask(target), target) || q;
  }));
  return out;
}

function sessionOf(quotes, nowMs) {
  const session = sessionState(quotes, Math.floor(nowMs / 1000));
  quotes.forEach((q) => { delete q.session; });
  return session;
}

export async function buildBody(contract, nowMs = Date.now(), scope = 'default') {
  if (scope === 'trade') {
    const equities = await Promise.all([...(contract.overnight || []), ...(contract.premarket_movers || [])].map(yahooQuote));
    return { fetched_at: new Date(nowMs).toISOString(), session: sessionOf(equities, nowMs),
      refresh_seconds: contract.refresh_seconds, closed_refresh_seconds: contract.closed_refresh_seconds,
      stale_after_seconds: contract.stale_after_seconds, quotes: equities };
  }
  if (scope.startsWith('board:')) {
    const board = (contract.boards || {})[scope.slice(6)];
    if (!board) return { error: `no board ${scope.slice(6)}` };
    const entries = board.symbols.map((symbol) => ({ symbol, label: board.labels?.[symbol] ?? symbol, kind: 'board' }));
    // The yield board is CNBC's: one call carries the whole curve.
    let quotes = board.source === 'cnbc' ? await cnbcRates(entries) : await yahooSpark(entries, { series: Boolean(board.series) });
    // A board's session is the US cash session: its index or its stocks.
    const session = sessionOf(quotes, nowMs);
    if (FALLBACK_BOARDS.has(scope.slice(6))) quotes = await fillStale(quotes, session, contract.stale_after_seconds ?? 1200, nowMs);
    return { fetched_at: new Date(nowMs).toISOString(), session,
      refresh_seconds: board.refresh_seconds, closed_refresh_seconds: board.closed_refresh_seconds,
      extended_refresh_seconds: board.extended_refresh_seconds,
      stale_after_seconds: contract.stale_after_seconds, quotes };
  }
  const [fetched, rates] = await Promise.all([yahooSpark(contract.strip || []), rateRows(contract.rates || [])]);
  const session = sessionOf(fetched.filter((q) => q.kind === 'index'), nowMs);
  fetched.forEach((q) => { delete q.session; });
  const equities = await fillStale(fetched, session, contract.stale_after_seconds ?? 1200, nowMs);
  return {
    fetched_at: new Date(nowMs).toISOString(),
    session,
    refresh_seconds: contract.refresh_seconds,
    closed_refresh_seconds: contract.closed_refresh_seconds,
    stale_after_seconds: contract.stale_after_seconds,
    quotes: [...equities, ...rates],
  };
}

// Which fetch a request names: the strip (default), a board, or the trade
// desk's overnight board. Anything else is the strip.
export function scopeOf(params, contract) {
  if (params.get('scope') === 'trade') return 'trade';
  const board = params.get('board');
  if (board && (contract.boards || {})[board]) return `board:${board}`;
  return 'default';
}

export async function onRequestGet({ request, env }) {
  const contractResponse = await env.ASSETS.fetch(new URL('/live.json', request.url));
  if (!contractResponse.ok) {
    return Response.json({ error: 'live.json is missing from this deploy' }, { status: 503 });
  }
  const contract = await contractResponse.json();
  const params = new URL(request.url).searchParams;
  const scope = scopeOf(params, contract);
  const seconds = scope.startsWith('board:') ? contract.board_cache_seconds || 60 : contract.server_cache_seconds || 15;
  const ttlMs = seconds * 1000;
  // A reader's REFRESH asks again, but never sooner than manual_min_seconds
  // after the last fetch: many clicks are still one fetch.
  const freshMs = (contract.manual_min_seconds || 30) * 1000;
  const key = `${scope}:${JSON.stringify(contract)}`;
  const now = Date.now();
  const cached = memo.get(scope);
  const age = cached ? now - cached.at : Infinity;
  const wanted = params.get('fresh') === '1' ? Math.min(ttlMs, freshMs) : ttlMs;
  if (!cached || cached.key !== key || age >= wanted) {
    // The promise is kept, not its result, so readers arriving while a fetch
    // is in flight wait for it instead of starting another. buildBody catches
    // per source and does not reject.
    memo.set(scope, { key, at: now, body: buildBody(contract, now, scope) });
  }
  return Response.json(await memo.get(scope).body, {
    headers: { 'Cache-Control': `public, max-age=${Math.round(Math.min(ttlMs, freshMs) / 1000)}` },
  });
}
