// The OpenRouter charts: estimated revenue, then tokens, each on its own
// full-width row under one control bar they share (scale, range, mode). The
// arithmetic lives in openrouter-model.js; this file only draws it.

import { el, num, periodSwitch, DASH } from './fmt.js';
import { render, SERIES_COLORS } from './charts.js';
import { RANGES, openrouterSeries, logValues, legendSelection } from './openrouter-model.js';

const MODE_LABEL = { DAILY: 'DAILY · 7D AVG', MONTHLY: 'MONTHLY ARR' };
const MODE_OF = Object.fromEntries(Object.entries(MODE_LABEL).map(([mode, label]) => [label, mode]));
const CHART_HEIGHT = 'height:340px';

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);

// Decimal places for a figure: never more than three, fewer for larger ones.
function places(v) {
  const a = Math.abs(v);
  return a === 0 || a >= 100 ? 0 : a >= 10 ? 1 : a >= 1 ? 2 : 3;
}

// Revenue: $k a day, or $M a year when monthly; the next unit up above 1,000.
function revenueFmt(monthly) {
  return (v) => {
    const big = Math.abs(v) >= 1000;
    if (monthly) return big ? `$${num(v / 1000, places(v / 1000))}B` : `$${num(v, places(v))}M`;
    return big ? `$${num(v / 1000, places(v / 1000))}M` : `$${num(v, places(v))}k`;
  };
}

// Tokens: billions a day, or trillions above 1,000.
function tokensFmt(v) {
  return Math.abs(v) >= 1000 ? `${num(v / 1000, places(v / 1000))}T` : `${num(v, places(v))}B`;
}

// The axis tooltip reads each series' raw value (not the log-safe copy) and
// says so for a partial month. Missing figures read as a dash.
function tooltipOf(data, fmt) {
  return (params) => {
    const list = [].concat(params);
    if (!list.length) return '';
    const i = list[0].dataIndex;
    const rows = list.map((q) => {
      const s = data.series.find((x) => x.name === q.seriesName);
      const v = s ? s.values[i] : null;
      const partial = s && s.partial[i] ? ' (partial)' : '';
      return `${q.marker}${esc(q.seriesName)} ${isNum(v) ? fmt(v) : DASH}${partial}`;
    });
    return [esc(data.labels[i] ?? ''), ...rows].join('<br/>');
  };
}

// One chart. Gaps are gaps: on a log axis a non-positive value is null, and a
// missing one stays null. Partial months are hollow markers (monthly only).
// Returns the ECharts instance, or null when ECharts did not load.
function drawSeries(node, data, { log, monthly, fmt, selected, onLegend }) {
  const chart = render(node, (option, p) => ({
    ...option,
    grid: { left: 58, right: 16, top: 46, bottom: 26 },
    legend: { top: 0, textStyle: { color: p.dim, fontSize: 9 }, itemWidth: 10, itemHeight: 2, selected },
    tooltip: { ...option.tooltip, trigger: 'axis', formatter: tooltipOf(data, fmt) },
    xAxis: { ...option.xAxis, data: data.labels },
    yAxis: { ...option.yAxis, type: log ? 'log' : 'value', scale: true, axisLabel: { color: p.dim, fontSize: 9, formatter: fmt } },
    series: data.series.map((s) => {
      const color = SERIES_COLORS[s.index % SERIES_COLORS.length];
      const values = log ? logValues(s.values) : s.values;
      return {
        name: s.name,
        type: 'line',
        data: values.map((v, i) => ({ value: v, symbol: s.partial[i] ? 'emptyCircle' : 'circle' })),
        showSymbol: monthly,
        symbolSize: 6,
        connectNulls: false,
        lineStyle: { width: 1.4, color },
        itemStyle: { color },
      };
    }),
  }));
  if (chart) chart.on('legendselectchanged', (e) => onLegend(e.selected));
  return chart;
}

function panel() {
  const title = el('span', { class: 'card-title' });
  const hint = el('span', { class: 'dim' });
  const node = el('div', { class: 'chart', style: CHART_HEIGHT });
  return { title, hint, node, root: el('div', { class: 'or-chart' }, [el('div', { class: 'chart-head' }, [title, hint]), node]) };
}

function control(label, node) {
  return el('span', { class: 'tag-row' }, [el('span', { class: 'dim', text: label }), node]);
}

export function openrouterCharts(or) {
  const providers = Array.isArray(or.providers) ? or.providers : [];
  // One state for both charts. The legend's selection is kept here because a
  // redraw starts from the state, not from what ECharts last showed.
  const state = { scale: 'LOG', range: '6M', mode: 'DAILY', selected: legendSelection(providers, or.default_slugs) };
  let pending = false;

  const scaleNode = periodSwitch(['LOG', 'RAW'], state.scale, (v) => { state.scale = v; draw(); });
  const rangeNode = periodSwitch(RANGES, state.range, (v) => { state.range = v; draw(); });
  const modeNode = periodSwitch(Object.values(MODE_LABEL), MODE_LABEL[state.mode], (label) => { state.mode = MODE_OF[label]; draw(); });
  for (const node of [scaleNode, rangeNode, modeNode]) node.classList.add('range-switch');
  const rangeControl = control('RANGE', rangeNode);
  const controls = el('div', { class: 'chart-head' }, [
    el('span', { class: 'tag-row' }, [control('SCALE', scaleNode), rangeControl, control('MODE', modeNode)]),
  ]);

  const revenue = panel();
  const tokens = panel();

  // A legend click in one chart is the same click for the other: store it and
  // redraw both on the next tick, after ECharts has finished the click.
  const onLegend = (selected) => {
    state.selected = { ...selected };
    if (pending) return;
    pending = true;
    setTimeout(() => { pending = false; draw(); }, 0);
  };

  const draw = () => {
    const monthly = state.mode === 'MONTHLY';
    const log = state.scale === 'LOG';
    for (const b of rangeNode.querySelectorAll('button')) b.disabled = monthly;
    rangeControl.style.opacity = monthly ? '0.35' : '';
    rangeControl.title = monthly ? 'The monthly view shows every month' : 'Applies to the daily 7-day average';

    const note = `${log ? 'log scale' : 'linear'}${monthly ? ' · hollow marker = partial month' : ''}`;
    revenue.title.textContent = monthly ? 'MONTHLY ARR · $ PER YEAR, ANNUALISED' : 'ESTIMATED REVENUE · 7D AVG, $ PER DAY';
    tokens.title.textContent = monthly ? 'AVERAGE TOKENS · BY MONTH, PER DAY' : 'TOKENS · 7D AVG, PER DAY';
    revenue.hint.textContent = note;
    tokens.hint.textContent = note;

    const revenueData = openrouterSeries(or, { metric: 'revenue', mode: state.mode, range: state.range });
    const tokenData = openrouterSeries(or, { metric: 'tokens', mode: state.mode, range: state.range });
    drawSeries(revenue.node, revenueData, { log, monthly, fmt: revenueFmt(monthly), selected: state.selected, onLegend });
    drawSeries(tokens.node, tokenData, { log, monthly, fmt: tokensFmt, selected: state.selected, onLegend });
  };

  requestAnimationFrame(draw);
  return el('div', { class: 'or-charts' }, [controls, revenue.root, tokens.root]);
}
