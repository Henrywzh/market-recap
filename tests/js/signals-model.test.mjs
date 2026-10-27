// The ranked signal list on synthetic build items under node: the state rules, the
// severity and its order, the distance text for an oversold reading and a near watch,
// the age from days or from since and date, CLEARED last, and the muted-key storage.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  toSignals, rankSignals, stateOf, severityOf, ageOf, readMuted, writeMuted, MUTED_KEY,
} from '../../web/js/signals-model.js';

const item = (over) => ({
  key: 'k', kind: 'move', date: '2026-10-22', time: null, timing: null, subject: 'X', title: 'A title', detail: null,
  value: null, unit: null, z: null, importance: 'medium', new: true, since: null, days: null, evidence: 'description',
  link: '#catalysts', extra: {}, ...over,
});

const ROWS = [
  { symbol: 'SOXX', label: 'Semiconductors (SOXX)', short: 'Semis', group: 'sector', ret_pct: -6.79, share_pct: 0.5 },
  { symbol: 'XLP', label: 'Consumer staples (XLP)', short: 'Staples', group: 'sector', ret_pct: 3.3, share_pct: 0.4 },
];

const byKey = (signals) => Object.fromEntries(signals.map((s) => [s.key, s]));

test('the state rules: a watch reads its own state, an ended risk state is CLEARED, a continuing item is ONGOING, the rest NEW', () => {
  assert.equal(stateOf(item({ kind: 'watch', extra: { state: 'triggered' } })), 'TRIGGERED');
  assert.equal(stateOf(item({ kind: 'watch', extra: { state: 'near' } })), 'NEAR');
  assert.equal(stateOf(item({ kind: 'risk', extra: { active: false } })), 'CLEARED');
  assert.equal(stateOf(item({ kind: 'oversold', new: false })), 'ONGOING');
  assert.equal(stateOf(item({ kind: 'risk' }), { ongoing: true }), 'ONGOING', 'an item from the ongoing list is ONGOING');
  assert.equal(stateOf(item({ kind: 'tail' })), 'NEW');
  assert.equal(stateOf(item({ kind: 'watch', extra: { state: 'elsewhere' } })), 'NEW', 'an unknown watch state is left to the default');
});

test('severity: TRIGGERED 5; a hot NEW 4; NEW 3; NEAR 2; ONGOING 1; CLEARED 0', () => {
  assert.equal(severityOf('TRIGGERED'), 5);
  assert.equal(severityOf('NEW', true), 4);
  assert.equal(severityOf('NEW'), 3);
  assert.equal(severityOf('NEAR'), 2);
  assert.equal(severityOf('ONGOING'), 1);
  assert.equal(severityOf('CLEARED'), 0);
});

test('a risk state into stressed is severity 4; an elevated one is 3; an oversold at the 20 line is 4, at 30 is 3', () => {
  const unusual = {
    states: [
      item({ key: 'risk:A', kind: 'risk', subject: 'A', title: 'Cross-asset · technical: A is stressed', extra: { state: 'stressed' } }),
      item({ key: 'risk:B', kind: 'risk', subject: 'B', title: 'Treasuries · technical: B is elevated', extra: { state: 'elevated' } }),
    ],
    oversold: [
      item({ key: 'os:20', kind: 'oversold', subject: 'Semiconductors (SOXX)', value: 18, extra: { symbol: 'SOXX', rsi: 18, line: 20 } }),
      item({ key: 'os:30', kind: 'oversold', subject: 'Technology (XLK)', value: 28, extra: { symbol: 'XLK', rsi: 28, line: 30 } }),
    ],
  };
  const sig = byKey(toSignals(unusual, ROWS));
  assert.equal(sig['risk:A'].severity, 4);
  assert.equal(sig['risk:B'].severity, 3);
  assert.equal(sig['os:20'].severity, 4);
  assert.equal(sig['os:30'].severity, 3);
});

test('the list is sorted by severity, a tie goes to the rarer move, then to subject A-Z; CLEARED comes last', () => {
  const unusual = {
    tails: [
      item({ key: 'tail:common', kind: 'tail', subject: 'Zeta', value: 2, extra: { share_pct: 3 } }),
      item({ key: 'tail:rare', kind: 'tail', subject: 'Beta', value: 2, extra: { share_pct: 0.4 } }),
    ],
    ongoing: [item({ key: 'ongoing:A', kind: 'market_state', subject: 'Alpha', days: 30 })],
    states: [item({ key: 'risk:ended', kind: 'risk', subject: 'Ended', title: 'Cross-asset: Ended is calm', extra: { active: false } })],
    watch: [item({ key: 'watch:trig', kind: 'watch', subject: 'Buyback', extra: { state: 'triggered' } })],
  };
  const keys = toSignals(unusual, ROWS).map((s) => s.key);
  assert.deepEqual(keys, ['watch:trig', 'tail:rare', 'tail:common', 'ongoing:A', 'risk:ended'], 'severity, then rarity, then the rest');
  const ties = toSignals({ tails: [
    item({ key: 'b', kind: 'tail', subject: 'Beta', value: 1, extra: { share_pct: 1 } }),
    item({ key: 'a', kind: 'tail', subject: 'Alpha', value: 1, extra: { share_pct: 1 } }),
  ] }, ROWS).map((s) => s.subject);
  assert.deepEqual(ties, ['Alpha', 'Beta'], 'same severity and rarity: subject A-Z');
  const cleared = toSignals({ states: [item({ key: 'end', kind: 'risk', extra: { active: false } })] }, ROWS);
  assert.equal(cleared[0].severity, 0);
  assert.equal(rankSignals([{ key: 'z', severity: 0, rarity: null, subject: 'A' }, { key: 'y', severity: 1, rarity: null, subject: 'B' }])[0].key, 'y');
});

test('distance: an oversold reading is its gap below the line; a near watch is its gap to the trigger; others have none', () => {
  const unusual = {
    oversold: [item({ key: 'os', kind: 'oversold', subject: 'Semiconductors (SOXX)', value: 24.1, extra: { symbol: 'SOXX', rsi: 24.1, line: 30 } })],
    watch: [
      item({ key: 'near', kind: 'watch', subject: 'Oil supply shock', value: 113, unit: null, extra: { state: 'near', value: 113, threshold: 120, op: 'above' } }),
      item({ key: 'trig', kind: 'watch', subject: 'Buyback', extra: { state: 'triggered' } }),
    ],
  };
  const sig = byKey(toSignals(unusual, ROWS));
  assert.equal(sig.os.distance, 'RSI 24.1 · 5.9 below 30');
  assert.equal(sig.near.distance, 'needs 7.0 more to 120');
  assert.equal(sig.trig.distance, null, 'a triggered scenario has no gap to close');
});

test('distance is null where it cannot be computed: no line, no value, or a reading not below its line', () => {
  const sig = byKey(toSignals({ oversold: [
    item({ key: 'noline', kind: 'oversold', subject: 'Tech', value: 25, extra: { rsi: 25 } }),
    item({ key: 'above', kind: 'oversold', subject: 'Tech', value: 35, extra: { rsi: 35, line: 30 } }),
  ] }, []));
  assert.equal(sig.noline.distance, null);
  assert.equal(sig.above.distance, null);
});

test('age: the build\'s days when it has them; else since to date, counted inclusively; null when neither', () => {
  assert.equal(ageOf(item({ days: 3 })), 3);
  assert.equal(ageOf(item({ since: '2026-10-20', date: '2026-10-22' })), 3, 'two days after since is day 3');
  assert.equal(ageOf(item({ since: '2026-10-22', date: '2026-10-22' })), 1, 'a signal that began today is day 1');
  assert.equal(ageOf(item({ since: '2026-10-25', date: '2026-10-22' })), null, 'since after date is not an age');
  assert.equal(ageOf(item({ since: null, date: '2026-10-22' })), null);
  assert.equal(ageOf(item({})), null);
  const sig = byKey(toSignals({ oversold: [item({ key: 'os', kind: 'oversold', since: '2026-10-20', date: '2026-10-22', extra: { rsi: 20, line: 30 } })] }, []));
  assert.equal(sig.os.age, 3);
});

test('each signal carries its key, group, text, title, href, tone and rarity; ETF flows are one NEW line at severity 1, keyed by date', () => {
  const unusual = {
    oversold: [item({ key: 'oversold:Semis:2026-10-22', kind: 'oversold', subject: 'Semiconductors (SOXX)', title: 'Semis oversold', detail: 'How stretched.', link: '#technicals/SOXX', value: 20.4, extra: { symbol: 'SOXX', rsi: 20.4, line: 20 } })],
    tails: [item({ key: 'tail:XLP', kind: 'tail', subject: 'Consumer staples (XLP)', value: 3.3, unit: '%', detail: 'Rare.', extra: { symbol: 'XLP', share_pct: 0.4 } })],
  };
  const flows = { date: '2026-10-22', us_equity_1w: -11.38e9, us_equity_1w_pct_rank: 11, top_in: [['SOXX', 4.39e9]], top_out: [] };
  const list = toSignals(unusual, ROWS, flows);
  const os = byKey(list)['oversold:Semis:2026-10-22'];
  assert.equal(os.group, 'OVERSOLD');
  assert.equal(os.text, 'Semis 20.4');
  assert.equal(os.title, 'How stretched.');
  assert.equal(os.href, '#technicals/SOXX');
  assert.equal(os.tone, 'down');
  assert.equal(os.state, 'NEW');
  assert.equal(os.severity, 4);
  assert.equal(os.rarity, null);
  const tail = byKey(list)['tail:XLP'];
  assert.equal(tail.text, 'Staples +3.3% · 0.4%');
  assert.equal(tail.href, '#movecheck/XLP');
  assert.equal(tail.rarity, 0.4);
  // The week's flows are one line: the total, then the funds in and out.
  const flowRows = list.filter((s) => s.group === 'ETF FLOWS');
  assert.equal(flowRows.length, 1);
  const flow = flowRows[0];
  assert.equal(flow.key, 'flows:2026-10-22');
  assert.equal(flow.state, 'NEW');
  assert.equal(flow.severity, 1);
  assert.equal(flow.text, 'US equity 1W −$11.4bn · 11th pct · SOXX +$4.4bn');
  assert.equal(flow.age, null);
});

test('an ONGOING signal reads its subject with the sessions count, and is severity 1', () => {
  const [sig] = toSignals({ ongoing: [item({ key: 'ongoing:SMALL', kind: 'market_state', subject: 'SMALL CAPS LAGGING', days: 30 })] }, []);
  assert.equal(sig.text, 'SMALL CAPS LAGGING · 30 sessions');
  assert.equal(sig.state, 'ONGOING');
  assert.equal(sig.severity, 1);
  assert.equal(sig.group, 'ONGOING');
});

test('a missing key falls back to the group, subject and date; an empty input gives an empty list', () => {
  const [sig] = toSignals({ ongoing: [item({ key: undefined, subject: 'Buyback', date: '2026-10-22' })] }, []);
  assert.equal(sig.key, 'ONGOING:Buyback:2026-10-22');
  assert.deepEqual(toSignals(undefined, undefined, undefined), []);
  assert.deepEqual(toSignals({}, [], null), []);
});

test('the muted keys are read and written through storage; a blocked storage gives none and keeps nothing', () => {
  const store = new Map();
  const storage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) };
  assert.deepEqual(readMuted(storage), [], 'nothing stored yet');
  assert.equal(writeMuted(storage, ['a', 'a', 'b']), true);
  assert.equal(store.get(MUTED_KEY), '["a","b"]', 'stored once per key');
  assert.deepEqual(readMuted(storage), ['a', 'b']);
  store.set(MUTED_KEY, '{not json');
  assert.deepEqual(readMuted(storage), [], 'a damaged value is no mutes');
  store.set(MUTED_KEY, '[1, "ok"]');
  assert.deepEqual(readMuted(storage), ['ok'], 'only text keys count');
  const blocked = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  assert.deepEqual(readMuted(blocked), []);
  assert.equal(writeMuted(blocked, ['a']), false, 'the page keeps the mute for the session only');
  assert.equal(writeMuted(undefined, ['a']), false);
  assert.deepEqual(readMuted(undefined), []);
});

test('an ONGOING line is tagged by its kind, not by the word its badge already shows', () => {
  const list = toSignals({ ongoing: [item({ key: 'risk:corr', kind: 'risk', subject: 'STOCK–BOND CORR 3M', value: 0.41, unit: 'corr', new: false })] }, ROWS, null);
  assert.equal(list[0].state, 'ONGOING');
  assert.equal(list[0].tag, 'RISK');
  assert.equal(list[0].group, 'ONGOING');
});
