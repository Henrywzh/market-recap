// TODAY's live unusual-move rules on synthetic rows and quotes: the z and own-part
// formulas, the sector and missing-beta cases, the threshold, the order and cap,
// and when the live list is shown at all.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { liveZ, liveUnusual, liveView, liveIsCurrent, isUnusualZ } from '../../web/js/today-live.js';

const close = (a, b) => Math.abs(a - b) < 1e-9;
const NOW = 1_800_000_000_000;               // ms; the quotes' times are seconds
const FRESH = 1_800_000_000 - 60;            // a minute old
const LIVE = { threshold_sigma: 2, market: 'SPY', sector_funds: { Tech: 'XLK' }, max_items: 12 };

test('z is the return over its own sigma; the own part takes out the market and the sector', () => {
  const row = { ticker: 'AAA', sector: 'Tech', sigma_pct: 2, sigma_own_pct: 1.5, beta_market: 1.2, beta_sector: 0.8 };
  const m = liveZ(row, { change_pct: 5 }, { change_pct: 1 }, { change_pct: 3 });
  assert.ok(close(m.z, 2.5));
  // sector part 0.8 * (3 - 1) = 1.6; own = 5 - 1.2 * 1 - 1.6 = 2.2; z_own = 2.2 / 1.5
  assert.ok(close(m.own_pct, 2.2));
  assert.ok(close(m.z_own, 2.2 / 1.5));
});

test('a name with no sector beta has no sector part, not a zero one from a missing fund', () => {
  const row = { ticker: 'WATCH', sector: null, sigma_pct: 2, sigma_own_pct: 1.5, beta_market: 1.2, beta_sector: null };
  const m = liveZ(row, { change_pct: 5 }, { change_pct: 1 }, null);
  assert.ok(close(m.own_pct, 5 - 1.2));
  assert.ok(close(m.z_own, 3.8 / 1.5));
});

test('a sector beta with no sector quote leaves the own part unknown, but keeps z', () => {
  const row = { ticker: 'AAA', sector: 'Tech', sigma_pct: 2, sigma_own_pct: 1.5, beta_market: 1.2, beta_sector: 0.8 };
  const m = liveZ(row, { change_pct: 5 }, { change_pct: 1 }, undefined);
  assert.ok(close(m.z, 2.5));
  assert.equal(m.own_pct, null);
  assert.equal(m.z_own, null);
});

test('a missing price or sigma gives null, never zero', () => {
  const row = { ticker: 'AAA', sector: 'Tech', sigma_pct: 2, sigma_own_pct: 1.5, beta_market: 1, beta_sector: 1 };
  const none = liveZ(row, { error: 'no price' }, { change_pct: 1 }, { change_pct: 1 });
  assert.equal(none.z, null);
  assert.equal(none.z_own, null);
  assert.equal(liveZ({ ...row, sigma_pct: 0 }, { change_pct: 4 }, { change_pct: 1 }, { change_pct: 1 }).z, null);
});

test('the threshold fires on either measure and not below it', () => {
  assert.equal(isUnusualZ({ z: 2, z_own: 0 }, 2), true);
  assert.equal(isUnusualZ({ z: 0.5, z_own: -2.4 }, 2), true);
  assert.equal(isUnusualZ({ z: 1.99, z_own: 1.9 }, 2), false);
  assert.equal(isUnusualZ({ z: null, z_own: null }, 2), false);
});

test('the live list keeps the names beyond the threshold, strongest first, and skips the unpriced', () => {
  const rows = [
    { ticker: 'A', name: 'Calm', sector: 'Tech', sigma_pct: 2, sigma_own_pct: 1, beta_market: 1, beta_sector: 1 },
    { ticker: 'B', name: 'Bee', sector: 'Tech', sigma_pct: 1, sigma_own_pct: 1, beta_market: 1, beta_sector: null },
    { ticker: 'C', name: 'Sea', sector: 'Tech', sigma_pct: 2, sigma_own_pct: 1, beta_market: 1, beta_sector: 1 },
    { ticker: 'D', name: 'Dee', sector: 'Tech', sigma_pct: 1, sigma_own_pct: 1, beta_market: 1, beta_sector: 1 },
    { ticker: 'E', name: 'Eee', sector: 'Health', sigma_pct: 1, sigma_own_pct: 1, beta_market: 1, beta_sector: null },
    { ticker: 'F', name: 'Eff', sector: 'Tech', sigma_pct: 1, sigma_own_pct: 1, beta_market: 1, beta_sector: null },
  ];
  const quotes = new Map([
    ['SPY', { symbol: 'SPY', change_pct: 1 }],
    ['XLK', { symbol: 'XLK', change_pct: 1 }],
    ['A', { symbol: 'A', change_pct: 1 }],               // z 0.5, own 0: calm
    ['B', { symbol: 'B', change_pct: 3 }],               // z 3, own 2 (no sector part)
    ['C', { symbol: 'C', change_pct: -6, time: FRESH }], // z -3; sector part 1 * (XLK 1 - SPY 1) = 0, own -7
    // D has no quote at all: skipped.
    ['E', { symbol: 'E', change_pct: 2.4 }],             // z 2.4; no fund and no sector beta: own 1.4
    ['F', { symbol: 'F', change_pct: 1.9 }],             // below 2 on both
  ]);
  const found = liveUnusual(rows, quotes, LIVE);
  assert.deepEqual(found.map((f) => f.ticker), ['C', 'B', 'E']);
  assert.equal(found[0].time, FRESH);
  assert.equal(found[0].name, 'Sea');
  assert.ok(close(found[0].z_own, -7));                  // own = -6 - 1 * 1 - 0, over sigma_own 1
  assert.ok(close(found[1].z_own, 2));                   // B: own = 3 - 1, over 1
  assert.ok(close(found[2].z_own, 1.4));                 // E: no sector part, own = 2.4 - 1
});

test('the cap keeps the first max_items names of that order', () => {
  const rows = ['P', 'Q', 'R'].map((t, i) => ({ ticker: t, name: t, sector: null, sigma_pct: 1, sigma_own_pct: 1, beta_market: 1, beta_sector: null, i }));
  const quotes = new Map([['SPY', { change_pct: 0 }], ['P', { change_pct: 3 }], ['Q', { change_pct: 5 }], ['R', { change_pct: 4 }]]);
  assert.deepEqual(liveUnusual(rows, quotes, { ...LIVE, max_items: 2 }).map((f) => f.ticker), ['Q', 'R']);
});

const heat = (open, quotes = []) => ({ session: { open }, stale_after_seconds: 1200, quotes });

test('the live list is shown only while the session is open and the market quote is fresh', () => {
  const rows = [{ ticker: 'B', name: 'Bee', sector: null, sigma_pct: 1, sigma_own_pct: 1, beta_market: 1, beta_sector: null }];
  const etfs = { quotes: [{ symbol: 'SPY', change_pct: 1, time: FRESH }] };
  const moves = rows;
  const bee = [{ symbol: 'B', change_pct: 3 }];
  const open = heat(true, bee);
  assert.ok(liveIsCurrent(open, { change_pct: 1, time: FRESH }, NOW));
  assert.equal(liveIsCurrent(heat(false, bee), { change_pct: 1, time: FRESH }, NOW), false);   // closed
  assert.equal(liveIsCurrent(open, { change_pct: 1, time: FRESH - 5000 }, NOW), false);        // stale
  assert.equal(liveIsCurrent(open, { error: 'HTTP 500' }, NOW), false);                         // no price
  const view = liveView({ moves, heat: open, etfs }, LIVE, NOW);
  assert.deepEqual(view.items.map((f) => f.ticker), ['B']);
  assert.equal(view.time, FRESH);
  assert.equal(liveView({ moves, heat: heat(false, bee), etfs }, LIVE, NOW), null);
  assert.equal(liveView({ moves: null, heat: open, etfs }, LIVE, NOW), null);
  assert.equal(liveView({ moves, heat: open, etfs }, null, NOW), null);
  assert.equal(liveView({ moves, heat: open, etfs: { quotes: [] } }, LIVE, NOW), null);        // no SPY quote
});
