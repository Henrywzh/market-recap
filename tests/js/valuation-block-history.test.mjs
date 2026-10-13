import test from 'node:test';
import assert from 'node:assert/strict';
import { companyHistory } from '../../web/js/valuation-block.js';

test('a company\'s filings become growth and margins by fiscal year, with the gross and operating fallbacks', () => {
  const history = companyHistory({
    columns: [{ fiscal_year: 2021 }, { fiscal_year: 2022 }, { fiscal_year: 2023 }, { fiscal_year: 2024 }],
    values: {
      revenue: [100, 110, null, 130],
      gross_profit: [null, 60, 66, null],
      cost_of_revenue: [50, 55, 60, 70],
      ebit: [10, null, 20, null],
      pretax_income: [11, 12, 13, 14],
    },
  });
  // Gross falls back to revenue less cost where no gross line is filed; operating
  // falls back to pre-tax income. A year with no revenue has no margin.
  assert.deepEqual(history, {
    years: [2021, 2022, 2023, 2024],
    revenue_growth: [null, 10, null, null],
    gross_margin: [50, 54.5, null, 46.2],
    operating_margin: [10, 10.9, null, 10.8],
  });
});

test('a fiscal year missing from the filings is a gap, not bridged by the year after it', () => {
  const history = companyHistory({
    columns: [{ fiscal_year: 2021 }, { fiscal_year: 2023 }],
    values: { revenue: [100, 120] },
  });
  assert.deepEqual(history.years, [2021, 2023]);
  assert.deepEqual(history.revenue_growth, [null, null]);
});

test('the history keeps the last ten fiscal years, in order whatever order the filing lists them', () => {
  const years = Array.from({ length: 12 }, (_, i) => 2013 + i).reverse();
  const history = companyHistory({
    columns: years.map((fiscal_year) => ({ fiscal_year })),
    values: { revenue: years.map((y) => y * 10), ebit: years.map((y) => y) },
  });
  assert.equal(history.years.length, 10);
  assert.equal(history.years[0], 2015);
  assert.equal(history.years[9], 2024);
  assert.equal(history.operating_margin[9], 10);
});

test('no statement, or one with no fiscal years, gives no history', () => {
  assert.equal(companyHistory(null), null);
  assert.equal(companyHistory({ columns: [] }), null);
  assert.equal(companyHistory({ columns: [{ fiscal_year: null }], values: {} }), null);
});
