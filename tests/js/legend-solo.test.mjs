import test from 'node:test';
import assert from 'node:assert/strict';
import { soloAction } from '../../web/js/charts.js';

test('a legend double click shows only that entry, and on the entry already alone shows them all', () => {
  assert.deepEqual(soloAction({ A: true, B: true, C: false }, 'B'), { show: ['B'], hide: ['A', 'C'] });
  assert.deepEqual(soloAction({ A: false, B: true, C: false }, 'B'), { show: ['A', 'B', 'C'], hide: [] });
  // A hidden entry double-clicked is shown alone.
  assert.deepEqual(soloAction({ A: true, B: false }, 'B'), { show: ['B'], hide: ['A'] });
});
