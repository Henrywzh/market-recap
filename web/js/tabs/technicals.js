// TECHNICALS: relative strength and single-ticker regime, with the windows in
// the reader's hands. The build bakes each ticker's close history; every
// indicator is computed here by technicals-math.js on the full history and
// then cut to the chosen period.

import { el, card, table, num, pct, dirClass, sectionTitle, DASH } from '../fmt.js';
import { render, multiLine, SERIES_COLORS } from '../charts.js';
import * as T from '../technicals-math.js';

const TICKER_BASE = 'artifacts/tickers';
// A sanity bound on typed windows, not a data limit: ten years of history
// would support more, but nobody means a 2,000-day "moving average".
const MAX_MA_WINDOW = 400;
const MAX_SLOPE_WINDOW = 60;

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

const cut = (values, start) => values.slice(start);

function periodSelect(periods, selected) {
  return el('select', {}, Object.keys(periods).map((label) => {
    const option = el('option', { value: label, text: label });
    if (label === selected) option.selected = true;
    return option;
  }));
}

function needs(window, sessions) {
  return `needs ${window} sessions, has ${sessions}`;
}

// ---------------------------------------------------------------- readings

function computeSingle(payload, { windows, slopeWindow, defaults }) {
  const close = payload.close;
  const n = close.length;
  const zWindow = defaults.zscore_window;
  const horizon = defaults.forward_return_days;
  const unavailable = {};

  const formed = windows.filter((w) => n >= w);
  windows.filter((w) => n < w).forEach((w) => { unavailable[`sma_${w}`] = needs(w, n); });
  const averages = Object.fromEntries(formed.map((w) => [w, T.sma(close, w)]));
  const slopes = Object.fromEntries(formed.map((w) => [w, T.smaSlope(close, w, slopeWindow)]));

  let summary = { price: close[n - 1] };
  let z = [];
  let bandLines = null;
  if (n >= zWindow) {
    const long = T.sma(close, zWindow);
    z = T.zscore(close, zWindow);
    bandLines = T.band(close, zWindow, defaults.band_sigma);
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
  return { averages, slopes, z, bandLines, summary, forward, unavailable };
}

// ------------------------------------------------------------------ charts

const BAND_BASE = 'band base';

function priceChart(node, payload, readings, start, defaults) {
  const dates = cut(payload.dates, start);
  const { bandLines } = readings;
  render(node, (option, p) => withLegend(option, p, {
    ...option,
    grid: { ...option.grid, bottom: 52 },
    xAxis: { ...option.xAxis, data: dates },
    series: [
      // The band is a stacked invisible base plus a filled span, so it reads
      // as an envelope rather than two unrelated lines.
      ...(bandLines ? [
        { name: BAND_BASE, type: 'line', data: cut(bandLines.lower, start), stack: 'band', showSymbol: false,
          lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 }, silent: true, tooltip: { show: false } },
        { name: `±${defaults.band_sigma}σ band`, type: 'line', stack: 'band', showSymbol: false, silent: true,
          data: cut(bandLines.upper, start).map((v, i) => {
            const low = bandLines.lower[start + i];
            return v === null || low === null ? null : v - low;
          }),
          lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(232,163,61,0.13)' }, tooltip: { show: false } },
      ] : []),
      { name: `${payload.ticker} Close`, type: 'line', data: cut(payload.close, start), showSymbol: false,
        lineStyle: { width: 1.4, color: p.text }, z: 5 },
      ...Object.entries(readings.averages).map(([w, values], i) => ({
        name: `${w}-day SMA`, type: 'line', data: cut(values, start), showSymbol: false,
        lineStyle: { width: 1, color: SERIES_COLORS[i % SERIES_COLORS.length] },
      })),
    ],
  }));
}

// The band's invisible base series exists only to lift the fill; it has no
// place in the legend.
function withLegend(option, p, built) {
  return {
    ...built,
    legend: {
      bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9,
      data: built.series.map((s) => s.name).filter((name) => name !== BAND_BASE),
    },
  };
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
  ];
  return table(['METRIC', 'VALUE', ''], rows.map(([label, value, note]) => el('tr', {}, [
    el('td', { class: 'dim', text: label }),
    el('td', { text: value }),
    el('td', { class: noteClass(note), text: note || '' }),
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
  const rsPeriod = periodSelect(data.periods, defaults.ratio_period);
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

  async function loadRatio() {
    const a = numInput.value.trim().toUpperCase();
    const b = denInput.value.trim().toUpperCase();
    rsStatus.textContent = `Loading ${a}/${b}…`;
    try {
      for (const symbol of [a, b]) if (!available.has(symbol)) throw new Error(`${symbol} is not in this build`);
      const [left, right] = await Promise.all([loadTicker(a), loadTicker(b)]);
      const { dates, ratio } = T.ratioSeries(left, right);
      const start = T.viewStart(dates, data.periods[rsPeriod.value]);
      const lines = { Ratio: cut(ratio, start) };
      defaults.ratio_ma_periods.forEach((w) => { lines[`${w}MA`] = cut(T.sma(ratio, w), start); });
      multiLine(ratioNode, cut(dates, start), lines);
      const m = T.macd(ratio, defaults.macd);
      macdChart(macdNode, cut(dates, start), {
        macd: cut(m.macd, start), signal: cut(m.signal, start), histogram: cut(m.histogram, start),
      });
      rsStatus.textContent = `Loaded ${a}/${b} as of ${dates[dates.length - 1]} · ${dates.length} shared sessions`;
    } catch (error) {
      rsStatus.textContent = error.message;
      ratioNode.innerHTML = '';
      macdNode.innerHTML = '';
    }
  }

  root.append(card('RELATIVE STRENGTH RATIO', null, [
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field' }, [el('label', { text: 'PRESET' }), presetSelect]),
      el('div', { class: 'field' }, [el('label', { text: 'NUMERATOR' }), numInput]),
      el('div', { class: 'field' }, [el('label', { text: 'DENOMINATOR' }), denInput]),
      el('div', { class: 'field' }, [el('label', { text: 'PERIOD' }), rsPeriod]),
      el('button', { class: 'action', text: 'LOAD', onclick: loadRatio }),
      rsStatus,
    ]),
    el('div', { class: 'card-title', text: `RATIO + ${maShort}/${maLong}-DAY MOVING AVERAGE` }),
    ratioNode,
    el('div', { class: 'card-title', text: `MACD (${fast}/${slow}/${signal})` }),
    macdNode,
  ]));

  await loadRatio();
  const requested = ctx.arg;
  await renderSingleTicker(root, data, { symbol: requested || (available.has('NVDA') ? 'NVDA' : data.available[0]) });
}

// The single-ticker section on its own, so the ticker page can show the same
// readings. `lockTicker` hides the ticker box when the page already names it.
export async function renderSingleTicker(root, data, { symbol, lockTicker = false }) {
  const defaults = data.defaults;
  // ---------------- Single ticker ----------------------------------------
  const stStatus = el('span', { class: 'field-note', text: '' });
  const tickerInput = el('input', { value: symbol, size: '8' });
  const maInput = el('input', { value: defaults.ma_periods.join(','), size: '12' });
  const slopeInput = el('input', { value: String(defaults.slope_window), size: '4', type: 'number', min: '1', max: String(MAX_SLOPE_WINDOW) });
  const stPeriod = periodSelect(data.periods, defaults.single_ticker_period);
  const summaryHost = el('div', {});
  const priceTitle = el('div', { class: 'card-title', text: '' });
  const stPriceNode = el('div', { class: 'chart tall' });
  const slopeTitle = el('span', { class: 'card-title', text: '' });
  const slopeNode = el('div', { class: 'chart short' });
  const zNode = el('div', { class: 'chart short' });
  const fwdHost = el('div', {});
  const zWindow = defaults.zscore_window;

  async function loadSingle() {
    const symbol = tickerInput.value.trim().toUpperCase();
    stStatus.textContent = `Loading ${symbol}…`;
    try {
      const windows = T.parseWindows(maInput.value, { max: MAX_MA_WINDOW });
      const slopeWindow = Number(slopeInput.value);
      if (!Number.isInteger(slopeWindow) || slopeWindow < 1 || slopeWindow > MAX_SLOPE_WINDOW) {
        throw new Error(`Slope window must be a whole number from 1 to ${MAX_SLOPE_WINDOW}`);
      }
      const payload = await loadTicker(symbol);
      const readings = computeSingle(payload, { windows, slopeWindow, defaults });
      const start = T.viewStart(payload.dates, data.periods[stPeriod.value]);
      const dates = cut(payload.dates, start);

      summaryHost.replaceChildren(summaryTable(payload, readings, { zWindow, slopeWindow }));
      priceTitle.textContent = `PRICE, ${windows.join('/')}-DAY SMA & ${defaults.band_sigma}σ BAND (${zWindow} DMA)`;
      priceChart(stPriceNode, payload, readings, start, defaults);

      slopeTitle.textContent = `SMA SLOPE (% PER DAY, OVER ${slopeWindow} SESSIONS)`;
      multiLine(slopeNode, dates, Object.fromEntries(
        Object.entries(readings.slopes).map(([w, v]) => [`${w}-day SMA slope`, cut(v, start)]),
      ));
      if (readings.z.length) zChart(zNode, dates, cut(readings.z, start));
      else zNode.replaceChildren(el('div', { class: 'note-text', text: `Not available for ${symbol}: ${readings.unavailable.zscore}.` }));

      fwdHost.replaceChildren(forwardCard(payload, readings, data));
      const gaps = Object.keys(readings.unavailable).length;
      stStatus.textContent = gaps
        ? `Loaded ${symbol} · ${payload.sessions} sessions since ${payload.first_session} · ${gaps} reading(s) need more history`
        : `Loaded ${symbol} as of ${payload.as_of}.`;
    } catch (error) {
      stStatus.textContent = error.message;
    }
  }

  for (const input of [tickerInput, maInput, slopeInput]) {
    input.addEventListener('keydown', (event) => { if (event.key === 'Enter') loadSingle(); });
  }
  stPeriod.addEventListener('change', () => loadSingle());

  root.append(card('SINGLE-TICKER TECHNICALS', null, [
    el('div', { class: 'field-row' }, [
      lockTicker ? null : el('div', { class: 'field' }, [el('label', { text: 'TICKER' }), tickerInput]),
      el('div', { class: 'field' }, [el('label', { text: 'MA PERIODS' }), maInput]),
      el('div', { class: 'field' }, [el('label', { text: 'SLOPE WINDOW (D)' }), slopeInput]),
      el('div', { class: 'field' }, [el('label', { text: 'PERIOD' }), stPeriod]),
      el('button', { class: 'action', text: 'LOAD', onclick: loadSingle }),
      stStatus,
    ]),
    summaryHost,
    priceTitle,
    stPriceNode,
  ]));

  const slopeCard = card('', null, slopeNode);
  slopeCard.querySelector('.card-title').replaceWith(slopeTitle);
  root.append(el('div', { class: 'grid two' }, [slopeCard, card(`Z-SCORE VS ${zWindow} DMA`, null, zNode)]));
  root.append(fwdHost);

  await loadSingle();
}
