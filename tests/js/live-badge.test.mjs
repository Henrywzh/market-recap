// The LIVE mark: shown on a live block only while the session is open and the
// last fetch answered; closed, failed or not yet asked shows no mark.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isLive } from '../../web/js/live-feed.js';

test('a block is live only on a fresh answer while the regular session is open', () => {
  assert.equal(isLive({ body: { session: { open: true } }, error: null }), true);
  assert.equal(isLive({ body: { session: { open: false } }, error: null }), false);
  assert.equal(isLive({ body: { session: { open: true } }, error: 'HTTP 503' }), false);
  assert.equal(isLive({ body: null, error: null }), false);
  assert.equal(isLive(undefined), false);
});
