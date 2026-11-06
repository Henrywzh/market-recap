import { test } from 'node:test';
import assert from 'node:assert/strict';
import { members, bins, summary, labelRows, verdict } from '../../web/js/day-spread-model.js';

const C = [
  { ticker: 'NVDA', weight: 8, returns: { '1D': -9 } },
  { ticker: 'AAPL', weight: 7, returns: { '1D': -1.5 } },
  { ticker: 'BRK.B', weight: 2, returns: { '1D': 0.5 } },
  { ticker: 'XOM', weight: 1, returns: { '1D': 1.2 } },
  { ticker: 'KO', weight: 1, returns: { '1D': 0.3 } },
  { ticker: 'GONE', weight: 0.5, returns: { '1D': null } },
];

test('members keep a move or are counted missing; live quotes match BRK.B to BRK-B', () => {
  const close = members(C);
  assert.equal(close.members.length, 5);
  assert.equal(close.missing, 1);
  const live = members(C, new Map([['NVDA', { change_pct: -5 }], ['BRK-B', { change_pct: 1 }]]));
  assert.deepEqual(live.members.map((m) => [m.ticker, m.ret]), [['NVDA', -5], ['BRK.B', 1]]);
  assert.equal(live.missing, 4);
});

test('bins have 0 as an edge and the end bins take everything past the clip', () => {
  const list = members(C).members;
  const out = bins(list, { width: 0.5, clip: 4 });
  assert.equal(out.bins.length, 16);
  assert.ok(out.bins.some((b) => b.lo === 0));
  assert.equal(out.bins[0].count, 1, 'NVDA −9% sits in the first bin');
  assert.equal(out.bins.reduce((a, b) => a + b.count, 0), 5);
  const kos = out.bins.find((b) => b.lo === 0);
  assert.deepEqual(kos.names.map((m) => m.ticker), ['KO']);
});

test('the summary splits the weighted move into the heavy names and the rest', () => {
  const s = summary(members(C).members, { top: 2 });
  assert.equal(s.up, 3);
  assert.equal(s.down, 2);
  assert.equal(s.median, 0.3);
  const weighted = (8 * -9 + 7 * -1.5 + 2 * 0.5 + 1.2 + 0.3) / 19;
  assert.ok(Math.abs(s.weighted - weighted) < 1e-12);
  assert.ok(Math.abs(s.heavy_part + s.rest_part - s.weighted) < 1e-12);
  assert.deepEqual(s.heavy.map((m) => m.ticker), ['NVDA', 'AAPL']);
  assert.match(verdict(s), /did worse than its typical member by 4\.5 points/);
});

test('labels close together go to separate rows', () => {
  const rows = labelRows([{ ticker: 'A', ret: -1 }, { ticker: 'B', ret: -0.9 }, { ticker: 'C', ret: 2 }], 0.75);
  assert.deepEqual(rows.map((m) => [m.ticker, m.row]), [['A', 0], ['B', 1], ['C', 0]]);
});
