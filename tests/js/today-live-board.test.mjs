// TODAY read live: the share ladder, the live RSI, the board, and the headline
// held equal to the build's template (panels/today.py) on the same boards.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ladderShare, liveRsi, liveBoard, headlineOf, liveSignals } from '../../web/js/today-live-board.js';

const CASES = JSON.parse(readFileSync(new URL('./fixtures/today-headline-cases.json', import.meta.url)));

test('the live headline is the build\'s headline on the same board', () => {
  for (const { board, expected } of CASES) assert.deepEqual(headlineOf(board), expected);
});

const LADDER = {
  up: [[0.05, 50], [0.6, 10], [1.2, 5], [2.0, 1], [3.0, 0.1], [4.5, 0.04]],
  down: [[-0.05, 50], [-0.7, 10], [-1.4, 5], [-2.4, 1], [-3.6, 0.1], [-6.0, 0.04]],
};

test('the share is read off the ladder: interpolated, none inside the middle half, 0 past the record', () => {
  assert.ok(Math.abs(ladderShare(LADDER, 1.6) - 3) < 1e-9);
  assert.equal(ladderShare(LADDER, -2.4), 1);
  assert.ok(Math.abs(ladderShare(LADDER, -3.0) - 0.55) < 1e-9);
  assert.equal(ladderShare(LADDER, 0.01), null);
  assert.equal(ladderShare(LADDER, 7), 0);
  assert.equal(ladderShare(null, 2), null);
  assert.equal(ladderShare(LADDER, 0), null);
});

test('the live RSI extends the run below a line by today\'s quote, or ends it', () => {
  const state = { period: 6, close: 100, gain: 0.2, loss: 0.8, below: { 20: 0, 30: 2 } };
  const down = liveRsi(state, 98);
  assert.ok(down.rsi < 20 && down.line === 20 && down.days === 1 && down.days_shallow === 3);
  const up = liveRsi(state, 103);
  assert.equal(up.line, null);
  assert.equal(up.days, 0);
  assert.equal(liveRsi(null, 100), null);
});

const BOARD = {
  rows: [
    { symbol: '^GSPC', label: 'S&P 500', short: 'S&P 500', group: 'index', sigma_pct: 1, ladder: LADDER, rsi_state: { period: 6, close: 100, gain: 0.5, loss: 0.5, below: {} } },
    { symbol: 'RSP', label: 'Equal weight', short: 'Equal weight', group: 'index', sigma_pct: 1, ladder: LADDER },
    { symbol: 'XLK', label: 'Technology (XLK)', short: 'Tech', group: 'sector', sigma_pct: 2, ladder: LADDER, rsi_state: { period: 6, close: 50, gain: 0.1, loss: 0.9, below: { 20: 1, 30: 3 } } },
    { symbol: 'XLE', label: 'Energy (XLE)', short: 'Energy', group: 'sector', sigma_pct: 1.5, ladder: LADDER },
  ],
};
const quotes = new Map([
  ['^GSPC', { price: 98.5, change_pct: -1.5, time: '2026-10-23T18:32:00Z' }],
  ['RSP', { price: 50, change_pct: -0.2 }],
  ['XLK', { price: 48.7, change_pct: -2.6 }],
  ['^VIX', { price: 21.4, change: 2.1 }],
]);

test('the live board takes each quoted row\'s move, sigma multiple, share and RSI, and leaves unquoted rows out', () => {
  const live = liveBoard(BOARD, quotes);
  assert.deepEqual(live.rows.map((r) => r.symbol), ['^GSPC', 'RSP', 'XLK']);
  const xlk = live.rows.find((r) => r.symbol === 'XLK');
  assert.ok(Math.abs(xlk.z + 1.3) < 1e-9);
  assert.ok(Math.abs(xlk.share_pct - 0.85) < 1e-9);  // between the 1% and 0.1% points
  assert.equal(xlk.reading.line, 20);
  assert.deepEqual(live.vix, { value: 21.4, change: 2.1 });
  assert.equal(live.time, '2026-10-23T18:32:00Z');
  assert.equal(liveBoard(BOARD, new Map([['XLK', { change_pct: 1 }]])), null);  // no S&P 500 quote: no live board
  assert.equal(headlineOf(live).title, 'Mega-cap selloff, led by Tech −2.6% (rare)');
});

test('live RARE and OVERSOLD chips come in the build\'s item shape', () => {
  const { tails, oversold } = liveSignals(liveBoard(BOARD, quotes), { oversoldDetail: 'How stretched' });
  assert.deepEqual(tails.map((t) => t.extra.symbol), ['XLK', '^GSPC']);
  assert.ok(Math.abs(tails[0].extra.share_pct - 0.85) < 1e-9);
  assert.deepEqual(oversold.map((o) => [o.extra.symbol, o.extra.line]), [['XLK', 20]]);
  assert.equal(oversold[0].detail, 'How stretched');
  for (const item of [...tails, ...oversold]) assert.doesNotMatch(JSON.stringify(item), /NaN|undefined/);
});
