// The live strip: what the quote function makes of each publisher's answer,
// and when the page asks again.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseYahooChart, parseCnbcRates, sessionState, buildBody, parseSpark, batches, scopeOf, SPARK_BATCH } from '../../functions/api/quotes.js';
import * as L from '../../web/js/live-model.js';

const yahoo = (meta) => ({ chart: { result: [{ meta }], error: null } });

test('a Yahoo quote is priced against the previous close and carries its session', () => {
  const q = parseYahooChart(yahoo({
    regularMarketPrice: 110,
    chartPreviousClose: 100,
    regularMarketTime: 1000,
    currentTradingPeriod: { regular: { start: 500, end: 2000 } },
  }));
  assert.equal(q.price, 110);
  assert.equal(q.change, 10);
  assert.ok(Math.abs(q.change_pct - 10) < 1e-9);
  assert.equal(q.time, 1000);
  assert.deepEqual(q.session, { start: 500, end: 2000 });
});

test('no previous close leaves the change null, never zero', () => {
  const q = parseYahooChart(yahoo({ regularMarketPrice: 110 }));
  assert.equal(q.change, null);
  assert.equal(q.change_pct, null);
});

test('extended-hours close comes from chart timestamps inside the named session', () => {
  const payload = yahoo({ regularMarketPrice: 100, regularMarketTime: 50,
    currentTradingPeriod: { pre: { start: 100, end: 200 }, regular: { start: 200, end: 300 },
      post: { start: 300, end: 400 } } });
  payload.chart.result[0].timestamp = [99, 120, 180, 250, 310];
  payload.chart.result[0].indicators = { quote: [{ close: [101, null, 102, 103, 104] }] };
  const quote = parseYahooChart(payload);
  assert.equal(quote.pre_price, 102);
  assert.equal(quote.pre_time, 180);
  assert.equal(quote.post_price, 104);
  assert.equal(quote.post_time, 310);
});

test('a Yahoo error or a missing price is an error, not a number', () => {
  assert.equal(parseYahooChart({ chart: { result: null, error: { description: 'No data found' } } }).error, 'No data found');
  assert.ok(parseYahooChart(yahoo({})).error);
  assert.ok(parseYahooChart(null).error);
});

test('CNBC yields parse to percent with the change in basis points and a UTC time', () => {
  const rates = parseCnbcRates({ FormattedQuoteResult: { FormattedQuote: [
    { symbol: 'US10Y', last: '5.158%', change: '-0.004', last_time: '2026-09-25T15:52:03.000-0400' },
    { symbol: 'US2Y', last: '', change: 'UNCH' },
  ] } });
  const ten = rates.get('US10Y');
  assert.equal(ten.price, 5.158);
  assert.equal(ten.change_bp, -0.4);
  assert.equal(ten.time, Date.parse('2026-09-25T19:52:03Z') / 1000);
  assert.ok(rates.get('US2Y').error);
});

test('a single CNBC quote (not wrapped in a list) still parses', () => {
  const rates = parseCnbcRates({ FormattedQuoteResult: { FormattedQuote: { symbol: 'US30Y', last: '5.4%', change: '0.012' } } });
  assert.equal(rates.get('US30Y').change_bp, 1.2);
});

test('the session is open only inside the regular period, and unknown without one', () => {
  const quotes = [{ error: 'x' }, { session: { start: 100, end: 200 } }];
  assert.equal(sessionState(quotes, 150).open, true);
  assert.equal(sessionState(quotes, 200).open, false);
  assert.equal(sessionState(quotes, 99).open, false);
  assert.equal(sessionState([{ error: 'x' }], 150).open, null);
});

const spark = (rows) => Object.fromEntries(Object.entries(rows).map(([symbol, r]) => [symbol, {
  symbol, timestamp: r.t, close: r.c, previousClose: r.prev, chartPreviousClose: r.prev, start: r.start ?? 0, end: r.end ?? 100,
}]));

test('a spark answer prices each symbol at its last close, against the previous close', () => {
  const out = parseSpark(spark({ NVDA: { t: [10, 20, 30], c: [100, 101, null], prev: 98 } }));
  const q = out.get('NVDA');
  assert.equal(q.price, 101);
  assert.equal(q.time, 20);                       // the last bar with a price, not the last stamp
  assert.ok(Math.abs(q.change_pct - (101 / 98 - 1) * 100) < 1e-9);
  assert.deepEqual(q.session, { start: 0, end: 100 });
  assert.deepEqual(q.series, { t: [10, 20], c: [100, 101] });
  assert.equal(parseSpark(spark({ X: { t: [1], c: [null], prev: 1 } })).get('X').error, 'no price in response');
  assert.equal(parseSpark({ spark: { result: null, error: { code: 'Bad Request' } } }).size, 0);
});

test('a board asks Yahoo twenty symbols a call', () => {
  const list = Array.from({ length: 504 }, (_, i) => i);
  const parts = batches(list);
  assert.equal(parts.length, 26);
  assert.ok(parts.every((p) => p.length <= SPARK_BATCH));
});

test('a failed source leaves its own rows as errors and the rest priced', async () => {
  const real = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (String(url).includes('yahoo')) {
      return new Response(JSON.stringify(spark({ '^GSPC': { t: [10], c: [5], prev: 4 } })), { status: 200 });
    }
    return new Response('nope', { status: 503 });
  };
  try {
    const body = await buildBody({
      refresh_seconds: 60,
      strip: [{ symbol: '^GSPC', label: 'SPX', kind: 'index' }],
      rates: [{ symbol: 'US10Y', label: 'UST 10Y', kind: 'rate' }],
    }, 50_000);
    assert.equal(body.quotes[0].price, 5);
    assert.equal(body.quotes[0].session, undefined);
    assert.equal(body.quotes[0].series, undefined);   // the strip carries no chart
    assert.equal(body.quotes[1].error, 'HTTP 503');
    assert.equal(body.quotes[1].price, undefined);
    assert.equal(body.session.open, true);
  } finally {
    globalThis.fetch = real;
  }
});

test('a Yahoo yield index is a rate row: the yield with its change in basis points', async () => {
  const real = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (String(url).includes('yahoo')) {
      return new Response(JSON.stringify(spark({ '^GSPC': { t: [10], c: [5], prev: 4 }, '^TNX': { t: [10], c: [5.24], prev: 5.244 } })), { status: 200 });
    }
    return new Response('nope', { status: 403 });
  };
  try {
    const body = await buildBody({
      refresh_seconds: 60,
      strip: [{ symbol: '^GSPC', label: 'SPX', kind: 'index' }],
      rates: [{ symbol: '^TNX', label: 'UST 10Y', kind: 'rate', source: 'yahoo' }, { symbol: 'US2Y', label: 'UST 2Y', kind: 'rate', source: 'cnbc' }],
    }, 50_000);
    const [ten, two] = body.quotes.slice(1);
    assert.equal(ten.label, 'UST 10Y');
    assert.equal(ten.price, 5.24);
    assert.equal(ten.change_bp, -0.4);
    assert.equal(ten.source, 'Yahoo');
    assert.equal(ten.session, undefined);
    assert.equal(two.error, 'HTTP 403');
  } finally {
    globalThis.fetch = real;
  }
});

test('a board returns its own symbols, with the day\'s series only where it asks', async () => {
  const real = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (url) => {
    seen.push(decodeURIComponent(String(url)));
    const symbols = decodeURIComponent(String(url)).match(/symbols=([^&]+)/)[1].split(',');
    return new Response(JSON.stringify(spark(Object.fromEntries(symbols.map((s) => [s, { t: [1, 2], c: [9, 10], prev: 8 }])))), { status: 200 });
  };
  try {
    const contract = { boards: {
      heatmap: { symbols: Array.from({ length: 45 }, (_, i) => `S${i}`), series: false, refresh_seconds: 300, closed_refresh_seconds: 900 },
      indices: { symbols: ['^GSPC'], series: true, refresh_seconds: 300 },
    } };
    const heat = await buildBody(contract, 1000, 'board:heatmap');
    assert.equal(seen.length, 3);                          // 45 names, three calls
    assert.equal(heat.quotes.length, 45);
    assert.equal(heat.quotes[0].series, undefined);
    assert.equal(heat.refresh_seconds, 300);
    const idx = await buildBody(contract, 1000, 'board:indices');
    assert.deepEqual(idx.quotes[0].series, { t: [1, 2], c: [9, 10] });
    assert.equal((await buildBody(contract, 1000, 'board:nope')).error, 'no board nope');
  } finally {
    globalThis.fetch = real;
  }
});

test('a request names the strip, a board the contract has, or the trade desk', () => {
  const contract = { boards: { heatmap: { symbols: [] } } };
  assert.equal(scopeOf(new URLSearchParams(''), contract), 'default');
  assert.equal(scopeOf(new URLSearchParams('board=heatmap'), contract), 'board:heatmap');
  assert.equal(scopeOf(new URLSearchParams('board=anything'), contract), 'default');
  assert.equal(scopeOf(new URLSearchParams('scope=trade'), contract), 'trade');
});

test('trade scope fetches its bounded list without slowing the main live strip', async () => {
  const original = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (url) => {
    seen.push(String(url));
    if (String(url).includes('/spark')) return new Response(JSON.stringify(spark({ '^GSPC': { t: [1], c: [10], prev: 9 } })), { status: 200 });
    return new Response(JSON.stringify(yahoo({ regularMarketPrice: 10, previousClose: 9 })), { status: 200 });
  };
  try {
    const contract = { strip: [{ symbol: '^GSPC', kind: 'index' }],
      overnight: [{ symbol: 'ES=F', kind: 'overnight' }], premarket_movers: [{ symbol: 'AAPL', kind: 'premarket' }] };
    const regular = await buildBody(contract, 1000);
    assert.deepEqual(regular.quotes.map((q) => q.symbol), ['^GSPC']);
    const trade = await buildBody(contract, 1000, 'trade');
    assert.deepEqual(trade.quotes.map((q) => q.symbol), ['ES=F', 'AAPL']);
    assert.ok(seen.some((u) => u.includes('interval=1m&range=1d&includePrePost=true')));
  } finally {
    globalThis.fetch = original;
  }
});

test('ages read as seconds, minutes, hours, days; no time is a dash', () => {
  assert.equal(L.ageText(L.ageSeconds(95, 100_000)), '5s');
  assert.equal(L.ageText(125), '2m');
  assert.equal(L.ageText(7200), '2h');
  assert.equal(L.ageText(3 * 86400), '3d');
  assert.equal(L.ageText(L.ageSeconds(null, 1)), '—');
});

test('a price is stale only while the session is open', () => {
  const quote = { time: 0 };
  const open = { session: { open: true }, stale_after_seconds: 1200 };
  assert.equal(L.isStale(quote, open, 1201_000), true);
  assert.equal(L.isStale(quote, open, 1199_000), false);
  assert.equal(L.isStale(quote, { ...open, session: { open: false } }, 99_999_000), false);
});

test('polling: every minute when open, slowly when closed, never when hidden', () => {
  const body = { refresh_seconds: 60, closed_refresh_seconds: 300, session: { open: true } };
  assert.equal(L.nextDelay(body, false), 60);
  assert.equal(L.nextDelay({ ...body, session: { open: false } }, false), 300);
  assert.equal(L.nextDelay({ ...body, session: { open: null } }, false), 60);
  assert.equal(L.nextDelay(body, true), null);
  assert.equal(L.nextDelay(null, false), 60);
});

test('a tab shown again fetches only if a refresh fell due while hidden', () => {
  const body = { refresh_seconds: 60, session: { open: true } };
  assert.equal(L.dueOnShow(0, body, 5), true);
  assert.equal(L.dueOnShow(1_000, body, 30_000), false);
  assert.equal(L.dueOnShow(1_000, body, 61_000), true);
});

test('the strip leads with indices, then VIX, the yields and the rest; names on their own row', async () => {
  const { stripRows } = await import('../../web/js/live.js');
  const quotes = [
    { label: 'WTI', kind: 'macro' }, { label: 'SPX', kind: 'index' }, { label: 'NVDA', kind: 'watch' },
    { label: 'UST 10Y', kind: 'rate' }, { label: 'VIX', kind: 'macro' }, { label: 'NDX', kind: 'index' },
  ];
  const [first, names] = stripRows(quotes);
  assert.deepEqual(first.map((q) => q.label), ['SPX', 'NDX', 'VIX', 'UST 10Y', 'WTI']);
  assert.deepEqual(names.map((q) => q.label), ['NVDA']);
});

test('REFRESH asks the function for a fresh answer, whatever the URL already carries', async () => {
  const { withFresh } = await import('../../web/js/live-feed.js');
  assert.equal(withFresh('api/quotes'), 'api/quotes?fresh=1');
  assert.equal(withFresh('api/quotes?board=heatmap'), 'api/quotes?board=heatmap&fresh=1');
});

test('an index chart keeps a gap in the day as a gap', async () => {
  const { points } = await import('../../web/js/live-indices.js');
  assert.deepEqual(points({ t: [1, 2, 3], c: [10, null, 11] }), [[1000, 10], [2000, null], [3000, 11]]);
  assert.deepEqual(points(null), []);
});

test('an index chart spans the whole session, Yahoo\'s own or 09:30-16:00 New York on the series\' day', async () => {
  const { sessionWindow, newYorkOpen } = await import('../../web/js/live-indices.js');
  const open = Date.parse('2026-10-08T13:30:00Z') / 1000;       // 09:30 EDT
  const series = { t: [open, open + 300], c: [1, 2] };
  assert.deepEqual(sessionWindow({ start: open, end: open + 23400 }, series), [open * 1000, (open + 23400) * 1000]);
  // An early close comes from Yahoo's period, not from a calendar here.
  assert.deepEqual(sessionWindow({ start: open, end: open + 12600 }, series)[1], (open + 12600) * 1000);
  // After the close Yahoo may report tomorrow's period: the series' own day wins.
  const tomorrow = { start: open + 86400, end: open + 86400 + 23400 };
  assert.deepEqual(sessionWindow(tomorrow, series), [open * 1000, (open + 23400) * 1000]);
  assert.equal(newYorkOpen(Date.parse('2026-12-08T18:00:00Z') / 1000), Date.parse('2026-12-08T14:30:00Z') / 1000);  // EST
  assert.equal(sessionWindow(null, { t: [] }), null);
});

test('an index chart\'s value range always holds the previous close', async () => {
  const { valueRange } = await import('../../web/js/live-indices.js');
  const [low, high] = valueRange({ c: [7773, 7794, null] }, 7801.77);
  assert.ok(high > 7801.77 && low < 7773);
  const [l2, h2] = valueRange({ c: [100, 100] }, null);
  assert.ok(l2 < 100 && h2 > 100);
  assert.equal(valueRange({ c: [] }, null), null);
});

test('bond-market holidays: Columbus Day and Veterans Day, observed as the bond market does', () => {
  assert.equal(L.bondHoliday('2026-10-12'), true);    // the second Monday of October
  assert.equal(L.bondHoliday('2026-10-13'), false);
  assert.equal(L.bondHoliday('2026-10-05'), false);   // the first Monday is not one
  assert.equal(L.bondHoliday('2025-10-13'), true);
  assert.equal(L.bondHoliday('2026-11-11'), true);    // a Wednesday
  assert.equal(L.bondHoliday('2029-11-12'), true);    // Nov 11 is a Sunday: the Monday after
  assert.equal(L.bondHoliday('2028-11-10'), false);   // Nov 11 is a Saturday: no weekday closure
  assert.equal(L.bondHoliday('2028-11-13'), false);
  assert.equal(L.bondHoliday('not a date'), false);
});

test('the strip\'s day is New York\'s calendar day, not UTC\'s', () => {
  assert.equal(L.newYorkDate(Date.parse('2026-10-12T03:00:00Z')), '2026-10-11');   // 23:00 on the 11th in New York
  assert.equal(L.newYorkDate(Date.parse('2026-10-12T15:00:00Z')), '2026-10-12');
  assert.equal(L.newYorkDayLabel(Date.parse('2026-10-12T15:00:00Z')), 'MON OCT 12');
});

test('the five primary quotes lead in their own order; the rest follow in strip order', async () => {
  const { splitPrimary, PRIMARY } = await import('../../web/js/live.js');
  const quotes = [
    { label: 'NVDA', kind: 'watch' }, { label: 'DXY', kind: 'macro' }, { label: 'WTI', kind: 'macro' },
    { label: 'UST 10Y', kind: 'rate' }, { label: 'VIX', kind: 'macro' }, { label: 'NDX', kind: 'index' },
    { label: 'SPX', kind: 'index' }, { label: 'UST 2Y', kind: 'rate' },
  ];
  assert.deepEqual(PRIMARY, ['SPX', 'NDX', 'VIX', 'UST 10Y', 'DXY']);
  const [primary, rest] = splitPrimary(quotes);
  assert.deepEqual(primary.map((q) => q.label), ['SPX', 'NDX', 'VIX', 'UST 10Y', 'DXY']);
  assert.deepEqual(rest.map((q) => q.label), ['UST 2Y', 'WTI', 'NVDA']);
});

test('a spark answer keeps Yahoo\'s extended-hours price apart from the regular one', () => {
  const payload = spark({ NFLX: { t: [10, 20], c: [69, 68.69], prev: 69.85 } });
  payload.NFLX.fulldayPrice = 64.75;
  const q = parseSpark(payload).get('NFLX');
  assert.equal(q.price, 68.69);
  assert.equal(q.extended_price, 64.75);
  assert.ok(Math.abs(L.extendedMove(q) - (64.75 / 68.69 - 1) * 100) < 1e-9);
  assert.equal(L.extendedMove({ price: 10, extended_price: 10 }), null);   // no extended trade
  assert.equal(L.extendedMove({ price: 10, extended_price: null }), null);
});

test('the trading day by the New York clock, and the heat map\'s schedule across it', () => {
  const at = (iso) => Date.parse(iso);          // October: New York is UTC-4
  assert.equal(L.marketPhase(at('2026-10-20T08:00:00Z')), 'pre');
  assert.equal(L.marketPhase(at('2026-10-20T13:30:00Z')), 'regular');
  assert.equal(L.marketPhase(at('2026-10-20T20:00:00Z')), 'post');
  assert.equal(L.marketPhase(at('2026-10-21T00:00:00Z')), 'closed');
  assert.equal(L.marketPhase(at('2026-10-24T15:00:00Z')), 'closed');   // Saturday
  const body = { refresh_seconds: 300, closed_refresh_seconds: 900, extended_refresh_seconds: 900, session: { open: true } };
  assert.equal(L.boardDelay(body, false, at('2026-10-20T14:00:00Z')), 300);
  assert.equal(L.boardDelay(body, false, at('2026-10-20T21:00:00Z')), 900);
  assert.equal(L.boardDelay(body, false, at('2026-10-21T00:00:00Z')), 8 * 3600);   // overnight: wake at 04:00
  assert.equal(L.boardDelay(body, false, at('2026-10-24T03:30:00Z')), 52.5 * 3600); // Friday 23:30 ET: Monday 04:00
  assert.equal(L.boardDelay(body, true, at('2026-10-20T21:00:00Z')), null);
});
