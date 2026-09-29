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

export async function buildBody(contract, nowMs = Date.now(), scope = 'default') {
  const trade = scope === 'trade';
  const [equities, rates] = await Promise.all([
    Promise.all((trade ? [...(contract.overnight || []), ...(contract.premarket_movers || [])]
      : (contract.equities || [])).map(yahooQuote)),
    cnbcRates(trade ? [] : contract.rates || []),
  ]);
  const session = sessionState(equities.filter((q) => q.kind === 'etf' || q.kind === 'index'), Math.floor(nowMs / 1000));
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
  const scope = new URL(request.url).searchParams.get('scope') === 'trade' ? 'trade' : 'default';
  const ttlMs = (contract.server_cache_seconds || 15) * 1000;
  const key = `${scope}:${JSON.stringify(contract)}`;
  const now = Date.now();
  const cached = memo.get(scope);
  if (!cached || cached.key !== key || now - cached.at >= ttlMs) {
    // The promise is kept, not its result, so readers arriving while a fetch
    // is in flight wait for it instead of starting another. buildBody catches
    // per source and does not reject.
    memo.set(scope, { key, at: now, body: buildBody(contract, now, scope) });
  }
  return Response.json(await memo.get(scope).body, {
    headers: { 'Cache-Control': `public, max-age=${Math.round(ttlMs / 1000)}` },
  });
}
