import { test } from 'node:test';
import assert from 'node:assert/strict';
import { linksOf, surpriseText } from '../../web/js/chain-card.js';

const chain = {
  edges: [
    { from: 'TSM', to: 'NVDA', type: 'supplies' },
    { from: 'NVDA', to: 'MSFT', type: 'supplies' },
    { from: 'NVDA', to: 'AMD', type: 'competes' },
    { from: 'AMD', to: 'NVDA', type: 'supplies' },
    { from: 'SNDK', to: 'KIOXIA', type: 'partner' },
  ],
};

test('a company\'s links read from its own side, a supply link before a rivalry', () => {
  const links = linksOf(chain, 'NVDA');
  assert.deepEqual(links.map((l) => [l.key, l.role]), [['AMD', 'supplier'], ['TSM', 'supplier'], ['MSFT', 'customer']]);
  assert.deepEqual(linksOf(chain, 'KIOXIA').map((l) => l.role), ['partner']);
});

test('a surprise past the study\'s clip is shown as a bound, not a size', () => {
  assert.equal(surpriseText(214.2), '≥+50%');
  assert.equal(surpriseText(-900), '≤−50%');
  assert.equal(surpriseText(null), '—');
  assert.equal(surpriseText(6.16), '+6.2%');
});
