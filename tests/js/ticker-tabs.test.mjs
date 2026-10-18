// TICKER sub-tabs: the hash's symbol and view, and back again.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { TICKER_TABS, tickerArg, tickerArgFor, creditSummary } from '../../web/js/tabs/ticker.js';

test('the page opens on RECENT; a known view after the symbol opens that tab', () => {
  assert.deepEqual(TICKER_TABS.map(([id]) => id), ['recent', 'report', 'price', 'valuation', 'financials']);
  assert.deepEqual(tickerArg('NVDA'), { symbol: 'NVDA', view: 'recent' });
  assert.deepEqual(tickerArg('NVDA/REPORT'), { symbol: 'NVDA', view: 'report' });
  assert.deepEqual(tickerArg('BRK.B/FINANCIALS'), { symbol: 'BRK.B', view: 'financials' });
  assert.deepEqual(tickerArg('NVDA/NOPE'), { symbol: 'NVDA', view: 'recent' });
  assert.deepEqual(tickerArg(null), { symbol: null, view: 'recent' });
});

test('RECENT is left out of the hash; the other views follow the symbol', () => {
  assert.equal(tickerArgFor('NVDA', 'recent'), 'NVDA');
  assert.equal(tickerArgFor('NVDA', 'valuation'), 'NVDA/VALUATION');
  TICKER_TABS.forEach(([id]) => assert.deepEqual(tickerArg(tickerArgFor('BRK-B', id)), { symbol: 'BRK-B', view: id }));
});

test('the credit summary reads the CREDIT row, dashing what it lacks', () => {
  assert.equal(creditSummary(null), null);
  const lines = creditSummary({ dd: 1.22, pd_1y: 11.17, own_percentile: 29, counted_debt_bn: 25.08 });
  assert.deepEqual(lines.map(([label, value]) => [label, value]), [
    ['DISTANCE TO DEFAULT', '1.22'], ['MODEL 1Y PD', '11.2%'], ['OWN 5Y HISTORY', '29th'], ['DEBT COUNTED', '$25.1B'],
  ]);
  assert.equal(creditSummary({ dd: 9, pd_1y: 0.001 })[1][1], '0.00%');
  assert.equal(creditSummary({})[2][1], '—');
});
