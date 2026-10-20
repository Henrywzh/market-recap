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
