import { test } from 'node:test';
import assert from 'node:assert/strict';
import { withData, emptyNote } from '../../web/js/tabs/financials.js';

test('a series the filer never tagged is left out, and a chart with none left is blank with its reason', () => {
  const margins = { left: 'pct', right: null, bars: [], lines: [
    { name: 'Gross margin', data: [null, null] }, { name: 'Operating margin', data: [null, null] }, { name: 'Net margin', data: [30, 31] },
  ] };
  assert.deepEqual(withData(margins).lines.map((s) => s.name), ['Net margin']);
  const fcf = { left: 'money', right: 'pct', bars: [{ name: 'Free cash flow', data: [null] }],
    lines: [{ name: 'FCF margin', data: [null], axis: 1 }] };
  assert.equal(withData(fcf), null);
  assert.match(emptyNote(3, { sector: 'Financials' }), /bank or insurer/);
  assert.match(emptyNote(3, { sector: 'Industrials' }), /Not tagged/);
  // A right-hand axis goes when its only line does.
  const revenue = { left: 'money', right: 'pct', bars: [{ name: 'Revenue', data: [1] }], lines: [{ name: 'Revenue growth', data: [null], axis: 1 }] };
  assert.equal(withData(revenue).right, null);
});
