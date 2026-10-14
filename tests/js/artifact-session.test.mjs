import { test } from 'node:test';
import assert from 'node:assert/strict';
import { monitorSession } from '../../web/js/artifact-session.js';

test('a partial build allows a same-session monitor without claiming it was rebuilt', () => {
  assert.deepEqual(monitorSession({ as_of: '2026-10-12' }, { as_of: '2026-10-12', panels: ['catalysts'], errors: {} }), { ok: true, partial: true });
});
test('monitor rejects stale, undated or failed-build artifacts', () => {
  assert.equal(monitorSession({ as_of: '2026-10-09' }, { as_of: '2026-10-12', panels: ['monitor'] }).ok, false);
  assert.equal(monitorSession({}, { as_of: '2026-10-12' }).ok, false);
  assert.equal(monitorSession({ as_of: '2026-10-12', unavailable: 'missing measurements' }, { as_of: '2026-10-12' }).ok, false);
  assert.equal(monitorSession({ as_of: '2026-10-12' }, { as_of: '2026-10-12', errors: { monitor: 'failed' } }).ok, false);
});
