// THEMES board cells: tone of a state, why it has its label, how a cell reads.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as B from '../../web/js/themes-board.js';

test('only strong price with rising estimates is green; weak with falling estimates is red', () => {
  assert.equal(B.stateTone('strong_rising'), 'up');
  assert.equal(B.stateTone('weak_falling'), 'down');
  assert.equal(B.stateTone('weak_steady'), 'info');      // price weak, estimates holding: a divergence, not a verdict
  assert.equal(B.stateTone('strong_steady'), 'warn');
  assert.equal(B.stateTone('nonsense'), 'dim');
  assert.equal(B.stateTone(null), 'dim');
});

test('the label comes with the numbers its rule used', () => {
  const board = { state: { key: 'weak_steady', relative_3m: -11.55, relative_pp: 2 }, revision: { median_pct: 0.01, of: 8, period: '0y', window: '30d', move_pct: 0.5 } };
  const why = B.stateWhy(board);
  assert.match(why, /-11\.6 pp against the S&P 500 over 3 months/);
  assert.match(why, /median 0y EPS estimate \+0\.01% over 30d across 8 names/);
  assert.match(B.stateWhy({ state: { key: null } }), /missing/);
  assert.match(B.stateWhy(null), /missing/);
});

test('breadth, revision and valuation cells read their counts and are absent without names', () => {
  assert.deepEqual(B.breadthText({ of: 8, above_ma: 6, up_month: 5, ma_sessions: 50 }), { main: '6/8', note: 'above 50d avg · 5 up 1M', share: 0.75 });
  assert.equal(B.breadthText({ of: 0 }), null);
  assert.equal(B.breadthText(null), null);
  const r = B.revisionText({ of: 10, median_pct: 0.4, rising: 3, falling: 2 });
  assert.equal(r.main, '+0.40%');
  assert.equal(r.note, '3↑ 5= 2↓ of 10');
  assert.equal(B.revisionText({ of: 0, median_pct: null }), null);
  assert.equal(B.valuationText({ of: 8, median_percentile: 40.2 }).main, '40');
  assert.equal(B.valuationText({ of: 2, median_percentile: null }), null);
});

test('the revision split is three widths that add to 100', () => {
  const w = B.splitWidths({ of: 8, median_pct: 1, rising: 2, falling: 2 });
  assert.equal(w.up + w.flat + w.down, 100);
  assert.deepEqual(w, { up: 25, flat: 50, down: 25 });
  assert.equal(B.splitWidths({ of: 0, median_pct: null }), null);
});

test('quadrant tone: leading green, lagging red, the two between amber', () => {
  assert.equal(B.quadrantTone('leading'), 'up');
  assert.equal(B.quadrantTone('lagging'), 'down');
  assert.equal(B.quadrantTone('improving'), 'warn');
  assert.equal(B.quadrantTone(null), 'dim');
});
