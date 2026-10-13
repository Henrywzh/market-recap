import test from 'node:test';
import assert from 'node:assert/strict';
import { lastOf, trimHistory, stripCells, companyBasket } from '../../web/js/valuation-block.js';

const history = { years: [2023, 2024, 2025, 2026], revenue_growth: [null, 6.2, 14.6, null], gross_margin: [47, 50, 52, null], operating_margin: [21, 23, 27, null] };

test('a half-reported fiscal year is dropped from the end', () => {
  assert.deepEqual(trimHistory(history).years, [2023, 2024, 2025]);
  assert.deepEqual(lastOf(history, 'operating_margin'), { year: 2025, value: 27 });
  assert.equal(trimHistory({ years: [2025], revenue_growth: [null], gross_margin: [null], operating_margin: [null] }), null);
});

test('the strip sets each figure beside the benchmark', () => {
  const own = { valuation: { stats: { current: 36.5, percentile: 62, median: 32.8 } }, outlook: { forward_pe: 20.5, eps_growth_next: 32.2, revenue_growth: 31.2 }, history };
  const other = { outlook: { forward_pe: 19.6, eps_growth_next: 14.2, revenue_growth: 12.8 }, history: { years: [2025], revenue_growth: [7], gross_margin: [null], operating_margin: [16.3] } };
  const cells = stripCells('Info Tech', 'S&P 500', own, other);
  assert.equal(cells[0].value, '36.5×');
  assert.match(cells[1].note, /5% premium · vs S&P 500/);
  assert.equal(cells[4].label, 'OPERATING MARGIN · FY2025');
  assert.equal(cells[4].value, '27.0% vs 16.3%');
  assert.equal(stripCells('X', null, {}, null)[1].value, '—');
});

test('one company is read as a basket of itself', () => {
  const b = companyBasket({ dates: ['a', 'b'], pe: [20, null], close: [100, 110], stats: { median: 1 } });
  assert.deepEqual(b.earnings, [5, null]);
  assert.equal(companyBasket({ dates: [] }), null);
});
