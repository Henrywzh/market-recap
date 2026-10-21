// SCENARIO WATCH: what is scheduled in the next few days, and where each hand-written
// condition stands. The scheduled half is automatic: the build reads the Kalshi strike
// ladder and past releases. The conditions are written in config/dashboard.toml and
// checked at each build. Probabilities are market prices, never opinions.

import { el, card, table, tag, num, sectionTitle, gap, DASH } from '../fmt.js';
import { render } from '../charts.js';
import { nextText } from '../scenarios-model.js';
import {
  stateLabel, triggerText, episodeText, matchText, changedText, outcomeText, historySeries, axisBounds,
  sortEvents, releaseStats, branchRows, lastReleaseText, fomcRows, probText, measureText, changeText,
  countStates, sortScenarios, figure,
} from '../watch-model.js';

const CHIP_STATES = ['triggered', 'near', 'quiet', 'killed', 'expired'];

function stat(label, value, note) {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: 'stat-value', text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

// --- the strip ---------------------------------------------------------------

function header(data) {
  const counts = countStates(data.scenarios);
  return el('div', {}, [
    el('div', { class: 'stat-strip watch-stats' }, [
      stat('AS OF', data.as_of || DASH, null),
      stat('TRIGGERED', String(counts.triggered), `of ${(data.scenarios || []).length} conditions`),
      stat('NEAR', String(counts.near), 'inside the near band of a trigger'),
    ]),
    el('div', { class: 'watch-intro dim', text: 'Scheduled events are automatic; condition scenarios are written by hand in config/dashboard.toml [[watch.scenarios]] and checked at each build. Probabilities shown are market prices (Kalshi), never opinions.' }),
  ]);
}

// --- one scheduled release ---------------------------------------------------

// A measured cell: dimmed when the figure is not detected, with its t in the tooltip.
function measuredCell(m, unit, digits) {
  if (!m || m.mean === null) return el('td', { class: 'dim', text: DASH });
  return el('td', {
    class: m.detected ? '' : 'watch-dim',
    title: `t ${m.t === null ? DASH : num(m.t, 1)}${m.detected ? '' : ' · not detected (|t| < 2)'}`,
  }, [measureText(m.mean, m.se, digits, unit)]);
}

// The three branches are the columns; the market, the past moves and the count are the rows.
function branchTable(event) {
  const rows = branchRows(event);
  const line = (head, cells) => el('tr', {}, [el('td', { text: head }), ...cells]);
  return table(['', ...rows.map((r) => r.label)], [
    line('MARKET', rows.map((r) => el('td', { text: probText(r.probability) }))),
    line('PAST 2Y', rows.map((r) => measuredCell(r.dY2, ' bp', 1))),
    line('PAST SPY', rows.map((r) => measuredCell(r.SPY, '%', 2))),
    line('N', rows.map((r) => el('td', { class: 'dim', text: r.n === null ? DASH : String(r.n) }))),
  ], { class: 'watch-table' });
}

function releaseCard(event) {
  const stats = releaseStats(event);
  const when = nextText({ date: event.date, time: event.time })?.when || DASH;
  const last = lastReleaseText(event);
  const band = Number.isFinite(event.band) ? `In line means within ±${num(event.band, 2)} of the forecast (${event.band_basis || 'the published tick'}). ` : '';
  const body = [
    el('div', { class: 'stat-strip watch-stats' }, [
      stat('CONSENSUS', stats.forecast, `previous ${stats.previous}`),
      stat('KALSHI MEDIAN', stats.median, event.market ? `10–90: ${stats.range || DASH}` : 'no Kalshi market'),
      stat('OPEN INTEREST', stats.openInterest || DASH, event.market ? 'contracts on the strike ladder' : null),
    ]),
    branchTable(event),
    last ? el('div', { class: 'watch-line', text: last }) : null,
    band ? el('div', { class: 'field-note', text: band.trim() }) : null,
  ];
  return card(String(event.label || event.key || '').toUpperCase(), el('span', { class: 'dim', text: when }), body);
}

// --- the FOMC decision -------------------------------------------------------

function fomcCard(event) {
  const rows = fomcRows(event);
  const outcomes = rows.filter((r) => r.kind === 'market');
  const branches = rows.filter((r) => r.kind !== 'market');
  const outcomeTable = table(['OUTCOME', 'CHANGE', 'MARKET'], outcomes.map((r) => el('tr', {}, [
    el('td', { text: r.label }),
    el('td', { text: changeText(r.changeBp) }),
    el('td', { text: probText(r.probability) }),
  ])), { class: 'watch-table' });
  const lines = branches.map((b) => el('div', { class: 'watch-line' }, [
    el('span', { text: `${b.label}: ` }),
    el('b', { text: `SPY mean ${figure(b.SPY, 2, '%')}` }),
    el('span', { class: 'dim', text: ` · n ${b.n === null ? DASH : b.n}` }),
  ]));
  return card('FOMC DECISION', el('span', { class: 'dim', text: nextText({ date: event.date })?.when || DASH }), [
    outcomes.length ? outcomeTable : el('div', { class: 'dim', text: 'No Kalshi market for this decision.' }),
    ...lines,
    el('div', { class: 'field-note', text: 'Probabilities are the Kalshi market\'s. Hawkish and dovish are past FOMC days sorted by what the 2-year yield did that day: a measure afterwards, not known beforehand. Each mean is SPY on those days.' }),
  ]);
}

function scheduledSection(data) {
  const days = data.settings?.event_days;
  const events = sortEvents(data.events);
  const nodes = [sectionTitle('SCHEDULED', Number.isFinite(days) ? `· NEXT ${days} DAYS` : '')];
  if (!events.length) {
    nodes.push(gap(`No release or FOMC decision in the next ${Number.isFinite(days) ? `${days} days` : 'window'}.`));
    return nodes;
  }
  nodes.push(el('div', { class: 'field-note', text: 'MARKET is the Kalshi price of each branch. PAST 2Y and PAST SPY are the average moves on past release days in that branch (2-year yield in bp, SPY in %), each ± one standard error; dim = not detected (|t| below 2), not zero.' }));
  nodes.push(el('div', { class: 'watch-grid' }, events.map((e) => (e.kind === 'fomc' ? fomcCard(e) : releaseCard(e)))));
  return nodes;
}

// --- one condition ----------------------------------------------------------

function chip(state) {
  const key = CHIP_STATES.includes(state) ? state : 'none';
  return el('span', { class: `watch-chip is-${key}`, text: stateLabel(state) });
}

// A trigger's line and its history. The chart is drawn after the page is in the
// document, so it has a size; `charts` collects what to draw.
function triggerRow(t, charts) {
  const node = el('div', { class: 'watch-trigger' }, [
    el('div', { class: `watch-trigger-text${t.met ? ' is-met' : ''}`, text: triggerText(t) }),
    t.as_of ? el('div', { class: 'watch-sub dim', text: `as of ${t.as_of}` }) : null,
  ]);
  if (historySeries(t).dates.length) {
    const host = el('div', { class: 'watch-chart' });
    node.append(host);
    charts.push({ host, trigger: t });
  }
  return node;
}

function scenarioCard(s, charts) {
  const changed = changedText(s);
  const tags = el('span', { class: 'watch-tags' }, [chip(s.state), changed ? tag(changed, 'warn') : null]);
  const meta = [`added ${s.added || DASH}`, s.since ? `since ${s.since}` : null, s.horizon ? `horizon ${s.horizon}` : null, matchText(s)].filter(Boolean).join(' · ');
  const episodes = episodeText(s.episodes);
  const outcome = outcomeText(s);
  const body = [
    el('div', { class: 'watch-thesis', text: s.thesis || '' }),
    el('div', { class: 'watch-meta dim', text: meta }),
    ...(s.triggers || []).map((t) => triggerRow(t, charts)),
    ...(s.kill || []).map((k) => el('div', { class: 'watch-line dim', text: `Kill: ${triggerText(k, 'kills')}` })),
    episodes ? el('div', { class: 'watch-line dim', text: `Episodes: ${episodes} · context only, not a forecast` }) : null,
    outcome ? el('div', { class: 'watch-line', text: outcome }) : null,
  ];
  return card(s.name || s.key || 'Condition', tags, body);
}

function conditionsSection(data, charts) {
  const nodes = [sectionTitle('CONDITIONS', '· YOUR SCENARIOS')];
  const list = sortScenarios(data.scenarios);
  if (!list.length) {
    nodes.push(gap('No conditions in config/dashboard.toml [[watch.scenarios]].'));
    return nodes;
  }
  nodes.push(el('div', { class: 'watch-grid' }, list.map((s) => scenarioCard(s, charts))));
  return nodes;
}

// --- the charts --------------------------------------------------------------

// The trigger's history, with its threshold (solid) and near band (dashed) as marked lines.
function historyChart(host, t) {
  const { dates, values } = historySeries(t);
  const bounds = axisBounds(values, [t.threshold, t.near]);
  const digits = bounds && bounds.max - bounds.min < 5 ? 2 : 0;
  render(host, (option, p) => {
    const marks = [];
    if (Number.isFinite(t.threshold)) marks.push({ yAxis: t.threshold, lineStyle: { type: 'solid', color: p.dim }, label: { formatter: 'trigger', position: 'insideEndTop', color: p.dim, fontSize: 9 } });
    if (Number.isFinite(t.near)) marks.push({ yAxis: t.near, lineStyle: { type: 'dashed', color: p.faint }, label: { formatter: 'near', position: 'insideEndBottom', color: p.faint, fontSize: 9 } });
    return {
      ...option,
      grid: { ...option.grid, top: 8, bottom: 22 },
      xAxis: { ...option.xAxis, data: dates },
      // Whole numbers for prices and % moves, two decimals for a ratio near 1.
      yAxis: { ...option.yAxis, ...(bounds || {}), axisLabel: { ...(option.yAxis?.axisLabel || {}), showMinLabel: false, showMaxLabel: false, formatter: (v) => num(v, digits) } },
      series: [{
        type: 'line', data: values, showSymbol: false, connectNulls: false,
        lineStyle: { width: 1.2, color: p.blue },
        markLine: { silent: true, symbol: 'none', data: marks },
      }],
    };
  });
}

// --- the notes and the view --------------------------------------------------

function notesFold(notes) {
  const list = (notes || []).filter(Boolean);
  if (!list.length) return null;
  return el('details', { class: 'method-fold' }, [
    el('summary', { text: 'ⓘ NOTES' }),
    ...list.map((text) => el('div', { class: 'method-copy', text })),
  ]);
}

export default function renderWatch(root, data) {
  // The loader's `{ unavailable: message }`; the panel's own `unavailable` is a list of missing inputs.
  if (!data || typeof data.unavailable === 'string' || !Array.isArray(data.scenarios) || !Array.isArray(data.events)) {
    root.append(gap('No scenario watch in this build.'));
    return;
  }
  const charts = [];
  root.append(header(data), ...scheduledSection(data), ...conditionsSection(data, charts));
  const notes = notesFold(data.notes);
  if (notes) root.append(notes);
  for (const job of charts) historyChart(job.host, job.trigger);
}
