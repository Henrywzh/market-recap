import test from 'node:test';
import assert from 'node:assert/strict';
import { regimeName, regimeViews, regimeAgreement } from '../../web/js/macro-regime.js';

test('four quadrants describe growth relative to trend and inflation direction', () => {
  assert.equal(regimeName(-.1, .2), 'STAGFLATION');
  assert.equal(regimeName(.1, .2), 'REFLATION');
  assert.equal(regimeName(-.1, -.2), 'SLOWDOWN');
  assert.equal(regimeName(.1, -.2), 'GOLDILOCKS');
  assert.equal(regimeName(0, -.2), 'ON THE BOUNDARY');
  assert.equal(regimeName(null, .2), null);
});

test('macro agenda includes policy, orders by date/time and retains source importance', async () => {
  const { macroCalendarEvents } = await import('../../web/js/macro-regime.js');
  const event = (title, date, time, category, importance) => ({ title, date, time, category, importance, lane: 'macro' });
  const source = { as_of: '2026-10-23', events: [
    event('PCE', '2026-10-29', '08:30', 'macro_data', 'low'),
    event('Fed conference', '2026-10-28', '14:30', 'monetary_policy', 'high'),
    event('Fed decision', '2026-10-28', '14:00', 'monetary_policy', 'high'),
    event('Old CPI', '2026-10-22', '08:30', 'macro_data', 'high'),
    event('Auction', '2026-10-28', '13:00', 'fiscal_treasury', 'medium'),
  ] };
  assert.deepEqual(macroCalendarEvents(source).map(e => e.title), ['Fed decision', 'Fed conference', 'PCE']);
  assert.deepEqual(macroCalendarEvents(source, true).map(e => e.title), ['Fed decision', 'Fed conference']);
  assert.equal(source.events[0].importance, 'low');
  assert.deepEqual(macroCalendarEvents(null), []);
  // A two-week window ends on the snapshot date plus 14 days, inclusive.
  const later = { as_of: '2026-10-23', events: [event('In', '2026-11-06', '08:30', 'macro_data', 'high'),
    event('Out', '2026-11-07', '08:30', 'macro_data', 'high')] };
  assert.deepEqual(macroCalendarEvents(later, false, 14).map(e => e.title), ['In']);
  assert.deepEqual(macroCalendarEvents(later).map(e => e.title), ['In', 'Out']);
});

test('nowcast ledger shows one row per month, its last reading, newest month first', async () => {
  const { nowcastLedgerRows } = await import('../../web/js/macro-regime.js');
  const rows = nowcastLedgerRows([
    { date: '2026-10-29', month: '2026-10', quadrant: 'SLOWDOWN' },
    { date: '2026-10-30', month: '2026-10', quadrant: 'REFLATION' },
    { date: '2026-11-02', month: '2026-11', quadrant: 'GOLDILOCKS' },
  ]);
  assert.deepEqual(rows.map(r => [r.month, r.quadrant]), [['2026-11', 'GOLDILOCKS'], ['2026-10', 'REFLATION']]);
  assert.deepEqual(nowcastLedgerRows(null), []);
});

test('the real-time view splits month-end reads from the still-moving ledger month, and agreement counts shared months', () => {
  const regime = { points: [{ month: '2026-08', growth: 0.1, inflation_change_pp: 0.1 }, { month: '2026-09', growth: 0.05, inflation_change_pp: 0.08 }] };
  const now = { points: [{ month: '2026-10', growth: 0.07, inflation_change_pp: 0.2 }] };
  const realtime = { points: [
    { month: '2026-08', growth: 0.2, inflation_change_pp: 0.1, source: 'archive' },
    { month: '2026-09', growth: -0.03, inflation_change_pp: -0.02, source: 'archive' },
    { month: '2026-10', growth: 0.07, inflation_change_pp: 0.21, source: 'ledger' },
    { month: '2026-11', growth: null, inflation_change_pp: 0.1, source: 'ledger' }] };
  const views = regimeViews(regime, now, realtime);
  assert.deepEqual(views.realtime.points.map((p) => p.month), ['2026-08', '2026-09']);
  assert.deepEqual(views.realtime.now.map((p) => p.month), ['2026-10']);
  assert.equal(views.official.now.length, 1);
  assert.deepEqual(regimeAgreement(views), { months: 2, same: 1 });
  assert.deepEqual(regimeAgreement(regimeViews(regime, now, null)), { months: 0, same: 0 });
});
