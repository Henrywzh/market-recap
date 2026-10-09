import { test } from 'node:test';
import assert from 'node:assert/strict';
import { slowestParts } from '../../web/js/timings.js';

test('the footer names the slowest parts of the build first', () => {
  const timings = { context: 95.2, panels: { events: 410.4, themes: 120, markets: 3.1 }, sec_check: 12, cache_prune: 0.4 };
  assert.equal(slowestParts(timings, 3), 'events 410s · themes 120s · prices & constituents 95s');
  assert.equal(slowestParts(undefined), null);
});
