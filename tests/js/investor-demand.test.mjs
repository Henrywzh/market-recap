import test from 'node:test';
import assert from 'node:assert/strict';
import { rolling4, signedBn, HOLDERS } from '../../web/js/investor-demand.js';

test('rolling four-quarter sums leave a gap where a quarter is missing', () => {
  assert.deepEqual(rolling4([1, 2, 3, 4, 5, null, 7, 8, 9, 10]), [null, null, null, 10, 14, null, null, null, null, 34]);
});

test('billions read as trillions past a thousand, with a true minus sign', () => {
  assert.equal(signedBn(350.49), '+$350.5B');
  assert.equal(signedBn(-1163.59), '−$1.16T');
  assert.equal(signedBn(null), '—');
});

test('every holder names a Z.1 history field', () => {
  assert.deepEqual(HOLDERS.map((h) => h.history), ['households', 'foreign', 'etfs', 'mutual_funds', 'pensions']);
});
