import { test } from 'node:test';
import assert from 'node:assert/strict';
import { change, logSpan, VIEWS } from '../../web/js/viewchart.js';

test('percent change over a lag, missing where either end is missing or the base is not positive', () => {
  assert.deepEqual(change([100, 110, null, 121, 0, 5], 1), [null, 10, null, null, -100, null]);
  assert.deepEqual(change([100, 200, 300], 2), [null, null, 200]);
});

test('point change for series that are already percentages', () => {
  assert.deepEqual(change([55.71, 56.13], 1, 'diff'), [null, 0.42]);
});

test('a raw view goes to a log axis only when the series span more than 25x', () => {
  assert.equal(logSpan([{ values: [12.5, 280, 3768] }]), true);
  assert.equal(logSpan([{ values: [100, 150] }, { values: [null, 90] }]), false);
});

test('view sets follow the frequency', () => {
  assert.deepEqual(VIEWS.monthly().map((v) => [v.id, v.lag]), [['RAW', undefined], ['MoM', 1], ['YoY', 12]]);
  assert.deepEqual(VIEWS.quarterly().map((v) => v.lag), [undefined, 1, 4]);
  assert.deepEqual(VIEWS.daily().map((v) => v.lag), [undefined, 7, 28]);
  assert.equal(VIEWS.monthly('diff')[1].kind, 'diff');
});
