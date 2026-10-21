// CATALYSTS: the calendar's reporters show two at a time; the rest fold under "N more reporting".
import test from 'node:test';
import assert from 'node:assert/strict';
import { splitRows } from '../../web/js/tabs/catalysts.js';

test('the first two upcoming reporters show, and the rest fold', () => {
  assert.deepEqual(splitRows(['a', 'b', 'c', 'd', 'e']), { shown: ['a', 'b'], folded: ['c', 'd', 'e'] });
});

test('a short list folds nothing, and a missing list is empty', () => {
  assert.deepEqual(splitRows(['a']), { shown: ['a'], folded: [] });
  assert.deepEqual(splitRows([]), { shown: [], folded: [] });
  assert.deepEqual(splitRows(undefined), { shown: [], folded: [] });
});

test('the split size can be set', () => {
  assert.deepEqual(splitRows([1, 2, 3], 1), { shown: [1], folded: [2, 3] });
});

test('earnings cards from another build are labelled with their date, not hidden', async () => {
  const { leadDateNote } = await import('../../web/js/tabs/catalysts.js');
  assert.equal(leadDateNote('2026-10-20', '2026-10-20'), null);
  assert.equal(leadDateNote(null, '2026-10-20'), null);
  assert.match(leadDateNote('2026-10-19', '2026-10-20'), /as of 2026-10-19.*older/);
  assert.match(leadDateNote('2026-10-21', '2026-10-20'), /calendar is the older file/);
});

test('reports traded in the build session are open; the earlier ones fold under the last N sessions', async () => {
  const { splitReported } = await import('../../web/js/tabs/catalysts.js');
  const rows = [
    { symbol: 'GE', outcome: { sessions_since: 0 } },
    { symbol: 'IBM', outcome: { sessions_since: 2 } },
    { symbol: 'MS', outcome: { sessions_since: 9 } },
  ];
  const split = splitReported(rows);
  assert.deepEqual(split.just.map((r) => r.symbol), ['GE']);
  assert.deepEqual(split.earlier.map((r) => r.symbol), ['IBM', 'MS']);
  assert.equal(split.sessions, 10, 'ten sessions unless the build says otherwise');
  assert.equal(splitReported(rows, 5).sessions, 5);
  assert.deepEqual(splitReported(undefined), { just: [], earlier: [], sessions: 10 });
});

test('the next session is the earliest reaction day; its reports come first, heaviest index impact first', async () => {
  const { splitUpcoming } = await import('../../web/js/tabs/catalysts.js');
  const card = (day, pts, weight) => ({ card: { reaction_session: day, impact: { indices: { SPX: { points_pct: pts, weight } } } } });
  const upcoming = [
    { symbol: 'AAA', ...card('2026-10-23', 0.5, 1) },
    { symbol: 'BBB', ...card('2026-10-22', 0.1, 2) },
    { symbol: 'CCC', ...card('2026-10-22', 0.4, 0.3) },
    { symbol: 'DDD', ...card('2026-10-22', 0.4, 0.9) },
    { symbol: 'EEE', card: { reaction_session: null } },
  ];
  const { next, rest } = splitUpcoming(upcoming);
  assert.deepEqual(next.map((p) => p.symbol), ['DDD', 'CCC', 'BBB'], 'impact, then weight');
  assert.deepEqual(rest.map((p) => p.symbol), ['AAA', 'EEE'], 'the rest keep their order');
  assert.deepEqual(splitUpcoming([{ symbol: 'X' }]), { next: [], rest: [{ symbol: 'X' }] });
  assert.deepEqual(splitUpcoming(undefined), { next: [], rest: [] });
});
