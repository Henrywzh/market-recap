// The single-ticker TECHNICALS view with candles, rendered under node against a
// small fake DOM and a stub ECharts that keeps each chart's option. The checks:
// candles and volume on a ticker with bars, the MA chips and the stat strip,
// a range the bars do not reach falling back to a line with its note, LOG, the
// LINE toggle, and a ticker without bars offering no candles.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { renderSingleTicker } from '../../web/js/tabs/technicals.js';
import * as T from '../../web/js/technicals-math.js';

class FakeNode {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this.parent = null;
    this.hidden = false;
  }
  setAttribute(key, value) {
    this.attrs[key] = String(value);
    if (key === 'value') this.value = String(value);
  }
  getAttribute(key) { return this.attrs[key]; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type, event = {}) { (this.listeners[type] || []).forEach((fn) => fn({ type, ...event })); }
  adopt(node) { if (node && node.nodeType === 1) node.parent = this; return node; }
  append(...nodes) { this.children.push(...nodes.map((n) => this.adopt(n))); }
  replaceChildren(...nodes) { this.children = nodes.map((n) => this.adopt(n)); }
  replaceWith(node) {
    const siblings = this.parent.children;
    siblings[siblings.indexOf(this)] = node;
    node.parent = this.parent;
  }
  focus() {}
  querySelector(selector) { return descendants(this).find((n) => n.className?.split(' ').includes(selector.slice(1))) || null; }
}

const descendants = (node) => (node.children || []).flatMap((child) => (child.nodeType === 1 ? [child, ...descendants(child)] : []));
const textOf = (node) => (node.nodeType === 3 ? node.text
  : [node.textContent || '', ...(node.children || []).map(textOf)].join(' '));
const buttonNamed = (root, label) => descendants(root).find((n) => n.tagName === 'BUTTON' && n.textContent === label);
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

// A weekday calendar from 2016 with a gentle uptrend, the last 520 sessions as bars.
function fixture(sessions = 2600, bars = 520) {
  const dates = [];
  const day = new Date(Date.UTC(2016, 0, 4));
  while (dates.length < sessions) {
    if (day.getUTCDay() % 6 !== 0) dates.push(day.toISOString().slice(0, 10));
    day.setUTCDate(day.getUTCDate() + 1);
  }
  const close = dates.map((_, i) => 50 + i * 0.05 + Math.sin(i / 7) * 4);
  const tail = (values) => values.slice(-bars);
  const ohlcvDates = tail(dates);
  const ohlcvClose = tail(close).map((v) => Number(v.toFixed(2)));
  const volume = ohlcvClose.map((_, i) => (i === 300 ? null : 1e6 + ((i * 7919) % 500000)));
  return {
    ticker: 'TST', as_of: dates[dates.length - 1], first_session: dates[0], sessions, dates, close,
    ohlcv: {
      dates: ohlcvDates,
      open: ohlcvClose.map((v, i) => Number((v - 0.3 + (i % 3) * 0.1).toFixed(2))),
      high: ohlcvClose.map((v) => Number((v + 1).toFixed(2))),
      low: ohlcvClose.map((v) => Number((v - 1).toFixed(2))),
      close: ohlcvClose,
      volume,
    },
  };
}

const data = (available) => ({
  available,
  note: 'A note.',
  defaults: {
    ma_periods: [20, 50, 200], zscore_window: 200, forward_return_days: 40, band_sigma: 1.5,
    slope_window: 20, single_ticker_period: '1Y', rsi: { period: 6 },
  },
  periods: { '6M': 126, '1Y': 252, '2Y': 504, '3Y': 756, '5Y': 1260, '10Y': 2520 },
});

// The globals stay installed for the file: a click after the render builds nodes.
// Each file runs in its own node process, so nothing else sees them.
let served = {};
const charts = [];
globalThis.document = {
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
  documentElement: new FakeNode('html'),
};
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.window = {
  echarts: {
    init: (node) => {
      // A full setOption replaces the option; a partial one merges, as ECharts does.
      const handlers = {};
      const chart = {
        setOption(option, notMerge) { node.option = notMerge || !node.option ? option : { ...node.option, ...option }; },
        on(type, fn) { handlers[type] = fn; },
        getModel: () => undefined, resize() {}, dispose() {},
      };
      charts.push({ node, chart, handlers });
      return chart;
    },
  },
};
globalThis.fetch = async (url) => {
  const key = url.split('/').pop().replace('.json', '');
  if (!served[key]) return { ok: false, json: async () => ({}) };
  return { ok: true, json: async () => served[key] };
};

// Renders the single-ticker view for `payloads` (symbol → payload) and returns the root and the charts.
async function mount(payloads, symbol = 'TST') {
  served = payloads;
  charts.length = 0;
  const root = new FakeNode('main');
  await renderSingleTicker(root, data(Object.keys(payloads)), { symbol });
  await flush();
  return { root, charts };
}

// The option of the price chart: the node with the tall chart class.
const priceOption = (charts) => charts.find(({ node }) => node.className === 'chart price-tall').node.option;
// The handlers of the latest price chart: a re-render makes a new chart on the same node.
const priceHandlers = (charts) => [...charts].reverse().find(({ node }) => node.className === 'chart price-tall').handlers;

test('a ticker with bars opens on candles: OHLC, a volume pane and the moving averages on the candles', async () => {
  const { root, charts } = await mount({ TST: fixture() });
  const option = priceOption(charts);
  assert.equal(option.grid.length, 2);
  assert.ok(option.series.some((s) => s.type === 'candlestick'));
  const volume = option.series.find((s) => s.name === 'Volume');
  assert.equal(volume.type, 'bar');
  assert.equal(volume.xAxisIndex, 1);
  assert.deepEqual(option.series.filter((s) => s.name.startsWith('SMA ')).map((s) => s.name), ['SMA 20', 'SMA 50', 'SMA 200']);
  assert.deepEqual(option.legend.data, ['±1.5σ band', 'SMA 20', 'SMA 50', 'SMA 200']);
  assert.equal(volume.data.length, option.xAxis[0].data.length);
  assert.equal(volume.data.filter((v) => v === null).length, 1, 'the missing bar is a gap, not a zero');
  assert.match(textOf(root), /PRICE, CANDLES/);
  assert.doesNotMatch(textOf(root), /NaN|undefined|\[object Object\]/);
});

test('the price chart zooms over the full history on both panes, with the range as the window', async () => {
  const { root, charts } = await mount({ TST: fixture() });
  let option = priceOption(charts);
  assert.equal(option.xAxis[0].data.length, 520, 'the chart holds every bar, not the cut range');
  assert.equal(option.dataZoom.length, 2);
  for (const zoom of option.dataZoom) assert.deepEqual(zoom.xAxisIndex, [0, 1]);
  assert.equal(option.dataZoom[0].type, 'inside');
  assert.equal(option.dataZoom[1].type, 'slider');
  assert.equal(option.dataZoom[0].endValue, 519);
  assert.equal(option.dataZoom[0].startValue, 519 - 252, '1Y starts 252 sessions before the last');
  buttonNamed(root, '3M').dispatch('click');
  await flush();
  option = priceOption(charts);
  assert.equal(option.dataZoom[0].startValue, 519 - 63);
  buttonNamed(root, 'LINE').dispatch('click');
  await flush();
  option = priceOption(charts);
  for (const zoom of option.dataZoom) assert.deepEqual(zoom.xAxisIndex, [0]);
});

test('the MA legend icons take the line colour, and the band a stronger shade of its fill', async () => {
  const { charts } = await mount({ TST: fixture() });
  const option = priceOption(charts);
  for (const s of option.series.filter((x) => x.name.startsWith('SMA '))) {
    assert.equal(s.itemStyle.color, s.lineStyle.color, s.name);
  }
  const band = option.series.find((s) => s.name === '±1.5σ band');
  assert.equal(band.itemStyle.color.slice(0, 16), band.areaStyle.color.slice(0, 16));
  assert.notEqual(band.itemStyle.color, band.areaStyle.color);
});

// The y-range the chart should show for bars [from, to], from the candles and their averages only.
function expectedExtent(bars, from, to, windows = [20, 50, 200]) {
  const lines = windows.map((w) => T.sma(bars.close, w));
  return T.visibleExtent({ low: bars.low, high: bars.high, lines }, from, to, 0.04);
}

test('the y-axis fits the visible candles and averages, never the band; BAND off removes it', async () => {
  const data = fixture();
  const { root, charts } = await mount({ TST: data });
  let option = priceOption(charts);
  // The axis is exactly the bars and averages over the 1Y window: a band term would move it.
  const want = expectedExtent(data.ohlcv, 519 - 252, data.ohlcv.close.length - 1);
  assert.ok(Math.abs(option.yAxis[0].min - want.min) < 1e-9 && Math.abs(option.yAxis[0].max - want.max) < 1e-9);
  assert.ok(option.series.some((s) => s.name === '±1.5σ band'), 'the band is drawn, and it is not part of the fit');
  buttonNamed(root, 'BAND').dispatch('click');
  await flush();
  option = priceOption(charts);
  assert.ok(!option.series.some((s) => s.name.startsWith('±')), 'no band series when BAND is off');
  assert.ok(!option.legend.data.some((name) => name.startsWith('±')));
  buttonNamed(root, 'BAND').dispatch('click');
  await flush();
  assert.ok(priceOption(charts).series.some((s) => s.name === '±1.5σ band'));
});

test('zooming re-fits the y-axis to the window on screen', async () => {
  const data = fixture();
  const { root, charts } = await mount({ TST: data });
  // The first 10% of the 520 bars: from index 0 to 52.
  priceHandlers(charts).datazoom({ start: 0, end: 10 });
  const zoomed = priceOption(charts).yAxis[0];
  const want = expectedExtent(data.ohlcv, 0, 52);
  assert.ok(Math.abs(zoomed.min - want.min) < 1e-9 && Math.abs(zoomed.max - want.max) < 1e-9);
  assert.ok(zoomed.max < 170, 'the early window tops out well below the latest prices');
  assert.doesNotMatch(textOf(root), /NaN|undefined|\[object Object\]/);
});

test('the stat strip reads the candles and dashes what it cannot compute', async () => {
  const { root } = await mount({ TST: fixture() });
  const labels = descendants(root).filter((n) => n.className === 'tech-stat-label').map((n) => n.textContent);
  assert.deepEqual(labels, ['PRICE', 'DAY %', '52W HIGH', '52W LOW', 'REL VOL', 'SMA 20', 'SMA 50', 'SMA 200',
    'DIST VS 200', 'Z-SCORE', 'SLOPE (ANN.)']);
  const values = descendants(root).filter((n) => n.className?.startsWith('tech-stat-value')).map((n) => n.textContent);
  assert.equal(values.length, labels.length);
  assert.ok(values.every((v) => v !== 'NaN' && v !== 'undefined'));
  assert.match(values[labels.indexOf('REL VOL')], /×$/);
});

test('a range the bars do not reach is drawn as a line, with the note', async () => {
  const { root, charts } = await mount({ TST: fixture() });
  buttonNamed(root, '10Y').dispatch('click');
  await flush();
  const option = priceOption(charts);
  assert.ok(!option.series.some((s) => s.type === 'candlestick'));
  assert.ok(option.series.some((s) => s.name === 'TST Close'));
  assert.equal(descendants(root).find((n) => n.className === 'tech-note').textContent,
    'Candles cover the last 520 sessions; 10Y is drawn as a line.');
});

test('LINE draws the close, LOG switches the price axis, and a short range keeps the candles', async () => {
  const { root, charts } = await mount({ TST: fixture() });
  buttonNamed(root, 'LINE').dispatch('click');
  await flush();
  assert.ok(!priceOption(charts).series.some((s) => s.type === 'candlestick'));
  buttonNamed(root, 'CANDLES').dispatch('click');
  buttonNamed(root, '3M').dispatch('click');
  await flush();
  const option = priceOption(charts);
  assert.ok(option.series.some((s) => s.type === 'candlestick'));
  assert.equal(option.xAxis[0].data.length, 520, 'the full series; the 3M window is the zoom');
  assert.equal(option.dataZoom[0].startValue, 519 - 63);
  buttonNamed(root, 'LOG').dispatch('click');
  await flush();
  assert.equal(priceOption(charts).yAxis[0].type, 'log');
});

test('a chip removes its window from the MA input, and + MA adds one', async () => {
  const { root, charts } = await mount({ TST: fixture() });
  const chip = (label) => descendants(root).find((n) => n.className === 'tech-chip' && textOf(n).trim().startsWith(label));
  const remove = descendants(chip('SMA 50')).find((n) => n.tagName === 'BUTTON');
  remove.dispatch('click');
  await flush();
  assert.deepEqual(priceOption(charts).series.filter((s) => s.name.startsWith('SMA ')).map((s) => s.name), ['SMA 20', 'SMA 200']);
  const addButton = descendants(root).find((n) => n.className === 'tech-chip-add');
  addButton.dispatch('click');
  const addInput = descendants(root).find((n) => n.tagName === 'INPUT' && n.attrs['aria-label'] === 'Moving-average period to add');
  addInput.value = '60';
  addInput.dispatch('keydown', { key: 'Enter' });
  await flush();
  assert.deepEqual(priceOption(charts).series.filter((s) => s.name.startsWith('SMA ')).map((s) => s.name), ['SMA 20', 'SMA 60', 'SMA 200']);
});

test('a ticker without bars offers no candles and no toggle', async () => {
  const bare = fixture();
  delete bare.ohlcv;
  const { root, charts } = await mount({ BARE: bare }, 'BARE');
  assert.ok(!priceOption(charts).series.some((s) => s.type === 'candlestick'));
  const toggle = descendants(root).find((n) => n.className === 'period-switch' && n.children.some((b) => b.textContent === 'CANDLES'));
  assert.equal(toggle.hidden, true);
  assert.doesNotMatch(textOf(root), /NaN|undefined|\[object Object\]/);
});
