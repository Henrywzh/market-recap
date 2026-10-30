import test from 'node:test';
import assert from 'node:assert/strict';
import { dailyMoves, simulateNextOpen, tailShare } from '../../web/js/trade-events.js';

function sample() {
  const dates = Array.from({ length: 70 }, (_, i) => `D${String(i).padStart(3, '0')}`);
  const close = [100];
  for (let i = 1; i < dates.length; i += 1) close.push(close.at(-1) * (i === 30 ? .9 : i % 2 ? 1.01 : .99));
  return { dates, close };
}

test('daily moves divide each return by the prior 20 sessions\' volatility', () => {
  const { dates, close } = sample();
  const moves = dailyMoves(dates, close);
  assert.equal(moves.length, dates.length - 1);
  assert.ok(moves.slice(0, 20).every((m) => m.z === null));
  const prior = moves.slice(9, 29).map((m) => m.ret);
  const mean = prior.reduce((a, b) => a + b, 0) / 20;
  const sd = Math.sqrt(prior.reduce((a, b) => a + (b - mean) ** 2, 0) / 19);
  assert.ok(Math.abs(moves[29].z - moves[29].ret / sd) < 1e-9);
  assert.ok(moves[29].z < -2);
});

test('simulation enters next open, exits fifth close and skips overlapping signals', () => {
  const dates = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];
  const bars = { dates, open: [100, 100, 100, 100, 100, 100, 100, 100], close: [100, 102, 102, 102, 102, 110, 100, 100] };
  const trades = simulateNextOpen(['a', 'c'], bars, { sessions: 5, costBps: 10 });
  assert.equal(trades.length, 1);
  assert.equal(trades[0].entry, 'b');
  assert.equal(trades[0].exit, 'f');
  assert.ok(Math.abs(trades[0].ret - 9.9) < 1e-9);
  assert.deepEqual(simulateNextOpen(['h'], bars), []);
});

test('execution modes use only post-signal opens/closes with explicit holding endpoints', () => {
  const bars = { dates: ['signal', 'next', 'following', 'third'], open: [50, 100, 110, 130], close: [60, 105, 120, 140] };
  const ret = (execution, sessions = 1) => simulateNextOpen(['signal'], bars, { execution, sessions, costBps: 0 })[0];
  assert.equal(ret('open-close').entry, 'next');
  assert.equal(ret('open-close').exit, 'next');
  assert.ok(Math.abs(ret('open-close').ret - 5) < 1e-9);
  assert.ok(Math.abs(ret('open-open').ret - 10) < 1e-9);
  assert.ok(Math.abs(ret('close-close').ret - (120 / 105 - 1) * 100) < 1e-9);
  assert.ok(Math.abs(ret('close-open').ret - (110 / 105 - 1) * 100) < 1e-9);
  assert.equal(ret('open-close', 2).exit, 'following');
  assert.equal(ret('open-open', 2).exit, 'third');
  assert.deepEqual(simulateNextOpen(['following'], bars, { execution: 'close-close', sessions: 1 }), []);
  assert.deepEqual(simulateNextOpen(['signal'], bars, { execution: 'bad' }), []);
});

test('tailShare counts values at least as far out, in the move\'s direction', () => {
  assert.deepEqual(tailShare([-3, -1, 0, 2, 4, NaN, null], -1), { hits: 2, n: 5, share: 0.4 });
  assert.deepEqual(tailShare([-3, -1, 0, 2, 4], 3), { hits: 1, n: 5, share: 0.2 });
  assert.equal(tailShare([1, 2], 0), null);
  assert.equal(tailShare([], -1), null);
});
