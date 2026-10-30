// TRADE DESK -> EVENT LAB: a trigger day on one ticker, optional conditions and
// excluded periods, and what followed from that day's close to later opens and
// closes. event-lab-model.js does the arithmetic; this file lays it out.
import { el, card, num, pct, DASH, table } from './fmt.js';
import { render } from './charts.js';
import { withSuggestions } from './ticker-suggest.js';
import { HORIZONS, EXCLUSION_PRESETS, study, byYear, rollingMedian, toCsv } from './event-lab-model.js';
import { stretches, randomDrawShare, likeToday } from './trade-conditions.js';

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
const keyLabel = (k) => `D${k.replace(/\D/g, '')} ${k.startsWith('open') ? 'OPEN' : 'CLOSE'}`;
const MIN_EVENTS = 30;
const MIN_STRETCHES = 5;

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
  const link = el('a', { href: url, download: name });
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function eventLab(root, technicals, ctx) {
  root.className = `${root.className || ''} trade-workbench event-lab`.trim();
  const available = technicals.available || [];
  const names = { ...(technicals.names || {}), ...(technicals.etf_names || {}) };
  const picker = el('input', { value: ctx.arg || 'QQQ', 'aria-label': 'Event lab ticker' });
  const suggested = withSuggestions(picker, available, names, () => load(), technicals.rank || [], {});

  // Trigger
  const kind = select('Trigger kind', [['intraday', 'INTRADAY LOW / HIGH vs prior close'], ['close', 'CLOSE vs prior close'],
    ['gap', 'OPEN GAP vs prior close'], ['sigma', 'CLOSE MOVE in σ (prior 20 sessions)']], 'intraday');
  const dir = select('Trigger direction', [['-1', 'FALL'], ['1', 'RISE']], '-1');
  const size = numberInput('Trigger size', 4);
  const sizeUnit = el('small', { text: '% (≥ this far)' });
  // Conditions
  const rsiOp = select('RSI(6) comparison', [['', 'ANY'], ['lt', '<'], ['le', '≤'], ['gt', '>'], ['ge', '≥']], '');
  const rsiValue = numberInput('RSI(6) level', 30, '1');
  const trend = select('Trend filter', [['', 'ANY'], ['above200', 'ABOVE 200D'], ['below200', 'BELOW 200D'], ['above50', 'ABOVE 50D'], ['below50', 'BELOW 50D']], '');
  const highOp = select('From 1Y high comparison', [['', 'ANY'], ['le', '≤'], ['ge', '≥']], '');
  const highValue = numberInput('From 1Y high level', -10, '1');
  const gap = numberInput('One event per N sessions', 5, '1');
  const windowSel = select('Study window', [['', 'ALL (FROM 2016)'], ['1260', 'LAST 5 YEARS'], ['756', 'LAST 3 YEARS']], '');
  const side = select('Side', [['1', 'LONG'], ['-1', 'SHORT']], '1');
  const cost = select('Cost', [['0', 'NO COST'], ['10', '10BP ROUND TRIP']], '0');
  const focus = select('Focus outcome', KEYS.map((k) => [k, keyLabel(k)]), 'close5');
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
    box.addEventListener('change', update);
    excludeBoxes.append(el('label', { class: 'el-check', title: `${p.from} → ${p.to}` }, [box, el('span', { text: `${p.label} · ${p.from.slice(0, 7)} → ${p.to.slice(0, 7)}` })]));
    return { box, preset: p };
  });

  const status = note('Loading…');
  const summaryLine = el('div', { class: 'el-summary' });
  const outcomeTable = el('div', {});
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
    status,
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
    el('div', { class: 'el-focus' }, [field('CHART & YEARS FOR', focus)]),
    el('div', { class: 'wb-result-grid' }, [card('EVERY EVENT · ROLLING MEDIAN OF LAST 10', null, scatter), card('BY YEAR OF THE TRIGGER', null, yearTable)]),
    card('EVENTS · NEWEST FIRST', csvButton, eventTable),
    el('details', { class: 'method-fold' }, [el('summary', { text: 'How this is computed' }),
      note('Prices are the nightly build\'s daily bars, split-adjusted but not dividend-adjusted, from October 2016. Outcome = price at day x open or close ÷ t0 close − 1 (short: the negative), less the chosen round-trip cost. Day 1 is the next session.'),
      note('Intraday trigger: the day\'s low (high for a rise) against the prior close, so a day that touched −4% and closed higher counts; the summary says how many. It is known before the close, so a t0-close entry is realistic. RSI(6), the averages and the 1Y high use the t0 close itself: in practice what was visible minutes before it.'),
      note('One event per N sessions keeps the first trigger and skips any within N sessions after it, so a crash with a big move every day is not counted many times. Baseline = every session in the same window and exclusions, with no trigger or conditions.'),
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
      return el('label', { class: 'wb-field', title: c.definition }, [el('span', { text: c.label }), s, el('small', { text: `today: ${c.today || DASH}` })]);
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
      p.box.disabled = before; if (before) p.box.checked = false;
      p.box.parentElement.classList.toggle('el-unavailable', before);
      p.box.parentElement.title = before ? `Before this ticker's daily bars (from ${first})` : `${p.preset.from} → ${p.preset.to}`;
    }
    drawSummary(opts); drawOutcomes(); drawFocus();
  }
  function drawSummary(opts) {
    const r = result; const k = focus.value;
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
    const roll = rollingMedian(events, k, 10);
    if (!events.length) { scatter.replaceChildren(note('No events.')); return; }
    render(scatter, (o, p) => ({ ...o,
      xAxis: { ...o.xAxis, type: 'time' }, yAxis: { ...o.yAxis, scale: true, axisLabel: { ...(o.yAxis?.axisLabel || {}), formatter: (v) => `${v}%` } },
      tooltip: { ...o.tooltip, trigger: 'item', formatter: (q) => `${q.value[0]} · ${q.seriesName}: ${pctText(q.value[1])}` },
      series: [
        { name: keyLabel(k), type: 'scatter', symbolSize: 7, data: events.map((e) => [e.date, e.out[k]]).filter((d) => Number.isFinite(d[1])),
          itemStyle: { color: (q) => (q.value[1] >= 0 ? p.up : p.down), opacity: 0.8 } },
        { name: 'Rolling median (10)', type: 'line', showSymbol: false, data: events.map((e, i) => [e.date, roll[i]]).filter((d) => d[1] !== null),
          lineStyle: { color: p.accent, width: 2 } },
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
  ctx.loadArtifact('trade_conditions').then((d) => { conditions = d; drawBackdrop(); update(); }).catch(() => drawBackdrop());
  load();
}
