import { el, card, num, pct, DASH, periodSwitch } from './fmt.js';
import { render } from './charts.js';
import { withSuggestions } from './ticker-suggest.js';
import { rangeStart } from './range.js';
import { chipView } from './chip-card.js';
import { eventStudy, simulateNextOpen } from './trade-events.js';
import { median, histogram, returns as dailyReturns, sigmaOf } from './movecheck-model.js';
import { matchSignals, stretches, summary, randomDrawShare, likeToday } from './trade-conditions.js';

const note = (text) => el('div', { class: 'wb-note', text });
const field = (label, node) => el('label', { class: 'wb-field' }, [el('span', { text: label }), node]);
const stat = (label, value, detail = '') => el('div', { class: 'wb-stat' }, [el('span', { text: label }), el('strong', { text: value, class: /^[−-]/.test(value) ? 'down' : /^\+/.test(value) ? 'up' : '' }), note(detail)]);
const pctText = (v) => Number.isFinite(v) ? pct(v, 2) : DASH;
// Today's reading behind each backdrop condition's state.
const readingText = (key, v) => ({ fed: `${num(v, 2)}%`, rates: `${num(v, 2)}%`, trend: `${pct(v, 1)} vs avg`, vix: num(v, 1), breadth: `z ${num(v, 2)}` })[key] ?? num(v, 2);

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
  const threshold = el('input', { type: 'range', min: '.5', max: '5', step: '.1', value: '2', 'aria-label': 'Sigma threshold' });
  // A move the reader types (today's intraday move, a level they are watching): its σ
  // against the last 20 completed sessions becomes the trigger, its sign the direction.
  const myMove = el('input', { type: 'number', step: '0.1', placeholder: 'e.g. −3.2', 'aria-label': 'Your move in percent' });
  const myMoveNote = note('Blank = use the slider. A typed move sets the trigger to its own σ.');
  const moveSigma = (move) => {
    if (!prices || !Number.isFinite(move)) return null;
    return sigmaOf([...dailyReturns(prices.dates, prices.close, 1), { ret: move }], move, 20, 1);
  };
  const applyMyMove = () => {
    const move = myMove.value === '' ? NaN : Number(myMove.value);
    const z = moveSigma(move);
    if (!Number.isFinite(z) || z === 0) {
      myMoveNote.textContent = myMove.value === '' ? 'Blank = use the slider. A typed move sets the trigger to its own σ.' : 'Needs 20 sessions of history and a non-zero move.';
      update(); return;
    }
    direction.value = z < 0 ? '-1' : '1';
    const size = Math.min(5, Math.max(0.5, Math.round(Math.abs(z) * 10) / 10));
    threshold.value = String(size);
    myMoveNote.textContent = `${pct(move, 2)} = ${num(z, 2)}σ of the last 20 sessions${Math.abs(z) < 0.5 ? ' · trigger floored at 0.5σ' : Math.abs(z) > 5 ? ' · trigger capped at 5σ' : ''}. Signals = days at least this extreme.`;
    update();
  };
  myMove.addEventListener('change', applyMyMove);
  myMove.addEventListener('keydown', (e) => { if (e.key === 'Enter') applyMyMove(); });
  const thresholdLabel = el('strong', { class: 'wb-threshold' });
  const history = el('select', { 'aria-label': 'Study history' }, [el('option', { value: '1260', text: 'LAST 5 YEARS' }), el('option', { value: '', text: 'ALL AVAILABLE HISTORY' })]);
  const side = el('select', { 'aria-label': 'Trade direction' }, [el('option', { value: '1', text: 'LONG · BUY THE DIP' }), el('option', { value: '-1', text: 'SHORT' })]);
  const holding = el('div', { class: 'wb-pills' });
  let days = 1;
  [1, 3, 5, 10, 20].forEach((n) => holding.append(el('button', { type: 'button', text: `${n}D`, 'aria-pressed': String(n === days), onclick: () => {
    days = n; [...holding.children].forEach((button) => button.setAttribute('aria-pressed', String(button.textContent === `${n}D`))); update();
  } })));
  const metrics = el('div', { class: 'wb-metrics' });
  // Backdrop at the signal close (trade_conditions artifact); empty picks = every signal.
  let conditions = null; let conditionSettings = {}; const picks = {};
  const backdropFields = el('div', { class: 'wb-backdrop-fields' });
  const backdropNote = note('Loading market backdrop…');
  const setPicks = (next) => {
    for (const key of Object.keys(picks)) delete picks[key];
    Object.assign(picks, next);
    for (const select of backdropFields.querySelectorAll('select')) select.value = picks[select.dataset.key] || '';
    update();
  };
  const backdrop = el('div', { class: 'wb-config-block wb-backdrop' }, [
    el('div', { class: 'wb-backdrop-head' }, [el('h3', { text: 'Backdrop at signal' }),
      el('div', { class: 'wb-pills' }, [
        el('button', { type: 'button', text: 'LIKE TODAY', title: "Set every condition to today's state", onclick: () => setPicks(likeToday(conditions?.conditions)) }),
        el('button', { type: 'button', text: 'ANY BACKDROP', title: 'Clear every condition', onclick: () => setPicks({}) })])]),
    backdropFields, backdropNote]);
  const compare = el('div', { class: 'wb-compare' });
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
      el('div', { class: 'wb-config-block' }, [el('h3', { text: 'Trigger' }), field('YOUR MOVE · %', myMove), myMoveNote, field('EVENT · CLOSE → CLOSE', direction), el('div', { class: 'wb-sigma-row' }, [thresholdLabel, threshold]), field('STUDY HISTORY', history)]),
      el('div', { class: 'wb-config-block' }, [el('h3', { text: 'Action' }), field('DIRECTION', side), field('ENTRY → EXIT', execution), timingNote, note('10bp round trip · no stop / target')]),
      el('div', { class: 'wb-config-block' }, [el('h3', { text: 'Holding period' }), holding, executionNote]),
    ]),
    backdrop,
    el('section', { class: 'wb-step' }, [el('span', { class: 'wb-eyebrow', text: '02 / ANALYSE' }), el('h2', { text: 'Historical results' })]),
    metrics, compare, conclusion,
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
    const typedMove = myMove.value !== '' && Number.isFinite(Number(myMove.value)) ? Number(myMove.value) : null;
    const typedZ = typedMove !== null ? moveSigma(typedMove) : null;
    const rule = { sessions: days, side: Number(side.value), execution: execution.value };
    const conditioned = Object.keys(picks).length > 0;
    const allTrades = simulateNextOpen(study.signals, bars, rule);
    // Conditions filter the signals before the simulation, as a trader applying the rule would.
    const trades = conditioned ? simulateNextOpen(matchSignals(study.signals, conditions?.conditions, picks), bars, rule) : allTrades;
    const returns = trades.map((t) => t.ret);
    const average = trades.length ? returns.reduce((a, b) => a + b, 0) / trades.length : null;
    let capital = 1; let peak = 1; let mdd = 0;
    const curve = trades.map((t) => { capital *= 1 + t.ret / 100; peak = Math.max(peak, capital); mdd = Math.min(mdd, capital / peak - 1); return capital; });
    metrics.replaceChildren(stat('TRADES', String(trades.length), `${trades[0]?.entry || DASH} → ${trades.at(-1)?.exit || DASH}`),
      stat('MEAN / TRADE', pctText(average), 'after assumed costs'), stat('MEDIAN / TRADE', pctText(median(returns))),
      stat('WIN RATE', trades.length ? `${num(100 * returns.filter((v) => v > 0).length / trades.length, 1)}%` : DASH),
      stat('TOTAL RETURN', trades.length ? pctText((capital - 1) * 100) : DASH, 'compounded at trade exits'),
      stat('DRAWDOWN', trades.length ? pctText(mdd * 100) : DASH, 'trade exits only'));
    const backdropText = conditioned ? ` · in ${Object.entries(picks).map(([, v]) => v).join(' + ')}` : '';
    conclusion.textContent = `${prices.ticker} · ${execution.value.toUpperCase()} · ${days}-session ${Number(side.value) === 1 ? 'long' : 'short'} after a ${limit}σ daily move${backdropText}. ${trades.length < 20 ? 'Small sample: fewer than 20 complete trades.' : 'Historical results depend on this selected rule and period.'}`;
    drawCompare(conditioned, trades, allTrades);
    // How many trades each set condition keeps on its own: which one empties the sample.
    for (const small of backdropFields.querySelectorAll('small[data-key]')) {
      const key = small.dataset.key;
      small.dataset.alone = picks[key] && conditions ? String(simulateNextOpen(matchSignals(study.signals, conditions.conditions, { [key]: picks[key] }), bars, rule).length) : '';
      small.textContent = small.dataset.base + (small.dataset.alone ? ` · alone: ${small.dataset.alone} of ${allTrades.length} trades` : '');
    }
    const view = bars && profileView();
    readings.replaceChildren(el('span', { class: 'wb-eyebrow', text: 'SESSION SNAPSHOT' }),
      ...(typedMove !== null ? [
        stat('YOUR MOVE', pctText(typedMove), 'typed · against the latest close history'),
        stat('OWN VOLATILITY', Number.isFinite(typedZ) ? `${num(typedZ, 2)}σ` : DASH, `last 20 completed sessions to ${latest?.date || DASH}`)] : [
        stat('LATEST DAILY MOVE', pctText(latest?.ret), `${latest?.date || ''} · total-return basis`),
        stat('OWN VOLATILITY', Number.isFinite(latest?.z) ? `${num(latest.z, 2)}σ` : DASH, 'close → close · prior 20-session volatility')]),
      stat('PRICE ACCEPTANCE', view?.area ? (view.close > view.area.high ? 'ABOVE VALUE' : view.close < view.area.low ? 'BELOW VALUE' : 'INSIDE VALUE') : DASH, `${profileRange} · 70% of estimated traded volume`),
      stat('MOST TRADED', view?.area ? num(view.area.poc, 2) : DASH, 'volume peak · not fair value'));
    requestAnimationFrame(() => {
      if (!trades.length) { distribution.replaceChildren(note('No complete trades with these inputs.')); equity.replaceChildren(note('No complete trades.')); return; }
      const bins = histogram(returns, 16);
      render(distribution, (o, p) => ({ ...o, xAxis: { ...o.xAxis, type: 'category', data: bins.counts.map((_, i) => `${num(bins.edges[i], 1)}%`) }, yAxis: { ...o.yAxis, minInterval: 1 }, series: [{ type: 'bar', data: bins.counts.map((v, i) => ({ value: v, itemStyle: { color: bins.edges[i + 1] <= 0 ? p.down : bins.edges[i] >= 0 ? p.up : p.accent } })) }] }));
      render(equity, (o, p) => ({ ...o, xAxis: { ...o.xAxis, data: ['Start', ...trades.map((t) => t.exit)] }, yAxis: { ...o.yAxis, scale: true }, series: [{ type: 'line', data: [1, ...curve], showSymbol: false, lineStyle: { color: p.blue, width: 3 }, areaStyle: { color: p.blue, opacity: .10 } }] }));
    });
  }
  function drawCompare(conditioned, trades, allTrades) {
    if (!conditioned) { compare.replaceChildren(); return; }
    const gap = conditionSettings.stretch_gap_days || 91;
    const a = summary(trades); const b = summary(allTrades);
    const sa = stretches(trades, gap); const sb = stretches(allTrades, gap);
    const share = randomDrawShare(allTrades.map((t) => t.ret), a.n, a.mean);
    const fmtPct = (v) => (Number.isFinite(v) ? `${num(v * 100, 0)}%` : DASH);
    const row = (label, x, y) => el('tr', {}, [el('th', { text: label }), el('td', { text: x }), el('td', { text: y })]);
    const warnings = [];
    if (a.n < (conditionSettings.min_trades || 30)) warnings.push(`only ${a.n} trades`);
    if (sa < (conditionSettings.min_stretches || 5)) warnings.push(`only ${sa} separate stretch${sa === 1 ? '' : 'es'}`);
    const verdict = share === null ? 'Random-draw check needs fewer conditioned trades than all trades.'
      : `${fmtPct(share)} of 2,000 random draws of ${a.n} trades from all signals averaged at least as much. ${share <= 0.05 ? 'The backdrop picked better trades than chance would.' : share >= 0.95 ? 'The backdrop picked worse trades than chance would.' : 'Not distinguishable from a random pick.'}`;
    compare.replaceChildren(el('table', { class: 'wb-compare-table' }, [
      el('thead', {}, [el('tr', {}, [el('th', { text: '' }), el('th', { text: 'IN THIS BACKDROP' }), el('th', { text: 'ALL SIGNALS' })])]),
      el('tbody', {}, [row('TRADES', String(a.n), String(b.n)), row('SEPARATE STRETCHES', String(sa), String(sb)),
        row('MEAN / TRADE', pctText(a.mean), pctText(b.mean)), row('MEDIAN / TRADE', pctText(a.median), pctText(b.median)),
        row('WIN RATE', fmtPct(a.win), fmtPct(b.win)), row('TOTAL RETURN', pctText(a.total), pctText(b.total))])]),
      el('div', {}, [
        warnings.length ? el('div', { class: 'wb-warn', text: `Small sample: ${warnings.join(', ')}. Read as anecdote, not evidence.` }) : null,
        note(verdict),
        note(`Stretch = trades with signals less than ${gap} days apart. Each condition is read at the signal close, as known then.`)].filter(Boolean)));
  }
  function drawBackdrop() {
    const list = conditions?.conditions || [];
    if (!list.length) { backdropNote.textContent = 'Market backdrop unavailable in this build: results use every signal.'; return; }
    backdropFields.replaceChildren(...list.map((c) => {
      const select = el('select', { 'aria-label': c.label, 'data-key': c.key, title: c.definition },
        [el('option', { value: '', text: 'ANY' }), ...c.options.map((o) => el('option', { value: o, text: o }))]);
      select.value = picks[c.key] || '';
      select.addEventListener('change', () => { if (select.value) picks[c.key] = select.value; else delete picks[c.key]; update(); });
      const base = `today: ${c.today || DASH}${Number.isFinite(c.reading) ? ` · ${readingText(c.key, c.reading)}` : ''}${c.from > '2001' ? ` · from ${c.from.slice(0, 4)}` : ''}`;
      return el('label', { class: 'wb-field', title: c.definition }, [el('span', { text: c.label }), select,
        el('small', { 'data-key': c.key, 'data-base': base, text: base })]);
    }));
    update();
    backdropNote.replaceChildren(el('details', { class: 'method-fold' }, [el('summary', { text: 'How each condition is defined' }),
      ...list.map((c) => note(`${c.label}: ${c.definition}`)), ...(conditions.notes || []).map((t) => note(t))]));
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
      if (myMove.value !== '') applyMyMove(); else update();
      drawMap();
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
  ctx.loadArtifact('trade_conditions').then((data) => { conditions = data; conditionSettings = data?.settings || {}; drawBackdrop(); })
    .catch(() => drawBackdrop());
  for (const node of [direction, history, side, execution]) node.addEventListener('change', update);
  threshold.addEventListener('input', () => { if (myMove.value !== '') { myMove.value = ''; myMoveNote.textContent = 'Slider set by hand; typed move cleared.'; } update(); });
  load();
}
