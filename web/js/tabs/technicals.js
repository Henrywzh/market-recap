import { el, card, table, num, pct, dirClass, sectionTitle, DASH } from '../fmt.js';
import { render, multiLine, SERIES_COLORS } from '../charts.js';
import { loadArtifact } from '../app.js';

const TICKER_BASE = '../artifacts/tickers';

async function loadTicker(symbol) {
  const response = await fetch(`${TICKER_BASE}/${symbol.toUpperCase()}.json`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`${symbol.toUpperCase()} is not in this build`);
  return response.json();
}

function priceChart(node, payload) {
  render(node, (option, p) => {
    const windows = Object.keys(payload.moving_averages);
    return {
      ...option,
      grid: { ...option.grid, bottom: 52 },
      legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
      xAxis: { ...option.xAxis, data: payload.dates },
      series: [
        // The band is drawn as a stacked invisible base plus a filled span, so
        // it reads as an envelope rather than two unrelated lines. A ticker
        // without enough history simply has no band.
        ...(payload.band_upper.length ? [
          { name: 'band base', type: 'line', data: payload.band_lower, stack: 'band', showSymbol: false,
            lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 }, silent: true, tooltip: { show: false } },
          { name: '±1.5σ band', type: 'line', stack: 'band', showSymbol: false, silent: true,
            data: payload.band_upper.map((v, i) => (v === null || payload.band_lower[i] === null ? null : v - payload.band_lower[i])),
            lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(232,163,61,0.13)' }, tooltip: { show: false } },
        ] : []),
        { name: `${payload.ticker} Close`, type: 'line', data: payload.close, showSymbol: false,
          lineStyle: { width: 1.4, color: p.text }, z: 5 },
        ...windows.map((w, i) => ({
          name: `${w}-day SMA`, type: 'line', data: payload.moving_averages[w], showSymbol: false,
          lineStyle: { width: 1, color: SERIES_COLORS[i % SERIES_COLORS.length] },
        })),
      ],
    };
  });
}

function summaryTable(summary, payload) {
  const gap = payload.unavailable || {};
  const w = payload_zwindow(payload);
  const rows = [
    ['PRICE', `${num(summary.price)} AS OF ${payload.as_of}`, `${payload.sessions} sessions since ${payload.first_session}`],
    [`${w} DMA / DISTANCE`, summary.sma_long === null ? DASH : num(summary.sma_long),
      summary.sma_long === null ? (gap.long_average || '') : pct(summary.distance_pct)],
    ['Z-SCORE', summary.zscore === null ? DASH : num(summary.zscore),
      summary.zscore === null ? (gap.zscore || '') : (summary.verdict || '')],
    [`${w} DMA SLOPE (ANN.)`, summary.slope_annualised === null ? DASH : pct(summary.slope_annualised, 1),
      summary.slope_annualised === null ? (gap.slope_annualised || '') : slopeVerdict(summary.slope_annualised)],
    ['Z-SCORE BAND', summary.zscore_band || DASH, ''],
  ];
  return table(['METRIC', 'VALUE', ''], rows.map(([label, value, note]) => el('tr', {}, [
    el('td', { class: 'dim', text: label }),
    el('td', { text: value }),
    el('td', { class: noteClass(note), text: note }),
  ])));
}

function payload_zwindow(payload) {
  return payload.zscore_window || 200;
}

function slopeVerdict(value) {
  if (value === null || value === undefined) return '';
  if (value > 20) return 'STRONG UPTREND';
  if (value > 2) return 'UPTREND';
  if (value < -20) return 'STRONG DOWNTREND';
  if (value < -2) return 'DOWNTREND';
  return 'FLAT';
}

function loadedMessage(symbol, payload) {
  const missing = Object.keys(payload.unavailable || {});
  return missing.length
    ? `Loaded ${symbol} · ${payload.sessions} sessions since ${payload.first_session} · `
      + `${missing.length} reading(s) need more history`
    : `Loaded ${symbol} as of ${payload.as_of}.`;
}

function gapText(payload, key) {
  const reason = (payload.unavailable || {})[key];
  return reason
    ? `Not available for ${payload.ticker}: ${reason}.`
    : `Not available for ${payload.ticker}.`;
}

function noteClass(note) {
  if (!note) return 'dim';
  if (/OVERBOUGHT|DOWNTREND/.test(note)) return 'down';
  if (/OVERSOLD|UPTREND/.test(note)) return 'up';
  return 'dim';
}

export default async function renderTechnicals(root, data) {
  root.append(sectionTitle('TECHNICALS', 'RELATIVE STRENGTH · MA SLOPE · Z-SCORE & REGIME'));

  const available = new Set(data.available);

  // ---------------- Relative strength ------------------------------------
  const rsStatus = el('span', { class: 'field-note', text: '' });
  const ratioNode = el('div', { class: 'chart' });
  const macdNode = el('div', { class: 'chart short' });

  const presetSelect = el('select', { id: 'rs-preset' }, data.presets.map((p) => el('option', { value: p, text: p })));
  const numInput = el('input', { id: 'rs-num', value: 'XLK', size: '8' });
  const denInput = el('input', { id: 'rs-den', value: 'SPY', size: '8' });
  presetSelect.addEventListener('change', () => {
    const [a, b] = presetSelect.value.split('/');
    numInput.value = a;
    denInput.value = b;
  });

  async function loadRatio() {
    const a = numInput.value.trim().toUpperCase();
    const b = denInput.value.trim().toUpperCase();
    rsStatus.textContent = `Loading ${a}/${b}…`;
    try {
      if (!available.has(a)) throw new Error(`${a} is not in this build`);
      if (!available.has(b)) throw new Error(`${b} is not in this build`);
      const [left, right] = await Promise.all([loadTicker(a), loadTicker(b)]);

      // Align on shared dates: the two series can start on different days.
      const rightMap = new Map(right.dates.map((d, i) => [d, right.close[i]]));
      const dates = [];
      const ratio = [];
      left.dates.forEach((d, i) => {
        const denominator = rightMap.get(d);
        if (denominator) { dates.push(d); ratio.push(left.close[i] / denominator); }
      });
      const sma = (values, window) => values.map((_, i) =>
        (i + 1 < window ? null : values.slice(i + 1 - window, i + 1).reduce((s, v) => s + v, 0) / window));

      multiLine(ratioNode, dates, { Ratio: ratio, '60MA': sma(ratio, 60), '200MA': sma(ratio, 200) });

      const ema = (values, span) => {
        const k = 2 / (span + 1);
        let prev = values[0];
        return values.map((v, i) => (i === 0 ? (prev = v) : (prev = v * k + prev * (1 - k))));
      };
      const line = ema(ratio, 8).map((v, i) => v - ema(ratio, 17)[i]);
      const signal = ema(line, 9);
      render(macdNode, (option, p) => ({
        ...option,
        grid: { ...option.grid, top: 10, bottom: 24 },
        xAxis: { ...option.xAxis, data: dates },
        series: [
          { name: 'Histogram', type: 'bar', barMaxWidth: 3,
            data: line.map((v, i) => ({ value: v - signal[i], itemStyle: { color: v - signal[i] >= 0 ? p.up : p.down } })) },
          { name: 'MACD', type: 'line', data: line, showSymbol: false, lineStyle: { width: 1, color: p.blue } },
          { name: 'Signal', type: 'line', data: signal, showSymbol: false, lineStyle: { width: 1, color: p.accent } },
        ],
      }));
      rsStatus.textContent = `Loaded ${a}/${b} as of ${left.as_of}. ${dates.length} shared sessions.`;
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
      el('button', { class: 'action', text: 'LOAD', onclick: loadRatio }),
      rsStatus,
    ]),
    el('div', { class: 'card-title', text: 'RATIO + 60/200-DAY MOVING AVERAGE' }),
    ratioNode,
    el('div', { class: 'card-title', text: 'MACD (8/17/9)' }),
    macdNode,
  ]));

  // ---------------- Single ticker ----------------------------------------
  const stStatus = el('span', { class: 'field-note', text: '' });
  const tickerInput = el('input', { id: 'st-ticker', value: 'NVDA', size: '8' });
  const summaryHost = el('div', {});
  const stPriceNode = el('div', { class: 'chart tall' });
  const slopeNode = el('div', { class: 'chart short' });
  const zNode = el('div', { class: 'chart short' });
  const fwdHost = el('div', {});

  async function loadSingle() {
    const symbol = tickerInput.value.trim().toUpperCase();
    stStatus.textContent = `Loading ${symbol}…`;
    try {
      const payload = await loadTicker(symbol);
      priceChart(stPriceNode, payload);

      summaryHost.innerHTML = '';
      summaryHost.append(summaryTable(payload.summary, payload));

      multiLine(slopeNode, payload.dates,
        Object.fromEntries(Object.entries(payload.sma_slope).map(([w, v]) => [`${w}-day SMA slope`, v])));

      if (!payload.zscore.length) {
        zNode.innerHTML = '';
        zNode.append(el('div', { class: 'note-text', text: gapText(payload, 'zscore') }));
      } else render(zNode, (option, p) => ({
        ...option,
        grid: { ...option.grid, top: 10, bottom: 24 },
        xAxis: { ...option.xAxis, data: payload.dates, boundaryGap: true },
        series: [{
          type: 'bar', barMaxWidth: 3,
          data: payload.zscore.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? '#2dd4bf' : p.down } })),
          markLine: { silent: true, symbol: 'none', data: [{ yAxis: 0 }],
            lineStyle: { color: p.faint, type: 'dashed' }, label: { show: false } },
        }],
      }));

      const fwd = payload.forward_returns;
      if (!fwd.rows.length) {
        fwdHost.innerHTML = '';
        fwdHost.append(card(`${fwd.horizon}-DAY FORWARD RETURN BY Z-SCORE BAND`, null,
          el('div', { class: 'notice', text: gapText(payload, 'forward_returns') })));
        stStatus.textContent = loadedMessage(symbol, payload);
        return;
      }
      const rows = fwd.rows.map((row) => el('tr', {}, [
        el('td', { text: row.band }),
        el('td', { class: 'dim', text: row.count }),
        el('td', { class: dirClass(row.mean), text: row.mean === null ? DASH : pct(row.mean) }),
        el('td', { class: dirClass(row.median), text: row.median === null ? DASH : pct(row.median) }),
        el('td', { text: row.hit_rate === null ? DASH : `${num(row.hit_rate, 1)}%` }),
      ]));
      fwdHost.innerHTML = '';
      fwdHost.append(card(
        `${fwd.horizon}-DAY FORWARD RETURN BY Z-SCORE BAND (${fwd.start} → ${payload.as_of}, ${fwd.sessions} SESSIONS)`,
        null,
        [
          table(['Z-SCORE BAND', 'COUNT', 'MEAN RETURN %', 'MEDIAN RETURN %', '% POSITIVE'], rows),
          el('div', { class: 'note-text', text: data.note }),
        ],
      ));
      stStatus.textContent = loadedMessage(symbol, payload);
    } catch (error) {
      stStatus.textContent = error.message;
    }
  }

  root.append(card('SINGLE-TICKER TECHNICALS', null, [
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field' }, [el('label', { text: 'TICKER' }), tickerInput]),
      el('button', { class: 'action', text: 'LOAD', onclick: loadSingle }),
      stStatus,
    ]),
    summaryHost,
    el('div', { class: 'card-title', text: `PRICE, MOVING AVERAGES & 1.5σ BAND (${data.zscore_window} DMA)` }),
    stPriceNode,
  ]));

  root.append(el('div', { class: 'grid two' }, [
    card('SMA SLOPE (% PER DAY)', null, slopeNode),
    card(`Z-SCORE VS ${data.zscore_window} DMA`, null, zNode),
  ]));
  root.append(fwdHost);

  await loadRatio();
  await loadSingle();
}
