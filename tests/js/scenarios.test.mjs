// The page's pure parts: what counts as detected, a difference with its
// noise, where a bar sits, how the next release and the ordering test read.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/scenarios-model.js';

test('a figure is detected at |t| of 2 or more and never when t is absent', () => {
  assert.equal(M.detected({ slope: 1, t: 2 }), true);
  assert.equal(M.detected({ slope: 1, t: -3.1 }), true);
  assert.equal(M.detected({ slope: 1, t: 1.99 }), false);
  assert.equal(M.detected({ slope: null, t: null }), false);
  assert.equal(M.detected(null), false);
});

test('the difference of two classes carries both standard errors', () => {
  const d = M.diffWithSe({ mean: 0.5, se: 0.3 }, { mean: -0.4, se: 0.4 });
  assert.ok(Math.abs(d.diff - 0.9) < 1e-9);
  assert.ok(Math.abs(d.se - 0.5) < 1e-9);
  assert.ok(Math.abs(d.t - 1.8) < 1e-9);
  assert.equal(d.within, true);                       // 0.9 < 1.96 x 0.5
  assert.equal(M.diffWithSe({ mean: 2, se: 0.2 }, { mean: 0, se: 0.2 }).within, false);
  assert.equal(M.diffWithSe(null, { mean: 0, se: 1 }), null);
  assert.equal(M.diffWithSe({ mean: 1, se: 1 }, { mean: null, se: 1 }), null);
  assert.equal(M.diffWithSe({ mean: 1, se: null }, { mean: 0, se: 1 }).t, null);
});

test('sector differences are largest first and skip a sector with a class missing', () => {
  const classes = {
    above: { A: { mean: 1, se: 0.1 }, B: { mean: -1, se: 0.1 }, C: null },
    below: { A: { mean: 0, se: 0.1 }, B: { mean: 0, se: 0.1 }, C: { mean: 0, se: 0.1 } },
  };
  const rows = M.sectorDiffs(classes, [{ sector: 'a', etf: 'A' }, { sector: 'b', etf: 'B' }, { sector: 'c', etf: 'C' }, { sector: 'd', etf: 'D' }]);
  assert.deepEqual(rows.map((r) => r.etf), ['A', 'B']);
  assert.ok(rows[0].diff > 0 && rows[1].diff < 0);
  assert.deepEqual(M.sectorDiffs(null, [{ sector: 'a', etf: 'A' }]), []);
});

test('a bar starts at the centre, goes the way of the sign, and is cut at its scale', () => {
  assert.deepEqual(M.barSpan(1, 2), { left: 50, width: 25 });
  assert.deepEqual(M.barSpan(-1, 2), { left: 25, width: 25 });
  assert.deepEqual(M.barSpan(5, 2), { left: 50, width: 50 });
  assert.equal(M.barSpan(null, 2), null);
  assert.equal(M.barSpan(1, 0), null);
  assert.equal(M.columnScale([1, -4, null, 2]), 4);
  assert.equal(M.columnScale([null]), null);
});

test('the next release reads as a day, a time, the forecast and the prior', () => {
  const t = M.nextText({ date: '2026-10-14', time: '08:30', forecast: 0.2, previous: 0.3, unit: 'pp' });
  assert.deepEqual(t, { when: 'Wed 14 Oct 08:30', forecast: '0.2', previous: '0.3' });
  assert.equal(M.nextText({ date: '2026-10-15', time: '08:30', forecast: 197, previous: null, unit: 'k' }).previous, '—');
  assert.equal(M.nextText(null), null);
});

test('the ordering test reads its rho and p, or says there are too few releases', () => {
  const tested = M.persistenceView({ status: 'tested', rho: 0.509, p_perm: 0.074, split: '2022-01-01', train_above: 12, train_below: 15, test_above: 17, test_below: 18, permutations: 2000 });
  assert.equal(tested.text, 'ρ +0.51 · p 0.07');
  assert.equal(tested.tone, 'dim');                  // p of 0.074 is not a finding
  assert.equal(M.persistenceView({ status: 'tested', rho: 0.9, p_perm: 0.01, split: 'x', permutations: 1 }).tone, 'info');
  assert.equal(M.persistenceView({ status: 'insufficient' }).text, 'too few releases');
  assert.equal(M.persistenceView(null).text, 'too few releases');
});

test('nowcast rows put the best-explained sector first and drop a sector with no fit', () => {
  const rows = M.nowcastRows({ sectors: [
    { sector: 'a', etf: 'A', betas: { x: 1 }, r2: 0.05, implied_last_session: 0.1, actual_last_session: 0.2 },
    { sector: 'b', etf: 'B', betas: null, r2: null },
    { sector: 'e', etf: 'E', betas: { x: 2 }, r2: 0.48, implied_last_session: 0.8, actual_last_session: 3.4 },
  ] });
  assert.deepEqual(rows.map((r) => r.etf), ['E', 'A']);
  assert.deepEqual(M.nowcastRows(null), []);
});
