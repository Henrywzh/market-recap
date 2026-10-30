import test from 'node:test';
import assert from 'node:assert/strict';
import { regimeName } from '../../web/js/macro-regime.js';

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
});
