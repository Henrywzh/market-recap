// The TODAY page on a fixture today.json, under node against a small fake DOM:
// the sections and their headings, the empty-state and ongoing lines, the
// coming-up days, the tags, the live MOVES list, the route label, and a full
// render with the live feeds stubbed out.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import renderToday, { dayLabel, whenText, unusualNodes, comingUpSection, justOutSection } from '../../web/js/tabs/today.js';
import { VIEWS, DEFAULT_VIEW, parseHash, viewById } from '../../web/js/routes.js';

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
  removeEventListener() {}
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  get isConnected() { return true; }
}

const fakeDocument = () => ({
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
  addEventListener() {},
  removeEventListener() {},
  hidden: false,
});

// The text of a node and everything under it, as a reader would see it.
function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(textOf)].filter(Boolean).join(' ');
}

// Runs a synchronous render with the browser globals and the timers stubbed, so the
// live strip and the live feeds create nothing that outlives the test.
function withBrowser(run) {
  const saved = { document: globalThis.document, setTimeout: globalThis.setTimeout, setInterval: globalThis.setInterval, clearInterval: globalThis.clearInterval };
  globalThis.document = fakeDocument();
  globalThis.setTimeout = () => 0;
  globalThis.setInterval = () => 0;
  globalThis.clearInterval = () => {};
  try {
    return run();
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
}

const item = (over) => ({
  key: 'k', kind: 'macro', date: '2026-10-16', time: null, timing: null, subject: 'X', title: 'A title', detail: null,
  value: null, unit: null, z: null, importance: 'medium', new: true, since: null, days: null, evidence: 'description',
  link: '#catalysts', extra: {}, ...over,
});

const fixture = () => ({
  as_of: '2026-10-16',
  sessions: ['2026-10-19', '2026-10-20', '2026-10-21'],
  just_out: {
    session: '2026-10-16',
    macro: [item({ subject: 'CPI', title: 'Consumer prices rose faster than expected', value: 3.4, unit: '%', detail: 'consensus 3.2%', importance: 'high', time: '08:30' })],
    earnings: [item({ kind: 'earnings', subject: 'TRV', title: 'Travelers beat and rose 1.5%', link: '#ticker/TRV', z: 0.9, extra: { return_1d: 1.47 } })],
  },
  coming_up: {
    days: [
      { date: '2026-10-19', items: [item({ kind: 'earnings', subject: 'FITB', title: 'Fifth Third reports before the open', timing: 'bmo', detail: 'EPS estimate 1.09', extra: { implied_pct: 4.2 }, link: '#ticker/FITB' })] },
      { date: '2026-10-20', items: [] },
      { date: '2026-10-21', items: [item({ kind: 'expiry', subject: 'VIX', title: 'VIX options and futures expire', time: '09:30', importance: 'high', evidence: 'tested' })] },
    ],
    later: [item({ kind: 'central_bank', subject: 'FOMC', title: 'Fed decision', date: '2026-10-28', time: '14:00', importance: 'high' })],
    later_until: '2026-11-01',
  },
  unusual: {
    moves: [item({ kind: 'move', subject: 'NVDA', title: 'NVIDIA fell far beyond its usual move', z: -3.4, evidence: 'tested', importance: 'high', link: '#ticker/NVDA' })],
    states: [],
    events: [],
    ongoing: [item({ kind: 'market_state', subject: 'small caps', title: 'Small caps lagging the S&P 500', days: 26, new: false, link: '#markets' })],
  },
  live: { threshold_sigma: 2, market: 'SPY', sector_funds: { 'Information Technology': 'XLK' }, max_items: 12 },
  unavailable: [{ part: 'moves', reason: 'the moves file did not load' }],
  history: [],
  settings: {},
  notes: [],
});

const nothing = () => ({ ...fixture(), just_out: { session: '2026-10-16', macro: [], earnings: [] }, coming_up: { days: [], later: [], later_until: null }, unusual: { moves: [], states: [], events: [], ongoing: [] } });

test('the landing page is TODAY, still at the overview hash, and the default view', () => {
  assert.equal(viewById('overview').label, 'TODAY');
  assert.equal(viewById('overview').module, 'today');
  assert.equal(viewById('overview').artifact, 'today');
  assert.equal(DEFAULT_VIEW, 'overview');
  assert.deepEqual(parseHash('#overview'), { id: 'overview', arg: null });
  assert.equal(VIEWS.filter((v) => v.label === 'TODAY').length, 1);
});

test('dates read as calendar days, and an item shows its clock time, else its timing', () => {
  assert.equal(dayLabel('2026-10-19'), 'MON OCT 19');
  assert.equal(dayLabel(null), '—');
  assert.equal(whenText(item({ time: '08:30' })), '08:30 ET');
  assert.equal(whenText(item({ timing: 'bmo' })), 'BEFORE OPEN');
  assert.equal(whenText(item({ timing: 'amc' })), 'AFTER CLOSE');
  assert.equal(whenText(item({})), '');
});

test('the page draws the title, the three section headings, the coming-up days and LATER', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderToday(root, fixture(), null, {});
  const text = textOf(root);
  for (const heading of ['TODAY', 'JUST OUT', 'COMING UP', 'UNUSUAL NOW']) assert.ok(text.includes(heading), `missing ${heading}`);
  assert.ok(text.includes('MON OCT 19') && text.includes('TUE OCT 20') && text.includes('WED OCT 21'));
  assert.ok(text.includes('LATER · HIGH IMPORTANCE · TO SUN NOV 1'));
  assert.ok(text.includes('Fifth Third reports before the open'));
  assert.ok(text.includes('EPS estimate 1.09 · implied ±4.2%'));
  assert.ok(text.includes('Consumer prices rose faster than expected'));
  assert.ok(text.includes('Travelers beat and rose 1.5%'));
  assert.ok(text.includes('SESSION CLOSE · OCT 16, 2026'), 'the header carries the session close');
}));

test('a day with no items, an empty unusual list and the ongoing line read as the page says', () => withBrowser(() => {
  const text = textOf(comingUpSection(fixture().coming_up));
  assert.ok(text.includes('Nothing on the calendar this session that matters here.'));
  const quiet = textOf({ children: unusualNodes(nothing().unusual, { live: null, asOf: '2026-10-16' }) });
  assert.ok(quiet.includes('Nothing crossed a threshold this session.'));
  assert.ok(!quiet.includes('MOVES'), 'no block headings when nothing moved');
  const busy = textOf({ children: unusualNodes(fixture().unusual, { live: null, asOf: '2026-10-16' }) });
  assert.ok(busy.includes('Ongoing: Small caps lagging the S&P 500 (26 sessions)'));
  assert.ok(busy.includes('TESTED'), 'a tested row carries the TESTED tag');
  assert.ok(busy.includes('AS OF OCT 16, 2026 CLOSE'));
}));

test('an empty macro or earnings list reads as one dim line each, not a gap', () => withBrowser(() => {
  const text = textOf(justOutSection({ session: '2026-10-16', macro: [], earnings: [] }));
  assert.ok(text.includes('No macro release came out last session.'));
  assert.ok(text.includes('No index-weight earnings came out last session.'));
}));

test('the live MOVES list replaces the close, and says it is provisional with the quote time', () => withBrowser(() => {
  const live = { items: [{ ticker: 'MU', name: 'Micron', ret_pct: 4.2, z: 3.1, z_own: 2.6, time: 1800000000 }], time: 1800000000 };
  const text = textOf({ children: unusualNodes(fixture().unusual, { live, asOf: '2026-10-16' }) });
  assert.ok(text.includes('LIVE · PROVISIONAL'));
  assert.ok(text.includes('Micron'));
  assert.ok(!text.includes('NVIDIA fell far beyond'), 'the close list is not shown while live');
  assert.ok(!text.includes('CLOSE'), 'no close stamp while live');
  const none = textOf({ children: unusualNodes(nothing().unusual, { live: { items: [], time: 1800000000 }, asOf: '2026-10-16' }) });
  assert.ok(none.includes('LIVE · PROVISIONAL') && none.includes('Nothing crossed a threshold this session.'));
}));

test('a part the build could not make is a notice, and the page still draws', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderToday(root, fixture(), null, {});
  assert.ok(textOf(root).includes('moves: the moves file did not load'));
}));

test('a page with a moves file that fails keeps the close list and no live feed', async () => {
  // The render is synchronous; the rejected moves load is handled after it.
  const root = await withBrowser(() => {
    const node = new FakeNode('main');
    renderToday(node, fixture(), null, { loadArtifact: () => Promise.reject(new Error('moves.json returned 404')) });
    return node;
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(textOf(root).includes('NVIDIA fell far beyond its usual move'));
});
