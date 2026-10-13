import test from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/catalyst-log-model.js';

test('the reading words the pair of states and says when too few names carry an estimate', () => {
  const held = M.reading({ price: 'down', estimates: 'flat', read_period: '0y', names_with_estimates: 6 }, 'THIS YEAR');
  assert.match(held.text, /^Prices fell and estimates have not moved: what investors will pay changed/);
  assert.match(held.text, /\(this year estimates\)$/);
  assert.equal(held.tone, 'info');
  assert.equal(M.reading({ price: 'down', estimates: 'down' }, 'THIS YEAR').tone, 'down');
  assert.equal(M.reading({ price: 'down', estimates: 'up' }, 'THIS YEAR').tone, 'warn');
  const few = M.reading({ price: 'down', estimates: null, names_with_estimates: 1 });
  assert.equal(few.text, 'Prices fell. 1 name with a recorded estimate: too few to say whether estimates followed.');
  assert.equal(M.reading({ price: 'up', estimates: null, names_with_estimates: 0 }).text, 'Prices rose. 0 names with a recorded estimate: too few to say whether estimates followed.');
  assert.match(M.reading({ price: null, estimates: null }).text, /^No price reading/);
  assert.match(M.reading(null).text, /^No price reading/);
});

test('every one of the nine pairs has a sentence', () => {
  for (const p of ['down', 'flat', 'up']) for (const e of ['down', 'flat', 'up']) {
    const r = M.reading({ price: p, estimates: e }, 'THIS YEAR');
    assert.ok(r.text.length > 20 && ['info', 'down', 'warn', 'dim', 'up'].includes(r.tone), `${p}|${e}`);
  }
});

test('counts keep a blank as a blank and show the seven-day pair only when recorded', () => {
  assert.equal(M.countsText({ up_7d: 26, down_7d: 1, up_30d: 10, down_30d: 2 }), '7d 26↑ 1↓ · 30d 10↑ 2↓');
  assert.equal(M.countsText({ up_7d: null, down_7d: null, up_30d: 28, down_30d: 2 }), '30d 28↑ 2↓');
  assert.equal(M.countsText({ up_7d: null, down_7d: null, up_30d: null, down_30d: null }), '30d —');
  assert.equal(M.countsText(null), '—');
  assert.equal(M.countPair(0, 3), '0↑ 3↓');                                            // a real zero is a zero
});

test('signed figures, the median cell and the kind label', () => {
  assert.equal(M.signed(-4.44, 1), '-4.4%');
  assert.equal(M.signed(0, 1), '0.0%');
  assert.equal(M.signed(null), '—');
  assert.equal(M.medianCell({ n: 3, median: -4.4 }), '-4.4% (3)');
  assert.equal(M.medianCell({ n: 0, median: null }), '—');
  assert.equal(M.medianCell(null), '—');
  assert.equal(M.kindLabel('competition'), 'COMPETITION');
  assert.equal(M.kindLabel('policy'), 'POLICY');
  assert.equal(M.kindLabel(null), null);
});
