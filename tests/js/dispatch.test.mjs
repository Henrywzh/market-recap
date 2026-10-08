// The cron Worker that starts the refresh on time.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { editionAt, dispatch } from '../../workers/dispatch/src/index.js';

const at = (iso) => Date.parse(iso);

test('each cron firing stands for an edition only at 16:20 or 18:35 in New York', () => {
  // Summer (EDT, UTC-4): 20:20 and 22:35 UTC.
  assert.equal(editionAt(at('2026-10-08T20:20:00Z')), 'close');
  assert.equal(editionAt(at('2026-10-08T21:20:00Z')), null);
  assert.equal(editionAt(at('2026-10-08T22:35:00Z')), 'evening');
  assert.equal(editionAt(at('2026-10-08T23:35:00Z')), null);
  // Winter (EST, UTC-5): 21:20 and 23:35 UTC.
  assert.equal(editionAt(at('2026-12-08T20:20:00Z')), null);
  assert.equal(editionAt(at('2026-12-08T21:20:00Z')), 'close');
  assert.equal(editionAt(at('2026-12-08T23:35:00Z')), 'evening');
});

test('a dispatch names the edition, retries a server error and stops at a refusal', async () => {
  const env = { REPO: 'o/r', WORKFLOW: 'refresh.yml', GITHUB_TOKEN: 't' };
  const calls = [];
  const answers = [503, 204];
  const ok = await dispatch(env, 'close', async (url, init) => {
    calls.push([url, JSON.parse(init.body)]);
    return new Response(null, { status: answers.shift() });
  });
  assert.equal(ok.ok, true);
  assert.equal(calls.length, 2);
  assert.equal(calls[0][0], 'https://api.github.com/repos/o/r/actions/workflows/refresh.yml/dispatches');
  assert.deepEqual(calls[0][1], { ref: 'main', inputs: { deploy: 'true', edition: 'close' } });
  let tries = 0;
  const refused = await dispatch(env, 'evening', async () => { tries += 1; return new Response('Bad credentials', { status: 401 }); });
  assert.equal(refused.status, 401);
  assert.equal(tries, 1);
});
