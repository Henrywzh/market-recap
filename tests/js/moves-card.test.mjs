import test from 'node:test';
import assert from 'node:assert/strict';
import { partRows, rangeText, unusualRows, stateRows, bpPair, rangeNote } from '../../web/js/moves-card.js';

test('parts share one scale and keep their sign', () => {
  const rows = partRows({ market_pct: 0.5, sector_pct: -0.25, own_pct: -2, beta_market: 1.2, beta_sector: null });
  assert.deepEqual(rows.map((r) => [r.label, r.width, r.negative]), [['Market', 25, false], ['Sector', 13, true], ['Own', 100, true]]);
  assert.equal(rows[0].beta, 1.2);
  assert.equal(partRows({ market_pct: null, sector_pct: 0, own_pct: 0 })[0].width, 0);
});

test('range text uses the outer quantile pairs and needs both ends', () => {
  const range = { bands: [0.05, 0.16, 0.5, 0.84, 0.95].map((q, i) => ({ q, pct: [-6, -3, 0.1, 3.2, 7][i], price: [94, 97, 100, 103, 107][i] })) };
  assert.deepEqual(rangeText(range), { wide: '-6.0% to +7.0%', widePrices: '$94.00 – $107.00', narrow: '-3.0% to +3.2%' });
  assert.equal(rangeText({ bands: [{ q: 0.5, pct: 0, price: 1 }] }), null);
  assert.equal(rangeText(null), null);
});

test('unusual names are filtered by the own part and sorted by its size', () => {
  const data = { settings: { threshold_sigma: 2 }, rows: [
    { ticker: 'A', z_own: -2.5 }, { ticker: 'B', z_own: 3.1 }, { ticker: 'C', z_own: 1.9 }, { ticker: 'D', z_own: null }] };
  assert.deepEqual(unusualRows(data).map((r) => r.ticker), ['B', 'A']);
  assert.deepEqual(unusualRows(data, 'DOWN').map((r) => r.ticker), ['A']);
  assert.deepEqual(unusualRows(data, 'UP').map((r) => r.ticker), ['B']);
});

// --- technology-only sell-off banner (research v6) ---
import { selloffBanner, selloffHistoryText, selloffOrder } from '../../web/js/moves-card.js';

const history = {
  days: 78, since: '2015-01', until: '2026-05',
  five_day: { bp: 75, lo: 24, hi: 125 }, twenty_day: { bp: 111, lo: 2, hi: 227 },
  strongest: [{ label: 'falls made during the session', bp: 116 }, { label: 'hardware', bp: 137 }],
  absent: [{ label: 'falls that came as a gap at the open', bp: -45 }],
};

test('sell-off history is one sentence with the interval and the negative case', () => {
  const text = selloffHistoryText(history);
  assert.equal(text, 'On 78 such days since 2015 the hardest-hit technology names ended the next 5 sessions +75 bp [+24, +125] ahead of the rest of the sector and the next 20 +111 bp [+2, +227]; most in falls made during the session (+116), hardware (+137); none in falls that came as a gap at the open (-45).');
  assert.equal(selloffHistoryText(null), null);
  assert.ok(!/buy|sell signal|expect/i.test(text));
});

test('sell-off losers: names that fit the profile first, then the hardest hit', () => {
  const order = selloffOrder([
    { ticker: 'A', ret_pct: -9, fits_profile: false }, { ticker: 'B', ret_pct: -5, fits_profile: true },
    { ticker: 'C', ret_pct: -7, fits_profile: true }]);
  assert.deepEqual(order.map((r) => r.ticker), ['C', 'B', 'A']);
  assert.deepEqual(selloffOrder(null), []);
});

test('the sell-off banner is absent unless the session is one with losers', () => {
  assert.equal(selloffBanner(null), null);
  assert.equal(selloffBanner({}), null);
  assert.equal(selloffBanner({ sector_selloff: { active: false, losers: [{ ticker: 'A' }], history } }), null);
  assert.equal(selloffBanner({ sector_selloff: { active: true, losers: [], history } }), null);
});

// "What shocks like this did next": rows come from the frozen table, matched on tags.
const cell = (mean, median) => ({ mean, median, positive_share: 0.5, n: 100, lo: mean - 0.002, hi: mean + 0.002 });
const states = { since: '2015-01', rows: [
  { direction: 'down', label: 'All down shocks', match: {}, stats: { h1: cell(0, 0), h5: cell(0.0003, 0.0004), h20: cell(-0.0003, 0) } },
  { direction: 'down', label: 'No report', match: { reported: false }, stats: { h5: cell(0.0006, 0.0007) } },
  { direction: 'down', label: 'Report', match: { reported: true }, stats: { h5: cell(-0.0011, -0.0011) } },
  { direction: 'down', label: 'First shock', match: { repeat: false }, stats: { h5: cell(-0.0005, 0) } },
  { direction: 'up', label: 'All up shocks', match: {}, stats: { h5: cell(-0.0015, -0.0009) } },
  { direction: 'up', label: 'Rally, no report, market below its 200-day', match: { reported: false, market_above_200d: false }, stats: { h5: cell(-0.0057, -0.0024) } },
] };

test('a shock matches its direction, the whole group first, then every tag that holds', () => {
  const row = { direction: 'down', tags: { reported: false, repeat: false } };
  assert.deepEqual(stateRows(row, states).map((r) => r.label), ['All down shocks', 'No report', 'First shock']);
  const rally = { direction: 'up', tags: { reported: false, market_above_200d: false } };
  assert.deepEqual(stateRows(rally, states).map((r) => r.label), ['All up shocks', 'Rally, no report, market below its 200-day']);
});

test('an unknown tag matches nothing, and a non-shock or a missing table has no rows', () => {
  assert.deepEqual(stateRows({ direction: 'down', tags: { reported: null, repeat: null } }, states).map((r) => r.label), ['All down shocks']);
  assert.deepEqual(stateRows({ direction: 'up', tags: { reported: false, market_above_200d: null } }, states).map((r) => r.label), ['All up shocks']);
  assert.deepEqual(stateRows({ direction: null, tags: null }, states), []);
  assert.deepEqual(stateRows({ direction: 'down', tags: { reported: true } }, null), []);
});

test('table cells are basis points, mean over median', () => {
  assert.equal(bpPair(cell(0.0003, 0.0004)), '+3 / +4');
  assert.equal(bpPair(cell(-0.0057, -0.0024)), '-57 / -24');
  assert.equal(bpPair(undefined), '—');
});

test('the range note names the factor and reason only when a shock was scaled', () => {
  const range = { widePrices: '$88.80 – $108.96' };
  assert.equal(rangeNote({ range_factor: 1 }, range), '90% of its own history · $88.80 – $108.96');
  assert.equal(rangeNote({}, range), '90% of its own history · $88.80 – $108.96');
  assert.equal(rangeNote({ range_factor: 1.12, range_reason: 'repeat drop: the band ran too narrow' }, range),
    '90% of its own history · $88.80 – $108.96 · ×1.12, repeat drop: the band ran too narrow');
});
