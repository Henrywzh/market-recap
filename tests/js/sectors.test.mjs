// SECTORS: the reading of the hub's artifact, tested on a small inline fixture.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/sectors-model.js';

const data = {
  as_of: '2026-10-12',
  sectors: [
    { key: 'XLP', label: 'Consumer Staples', weight: 4.9, sub_industries: ['XLP-SDNB', 'XLP-PFM'] },
    { key: 'XLF', label: 'Financials', weight: 11.5, sub_industries: [] },
  ],
  sub_industries: [
    { key: 'XLP-PFM', label: 'Packaged Foods & Meats', sector_key: 'XLP', weight: 2.0, members: 6, thin: false, theme: null },
    { key: 'XLP-SDNB', label: 'Soft Drinks & Non-alcoholic Beverages', sector_key: 'XLP', weight: 1.2, members: 4, thin: true, theme: null },
    { key: 'XLF-DB', label: 'Diversified Banks', sector_key: 'XLF', weight: 3.0, members: 5, thin: false, theme: 'banks' },
  ],
  members: [
    { ticker: 'KO', name: 'Coca-Cola Co', sector_key: 'XLP', sub_key: 'XLP-SDNB', weight: 0.5,
      returns: { '1M': 2.0, '3M': 8.7, '1Y': 10 }, drawdown: -3.2, above_200d: true, revision_90d: 0.9,
      forward_pe: 22.3, pe_percentile: 71, next_report: { date: '2026-10-21', timing: 'before_open' },
      monitor: { queued: true } },
    { ticker: 'GIS', name: 'General Mills', sector_key: 'XLP', sub_key: 'XLP-PFM', weight: 0.2,
      returns: { '1M': -4.0, '3M': -10.3, '1Y': null }, drawdown: -20, above_200d: false, revision_90d: null,
      forward_pe: null, pe_percentile: null, next_report: { date: '2026-11-02', timing: 'after_close' },
      monitor: { queued: false } },
    { ticker: 'PEP', name: 'PepsiCo', sector_key: 'XLP', sub_key: 'XLP-PFM', weight: 0.9,
      returns: { '1M': 1.0, '3M': 3.0, '1Y': 5 }, drawdown: -6, above_200d: null, revision_90d: 0.1,
      forward_pe: 19.0, pe_percentile: 40, next_report: { date: '2026-10-12', timing: 'scheduled' },
      monitor: null },
    { ticker: 'JPM', name: 'JPMorgan', sector_key: 'XLF', sub_key: 'XLF-DB', weight: 3.0,
      returns: { '1M': 5 }, drawdown: -2, above_200d: true, revision_90d: 1.5,
      forward_pe: 13.2, pe_percentile: 55, ptbv: 2.1, ptbv_percentile: 60,
      next_report: { date: '2026-10-14', timing: 'before_open' }, monitor: { queued: false } },
    { ticker: 'BAC', name: 'Bank of America', sector_key: 'XLF', sub_key: 'XLF-DB', weight: 1.0,
      returns: { '1M': 3 }, drawdown: -5, above_200d: false, revision_90d: 0.2,
      forward_pe: 11.0, pe_percentile: 30, ptbv: 1.4, ptbv_percentile: 25,
      next_report: { date: '2026-10-30', timing: 'after_close' }, monitor: { queued: false } },
    { ticker: 'WFC', name: 'Wells Fargo', sector_key: 'XLF', sub_key: 'XLF-DB', weight: 1.0,
      returns: { '1M': 2 }, drawdown: -9, above_200d: true, revision_90d: null,
      forward_pe: null, pe_percentile: null, ptbv: null, ptbv_percentile: null,
      next_report: { date: '2026-12-01', timing: 'before_open' }, monitor: { queued: false } },
  ],
};

test('the argument names the hub, a sector, a sub-industry, or nothing the build knows', () => {
  assert.equal(M.levelOf(null, data).level, 'hub');
  assert.equal(M.levelOf('', data).level, 'hub');
  const sector = M.levelOf('xlp', data);
  assert.equal(sector.level, 'sector');
  assert.equal(sector.sector.label, 'Consumer Staples');
  assert.equal(sector.sub, null);
  const sub = M.levelOf('XLP-SDNB', data);
  assert.equal(sub.level, 'sub');
  assert.equal(sub.sub.label, 'Soft Drinks & Non-alcoholic Beverages');
  assert.equal(sub.sector.key, 'XLP');
  assert.equal(M.levelOf('NOPE', data).level, 'unknown');
  assert.equal(M.levelOf('AAPL', data).level, 'unknown');
});

test('a sub-industry whose sector is missing still resolves, with no sector', () => {
  const orphan = { ...data, sectors: [] };
  const found = M.levelOf('XLP-SDNB', orphan);
  assert.equal(found.level, 'sub');
  assert.equal(found.sector, null);
});

test('sortRows puts a missing value last whichever way the column runs', () => {
  const rows = [{ v: 1 }, { v: null }, { v: 3 }, { v: undefined }, { v: 2 }];
  assert.deepEqual(M.sortRows(rows, 'v', 'desc').map((r) => r.v), [3, 2, 1, null, undefined]);
  assert.deepEqual(M.sortRows(rows, 'v', 'asc').map((r) => r.v), [1, 2, 3, null, undefined]);
});

test('sortRows sorts text by locale, accepts a reader function, and leaves the input alone', () => {
  const rows = [{ name: 'banana' }, { name: 'Apple' }, { name: 'cherry' }];
  const before = rows.map((r) => r.name);
  assert.deepEqual(M.sortRows(rows, 'name', 'asc').map((r) => r.name), ['Apple', 'banana', 'cherry']);
  assert.deepEqual(M.sortRows(rows, (r) => r.name.length, 'desc').map((r) => r.name).slice(0, 1), ['banana']);
  assert.deepEqual(rows.map((r) => r.name), before);
});

test('sortRows keeps ties in their order and treats an empty string as missing', () => {
  const rows = [{ k: 'a', v: 1 }, { k: 'b', v: 1 }, { k: 'c', v: '' }];
  assert.deepEqual(M.sortRows(rows, 'v', 'desc').map((r) => r.k), ['a', 'b', 'c']);
});

test('membersOf picks a sector or a sub-industry, heaviest first, and nothing else', () => {
  assert.deepEqual(M.membersOf(data, { sectorKey: 'XLP' }).map((m) => m.ticker), ['PEP', 'KO', 'GIS']);
  assert.deepEqual(M.membersOf(data, { subKey: 'XLP-SDNB' }).map((m) => m.ticker), ['KO']);
  assert.deepEqual(M.membersOf(data, { subKey: 'XLP-NONE' }), []);
});

test('subsOf lists a sector\'s sub-industries heaviest first', () => {
  assert.deepEqual(M.subsOf(data, 'XLP').map((s) => s.key), ['XLP-PFM', 'XLP-SDNB']);
  assert.deepEqual(M.subsOf(data, 'XLK'), []);
});

test('upcoming lists only reports after the session, within 42 days, soonest first', () => {
  const members = M.membersOf(data);
  const names = M.upcoming(members, data.as_of, M.REPORT_WINDOW_DAYS).map((m) => m.ticker);
  // PEP reports today (the session's own date) and is not upcoming; WFC is 50 days out.
  assert.deepEqual(names, ['JPM', 'KO', 'BAC', 'GIS']);
});

test('upcoming skips a name with no report date and a bad session date', () => {
  const members = [{ ticker: 'X', next_report: null }, { ticker: 'Y' }];
  assert.deepEqual(M.upcoming(members, '2026-10-12', 42), []);
  assert.deepEqual(M.upcoming(data.members, 'not a date', 42), []);
});

test('timing reads both the build\'s words and the short forms, and an unknown timing is null', () => {
  assert.equal(M.timingLabel('before_open'), 'BMO');
  assert.equal(M.timingLabel('bmo'), 'BMO');
  assert.equal(M.timingLabel('after_close'), 'AMC');
  assert.equal(M.timingLabel('amc'), 'AMC');
  assert.equal(M.timingLabel('scheduled'), 'TBC');
  assert.equal(M.timingLabel(null), null);
  assert.equal(M.timingLabel('whenever'), null);
  assert.match(M.timingTitle('before_open'), /before the open/);
  assert.equal(M.timingTitle(null), '');
});

test('a quadrant has a tag with its tone, and an unknown quadrant has none', () => {
  assert.deepEqual(M.quadrantTag('lagging'), { label: 'LAGGING', tone: 'down' });
  assert.deepEqual(M.quadrantTag('leading'), { label: 'LEADING', tone: 'up' });
  assert.equal(M.quadrantTag(null), null);
  assert.equal(M.quadrantTag('sideways'), null);
});

test('only evidence the build marks true shows a flag; null and false show none', () => {
  const flags = M.evidenceFlags({ sold_off: true, estimates_cut: false, cheap_vs_own_history: null });
  assert.deepEqual(flags.map((f) => f.text), ['SOLD OFF']);
  assert.equal(flags[0].tone, 'down');
  assert.deepEqual(M.evidenceFlags({ sold_off: true, estimates_cut: true, cheap_vs_own_history: true }).map((f) => f.text),
    ['SOLD OFF', 'EST CUT', 'P/E LOW']);
  assert.deepEqual(M.evidenceFlags(undefined), []);
});

test('the best and worst names over a period come from the names that have a return for it', () => {
  const members = M.membersOf(data, { sectorKey: 'XLP' });
  assert.deepEqual(M.extremesOf(members, '3M'), {
    best: { ticker: 'KO', return: 8.7 },
    worst: { ticker: 'GIS', return: -10.3 },
  });
  assert.deepEqual(M.extremesOf(members, 'YTD'), { best: null, worst: null });
  assert.deepEqual(M.extremesOf([], '3M'), { best: null, worst: null });
});

test('themedSubs names only the sub-industries that carry a THEMES group', () => {
  assert.deepEqual(M.themedSubs(data, 'XLF').map((s) => s.key), ['XLF-DB']);
  assert.deepEqual(M.themedSubs(data, 'XLP'), []);
});

test('ordinals read as the English do, eleven to thirteen as "th", a missing value as a dash', () => {
  const cases = { 1: '1st', 2: '2nd', 3: '3rd', 4: '4th', 11: '11th', 12: '12th', 13: '13th', 21: '21st', 22: '22nd', 101: '101st', 112: '112th' };
  for (const [n, text] of Object.entries(cases)) assert.equal(M.ordinal(Number(n)), text);
  assert.equal(M.ordinal(21.6), '22nd');
  assert.equal(M.ordinal(null), '—');
  assert.equal(M.ordinal(Number.NaN), '—');
});

test('a 200-day mark is a tick above, a cross below, and a dash when unknown', () => {
  assert.equal(M.boolMark(true), '✓');
  assert.equal(M.boolMark(false), '✗');
  assert.equal(M.boolMark(null), '—');
});

test('the names table orders its columns, and drops the sub-industry and P/TBV where they do not apply', () => {
  const sector = M.nameColumns('1M', { withSub: true, financials: false }).map((c) => c.key);
  assert.deepEqual(sector, ['ticker', 'name', 'sub', 'weight', 'ret', 'y1', 'high', 'a200', 'rev', 'pe', 'pctl', 'next', 'monitor']);
  const bank = M.nameColumns('3M', { withSub: false, financials: true }).map((c) => c.key);
  assert.deepEqual(bank, ['ticker', 'name', 'weight', 'ret', 'y1', 'high', 'a200', 'rev', 'pe', 'pctl', 'ptbv', 'ptbvPctl', 'next', 'monitor']);
  assert.equal(M.nameColumns('3M').find((c) => c.key === 'ret').label, '3M RETURN');
});

test('the name columns read the build\'s fields, and a missing field sorts last', () => {
  const cols = Object.fromEntries(M.nameColumns('3M', { financials: true }).map((c) => [c.key, c]));
  const ko = data.members[0];
  const gis = data.members[1];
  assert.equal(cols.ret.get(ko), 8.7);
  assert.equal(cols.y1.get(gis), null);
  assert.equal(cols.a200.get(ko), 1);
  assert.equal(cols.a200.get(gis), 0);
  assert.equal(cols.a200.get(data.members[2]), null);
  assert.equal(cols.monitor.get(ko), 1);
  assert.equal(cols.monitor.get(data.members[2]), null);
  assert.equal(cols.next.get(gis), '2026-11-02');
  assert.equal(cols.next.first, 'asc');
  // Percentile descending: the four with a value in order, then the two without (in input order).
  assert.deepEqual(M.sortRows(data.members, cols.pctl.get, 'desc').map((m) => m.ticker), ['KO', 'JPM', 'PEP', 'BAC', 'GIS', 'WFC']);
});

test('a page\'s valuation parts are passed on as they are; an older page with none gives nulls', () => {
  const valuation = { dates: ['2024-01-05'], pe: [20] };
  const parts = M.pageValuation({ valuation, outlook: { forward_pe: 21.5 }, history: { years: [2024] } });
  assert.equal(parts.valuation, valuation);
  assert.equal(parts.outlook.forward_pe, 21.5);
  assert.deepEqual(parts.history.years, [2024]);
  // An older build has no outlook or history: the block shows dashes for them.
  assert.deepEqual(M.pageValuation({ valuation }), { valuation, outlook: null, history: null });
  assert.deepEqual(M.pageValuation({}), { valuation: null, outlook: null, history: null });
  assert.equal(M.pageValuation(null), null);
  assert.equal(M.pageValuation(undefined), null);
});
