// The TODAY page on a fixture today.json, under node against a small fake DOM:
// the sections and their headings, the empty-state and ongoing lines, the
// coming-up days, the tags, the live MOVES list, the route label, and a full
// render with the live feeds stubbed out.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import renderToday, { dayLabel, whenText, moversNodes, comingUpSection, justOutSection, median, epsVerdict, earningsSummary, forecastOf, surpriseDirection } from '../../web/js/tabs/today.js';
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
  const saved = { document: globalThis.document, window: globalThis.window, setTimeout: globalThis.setTimeout, setInterval: globalThis.setInterval, clearInterval: globalThis.clearInterval };
  globalThis.document = fakeDocument();
  // No ECharts here: the board's chart draws nothing, and the page still builds.
  globalThis.window = {};
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
    macro: [
      item({ subject: 'CPI', title: 'CPI: CPI 3.4%', value: 3.4, unit: '%', detail: 'For 2026-09-01', importance: 'high', time: '08:30',
        extra: { expectations: [{ kind: 'survey', value: 3.2, unit: '%', decimals: 1, source: 'Survey' }] } }),
      item({ kind: 'expiry', subject: 'Monthly options expiry', title: 'Monthly options expiry settled this session', importance: 'medium' }),
    ],
    earnings: [item({ kind: 'earnings', subject: 'TRV', title: 'TRV beat expected EPS: 9.18 against 7.07', link: '#ticker/TRV', z: 0.9, extra: { eps: 9.18, return_1d: 1.47, surprise_pct: 29.84, weight: 0.12 } })],
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

// The page with the figure blocks: the board, the headline, the signal chips and the
// movers' earnings flags and sparklines, as the build now gives them.
const BOARD_ROWS = [
  { symbol: '^GSPC', label: 'S&P 500', short: 'S&P 500', group: 'index', ret_pct: -1.2, z: -1.9, share_pct: 30.1, rsi6: 41.0 },
  { symbol: '^NDX', label: 'Nasdaq-100', short: 'Nasdaq-100', group: 'index', ret_pct: -2.9, z: -3.4, share_pct: 4.1, rsi6: 27.2 },
  { symbol: 'DIA', label: 'Dow (DIA)', short: 'Dow', group: 'index', ret_pct: -0.8, z: -1.2, share_pct: 20.0, rsi6: 44.0 },
  { symbol: 'IWM', label: 'Russell 2000 (IWM)', short: 'Russell 2000', group: 'index', ret_pct: -1.5, z: -2.0, share_pct: 8.0, rsi6: 35.0 },
  { symbol: 'RSP', label: 'S&P 500 equal weight (RSP)', short: 'Equal weight', group: 'index', ret_pct: -1.0, z: -1.5, share_pct: 25.0, rsi6: 38.0 },
  { symbol: 'SOXX', label: 'Semiconductors (SOXX)', short: 'Semis', group: 'sector', ret_pct: -6.79, z: -3.1, share_pct: 0.5, rsi6: 20.4 },
  { symbol: 'XLK', label: 'Technology (XLK)', short: 'Tech', group: 'sector', ret_pct: -3.27, z: -2.4, share_pct: 2.3, rsi6: 28.0 },
  { symbol: 'XLC', label: 'Communication services (XLC)', short: 'Comm services', group: 'sector', ret_pct: -1.9, z: -1.6, share_pct: 12.0, rsi6: 25.1 },
  { symbol: 'XLF', label: 'Financials (XLF)', short: 'Financials', group: 'sector', ret_pct: -0.5, z: -0.6, share_pct: 40.0, rsi6: 45.0 },
  { symbol: 'XLY', label: 'Consumer discretionary (XLY)', short: 'Discretionary', group: 'sector', ret_pct: -0.2, z: -0.3, share_pct: 45.0, rsi6: 50.0 },
  { symbol: 'XLE', label: 'Energy (XLE)', short: 'Energy', group: 'sector', ret_pct: 0.9, z: 0.8, share_pct: 35.0, rsi6: 55.0 },
  { symbol: 'XLU', label: 'Utilities (XLU)', short: 'Utilities', group: 'sector', ret_pct: 2.1, z: 2.2, share_pct: 3.0, rsi6: 70.0 },
  { symbol: 'XLP', label: 'Consumer staples (XLP)', short: 'Staples', group: 'sector', ret_pct: 3.3, z: 3.0, share_pct: 0.4, rsi6: 75.0 },
];

const HEADLINE = 'S&P 500 −1.2%, Nasdaq-100 −2.9%. Weakest: Semis −6.8% (rare: 0.5% of days), Tech −3.3%. Strongest: Staples +3.3%, Utilities +2.1%. VIX 19.0 (+2.4).';

// The fixture with the new payload keys: the board, the headline, the signal kinds,
// and the movers' earnings flags and sparklines.
const pageFixture = () => {
  const data = fixture();
  data.board = { as_of: '2026-10-16', rows: BOARD_ROWS, vix: { value: 19.03, change: 2.35 } };
  data.headline = { text: HEADLINE, tone: 'down' };
  data.unusual.moves = [item({
    kind: 'move', subject: 'NVDA', title: 'NVIDIA fell far beyond its usual move', z: -3.4, evidence: 'tested', importance: 'high', link: '#ticker/NVDA',
    extra: { ret_pct: -6.1, own_pct: -5.2, market_pct: -0.9, sector_pct: -0.4, earnings: true, spark: [10, 10.5, null, 11, 9.8] },
  }), item({
    kind: 'move', subject: 'CSX', title: 'CSX rose 2.1%, 2.2 times its usual move', z: 2.2, importance: 'medium', link: '#ticker/CSX',
    extra: { ret_pct: 2.1, own_pct: 1.9, market_pct: -0.2, sector_pct: 0.1, spark: [] },
  })];
  data.unusual.oversold = [item({
    kind: 'oversold', subject: 'Semiconductors (SOXX)', title: 'Semiconductors (SOXX) oversold: first close below 30 on RSI(6)', value: 20.4,
    detail: 'How stretched the fall is, not a rebound call.', link: '#technicals/SOXX', extra: { symbol: 'SOXX', rsi: 20.4, line: 20 },
  })];
  data.unusual.tails = [item({
    kind: 'tail', subject: 'Consumer staples (XLP)', title: 'Consumer staples (XLP) rose 3.3% today', value: 3.3, unit: '%',
    detail: 'How rare in its own history.', link: '#movecheck/XLP', extra: { symbol: 'XLP', share_pct: 0.4 },
  })];
  data.just_out.earnings = [
    item({ kind: 'earnings', subject: 'TRV', title: 'TRV beat expected EPS: 9.18 against 7.07', link: '#ticker/TRV', extra: { eps: 9.18, return_1d: 1.47, surprise_pct: 29.84, weight: 0.12 } }),
    ...['WDC', 'NEM', 'BE', 'FIX', 'VRSN', 'OMC', 'DECK'].map((name, i) => item({
      kind: 'earnings', subject: name, title: `${name} reports after the close`, timing: 'amc', link: `#ticker/${name}`, importance: 'low',
      extra: { eps: null, weight: 0.2 - i * 0.02, eps_forecast: 1.2 },
    })),
  ];
  return data;
};

// Every node under a root whose class names the given class.
function byClass(node, name, found = []) {
  if (node?.className?.split(' ').includes(name)) found.push(node);
  for (const child of node?.children || []) byClass(child, name, found);
  return found;
}

const BAD = /NaN|undefined|\[object Object\]/;

test('the page reads headline first, then the board card, then signals, movers and the columns', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderToday(root, pageFixture(), null, {});
  const page = root.children[0];
  const order = page.children.map((child) => child.className || child.tagName);
  const at = (cls) => order.findIndex((c) => String(c).split(' ').includes(cls));
  // The headline and the board sit in hosts the live board repaints in place.
  assert.ok(at('today-headline-host') > at('today-live'), 'the headline follows the live strip');
  assert.ok(at('today-board-host') > at('today-headline-host'), 'the board card follows the headline');
  assert.ok(at('today-columns') > at('today-board-host'), 'the two columns follow the board');
  assert.equal(byClass(root, 'live-badge').filter((n) => !n.hidden).length, 0, 'the close carries no LIVE mark');
  const text = textOf(root);
  assert.ok(text.includes(HEADLINE), 'the headline is the build text');
  assert.equal(byClass(root, 'today-headline')[0].className, 'today-headline down');
  assert.ok(text.includes('THE DAY') && text.includes('SECTORS'));
  assert.ok(byClass(root, 'today-index').length >= 2, 'the indices are tiles');
  assert.equal(byClass(root, 'today-index').filter((n) => n.className === 'today-index lead').length, 1, 'the S&P 500 is the lead tile');
  assert.ok(byClass(root, 'today-board-chart').length === 1);
  assert.doesNotMatch(text, BAD);
}));

test('the page draws the title, the section headings, the coming-up days and LATER', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderToday(root, fixture(), null, {});
  const text = textOf(root);
  for (const heading of ['TODAY', 'JUST OUT', 'COMING UP', 'UNUSUAL NOW', 'MOVERS']) assert.ok(text.includes(heading), `missing ${heading}`);
  assert.ok(text.includes('MON OCT 19') && text.includes('TUE OCT 20') && text.includes('WED OCT 21'));
  assert.ok(text.includes('LATER · HIGH IMPORTANCE · TO SUN NOV 1'));
  assert.ok(text.includes('FITB') && text.includes('implied ±4.2%'), 'a coming-up row is its subject and its figure');
  assert.ok(text.includes('CPI') && text.includes('3.40%') && text.includes('VS FORECAST') && text.includes('3.20%'), 'the macro table carries the actual and the forecast');
  assert.ok(text.includes('Also: Monthly options expiry'), 'a release with no number is named on one line');
  assert.ok(text.includes('TRV') && text.includes('BEAT') && text.includes('+29.8%') && text.includes('+1.5%'), 'the earnings tile carries the verdict, surprise and move');
  assert.ok(text.includes('SESSION CLOSE · OCT 16, 2026'), 'the header carries the session close');
}));

test('a day with no items, an empty movers list and the empty signals read as the page says', () => withBrowser(() => {
  const text = textOf(comingUpSection(fixture().coming_up));
  assert.ok(text.includes('Nothing on the calendar this session that matters here.'));
  const quiet = textOf({ children: moversNodes(nothing().unusual, { live: null, asOf: '2026-10-16' }) });
  assert.ok(quiet.includes('Nothing crossed a threshold this session.'));
  assert.ok(!quiet.includes('NVDA'), 'no mover, no table');
  const busy = textOf({ children: moversNodes(fixture().unusual, { live: null, asOf: '2026-10-16' }) });
  assert.ok(busy.includes('NVDA') && busy.includes('AS OF OCT 16, 2026 CLOSE'));
  assert.ok(!busy.includes('TESTED'), 'no tag beyond the E badge');
  assert.ok(moversNodes(fixture().unusual, { live: null, asOf: '2026-10-16' }).every(Boolean), 'no null node: replaceChildren would print it');
  const signals = new FakeNode('main');
  renderToday(signals, nothing(), null, {});
  assert.ok(textOf(signals).includes('No signal this session.'));
}));

test('an empty macro or earnings list reads as one dim line each, not a gap', () => withBrowser(() => {
  const text = textOf(justOutSection({ session: '2026-10-16', macro: [], earnings: [] }));
  assert.ok(text.includes('No macro release came out last session.'));
  assert.ok(text.includes('No index-weight earnings came out last session.'));
}));

test('the live MOVERS list replaces the close, and says it is provisional with the quote time', () => withBrowser(() => {
  const live = { items: [{ ticker: 'MU', name: 'Micron', ret_pct: 4.2, z: 3.1, own_pct: 3.0, z_own: 2.6, time: 1800000000 }], time: 1800000000 };
  const text = textOf({ children: moversNodes(fixture().unusual, { live, asOf: '2026-10-16' }) });
  assert.ok(text.includes('LIVE · PROVISIONAL'));
  assert.ok(text.includes('MU'), 'the live row is the ticker');
  assert.ok(!text.includes('NVDA'), 'the close list is not shown while live');
  assert.ok(!text.includes('CLOSE'), 'no close stamp while live');
  const none = textOf({ children: moversNodes(nothing().unusual, { live: { items: [], time: 1800000000 }, asOf: '2026-10-16' }) });
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
  assert.ok(textOf(root).includes('NVDA'));
});

test('the median is the middle value, the mean of the middle two, or null when there is none', () => {
  assert.equal(median([3, 1, 2]), 2);
  assert.equal(median([4, 1, 3, 2]), 2.5);
  assert.equal(median([null, 0.4, undefined, 0.6]), 0.5, 'missing moves are left out, not read as zero');
  assert.equal(median([]), null);
});

test('an EPS surprise reads as BEAT, MISS or IN LINE, and a missing one gets no verdict', () => {
  assert.deepEqual(epsVerdict(2.1), { word: 'BEAT', tone: 'up' });
  assert.deepEqual(epsVerdict(-0.85), { word: 'MISS', tone: 'down' });
  assert.deepEqual(epsVerdict(0), { word: 'IN LINE', tone: 'flat' });
  assert.equal(epsVerdict(null), null);
});

test('the earnings summary counts every reporter, its beats and misses, the median move and the heaviest weight', () => {
  const reporters = [
    item({ kind: 'earnings', subject: 'TRV', extra: { surprise_pct: 29.8, return_1d: 1.47, weight: 0.12 } }),
    item({ kind: 'earnings', subject: 'TFC', extra: { surprise_pct: -0.85, return_1d: 1.07, weight: 0.085 } }),
    item({ kind: 'earnings', subject: 'MTB', extra: { surprise_pct: 2.01, return_1d: -1.54, weight: 0.047 } }),
    item({ kind: 'earnings', subject: 'CFG', extra: { surprise_pct: 2.17, return_1d: -0.11, weight: 0.04 } }),
    item({ kind: 'earnings', subject: 'RF', extra: { surprise_pct: 8.96, return_1d: 0.51, weight: 0.035 } }),
  ];
  assert.equal(earningsSummary(reporters), '5 reported · 4 beat · 1 miss · median move +0.5% · largest weight: TRV');
  assert.equal(earningsSummary([]), null);
  assert.equal(earningsSummary([item({ kind: 'earnings', subject: 'XYZ', extra: {} })]), '1 reported · 0 beat · 0 miss');
});

test('the forecast is the survey row, and the surprise is read only when the units match', () => {
  const survey = { kind: 'survey', value: 3.2, unit: '%' };
  const model = { kind: 'model', value: 9, unit: '%' };
  assert.equal(forecastOf(item({ extra: { expectations: [model, survey] } })), survey);
  assert.equal(forecastOf(item({ extra: { expectations: [model] } })), null, 'a model row is not a forecast');
  assert.equal(surpriseDirection(item({ value: 3.4, unit: '%', extra: { expectations: [survey] } })), 'above');
  assert.equal(surpriseDirection(item({ value: 3.2, unit: '%', extra: { expectations: [survey] } })), 'in-line');
  assert.equal(surpriseDirection(item({ value: 3.4, unit: '%', extra: { expectations: [] } })), null, 'no forecast, no colour');
  assert.equal(surpriseDirection(item({ value: 3.4, unit: 'bp', extra: { expectations: [survey] } })), null, 'mixed units are not compared');
});

test('the earnings tiles lead with the heaviest reporter, fold past eight, and scale the bar to the largest move', () => withBrowser(() => {
  const earnings = Array.from({ length: 10 }, (_, i) => item({
    kind: 'earnings', subject: `T${i}`, link: `#ticker/T${i}`, extra: { eps: 1, weight: 1 + i, surprise_pct: 1, return_1d: i === 0 ? 4 : 1 },
  }));
  const root = justOutSection({ session: '2026-10-16', macro: [], earnings });
  const grids = byClass(root, 'today-tiles');
  assert.equal(grids.length, 2, 'one grid of eight, one folded grid of the rest');
  assert.equal(grids[0].children.length, 8);
  assert.equal(grids[1].children.length, 2);
  assert.ok(textOf(root).includes('2 more'), 'the two lightest reporters are folded');
  assert.ok(textOf(grids[0].children[0]).includes('T9'), 'heaviest first');
  assert.ok(!textOf(grids[0].children[0]).includes('T0'));
  const fills = byClass(root, 'today-tile-bar-fill');
  assert.equal(fills[0].style.width, '25%', 'T9 moved 1 against the set largest of 4 (T0)');
  assert.equal(fills[9].style.width, '100%', 'T0 is the largest move');
}));

test('after-close reporters without a result collapse into one line of names by weight, not tiles', () => withBrowser(() => {
  const root = justOutSection(pageFixture().just_out);
  assert.equal(byClass(root, 'today-tile').length, 1, 'only TRV has a result');
  const pending = byClass(root, 'today-pending');
  assert.equal(pending.length, 1);
  const line = textOf(pending[0]).replace(/\s+/g, ' ').replace(/ ,/g, ',');
  assert.ok(line.startsWith('7 report after the close: WDC, NEM, BE, FIX, VRSN, OMC, DECK'), line);
  assert.ok(line.endsWith('— results in the next build'));
  assert.equal(byClass(pending[0], 'today-tile').length, 0);
}));

test('the page shows the signal chips by kind and the E badge on a reporter, with no HIGH or TESTED tags', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderToday(root, pageFixture(), null, {});
  const rows = byClass(root, 'today-chips');
  assert.equal(rows.length, 3, 'OVERSOLD, RARE and ONGOING have chips; CHANGED and SCENARIO are empty');
  assert.equal(byClass(root, 'chip').length, 3, 'one chip per signal');
  const movers = textOf(byClass(root, 'today-movers-host')[0] || root);
  assert.ok(!/\bHIGH\b/.test(movers) || movers.includes('LATER'), 'no HIGH tag in the movers');
  assert.ok(!textOf(byClass(root, 'today-movers')[0] || root).includes('TESTED'));
  const badges = byClass(root, 'tag-info').filter((n) => n.textContent === 'E');
  assert.equal(badges.length, 1, 'NVDA is a reporter and CSX is not');
  assert.doesNotMatch(textOf(root), BAD);
}));

test('LATER shows the priced move and EPS forecast as figures, not the sentence', async () => {
  const { expectedOf } = await import('../../web/js/tabs/today.js');
  assert.equal(expectedOf({ detail: 'EPS forecast 2.94; options price a 8.2% move' }), '±8.2% · EPS 2.94');
  assert.equal(expectedOf({ detail: 'EPS forecast 0.87' }), 'EPS 0.87');
  assert.equal(expectedOf({ detail: 'Expected: Kalshi P(hike) 6%; Polymarket P(hike) 6%' }), 'Kalshi P(hike) 6%; Polymarket…');
  assert.equal(expectedOf({ detail: null }), '—');
});
