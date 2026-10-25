import { test } from 'node:test';
import assert from 'node:assert/strict';
import { matchTickers } from '../../web/js/ticker-suggest.js';

const tickers = ['A', 'AAPL', 'ABBV', 'AMZN', 'AXP', 'GOOG', 'GOOGL', 'BKNG', 'MSFT'];
const names = { AMZN: 'Amazon.com Inc', GOOG: 'Alphabet Inc Class C', GOOGL: 'Alphabet Inc Class A', BKNG: 'Booking Holdings', AXP: 'American Express' };

test('symbols starting with the text come first, the exact one at the top, then shorter ones', () => {
  assert.deepEqual(matchTickers('goog', tickers, names).map((m) => m.ticker), ['GOOG', 'GOOGL']);
  assert.deepEqual(matchTickers('A', tickers, names).map((m) => m.ticker), ['A', 'AXP', 'AAPL', 'ABBV', 'AMZN', 'GOOG', 'GOOGL']);
});

test('a name matches on a word start, after the symbols, and the list is capped', () => {
  assert.deepEqual(matchTickers('amazon', tickers, names).map((m) => m.ticker), ['AMZN']);
  assert.deepEqual(matchTickers('book', tickers, names), [{ ticker: 'BKNG', name: 'Booking Holdings' }]);
  // "ex" is inside "Express" at a word start, not inside a ticker.
  assert.deepEqual(matchTickers('EX', tickers, names).map((m) => m.ticker), ['AXP']);
  assert.equal(matchTickers('A', tickers, names, 3).length, 3);
  assert.deepEqual(matchTickers('  ', tickers, names), []);
});

test('the build\'s weight rank puts the larger companies first within the matches', () => {
  const rank = ['AAPL', 'AMZN', 'GOOGL', 'GOOG', 'ABBV', 'AXP'];
  assert.deepEqual(matchTickers('A', tickers, names, 5, rank).map((m) => m.ticker), ['A', 'AAPL', 'AMZN', 'ABBV', 'AXP']);
});
