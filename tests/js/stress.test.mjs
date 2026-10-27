import test from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/stress-model.js';

const vote = (over = {}) => ({ key: 'vix_high', label: 'VIX above 25', unit: 'pts', op: 'gt', threshold: 25, value: 22.44, on: false, as_of: '2026-10-23', ...over });

test('a vote reads its value and the line, and an unknown vote says no reading, never off', () => {
  assert.equal(M.voteReading(vote()), '22.4 · line: above 25.0');
  assert.equal(M.voteReading(vote({ unit: 'pp', op: 'gt', value: 3.2, threshold: 3 })), '3.20 pts · line: above 3.00 pts');
  assert.equal(M.voteReading(vote({ on: null, value: null })), 'no reading');
  assert.equal(M.voteState(vote({ on: true })), 'on');
  assert.equal(M.voteState(vote({ on: false })), 'off');
  assert.equal(M.voteState(vote({ on: null })), 'unknown');
});

test('a group says how many of its known votes are on, and counts the unknown ones apart', () => {
  assert.equal(M.groupText({ on: 1, known: 2, total: 2 }), '1 of 2 on');
  assert.equal(M.groupText({ on: 0, known: 1, total: 2 }), '0 of 1 on · 1 unknown');
  assert.equal(M.groupText({ on: 0, known: 0, total: 2 }), 'no reading');
  assert.equal(M.groupTone({ on: 1, known: 2 }), 'down');
  assert.equal(M.groupTone({ on: 0, known: 2 }), 'up');
  assert.equal(M.groupTone({ on: 0, known: 0 }), 'dim');
});

test('the headline is the raw count when every vote is known and the known part when one is missing', () => {
  assert.equal(M.countText({ raw: 3, total: 9, known: 9, on_known: 3 }), '3 of 9 on');
  assert.equal(M.countText({ raw: null, total: 9, known: 7, on_known: 2 }), '2 of 7 known on');
  assert.equal(M.countText({ raw: null, total: 9, known: 0, on_known: 0 }), 'no reading');
});

test('the reference line is described only when the count exists, and change needs a count a week ago', () => {
  assert.equal(M.referenceText({ raw: 5, reference: 5 }), 'At or above the reference line of 5');
  assert.equal(M.referenceText({ raw: 4, reference: 5 }), 'Below the reference line of 5');
  assert.equal(M.referenceText({ raw: null, reference: 5 }), null);
  assert.equal(M.changeText({ raw: 5, week_ago: 3 }), '1 week ago: 3 · now 5 (+2)');
  assert.equal(M.changeText({ raw: 2, week_ago: 4 }), '1 week ago: 4 · now 2 (−2)');
  assert.equal(M.changeText({ raw: 2, week_ago: 2 }), '1 week ago: 2 · now 2 (±0)');
  assert.equal(M.changeText({ raw: 2, week_ago: null }), null);
  assert.equal(M.changeText({ raw: null, week_ago: 2 }), null);
});

test('history starts at the first real count, and an input older than ten days is named', () => {
  assert.equal(M.firstKnown({ dates: ['a', 'b', 'c'], raw: [null, null, 2] }), 'c');
  assert.equal(M.firstKnown({ dates: [], raw: [] }), null);
  const stress = { as_of: '2026-10-23', groups: [{ votes: [vote(), vote({ key: 'anfci_tight', label: 'ANFCI', as_of: '2026-09-18' })] }] };
  assert.deepEqual(M.staleInputs(stress), [{ key: 'anfci_tight', label: 'ANFCI', as_of: '2026-09-18' }]);
});
