// CHIP DISTRIBUTION card: candles beside the volume profile or the estimated
// cost distribution (chip-math.js), for a window ending on the latest session
// or on any session clicked. The ticker page folds the cost view under its
// PRICE & TREND chart, which carries the volume profile itself.

import { el, num, gap, periodSwitch, DASH } from './fmt.js';
import { render } from './charts.js';
import { grid, priceRange, volumeProfile, costDistribution, valueArea, costStats } from './chip-math.js';

const WINDOWS = [['3M', 63], ['6M', 126], ['1Y', 252], ['2Y', 504], ['SINCE 2020', Infinity]];
const MODES = [['volume', 'VOLUME PROFILE'], ['cost', 'COST DISTRIBUTION']];
const BINS = 80;
const COST_BINS = 600;
const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const price = (v) => (finite(v) ? num(v, v < 10 ? 2 : 1) : DASH);
const pctOf = (v) => (finite(v) ? `${num(v * 100, 1)}%` : DASH);
const away = (from, to) => (finite(from) && finite(to) && to ? `${from >= to ? '+' : '−'}${num(Math.abs(from / to - 1) * 100, 1)}%` : DASH);

function stat(label, value, note) {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: 'stat-value', text: value }),
    el('div', { class: 'stat-note', text: note }),
  ]);
}

// Everything one view needs: the bars shown, the grid, the profile and its readings.
export function chipView(bars, { sessions, end, mode, shares }) {
  const last = Math.min(end ?? bars.dates.length - 1, bars.dates.length - 1);
  const from = Number.isFinite(sessions) ? Math.max(0, last - sessions + 1) : 0;
  const range = priceRange(bars, from, last);
  if (!range) return null;
  const pad = (range.max - range.min) * 0.02;
  const g = grid(range.min - pad, range.max + pad, BINS);
  const close = bars.close[last];
  const out = { from, last, g, close, date: bars.dates[last], mode };
  if (mode === 'cost') {
    // Estimated over every price since the first bar, so the readings do not
    // depend on the window; the window only crops what is drawn.
    const whole = priceRange(bars, 0, last);
    const fine = whole && grid(whole.min, whole.max, COST_BINS);
    const distribution = fine && costDistribution(bars, last, fine, shares);
    if (!distribution) return null;
    out.stats = costStats(distribution, fine, close);
    out.profile = new Array(g.count).fill(0);
    let shown = 0;
    distribution.chips.forEach((c, k) => {
      const at = Math.floor((fine.centers[k] - g.min) / g.step);
      if (at >= 0 && at < g.count) { out.profile[at] += c; shown += c; }
    });
    out.hidden = 1 - shown;
  } else {
    out.profile = volumeProfile(bars, from, last, g);
    out.area = valueArea(out.profile, g);
  }
  return out;
}

function draw(node, bars, view, onPick) {
  const dates = bars.dates.slice(view.from, view.last + 1);
  const candles = dates.map((_, k) => {
    const i = view.from + k;
    return [bars.open[i], bars.close[i], bars.low[i], bars.high[i]];
  });
  const { g } = view;
  const maxValue = Math.max(...view.profile) || 1;
  const chart = render(node, (option, p) => {
    const tone = (k) => {
      if (view.mode === 'cost') return g.centers[k] <= view.close ? p.accent : p.blue;
      const a = view.area;
      return a && g.centers[k] >= a.low && g.centers[k] <= a.high ? p.accent : p.faint;
    };
    const lines = view.mode === 'cost'
      ? [{ yAxis: view.stats?.average, name: 'AVG COST' }]
      : [{ yAxis: view.area?.poc, name: 'POC' }, { yAxis: view.area?.high, name: 'VAH' }, { yAxis: view.area?.low, name: 'VAL' }];
    const axis = { min: g.min, max: g.max, scale: true };
    return {
      ...option,
      tooltip: { ...option.tooltip, trigger: 'axis', axisPointer: { type: 'cross', lineStyle: { color: p.faint } } },
      axisPointer: { link: [{ yAxisIndex: 'all' }] },
      grid: [{ left: 52, right: '30%', top: 12, bottom: 30 }, { left: '71%', right: 8, top: 12, bottom: 30 }],
      xAxis: [
        { ...option.xAxis, gridIndex: 0, data: dates, boundaryGap: true },
        { type: 'value', gridIndex: 1, max: maxValue, axisLabel: { show: false }, splitLine: { show: false }, axisLine: { show: false } },
      ],
      yAxis: [
        { ...option.yAxis, gridIndex: 0, ...axis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => price(v) } },
        { type: 'category', gridIndex: 1, data: g.centers.map((c) => price(c)), axisLabel: { show: false }, axisTick: { show: false },
          axisLine: { show: false } },
      ],
      series: [
        {
          type: 'candlestick', name: 'Price', xAxisIndex: 0, yAxisIndex: 0, data: candles,
          itemStyle: { color: p.up, color0: p.down, borderColor: p.up, borderColor0: p.down },
          markLine: { silent: true, symbol: 'none', lineStyle: { color: p.dim, type: 'dashed' },
            label: { color: p.dim, fontSize: 9, formatter: (d) => `${d.name} ${price(d.value)}` },
            data: lines.filter((l) => finite(l.yAxis)) },
        },
        {
          type: 'bar', name: view.mode === 'cost' ? 'Holdings' : 'Volume', xAxisIndex: 1, yAxisIndex: 1, barCategoryGap: '8%',
          data: view.profile.map((v, k) => ({ value: v, itemStyle: { color: tone(k) } })),
          tooltip: { valueFormatter: (v) => (view.mode === 'cost' ? `${num(v * 100, 2)}%` : `${num(v / 1e6, 1)}M sh`) },
        },
      ],
    };
  });
  // Any click inside the price grid picks the nearest session: a candle is a few pixels wide.
  chart?.getZr().on('click', (event) => {
    const point = [event.offsetX, event.offsetY];
    if (!chart.containPixel({ gridIndex: 0 }, point)) return;
    const [index] = chart.convertFromPixel({ gridIndex: 0 }, point);
    if (Number.isFinite(index)) onPick(view.from + Math.max(0, Math.min(dates.length - 1, Math.round(index))));
  });
}

function statsNode(view) {
  if (view.mode === 'cost') {
    const s = view.stats;
    if (!s) return el('div', {});
    return el('div', { class: 'stat-strip' }, [
      stat('AVERAGE COST', price(s.average), `close ${away(view.close, s.average)} from it`),
      stat('IN PROFIT', pctOf(s.profitShare), 'of estimated holdings bought below the close'),
      stat('70% OF HOLDINGS', `${price(s.band70[0])} – ${price(s.band70[1])}`, 'middle seventy per cent'),
      stat('90% OF HOLDINGS', `${price(s.band90[0])} – ${price(s.band90[1])}`, `width ${pctOf(s.concentration)} of its midpoint`),
    ]);
  }
  const a = view.area;
  if (!a) return el('div', {});
  const where = view.close > a.high ? 'above the value area' : view.close < a.low ? 'below the value area' : 'inside the value area';
  return el('div', { class: 'stat-strip' }, [
    stat('MOST TRADED (POC)', price(a.poc), `close ${away(view.close, a.poc)} from it`),
    stat('VALUE AREA', `${price(a.low)} – ${price(a.high)}`, `${pctOf(a.share)} of the window's volume`),
    stat('CLOSE', price(view.close), where),
  ]);
}

// The card's body, or a gap when the ticker has no bars. ``shares``: shares
// outstanding (market cap / price), for the cost model's turnover; ``modes``:
// the modes to offer, all by default.
export function chipCard(bars, { shares = null, modes: only = null } = {}) {
  if (!bars?.dates?.length) return gap('No daily bars for this ticker.');
  let windowLabel = '1Y';
  let end = null;
  const body = el('div', {});
  // ``only`` limits the modes offered (the ticker page shows the volume profile with its candles).
  const modes = MODES.filter(([k]) => (finite(shares) || k === 'volume') && (!only || only.includes(k)));
  if (!modes.length) return gap('No shares outstanding for the cost estimate.');
  let mode = modes[0][0];
  const redraw = () => {
    body.replaceChildren();
    const sessions = WINDOWS.find(([label]) => label === windowLabel)[1];
    const view = chipView(bars, { sessions, end, mode, shares });
    const controls = el('div', { class: 'tag-row' }, [
      modes.length > 1 ? periodSwitch(modes.map(([, l]) => l), MODES.find(([k]) => k === mode)[1], (l) => {
        mode = MODES.find(([, x]) => x === l)[0]; redraw();
      }) : null,
      periodSwitch(WINDOWS.map(([l]) => l), windowLabel, (l) => { windowLabel = l; redraw(); }),
      end !== null ? el('button', { type: 'button', class: 'action', text: 'BACK TO LATEST', onclick: () => { end = null; redraw(); } }) : null,
    ]);
    if (!view) {
      body.append(controls, gap('Not enough bars in this window.'));
      return;
    }
    const chart = el('div', { class: 'chart', style: 'height:360px' });
    body.append(
      controls,
      el('div', { class: 'field-note', text: `AS OF ${view.date}${end !== null ? ' (picked)' : ''} · ${bars.dates[view.from]} → ${view.date} · click a candle to see the distribution as of that day` }),
      chart,
      statsNode(view),
      el('div', { class: 'field-note', text: view.mode === 'cost'
        ? 'Estimated holders\' cost: every session since 2020 spread over its low–high range, each turning over volume ÷ shares outstanding of the holdings before it. Amber = bought below the close (in profit), blue = above.'
          + (view.hidden > 0.005 ? ` ${pctOf(view.hidden)} of the estimated holdings were bought at prices outside this window's range (counted in the readings, not drawn).` : '')
          + ' An estimate: market-making and high-frequency volume count as shares changing hands, and the decay is the charting convention, not a measurement. Descriptive, not a support or resistance call.'
        : 'Volume by price over the window: each session\'s volume spread over its low–high range. Amber = the value area, the 70% of volume around the most traded price (POC). Split-adjusted. Descriptive, not a support or resistance call.' }),
    );
    requestAnimationFrame(() => draw(chart, bars, view, (i) => { end = i; redraw(); }));
  };
  redraw();
  return body;
}
