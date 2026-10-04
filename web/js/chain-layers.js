// AI CHAIN, layer to layer: the study's first question asked of the chain's
// parts rather than its links. A cell is every pair whose reporter sits in
// the row's layer and whose follower sits in the column's -- linked or not --
// and how the follower moved on the session it first traded the report.

import { render } from './charts.js';
import { el, card, num, periodSwitch } from './fmt.js';

const PERIODS = { ALL: 'all', 'SINCE 2023': 'recent' };
const METRICS = {
  'RANK ρ': { key: 'rank_corr', digits: 2, span: 0.4, unit: '', note: 'rank correlation of the reporter\'s own move and the follower\'s' },
  'MEAN pp': { key: 'mean', digits: 2, span: 1, unit: ' pp', note: 'the follower\'s move, signed by the reporter\'s: positive is the same way' },
};

function escape(text) {
  return String(text ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

export function layerCells(matrix, layers, metric) {
  const out = [];
  layers.forEach((lead, y) => layers.forEach((follow, x) => {
    const cell = matrix?.[lead.key]?.[follow.key];
    const value = cell ? cell[metric.key] : null;
    out.push({ value: [x, y, value === null || value === undefined ? '-' : value], cell, lead, follow });
  }));
  return out;
}

function draw(node, data, period, metricLabel) {
  const layers = data.layers || [];
  const metric = METRICS[metricLabel];
  const matrix = data.study?.layers?.[PERIODS[period]] || {};
  const names = new Map((data.nodes || []).map((n) => [n.key, n.name]));
  const cells = layerCells(matrix, layers, metric);
  render(node, (option, p) => ({
    animation: false,
    backgroundColor: 'transparent',
    textStyle: option.textStyle,
    tooltip: {
      ...option.tooltip, trigger: 'item', axisPointer: undefined, confine: true,
      formatter: (q) => {
        const d = cells[q.dataIndex];
        const c = d?.cell;
        if (!c) return `${escape(d?.lead.label)} → ${escape(d?.follow.label)}: no pairs`;
        const top = (c.top || []).map((t) => `${escape(names.get(t.lead) || t.lead)} → ${escape(names.get(t.follow) || t.follow)}: β ${num(t.beta, 2)} · t ${num(t.t, 1)} · ${t.n}`);
        return `<b>${escape(d.lead.label)}</b> reports → <b>${escape(d.follow.label)}</b><br>`
          + `rank ρ ${num(c.rank_corr, 2)} · mean ${num(c.mean, 2)} pp signed · t ${num(c.t, 1)}<br>`
          + `same way ${c.same_way_pct ?? '—'}% · ${c.reports} reports, ${c.pairs} pairs`
          + (top.length ? `<br><span style="opacity:.75">firmest pairs</span><br>${top.join('<br>')}` : '');
      },
    },
    grid: { left: 150, right: 70, top: 10, bottom: 70 },
    xAxis: {
      type: 'category', data: layers.map((l) => l.label), position: 'bottom',
      name: 'MOVES →', nameLocation: 'end', nameTextStyle: { color: p.dim, fontSize: 9 },
      axisLabel: { color: p.dim, fontSize: 9, interval: 0, rotate: 30 }, axisLine: { lineStyle: { color: p.border } }, axisTick: { show: false },
      splitArea: { show: false },
    },
    yAxis: {
      type: 'category', data: layers.map((l) => l.label), inverse: true,
      name: 'REPORTS ↓', nameLocation: 'start', nameTextStyle: { color: p.dim, fontSize: 9 },
      axisLabel: { color: p.dim, fontSize: 9 }, axisLine: { lineStyle: { color: p.border } }, axisTick: { show: false },
    },
    visualMap: {
      type: 'continuous', min: -metric.span, max: metric.span, calculable: false, orient: 'vertical', right: 0, top: 'middle',
      itemHeight: 140, itemWidth: 10, text: [`+${metric.span}`, `−${metric.span}`], textStyle: { color: p.dim, fontSize: 9 },
      inRange: { color: [p.down, p.panel, p.up] },
    },
    series: [{
      type: 'heatmap', data: cells.map((d) => d.value),
      label: { show: true, color: p.text, fontSize: 9, formatter: (q) => (q.value[2] === '-' ? '' : num(q.value[2], metric.digits)) },
      itemStyle: { borderColor: p.panel, borderWidth: 1 },
      emphasis: { itemStyle: { borderColor: p.accent, borderWidth: 1 } },
    }],
  }));
}

export function layersCard(data) {
  if (!data.study?.layers) return null;
  let period = 'ALL';
  let metric = 'RANK ρ';
  const canvas = el('div', { class: 'chain-layers' });
  const note = el('div', { class: 'field-note' });
  const redraw = () => {
    note.textContent = `Rows report, columns move. Each cell: every pair with the reporter in the row's layer and the other company in the column's, linked or not — ${METRICS[metric].note}, on the first session the follower's market traded the report. The diagonal is a layer moving on its own reports. Hover a cell for its counts and firmest pairs.`;
    requestAnimationFrame(() => draw(canvas, data, period, metric));
  };
  const controls = el('span', { class: 'tag-row' }, [
    periodSwitch(Object.keys(METRICS), metric, (m) => { metric = m; redraw(); }),
    periodSwitch(Object.keys(PERIODS), period, (p) => { period = p; redraw(); }),
  ]);
  redraw();
  return card('LAYER TO LAYER · SAME SESSION', controls, [note, el('div', { class: 'chain-graph-scroll' }, [canvas])]);
}
