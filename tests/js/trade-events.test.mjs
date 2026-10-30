import test from 'node:test';
import assert from 'node:assert/strict';
import { eventStudy, simulateNextOpen } from '../../web/js/trade-events.js';

function sample() {
  const dates = Array.from({ length: 70 }, (_, i) => `D${String(i).padStart(3, '0')}`);
  const close = [100];
  for (let i = 1; i < dates.length; i += 1) close.push(close.at(-1) * (i === 30 ? .9 : i % 2 ? 1.01 : .99));
  return { dates, close };
}

test('sigma events use prior volatility and expose 1, 3, 5, 10 and 20-session outcomes', () => {
  const { dates, close } = sample();
  const study = eventStudy(dates, close, { threshold: -2 });
  assert.deepEqual(study.rows.map((r) => r.days), [1, 3, 5, 10, 20]);
  assert.deepEqual(study.events.map((e) => e.worstDate), [dates[30]]);
  assert.ok(Math.abs(study.events[0].forward[1] - (close[33] / close[30] - 1) * 100) < 1e-9);
  const later = close.slice();
  for (let i = 40; i < later.length; i++) later[i] *= 2;
  assert.ok(eventStudy(dates, later, { threshold: -2 }).events.some((e) => e.worstDate === dates[30]));
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

test('sigma excludes insufficient prior history and percent threshold respects sign', () => {
  const { dates, close } = sample();
  assert.equal(eventStudy(dates.slice(0, 15), close.slice(0, 15), { threshold: -2 }).eligible, 0);
  const down = eventStudy(dates, close, { mode: 'percent', threshold: -5 });
  assert.deepEqual(down.events.map((e) => e.worstDate), [dates[30]]);
  assert.equal(eventStudy(dates, close, { mode: 'percent', threshold: 5 }).events.length, 0);
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
