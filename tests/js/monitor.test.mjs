import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  FOLLOW_STORAGE_KEY,
  MONITOR_STATUSES,
  deriveHistoryStatus,
  loadFollowState,
  mergeFollowLists,
  normalizeObservedHistory,
  parseFollowImport,
  saveFollowState,
  serializeFollowList,
} from '../../web/js/monitor-model.js';

const history = (...values) => values.map(([date, drawdown]) => [date, drawdown]);

class MemoryStorage {
  constructor() { this.values = new Map(); }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) { this.values.set(key, String(value)); }
}

test('the first qualifying observation is a baseline, not a false historical new entry', () => {
  const view = deriveHistoryStatus(history(['2026-09-22', -20.0]), 20);
  assert.equal(view.status, MONITOR_STATUSES.BASELINE);
  assert.equal(view.firstObserved, '2026-09-22');
  assert.equal(view.previousDate, null);
});

test('pool qualification is derived at the selected threshold from the same history', () => {
  const observations = history(['2026-09-22', -21]);
  assert.equal(deriveHistoryStatus(observations, 20).status, MONITOR_STATUSES.BASELINE);
  assert.equal(deriveHistoryStatus(observations, 25).status, MONITOR_STATUSES.OUTSIDE);
});

test('changes name the previous observed date when whole builds are missing', () => {
  const entered = deriveHistoryStatus(history(
    ['2026-09-18', -12],
    ['2026-09-22', -21],
  ), 20);
  assert.equal(entered.status, MONITOR_STATUSES.NEWLY_ENTERED);
  assert.equal(entered.previousDate, '2026-09-18');

  const exited = deriveHistoryStatus(history(
    ['2026-09-18', -12],
    ['2026-09-22', -21],
    ['2026-09-23', -5],
  ), 20);
  assert.equal(exited.status, MONITOR_STATUSES.EXITED);
  assert.equal(exited.previousDate, '2026-09-22');
});

test('null observations and unknown gaps never imply an exit', () => {
  const currentGap = deriveHistoryStatus(history(
    ['2026-09-18', -21],
    ['2026-09-22', null],
  ), 20);
  assert.equal(currentGap.status, MONITOR_STATUSES.UNKNOWN);

  const outsideAfterGap = deriveHistoryStatus(history(
    ['2026-09-18', -21],
    ['2026-09-22', null],
    ['2026-09-23', -5],
  ), 20);
  assert.equal(outsideAfterGap.status, MONITOR_STATUSES.OUTSIDE);
  assert.notEqual(outsideAfterGap.status, MONITOR_STATUSES.EXITED);

  const qualifyingAfterGap = deriveHistoryStatus(history(
    ['2026-09-18', -21],
    ['2026-09-22', null],
    ['2026-09-23', -22],
  ), 20);
  assert.equal(qualifyingAfterGap.status, MONITOR_STATUSES.CONTINUING);
});

test('same-day history replaces the earlier print and impossible dates are ignored', () => {
  assert.deepEqual(
    normalizeObservedHistory(history(
      ['2026-02-30', -40],
      ['2026-09-22', -10],
      ['2026-09-22', -21],
    )),
    [['2026-09-22', -21]],
  );
  assert.equal(
    deriveHistoryStatus(history(['2026-09-22', -10], ['2026-09-22', -21]), 20).status,
    MONITOR_STATUSES.BASELINE,
  );
});

test('a stale last observation is unknown rather than a carried-forward value', () => {
  const view = deriveHistoryStatus(history(['2026-09-21', -30]), 20, { asOf: '2026-09-22' });
  assert.equal(view.status, MONITOR_STATUSES.UNKNOWN);
  assert.equal(view.stale, true);
  assert.equal(view.currentValue, null);
});

test('follow persistence is browser-local, import is validated, and merge is non-destructive', () => {
  const storage = new MemoryStorage();
  const empty = loadFollowState(storage, FOLLOW_STORAGE_KEY);
  assert.equal(empty.status, 'ok');
  assert.deepEqual(empty.tickers, []);

  const saved = saveFollowState(storage, FOLLOW_STORAGE_KEY, ['msft', 'AAPL']);
  assert.equal(saved.ok, true);
  assert.deepEqual(loadFollowState(storage, FOLLOW_STORAGE_KEY).tickers, ['AAPL', 'MSFT']);

  const imported = parseFollowImport(serializeFollowList(['NVDA'], '2026-09-22T12:00:00.000Z'));
  assert.deepEqual(imported, { ok: true, tickers: ['NVDA'] });
  assert.deepEqual(mergeFollowLists(['AAPL', 'MSFT'], imported.tickers), ['AAPL', 'MSFT', 'NVDA']);
  assert.equal(parseFollowImport('{"tickers":["BAD/SYMBOL"]}').ok, false);
  assert.equal(parseFollowImport('{"tickers":["AAPL"],"exported_at":"2026-02-30T12:00:00Z"}').ok, false);
});

test('corrupt saved follow data is not silently replaced', () => {
  const storage = new MemoryStorage();
  storage.setItem(FOLLOW_STORAGE_KEY, '{not-json');
  const before = storage.getItem(FOLLOW_STORAGE_KEY);
  const loaded = loadFollowState(storage, FOLLOW_STORAGE_KEY);
  assert.equal(loaded.status, 'corrupt');

  const blocked = saveFollowState(storage, FOLLOW_STORAGE_KEY, ['AAPL']);
  assert.equal(blocked.ok, false);
  assert.equal(blocked.status, 'corrupt');
  assert.equal(storage.getItem(FOLLOW_STORAGE_KEY), before);

  const repaired = saveFollowState(storage, FOLLOW_STORAGE_KEY, ['AAPL'], { allowRepair: true });
  assert.equal(repaired.ok, true);
  assert.deepEqual(loadFollowState(storage, FOLLOW_STORAGE_KEY).tickers, ['AAPL']);
});

import { inQueue, quadrantOf, logChanges, todayChanges } from '../../web/js/monitor-model.js';

test('the queue is drawdown at the selected threshold or lagging peers, minus exclusions', () => {
  assert.equal(inQueue({ currentQualifies: true, row: { reasons: ['drawdown'] } }), true);
  assert.equal(inQueue({ currentQualifies: false, row: { reasons: ['peer_laggard'] } }), true);
  assert.equal(inQueue({ currentQualifies: false, row: { reasons: [] } }), false);
  assert.equal(inQueue({ currentQualifies: true, row: { note: { status: 'exclude' } } }), false);
  assert.equal(inQueue({ currentQualifies: true, row: { membership: 'removed' } }), false);
});

test('the 2x2 needs a price state and treats unknown evidence as not steady', () => {
  assert.equal(quadrantOf({ price_state: 'weak', evidence_state: 'steady' }), 'weak-steady');
  assert.equal(quadrantOf({ price_state: 'stabilising', evidence_state: 'unknown' }), 'stabilising-other');
  assert.equal(quadrantOf({ price_state: null, evidence_state: 'steady' }), null);
});

test('followed names get their own transitions; excluded names are dropped from today', () => {
  const data = {
    as_of: '2026-09-23',
    changes: [{ ticker: 'EXC', kind: 'entered', text: 'x' }, { ticker: 'AAA', kind: 'entered', text: 'y' }],
    rows: [
      { ticker: 'EXC', note: { status: 'exclude' } },
      { ticker: 'AAA' },
      { ticker: 'FOL', evidence_against: ['cut'], state_log: [
        ['2026-09-20', false, 'weak', 'steady'], ['2026-09-23', false, 'stabilising', 'deteriorating']] },
      { ticker: 'OLD', state_log: [['2026-09-20', false, 'weak', null], ['2026-09-22', false, 'stabilising', null]] },
    ],
  };
  const groups = todayChanges(data, ['FOL', 'OLD']);
  assert.deepEqual(groups.map((g) => g.kind), ['entered', 'stabilising', 'evidence_down']);
  assert.deepEqual(groups[0].items.map((c) => c.ticker), ['AAA']);
  assert.equal(groups[2].items[0].text, 'cut');
  assert.deepEqual(logChanges(data.rows[3], '2026-09-23'), []);
  // Against a state logged before the price rule took effect, a flip is the rule, not a move.
  const relabelled = todayChanges({ ...data, settings: { price_rule_since: '2026-09-23' } }, ['FOL']);
  assert.deepEqual(relabelled.map((g) => g.kind), ['entered', 'evidence_down']);
});
