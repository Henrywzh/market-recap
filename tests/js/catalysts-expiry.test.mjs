// CATALYSTS: the expiry tags, the after-a-large-move reading, and the two lines the page says about expiry.
import test from 'node:test';
import assert from 'node:assert/strict';
import { expiryTag, expiryWatchTitle, EXPIRY_WATCH_LINE, ZERO_DTE_LINE } from '../../web/js/tabs/catalysts.js';

test('a rule event is tagged by its expiry, and any other event is not', () => {
  assert.equal(expiryTag({ rule: 'monthly_opex' }), 'MONTHLY OPEX');
  assert.equal(expiryTag({ rule: 'quad_witching' }), 'QUAD WITCHING');
  assert.equal(expiryTag({ rule: 'vix_expiry' }), 'VIX EXPIRY');
  assert.equal(expiryTag({ rule: 'jobless_claims' }), null);
  assert.equal(expiryTag({ rule: null }), null);
  assert.equal(expiryTag(undefined), null);
});

test('the reading behind the flag names the fund, its move, the date and the sigmas, signed as the move was', () => {
  const down = expiryWatchTitle({ fund: 'SPY', date: '2026-10-14', return_pct: -2.314, z: -2.6 });
  assert.match(down, /^SPY -2\.31% on 2026-10-14: 2\.6σ/);
  const up = expiryWatchTitle({ fund: 'QQQ', date: '2026-10-13', return_pct: 3.1, z: 2.04 });
  assert.match(up, /^QQQ \+3\.10% on 2026-10-13: 2\.0σ/);
});

test('the two lines the page says are the ones the brief asks for, and say no more', () => {
  assert.match(EXPIRY_WATCH_LINE, /^Expiry can change hedging and flows: watch the open and close and liquidity\./);
  assert.match(EXPIRY_WATCH_LINE, /not a directional signal\.$/);
  assert.equal(ZERO_DTE_LINE, 'SPX options now expire every session (0DTE); these dates mark the larger monthly and quarterly expiries.');
});

test('next expiries line names each expiry with days to go', async () => {
  const { nextExpiriesText } = await import('../../web/js/tabs/catalysts.js');
  const text = nextExpiriesText([{ rule: 'monthly_opex', date: '2026-11-20' }, { rule: 'quad_witching', date: '2026-12-18' }], '2026-10-16');
  assert.equal(text, 'MONTHLY OPEX 2026-11-20 (35d) · QUAD WITCHING 2026-12-18 (63d)');
  assert.equal(nextExpiriesText([], '2026-10-16'), null);
});
