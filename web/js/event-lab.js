// TRADE DESK -> EVENT LAB: a trigger day on one ticker, optional conditions and
// excluded periods, and what followed from that day's close to later opens and
// closes, then the same events traded with an execution rule (TRADE IT).
// event-lab-model.js does the arithmetic; this file lays it out.
import { el, card, num, pct, DASH, table } from './fmt.js';
import { render } from './charts.js';
import { withSuggestions } from './ticker-suggest.js';
import { HORIZONS, EXCLUSION_PRESETS, study, byYear, rollingMedian, rollingShare, toCsv, path } from './event-lab-model.js';
import { stretches, randomDrawShare, likeToday, summary as tradeSummary } from './trade-conditions.js';
import { simulateNextOpen } from './trade-events.js';
import { histogram } from './movecheck-model.js';

const note = (text) => el('div', { class: 'wb-note', text });
const field = (label, node, extra) => el('label', { class: 'wb-field' }, [el('span', { text: label }), node, extra].filter(Boolean));
const select = (label, options, value) => {
  const node = el('select', { 'aria-label': label }, options.map(([v, t]) => el('option', { value: v, text: t })));
  node.value = value; return node;
};
const numberInput = (label, value, step = '0.5') => el('input', { type: 'number', step, value: String(value), 'aria-label': label });
const pctText = (v) => (Number.isFinite(v) ? pct(v, 2) : DASH);
const shareText = (v) => (Number.isFinite(v) ? `${num(v * 100, 0)}%` : DASH);
const signClass = (v) => (Number.isFinite(v) ? (v > 0 ? 'up' : v < 0 ? 'down' : '') : '');
const KEYS = HORIZONS.flatMap((x) => [`open${x}`, `close${x}`]);
const keyLabel = (k) => (k === 'trade' ? 'TRADE IT' : `D${k.replace(/\D/g, '')} ${k.startsWith('open') ? 'OPEN' : 'CLOSE'}`);
const MIN_EVENTS = 30;
const MIN_STRETCHES = 5;

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
  const link = el('a', { href: url, download: name });
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function eventLab(root, technicals, ctx, preset = null) {
  root.className = `${root.className || ''} trade-workbench event-lab`.trim();
  const available = technicals.available || [];
  const names = { ...(technicals.names || {}), ...(technicals.etf_names || {}) };
  const picker = el('input', { value: preset?.symbol || ctx.arg || 'QQQ', 'aria-label': 'Event lab ticker' });
  const suggested = withSuggestions(picker, available, names, () => load(), technicals.rank || [], {});

  // Trigger
  const kind = select('Trigger kind', [['intraday', 'INTRADAY LOW / HIGH vs prior close'], ['close', 'CLOSE vs prior close'],
    ['gap', 'OPEN GAP vs prior close'], ['sigma', 'CLOSE MOVE in σ (prior 20 sessions)']], 'intraday');
  const dir = select('Trigger direction', [['-1', 'FALL'], ['1', 'RISE']], '-1');
  const size = numberInput('Trigger size', 4);
  const sizeUnit = el('small', { text: '% (≥ this far)' });
  // Conditions
  const rsiOp = select('RSI(6) comparison', [['', 'ANY'], ['lt', '<'], ['le', '≤'], ['gt', '>'], ['ge', '≥']], 'lt');
  const rsiValue = numberInput('RSI(6) level', 30, '1');
  const trend = select('Trend filter', [['', 'ANY'], ['above200', 'ABOVE 200D'], ['below200', 'BELOW 200D'], ['above50', 'ABOVE 50D'], ['below50', 'BELOW 50D']], '');
  const highOp = select('From 1Y high comparison', [['', 'ANY'], ['le', '≤'], ['ge', '≥']], '');
  const highValue = numberInput('From 1Y high level', -10, '1');
  const gap = numberInput('One event per N sessions', 5, '1');
  const windowSel = select('Study window', [['', 'ALL HISTORY'], ['1260', 'LAST 5 YEARS'], ['756', 'LAST 3 YEARS']], '');
  const side = select('Side', [['1', 'LONG'], ['-1', 'SHORT']], '1');
  const cost = select('Cost', [['0', 'NO COST'], ['10', '10BP ROUND TRIP']], '0');
  // TRADE IT (the default) = each event's trade with the execution rule below.
  const focus = select('Focus outcome', [['trade', 'TRADE IT · rule below'], ...KEYS.map((k) => [k, keyLabel(k)])], 'trade');
  // TRADE IT: the events above, entered after t0 with an execution rule.
  const execution = select('Entry and exit', [['open-close', 'OPEN → CLOSE'], ['close-close', 'CLOSE → CLOSE'],
    ['open-open', 'OPEN → OPEN'], ['close-open', 'CLOSE → OPEN · overnight']], 'close-open');
  const hold = select('Holding sessions', [1, 3, 5, 10, 20].map((n) => [String(n), `${n} SESSION${n > 1 ? 'S' : ''}`]), '1');
  const executionNote = note('');
  const tradeMetrics = el('div', { class: 'wb-metrics' });
  const tradeCompare = el('div', { class: 'wb-compare' });
  const distribution = el('div', { class: 'wb-result-chart', 'aria-label': 'Trade return distribution' });
  const equity = el('div', { class: 'wb-result-chart', 'aria-label': 'Trade equity curve' });
  const fromStructure = preset ? el('div', { class: 'el-preset', text: `From STRUCTURE: ${preset.source}. The trigger is filled in${preset.picks ? ' with the backdrop' : ''}; change anything below.` }) : null;
  if (preset?.trigger) { kind.value = preset.trigger.kind; dir.value = String(preset.trigger.dir); size.value = String(preset.trigger.size); }
  // Backdrop
  let conditions = null; const picks = {};
  const backdropFields = el('div', { class: 'wb-backdrop-fields' });
  // Exclusions
  const excludeBoxes = el('div', { class: 'el-excludes' });
  const custom = []; const customList = el('div', { class: 'el-chips' });
  const customFrom = el('input', { type: 'date', 'aria-label': 'Exclude from' });
  const customTo = el('input', { type: 'date', 'aria-label': 'Exclude to' });
  const presetBoxes = EXCLUSION_PRESETS.map((p) => {
    const box = el('input', { type: 'checkbox', 'data-key': p.key });
    box.checked = Boolean(p.on);
    box.addEventListener('change', update);
    excludeBoxes.append(el('label', { class: 'el-check', title: `${p.from} → ${p.to}` }, [box, el('span', { text: `${p.label} · ${p.from.slice(0, 7)} → ${p.to.slice(0, 7)}` })]));
    return { box, preset: p };
  });

  const status = note('Loading…');
  const summaryLine = el('div', { class: 'el-summary' });
  const outcomeTable = el('div', {});
  const pathChart = el('div', { class: 'wb-result-chart el-path', 'aria-label': 'Path from the t0 close to day 20' });
  const scatter = el('div', { class: 'wb-result-chart', 'aria-label': 'Event outcomes over time' });
  const yearTable = el('div', {});
  const eventTable = el('div', { class: 'el-events' });
  const csvButton = el('button', { type: 'button', class: 'action', text: 'DOWNLOAD EVENTS (CSV)' });
  let bars = null; let result = null; let symbol = ''; let revision = 0;

  root.append(
    el('header', { class: 'wb-heading' }, [el('div', {}, [el('span', { class: 'wb-eyebrow', text: 'EVENT LAB' }),
      el('h1', { text: 'Days like this → what followed' }),
      note('Pick a trigger day, add conditions, leave out periods. Every outcome runs from the trigger day\'s close to a later open or close.')]),
    el('div', { class: 'wb-symbol-picker' }, [field('SYMBOL', suggested)])]),
    status, fromStructure,
    el('div', { class: 'wb-config' }, [
      el('div', { class: 'wb-config-block' }, [el('h3', { text: 'Trigger · day t0' }), field('KIND', kind), field('DIRECTION', dir), field('SIZE', size, sizeUnit)]),
      el('div', { class: 'wb-config-block' }, [el('h3', { text: 'Conditions at t0 close · AND' }),
        el('div', { class: 'el-pair' }, [field('RSI(6)', rsiOp), field('LEVEL', rsiValue)]), field('TREND', trend),
        el('div', { class: 'el-pair' }, [field('FROM 1Y HIGH %', highOp), field('LEVEL', highValue)])]),
      el('div', { class: 'wb-config-block' }, [el('h3', { text: 'Counting' }), field('ONE EVENT PER N SESSIONS', gap, el('small', { text: '0 = every trigger day' })),
        field('WINDOW', windowSel), el('div', { class: 'el-pair' }, [field('SIDE', side), field('COST', cost)])]),
    ]),
    el('div', { class: 'wb-config-block wb-backdrop' }, [
      el('div', { class: 'wb-backdrop-head' }, [el('h3', { text: 'Backdrop at t0 · AND' }), el('div', { class: 'wb-pills' }, [
        el('button', { type: 'button', text: 'LIKE TODAY', onclick: () => setPicks(likeToday(conditions?.conditions)) }),
        el('button', { type: 'button', text: 'ANY BACKDROP', onclick: () => setPicks({}) })])]),
      backdropFields]),
    el('div', { class: 'wb-config-block el-exclude-block' }, [el('h3', { text: 'Leave out periods (by trigger date)' }), excludeBoxes,
      el('div', { class: 'el-custom' }, [field('FROM', customFrom), field('TO', customTo),
        el('button', { type: 'button', text: 'ADD', onclick: () => {
          if (!customFrom.value || !customTo.value || customFrom.value > customTo.value) return;
          custom.push({ from: customFrom.value, to: customTo.value }); drawCustom(); update();
        } })]), customList]),
    el('section', { class: 'wb-step' }, [el('span', { class: 'wb-eyebrow', text: 'RESULTS' }), el('h2', { text: 'From the t0 close' })]),
    summaryLine,
    card('OUTCOMES · t0 CLOSE → DAY x OPEN / CLOSE', null, outcomeTable),
    card('PATH · t0 CLOSE → D20 · MEDIAN, MEAN, 25–75%, MIN / MAX · WIN RATE UNDER EACH STEP', null, pathChart),
    el('div', { class: 'el-focus' }, [field('CHART & YEARS FOR', focus)]),
    el('div', { class: 'wb-result-grid' }, [card('EVERY EVENT · ROLLING MEDIAN & WIN RATE OF LAST 10', null, scatter), card('BY YEAR OF THE TRIGGER', null, yearTable)]),
    card('EVENTS · NEWEST FIRST', csvButton, eventTable),
    el('section', { class: 'wb-step' }, [el('span', { class: 'wb-eyebrow', text: 'TRADE IT' }), el('h2', { text: 'The same events, traded after t0' })]),
    el('div', { class: 'wb-config el-trade-config' }, [el('div', { class: 'wb-config-block' }, [el('h3', { text: 'Execution' }),
      el('div', { class: 'el-pair' }, [field('ENTRY → EXIT', execution), field('HOLD', hold)]), executionNote,
      note('Side and cost from COUNTING above · trades do not overlap · no stop / target')])]),
    tradeMetrics, tradeCompare,
    el('div', { class: 'wb-result-grid' }, [card('TRADE RETURN DISTRIBUTION', null, distribution), card('EQUITY · TRADE EXITS', null, equity)]),
    el('details', { class: 'method-fold' }, [el('summary', { text: 'How this is computed' }),
      note(`Prices are the nightly build's daily bars, split-adjusted but not dividend-adjusted: ${(technicals.long_bars?.symbols || []).join(', ') || 'the broad-market funds'} from ${technicals.long_bars?.first || '2000'}, every other ticker from October 2016. Outcome = price at day x open or close ÷ t0 close − 1 (short: the negative), less the chosen round-trip cost. Day 1 is the next session.`),
      note('Intraday trigger: the day\'s low (high for a rise) against the prior close, so a day that touched −4% and closed higher counts; the summary says how many. It is known before the close, so a t0-close entry is realistic. RSI(6), the averages and the 1Y high use the t0 close itself: in practice what was visible minutes before it.'),
      note('One event per N sessions keeps the first trigger and skips any within N sessions after it, so a crash with a big move every day is not counted many times. Baseline = every session in the same window and exclusions, with no trigger or conditions.'),
      note(`Path: each point is a separate statistic over the events with that outcome (the median at D10 is not the median event's D10), so the line is not one event's path. Win rate under each step = share of events above the t0 close there. The x axis is in steps, not days: D5 → D10 → D20 are wider gaps.`),
      note('TRADE IT enters in the session after t0 (never at the t0 close a signal needs), so its returns differ from the outcome table. Open → close exits at session +N close; the other rules exit at session +(N+1) at the chosen open or close. A signal while a trade is open is skipped. Equity reinvests fully per trade and holds cash between trades; drawdown uses trade exits only, so losses within a trade may be worse. Dividends, financing and borrow are left out.'),
      note('Random-draw check: how often the mean of as many randomly chosen sessions (from the baseline) was at least the events\' mean, for the focus outcome. Small = the trigger picked better days than chance; near 50% = no different. A description of the past, not a forecast.')]),
  );

  const setPicks = (next) => {
    for (const k of Object.keys(picks)) delete picks[k];
    Object.assign(picks, next);
    for (const s of backdropFields.querySelectorAll('select')) s.value = picks[s.dataset.key] || '';
    update();
  };
  function drawBackdrop() {
    backdropFields.replaceChildren(...(conditions?.conditions || []).map((c) => {
      const s = el('select', { 'aria-label': c.label, 'data-key': c.key, title: c.definition },
        [el('option', { value: '', text: 'ANY' }), ...c.options.map((o) => el('option', { value: o, text: o }))]);
      s.addEventListener('change', () => { if (s.value) picks[c.key] = s.value; else delete picks[c.key]; update(); });
      const base = `today: ${c.today || DASH}`;
      return el('label', { class: 'wb-field', title: c.definition }, [el('span', { text: c.label }), s, el('small', { 'data-key': c.key, 'data-base': base, text: base })]);
    }));
    if (!conditions) backdropFields.replaceChildren(note('Market backdrop unavailable in this build.'));
  }
  function drawCustom() {
    customList.replaceChildren(...custom.map((r, i) => el('button', { type: 'button', class: 'el-chip', title: 'Remove',
      text: `${r.from} → ${r.to} ×`, onclick: () => { custom.splice(i, 1); drawCustom(); update(); } })));
  }
  function settings() {
    const from = windowSel.value && bars ? bars.dates[Math.max(0, bars.dates.length - Number(windowSel.value))] : null;
    const exclude = [...presetBoxes.filter((p) => p.box.checked).map((p) => p.preset), ...custom];
    const filters = { conditions: conditions?.conditions || [], backdrop: { ...picks } };
    if (rsiOp.value && rsiValue.value !== '') filters.rsi = { op: rsiOp.value, value: Number(rsiValue.value) };
    if (trend.value) filters.trend = trend.value;
    if (highOp.value && highValue.value !== '') filters.fromHigh = { op: highOp.value, value: Number(highValue.value) };
    return { trigger: { kind: kind.value, dir: Number(dir.value), size: Math.abs(Number(size.value) || 0) }, filters, exclude,
      gap: Math.max(0, Math.floor(Number(gap.value) || 0)), from, costBps: Number(cost.value), side: Number(side.value) };
  }
  function update() {
    sizeUnit.textContent = kind.value === 'sigma' ? 'σ (≥ this far)' : '% (≥ this far)';
    if (!bars) return;
    const opts = settings();
    result = study(bars, opts);
    const first = bars.dates[0];
    for (const p of presetBoxes) {
      const before = p.preset.to < first;
      // Kept as chosen when greyed: a period before the bars has no events either way.
      p.box.disabled = before;
      p.box.parentElement.classList.toggle('el-unavailable', before);
      p.box.parentElement.title = before ? `Before this ticker's daily bars (from ${first})` : `${p.preset.from} → ${p.preset.to}`;
    }
    attachTrades(opts);
    drawSummary(opts); drawOutcomes(); drawPath(); drawFocus(); drawTrade(opts);
  }
  // Each event's TRADE IT return as e.out.trade (null when it overlapped an open trade).
  let trades = [];
  function attachTrades(opts) {
    trades = tradesOf(result, opts);
    const bySignal = new Map(trades.map((t) => [t.signal, t.ret]));
    for (const e of result.events) e.out.trade = bySignal.has(e.date) ? bySignal.get(e.date) : null;
  }
  // Trades from a study's events with the TRADE IT rule.
  const tradesOf = (r, opts) => simulateNextOpen(r.events.map((e) => e.date), bars,
    { sessions: Number(hold.value), side: opts.side, costBps: opts.costBps, execution: execution.value });
  function drawTrade(opts) {
    const n = Number(hold.value); const entryWord = execution.value.startsWith('open-') ? 'open' : 'close';
    const exitWord = execution.value.endsWith('-open') ? 'open' : 'close';
    executionNote.textContent = `Enter session +1 ${entryWord}; exit session +${n + (execution.value === 'open-close' ? 0 : 1)} ${exitWord}.`;
    if (!result) return;
    const returns = trades.map((t) => t.ret);
    const s = tradeSummary(trades);
    let capital = 1; let peak = 1; let mdd = 0;
    const curve = trades.map((t) => { capital *= 1 + t.ret / 100; peak = Math.max(peak, capital); mdd = Math.min(mdd, capital / peak - 1); return capital; });
    const tstat = (label, value, detail = '') => el('div', { class: 'wb-stat' }, [el('span', { text: label }), el('strong', { text: value, class: /^[−-]/.test(value) ? 'down' : /^\+/.test(value) ? 'up' : '' }), note(detail)]);
    tradeMetrics.replaceChildren(tstat('TRADES', String(s.n), `${trades[0]?.entry || DASH} → ${trades.at(-1)?.exit || DASH}`),
      tstat('MEAN / TRADE', pctText(s.mean), opts.costBps ? `after ${opts.costBps}bp round trip` : 'no cost'), tstat('MEDIAN / TRADE', pctText(s.median)),
      tstat('WIN RATE', shareText(s.win)), tstat('TOTAL RETURN', s.n ? pctText(s.total) : DASH, 'compounded at trade exits'),
      tstat('DRAWDOWN', s.n ? pctText(mdd * 100) : DASH, 'trade exits only'));
    drawBackdropCompare(opts, trades);
    if (!trades.length) { distribution.replaceChildren(note('No complete trades.')); equity.replaceChildren(note('No complete trades.')); return; }
    const bins = histogram(returns, 16);
    render(distribution, (o, p) => ({ ...o, xAxis: { ...o.xAxis, type: 'category', data: bins.counts.map((_, i) => `${num(bins.edges[i], 1)}%`) }, yAxis: { ...o.yAxis, minInterval: 1 },
      series: [{ type: 'bar', data: bins.counts.map((v, i) => ({ value: v, itemStyle: { color: bins.edges[i + 1] <= 0 ? p.down : bins.edges[i] >= 0 ? p.up : p.accent } })) }] }));
    render(equity, (o, p) => ({ ...o, xAxis: { ...o.xAxis, data: ['Start', ...trades.map((t) => t.exit)] }, yAxis: { ...o.yAxis, scale: true },
      series: [{ type: 'line', data: [1, ...curve], showSymbol: false, lineStyle: { color: p.blue, width: 3 }, areaStyle: { color: p.blue, opacity: .10 } }] }));
  }
  // With a backdrop set: the same rule without it, and how many events each condition keeps alone.
  function drawBackdropCompare(opts, trades) {
    const keys = Object.keys(opts.filters.backdrop);
    const withoutBackdrop = (backdrop) => study(bars, { ...opts, filters: { ...opts.filters, backdrop } });
    for (const small of backdropFields.querySelectorAll('small[data-key]')) {
      const key = small.dataset.key;
      const alone = keys.includes(key) ? withoutBackdrop({ [key]: picks[key] }).events.length : null;
      small.textContent = small.dataset.base + (alone !== null ? ` · alone: ${alone} events` : '');
    }
    if (!keys.length) { tradeCompare.replaceChildren(); return; }
    const all = tradesOf(withoutBackdrop({}), opts);
    const a = tradeSummary(trades); const b = tradeSummary(all);
    const sa = stretches(trades, 91); const sb = stretches(all, 91);
    const share = randomDrawShare(all.map((t) => t.ret), a.n, a.mean);
    const row = (label, x, y) => el('tr', {}, [el('th', { text: label }), el('td', { text: x }), el('td', { text: y })]);
    const warnings = [];
    if (a.n < MIN_EVENTS) warnings.push(`only ${a.n} trades`);
    if (sa < MIN_STRETCHES) warnings.push(`only ${sa} separate stretch${sa === 1 ? '' : 'es'}`);
    tradeCompare.replaceChildren(el('table', { class: 'wb-compare-table' }, [
      el('thead', {}, [el('tr', {}, [el('th', { text: '' }), el('th', { text: 'IN THIS BACKDROP' }), el('th', { text: 'ANY BACKDROP' })])]),
      el('tbody', {}, [row('TRADES', String(a.n), String(b.n)), row('SEPARATE STRETCHES', String(sa), String(sb)),
        row('MEAN / TRADE', pctText(a.mean), pctText(b.mean)), row('MEDIAN / TRADE', pctText(a.median), pctText(b.median)),
        row('WIN RATE', shareText(a.win), shareText(b.win)), row('TOTAL RETURN', pctText(a.total), pctText(b.total))])]),
      el('div', {}, [
        warnings.length ? el('div', { class: 'wb-warn', text: `Small sample: ${warnings.join(', ')}. Read as anecdote, not evidence.` }) : null,
        note(share === null ? 'Random-draw check needs fewer trades in the backdrop than in any backdrop.'
          : `${shareText(share)} of 2,000 random draws of ${a.n} trades from any backdrop averaged at least as much. ${share <= 0.05 ? 'The backdrop picked better trades than chance would.' : share >= 0.95 ? 'The backdrop picked worse trades than chance would.' : 'Not distinguishable from a random pick.'}`),
        note('Stretch = trades with signals less than 91 days apart. Each condition is read at the t0 close, as known then.')].filter(Boolean)));
  }
  function drawSummary(opts) {
    // The random-draw check compares with every session, so it reads a t0-close outcome.
    const r = result; const k = focus.value === 'trade' ? 'close5' : focus.value;
    const n = r.events.length; const nStretch = stretches(r.events.map((e) => ({ signal: e.date })), 91);
    const mean = r.summary[k].mean;
    const share = randomDrawShare(r.baseValues[k], r.summary[k].n, mean);
    const trig = `${opts.trigger.dir < 0 ? 'fall' : 'rise'} ≥ ${num(opts.trigger.size, 1)}${opts.trigger.kind === 'sigma' ? 'σ' : '%'}`;
    const lines = [
      `${symbol} · ${n} events (${r.raw} trigger days before one-per-${opts.gap}) · ${nStretch} separate stretches · ${r.first || DASH} → ${r.last || DASH} · ${r.eligible} sessions in the window.`,
      `Trigger: ${{ intraday: 'intraday', close: 'close', gap: 'open gap', sigma: 'close move' }[opts.trigger.kind]} ${trig}${r.touchedOnly !== null ? ` · ${r.touchedOnly} of the ${n} touched it intraday but closed above the line` : ''}.`,
    ];
    const warn = [];
    if (n < MIN_EVENTS) warn.push(`only ${n} events`);
    if (nStretch < MIN_STRETCHES) warn.push(`only ${nStretch} separate stretch${nStretch === 1 ? '' : 'es'}`);
    summaryLine.replaceChildren(...lines.map(note),
      ...(warn.length ? [el('div', { class: 'wb-warn', text: `Small sample: ${warn.join(', ')}. Read as anecdote, not evidence.` })] : []),
      note(share === null ? `Random-draw check (${keyLabel(k)}): needs events.` : `Random-draw check (${keyLabel(k)}): ${shareText(share)} of 2,000 random sets of ${r.summary[k].n} sessions averaged at least ${pctText(mean)}. ${share <= 0.05 ? 'The trigger picked better days than chance.' : share >= 0.95 ? 'The trigger picked worse days than chance.' : 'Not distinguishable from random days.'}`));
  }
  function drawOutcomes() {
    const cell = (v, f = pctText) => el('td', { text: f(v), class: signClass(f === pctText ? v : null) });
    const rows = KEYS.map((k) => {
      const s = result.summary[k]; const b = result.baseline[k];
      return el('tr', { class: k === focus.value ? 'el-focus-row' : '' }, [el('td', { text: keyLabel(k) }), el('td', { text: String(s.n) }), cell(s.hit, shareText),
        cell(s.mean), cell(s.median), cell(s.min), cell(s.p25), cell(s.p75), cell(s.max), cell(b.mean), cell(b.hit, shareText)]);
    });
    outcomeTable.replaceChildren(table(['FROM t0 CLOSE TO', 'N', 'P(>0)', 'MEAN', 'MEDIAN', 'MIN', '25%', '75%', 'MAX', 'ALL DAYS MEAN', 'ALL DAYS P(>0)'], rows, { class: 'el-table' }));
  }
  // What followed, in time order: the events' range, middle half, median and mean at
  // each step, with the share above the t0 close under each label.
  function drawPath() {
    if (!result.events.length) { pathChart.replaceChildren(note('No events.')); return; }
    const { labels, points } = path(result);
    const col = (f) => points.map((q) => (Number.isFinite(q[f]) ? q[f] : null));
    const low = col('p25'); const high = col('p75');
    const axisLabels = labels.map((l, i) => (Number.isFinite(points[i].hit) ? `${l}\n${num(points[i].hit * 100, 0)}%` : `${l}\nwin rate`));
    render(pathChart, (o, p) => ({ ...o,
      legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, data: ['Median', 'Mean', '25–75%', 'Min / max'] },
      grid: { ...o.grid, bottom: 62 },
      xAxis: { ...o.xAxis, type: 'category', boundaryGap: false, data: axisLabels,
        axisLabel: { ...(o.xAxis?.axisLabel || {}), interval: 0, lineHeight: 14 } },
      yAxis: { ...o.yAxis, scale: true, axisLabel: { ...(o.yAxis?.axisLabel || {}), formatter: (v) => `${v}%` } },
      tooltip: { ...o.tooltip, trigger: 'axis', formatter: (q) => {
        const i = q[0]?.dataIndex ?? 0; const pt = points[i];
        if (!i) return 't0 CLOSE · 0%';
        // Returns coloured by sign; win rates by side of 50%.
        const tint = (text, v, mid = 0) => (Number.isFinite(v) && v !== mid ? `<span style="color:${v > mid ? p.up : p.down}">${text}</span>` : text);
        const r = (v) => tint(pctText(v), v); const w = (v) => tint(shareText(v), v, 0.5);
        return `${labels[i]} · ${pt.n} events<br/>max ${r(pt.max)}<br/>75% ${r(pt.p75)}<br/>median ${r(pt.median)} · mean ${r(pt.mean)}<br/>25% ${r(pt.p25)}<br/>min ${r(pt.min)}<br/>win rate ${w(pt.hit)} · all sessions ${w(pt.baseHit)}`;
      } },
      series: [
        { name: 'band-low', type: 'line', stack: 'band', stackStrategy: 'all', data: low, showSymbol: false, silent: true, lineStyle: { opacity: 0 }, tooltip: { show: false } },
        { name: '25–75%', type: 'line', stack: 'band', stackStrategy: 'all', data: high.map((v, i) => (v === null || low[i] === null ? null : v - low[i])),
          showSymbol: false, silent: true, lineStyle: { opacity: 0 }, areaStyle: { color: p.accent, opacity: 0.18 }, itemStyle: { color: p.accent } },
        { name: 'Min / max', type: 'line', data: col('max'), showSymbol: false, lineStyle: { color: p.dim, width: 1, type: 'dashed' }, itemStyle: { color: p.dim } },
        { name: 'Min / max', type: 'line', data: col('min'), showSymbol: false, lineStyle: { color: p.dim, width: 1, type: 'dashed' }, itemStyle: { color: p.dim } },
        { name: 'Mean', type: 'line', data: col('mean'), showSymbol: false, lineStyle: { color: p.blue, type: 'dashed', width: 1.5 }, itemStyle: { color: p.blue } },
        { name: 'Median', type: 'line', data: col('median'), symbolSize: 5, lineStyle: { color: p.accent, width: 2.5 }, itemStyle: { color: p.accent },
          markLine: { silent: true, symbol: 'none', data: [{ yAxis: 0 }], lineStyle: { color: p.text, type: 'solid', width: 1, opacity: 0.4 }, label: { show: false } } },
      ] }));
  }
  function drawFocus() {
    const k = focus.value; const events = result.events;
    const years = byYear(events, k);
    yearTable.replaceChildren(years.length ? table(['YEAR', 'N', 'MEAN', 'MEDIAN', 'P(>0)'], years.map((y) => el('tr', {}, [
      el('td', { text: y.year }), el('td', { text: String(y.n) }), el('td', { text: pctText(y.mean), class: signClass(y.mean) }),
      el('td', { text: pctText(y.median), class: signClass(y.median) }), el('td', { text: shareText(y.hit) })]))) : note('No events.'));
    const newest = [...events].reverse();
    const show = (v) => el('td', { text: pctText(v), class: signClass(v) });
    eventTable.replaceChildren(newest.length ? table(['DATE', 'LOW', 'CLOSE', 'RSI(6)', 'VS 200D', 'D1 OPEN', 'D1 CLOSE', 'D5 CLOSE', 'D10 CLOSE', 'D20 CLOSE', keyLabel(k)],
      newest.map((e) => el('tr', {}, [el('td', { text: e.date }), show(e.lowRet), show(e.closeRet), el('td', { text: Number.isFinite(e.rsi6) ? num(e.rsi6, 1) : DASH }),
        show(e.vs200), show(e.out.open1), show(e.out.close1), show(e.out.close5), show(e.out.close10), show(e.out.close20), show(e.out[k])]))) : note('No events with these settings.'));
    csvButton.onclick = () => download(`${symbol}-event-lab.csv`, toCsv(events, symbol));
    const roll = rollingMedian(events, k, 10); const wins = rollingShare(events, k, 10);
    if (!events.length) { scatter.replaceChildren(note('No events.')); return; }
    // Both axes centred: 0% return on the left lines up with 50% win rate on the right.
    const span = Math.max(1, ...events.map((e) => Math.abs(e.out[k])).filter(Number.isFinite), ...roll.filter(Number.isFinite).map(Math.abs));
    const step = span <= 2 ? 0.5 : span <= 5 ? 1 : span <= 10 ? 2 : span <= 25 ? 5 : 10;
    const edge = Math.ceil(span / step) * step;
    render(scatter, (o, p) => ({ ...o,
      legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, data: [keyLabel(k), 'Rolling median (10)', 'Rolling win rate (10)'] },
      grid: { ...o.grid, right: 48, bottom: 40 },
      xAxis: { ...o.xAxis, type: 'time' },
      yAxis: [{ ...o.yAxis, min: -edge, max: edge, interval: edge / 2, axisLabel: { ...(o.yAxis?.axisLabel || {}), formatter: (v) => `${v}%` } },
        { ...o.yAxis, min: 0, max: 100, interval: 25, splitLine: { show: false }, axisLabel: { ...(o.yAxis?.axisLabel || {}), formatter: (v) => `${v}%` } }],
      tooltip: { ...o.tooltip, trigger: 'item', formatter: (q) => `${q.value[0]} · ${q.seriesName}: ${q.seriesName.startsWith('Rolling win') ? `${num(q.value[1], 0)}%` : pctText(q.value[1])}` },
      series: [
        { name: 'Rolling win rate (10)', type: 'line', yAxisIndex: 1, showSymbol: false, data: events.map((e, i) => [e.date, wins[i] === null ? null : wins[i] * 100]).filter((d) => d[1] !== null),
          lineStyle: { color: p.blue, width: 1.5, type: 'dashed' }, itemStyle: { color: p.blue } },
        { name: keyLabel(k), type: 'scatter', symbolSize: 7, data: events.map((e) => [e.date, e.out[k]]).filter((d) => Number.isFinite(d[1])),
          itemStyle: { color: (q) => (q.value[1] >= 0 ? p.up : p.down), opacity: 0.8 } },
        { name: 'Rolling median (10)', type: 'line', showSymbol: false, data: events.map((e, i) => [e.date, roll[i]]).filter((d) => d[1] !== null),
          lineStyle: { color: p.accent, width: 2 }, itemStyle: { color: p.accent } },
        { name: 'zero', type: 'line', showSymbol: false, silent: true, data: [[events[0].date, 0], [events.at(-1).date, 0]], lineStyle: { color: p.dim, type: 'dashed', width: 1 } },
      ] }));
  }
  async function load() {
    symbol = picker.value.trim().toUpperCase();
    if (!available.includes(symbol)) { status.textContent = `${symbol} has no prepared history in this build.`; return; }
    const run = ++revision; status.textContent = `Loading ${symbol}…`;
    try {
      const next = await ctx.loadArtifact(`bars/${symbol}`);
      if (run !== revision) return;
      bars = next; ctx.setArg?.(symbol);
      status.textContent = `${symbol} · daily bars ${bars.dates[0]} → ${bars.dates.at(-1)} · ${bars.dates.length} sessions`;
      update();
    } catch (e) { if (run === revision) { bars = null; status.textContent = `No daily bars for ${symbol}: ${e.message}`; } }
  }
  picker.addEventListener('change', load);
  picker.addEventListener('keydown', (e) => { if (e.key === 'Enter') load(); });
  for (const node of [kind, dir, rsiOp, trend, highOp, windowSel, side, cost]) node.addEventListener('change', update);
  for (const node of [size, rsiValue, highValue, gap]) node.addEventListener('change', update);
  focus.addEventListener('change', () => { if (result) { drawSummary(settings()); drawOutcomes(); drawFocus(); } });
  for (const node of [execution, hold]) node.addEventListener('change', () => {
    if (!result) return;
    const opts = settings(); attachTrades(opts); drawTrade(opts); drawFocus();
  });
  ctx.loadArtifact('trade_conditions').then((d) => {
    conditions = d; drawBackdrop();
    if (preset?.picks) setPicks(preset.picks); else update();
  }).catch(() => drawBackdrop());
  load();
}
