// TECHNICALS: relative strength and single-ticker regime, with the windows in
// the reader's hands. The build bakes each ticker's close history; every
// indicator is computed here by technicals-math.js on the full history and
// then cut to the chosen period.

import { el, card, table, num, pct, dirClass, sectionTitle, tag, DASH } from '../fmt.js';
import { render, multiLine, SERIES_COLORS } from '../charts.js';
import * as T from '../technicals-math.js';
import { grid as priceGrid, volumeProfile, valueArea } from '../chip-math.js';
import { withSuggestions } from '../ticker-suggest.js';
import { resolveTicker } from '../routes.js';

const TICKER_BASE = 'artifacts/tickers';
// Daily bars since 2020 (panels/technicals.py BARS_START), for a range past the payload's own candles.
const BARS_BASE = 'artifacts/bars';
// A sanity bound on typed windows, not a data limit: ten years of history
// would support more, but nobody means a 2,000-day "moving average".
const MAX_MA_WINDOW = 400;
const MAX_SLOPE_WINDOW = 60;
const MAX_RSI_PERIOD = 50;
const RSI_NOTE = 'Wilder RSI on closes. The lines describe how stretched a fall is, not a rebound call: since '
  + '1950 on the S&P 500 and since 2008 on the sector funds, a close below 20 was followed by much the same '
  + 'returns as one below 30, and the worst tenth still fell 7–16% further within 20 sessions.';
// The range buttons; the PERIOD select offers every range in T.RANGES.
const BUTTON_RANGES = ['1M', '3M', '6M', 'YTD', '1Y', '2Y', '5Y', '10Y', 'MAX'];
const VOLUME_WINDOW = 20;
// The y-axis pads the visible range by this share of its span on each side.
const FIT_PAD = 0.04;
const BAND_FILL = 'rgba(232,163,61,0.13)';
// The legend icon is a small square: the fill's own alpha would be invisible there.
const BAND_ICON = 'rgba(232,163,61,0.55)';
// Price bins of the volume profile beside the candles.
const PROFILE_BINS = 60;
// A bin inside the window's traded range holding under this share of the
// average bin is thin: few shares changed hands at those prices.
const THIN_SHARE = 0.35;

const payloads = new Map();

async function loadTicker(symbol) {
  const key = symbol.toUpperCase();
  if (!payloads.has(key)) {
    payloads.set(key, fetch(`${TICKER_BASE}/${key}.json`, { cache: 'no-cache' }).then((response) => {
      if (!response.ok) throw new Error(`${key} is not in this build`);
      return response.json();
    }));
  }
  try {
    return await payloads.get(key);
  } catch (error) {
    payloads.delete(key);
    throw error;
  }
}

const longBars = new Map();

// The long daily bars for a symbol, or null when the build has none for it.
async function loadLongBars(symbol) {
  const key = symbol.toUpperCase();
  if (!longBars.has(key)) {
    longBars.set(key, fetch(`${BARS_BASE}/${key}.json`, { cache: 'no-cache' })
      .then((response) => (response.ok ? response.json() : null)).catch(() => null));
  }
  return longBars.get(key);
}

const cut = (values, start) => values.slice(start);
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

function periodSelect(labels, selected) {
  return el('select', {}, labels.map((label) => {
    const option = el('option', { value: label, text: label });
    if (label === selected) option.selected = true;
    return option;
  }));
}

// A row of exclusive buttons in the period-switch style. setActive marks one as pressed.
function segmented(labels, active, onPick) {
  const buttons = labels.map((label) => el('button', { type: 'button', text: label, onclick: () => onPick(label) }));
  const wrap = el('div', { class: 'period-switch' }, buttons);
  wrap.setActive = (value) => buttons.forEach((b, i) => b.setAttribute('aria-pressed', String(labels[i] === value)));
  wrap.setActive(active);
  return wrap;
}

function needs(window, sessions) {
  return `needs ${window} sessions, has ${sessions}`;
}

// ---------------------------------------------------------------- readings

// The page's RSI settings: the build's when it sends them, else the classic 6 and
// the module's lines, so an older technicals.json still draws.
export function rsiSettings(defaults) {
  return { period: defaults?.rsi?.period ?? 6, lines: defaults?.rsi?.lines ?? T.RSI_LINES };
}

// `series` is the close the moving averages and the band are drawn on: the
// close history, or the candles' close when candles are shown. Everything else
// reads the close history, as before.
function computeSingle(payload, { windows, slopeWindow, defaults, rsiPeriod, series }) {
  const close = payload.close;
  const n = close.length;
  const zWindow = defaults.zscore_window;
  const horizon = defaults.forward_return_days;
  const unavailable = {};
  const line = series || close;

  const formed = windows.filter((w) => n >= w);
  windows.filter((w) => n < w).forEach((w) => { unavailable[`sma_${w}`] = needs(w, n); });
  const averages = Object.fromEntries(windows.map((w) => [w, T.sma(line, w)]));
  const slopes = Object.fromEntries(formed.map((w) => [w, T.smaSlope(close, w, slopeWindow)]));
  const bandLines = line.length >= zWindow ? T.band(line, zWindow, defaults.band_sigma) : null;

  let summary = { price: close[n - 1] };
  let z = [];
  if (n >= zWindow) {
    const long = T.sma(close, zWindow);
    z = T.zscore(close, zWindow);
    const lastZ = z[n - 1];
    const b = T.bandFor(lastZ);
    const slope = T.annualisedSlope(close, zWindow, slopeWindow);
    summary = {
      ...summary,
      smaLong: long[n - 1],
      distance: (close[n - 1] / long[n - 1] - 1) * 100,
      zscore: lastZ,
      band: b?.label ?? null,
      verdict: b?.verdict ?? null,
      slope,
      slopeVerdict: T.slopeVerdict(slope),
    };
  } else {
    ['zscore', 'sigma_band', 'long_average', 'slope_annualised'].forEach((k) => { unavailable[k] = needs(zWindow, n); });
  }

  const forward = n >= zWindow + horizon ? T.forwardReturnByBand(close, zWindow, horizon) : null;
  if (!forward) {
    unavailable.forward_returns = `needs ${zWindow + horizon} sessions (${zWindow} to form the z-score plus `
      + `${horizon} for the forward window), has ${n}`;
  }
  const lines = rsiSettings(defaults).lines;
  let rsi = [];
  let rsiNow = null;
  if (n > rsiPeriod) {
    rsi = T.rsi(close, rsiPeriod);
    rsiNow = T.rsiReading(rsi, lines);
  } else {
    unavailable.rsi = needs(rsiPeriod + 1, n);
  }
  return { averages, slopes, z, bandLines, summary, forward, unavailable, rsi, rsiNow, rsiPeriod, lines };
}

// The stat strip: each reading from the series the price chart draws, dashed
// where the history cannot form it. Z-SCORE and SLOPE are the single-ticker readings.
function statItems(payload, series, readings, windows) {
  const s = series.close;
  const last = s.length - 1;
  const day = T.change(s, last);
  const { high, low } = T.stats52w(s);
  const sma200 = T.sma(s, 200)[last];
  const dist = isNum(sma200) && isNum(s[last]) ? (s[last] / sma200 - 1) * 100 : null;
  const rel = T.relVolume(payload.ohlcv?.volume || [], VOLUME_WINDOW);
  const { summary } = readings;
  return [
    ['PRICE', num(s[last]), ''],
    ['DAY %', pct(day), dirClass(day)],
    ['52W HIGH', num(high), ''],
    ['52W LOW', num(low), ''],
    ['REL VOL', rel === null ? DASH : `${num(rel, 2)}×`, ''],
    ...windows.map((w) => [`SMA ${w}`, num(readings.averages[w][last]), '']),
    ['DIST VS 200', pct(dist), dirClass(dist)],
    ['Z-SCORE', num(summary.zscore), ''],
    ['SLOPE (ANN.)', pct(summary.slope, 1), dirClass(summary.slope)],
  ];
}

// ------------------------------------------------------------------ charts

const BAND_BASE = 'band base';
const maName = (w) => `SMA ${w}`;
const MA_COLORS = (p) => [p.accent, p.blue, p.purple, ...SERIES_COLORS];

// Volume labels on the pane's axis: 1.2M, 340K.
// The profile's readings in a line: where the window traded most, its value
// area, and the last close on screen against it. Descriptive, not a level call.
export function profileText(reading) {
  if (!reading) return '';
  const { area, close } = reading;
  const where = !isNum(close) ? '' : close > area.high ? 'above it' : close < area.low ? 'below it' : 'inside it';
  const range = isNum(reading.high) && isNum(reading.low) ? ` · window range ${num(reading.low)}–${num(reading.high)}` : '';
  const nodes = (reading.nodes || []).map((n) => `${n.kind} ${num(n.price)}`).join(', ');
  return `VOLUME PROFILE (sessions on screen) · most traded ${num(area.poc)} · value area ${num(area.low)}–${num(area.high)}`
    + ` (${num(area.share * 100, 0)}% of volume)${where ? ` · last close ${num(close)}, ${where}` : ''}${range}`
    + (nodes ? ` · ${nodes} (HVN a heavy node, LVN the thin gap between the two)` : '')
    + ' · amber = value area, blue = thin trading (under a third of the average price bin)'
    + ' · estimated from daily bars, each session\'s volume spread over its low–high range, not trade-by-trade;'
    + ' where trading was heavy in the past, not a support, resistance or target.';
}

// The window's high and low, and which bins inside that range are thin.
export function profileRange(bars, from, to, g, volumes) {
  let high = -Infinity;
  let low = Infinity;
  for (let i = from; i <= to; i += 1) {
    if (isNum(bars.high[i])) high = Math.max(high, bars.high[i]);
    if (isNum(bars.low[i])) low = Math.min(low, bars.low[i]);
  }
  const inside = (k) => g.min + (k + 1) * g.step > low && g.min + k * g.step < high;
  const traded = volumes.filter((_, k) => inside(k));
  const mean = traded.length ? traded.reduce((a, b) => a + b, 0) / traded.length : 0;
  return {
    high: isNum(high) ? high : null, low: isNum(low) ? low : null,
    thin: volumes.map((v, k) => inside(k) && mean > 0 && v < mean * THIN_SHARE),
    nodes: profileNodes(volumes, g, inside, mean),
  };
}

// The two heaviest nodes (HVN: local peaks of the profile smoothed over three
// bins, above the average bin and at least NODE_GAP bins apart) and, between
// them, the thinnest bin (LVN) when it holds under 60% of the smaller peak.
const NODE_GAP = 5;
export function profileNodes(volumes, g, inside = () => true, mean = null) {
  const n = volumes.length;
  const smooth = volumes.map((_, k) => {
    const near = volumes.slice(Math.max(0, k - 1), Math.min(n, k + 2));
    return near.reduce((a, b) => a + b, 0) / near.length;
  });
  const floor = mean ?? smooth.reduce((a, b) => a + b, 0) / (n || 1);
  const peaks = smooth.map((v, k) => k).filter((k) => inside(k) && smooth[k] > floor
    && (k === 0 || smooth[k] >= smooth[k - 1]) && (k === n - 1 || smooth[k] >= smooth[k + 1]))
    .sort((a, b) => smooth[b] - smooth[a]);
  const heavy = [];
  for (const k of peaks) {
    if (heavy.every((h) => Math.abs(h - k) >= NODE_GAP)) heavy.push(k);
    if (heavy.length === 2) break;
  }
  const at = (k) => g.min + (k + 0.5) * g.step;
  const out = heavy.map((k) => ({ kind: 'HVN', price: at(k), volume: volumes[k] }));
  if (heavy.length === 2) {
    const [a, b] = [...heavy].sort((x, y) => x - y);
    let low = a + 1;
    for (let k = a + 1; k < b; k += 1) if (smooth[k] < smooth[low]) low = k;
    if (low < b && smooth[low] < 0.6 * Math.min(smooth[a], smooth[b])) out.push({ kind: 'LVN', price: at(low), volume: volumes[low] });
  }
  return out.sort((x, y) => y.price - x.price);
}

// The window the profile reads, above the chart: it changes with zoom and pan.
export function profileWindow(reading) {
  if (!reading) return '';
  return `VOLUME PROFILE WINDOW · ${reading.from} → ${reading.to} · ${reading.sessions} sessions on screen · zoom or pan to change it`;
}

function volumeLabel(v) {
  if (!isNum(v)) return '';
  const unit = [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']].find(([size]) => v >= size);
  return unit ? `${num(v / unit[0], 1)}${unit[1]}` : num(v, 0);
}

// The price chart. LINE draws the close; CANDLES (`view.bars`, the ohlcv
// block) draws the bars with a volume pane under them. Either way the moving
// averages and the band sit on `view.close`. Every series is the full history:
// the range is a zoom window from `view.start` to the last session, so the
// reader can pan and zoom past it. The y-axis fits the visible candles (or
// closes) and the visible averages; the band is left to be clipped.
// With ``view.profile`` the candles get the volume profile of the sessions on
// screen to their right (chip-math.js): volume by price, the value area in amber,
// thin bins in blue, and the point of control and the window's high and low
// dashed across the candles. It follows zoom and pan, and ``view.onProfile``
// hears its readings.
function priceChart(node, view) {
  const { bars, dates, close, averages, bandLines, start, log, ticker } = view;
  const last = dates.length - 1;
  const lines = Object.values(averages);
  const fit = (from, to) => {
    const extent = T.visibleExtent({ low: bars ? bars.low : close, high: bars ? bars.high : close, lines }, from, to, FIT_PAD);
    if (!extent) return {};
    // A log axis needs positive bounds; prices are, so this only guards a stray zero.
    return log && extent.min <= 0 ? { max: extent.max } : extent;
  };
  const withProfile = Boolean(bars && view.profile);
  // The profile of sessions [from, to] over the y-axis range they are drawn in.
  const profileOf = (from, to, extent) => {
    const g = extent && priceGrid(extent.min, extent.max, PROFILE_BINS);
    if (!g) return null;
    const volumes = volumeProfile(bars, from, to, g);
    const area = valueArea(volumes, g);
    if (!area) return null;
    return { g, volumes, area, close: bars.close[to], ...profileRange(bars, from, to, g, volumes),
      from: dates[from], to: dates[to], sessions: to - from + 1 };
  };
  // Tone per bin: 1 the value area, 2 thin, 0 the rest.
  const profileData = (profile) => (profile ? profile.volumes.map((v, k) => {
    const low = profile.g.min + k * profile.g.step;
    const high = low + profile.g.step;
    const inArea = low >= profile.area.low - 1e-9 && high <= profile.area.high + 1e-9;
    return [v, low, high, inArea ? 1 : profile.thin[k] ? 2 : 0];
  }) : []);
  const nodeData = (profile) => (profile?.nodes || []).map((node) => ({ name: node.kind, value: [node.volume, node.price] }));
  const pocLine = (profile) => (profile ? [
    { yAxis: profile.area.poc, name: 'POC' },
    ...(isNum(profile.high) ? [{ yAxis: profile.high, name: 'HIGH', lineStyle: { type: 'dotted' } }] : []),
    ...(isNum(profile.low) ? [{ yAxis: profile.low, name: 'LOW', lineStyle: { type: 'dotted' } }] : []),
  ] : []);
  let profile = withProfile ? profileOf(start, last, fit(start, last)) : null;
  if (withProfile) view.onProfile?.(profile);
  const chart = render(node, (option, p) => {
    const colors = MA_COLORS(p);
    const maEntries = Object.entries(averages).map(([w, values], i) => ({
      w, name: maName(w), color: colors[i % colors.length], data: values,
    }));
    // The band is a stacked invisible base plus a filled span, so it reads
    // as an envelope rather than two unrelated lines.
    const bandSeries = bandLines ? [
      { name: BAND_BASE, type: 'line', data: bandLines.lower, stack: 'band', showSymbol: false,
        lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 }, silent: true, tooltip: { show: false } },
      { name: `±${view.sigma}σ band`, type: 'line', stack: 'band', showSymbol: false, silent: true,
        data: bandLines.upper.map((v, i) => {
          const low = bandLines.lower[i];
          return v === null || low === null ? null : v - low;
        }),
        lineStyle: { opacity: 0 }, areaStyle: { color: BAND_FILL }, itemStyle: { color: BAND_ICON }, tooltip: { show: false } },
    ] : [];
    const maSeries = maEntries.map(({ name, color, data }) => ({
      name, type: 'line', data, showSymbol: false, lineStyle: { width: 1, color }, itemStyle: { color }, z: 3,
    }));
    const tip = (params) => {
      const first = [].concat(params)[0];
      if (!first) return '';
      const k = first.dataIndex;
      const rows = [`<b>${dates[k]}</b>`];
      if (bars) rows.push(`O ${num(bars.open[k])}  H ${num(bars.high[k])}  L ${num(bars.low[k])}  C ${num(bars.close[k])}`);
      else rows.push(`Close <b>${num(close[k])}</b>`);
      rows.push(`Day ${pct(T.change(close, k))}`);
      maEntries.forEach(({ w, name, color }) => rows.push(`<span style="color:${color}">${name}</span> ${num(averages[w][k])}`));
      return rows.join('<br>');
    };
    const axisTooltip = {
      ...option.tooltip,
      valueFormatter: undefined,
      formatter: tip,
      axisPointer: { ...option.tooltip.axisPointer, link: [{ xAxisIndex: 'all' }] },
    };
    // The fitted ends are padded data values, not round numbers: label only the ticks between them.
    // The price axis has its own pointer: a dashed level at the mouse, its price on the axis,
    // so a level can be laid across the candles and the profile beside them.
    const yPrice = { ...option.yAxis, gridIndex: 0, type: log ? 'log' : 'value', ...fit(start, last),
      axisLabel: { ...option.yAxis.axisLabel, showMinLabel: false, showMaxLabel: false },
      axisPointer: { show: true, type: 'line', snap: false, triggerTooltip: false,
        lineStyle: { color: p.dim, type: 'dashed', width: 1 },
        label: { show: true, backgroundColor: p.panel, color: p.text, borderColor: p.faint, borderWidth: 1, fontSize: 10,
          formatter: (d) => num(d.value) } } };
    const zoomAxes = bars ? [0, 1] : [0];
    const dataZoom = [
      { type: 'inside', xAxisIndex: zoomAxes, filterMode: 'weakFilter', startValue: start, endValue: last },
      { type: 'slider', xAxisIndex: zoomAxes, filterMode: 'weakFilter', height: 18, bottom: 22, startValue: start, endValue: last },
    ];

    if (!bars) {
      return withLegend(option, p, {
        ...option,
        tooltip: axisTooltip,
        grid: { ...option.grid, bottom: 64 },
        dataZoom,
        xAxis: { ...option.xAxis, data: dates },
        yAxis: yPrice,
        series: [
          ...bandSeries,
          { name: `${ticker} Close`, type: 'line', data: close, showSymbol: false,
            lineStyle: { width: 1.4, color: p.text }, z: 5 },
          ...maSeries,
        ],
      });
    }

    const O = bars.open;
    const H = bars.high;
    const L = bars.low;
    const C = close;
    const V = bars.volume;
    const right = withProfile ? '19%' : 16;
    // The profile's grid shares the price grid's height and y-range, so a bar sits at its price.
    const profileParts = withProfile ? {
      grid: [{ left: '82%', right: 16, top: 12, height: '68%' }],
      xAxis: [{ type: 'value', gridIndex: 2, min: 0, axisLabel: { show: false }, splitLine: { show: false },
        axisLine: { show: false }, axisTick: { show: false } }],
      yAxis: [{ ...yPrice, gridIndex: 2, axisLabel: { show: false }, splitLine: { show: false }, axisTick: { show: false },
        axisPointer: { ...yPrice.axisPointer, label: { show: false } } }],
      series: [{
        id: 'profile', name: 'Volume profile', type: 'custom', xAxisIndex: 2, yAxisIndex: 2, silent: true,
        tooltip: { show: false }, encode: { x: 0, y: [1, 2] }, data: profileData(profile),
        renderItem: (params, api) => {
          const from = api.coord([0, api.value(1)]);
          const to = api.coord([api.value(0), api.value(2)]);
          return { type: 'rect', shape: { x: from[0], y: to[1], width: Math.max(0, to[0] - from[0]), height: Math.max(1, from[1] - to[1] - 1) },
            style: { fill: [p.faint, p.accent, p.blue][api.value(3)], opacity: [0.45, 0.75, 0.35][api.value(3)] } };
        },
      }, {
        id: 'nodes', name: 'Profile nodes', type: 'scatter', xAxisIndex: 2, yAxisIndex: 2, silent: true, tooltip: { show: false },
        symbolSize: 5, data: nodeData(profile),
        itemStyle: { color: p.text }, label: { show: true, position: 'right', color: p.text, fontSize: 9, formatter: (d) => d.data.name },
      }],
    } : { grid: [], xAxis: [], yAxis: [], series: [] };
    return withLegend(option, p, {
      ...option,
      tooltip: axisTooltip,
      grid: [
        { left: 52, right, top: 12, height: '68%' },
        { left: 52, right, top: '74%', height: '12%' },
        ...profileParts.grid,
      ],
      dataZoom,
      xAxis: [
        { ...option.xAxis, data: dates, gridIndex: 0, boundaryGap: true, axisLabel: { show: false } },
        { ...option.xAxis, data: dates, gridIndex: 1, boundaryGap: true },
        ...profileParts.xAxis,
      ],
      yAxis: [
        yPrice,
        { ...option.yAxis, gridIndex: 1, scale: false, min: 0, splitNumber: 2,
          axisLabel: { ...option.yAxis.axisLabel, formatter: volumeLabel } },
        ...profileParts.yAxis,
      ],
      series: [
        ...bandSeries,
        { id: 'candles', name: `${ticker} OHLC`, type: 'candlestick', z: 5,
          data: O.map((_, i) => (isNum(O[i]) && isNum(H[i]) && isNum(L[i]) && isNum(C[i]) ? [O[i], C[i], L[i], H[i]] : '-')),
          itemStyle: { color: p.up, color0: p.down, borderColor: p.up, borderColor0: p.down },
          markLine: { silent: true, symbol: 'none', lineStyle: { color: p.accent, type: 'dashed', width: 1 },
            label: { color: p.accent, fontSize: 9, position: 'insideEndTop', formatter: (d) => `${d.name} ${num(d.value)}` },
            data: pocLine(profile) } },
        ...maSeries,
        { name: 'Volume', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, barMaxWidth: 6,
          data: V.map((v, i) => (isNum(v) ? {
            value: v,
            itemStyle: { color: isNum(O[i]) && isNum(C[i]) ? (C[i] < O[i] ? p.down : p.up) : p.faint, opacity: 0.5 },
          } : null)) },
        ...profileParts.series,
      ],
    }, [`${ticker} OHLC`, 'Volume', 'Volume profile', 'Profile nodes']);
  });
  // Zooming or panning re-fits the y-axis to what is now on screen.
  chart?.on('datazoom', (event) => {
    const e = event.batch?.[0] || event;
    const from = Math.floor(((e.start ?? 0) / 100) * last);
    const to = Math.ceil(((e.end ?? 100) / 100) * last);
    const extent = fit(from, to);
    if (!withProfile) {
      chart.setOption({ yAxis: [extent] });
      return;
    }
    profile = profileOf(from, Math.min(to, last), extent);
    view.onProfile?.(profile);
    chart.setOption({
      yAxis: [extent, {}, extent],
      series: [{ id: 'candles', markLine: { data: pocLine(profile) } }, { id: 'profile', data: profileData(profile) },
        { id: 'nodes', data: nodeData(profile) }],
    });
  });
  return chart;
}

// The band's invisible base series exists only to lift the fill, and the
// candles and volume are read from the tooltip, so none of them is in the legend.
function withLegend(option, p, built, hidden = []) {
  return {
    ...built,
    legend: {
      bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9,
      data: built.series.map((s) => s.name).filter((name) => name !== BAND_BASE && !hidden.includes(name)),
    },
  };
}

// The ratio with its moving averages and a ±σ band around the longest one: the
// same envelope the price chart draws, so a stretched ratio reads the same way.
// A dashed level and its value follow the pointer.
// With ``candles`` (ratioBars cut to the view) the ratio is drawn as daily candles:
// an exact body from the open and close, and a faint wick for the bounds of the day.
function ratioChart(node, dates, { ratio, averages, band, sigma, window, candles = null }) {
  return render(node, (option, p) => {
    const colors = MA_COLORS(p);
    const bandSeries = band ? [
      { name: BAND_BASE, type: 'line', data: band.lower, stack: 'band', showSymbol: false,
        lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 }, silent: true, tooltip: { show: false } },
      { name: `±${sigma}σ band (${window}-day)`, type: 'line', stack: 'band', showSymbol: false, silent: true,
        data: band.upper.map((v, i) => (v === null || band.lower[i] === null ? null : v - band.lower[i])),
        lineStyle: { opacity: 0 }, areaStyle: { color: BAND_FILL }, itemStyle: { color: BAND_ICON }, tooltip: { show: false } },
    ] : [];
    // The ratio takes the first colour, so the averages start from the second.
    const maColor = (i) => colors[(i + 1) % colors.length];
    const maSeries = Object.entries(averages).map(([name, data], i) => ({
      name, type: 'line', data, showSymbol: false, lineStyle: { width: 1, color: maColor(i) },
      itemStyle: { color: maColor(i) },
    }));
    // The fit takes the bodies, not the wick bounds, which can run far wider than the day did.
    const values = [...ratio, ...(candles ? candles.open : []), ...Object.values(averages).flat()].filter(isNum);
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const pad = (hi - lo) * FIT_PAD || hi * 0.01;
    const tip = (params) => {
      const k = [].concat(params)[0]?.dataIndex;
      if (k === undefined) return '';
      const rows = [`<b>${dates[k]}</b>`, candles
        ? `Open ${num(candles.open[k], 4)} · close <b>${num(candles.close[k], 4)}</b><br><span style="color:${p.dim}">day bounds ${num(candles.lower[k], 4)} – ${num(candles.upper[k], 4)}</span>`
        : `Ratio <b>${num(ratio[k], 4)}</b>`];
      Object.entries(averages).forEach(([name, data], i) => rows.push(`<span style="color:${maColor(i)}">${name}</span> ${num(data[k], 4)}`));
      if (band && isNum(band.upper[k])) rows.push(`Band ${num(band.lower[k], 4)} – ${num(band.upper[k], 4)}`);
      return rows.join('<br>');
    };
    return withLegend(option, p, {
      ...option,
      tooltip: { ...option.tooltip, valueFormatter: undefined, formatter: tip },
      grid: { ...option.grid, bottom: 40 },
      xAxis: { ...option.xAxis, data: dates },
      yAxis: { ...option.yAxis, min: lo - pad, max: hi + pad,
        axisLabel: { ...option.yAxis.axisLabel, showMinLabel: false, showMaxLabel: false },
        axisPointer: { show: true, type: 'line', snap: false, triggerTooltip: false,
          lineStyle: { color: p.dim, type: 'dashed', width: 1 },
          label: { show: true, backgroundColor: p.panel, color: p.text, borderColor: p.faint, borderWidth: 1, fontSize: 10,
            formatter: (d) => num(d.value, 4) } } },
      series: [
        ...bandSeries,
        candles ? {
          name: 'Ratio', type: 'custom', z: 5, clip: true, encode: { x: 0, y: [1, 2] },
          data: dates.map((_, i) => [i, candles.open[i], candles.close[i], candles.lower[i], candles.upper[i]]),
          renderItem: (params, api) => {
            const [open, close, low, high] = [1, 2, 3, 4].map((k) => api.value(k));
            if (![open, close, low, high].every(isNum)) return null;
            const x = api.coord([api.value(0), open])[0];
            const width = Math.max(1, api.size([1, 0])[0] * 0.6);
            const top = api.coord([api.value(0), Math.max(open, close)])[1];
            const bottom = api.coord([api.value(0), Math.min(open, close)])[1];
            const color = close >= open ? p.up : p.down;
            return { type: 'group', children: [
              { type: 'line', shape: { x1: x, y1: api.coord([0, high])[1], x2: x, y2: api.coord([0, low])[1] },
                style: { stroke: p.faint, lineWidth: 1, opacity: 0.6 } },
              { type: 'rect', shape: { x: x - width / 2, y: top, width, height: Math.max(1, bottom - top) }, style: { fill: color } },
            ] };
          },
        } : { name: 'Ratio', type: 'line', data: ratio, showSymbol: false, lineStyle: { width: 1.5, color: p.accent }, itemStyle: { color: p.accent }, z: 5 },
        ...maSeries,
      ],
    });
  });
}

function zChart(node, dates, z) {
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, top: 10, bottom: 24 },
    xAxis: { ...option.xAxis, data: dates, boundaryGap: true },
    series: [{
      type: 'bar', barMaxWidth: 3,
      data: z.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? '#2dd4bf' : p.down } })),
      markLine: { silent: true, symbol: 'none', data: [{ yAxis: 0 }],
        lineStyle: { color: p.faint, type: 'dashed' }, label: { show: false } },
    }],
  }));
}

function macdChart(node, dates, series) {
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, top: 10, bottom: 24 },
    xAxis: { ...option.xAxis, data: dates },
    series: [
      { name: 'Histogram', type: 'bar', barMaxWidth: 3,
        data: series.histogram.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? p.up : p.down } })) },
      { name: 'MACD', type: 'line', data: series.macd, showSymbol: false, lineStyle: { width: 1, color: p.blue } },
      { name: 'Signal', type: 'line', data: series.signal, showSymbol: false, lineStyle: { width: 1, color: p.accent } },
    ],
  }));
}

// RSI with its lines drawn and the space under each tinted, so a dip below 30
// or 20 shows as a shape rather than a number to compare.
function rsiChart(node, dates, values, lines) {
  const sorted = [...lines].sort((a, b) => a.below - b.below);
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, top: 10, bottom: 24 },
    xAxis: { ...option.xAxis, data: dates },
    yAxis: { ...option.yAxis, min: 0, max: 100, interval: 10,
      axisLabel: { ...(option.yAxis?.axisLabel || {}), formatter: (v) => ([0, 50, 100].includes(v) || sorted.some((l) => l.below === v) ? v : '') } },
    series: [{
      name: 'RSI', type: 'line', data: values, showSymbol: false, lineStyle: { width: 1.2, color: p.blue },
      markArea: { silent: true, data: sorted.map((l, i) => [
        { yAxis: i ? sorted[i - 1].below : 0, itemStyle: { color: p.accent, opacity: i ? 0.08 : 0.16 } },
        { yAxis: l.below },
      ]) },
      markLine: { silent: true, symbol: 'none', data: sorted.map((l) => ({ yAxis: l.below })),
        lineStyle: { color: p.accent, type: 'dashed', width: 1 },
        label: { color: p.dim, fontSize: 10, formatter: (d) => d.value } },
    }],
  }));
}

// "DEEPLY OVERSOLD · 3rd close below 20", or the plain value when above the lines.
export function rsiNote(reading) {
  if (!reading || reading.line === null) return '';
  const nth = reading.days === 1 ? 'first close' : `${reading.days} closes in a row`;
  return `${reading.verdict} · ${nth} below ${reading.line}`;
}

// ------------------------------------------------------------------ tables

function noteClass(note) {
  if (!note) return 'dim';
  if (/OVERBOUGHT|DOWNTREND/.test(note)) return 'down';
  if (/OVERSOLD|UPTREND/.test(note)) return 'up';
  return 'dim';
}

function summaryTable(payload, readings, { zWindow, slopeWindow }) {
  const s = readings.summary;
  const gap = readings.unavailable;
  const missing = s.zscore === undefined;
  const rows = [
    ['PRICE', `${num(s.price)} AS OF ${payload.as_of}`, `${payload.sessions} sessions since ${payload.first_session}`],
    [`${zWindow} DMA / DISTANCE`, missing ? DASH : num(s.smaLong), missing ? gap.long_average : pct(s.distance)],
    ['Z-SCORE', missing || s.zscore === null ? DASH : num(s.zscore), missing ? gap.zscore : (s.verdict || '')],
    [`${zWindow} DMA SLOPE (ANN., ${slopeWindow}D)`, missing || s.slope === null ? DASH : pct(s.slope, 1),
      missing ? gap.slope_annualised : (s.slopeVerdict || '')],
    ['Z-SCORE BAND', s.band || DASH, ''],
    [`RSI(${readings.rsiPeriod})`, readings.rsiNow ? num(readings.rsiNow.value, 1) : DASH,
      readings.rsiNow ? (readings.rsiNow.verdict || '') : (readings.unavailable.rsi || '')],
  ];
  return table(['METRIC', 'VALUE', ''], rows.map(([label, value, note]) => el('tr', {}, [
    el('td', { class: 'dim', text: label }),
    el('td', { text: value }),
    // A verdict is a state and reads as a tag; a gap message stays prose.
    /^[A-Z][A-Z \-]+$/.test(note || '') ? el('td', {}, [tag(note, { up: 'up', down: 'down' }[noteClass(note)] || 'dim')])
      : el('td', { class: noteClass(note), text: note || '' }),
  ])));
}

function forwardCard(payload, readings, data) {
  const horizon = data.defaults.forward_return_days;
  if (!readings.forward) {
    return card(`${horizon}-DAY FORWARD RETURN BY Z-SCORE BAND`, null,
      el('div', { class: 'notice', text: `Not available for ${payload.ticker}: ${readings.unavailable.forward_returns}.` }));
  }
  const rows = readings.forward.map((row) => el('tr', {}, [
    el('td', { text: row.band }),
    el('td', { class: 'dim', text: row.count }),
    el('td', { class: dirClass(row.mean), text: row.mean === null ? DASH : pct(row.mean) }),
    el('td', { class: dirClass(row.median), text: row.median === null ? DASH : pct(row.median) }),
    el('td', { text: row.hitRate === null ? DASH : `${num(row.hitRate, 1)}%` }),
  ]));
  return card(
    `${horizon}-DAY FORWARD RETURN BY Z-SCORE BAND (${payload.first_session} → ${payload.as_of}, ${payload.sessions} SESSIONS)`,
    null,
    [
      table(['Z-SCORE BAND', 'COUNT', 'MEAN RETURN %', 'MEDIAN RETURN %', '% POSITIVE'], rows),
      el('div', { class: 'note-text', text: data.note }),
    ],
  );
}

// -------------------------------------------------------------------- tab

export default async function renderTechnicals(root, data, _manifest, ctx = {}) {
  const defaults = data.defaults;
  const available = new Set(data.available);
  root.append(sectionTitle('TECHNICALS', 'RELATIVE STRENGTH · MA SLOPE · Z-SCORE & REGIME'));

  // ---------------- Relative strength ------------------------------------
  const rsStatus = el('span', { class: 'field-note', text: '' });
  const ratioNode = el('div', { class: 'chart' });
  const macdNode = el('div', { class: 'chart short' });
  const [firstNum, firstDen] = defaults.presets[0].split('/');
  const presetSelect = el('select', {}, [
    ...defaults.presets.map((p) => el('option', { value: p, text: p })),
    el('option', { value: '', text: 'Custom…' }),
  ]);
  const numInput = el('input', { value: firstNum, size: '8' });
  const denInput = el('input', { value: firstDen, size: '8' });
  // Every range the price chart offers, 1M to MAX: indicators are computed on the
  // whole history first, so a 1M view still has its 200-day average and band.
  const rsPeriod = periodSelect(T.RANGES.map((r) => r.key), defaults.ratio_period);
  presetSelect.addEventListener('change', () => {
    if (!presetSelect.value) return;
    [numInput.value, denInput.value] = presetSelect.value.split('/');
    loadRatio();
  });
  const markCustom = () => { presetSelect.value = ''; };
  numInput.addEventListener('input', markCustom);
  denInput.addEventListener('input', markCustom);
  rsPeriod.addEventListener('change', () => loadRatio());

  const [maShort, maLong] = defaults.ratio_ma_periods;
  const { fast, slow, signal } = defaults.macd;

  let ratioCandles = true;
  const ratioNote = el('div', { class: 'field-note', text: '' });
  const ratioMode = segmented(['LINE', 'CANDLES'], 'CANDLES', (label) => {
    ratioCandles = label === 'CANDLES';
    ratioMode.setActive(label);
    loadRatio();
  });

  async function loadRatio() {
    const a = numInput.value.trim().toUpperCase();
    const b = denInput.value.trim().toUpperCase();
    rsStatus.textContent = `Loading ${a}/${b}…`;
    try {
      for (const symbol of [a, b]) if (!available.has(symbol)) throw new Error(`${symbol} is not in this build`);
      const [left, right] = await Promise.all([loadTicker(a), loadTicker(b)]);
      const closes = T.ratioSeries(left, right);
      // Candles need both legs' daily bars (since 2020) to reach back over the range;
      // otherwise the ratio is the close line over its whole history.
      let bars = null;
      if (ratioCandles && [a, b].every((s) => (data.bars || []).includes(s))) {
        const [la, lb] = await Promise.all([loadLongBars(a), loadLongBars(b)]);
        const made = la && lb ? T.ratioBars(la, lb) : null;
        if (made?.dates.length && T.rangeWithin(closes.dates, rsPeriod.value, made.dates[0])) bars = made;
      }
      // The averages, band, z-score and MACD read the series drawn, so a candle's close
      // and its averages are on one basis (the bars: split-adjusted, not dividend-adjusted).
      const { dates, ratio } = bars ? { dates: bars.dates, ratio: bars.close } : closes;
      const start = T.rangeStart(dates, rsPeriod.value);
      ratioNote.textContent = bars
        ? 'Candles: the body is the ratio of the two opens and the two closes, exact; the faint wick is the widest the day could have been '
          + '(the numerator\'s high over the denominator\'s low, and the reverse), as the two highs come at different times. '
          + 'Daily bars, split- but not dividend-adjusted; the averages, band and MACD are on the same closes.'
        : (ratioCandles ? `Candles need both names' daily bars, which start ${data.bars_start || '2020-01-01'}; this range is drawn as the close line.` : '');
      // Every line drawn is rebased to 1.00 at the window's first ratio, so a range switch
      // starts it again at one; the averages, band and MACD scale with it and keep their shape.
      // They are computed on the whole series first, so a short window still has its long averages.
      const base = T.firstFinite(cut(ratio, start));
      const view = (values) => T.rebase(cut(values, start), base);
      const averages = Object.fromEntries(defaults.ratio_ma_periods.map((w) => [`${w}MA`, view(T.sma(ratio, w))]));
      const bandWindow = Math.max(...defaults.ratio_ma_periods);
      const full = ratio.length >= bandWindow ? T.band(ratio, bandWindow, defaults.band_sigma) : null;
      ratioChart(ratioNode, cut(dates, start), {
        ratio: view(ratio), averages, sigma: defaults.band_sigma, window: bandWindow,
        band: full ? { upper: view(full.upper), lower: view(full.lower) } : null,
        candles: bars ? { open: view(bars.open), close: view(bars.close), upper: view(bars.upper), lower: view(bars.lower) } : null,
      });
      const z = T.zscore(ratio, bandWindow);
      const zNow = z[z.length - 1];
      const m = T.macd(ratio, defaults.macd);
      macdChart(macdNode, cut(dates, start), {
        macd: view(m.macd), signal: view(m.signal), histogram: view(m.histogram),
      });
      const now = ratio[ratio.length - 1];
      rsStatus.textContent = `Loaded ${a}/${b} as of ${dates[dates.length - 1]} · ${dates.length} shared sessions`
        + (isNum(base) && isNum(now) ? ` · 1.00 = ${dates[start]} · now ${num(now / base, 3)} (raw ratio ${num(now, 4)})` : '')
        + (isNum(zNow) ? ` · ratio ${zNow >= 0 ? '+' : '−'}${num(Math.abs(zNow), 2)}σ from its ${bandWindow}-day average` : '');
    } catch (error) {
      rsStatus.textContent = error.message;
      ratioNode.innerHTML = '';
      macdNode.innerHTML = '';
    }
  }

  root.append(card('RELATIVE STRENGTH RATIO', null, [
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field' }, [el('label', { text: 'PRESET' }), presetSelect]),
      el('div', { class: 'field' }, [el('label', { text: 'NUMERATOR' }), withSuggestions(numInput, data.available, data.names || {}, () => { markCustom(); loadRatio(); }, data.rank || [])]),
      el('div', { class: 'field' }, [el('label', { text: 'DENOMINATOR' }), withSuggestions(denInput, data.available, data.names || {}, () => { markCustom(); loadRatio(); }, data.rank || [])]),
      el('div', { class: 'field' }, [el('label', { text: 'PERIOD' }), rsPeriod]),
      el('div', { class: 'field' }, [el('label', { text: 'DRAW' }), ratioMode]),
      el('button', { class: 'action', text: 'LOAD', onclick: loadRatio }),
      rsStatus,
    ]),
    el('div', { class: 'card-title', text: `RATIO + ${maShort}/${maLong}-DAY MOVING AVERAGE & ${defaults.band_sigma}σ BAND (${maLong}-DAY) · 1.00 AT THE WINDOW'S START` }),
    ratioNode,
    ratioNote,
    el('div', { class: 'card-title', text: `MACD (${fast}/${slow}/${signal})` }),
    macdNode,
  ]));

  await loadRatio();
  const requested = resolveTicker(ctx.arg, (t) => available.has(t));
  await renderSingleTicker(root, data, { symbol: requested || (available.has('NVDA') ? 'NVDA' : data.available[0]) });
}

// The single-ticker section on its own, so the ticker page can show the same
// readings. `lockTicker` hides the ticker box when the page already names it.
// ``compact`` is the ticker page's form: default windows, no MA or period
// inputs in the card, and no forward-return table (that and the windows stay
// on TOOLS → TECHNICALS). The range, candles, log and MA chips work in both.
export async function renderSingleTicker(root, data, { symbol, lockTicker = false, compact = false }) {
  const defaults = data.defaults;
  // ---------------- Single ticker ----------------------------------------
  const stStatus = el('span', { class: 'field-note', text: '' });
  const tickerInput = el('input', { value: symbol, size: '8' });
  const maInput = el('input', { value: defaults.ma_periods.join(','), size: '12' });
  const slopeInput = el('input', { value: String(defaults.slope_window), size: '4', type: 'number', min: '1', max: String(MAX_SLOPE_WINDOW) });
  let range = T.RANGES.some((r) => r.key === defaults.single_ticker_period) ? defaults.single_ticker_period : '1Y';
  const stPeriod = periodSelect(T.RANGES.map((r) => r.key), range);
  let candlesOn = true;
  let logOn = false;
  let bandOn = true;
  let profileOn = true;
  let shownWindows = [...defaults.ma_periods].sort((a, b) => a - b);
  const summaryHost = el('div', {});
  const priceTitle = el('div', { class: 'card-title', text: '' });
  const stPriceNode = el('div', { class: 'chart price-tall' });
  const statHost = el('div', { class: 'tech-stats' });
  const slopeTitle = el('span', { class: 'card-title', text: '' });
  const slopeNode = el('div', { class: 'chart short' });
  const zNode = el('div', { class: 'chart short' });
  const rsiNode = el('div', { class: 'chart short' });
  const rsiTitle = el('span', { class: 'card-title', text: '' });
  const rsiInput = el('input', { value: String(rsiSettings(defaults).period), size: '3', type: 'number', min: '2', max: String(MAX_RSI_PERIOD) });
  const fwdHost = el('div', {});
  const zWindow = defaults.zscore_window;

  // Range buttons, candles and log. The buttons and the PERIOD select set the
  // same window; a range the candles do not reach is drawn as a line, with a note.
  const modeSwitch = segmented(['LINE', 'CANDLES'], 'CANDLES', (label) => {
    candlesOn = label === 'CANDLES';
    modeSwitch.setActive(label);
    loadSingle();
  });
  const rangeSwitch = segmented(BUTTON_RANGES, range, (key) => pickRange(key));
  const logButton = el('button', {
    type: 'button', text: 'LOG', 'aria-pressed': 'false',
    onclick: () => {
      logOn = !logOn;
      logButton.setAttribute('aria-pressed', String(logOn));
      loadSingle();
    },
  });
  // BAND hides the ±σ envelope; it is on by default and does not change the y-axis fit.
  const bandButton = el('button', {
    type: 'button', text: 'BAND', 'aria-pressed': 'true',
    onclick: () => {
      bandOn = !bandOn;
      bandButton.setAttribute('aria-pressed', String(bandOn));
      loadSingle();
    },
  });
  // VOL PROFILE: volume by price beside the candles, on by default; candles only, since a line has no volume.
  const profileButton = el('button', {
    type: 'button', text: 'VOL PROFILE', 'aria-pressed': 'true', title: 'Volume by price for the sessions on screen',
    onclick: () => {
      profileOn = !profileOn;
      profileButton.setAttribute('aria-pressed', String(profileOn));
      loadSingle();
    },
  });
  const profileNote = el('div', { class: 'tech-note', text: '' });
  const profileLabel = el('div', { class: 'tech-note', text: '' });
  // The same name on the other pages of the flow: company, history of its moves, a plan.
  const flowLinks = el('div', { class: 'field-note' });
  const drawLinks = (name) => {
    const items = [['TICKER PAGE', 'ticker'], ['MOVE CHECK', 'movecheck'], ['TRADE DESK', 'trade']];
    flowLinks.replaceChildren(`${name} ON `, ...items.flatMap(([label, tab], i) => [
      i ? ' · ' : '', el('a', { href: `#${tab}/${encodeURIComponent(name)}`, text: label }),
    ]));
  };
  const toolNote = el('span', { class: 'tech-note', text: '' });
  const toolbar = el('div', { class: 'tech-toolbar' }, [
    modeSwitch, rangeSwitch, el('div', { class: 'period-switch' }, [logButton, bandButton, profileButton]), toolNote,
  ]);

  function pickRange(key) {
    range = key;
    rangeSwitch.setActive(key);
    stPeriod.value = key;
    loadSingle();
  }
  stPeriod.addEventListener('change', () => pickRange(stPeriod.value));

  // MA chips, kept in step with the MA PERIODS input: a chip removes its
  // window, "+ MA" adds one. The last chip cannot be removed.
  const chipHost = el('span', { class: 'tech-chip-list' });
  const addInput = el('input', {
    type: 'number', min: '2', max: String(MAX_MA_WINDOW), size: '4', hidden: '', 'aria-label': 'Moving-average period to add',
  });
  const addButton = el('button', {
    type: 'button', class: 'tech-chip-add', text: '+ MA',
    onclick: () => { addInput.hidden = false; addInput.focus(); },
  });
  const chipRow = el('div', { class: 'tech-chips' }, [chipHost, addInput, addButton]);
  addInput.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { addInput.hidden = true; addInput.value = ''; return; }
    if (event.key !== 'Enter' || !addInput.value.trim()) return;
    try {
      const next = T.parseWindows([...shownWindows, addInput.value].join(','), { max: MAX_MA_WINDOW });
      addInput.hidden = true;
      addInput.value = '';
      setWindows(next);
    } catch (error) {
      stStatus.textContent = error.message;
    }
  });

  function setWindows(list) {
    maInput.value = list.join(', ');
    loadSingle();
  }

  function drawChips() {
    const removable = shownWindows.length > 1;
    chipHost.replaceChildren(...shownWindows.map((w) => el('span', { class: 'tech-chip' }, [
      `SMA ${w}`,
      el('button', {
        type: 'button', class: 'tech-chip-x', text: '×', 'aria-label': `Remove SMA ${w}`,
        disabled: removable ? null : '',
        onclick: () => setWindows(shownWindows.filter((x) => x !== w)),
      }),
    ])));
  }

  async function loadSingle() {
    const symbol = resolveTicker(tickerInput.value.trim().toUpperCase(), (t) => (data.available || []).includes(t));
    drawLinks(symbol);
    stStatus.textContent = `Loading ${symbol}…`;
    try {
      const windows = T.parseWindows(maInput.value, { max: MAX_MA_WINDOW });
      shownWindows = windows;
      drawChips();
      const slopeWindow = Number(slopeInput.value);
      if (!Number.isInteger(slopeWindow) || slopeWindow < 1 || slopeWindow > MAX_SLOPE_WINDOW) {
        throw new Error(`Slope window must be a whole number from 1 to ${MAX_SLOPE_WINDOW}`);
      }
      const rsiPeriod = Number(rsiInput.value);
      if (!Number.isInteger(rsiPeriod) || rsiPeriod < 2 || rsiPeriod > MAX_RSI_PERIOD) {
        throw new Error(`RSI period must be a whole number from 2 to ${MAX_RSI_PERIOD}`);
      }
      const payload = await loadTicker(symbol);
      const bars = payload.ohlcv?.dates?.length ? payload.ohlcv : null;
      modeSwitch.hidden = !bars;
      let candles = candlesOn && bars && T.rangeWithin(payload.dates, range, bars.dates[0]) ? bars : null;
      // Past the payload's candles, the bars since 2020 carry the range when they reach back far enough.
      let long = null;
      if (candlesOn && bars && !candles && (data.bars || []).includes(symbol)) {
        long = await loadLongBars(symbol);
        if (long?.dates?.length && T.rangeWithin(payload.dates, range, long.dates[0])) candles = long;
      }
      const firstBar = long?.dates?.[0] || bars?.dates?.[0];
      toolNote.textContent = candlesOn && bars && !candles
        ? `Candles and the volume profile start ${firstBar}; ${range} reaches further back, so it is drawn as a line.` : '';

      // The price chart and its readings use the candles' close when candles
      // are shown, else the close history the other charts use.
      const series = candles ? { dates: candles.dates, close: candles.close } : { dates: payload.dates, close: payload.close };
      const readings = computeSingle(payload, { windows, slopeWindow, defaults, rsiPeriod, series: series.close });
      const start = T.rangeStart(payload.dates, range);
      const dates = cut(payload.dates, start);

      summaryHost.replaceChildren(summaryTable(payload, readings, { zWindow, slopeWindow }));
      priceTitle.textContent = `${candles ? 'PRICE, CANDLES' : 'PRICE'}, ${windows.join('/')}-DAY SMA & ${defaults.band_sigma}σ BAND (${zWindow} DMA)`;
      // The whole series goes to the chart; the range is the zoom window.
      priceChart(stPriceNode, {
        bars: candles, dates: series.dates, close: series.close, averages: readings.averages,
        bandLines: bandOn ? readings.bandLines : null, sigma: defaults.band_sigma, start: T.rangeStart(series.dates, range),
        log: logOn, ticker: payload.ticker, profile: profileOn,
        onProfile: (reading) => {
          profileNote.textContent = profileText(reading);
          profileLabel.textContent = profileWindow(reading);
        },
      });
      profileButton.hidden = !candles;
      if (!candles || !profileOn) {
        profileNote.textContent = '';
        profileLabel.textContent = '';
      }
      statHost.replaceChildren(...statItems(payload, series, readings, windows).map(([label, text, tone]) => el('div', { class: 'tech-stat' }, [
        el('span', { class: 'tech-stat-label', text: label }),
        el('span', { class: `tech-stat-value ${tone}`, text }),
      ])));

      slopeTitle.textContent = `SMA SLOPE (% PER DAY, OVER ${slopeWindow} SESSIONS)`;
      multiLine(slopeNode, dates, Object.fromEntries(
        Object.entries(readings.slopes).map(([w, v]) => [`${w}-day SMA slope`, cut(v, start)]),
      ));
      if (readings.z.length) zChart(zNode, dates, cut(readings.z, start));
      else zNode.replaceChildren(el('div', { class: 'note-text', text: `Not available for ${symbol}: ${readings.unavailable.zscore}.` }));

      const lineText = [...readings.lines].sort((a, b) => b.below - a.below).map((l) => l.below).join(' / ');
      rsiTitle.textContent = `RSI(${rsiPeriod}) · LINES ${lineText}${readings.rsiNow?.line ? ` · ${rsiNote(readings.rsiNow)}` : ''}`;
      if (readings.rsi.length) rsiChart(rsiNode, dates, cut(readings.rsi, start), readings.lines);
      else rsiNode.replaceChildren(el('div', { class: 'note-text', text: `Not available for ${symbol}: ${readings.unavailable.rsi}.` }));

      if (!compact) fwdHost.replaceChildren(forwardCard(payload, readings, data));
      const gaps = Object.keys(readings.unavailable).length;
      stStatus.textContent = gaps
        ? `Loaded ${symbol} · ${payload.sessions} sessions since ${payload.first_session} · ${gaps} reading(s) need more history`
        : `Loaded ${symbol} as of ${payload.as_of}.`;
    } catch (error) {
      stStatus.textContent = error.message;
    }
  }

  // Suggestions first, so a picked symbol's Enter is not also read as the half-typed one.
  const tickerBox = withSuggestions(tickerInput, data.available || [], data.names || {}, () => loadSingle(), data.rank || []);
  tickerInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') loadSingle(); });

  const rsiCard = card('', null, [rsiNode, el('div', { class: 'field-note', text: RSI_NOTE })]);
  rsiCard.querySelector('.card-title').replaceWith(rsiTitle);

  for (const input of [maInput, slopeInput, rsiInput]) {
    input.addEventListener('keydown', (event) => { if (event.key === 'Enter') loadSingle(); });
  }

  if (compact) {
    root.append(card('PRICE & TREND', null, [priceTitle, toolbar, chipRow, statHost, profileLabel, stPriceNode, profileNote, summaryHost, stStatus]));
    const slopeCard = card('', null, slopeNode);
    slopeCard.querySelector('.card-title').replaceWith(slopeTitle);
    root.append(el('div', { class: 'grid two' }, [slopeCard, card(`Z-SCORE VS ${zWindow} DMA`, null, zNode)]));
    root.append(rsiCard);
    await loadSingle();
    return;
  }

  root.append(card('SINGLE-TICKER TECHNICALS', null, [
    el('div', { class: 'field-row' }, [
      lockTicker ? null : el('div', { class: 'field' }, [el('label', { text: 'TICKER' }), tickerBox]),
      el('div', { class: 'field' }, [el('label', { text: 'MA PERIODS' }), maInput]),
      el('div', { class: 'field' }, [el('label', { text: 'SLOPE WINDOW (D)' }), slopeInput]),
      el('div', { class: 'field' }, [el('label', { text: 'RSI PERIOD' }), rsiInput]),
      el('div', { class: 'field' }, [el('label', { text: 'PERIOD' }), stPeriod]),
      el('button', { class: 'action', text: 'LOAD', onclick: loadSingle }),
      stStatus,
    ]),
    flowLinks,
    summaryHost,
    priceTitle,
    toolbar,
    chipRow,
    statHost,
    profileLabel,
    stPriceNode,
    profileNote,
  ]));

  const slopeCard = card('', null, slopeNode);
  slopeCard.querySelector('.card-title').replaceWith(slopeTitle);
  root.append(el('div', { class: 'grid two' }, [slopeCard, card(`Z-SCORE VS ${zWindow} DMA`, null, zNode)]));
  root.append(rsiCard);
  root.append(fwdHost);

  await loadSingle();
}
