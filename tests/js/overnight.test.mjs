import test from 'node:test';
import assert from 'node:assert/strict';
import { rangePath } from '../../web/js/overnight-card.js';

const path = {
  dates: ['2015-10-09', '2020-10-09', '2021-10-11', '2026-10-09'],
  overnight: [1, 2, 4, 8], intraday: [1, 0.5, 0.5, 1], total: [1, 1, 2, 8],
};

test('a range keeps the last years of the path and rebases each leg to 1', () => {
  const five = rangePath(path, 5);
  assert.deepEqual(five.dates, ['2021-10-11', '2026-10-09']);
  assert.deepEqual(five.overnight, [1, 2]);
  assert.deepEqual(five.intraday, [1, 2]);
  assert.deepEqual(five.total, [1, 4]);
});

test('the whole path when no range is set, and an empty path stays empty', () => {
  assert.equal(rangePath(path, null).dates.length, 4);
  assert.deepEqual(rangePath({ dates: [], overnight: [], intraday: [], total: [] }, 1).dates, []);
});
