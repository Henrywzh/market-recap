import { el, card, num, pct, DASH, periodSwitch } from './fmt.js';
import { render } from './charts.js';
import { withSuggestions } from './ticker-suggest.js';
import { rangeStart } from './range.js';
import { chipView } from './chip-card.js';
import { eventStudy, simulateNextOpen } from './trade-events.js';
import { median, histogram } from './movecheck-model.js';

const note = (text) => el('div', { class: 'wb-note', text });
const field = (label, node) => el('label', { class: 'wb-field' }, [el('span', { text: label }), node]);
const stat = (label, value, detail = '') => el('div', { class: 'wb-stat' }, [el('span', { text: label }), el('strong', { text: value, class: /^[−-]/.test(value) ? 'down' : /^\+/.test(value) ? 'up' : '' }), note(detail)]);
const pctText = (v) => Number.isFinite(v) ? pct(v, 2) : DASH;

export default function workbench(root, technicals, ctx) {
  root.className = `${root.className || ''} trade-workbench`.trim();
  const available = technicals.available || [];
  const picker = el('input', { value: ctx.arg || 'QQQ', 'aria-label': 'Workbench ticker' });
  const symbolInfo = el('div', { class: 'wb-symbol-info' });
  const identities = Object.fromEntries(available.map(ticker => [ticker, {
    type: technicals.etf_names?.[ticker] ? 'ETF' : '',
  }]));
  const names = { ...(technicals.names || {}), ...(technicals.etf_names || {}) };
  const suggested = withSuggestions(picker, available, names, () => load(), technicals.rank || [], identities);
  const symbolPicker = el('div', { class: 'wb-symbol-picker' }, [field('SYMBOL', suggested), symbolInfo]);
  const execution = el('select', { 'aria-label': 'Execution price interval' }, [
    el('option', { value: 'open-close', text: 'OPEN → CLOSE' }),
    el('option', { value: 'close-close', text: 'CLOSE → CLOSE' }),
    el('option', { value: 'open-open', text: 'OPEN → OPEN' }),
    el('option', { value: 'close-open', text: 'CLOSE → OPEN · overnight' }),
  ]);
  const timingNote = note('');
  const status = note('Loading…');
  const map = el('div', { class: 'wb-map', 'aria-label': 'Price volume structure map' });
  const readings = el('aside', { class: 'wb-readings' });
  let profileRange = '1Y';
  const profileNote = note('');
  const profileRanges = periodSwitch(['YTD', '1Y', '2Y', '5Y', 'MAX'], profileRange, (range) => {
    profileRange = range; update(); drawMap();
  });
  const executionNote = note('');
  const mapTitle = el('h2', { text: 'Market structure' });
  const direction = el('select', { 'aria-label': 'Event direction' }, [el('option', { value: '-1', text: 'EXTREME FALL' }), el('option', { value: '1', text: 'POSITIVE BURST' })]);
  const threshold = el('input', { type: 'range', min: '.5', max: '5', step: '.5', value: '2', 'aria-label': 'Sigma threshold' });
  const thresholdLabel = el('strong', { class: 'wb-threshold' });
  const history = el('select', { 'aria-label': 'Study history' }, [el('option', { value: '1260', text: 'LAST 5 YEARS' }), el('option', { value: '', text: 'ALL AVAILABLE HISTORY' })]);
  const side = el('select', { 'aria-label': 'Trade direction' }, [el('option', { value: '1', text: 'LONG · BUY THE DIP' }), el('option', { value: '-1', text: 'SHORT' })]);
  const holding = el('div', { class: 'wb-pills' });
  let days = 1;
  [1, 3, 5, 10, 20].forEach((n) => holding.append(el('button', { type: 'button', text: `${n}D`, 'aria-pressed': String(n === days), onclick: () => {
    days = n; [...holding.children].forEach((button) => button.setAttribute('aria-pressed', String(button.textContent === `${n}D`))); update();
  } })));
  const metrics = el('div', { class: 'wb-metrics' });
  const distribution = el('div', { class: 'wb-result-chart', 'aria-label': 'Strategy return distribution' });
  const equity = el('div', { class: 'wb-result-chart', 'aria-label': 'Strategy equity curve' });
  const conclusion = note('');
  const method = el('details', { class: 'method-fold' }, [el('summary', { text: 'Execution rules & data limits' }), note('Signal: one-day close-to-close total return exceeds the selected threshold of prior 20-session volatility. All entries occur in the session after the signal. Open → close exits at session +N close; the other intervals exit at session +(N+1), using the selected open/close. Close-entry modes deliberately avoid entering at the signal close, which would require trading on a closing signal before it is known. Signals while a trade is open are skipped. Prices are split-adjusted; illustrative round-trip cost 10bp. Dividends, financing and borrow fees are excluded. Equity assumes full capital reinvested per trade and cash between trades. Drawdown uses trade exits only; intratrade losses may be worse. This is an in-sample historical simulation, not a forecast. Volume structure is estimated from daily bars, smoothed for display; it does not measure investors’ holdings or predict support.')]);
  let prices = null; let bars = null; let revision = 0;

  root.append(
    el('header', { class: 'wb-heading' }, [el('div', {}, [el('span', { class: 'wb-eyebrow', text: 'ANALYSIS CORE' }), el('h1', { text: 'Structure → evidence → trade' }), note('Choose a stock. See where it trades, how unusual the move is, and what happened after comparable signals.')]),
      symbolPicker]),
    status,
    el('section', { class: 'wb-structure' }, [el('div', { class: 'wb-map-panel' }, [mapTitle, el('div', { class: 'wb-profile-tools' }, [profileRanges, profileNote]), map]), readings]),
    el('section', { class: 'wb-step' }, [el('span', { class: 'wb-eyebrow', text: '01 / CONFIGURE' }), el('h2', { text: 'Test a move, before trading it' })]),
    el('div', { class: 'wb-config' }, [
      el('div', { class: 'wb-config-block' }, [el('h3', { text: 'Trigger' }), field('EVENT · CLOSE → CLOSE', direction), el('div', { class: 'wb-sigma-row' }, [thresholdLabel, threshold]), field('STUDY HISTORY', history)]),
      el('div', { class: 'wb-config-block' }, [el('h3', { text: 'Action' }), field('DIRECTION', side), field('ENTRY → EXIT', execution), timingNote, note('10bp round trip · no stop / target')]),
      el('div', { class: 'wb-config-block' }, [el('h3', { text: 'Holding period' }), holding, executionNote]),
    ]),
    el('section', { class: 'wb-step' }, [el('span', { class: 'wb-eyebrow', text: '02 / ANALYSE' }), el('h2', { text: 'Historical results' })]),
    metrics, conclusion,
    el('div', { class: 'wb-result-grid' }, [card('RETURN DISTRIBUTION', null, distribution), card('EQUITY · TRADE EXITS', null, equity)]), method,
    el('div', { class: 'wb-links' }, [el('a', { href: '#technicals', text: 'Advanced technicals →' }), el('a', { href: '#movecheck', text: 'Move Check →' })]),
  );

  function update() {
    const entryWord = execution.value.startsWith('open-') ? 'open' : 'close';
    const exitWord = execution.value.endsWith('-open') ? 'open' : 'close';
    const exitSession = days + (execution.value === 'open-close' ? 0 : 1);
    executionNote.textContent = execution.value === 'open-close' && days === 1 ? 'Next session only · open → close'
      : `Session +1 ${entryWord} → session +${exitSession} ${exitWord}`;
    timingNote.textContent = `Signal: session 0 close. Enter session +1 ${entryWord}; exit session +${exitSession} ${exitWord}.`;

    const limit = Number(threshold.value) * Number(direction.value);
    thresholdLabel.textContent = `${limit < 0 ? '≤ −' : '≥ +'}${num(Math.abs(limit), 1)}σ`;
    if (!prices) return;
    const study = eventStudy(prices.dates, prices.close, { threshold: limit, lookback: Number(history.value) || null });
    const latest = study.latest;
    const trades = simulateNextOpen(study.signals, bars, { sessions: days, side: Number(side.value), execution: execution.value });
    const returns = trades.map((t) => t.ret);
    const average = trades.length ? returns.reduce((a, b) => a + b, 0) / trades.length : null;
    let capital = 1; let peak = 1; let mdd = 0;
    const curve = trades.map((t) => { capital *= 1 + t.ret / 100; peak = Math.max(peak, capital); mdd = Math.min(mdd, capital / peak - 1); return capital; });
    metrics.replaceChildren(stat('TRADES', String(trades.length), `${trades[0]?.entry || DASH} → ${trades.at(-1)?.exit || DASH}`),
      stat('MEAN / TRADE', pctText(average), 'after assumed costs'), stat('MEDIAN / TRADE', pctText(median(returns))),
      stat('WIN RATE', trades.length ? `${num(100 * returns.filter((v) => v > 0).length / trades.length, 1)}%` : DASH),
      stat('TOTAL RETURN', trades.length ? pctText((capital - 1) * 100) : DASH, 'compounded at trade exits'),
      stat('DRAWDOWN', trades.length ? pctText(mdd * 100) : DASH, 'trade exits only'));
    conclusion.textContent = `${prices.ticker} · ${execution.value.toUpperCase()} · ${days}-session ${Number(side.value) === 1 ? 'long' : 'short'} after a ${limit}σ daily move. ${trades.length < 20 ? 'Small sample: fewer than 20 complete trades.' : 'Historical results depend on this selected rule and period.'}`;
    const view = bars && profileView();
    readings.replaceChildren(el('span', { class: 'wb-eyebrow', text: 'SESSION SNAPSHOT' }),
      stat('LATEST DAILY MOVE', pctText(latest?.ret), `${latest?.date || ''} · total-return basis`),
      stat('OWN VOLATILITY', Number.isFinite(latest?.z) ? `${num(latest.z, 2)}σ` : DASH, 'close → close · prior 20-session volatility'),
      stat('PRICE ACCEPTANCE', view?.area ? (view.close > view.area.high ? 'ABOVE VALUE' : view.close < view.area.low ? 'BELOW VALUE' : 'INSIDE VALUE') : DASH, `${profileRange} · 70% of estimated traded volume`),
      stat('MOST TRADED', view?.area ? num(view.area.poc, 2) : DASH, 'volume peak · not fair value'));
    requestAnimationFrame(() => {
      if (!trades.length) { distribution.replaceChildren(note('No complete trades with these inputs.')); equity.replaceChildren(note('No complete trades.')); return; }
      const bins = histogram(returns, 16);
      render(distribution, (o, p) => ({ ...o, xAxis: { ...o.xAxis, type: 'category', data: bins.counts.map((_, i) => `${num(bins.edges[i], 1)}%`) }, yAxis: { ...o.yAxis, minInterval: 1 }, series: [{ type: 'bar', data: bins.counts.map((v, i) => ({ value: v, itemStyle: { color: bins.edges[i + 1] <= 0 ? p.down : bins.edges[i] >= 0 ? p.up : p.accent } })) }] }));
      render(equity, (o, p) => ({ ...o, xAxis: { ...o.xAxis, data: ['Start', ...trades.map((t) => t.exit)] }, yAxis: { ...o.yAxis, scale: true }, series: [{ type: 'line', data: [1, ...curve], showSymbol: false, lineStyle: { color: p.blue, width: 3 }, areaStyle: { color: p.blue, opacity: .10 } }] }));
    });
  }
  function profileView() {
    if (!bars?.dates?.length) return null;
    const start = rangeStart(bars.dates, profileRange);
    return chipView(bars, { sessions: bars.dates.length - start, mode: 'volume' });
  }
  function drawMap() {
    const view = bars && profileView();
    if (!view?.area) { map.replaceChildren(note('Volume structure unavailable for this symbol.')); return; }
    profileNote.textContent = `${bars.dates[view.from]} → ${view.date} · ${view.last - view.from + 1} sessions available · estimated OHLCV`;
    // Weighted local smoothing of observed price-bin volume; no probability claim.
    const smooth = view.profile.map((_, i, a) => { let sum = 0; let w = 0; for (let k = -3; k <= 3; k++) if (i+k >= 0 && i+k < a.length) { const weight = 4-Math.abs(k); sum += a[i+k]*weight; w += weight; } return sum / w; });
    requestAnimationFrame(() => render(map, (o, p) => ({ ...o,
      grid: { left: 48, right: 26, top: 40, bottom: 44 },
      xAxis: { ...o.xAxis, type: 'value', min: view.g.min, max: view.g.max, name: '', axisLabel: { color: p.dim, formatter: (v) => num(v, 0), hideOverlap: true, showMinLabel: false, showMaxLabel: false } },
      yAxis: { ...o.yAxis, type: 'value', axisLabel: { show: false }, name: '' },
      tooltip: { ...o.tooltip, trigger: 'axis', confine: true,
        formatter: (params) => {
          const point = params.find((v) => Array.isArray(v.value));
          if (!point) return '';
          const volume = point.value[1];
          const compact = volume >= 1e9 ? `${num(volume / 1e9, 2)}B` : volume >= 1e6 ? `${num(volume / 1e6, 1)}M` : num(volume, 0);
          return `PRICE · $${num(point.value[0], 2)}<br/>EST. VOLUME / BIN · ${compact} shares`;
        } },
      series: [{ name: 'Smoothed volume by price', type: 'line', smooth: .35, showSymbol: false, data: view.g.centers.map((v, i) => [v, smooth[i]]), lineStyle: { color: p.accent, width: 3 }, areaStyle: { color: p.accent, opacity: .16 },
        markLine: { symbol: 'none', data: [{ xAxis: view.close, name: 'CURRENT', lineStyle: { color: p.text, type: 'dashed' } }, { xAxis: view.area.poc, name: 'VOLUME PEAK', lineStyle: { color: p.accent, type: 'dotted' } }], label: { formatter: (v) => `${v.name} ${num(v.value, 2)}`, color: p.dim } },
        markArea: { silent: true, itemStyle: { color: p.accent, opacity: .05 }, data: [[{ xAxis: view.area.low }, { xAxis: view.area.high }]] } }],
    })));
  }
  async function load() {
    const symbol = picker.value.trim().toUpperCase();
    if (!available.includes(symbol)) { status.textContent = `${symbol} has no prepared history in this build.`; return; }
    const run = ++revision; status.textContent = `Loading ${symbol}…`;
    try {
      const [next, candles] = await Promise.all([ctx.loadArtifact(`tickers/${symbol}`), ctx.loadArtifact(`bars/${symbol}`).catch(() => null)]);
      if (run !== revision) return;
      prices = next; bars = candles; ctx.setArg?.(symbol);
      showIdentity(symbol);
      mapTitle.textContent = `${symbol} · Market structure`;
      status.textContent = `AS OF ${next.as_of || next.dates.at(-1)} · USD prices · historical estimates`;
      [...root.querySelectorAll('.wb-links a')].forEach((a, i) => { a.href = `#${i ? 'movecheck' : 'technicals'}/${symbol}`; });
      update(); drawMap();
    } catch (e) { if (run === revision) status.textContent = `Unable to load ${symbol}: ${e.message}`; }
  }
  function showIdentity(symbol) {
    symbolInfo.replaceChildren(el('span', { class: 'wb-asset-type', text: identities[symbol]?.type || 'TYPE UNAVAILABLE' }),
      el('span', { text: names[symbol] || 'Name unavailable in this build' }));
  }
  picker.addEventListener('change', load);
  picker.addEventListener('keydown', (e) => { if (e.key === 'Enter') load(); });
  Promise.all(['valuation', 'heatmaps'].map(key => ctx.loadArtifact(key).catch(() => null))).then(([valuation, heatmaps]) => {
    for (const row of [...(heatmaps?.constituents || []), ...(valuation?.rows || [])]) {
      if (identities[row.ticker]) { names[row.ticker] = row.name || names[row.ticker] || ''; identities[row.ticker].type = 'STOCK'; }
    }
    for (const row of heatmaps?.etfs || []) {
      const ticker = row.ticker || row.symbol;
      if (identities[ticker]) { names[ticker] = technicals.etf_names?.[ticker] || row.name || row.label || names[ticker] || ''; identities[ticker].type = 'ETF'; }
    }
    showIdentity(prices?.ticker || picker.value.trim().toUpperCase());

  });
  for (const node of [direction, history, side, execution]) node.addEventListener('change', update);
  threshold.addEventListener('input', update);
  load();
}
