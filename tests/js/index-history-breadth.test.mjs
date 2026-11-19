import { test } from 'node:test';
import assert from 'node:assert/strict';

const { breadthPeriods } = await import('../../web/js/index-history.js');

test('the breadth chart offers the windows its history covers', () => {
  const span = (n) => ({ dates: Array.from({ length: n }, (_, i) => String(i)) });
  assert.deepEqual(breadthPeriods(span(252)), ['1M', '3M', '6M', '1Y']);
  assert.deepEqual(breadthPeriods(span(1480)), ['1M', '3M', '6M', '1Y', '3Y', '5Y']);   // a few weeks short of five years
  assert.deepEqual(breadthPeriods(span(900)), ['1M', '3M', '6M', '1Y', '3Y']);
  assert.deepEqual(breadthPeriods(null), ['1Y']);
});
