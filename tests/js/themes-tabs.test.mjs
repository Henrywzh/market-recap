// THEMES sub-tabs: the hash's theme, sub-tab and DATA chip; the chips per theme;
// the default view; panels built on first show; and that themeBlocks (used by the
// SECTORS pages) still draws the same cards in the same order.
// Rendered under node against a small fake DOM and a stub ECharts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import renderThemes, { themeArg, themeArgFor, themeBlocks, themeDataCards, themeOverview, creditPaths } from '../../web/js/tabs/themes.js';

class FakeNode {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this.style = {};
    this.hidden = false;
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  click() { (this.listeners.click || []).forEach((fn) => fn({ type: 'click' })); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  querySelectorAll() { return []; }
  get isConnected() { return true; }
}

const fakeDocument = () => ({
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
  documentElement: new FakeNode('html'),
  body: { contains: () => true },
});

// Installs the fake DOM, ECharts and the frame clock for one test, then restores them.
function withBrowser(run) {
  const saved = {
    document: globalThis.document, window: globalThis.window, getComputedStyle: globalThis.getComputedStyle,
    requestAnimationFrame: globalThis.requestAnimationFrame,
  };
  globalThis.document = fakeDocument();
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
  globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
  globalThis.window = { echarts: { init: () => ({ setOption() {}, resize() {}, dispose() {}, on() {}, getModel() {} }) } };
  return Promise.resolve().then(run).finally(() => {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  });
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(textOf)].filter(Boolean).join(' ');
}

// The title of a card node (its first child is the head, which holds the title).
const cardTitle = (node) => node?.children?.[0]?.children?.[0]?.textContent;

const unavailable = { unavailable: 'source down' };
// Every CLOUD section failed and the release-day study is unavailable: each card still
// draws (with its reason), so each is a chip.
const cloud = { capex: unavailable, guidance: unavailable, nvda: unavailable, odm: unavailable, ramp: unavailable };
const semis = { tw: unavailable, korea_flash: unavailable, korea: unavailable, memory_exports: unavailable, chip_prices: unavailable,
  ramp_tokenomics: unavailable, openrouter: unavailable, adata: unavailable, pcpp: unavailable };

const data = {
  as_of: '2026-10-12',
  calendar_days: 42,
  groups: [
    { key: 'cloud', label: 'Cloud & AI capex', proxy: 'WCLD', proxy_is_etf: true, calendar: [], bellwethers: [], pairs: [], run_in: {} },
    { key: 'semis', label: 'Semiconductors', proxy: 'SMH', proxy_is_etf: true, calendar: [], bellwethers: [], pairs: [], run_in: {} },
    { key: 'cruise', label: 'Cruise lines', proxy: 'CRUZ', proxy_is_etf: false, calendar: [], bellwethers: [], pairs: [], run_in: {} },
  ],
  cloud, semis,
  cruise: { sensitivity: { rows: [], note: 'n' } },
  studies: { unavailable: 'FRED down' },
};

function ctxWith(arg, sets = []) {
  const calls = [];
  return {
    calls,
    arg,
    setArg: (next) => calls.push(next),
    loadArtifact: async (name) => {
      if (name === 'sectors/MARKET') return { valuation: null, outlook: null, history: null };
      throw new Error(`${name}.json returned 404`);
    },
    ...sets,
  };
}

// The sub-tab panels and the status board's root children, found by their attributes.
function panels(root) {
  const nav = root.children.find((n) => n.attrs?.role === 'tablist' && n.attrs?.['aria-label'] === 'Theme views');
  const pane = (id) => root.children.find((n) => n.attrs?.id === `theme-view-${id}`);
  return { nav, pane };
}

test('a hash names the theme, the sub-tab and the DATA chip; anything else falls back', () => {
  const groups = data.groups;
  assert.deepEqual(themeArg('', groups), { key: 'cloud', view: 'overview', chip: null });
  assert.deepEqual(themeArg('SEMIS', groups), { key: 'semis', view: 'overview', chip: null });
  assert.deepEqual(themeArg('SEMIS.VALUATION', groups), { key: 'semis', view: 'valuation', chip: null });
  assert.deepEqual(themeArg('CLOUD.DATA', groups), { key: 'cloud', view: 'data', chip: null });
  assert.deepEqual(themeArg('CLOUD.DATA.OPENROUTER', groups), { key: 'cloud', view: 'data', chip: 'OPENROUTER' });
  assert.deepEqual(themeArg('CLOUD.VALUATION.RAMP', groups), { key: 'cloud', view: 'valuation', chip: null }, 'a chip is read only in DATA');
  assert.deepEqual(themeArg('NOPE.DATA', groups), { key: 'cloud', view: 'data', chip: null }, 'an unknown theme is the first');
  assert.deepEqual(themeArg('CRUISE.FOO', groups), { key: 'cruise', view: 'overview', chip: null }, 'an unknown view is OVERVIEW');
});

test('the argument written back reads the same as the hash it came from', () => {
  assert.equal(themeArgFor({ key: 'cloud', view: 'overview', chip: null }), 'CLOUD');
  assert.equal(themeArgFor({ key: 'cloud', view: 'valuation', chip: null }), 'CLOUD.VALUATION');
  assert.equal(themeArgFor({ key: 'cloud', view: 'data', chip: null }), 'CLOUD.DATA');
  assert.equal(themeArgFor({ key: 'cloud', view: 'data', chip: 'ALL' }), 'CLOUD.DATA.ALL');
  assert.equal(themeArgFor({ key: 'cloud', view: 'overview', chip: 'RAMP' }), 'CLOUD', 'a chip outside DATA is not written');
  const back = themeArg(themeArgFor({ key: 'semis', view: 'data', chip: 'KOREA-EXPORTS' }), data.groups);
  assert.deepEqual(back, { key: 'semis', view: 'data', chip: 'KOREA-EXPORTS' });
});

test('each theme lists its DATA chips in the order the page draws them', () => withBrowser(() => {
  const cloudCards = themeDataCards('cloud', data).map((c) => [c.id, c.label]);
  assert.deepEqual(cloudCards, [
    ['SPENDING', 'Spending'], ['SUPPLIERS', 'Suppliers'], ['RAMP', 'Ramp'], ['FINANCING', 'Financing'], ['RELEASE-DAYS', 'Release days'],
  ]);
  // SEMIS gathers its cards under three chips by what they read, in page order.
  const semis = themeDataCards('semis', data);
  assert.deepEqual(semis.map((c) => [c.id, c.label]), [
    ['TAIWAN-KOREA', 'Taiwan & Korea'], ['MEMORY-PRICES', 'Memory prices'], ['AI-USAGE', 'AI usage'], ['RELEASE-DAYS', 'Release days'],
  ]);
  assert.deepEqual(semis[1].cards, ['MEMORY-EXPORTS', 'CHIP-PRICES', 'ADATA', 'PCPARTPICKER']);
  assert.deepEqual(semis[2].cards, ['RAMP-TOKENS', 'OPENROUTER']);
  // A driven theme whose sensitivity has no rows draws no card for it; the release-day card stays.
  const cruise = themeDataCards('cruise', data).map((c) => c.label);
  assert.deepEqual(cruise, ['Release days']);
}));

test('the overview is the calendar and relative chart, the bellwethers, then the pairs', () => withBrowser(() => {
  const nodes = themeOverview(data.groups[2], data);
  assert.equal(nodes[0].className, 'grid two');
  assert.equal(cardTitle(nodes[1]), 'BELLWETHERS · WHAT THEIR REPORTS DID TO THE THEME');
  assert.equal(nodes.length, 2, 'no pairs for this theme');
}));

test('themeBlocks keeps its order for the SECTORS pages: title, overview, then the industry cards', () => withBrowser(() => {
  const blocks = themeBlocks('semis', data, { title: false });
  assert.equal(blocks[0].className, 'grid two');
  assert.equal(cardTitle(blocks[1]), 'BELLWETHERS · WHAT THEIR REPORTS DID TO THE THEME');
  // The two pairs keep their side-by-side wrapper.
  const pairs = blocks.filter((n) => n.className === 'grid two');
  assert.equal(pairs.length, 3, 'the overview grid and the two industry pairs');
  assert.equal(pairs[1].children.length, 2);
  assert.equal(pairs[2].children.length, 2);
  assert.equal(cardTitle(blocks[blocks.length - 1]), 'RELEASE DAYS', 'the release-day study is last');
  const withTitle = themeBlocks('semis', data);
  assert.equal(withTitle[0].tagName, 'H2');
  assert.equal(themeBlocks('nope', data).length, 0);
}));

test('the page opens on OVERVIEW with the first DATA card only when DATA is picked', () => withBrowser(async () => {
  const root = new FakeNode('div');
  const ctx = ctxWith('CLOUD');
  await renderThemes(root, data, {}, ctx);
  await flush();
  const { nav, pane } = panels(root);
  assert.equal(nav.children[0].attrs['aria-selected'], 'true');
  assert.equal(pane('overview').hidden, false);
  assert.equal(pane('data').hidden, true);
  assert.equal(pane('data').children.length, 0, 'a hidden panel is not built until it is shown');
  assert.deepEqual(ctx.calls, [], 'the hash is not rewritten on load');

  nav.children[2].click();                              // DATA
  const chips = pane('data').children[0];
  const cards = pane('data').children[1].children;
  assert.equal(chips.children.length, 5 + 1, 'one chip per group of cards, plus All');
  assert.deepEqual(cards.map((c) => c.hidden), [false, true, true, true, true], 'the first chip only');
  assert.equal(chips.children[0].attrs['aria-pressed'], 'true');
  assert.deepEqual(ctx.calls, ['CLOUD.DATA']);
}));

test('picking a chip shows that card; All shows every card; the hash follows', () => withBrowser(async () => {
  const root = new FakeNode('div');
  const ctx = ctxWith('CLOUD.DATA');
  await renderThemes(root, data, {}, ctx);
  await flush();
  const { pane } = panels(root);
  const chips = pane('data').children[0].children;
  const cards = pane('data').children[1].children;
  const ramp = chips.find((c) => c.textContent === 'Ramp');
  ramp.click();
  assert.deepEqual(cards.map((c) => c.hidden), [true, true, false, true, true]);
  assert.equal(ramp.attrs['aria-pressed'], 'true');
  assert.equal(chips[0].attrs['aria-pressed'], 'false');
  assert.equal(ctx.calls.at(-1), 'CLOUD.DATA.RAMP');
  chips.find((c) => c.textContent === 'All').click();
  assert.ok(cards.every((c) => !c.hidden));
  assert.equal(ctx.calls.at(-1), 'CLOUD.DATA.ALL');
}));

test('a deep link to a card opens the chip that holds it on load; an unknown chip falls back to the first', () => withBrowser(async () => {
  const root = new FakeNode('div');
  await renderThemes(root, data, {}, ctxWith('SEMIS.DATA.ADATA'));
  await flush();
  const { pane } = panels(root);
  assert.equal(pane('data').hidden, false, 'the linked sub-tab is the one shown');
  const cards = pane('data').children[1].children;
  assert.deepEqual(cards.map((c) => c.hidden), [true, false, true, true], 'ADATA sits under Memory prices');

  const fallback = new FakeNode('div');
  await renderThemes(fallback, data, {}, ctxWith('SEMIS.DATA.NOPE'));
  await flush();
  const first = panels(fallback).pane('data').children[1].children;
  assert.deepEqual(first.map((c) => c.hidden), [false, true, true, true]);
}));

test('picking a theme on the status board keeps the sub-tab and redraws the title', () => withBrowser(async () => {
  const root = new FakeNode('div');
  const ctx = ctxWith('CLOUD.VALUATION');
  await renderThemes(root, data, {}, ctx);
  await flush();
  const { nav, pane } = panels(root);
  assert.equal(pane('valuation').hidden, false);
  assert.match(textOf(root.children[3]), /Cloud & AI capex/, 'the title sits above the tabs');
  // Without bellwether P/E data the board is the overview strip: each tile picks its theme.
  const strip = root.children[2].children.find((n) => n.className === 'theme-strip');
  strip.children[1].click();
  assert.match(textOf(root.children[3]), /Semiconductors/);
  assert.equal(pane('valuation').hidden, false, 'the sub-tab is kept');
  assert.equal(nav.children[1].attrs['aria-selected'], 'true');
  assert.equal(ctx.calls.at(-1), 'SEMIS.VALUATION');
}));

test('an older link to one SEMIS card opens the chip that holds it', () => withBrowser(async () => {
  const root = new FakeNode('div');
  const ctx = ctxWith('SEMIS.DATA.OPENROUTER');
  await renderThemes(root, data, {}, ctx);
  await flush();
  const { pane } = panels(root);
  const chips = pane('data').children[0].children;
  const cards = pane('data').children[1].children;
  assert.equal(chips.find((c) => c.textContent === 'AI usage').attrs['aria-pressed'], 'true');
  assert.deepEqual(cards.map((c) => c.hidden), [true, true, false, true]);
}));

test('the AI borrowers chart puts every name on one weekly axis, with gaps where a name has no reading', () => {
  const weekly = {
    CRWV: { dates: ['2026-10-02', '2026-10-09'], dd: [1.49, 1.44] },
    ORCL: { dates: ['2026-09-25', '2026-10-09'], dd: [3.57, 3.4] },
  };
  const { dates, series } = creditPaths(weekly, ['CRWV', 'ORCL', 'NBIS']);
  assert.deepEqual(dates, ['2026-09-25', '2026-10-02', '2026-10-09']);
  assert.deepEqual(series.CRWV, [null, 1.49, 1.44]);
  assert.deepEqual(series.ORCL, [3.57, null, 3.4]);
  assert.equal(series.NBIS, undefined, 'a name with no path draws no line');
});
