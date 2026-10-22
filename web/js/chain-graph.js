// AI CHAIN as a graph: the board's columns, with the links drawn. Built on
// ECharts' graph series with fixed positions (one column per layer), so the
// picture reads upstream to downstream like the board beside it.
//
// Three hundred links drawn at once are a hairball. With nothing picked, only
// the backbone shows: links where one side's reports have moved the other
// with t >= BACKBONE_T. A picked company shows all of its own links, coloured
// by role, as wide as the read-through is firm, dashed where it is not
// (|t| < 2); arrows follow the goods.

import { render } from './charts.js';
import { linksOf, surpriseText, ROLE_LABEL } from './chain-card.js';
import { num, pct } from './fmt.js';

const BACKBONE_T = 3;
const ROW_PX = 30;
// The graph's view keeps its aspect ratio, so positions are in pixels: a
// column a node's width plus a gap, a row a node's height plus a gap.
const COL_PX = 118;
const NODE_W = 108;
const NODE_H = 22;

function firmness(edge) {
  const ts = Object.values(edge.stats || {}).filter(Boolean).map((s) => Math.abs(s.t || 0));
  return ts.length ? Math.max(...ts) : 0;
}

function seasonColor(node, p) {
  const r = node.season?.reported;
  if (!r || r.surprise === null || r.surprise === undefined) return p.faint;
  return r.surprise > 0 ? p.up : r.surprise < 0 ? p.down : p.faint;
}

function statLine(label, s) {
  return s ? `${label}: β ${num(s.beta, 2)} · t ${num(s.t, 1)} · ${s.n} reports since ${s.since}` : `${label}: fewer than 8 shared reports`;
}

function escape(text) {
  return String(text ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

export function graphHeight(data) {
  const counts = {};
  (data.nodes || []).forEach((n) => { counts[n.layer] = (counts[n.layer] || 0) + 1; });
  return (Math.max(...Object.values(counts), 1) + 1.4) * ROW_PX + 40;
}

// Where every company sits: one column per layer, each column centred on
// the tallest; and a label node over each column. Shared with the replay.
export function layout(data, p) {
  const layers = data.layers || [];
  const byLayer = new Map(layers.map((l) => [l.key, []]));
  (data.nodes || []).forEach((n) => byLayer.get(n.layer)?.push(n));
  const tallest = Math.max(...[...byLayer.values()].map((v) => v.length), 1);
  const labels = [];
  const places = [];
  layers.forEach((layer, x) => {
    labels.push({ id: `layer:${layer.key}`, name: layer.label, x: x * COL_PX, y: -1.4 * ROW_PX, symbol: 'rect', symbolSize: [NODE_W, 1],
      // A node that only carries its column's label: ECharts draws no label on
      // symbol 'none', and an item opacity of 0 hides the label with it.
      itemStyle: { color: 'transparent', borderWidth: 0 },
      label: { show: true, color: p.dim, fontSize: 9, fontWeight: 600, width: NODE_W, overflow: 'break' }, isLabel: true });
    const column = byLayer.get(layer.key) || [];
    const offset = (tallest - column.length) / 2;
    column.forEach((n, i) => places.push({ node: n, x: x * COL_PX, y: (offset + i) * ROW_PX }));
  });
  return { labels, places };
}

export const NODE_SIZE = [NODE_W, NODE_H];
export const GRAPH_SERIES = { type: 'graph', layout: 'none', roam: false, draggable: false,
  left: NODE_W / 2 + 4, right: NODE_W / 2 + 4, top: 16, bottom: NODE_H / 2 + 4, emphasis: { disabled: true } };

export function drawGraph(host, data, state) {
  const names = new Map((data.nodes || []).map((n) => [n.key, n]));
  const roles = state.selected ? new Map(linksOf(data, state.selected).map((l) => [l.key, l.role])) : new Map();

  return render(host, (option, p) => {
    const roleColor = { supplier: p.blue, customer: p.up, competitor: p.accent, partner: p.dim };
    const { labels, places } = layout(data, p);
    const nodes = [...labels, ...places.map(({ node: n, x, y }) => {
      const picked = n.key === state.selected;
      const role = roles.get(n.key);
      const faded = state.selected && !picked && !role;
      return {
        id: n.key, name: n.name, x, y, node: n,
        symbol: 'roundRect', symbolSize: [NODE_W, NODE_H],
        itemStyle: {
          color: p.panel, borderWidth: picked ? 2 : 1,
          borderColor: picked ? p.accent : role ? roleColor[role] : seasonColor(n, p),
          opacity: faded ? 0.3 : 1,
        },
        label: { show: true, color: faded ? p.faint : p.text, fontSize: 10, width: NODE_W - 10, overflow: 'truncate',
          formatter: () => n.short || n.name },
      };
    })];

    const edges = (data.edges || []).filter((e) => (state.selected
      ? e.from === state.selected || e.to === state.selected
      : firmness(e) >= BACKBONE_T));
    const links = edges.map((e) => {
      const t = firmness(e);
      const other = state.selected ? (e.from === state.selected ? e.to : e.from) : null;
      const color = other ? roleColor[roles.get(other)] || p.dim : (e.type === 'competes' ? p.accent : p.dim);
      return {
        source: e.from, target: e.to, edge: e,
        symbol: e.type === 'supplies' ? ['none', 'arrow'] : ['none', 'none'], symbolSize: 6,
        lineStyle: {
          color, width: 0.8 + Math.min(t, 8) * 0.45, type: t >= 2 ? 'solid' : 'dashed',
          opacity: state.selected ? 0.85 : 0.35, curveness: 0.12,
        },
      };
    });

    return {
      animation: false,
      backgroundColor: 'transparent',
      textStyle: option.textStyle,
      tooltip: {
        ...option.tooltip, trigger: 'item', axisPointer: undefined, confine: true,
        formatter: (q) => {
          if (q.dataType === 'edge') {
            const e = q.data.edge;
            const a = names.get(e.from)?.name || e.from;
            const b = names.get(e.to)?.name || e.to;
            const ev = e.evidence || {};
            return `<b>${escape(a)}</b> ${e.type} <b>${escape(b)}</b><br>${escape(e.reason)}<br>`
              + `${escape(statLine(`${a}'s reports → ${b}`, e.stats?.[`${e.from}>${e.to}`]))}<br>`
              + `${escape(statLine(`${b}'s reports → ${a}`, e.stats?.[`${e.to}>${e.from}`]))}`
              + (ev.filer ? `<br><span style="opacity:.7">${escape(ev.filer)} ${escape(ev.form)} ${escape(ev.filed)}</span>` : '');
          }
          const n = q.data.node;
          if (!n) return '';
          const r = n.season?.reported;
          const role = roles.get(n.key);
          return `<b>${escape(n.name)}</b> ${escape(n.key)} · ${escape(n.market)}${n.us ? ` · US ${escape(n.us)}` : ''}${role ? ` · ${ROLE_LABEL[role]} of ${escape(state.selected)}` : ''}<br>`
            + (r ? `${escape(data.season?.label || '')}: ${r.date} · EPS ${surpriseText(r.surprise)} · ${pct(r.move, 1)}` : `next ${n.next ? n.next.date : '—'}`);
        },
      },
      series: [{ ...GRAPH_SERIES, data: nodes, links, edgeSymbol: ['none', 'none'] }],
    };
  });
}

export function attachClicks(chart, state) {
  if (!chart) return;
  chart.on('click', (q) => {
    if (q.dataType === 'node' && q.data.node) state.pick(q.data.node.key);
  });
}

