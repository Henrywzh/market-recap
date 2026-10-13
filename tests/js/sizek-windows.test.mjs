// SIZE & STYLE: the lookback window, the windowed price series, and the input
// the valuation cards are given when the build has no payload (or only a note).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readWindow, writeWindow, priceSeries, gapSeries, fundamentalsOf } from '../../web/js/sizek-model.js';

const DATES = ['2020-12-31', '2021-06-30', '2025-10-10', '2026-01-02', '2026-07-13', '2026-09-14', '2026-10-12'];

// Node 25 defines localStorage as an accessor, so swap it with a defined
// property and put the original descriptor back afterwards.
function withStorage(storage, run) {
  const had = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true, writable: true });
  try {
    run();
  } finally {
    if (had) Object.defineProperty(globalThis, 'localStorage', had);
    else delete globalThis.localStorage;
  }
}

test('the remembered window comes back when it is a known window, and a failing or empty store falls back', () => {
  const store = new Map();
  withStorage({ getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)) }, () => {
    assert.equal(readWindow('mr-window-sizek', '5Y'), '5Y');
    writeWindow('mr-window-sizek', '1Y');
    assert.equal(readWindow('mr-window-sizek', '5Y'), '1Y');
    store.set('mr-window-sizek', 'FOREVER');
    assert.equal(readWindow('mr-window-sizek', '5Y'), '5Y');
  });
  withStorage({ getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } }, () => {
    assert.equal(readWindow('mr-window-sizek', '5Y'), '5Y');
    assert.doesNotThrow(() => writeWindow('mr-window-sizek', '1Y'));
  });
  withStorage(undefined, () => {
    assert.equal(readWindow('mr-window-sizek', '3Y'), '3Y');
    assert.doesNotThrow(() => writeWindow('mr-window-sizek', '1Y'));
  });
});

test('the price ratio is rebased to 1 and each arm to 100 at the window\'s first close', () => {
  const price = { dates: DATES, ratio: [1, 2, 2, 4, 8, 6, 2], big: [10, 20, 20, 40, 80, 60, 20], small: [10, 10, 10, 10, 10, 10, 10] };
  const cut = priceSeries(price, '1Y');
  assert.deepEqual(cut.dates, DATES.slice(2));
  assert.deepEqual(cut.series.ratio, [1, 2, 4, 3, 1]);
  assert.deepEqual(cut.series.big, [100, 200, 400, 300, 100]);
  assert.deepEqual(cut.series.small, [100, 100, 100, 100, 100]);
});

test('the rolling gap is cut to the window and never rebased', () => {
  const gap = { dates: ['2025-09-30', '2025-10-10', '2025-10-17', '2026-01-02'], gap: [-3.5, 2.0, 0.5, -1.0] };
  const cut = gapSeries(gap, '1M');   // from the last gap date, the window starts on 2025-10-17
  assert.deepEqual(cut.dates, ['2025-10-17', '2026-01-02']);
  assert.deepEqual(cut.series.gap, [0.5, -1.0]);
});

test('a view with no valuation payload gives its note as the reason, or says the build lacks it', () => {
  assert.deepEqual(fundamentalsOf({ fundamentals_note: 'Small and mid caps are outside the filings universe.' }),
    { missing: 'Small and mid caps are outside the filings universe.' });
  assert.match(fundamentalsOf({}).missing, /not in this build/);
  assert.equal(fundamentalsOf({}, 'Custom reason.').missing, 'Custom reason.');
});

test('a complete payload passes through; a reason stated by the payload or an empty arm is shown', () => {
  const payload = { arms: [{ key: 'big', basket: { dates: DATES } }, { key: 'small', basket: { dates: DATES } }] };
  assert.equal(fundamentalsOf({ fundamentals: payload }), payload);
  const missing = { missing: 'The iShares fetch failed.' };
  assert.equal(fundamentalsOf({ fundamentals: missing }), missing);
  const oneArm = { arms: [{ key: 'big', basket: { dates: DATES } }, { key: 'small', missing: 'IWF holdings could not be fetched.' }] };
  assert.deepEqual(fundamentalsOf({ fundamentals: oneArm }), { missing: 'IWF holdings could not be fetched.' });
  assert.deepEqual(fundamentalsOf({ fundamentals: { arms: [{ key: 'a', basket: { dates: [] } }, { key: 'b', basket: null }] }, fundamentals_note: 'note' }), { missing: 'note' });
  assert.deepEqual(fundamentalsOf({ fundamentals: { arms: [] } }), { missing: 'No filings history for both arms.' });
});

test('the SIZE & STYLE tab loads under node and exports its renderer', async () => {
  const mod = await import('../../web/js/tabs/sizek.js');
  assert.equal(typeof mod.default, 'function');
});
