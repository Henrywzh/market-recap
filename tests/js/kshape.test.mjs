import test from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/kshape-model.js';

test('ordinals and the percentile view', () => {
  assert.deepEqual([1, 2, 3, 4, 11, 12, 13, 21, 22, 83, 100].map(M.ordinal), ['1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '83rd', '100th']);
  assert.equal(M.ordinal(null), '—');
  assert.equal(M.percentileView(92).tone, 'warn');
  assert.equal(M.percentileView(8).tone, 'info');
  assert.equal(M.percentileView(50).tone, 'dim');
  assert.equal(M.percentileView(null).text, '—');
  assert.equal(M.percentileView(83).text, '83rd percentile');
});

test('the premium sentence reports price and growth in the build\'s own figures and says nothing when a leg has no multiple', () => {
  const v = M.premiumView({ pe_forward_ratio: 1.89, eps_growth_this_year_top: 24.2, eps_growth_this_year_bottom: 13.4 });
  assert.equal(Math.round(v.premiumPct), 89);
  assert.match(v.text, /pays 89% more per dollar of earnings, against consensus EPS growth ahead by 10\.8 points/);
  const d = M.premiumView({ pe_forward_ratio: 0.73, eps_growth_this_year_top: -5.8, eps_growth_this_year_bottom: 8.0 });
  assert.match(d.text, /is priced 27% less per dollar of earnings, against consensus EPS growth behind by 13\.8 points/);
  assert.equal(M.premiumView({ pe_forward_ratio: null }).premiumPct, null);
  assert.match(M.premiumView(null).text, /no forward multiple/);
  assert.doesNotMatch(M.premiumView({ pe_forward_ratio: 1.2, eps_growth_this_year_top: null, eps_growth_this_year_bottom: 5 }).text, /growth/);
});

test('a name row marks where its forward multiple came from and never turns a gap into zero', () => {
  const r = M.nameRow({ ticker: 'VIK', leg: 'top', pe_forward: 19.8, forward_source: 'consensus', pe_percentile: null, eps_growth_this_year: 24.2, revenue_growth: null, ret_3m: -16.9, ret_1y: 36.7, first_price: '2024-05-01' });
  assert.deepEqual([r.pe, r.percentile, r.growth, r.revenue], ['19.8×', '—', '+24.2', '—']);
  assert.match(r.peTitle, /consensus only/);
  const bare = M.nameRow({ ticker: 'X', leg: 'bottom', pe_forward: null, forward_source: null });
  assert.deepEqual([bare.pe, bare.peTitle], ['—', 'no forward multiple']);
});

test('spread rows are coloured by the gap and a missing window stays missing', () => {
  const rows = M.spreadRows([{ period: '1M', top: 1, bottom: -2, spread: 3 }, { period: '5Y', top: null, bottom: null, spread: null }, { period: '3M', top: -5, bottom: -1, spread: -4 }]);
  assert.deepEqual(rows.map((r) => r.tone), ['up', 'dim', 'down']);
  assert.equal(rows[1].spread, null);
  assert.equal(M.multipleText(1.886), '1.89×');
  assert.equal(M.multipleText(undefined), '—');
  assert.equal(M.peRangeText(null), null);
  assert.match(M.peRangeText({ ratio_median: 0.99, ratio_p10: 0.7, ratio_p90: 1.4, dates_used: 522 }), /median 0\.99×, 10th to 90th percentile 0\.70× to 1\.40×, 522 weeks/);
});
