import test from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/market-state-model.js';

test('a reading is phrased with its unit, and a missing one is a dash', () => {
  assert.equal(M.readingText({ value: -4.19, unit: 'pp' }), '-4.2 pp');
  assert.equal(M.readingText({ value: 1.2, unit: 'pp' }), '+1.2 pp');
  assert.equal(M.readingText({ value: 45.45, unit: '%' }), '45.5%');
  assert.equal(M.readingText({ value: 14.84, unit: 'pts' }), '14.8');
  assert.equal(M.readingText({ value: null, unit: 'pp' }), '—');
  assert.equal(M.readingText(null), '—');
  assert.equal(M.readingNote({ count: { above: 5, of: 11 } }), '5 OF 11 FUNDS');
  assert.equal(M.readingNote({}), null);
});

test('an outcome is coloured only when its range excludes zero, and by whether it hurts', () => {
  const ret = (o) => M.outcomeCell('ret', o, 'pp');
  assert.equal(ret({ diff: 4, lo: 1, hi: 7, inside: 7, outside: 3, detected: true }).tone, 'up');
  assert.equal(ret({ diff: -4, lo: -7, hi: -1, inside: 0, outside: 4, detected: true }).tone, 'down');
  assert.equal(ret({ diff: 4, lo: -1, hi: 9, inside: 7, outside: 3, detected: false }).tone, 'dim');   // a range through zero is not a finding
  assert.equal(M.outcomeCell('worst_dd', { diff: -2, lo: -3, hi: -0.5, inside: -8, outside: -6, detected: true }, 'pp').tone, 'down');
  assert.equal(M.outcomeCell('hit', { diff: 24, lo: 7, hi: 38, inside: 74, outside: 51, detected: true }, '%').tone, 'down');
  const none = ret(null);
  assert.deepEqual([none.text, none.tone], ['—', 'dim']);
  assert.match(ret({ diff: 4, lo: -1, hi: 9, inside: 7, outside: 3, detected: false }).title, /no difference detected/);
  assert.equal(ret({ diff: 1.04, lo: -1.53, hi: 3.53, inside: 1, outside: 0, detected: false }).text, '+1.0 (-1.5 to +3.5)');
});

test('the summary splits what holds now into what has a detected consequence and what has not', () => {
  const ok = (key, label, active, detected) => ({
    key, label, active_now: active, status: 'ok', days: 600, episodes: 12,
    outcomes: { ret: { diff: 4, lo: detected ? 1 : -1, hi: 7, detected }, worst_dd: { diff: -2, lo: -3, hi: detected ? -0.5 : 0.5, detected }, hit: { diff: 20, lo: 5, hi: 35, detected: true } },
  });
  const s = M.stateSummary([ok('a', 'THIN', true, true), ok('b', 'NARROW', true, false), ok('c', 'STRESS', false, true),
    { key: 'd', label: 'RARE', active_now: true, status: 'insufficient', days: 3, episodes: 1, outcomes: null }]);
  assert.deepEqual(s.holding, ['THIN', 'NARROW', 'RARE']);
  assert.equal(s.detected.length, 2);                                   // NARROW still has the chance-of-fall range above zero
  assert.deepEqual(s.undetected.map((x) => x.label), ['RARE']);          // too few days to say anything
  assert.match(s.detected[0].parts.join(' '), /return \+4\.0 pp/);
  assert.match(M.stateSummary([ok('a', 'THIN', true, true)], 5).detected[0].parts.join(' '), /chance of a 5%\+ fall \+20\.0 pp/);
  assert.deepEqual(M.stateSummary(null), { holding: [], detected: [], undetected: [] });
});

test('days now and the sector flags read as the page shows them', () => {
  assert.equal(M.daysNow({ active_now: true, days_now: 13 }), 'NOW · 13 D');
  assert.equal(M.daysNow({ active_now: false, days_now: 0 }), null);
  assert.deepEqual(M.sectorFlag({ above_200: true, vs_200_pct: 3.21 }), { text: '▲ +3.2%', tone: 'up' });
  assert.deepEqual(M.sectorFlag({ above_200: false, vs_200_pct: -2.0 }), { text: '▼ -2.0%', tone: 'down' });
  assert.deepEqual(M.sectorFlag({ above_200: null, vs_200_pct: null }), { text: '—', tone: 'dim' });
});
