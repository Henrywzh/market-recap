import test from 'node:test';
import assert from 'node:assert/strict';
import { stateAt, matchSignals, stretches, summary, randomDrawShare, likeToday } from '../../web/js/trade-conditions.js';

const fed = { key: 'fed', today: 'HOLD', runs: [['2020-01-02', 'HOLD'], ['2022-03-17', 'HIKING'], ['2023-09-01', 'HOLD']] };
const quad = { key: 'quadrant', today: 'REFLATION', runs: [['2014-02-04', 'SLOWDOWN'], ['2022-01-04', 'STAGFLATION'], ['2022-12-01', null]] };

test('a state holds from its first date until the next run; before the first run it is unknown', () => {
  assert.equal(stateAt(fed.runs, '2019-12-31'), null);
  assert.equal(stateAt(fed.runs, '2022-03-16'), 'HOLD');
  assert.equal(stateAt(fed.runs, '2022-03-17'), 'HIKING');
  assert.equal(stateAt(fed.runs, '2030-01-01'), 'HOLD');
  assert.equal(stateAt(quad.runs, '2023-01-01'), null);
});

test('signals keep only matching backdrops; an unknown state for a set condition drops the signal', () => {
  const signals = ['2021-05-03', '2022-06-01', '2022-11-01', '2023-02-01'];
  assert.deepEqual(matchSignals(signals, [fed, quad], {}), signals);
  assert.deepEqual(matchSignals(signals, [fed, quad], { fed: 'HIKING' }), ['2022-06-01', '2022-11-01', '2023-02-01']);
  assert.deepEqual(matchSignals(signals, [fed, quad], { fed: 'HIKING', quadrant: 'STAGFLATION' }), ['2022-06-01', '2022-11-01']);
});

test('stretches split trades more than the gap apart', () => {
  const t = (signal) => ({ signal, ret: 1 });
  assert.equal(stretches([t('2022-01-03'), t('2022-02-01'), t('2022-09-01'), t('2022-09-20')], 91), 2);
  assert.equal(stretches([], 91), 0);
});

test('summary and the random-draw share', () => {
  const s = summary([{ ret: 10 }, { ret: -10 }, { ret: 4 }]);
  assert.equal(s.n, 3); assert.equal(s.median, 4); assert.ok(Math.abs(s.total - (1.1 * 0.9 * 1.04 - 1) * 100) < 1e-9);
  const all = Array.from({ length: 100 }, (_, i) => i - 50);
  assert.equal(randomDrawShare(all, 10, 1000), 0);
  assert.equal(randomDrawShare(all, 10, -1000), 1);
  const mid = randomDrawShare(all, 10, -0.5);
  assert.ok(mid > 0.35 && mid < 0.65);
  assert.equal(randomDrawShare(all, 100, 0), null);
  assert.equal(randomDrawShare(all, 10, 3), randomDrawShare(all, 10, 3));
});

test('like today takes every condition that has a state today', () => {
  assert.deepEqual(likeToday([fed, quad, { key: 'vix', today: null }]), { fed: 'HOLD', quadrant: 'REFLATION' });
});
