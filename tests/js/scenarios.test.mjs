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

test('regime rows put each regime\'s slopes in a row, and the verdict is info only when the permutation p is under 0.05', () => {
  const slope = (v, t, n) => ({ slope: v, t, n });
  const rr = {
    status: 'ok', days: 1162,
    surprise: {
      all: { n: 1162, rates_days: 399, permutations: 2000, p_perm: 0.04, interaction: { coef: -0.121, t: -1.87 },
        by_regime: { rates: slope(-0.07, -1.5, 399), growth: slope(0.051, 1.6, 763) } },
      since_split: { interaction: { coef: -0.261, t: -2.3 }, by_regime: { rates: slope(-0.113, -1.8, 334), growth: slope(0.148, 1.7, 197) } },
    },
    after_the_move: { release_days: { rates: slope(-0.028, -4.1, 399), growth: slope(0.039, 5.6, 763) }, other_days: { rates: slope(-0.007, -1, 465), growth: slope(0.056, 8, 949) } },
    out_of_sample: { split: '2022-01-01', pooled: -0.269, by_regime: -0.007, train_days: 631, test_days: 531 },
  };
  const rows = M.regimeRows(rr);
  assert.deepEqual(rows.map((r) => r.key), ['rates', 'growth']);
  assert.equal(rows[0].onRelease.n, 399);
  const v = M.regimeVerdict(rr);
  assert.equal(v.tone, 'info');
  assert.match(v.text, /difference -0\.12% per sd \(t -1\.9, permutation p 0\.040\)/);
  assert.match(v.text, /from 2022-01-01 on -0\.26/);
  rr.surprise.all.p_perm = 0.2;
  assert.equal(M.regimeVerdict(rr).tone, 'dim');
  assert.deepEqual(M.regimeRows({ status: 'insufficient' }), []);
  assert.equal(M.regimeVerdict(null).text, 'no measurement');
  assert.match(M.oosText(rr.out_of_sample), /R² -0\.27, a line per regime R² -0\.01/);
  assert.match(M.oosText(rr.out_of_sample), /not by how much/);
  assert.doesNotMatch(M.oosText({ ...rr.out_of_sample, by_regime: 0.2 }), /not by how much/);
  assert.equal(M.oosText(null), null);
});

test('event size reads the 2-year yield and SPY, and is absent when the build has no figure', () => {
  const text = M.eventSizeText({ n: 120, dy2_release: 5.37, dy2_other: 3.47, spy_release: 0.85, spy_other: 0.82 });
  assert.match(text, /5\.4 bp on its release days against 3\.5 bp on others \(n 120\)/);
  assert.match(text, /SPY moved 0\.85× its recent typical day against 0\.82×/);
  assert.equal(M.eventSizeText({ n: 0, dy2_release: null, dy2_other: 3 }), null);
  assert.doesNotMatch(M.eventSizeText({ n: 5, dy2_release: 4, dy2_other: 3, spy_release: null, spy_other: 1 }), /SPY/);
});
