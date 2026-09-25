// The live strip: what the quote function makes of each publisher's answer,
// and when the page asks again.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseYahooChart, parseCnbcRates, sessionState, buildBody } from '../../functions/api/quotes.js';
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

test('a failed source leaves its own rows as errors and the rest priced', async () => {
  const real = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (String(url).includes('yahoo')) {
      return new Response(JSON.stringify(yahoo({
        regularMarketPrice: 5, chartPreviousClose: 4, regularMarketTime: 10,
        currentTradingPeriod: { regular: { start: 0, end: 100 } },
      })), { status: 200 });
    }
    return new Response('nope', { status: 503 });
  };
  try {
    const body = await buildBody({
      refresh_seconds: 60,
      equities: [{ symbol: 'SPY', label: 'SPY', kind: 'etf' }],
      rates: [{ symbol: 'US10Y', label: 'UST 10Y', kind: 'rate' }],
    }, 50_000);
    assert.equal(body.quotes[0].price, 5);
    assert.equal(body.quotes[0].session, undefined);
    assert.equal(body.quotes[1].error, 'HTTP 503');
    assert.equal(body.quotes[1].price, undefined);
    assert.equal(body.session.open, true);
  } finally {
    globalThis.fetch = real;
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
