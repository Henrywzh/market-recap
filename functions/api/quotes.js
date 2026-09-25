// Intraday quotes for the MARKETS live strip: GET /api/quotes.
//
// The only server-side code on the site, and deliberately small. It fetches
// exactly the symbols in /live.json (written from config/dashboard.toml by
// site.build), so it cannot be used to proxy anything else, and it answers
// every reader from one fetch per `server_cache_seconds`.
//
// Sources were chosen by measurement (2026-09-24/25, from Cloudflare's edge):
// Yahoo's v8 chart answered every call in ~45 ms with prices a few seconds
// old; CNBC's quote service carried the Treasury yields ~15 s behind. Nasdaq
// (2-3 s per call) and Cboe (15-minute delay) were not used. A source that
// fails leaves its rows null with the reason: the page shows a dash, never a
// number from somewhere else.

const CLIENT = 'market-recap-live/0.1 (+https://market-recap-b5p.pages.dev)';
const TIMEOUT_MS = 4000;

// One copy per isolate. Cloudflare may run several, so this bounds the
// request rate per isolate rather than globally -- enough at this traffic.
let memo = { key: null, at: 0, body: null };

export function parseYahooChart(payload) {
  const meta = payload?.chart?.result?.[0]?.meta;
  if (!meta || typeof meta.regularMarketPrice !== 'number') {
    const reason = payload?.chart?.error?.description || 'no price in response';
    return { error: reason };
  }
  const price = meta.regularMarketPrice;
  const prev = typeof meta.chartPreviousClose === 'number' ? meta.chartPreviousClose
    : typeof meta.previousClose === 'number' ? meta.previousClose : null;
  const regular = meta.currentTradingPeriod?.regular;
  return {
    price,
    previous_close: prev,
    change: prev === null ? null : price - prev,
    change_pct: prev ? (price / prev - 1) * 100 : null,
    time: typeof meta.regularMarketTime === 'number' ? meta.regularMarketTime : null,
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
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(entry.symbol)}?interval=1d&range=1d`;
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

export async function buildBody(contract, nowMs = Date.now()) {
  const [equities, rates] = await Promise.all([
    Promise.all((contract.equities || []).map(yahooQuote)),
    cnbcRates(contract.rates || []),
  ]);
  const session = sessionState(equities, Math.floor(nowMs / 1000));
  equities.forEach((q) => { delete q.session; });
  return {
    fetched_at: new Date(nowMs).toISOString(),
    session,
    refresh_seconds: contract.refresh_seconds,
    closed_refresh_seconds: contract.closed_refresh_seconds,
    stale_after_seconds: contract.stale_after_seconds,
    quotes: [...equities, ...rates],
  };
}

export async function onRequestGet({ request, env }) {
  const contractResponse = await env.ASSETS.fetch(new URL('/live.json', request.url));
  if (!contractResponse.ok) {
    return Response.json({ error: 'live.json is missing from this deploy' }, { status: 503 });
  }
  const contract = await contractResponse.json();
  const ttlMs = (contract.server_cache_seconds || 15) * 1000;
  const key = JSON.stringify(contract);
  const now = Date.now();
  if (memo.key !== key || now - memo.at >= ttlMs) {
    // The promise is kept, not its result, so readers arriving while a fetch
    // is in flight wait for it instead of starting another. buildBody catches
    // per source and does not reject.
    memo = { key, at: now, body: buildBody(contract, now) };
  }
  return Response.json(await memo.body, {
    headers: { 'Cache-Control': `public, max-age=${Math.round(ttlMs / 1000)}` },
  });
}
