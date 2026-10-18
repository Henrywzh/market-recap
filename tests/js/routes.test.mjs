// Navigation: every hash lands on a view, and old bookmarks still work.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import * as R from '../../web/js/routes.js';

test('a view with an argument reads it after the slash', () => {
  assert.deepEqual(R.parseHash('#ticker/aapl'), { id: 'ticker', arg: 'AAPL' });
  assert.deepEqual(R.parseHash('#dcf/BRK-B'), { id: 'dcf', arg: 'BRK-B' });
});

test('a view without an argument ignores one', () => {
  assert.deepEqual(R.parseHash('#monitor/AAPL'), { id: 'monitor', arg: null });
});

test('an argument falls back to ?ticker= from links written before the regrouping', () => {
  assert.deepEqual(R.parseHash('#technicals', '?ticker=nvda'), { id: 'technicals', arg: 'NVDA' });
  assert.deepEqual(R.parseHash('#ticker/MSFT', '?ticker=nvda'), { id: 'ticker', arg: 'MSFT' });
});

test('merged views redirect, carrying the ticker', () => {
  assert.deepEqual(R.parseHash('#fixed-income'), { id: 'rates', arg: null });
  assert.deepEqual(R.parseHash('#macro'), { id: 'rates', arg: null });
  assert.deepEqual(R.parseHash('#financials', '?ticker=AAPL'), { id: 'ticker', arg: 'AAPL' });
});

test('unknown or empty hashes land on the default view', () => {
  assert.deepEqual(R.parseHash(''), { id: R.DEFAULT_VIEW, arg: null });
  assert.deepEqual(R.parseHash('#nope'), { id: R.DEFAULT_VIEW, arg: null });
});

test('an argument that is not a ticker is dropped, not passed on', () => {
  assert.equal(R.parseHash('#ticker/<script>').arg, null);
  assert.equal(R.cleanTicker('^GSPC'), '^GSPC');
  assert.equal(R.cleanTicker(''), null);
});

test('hashFor round-trips through parseHash', () => {
  assert.deepEqual(R.parseHash(`#${R.hashFor('ticker', 'BRK-B')}`), { id: 'ticker', arg: 'BRK-B' });
  assert.equal(R.hashFor('monitor'), 'monitor');
});

test('every view has a module, a known group, and a unique id', () => {
  const modules = new Set(readdirSync(new URL('../../web/js/tabs/', import.meta.url)).map((f) => f.replace(/\.js$/, '')));
  const groups = new Set(R.GROUPS.map((g) => g.id));
  const ids = new Set();
  for (const view of R.VIEWS) {
    assert.ok(modules.has(view.module), `${view.id}: no module ${view.module}.js`);
    assert.ok(groups.has(view.group), `${view.id}: unknown group ${view.group}`);
    assert.ok(!ids.has(view.id), `${view.id} is listed twice`);
    ids.add(view.id);
  }
  for (const target of Object.values(R.ALIASES)) assert.ok(ids.has(target), `alias target ${target} is not a view`);
});

// Four, except NAMES: the screener came back beside TICKER (2026-10-18).
test('no group offers more than five views', () => {
  for (const group of R.GROUPS) assert.ok(R.viewsIn(group.id).length <= 5, group.id);
});

test('every ticker link opens the ticker page', () => {
  assert.equal(R.tickerHref('BRK-B'), '#ticker/BRK-B');
  assert.deepEqual(R.parseHash(R.tickerHref('brk-b')), { id: 'ticker', arg: 'BRK-B' });
});

test('#sectors opens the hub, a sector or a sub-industry; the old #rotation lands there too', () => {
  assert.deepEqual(R.parseHash('#sectors'), { id: 'sectors', arg: null });
  assert.deepEqual(R.parseHash('#sectors/xlp-sdnb'), { id: 'sectors', arg: 'XLP-SDNB' });
  assert.deepEqual(R.parseHash('#rotation'), { id: 'sectors', arg: null });
});

test('the overview is the landing page; MARKET, then SECTORS, then RISK', () => {
  assert.equal(R.DEFAULT_VIEW, 'overview');
  assert.deepEqual(R.GROUPS.map((g) => g.id).slice(0, 3), ['market', 'sectors', 'risk']);
  assert.deepEqual(R.parseHash('#brief'), { id: 'overview', arg: null });
  assert.deepEqual(R.parseHash('#journal'), { id: 'overview', arg: null });
});

test('SCREENER is in the menu under NAMES, right after TICKER; #valuation/MSFT still opens it', () => {
  const names = R.viewsIn('names').map((v) => v.id);
  assert.equal(R.viewById('valuation').label, 'SCREENER');
  assert.ok(!R.viewById('valuation').hidden);
  assert.equal(names[names.indexOf('valuation') - 1], 'ticker');
  assert.deepEqual(names, ['monitor', 'ticker', 'valuation', 'europe-names', 'cross-listing']);
  assert.deepEqual(R.parseHash('#valuation/MSFT'), { id: 'valuation', arg: 'MSFT' });
});

test('a dotted share class resolves to the build\'s dashed symbol, nothing else does', () => {
  const has = (t) => ['BRK-B', 'BF-B', 'VOD.L', 'AAPL'].includes(t);
  assert.equal(R.resolveTicker('BRK.B', has), 'BRK-B');
  assert.equal(R.resolveTicker('BRK-B', has), 'BRK-B');
  assert.equal(R.resolveTicker('VOD.L', has), 'VOD.L');
  assert.equal(R.resolveTicker('XYZ.B', has), 'XYZ.B');            // unknown either way: left as typed
  assert.equal(R.resolveTicker(null, has), null);
});

test('a pair key with an underscore survives the hash', () => {
  assert.deepEqual(R.parseHash("#sizek/value_growth"), { id: "sizek", arg: "VALUE_GROWTH" });
});

test('RELATIVE VALUE is one menu entry: SIZE & STYLE is reached from its switch and highlights its parent', () => {
  const sizek = R.viewById('sizek');
  assert.equal(sizek.hidden, true);
  assert.equal(R.viewById(sizek.menu).group, sizek.group);
  assert.ok(R.viewsIn('sectors').some((v) => v.id === sizek.menu));
  assert.ok(!R.viewsIn('sectors').some((v) => v.id === 'sizek'));
  assert.deepEqual(R.parseHash('#sizek/uk'), { id: 'sizek', arg: 'UK' });        // bookmarks to either page keep working
  assert.deepEqual(R.parseHash('#kshape/cruise'), { id: 'kshape', arg: 'CRUISE' });
});

test('AI CHAIN is a SECTORS view, not a CALENDAR one', () => {
  assert.equal(R.viewById('chain').group, 'sectors');
  assert.ok(!R.viewsIn('calendar').some((v) => v.id === 'chain'));
});

test('THEMES deep links keep their sub-view through the hash', async () => {
  const { parseHash, cleanThemeArg } = await import('../../web/js/routes.js');
  assert.equal(parseHash('#themes/CLOUD.DATA.OPENROUTER').arg, 'CLOUD.DATA.OPENROUTER');
  assert.equal(parseHash('#themes/semis.data.korea-exports').arg, 'SEMIS.DATA.KOREA-EXPORTS');
  assert.equal(parseHash('#themes/CONSUMER.VALUATION').arg, 'CONSUMER.VALUATION');
  assert.equal(parseHash('#themes/CLOUD').arg, 'CLOUD');
  assert.equal(cleanThemeArg('<script>'), null);
  assert.equal(parseHash('#ticker/NVDA').arg, 'NVDA');
});

test('the TICKER page keeps its sub-tab after the symbol, dotted symbols included', () => {
  assert.deepEqual(R.parseHash('#ticker/nvda/report'), { id: 'ticker', arg: 'NVDA/REPORT' });
  assert.deepEqual(R.parseHash('#ticker/BRK.B/FINANCIALS'), { id: 'ticker', arg: 'BRK.B/FINANCIALS' });
  assert.equal(R.hashFor('ticker', 'NVDA/VALUE'), 'ticker/NVDA/VALUE', 'the slash stays readable');
  assert.deepEqual(R.parseHash(`#${R.hashFor('ticker', 'NVDA/VALUE')}`), { id: 'ticker', arg: 'NVDA/VALUE' });
  assert.deepEqual(R.parseHash('#ticker/NVDA%2FVALUE'), { id: 'ticker', arg: 'NVDA/VALUE' }, 'an encoded slash still reads');
  assert.deepEqual(R.parseHash('#ticker/NVDA/1/2'), { id: 'ticker', arg: null }, 'anything longer is not an argument');
  assert.deepEqual(R.parseHash('#ticker/NVDA/x1'), { id: 'ticker', arg: 'NVDA' }, 'a malformed view keeps the symbol');
  assert.deepEqual(R.parseHash('#dcf/NVDA/REPORT'), { id: 'dcf', arg: null }, 'only TICKER takes a sub-tab');
});
