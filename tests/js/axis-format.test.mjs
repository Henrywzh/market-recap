import test from 'node:test';
import assert from 'node:assert/strict';
import * as F from '../../web/js/axis-format.js';

test('decimals follow the tick spacing, never more than three', () => {
  assert.equal(F.decimalsForStep(0.05), 2);
  assert.equal(F.decimalsForStep(0.5), 1);
  assert.equal(F.decimalsForStep(5), 0);
  assert.equal(F.decimalsForStep(10), 0);
  assert.equal(F.decimalsForStep(2.5), 1);
  assert.equal(F.decimalsForStep(0.25), 2);
  assert.equal(F.decimalsForStep(0.001), 3);
  assert.equal(F.decimalsForStep(0.0004), 3);
  assert.equal(F.decimalsForStep(0.3000000000000004), 1);
  assert.equal(F.decimalsForStep(null), 3);
  assert.equal(F.decimalsForStep(0), 3);
  assert.equal(F.decimalsForStep(NaN), 3);
});

test('tick labels print every tick at the step\'s decimals', () => {
  assert.deepEqual([0.6, 0.62, 0.64, 0.66].map((v) => F.formatTick(v, 0.02)), ['0.60', '0.62', '0.64', '0.66']);
  assert.deepEqual([0.6, 0.65, 0.7].map((v) => F.formatTick(v, 0.05)), ['0.60', '0.65', '0.70']);
  assert.deepEqual([-1, -0.5, 0, 0.5, 1].map((v) => F.formatTick(v, 0.5)), ['-1.0', '-0.5', '0.0', '0.5', '1.0']);
  assert.deepEqual([1000, 1010, 1020].map((v) => F.formatTick(v, 10)), ['1000', '1010', '1020']);
  assert.equal(F.formatTick(1.2345, 0.001), '1.234');
});

test('tick labels never print a negative zero', () => {
  assert.equal(F.formatTick(-1.1102230246251565e-16, 0.05), '0.00');
  assert.equal(F.formatTick(-0.0001, 0.001), '0.000');
  assert.equal(F.formatTick(-0.04, 0.5), '0.0');
});

test('tick labels fall back to the value form when the step is unusable', () => {
  assert.equal(F.formatTick(5.25, null), '5.25');
  assert.equal(F.formatTick(5, 0), '5');
  assert.equal(F.formatTick(null, 0.5), '—');
  assert.equal(F.formatTick(NaN, 0.5), '—');
});

test('values keep at most three decimals and drop trailing zeros', () => {
  assert.equal(F.formatValue(1.23456), '1.235');
  assert.equal(F.formatValue(0.7), '0.7');
  assert.equal(F.formatValue(2), '2');
  assert.equal(F.formatValue(2.5000), '2.5');
  assert.equal(F.formatValue(1234.5), '1234.5');
  assert.equal(F.formatValue(-1.5), '-1.5');
  assert.equal(F.formatValue(0.62, 1), '0.6');
  assert.equal(F.formatValue(0.62, 2), '0.62');
  assert.equal(F.formatValue(0.62, 3), '0.62');
});

test('values never print a negative zero and absence is an em dash', () => {
  assert.equal(F.formatValue(-0.0004), '0');
  assert.equal(F.formatValue(-0), '0');
  assert.equal(F.formatValue(0), '0');
  assert.equal(F.formatValue(null), '—');
  assert.equal(F.formatValue(undefined), '—');
  assert.equal(F.formatValue(NaN), '—');
  assert.equal(F.formatValue(Infinity), '—');
  assert.equal(F.formatValue(-Infinity), '—');
});

test('niceStepFromRange picks the 1, 2 or 5 times a power of ten nearest the target', () => {
  assert.equal(F.niceStepFromRange(0, 1, 5), 0.2);
  assert.equal(F.niceStepFromRange(0.6, 0.8, 5), 0.05);
  assert.equal(F.niceStepFromRange(0, 10, 5), 2);
  assert.equal(F.niceStepFromRange(0, 5, 5), 1);
  assert.equal(F.niceStepFromRange(0, 50, 5), 10);
  assert.equal(F.niceStepFromRange(0, 100, 5), 20);
  assert.equal(F.niceStepFromRange(0, 3, 5), 0.5);
  assert.equal(F.niceStepFromRange(-1, 1, 5), 0.5);
  assert.equal(F.niceStepFromRange(0, 1e6, 5), 200000);
  assert.equal(F.niceStepFromRange(0, 0.01, 5), 0.002);
  assert.equal(F.niceStepFromRange(0, 60, 5), 10);
  assert.equal(F.niceStepFromRange(0, 8, 5), 2);
});

test('niceStepFromRange is null for an empty or non-finite range', () => {
  assert.equal(F.niceStepFromRange(10, 10, 5), null);
  assert.equal(F.niceStepFromRange(10, 5, 5), null);
  assert.equal(F.niceStepFromRange(NaN, 5, 5), null);
  assert.equal(F.niceStepFromRange(0, Infinity, 5), null);
});

test('the step from a range decides the decimals of its labels', () => {
  const step = F.niceStepFromRange(0.6, 0.8, 5);
  assert.deepEqual([0.6, 0.65, 0.7, 0.75, 0.8].map((v) => F.formatTick(v, step)), ['0.60', '0.65', '0.70', '0.75', '0.80']);
});
