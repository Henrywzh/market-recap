// TODAY's figure blocks on synthetic data under node: the signed figures and the
// sparkline path, the board's bars and their order, the chart option and its click,
// the ranked signal list, the movers records and table, and the events left under it.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  moveText, sigmaText, sparkPath, sparkSvg, headlineNode, titleSegments, boardSlots, boardLabel, boardOption, drawBoard, boardCard,
  signalGroups, signalsCard, flowChips, flowDollars, scenarioText, moverRecords, moversTable, sectorLine, remainingEvents, eventNodes,
} from '../../web/js/today-board.js';
import { tickerHref } from '../../web/js/routes.js';

class FakeNode {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.className = '';
    this.textContent = '';
    this.innerHTML = '';
    this.style = {};
    this.listeners = {};
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener() {}
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
}

const fakeDocument = () => ({
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
});

// The text of a node and everything under it, joined by spaces as a reader would see it.
function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(textOf)].filter(Boolean).join(' ');
}

function byClass(node, name, found = []) {
  if (node?.className?.split(' ').includes(name)) found.push(node);
  for (const child of node?.children || []) byClass(child, name, found);
  return found;
}

// Runs a synchronous body with the browser globals a page draw needs, and restores them.
// `echarts` is the chart library stub, or undefined for a page with no chart library.
function withBrowser(body, { echarts } = {}) {
  const saved = {
    document: globalThis.document, window: globalThis.window, getComputedStyle: globalThis.getComputedStyle, location: globalThis.location,
  };
  globalThis.document = fakeDocument();
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
  globalThis.location = { hash: '' };
  globalThis.window = echarts ? { echarts } : {};
  try {
    return body();
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
}

const PALETTE = { text: '#t', dim: '#d', faint: '#f', border: '#b', up: '#u', down: '#dn' };

// Thirteen rows as the build gives them: five indices and eight sector funds.
const ROWS = [
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

const item = (over) => ({
  key: 'k', kind: 'move', date: '2026-10-22', time: null, timing: null, subject: 'X', title: 'A title', detail: null,
  value: null, unit: null, z: null, importance: 'medium', new: true, since: null, days: null, evidence: 'description',
  link: '#catalysts', extra: {}, ...over,
});

test('a signed figure carries a true minus, and a value that rounds to zero carries no sign', () => {
  assert.equal(moveText(-6.79), '−6.8%');
  assert.equal(moveText(3.3061), '+3.3%');
  assert.equal(moveText(-0.04), '0.0%');
  assert.equal(moveText(0), '0.0%');
  assert.equal(moveText(null), '—');
  assert.equal(moveText(undefined), '—');
  assert.equal(moveText(Number.NaN), '—', 'a NaN is a dash, never a number');
  assert.equal(sigmaText(-3.1), '−3.1σ');
  assert.equal(sigmaText(7.89), '+7.9σ');
});

test('the sparkline is a path through the closes, a gap breaks it, and fewer than two closes draw nothing', () => {
  assert.equal(sparkPath([1, 2, 3]), 'M0.0 16.0 L28.0 8.0 L56.0 0.0');
  assert.equal(sparkPath([5, 5]), 'M0.0 16.0 L56.0 16.0', 'a flat series is a flat line');
  assert.equal(sparkPath([1]), null);
  assert.equal(sparkPath([null, 2]), null, 'one close is not a line');
  assert.equal(sparkPath([]), null);
  assert.equal(sparkPath(undefined), null);
  const broken = sparkPath([1, null, 3, 2]);
  assert.match(broken, /^M.*M/, 'the line restarts after a missing close');
  assert.ok(!broken.includes('NaN'));
  assert.equal(sparkSvg([]), '');
  assert.ok(sparkSvg([1, 2]).includes('<path d="M0.0 16.0 L56.0 0.0"/>'));
});

test('the headline is one line toned up, down or flat, and absent when the build has none', () => withBrowser(() => {
  assert.equal(headlineNode(null), null);
  assert.equal(headlineNode({ text: '' }), null);
  const down = headlineNode({ text: 'S&P 500 −1.2%.', tone: 'down' });
  assert.equal(down.className, 'today-headline down');
  assert.equal(down.textContent, 'S&P 500 −1.2%.');
  assert.equal(headlineNode({ text: 'Quiet.', tone: 'sideways' }).className, 'today-headline flat');
}));

test('each sector in the title takes the colour of its own move, not the market\'s', () => {
  const parts = titleSegments('Up day, led by Semis +3.8% and Tech +2.0%; Comm services −1.4% fell', 'up');
  assert.deepEqual(parts, [
    { text: 'Up day', tone: 'up' },
    { text: ', led by ', tone: null },
    { text: 'Semis +3.8%', tone: 'up' },
    { text: ' and ', tone: null },
    { text: 'Tech +2.0%', tone: 'up' },
    { text: '; ', tone: null },
    { text: 'Comm services −1.4%', tone: 'down' },
    { text: ' fell', tone: null },
  ]);
  // A selloff with a sector that rose, a rare move, and a flat day's two lists.
  const down = titleSegments('Selloff, led by Energy −3.1% (rare); Utilities +0.8% rose', 'down');
  assert.deepEqual(down.filter((p) => p.tone).map((p) => [p.text, p.tone]),
    [['Selloff', 'down'], ['Energy −3.1% (rare)', 'down'], ['Utilities +0.8%', 'up']]);
  const flat = titleSegments('Flat day; up: Semis +1.2%; down: Health care −0.9%', 'flat');
  assert.deepEqual(flat.filter((p) => p.tone && p.tone !== 'flat').map((p) => p.tone), ['up', 'down']);
  assert.deepEqual(titleSegments('Up day', 'up'), [{ text: 'Up day', tone: 'up' }]);
});

test('the headline title is drawn in those pieces, the words between them plain', () => withBrowser(() => {
  const node = headlineNode({ title: 'Up day; Comm services −1.4% fell', text: 'S&P 500 +0.6%.', tone: 'up' });
  const title = byClass(node, 'today-headline')[0];
  assert.equal(title.className, 'today-headline up split');
  assert.equal(title.children.map((c) => (c.nodeType === 3 ? c.text : c.textContent)).join(''), 'Up day; Comm services −1.4% fell');
  const spans = title.children.filter((c) => c.className);
  assert.deepEqual(spans.map((c) => [c.textContent, c.className]),
    [['Up day', 'today-headline-up'], ['Comm services −1.4%', 'today-headline-down']]);
}));

test('the board puts the indices first, a gap, then the sectors, each group highest move first', () => {
  const slots = boardSlots(ROWS);
  assert.equal(slots.length, 14, 'thirteen rows and one gap');
  assert.equal(slots[5], null, 'the gap sits between the groups');
  assert.deepEqual(slots.slice(0, 5).map((r) => r.symbol), ['DIA', 'RSP', '^GSPC', 'IWM', '^NDX'], 'indices by move');
  assert.deepEqual(slots.slice(6).map((r) => r.symbol), ['XLP', 'XLU', 'XLE', 'XLY', 'XLF', 'XLC', 'XLK', 'SOXX'], 'sectors by move');
  assert.equal(boardSlots(ROWS.filter((r) => r.group === 'index')).includes(null), false, 'no gap without sectors');
  assert.equal(boardSlots([{ symbol: 'A', group: 'sector', ret_pct: null }, { symbol: 'B', group: 'sector', ret_pct: 1 }]).length, 1, 'a row with no move is left out');
  assert.deepEqual(boardSlots(undefined), []);
});

test('a bar label carries the move, its σ, and the share of days at 5% or fewer (RARE at 1%)', () => {
  const [soxx, xlu] = [ROWS[5], ROWS[11]];
  assert.equal(boardLabel(soxx), `−6.8% · 3.1σ · RARE: ${soxx.share_pct.toFixed(1)}% of days`);
  assert.equal(boardLabel(xlu), '+2.1% · 2.2σ · 3.0% of days', 'uncommon, not rare: the share without RARE');
  assert.equal(boardLabel({ ret_pct: 0.7, z: 0.7, share_pct: 28.8 }), '+0.7% · 0.7σ', 'a common move carries no share');
  assert.equal(boardLabel({ ret_pct: -3.3, z: -2.0, share_pct: 2.31 }), '−3.3% · 2.0σ · 2.3% of days');
  assert.equal(boardLabel({ ret_pct: 1, z: null, share_pct: null }), '+1.0%', 'a missing σ is left out, not zero');
});

test('the chart option has one bar per row, coloured by direction, full strength at |σ| of 2 or more', () => {
  const slots = boardSlots(ROWS);
  const option = boardOption(slots, PALETTE);
  const bars = option.series[0].data;
  assert.equal(bars.length, 14);
  assert.equal(bars.filter((b) => b.value !== null).length, 13, 'the gap is no bar');
  const soxxAt = slots.findIndex((r) => r?.symbol === 'SOXX');
  assert.equal(bars[soxxAt].itemStyle.color, '#dn');
  assert.equal(bars[soxxAt].itemStyle.opacity, 1, '|z| 3.1 is full strength');
  assert.equal(bars[soxxAt].label.position, 'left', 'a fall labels its bar end on the left');
  const xleAt = slots.findIndex((r) => r?.symbol === 'XLE');
  assert.equal(bars[xleAt].itemStyle.color, '#u');
  assert.equal(bars[xleAt].itemStyle.opacity, 0.55, '|z| 0.8 is faded');
  assert.equal(option.series[0].label.formatter({ dataIndex: soxxAt }), '−6.8%', 'the bar end holds the move only');
  assert.equal(option.yAxis[1].data[soxxAt], `{rare|3.1σ · RARE: ${ROWS[5].share_pct.toFixed(1)}% of days}`, 'σ and the share in the right column, RARE accented');
  assert.equal(option.series[0].label.formatter({ dataIndex: 5 }), '', 'the gap has no label');
  assert.equal(option.yAxis[0].data[5], '', 'the gap is an empty row name');
  assert.equal(option.yAxis[1].data[5], '', 'and an empty note');
  assert.equal(option.yAxis[0].data[soxxAt], 'Semis');
  const span = option.xAxis.max;
  assert.equal(option.xAxis.min, -span, 'the axis is symmetric about zero');
  assert.ok(Math.abs(6.79) < span, 'the largest move fits inside the axis');
  const tip = option.tooltip.formatter({ dataIndex: soxxAt });
  assert.ok(tip.includes('Move −6.8% · −3.1σ'), tip);
  assert.ok(tip.includes('Share 0.5% of days at this move or beyond'), tip);
  assert.ok(tip.includes('RSI(6) 20.4'), tip);
  assert.equal(option.tooltip.formatter({ dataIndex: 5 }), '');
});

test('the board chart opens MOVE CHECK for the bar clicked, and a gap click does nothing', () => {
  const handlers = {};
  const charts = [];
  const echarts = {
    init: () => {
      const chart = { option: null, setOption(o) { this.option = o; }, on(name, fn) { handlers[name] = fn; }, dispose() {}, resize() {}, getModel() {} };
      charts.push(chart);
      return chart;
    },
  };
  withBrowser(() => {
    const node = new FakeNode('div');
    drawBoard(node, boardSlots(ROWS));
    assert.equal(charts.length, 1);
    assert.equal(charts[0].option.series[0].data.length, 14);
    handlers.click({ dataIndex: 5 });
    assert.equal(globalThis.location.hash, '', 'the gap opens nothing');
    handlers.click({ dataIndex: 13 });
    assert.equal(globalThis.location.hash, '#movecheck/SOXX');
  }, { echarts });
});

test('the board card: index tiles broad market first, the S&P 500 the lead; sectors as bars; no card without rows', () => withBrowser(() => {
  assert.equal(boardCard({ rows: [] }), null);
  assert.equal(boardCard(null), null);
  const card = boardCard({ rows: ROWS, vix: { value: 19.03, change: 2.35 } });
  const tiles = byClass(card.node, 'today-index');
  const indexRows = ROWS.filter((r) => r.group === 'index');
  assert.equal(tiles.length, indexRows.length + 1, 'one tile per index, plus VIX');
  assert.equal(tiles[0].className, 'today-index lead');
  assert.ok(textOf(tiles[0]).startsWith('S&P 500'));
  assert.ok(textOf(tiles[tiles.length - 1]).includes('VIX'));
  const [chartNode] = byClass(card.node, 'today-board-chart');
  const sectors = ROWS.filter((r) => r.group !== 'index').length;
  assert.equal(chartNode.style.height, `${sectors * 22 + 10}px`, 'sector bars only, at 22px each');
  assert.ok(textOf(card.node).includes('THE DAY') && textOf(card.node).includes('SECTORS'));
  assert.doesNotThrow(() => card.draw());
}));

test('the headline shows the title over the line of figures; an old build without a title shows the line alone', () => withBrowser(() => {
  const node = headlineNode({ title: 'Mega-cap selloff, the average stock held up', text: 'S&P 500 −1.2%.', tone: 'down' });
  assert.equal(node.className, 'today-headline-block');
  assert.equal(byClass(node, 'today-headline')[0].className, 'today-headline down split');
  assert.ok(textOf(node).includes('Mega-cap selloff') && textOf(node).includes('S&P 500 −1.2%.'));
}));

test('the signal groups come in the order OVERSOLD, RARE, CHANGED, SCENARIO, ONGOING, with the build names and links', () => {
  const unusual = {
    oversold: [item({ kind: 'oversold', subject: 'Semiconductors (SOXX)', title: 'Semis oversold', detail: 'How stretched.', link: '#technicals/SOXX', value: 20.4, extra: { symbol: 'SOXX', rsi: 20.4, line: 20 } })],
    tails: [item({ kind: 'tail', subject: 'Consumer staples (XLP)', title: 'XLP rose 3.3%', value: 3.3, unit: '%', detail: 'Rare.', link: '#movecheck/XLP', extra: { symbol: 'XLP', share_pct: 0.4 } })],
    states: [item({ kind: 'risk', subject: 'MOVE', title: 'Treasuries · technical: MOVE moved to elevated (elevated from 100)', extra: { active: true } })],
    watch: [
      item({ kind: 'watch', subject: 'Oil supply shock', title: 'Oil supply shock near its trigger', link: '#watch', extra: { state: 'near', value: 113, threshold: 120 } }),
      item({ kind: 'watch', subject: 'Buyback', title: 'Buyback', link: '#watch', extra: { state: 'triggered' } }),
    ],
    ongoing: [item({ kind: 'market_state', subject: 'SMALL CAPS LAGGING', title: 'Small caps lagging has held for 30 sessions', days: 30, link: '#markets' })],
  };
  const groups = signalGroups(unusual, ROWS);
  assert.deepEqual(groups.map((g) => g.label), ['OVERSOLD', 'RARE', 'CHANGED', 'SCENARIO', 'ONGOING']);
  const [oversold, rare, changed, scenario, ongoing] = groups.map((g) => g.chips);
  assert.deepEqual(oversold.map((c) => c.text), ['Semis 20.4']);
  assert.equal(oversold[0].href, '#technicals/SOXX');
  assert.equal(oversold[0].title, 'How stretched.', 'the detail is the tooltip, not body text');
  assert.equal(oversold[0].tone, 'down', 'below 20 is the deeper tone');
  assert.deepEqual(rare.map((c) => c.text), ['Staples +3.3% · 0.4%']);
  assert.equal(rare[0].href, '#movecheck/XLP');
  assert.deepEqual(changed.map((c) => c.text), ['MOVE moved to elevated'], 'the state after the colon, the build note left out');
  assert.equal(changed[0].title, 'Treasuries · technical: MOVE moved to elevated (elevated from 100)', 'the full title is the tooltip');
  // The list is ranked: a triggered scenario (severity 5) comes before a near one (2).
  assert.deepEqual(scenario.map((c) => c.text), ['Buyback · triggered', 'Oil supply shock 113 ≥ 120']);
  assert.equal(scenario[0].tone, 'down');
  assert.equal(scenario[1].state, 'NEAR');
  assert.equal(scenario[1].distance, 'needs 7.0 more to 120');
  assert.deepEqual(ongoing.map((c) => c.text), ['SMALL CAPS LAGGING · 30 sessions']);
});

test('a group with no chip is left out, and nothing at all gives no groups', () => {
  assert.deepEqual(signalGroups({ oversold: [], tails: [] }, ROWS), []);
  assert.deepEqual(signalGroups(undefined, undefined), []);
  const groups = signalGroups({ ongoing: [item({ subject: 'Buyback blackout', value: 84.8, unit: '%', days: null })] }, []);
  assert.deepEqual(groups.map((g) => g.label), ['ONGOING']);
  assert.equal(groups[0].chips[0].text, 'Buyback blackout · 84.8%');
});

test('the signals card is one ranked list, a row per signal with its state, group and distance; none says so', () => withBrowser(() => {
  const groups = signalGroups({ oversold: [item({ subject: 'XLK', value: 28, extra: { rsi: 28, line: 30 } })], ongoing: [item({ subject: 'A' })] }, ROWS);
  const card = signalsCard(groups);
  const rows = byClass(card, 'today-signal');
  assert.equal(rows.length, 2);
  assert.equal(byClass(rows[0], 'sig-badge')[0].textContent, 'NEW', 'the NEW oversold ranks above the ongoing one');
  assert.equal(byClass(rows[0], 'sig-group')[0].textContent, 'OVERSOLD');
  assert.equal(byClass(rows[1], 'sig-badge')[0].textContent, 'ONGOING');
  assert.ok(textOf(rows[0]).includes('RSI 28.0 · 2.0 below 30'), 'the distance to the line is printed');
  assert.equal(byClass(card, 'sig-mute').length, 2, 'each row has its × to mute it');
  assert.ok(textOf(signalsCard([])).includes('No signal this session.'));
}));

test('a muted signal is hidden under "show N muted" until shown; the muted keys come from storage', () => withBrowser(() => {
  const groups = signalGroups({ ongoing: [item({ key: 'ongoing:A', subject: 'A' }), item({ key: 'ongoing:B', subject: 'B' })] }, ROWS);
  const saved = globalThis.localStorage;
  globalThis.localStorage = { getItem: () => JSON.stringify(['ongoing:A']), setItem() {} };
  try {
    const card = signalsCard(groups);
    const rows = byClass(card, 'today-signal');
    assert.equal(rows.length, 1, 'the muted row is hidden');
    assert.ok(textOf(rows[0]).includes('B'));
    assert.equal(byClass(card, 'sig-more')[0].textContent, 'show 1 muted');
  } finally {
    globalThis.localStorage = saved;
  }
}));

test('the movers records come from the build, with the reporter flag, or from the live rows with the same flag', () => {
  const unusual = {
    moves: [item({ subject: 'NVDA', z: -3.4, link: '#ticker/NVDA', extra: { ret_pct: -6.1, own_pct: -5.2, market_pct: -0.9, sector_pct: -0.4, earnings: true, spark: [1, 2] } })],
  };
  const [built] = moverRecords(unusual, null);
  assert.deepEqual(built, { ticker: 'NVDA', href: '#ticker/NVDA', move: -6.1, z: -3.4, own: -5.2, market: -0.9, sector: -0.4, spark: [1, 2], earnings: true });
  const live = [{ ticker: 'NVDA', ret_pct: -4, z: -2.5, own_pct: -3, z_own: -2 }, { ticker: 'MU', ret_pct: 4.2, z: 3.1, own_pct: 3, z_own: 2.6 }];
  const [nvda, mu] = moverRecords(unusual, live);
  assert.equal(nvda.earnings, true, 'a live reporter keeps its flag');
  assert.equal(nvda.market, null, 'the live rows carry no market part');
  assert.equal(nvda.spark, null);
  assert.equal(mu.href, tickerHref('MU'));
  assert.equal(mu.earnings, false);
});

test('the movers table: bold past 3σ, E on a reporter, the market and sector parts, a sparkline, and no tags', () => withBrowser(() => {
  const records = [
    { ticker: 'NVDA', href: '#ticker/NVDA', move: -6.1, z: -3.4, own: -5.2, market: -0.9, sector: -0.4, spark: [10, 10.5, null, 11, 9.8], earnings: true },
    { ticker: 'CSX', href: '#ticker/CSX', move: 2.1, z: 2.2, own: 1.9, market: null, sector: null, spark: [], earnings: false },
  ];
  const root = moversTable(records);
  const [table] = byClass(root, 'today-movers');
  const headers = byClass(table, 'today-movers').length ? textOf(table.children[0]) : '';
  assert.ok(headers.includes('TICKER') && headers.includes('OWN PART') && headers.includes('MARKET / SECTOR') && headers.includes('SPARK'));
  const [tbody] = table.children.slice(-1);
  const [nvda, csx] = tbody.children;
  assert.equal(nvda.className, 'is-strong', 'beyond 3σ is bold');
  assert.equal(csx.className, '', 'under 3σ is not');
  const badge = byClass(nvda, 'tag-info')[0];
  assert.equal(badge.textContent, 'E');
  assert.equal(byClass(csx, 'tag-info').length, 0, 'no E without a reporter flag');
  const cells = nvda.children;
  assert.equal(cells[4].textContent, '−0.9% / −0.4%');
  assert.equal(cells[5].innerHTML.includes('<svg'), true, 'the sparkline is drawn');
  assert.equal(csx.children[4].textContent, '—', 'no market or sector part is a dash');
  assert.equal(csx.children[5].innerHTML, '', 'no closes, no sparkline');
  const text = textOf(root);
  assert.ok(!/\bHIGH\b/.test(text) && !text.includes('TESTED'), 'no HIGH or TESTED tag');
  assert.ok(!text.includes('NaN') && !text.includes('undefined'));
}));

test('the sector sell-off is one line above the table, and the events left are not the movers or the sell-off', () => withBrowser(() => {
  const unusual = {
    moves: [item({ subject: 'ALLE' })],
    events: [
      item({ kind: 'sector_selloff', subject: 'Semis', title: 'Semis fell 6.8% with the group', link: '#sectors' }),
      item({ kind: 'reaction', subject: 'ALLE', title: 'ALLE rose after its report', z: 7.9 }),
      item({ kind: 'monitor', subject: 'MONITOR queue', title: 'Monitor queue backed up', z: null }),
    ],
  };
  const line = sectorLine(unusual);
  assert.equal(line.textContent, 'Semis fell 6.8% with the group');
  assert.equal(line.tagName, 'A');
  assert.equal(sectorLine({ events: [] }), null);
  assert.deepEqual(remainingEvents(unusual).map((i) => i.subject), ['MONITOR queue']);
}));

test('the events under the table show six and fold the rest', () => withBrowser(() => {
  const events = Array.from({ length: 8 }, (_, i) => item({ kind: 'monitor', subject: `M${i}`, title: `Monitor ${i}`, z: i === 0 ? 2.5 : null }));
  const nodes = eventNodes(events);
  assert.equal(nodes.length, 7, 'six rows and one fold');
  assert.equal(nodes[6].className, 'today-more');
  assert.equal(nodes[6].children[0].textContent, '2 more');
  assert.equal(nodes[0].children[1].textContent, '+2.5σ', 'a σ value where the build has one');
  assert.equal(eventNodes([]).length, 0);
}));

test('ETF flow chips: the US equity week with its rank, then the funds in and out, each linking to FLOWS', () => {
  const flows = { date: '2026-10-22', us_equity_1w: -11.38e9, us_equity_1w_pct_rank: 11, top_in: [['SOXX', 4.39e9]], top_out: [['IWM', -5.07e9], ['XLE', -3.1e8]] };
  const chips = flowChips(flows);
  assert.deepEqual(chips.map((c) => c.text), ['US equity 1W −$11.4bn · 11th pct', 'SOXX +$4.4bn', 'IWM −$5.1bn', 'XLE −$310m']);
  assert.deepEqual(chips.map((c) => c.tone), ['down', 'up', 'down', 'down']);
  assert.ok(chips.every((c) => c.href === '#flows'));
  const groups = signalGroups({}, [], flows);
  assert.deepEqual(groups.map((g) => g.label), ['ETF FLOWS']);
  assert.deepEqual(flowChips(null), []);
  assert.deepEqual(flowChips({ us_equity_1w: null }), []);
  assert.equal(flowDollars(null), '—');
});

test('read live, the headline, the board and the signals carry the blinking LIVE mark with the quote time', () => withBrowser(() => {
  const headline = headlineNode({ title: 'Down day', text: 'S&P 500 −0.5%.', tone: 'down' }, '14:32 ET quotes');
  assert.equal(byClass(headline, 'live-badge').length, 1);
  assert.match(textOf(headline), /LIVE · SO FAR TODAY\s+14:32 ET quotes/);
  assert.equal(byClass(signalsCard([], '14:32 ET quotes'), 'live-badge').length, 1);
  assert.equal(byClass(headlineNode({ title: 'Down day', text: 'x', tone: 'down' }), 'live-badge').length, 0);
}));

test('a scenario chip reads its trigger in its unit: the figure, the side, the threshold', () => {
  assert.equal(scenarioText({ subject: 'Oil spike', extra: { value: 113.4, threshold: 120, unit: '$', op: 'above', measure: 'level' } }), 'Oil spike $113 ≥ $120');
  assert.equal(scenarioText({ subject: 'Curve', extra: { value: 0.95, threshold: 1.0, unit: '', op: 'above', measure: 'level' } }), 'Curve 0.95 ≥ 1.00');
  assert.equal(scenarioText({ subject: 'Spreads', extra: { value: 42, threshold: 50, unit: 'bp', op: 'above', measure: 'change' } }), 'Spreads +42.0bp ≥ 50.0bp');
  assert.equal(scenarioText({ subject: 'Old', extra: { state: 'triggered' } }), 'Old · triggered');
});
