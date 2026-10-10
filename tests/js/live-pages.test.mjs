// The pages that take live prices only on REFRESH: SECTORS' TODAY window,
// the Treasury table's live spreads, and the yield board's source.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { todayFrom, applyToday, TODAY } from '../../web/js/rotation-live.js';
import { buildBody } from '../../functions/api/quotes.js';

const close = (a, b) => Math.abs(a - b) < 1e-9;

function rotation() {
  const window = () => ({ '1M': { return: 1, excess: 0 } });
  const scheme = () => ({ windows: window(), breadth: { '1M': 50 } });
  return {
    benchmark: { cap: { '1M': 1 }, equal: { '1M': 1 } },
    groups: [{ key: 'Tech', label: 'Tech', cap: scheme(), equal: scheme() },
      { key: 'Energy', label: 'Energy', cap: scheme(), equal: scheme() }],
    sub_industries: [{ sector: 'Tech', label: 'Chips', cap: { '1M': {} }, equal: { '1M': {} } }],
    members: [
      { ticker: 'A', sector: 'Tech', sub_sector: 'Chips', weight: 3, returns: {}, contribution: { cap: {}, equal: {} } },
      { ticker: 'B', sector: 'Tech', sub_sector: 'Software', weight: 1, returns: {}, contribution: { cap: {}, equal: {} } },
      { ticker: 'C', sector: 'Energy', sub_sector: 'Oil', weight: 4, returns: {}, contribution: { cap: {}, equal: {} } },
      { ticker: 'D', sector: 'Energy', sub_sector: 'Oil', weight: 2, returns: {} },
    ],
  };
}

test('TODAY is the page\'s own baskets at live member prices, unpriced names left out', () => {
  const data = rotation();
  const quotes = [{ symbol: 'A', change_pct: 2 }, { symbol: 'B', change_pct: -2 }, { symbol: 'C', change_pct: 1 },
    { symbol: 'D', price: null, change_pct: null, error: 'no price in response' }];
  const etfs = [{ symbol: 'XLK', label: 'Tech', change_pct: 1.5 }, { symbol: 'SPY', label: 'benchmark', change_pct: 0.5 },
    { symbol: 'XLE', label: 'Energy', error: 'HTTP 500' }];
  const t = todayFrom(data, quotes, etfs);
  assert.equal(t.priced, 3);
  assert.equal(t.total, 4);
  assert.ok(close(t.benchmark.cap, (3 * 2 + 1 * -2 + 4 * 1) / 8));     // 1.0
  assert.ok(close(t.benchmark.equal, 1 / 3));
  assert.ok(close(t.groups.Tech.cap.return, 1));                       // (3*2 - 2) / 4
  assert.ok(close(t.groups.Tech.cap.excess, 0));
  assert.equal(t.groups.Energy.priced, 1);                             // D has no price
  assert.equal(t.groups.Tech.cap.breadth, 50);                         // A beats 1.0, B does not
  // Contributions add up to the sector's pp, as on the longer windows.
  const sum = t.members.A.contribution.equal + t.members.B.contribution.equal;
  assert.ok(close(sum, t.groups.Tech.equal.excess));
  assert.ok(close(t.subs['Tech|Chips'].cap.return, 2));
  assert.ok(close(t.etfs.Tech.excess, 1));
  assert.equal(t.etfs.Energy.excess, null);
  assert.equal(t.etfs.Energy.error, 'HTTP 500');
  assert.equal(t.etfBenchmark.symbol, 'SPY');
});

test('TODAY is written into the artifact\'s own shape, beside the build\'s windows', () => {
  const data = rotation();
  applyToday(data, todayFrom(data, [{ symbol: 'A', change_pct: 2 }, { symbol: 'C', change_pct: 1 }]));
  assert.ok(close(data.benchmark.cap[TODAY], (6 + 4) / 7));
  assert.deepEqual(Object.keys(data.groups[0].cap.windows), ['1M', TODAY]);
  assert.equal(data.members[1].returns[TODAY], null);                  // B unpriced: null, never 0
  assert.equal(data.members[3].contribution.cap[TODAY], null);         // D had no contribution object
  assert.ok(close(data.sub_industries[0].cap[TODAY].return, 2));
});

test('a live spread is its two legs\' difference, in bp, and nothing when a leg is missing', async () => {
  const { liveSpread } = await import('../../web/js/tabs/fixed-income.js');
  const byTenor = new Map([['10Y', { price: 5.286, change_bp: -2.5 }], ['2Y', { price: 4.798, change_bp: -3.5 }]]);
  assert.deepEqual(liveSpread('10Y - 2Y', byTenor), { bps: 48.8, change_bp: 1 });
  assert.equal(liveSpread('10Y - 3M', byTenor), null);
});

test('the manual status says the page is on the build\'s close until REFRESH, and never promises a next fetch', async () => {
  const { manualStatusText } = await import('../../web/js/live-feed.js');
  assert.equal(manualStatusText({ body: null }), 'BUILD CLOSE · PRESS REFRESH FOR LIVE PRICES');
  const text = manualStatusText({ body: { session: { open: true } }, lastFetch: 0 }, 90_000);
  assert.equal(text, 'SESSION OPEN · LIVE AS OF 1m AGO · PRESS REFRESH TO UPDATE');
  assert.ok(!/NEXT/.test(text));
  assert.equal(manualStatusText({ body: { session: { open: null } }, lastFetch: 0 }, 5_000), 'LIVE AS OF 5s AGO · PRESS REFRESH TO UPDATE');
});

test('the yield board asks CNBC once for the whole curve', async () => {
  const real = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (url) => {
    seen.push(decodeURIComponent(String(url)));
    return new Response(JSON.stringify({ FormattedQuoteResult: { FormattedQuote: [
      { symbol: 'US2Y', last: '4.798%', change: '-0.035' }, { symbol: 'US10Y', last: '5.286%', change: '-0.025' }] } }), { status: 200 });
  };
  try {
    const contract = { boards: { yields: { source: 'cnbc', symbols: ['US2Y', 'US10Y'], labels: { US2Y: '2Y', US10Y: '10Y' } } } };
    const body = await buildBody(contract, 1000, 'board:yields');
    assert.equal(seen.length, 1);
    assert.ok(seen[0].includes('cnbc.com') && seen[0].includes('US2Y|US10Y'));
    assert.deepEqual(body.quotes.map((q) => [q.label, q.price, q.change_bp]), [['2Y', 4.798, -3.5], ['10Y', 5.286, -2.5]]);
  } finally {
    globalThis.fetch = real;
  }
});

test('a risk chart is weekly for the long history and daily for the last year', async () => {
  const { chartHistory } = await import('../../web/js/tabs/risk.js');
  const tile = {
    history: { dates: ['2025-09-05', '2025-09-12', '2025-10-10', '2026-10-09'], values: [1, 2, 3, 9] },
    recent: { dates: ['2025-10-10', '2025-10-13', '2026-10-09'], values: [3, 4, 9] },
  };
  assert.deepEqual(chartHistory(tile), {
    dates: ['2025-09-05', '2025-09-12', '2025-10-10', '2025-10-13', '2026-10-09'], values: [1, 2, 3, 4, 9],
  });
  // A weekly source has no daily year: its history is the chart.
  assert.deepEqual(chartHistory({ history: tile.history, recent: null }), tile.history);
});
