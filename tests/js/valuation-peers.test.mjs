import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sectorRanks } from '../../web/js/tabs/valuation.js';

test('a row is ranked against its whole sector, so a search for one name keeps its rank', () => {
  const metrics = [{ key: 'pe', better: 'low' }];
  const peers = [
    { ticker: 'JPM', sector: 'Financials', pe: 14 },
    { ticker: 'BAC', sector: 'Financials', pe: 12 },
    { ticker: 'WFC', sector: 'Financials', pe: 10 },
  ];
  // Against all three, JPM has the highest multiple: the bottom of a lower-is-better rank.
  assert.equal(sectorRanks(peers, metrics).get(peers[0]).pe, 0);
  // Ranked against itself alone it would read as the middle: the old search fault.
  assert.equal(sectorRanks([peers[0]], metrics).get(peers[0]).pe, 0.5);
});
