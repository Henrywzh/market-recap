// AI CHAIN, season replay: the season session by session on the chain's
// graph. Each company is filled by its move beyond its home index that day
// (or since the season began); a company whose report traded that day is
// ringed by its surprise, with its links drawn; the log beneath says who
// reported and how its links moved.

import { render } from './charts.js';
import { el, card, pct, periodSwitch, dirClass, DASH } from './fmt.js';
import { layout, NODE_SIZE, GRAPH_SERIES, graphHeight } from './chain-graph.js';
import { linksOf, surpriseText, ROLE_LABEL } from './chain-card.js';

const FRAME_MS = 700;
// The move at which a fill is full strength: a day's, a season's.
const CAP = { DAY: 5, SEASON: 25 };
const LOG_LINKS = 5;

function rgb(color) {
  const hex = String(color).trim().match(/^#([0-9a-f]{6})$/i);
  if (hex) return [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16));
  const parts = String(color).match(/\d+(\.\d+)?/g);
  return parts ? parts.slice(0, 3).map(Number) : [128, 128, 128];
}

export function fillFor(value, cap, up, down) {
  if (value === null || value === undefined) return 'transparent';
  const [r, g, b] = rgb(value >= 0 ? up : down);
  const alpha = Math.min(Math.abs(value) / cap, 1) * 0.85;
  return `rgba(${r},${g},${b},${alpha.toFixed(2)})`;
}

// Each company's running sum of daily moves through each session.
export function cumulative(moves) {
  const out = {};
  for (const [key, values] of Object.entries(moves || {})) {
    let sum = 0;
    let seen = false;
    out[key] = values.map((v) => {
      if (v !== null && v !== undefined) { sum += v; seen = true; }
      return seen ? Math.round(sum * 100) / 100 : null;
    });
  }
  return out;
}

function short(text, n) {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}

function signed(v) {
  return v === null || v === undefined ? '' : `${v > 0 ? '+' : ''}${v.toFixed(1)}`;
}

export function replayCard(data) {
  const seasons = data.replay || [];
  if (!seasons.length || !seasons[0].dates?.length) return null;
  const names = new Map((data.nodes || []).map((n) => [n.key, n]));
  const state = { season: 0, mode: 'DAY', i: 0, timer: null, chart: null };
  const canvas = el('div', { class: 'chain-graph', style: `height:${graphHeight(data)}px` });
  const day = el('div', { class: 'stat-value replay-day' });
  const log = el('div', { class: 'replay-log' });
  const slider = el('input', { type: 'range', min: '0', value: '0', class: 'replay-slider', 'aria-label': 'session' });
  const play = el('button', { type: 'button', class: 'action', text: 'PLAY' });
  let cum = cumulative(seasons[0].moves);

  const season = () => seasons[state.season];
  const stop = () => {
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
    play.textContent = 'PLAY';
  };

  const frame = () => {
    const s = season();
    const date = s.dates[state.i];
    const p = state.palette;
    const values = state.mode === 'DAY' ? s.moves : cum;
    const reporters = new Map(s.reports.filter((r) => r.day === date).map((r) => [r.key, r]));
    const { labels, places } = layout(data, p);
    const nodes = [...labels, ...places.map(({ node: n, x, y }) => {
      const v = values[n.key]?.[state.i] ?? null;
      const rep = reporters.get(n.key);
      return {
        id: n.key, name: n.name, x, y, node: n, value: v,
        symbol: 'roundRect', symbolSize: NODE_SIZE,
        itemStyle: {
          color: fillFor(v, CAP[state.mode], p.up, p.down),
          borderWidth: rep ? 3 : 1,
          borderColor: rep ? ((rep.surprise ?? 0) >= 0 ? p.up : p.down) : p.border,
        },
        label: { show: true, color: p.text, fontSize: 10, formatter: () => `${short(n.name, 10)} ${signed(v)}` },
      };
    })];
    const links = [];
    reporters.forEach((_, key) => {
      (data.edges || []).filter((e) => e.from === key || e.to === key).forEach((e) => links.push({
        source: e.from, target: e.to,
        symbol: e.type === 'supplies' ? ['none', 'arrow'] : ['none', 'none'], symbolSize: 6,
        lineStyle: { color: e.type === 'competes' ? p.accent : p.blue, width: 1.2, opacity: 0.6, curveness: 0.12 },
      }));
    });
    state.chart?.setOption({ series: [{ ...GRAPH_SERIES, data: nodes, links, edgeSymbol: ['none', 'none'] }] });
    day.textContent = `${date} · session ${state.i + 1} of ${s.dates.length}`;
    slider.value = String(state.i);
    log.replaceChildren(...logLines(s, date, values));
  };

  const logLines = (s, date, values) => {
    const lines = [];
    const reps = s.reports.filter((r) => r.day === date);
    reps.forEach((r) => {
      const node = names.get(r.key);
      const links = linksOf(data, r.key)
        .map((l) => ({ ...l, move: s.moves[l.key]?.[state.i] ?? null }))
        .filter((l) => l.move !== null)
        .sort((a, b) => Math.abs(b.move) - Math.abs(a.move))
        .slice(0, LOG_LINKS);
      lines.push(el('div', { class: 'replay-line' }, [
        el('b', { text: `${node?.name || r.key} reported` }), ' · EPS ',
        el('span', { class: dirClass(r.surprise), text: surpriseText(r.surprise) }), ' · its move ',
        el('span', { class: dirClass(r.move), text: pct(r.move, 1) }),
        links.length ? el('span', { class: 'dim', text: ' · links: ' }) : null,
        ...links.flatMap((l, i) => [i ? ', ' : '', `${names.get(l.key)?.name || l.key} (${ROLE_LABEL[l.role].toLowerCase()}) `,
          el('span', { class: dirClass(l.move), text: pct(l.move, 1) })]),
      ]));
    });
    if (!reps.length) {
      const movers = Object.entries(s.moves).map(([k, v]) => [k, v[state.i]]).filter(([, v]) => v !== null && v !== undefined)
        .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 4);
      lines.push(el('div', { class: 'replay-line dim' }, [
        'No chain report traded this session. Largest moves: ',
        ...movers.flatMap(([k, v], i) => [i ? ', ' : '', `${names.get(k)?.name || k} `, el('span', { class: dirClass(v), text: pct(v, 1) })]),
      ]));
    }
    if (state.mode === 'SEASON') {
      lines.push(el('div', { class: 'replay-line dim', text: `Fill: each company's summed move beyond its index from ${s.dates[0]} through this session.` }));
    }
    return lines;
  };

  const start = () => {
    stop();
    const s = season();
    slider.max = String(s.dates.length - 1);
    state.i = Math.min(state.i, s.dates.length - 1);
    requestAnimationFrame(() => {
      if (!state.chart || state.chart.isDisposed()) {
        state.chart = render(canvas, (option, p) => {
          state.palette = p;
          return {
            animation: false, backgroundColor: 'transparent', textStyle: option.textStyle,
            tooltip: { ...option.tooltip, trigger: 'item', axisPointer: undefined, confine: true,
              formatter: (q) => {
                const n = q.data?.node;
                if (!n) return '';
                const sNow = season();
                const d = sNow.moves[n.key]?.[state.i];
                const c = cum[n.key]?.[state.i];
                const rep = sNow.reports.find((r) => r.key === n.key && r.day === sNow.dates[state.i]);
                return `<b>${n.name}</b> ${n.key} · ${n.market}<br>session ${d === null || d === undefined ? DASH : pct(d, 1)} · season ${c === null || c === undefined ? DASH : pct(c, 1)}`
                  + (rep ? `<br>reported: EPS ${surpriseText(rep.surprise)} · ${pct(rep.move, 1)}` : '');
              } },
            series: [{ ...GRAPH_SERIES, data: [], links: [] }],
          };
        });
      }
      frame();
    });
  };

  play.addEventListener('click', () => {
    if (state.timer) { stop(); return; }
    if (state.i >= season().dates.length - 1) state.i = 0;
    play.textContent = 'PAUSE';
    state.timer = setInterval(() => {
      // The page moved on: stop playing to a chart nobody sees.
      if (!document.body.contains(canvas)) { stop(); return; }
      if (state.i >= season().dates.length - 1) { stop(); return; }
      state.i += 1;
      frame();
    }, FRAME_MS);
  });
  slider.addEventListener('input', () => { stop(); state.i = Number(slider.value); frame(); });
  const step = (d) => () => { stop(); state.i = Math.max(0, Math.min(season().dates.length - 1, state.i + d)); frame(); };
  // Jump to the next / previous session a chain report traded.
  const jump = (d) => () => {
    stop();
    const s = season();
    const days = new Set(s.reports.map((r) => r.day));
    for (let i = state.i + d; i >= 0 && i < s.dates.length; i += d) {
      if (days.has(s.dates[i])) { state.i = i; break; }
    }
    frame();
  };

  const seasonSwitch = periodSwitch(seasons.map((s) => s.label), seasons[0].label, (label) => {
    state.season = seasons.findIndex((s) => s.label === label);
    state.i = 0;
    cum = cumulative(season().moves);
    start();
  });
  const modeSwitch = periodSwitch(['DAY', 'SEASON'], 'DAY', (mode) => { state.mode = mode; frame(); });
  const controls = el('div', { class: 'replay-controls' }, [
    el('button', { type: 'button', class: 'action', text: '◀ REPORT', onclick: jump(-1), title: 'previous session a chain report traded' }),
    el('button', { type: 'button', class: 'action', text: '◀', onclick: step(-1), title: 'previous session' }),
    play,
    el('button', { type: 'button', class: 'action', text: '▶', onclick: step(1), title: 'next session' }),
    el('button', { type: 'button', class: 'action', text: 'REPORT ▶', onclick: jump(1), title: 'next session a chain report traded' }),
    slider, day,
  ]);
  start();
  return card('SEASON REPLAY', el('span', { class: 'tag-row' }, [modeSwitch, seasonSwitch]), [
    el('div', { class: 'field-note', text: 'Session by session: each company filled by its move beyond its home index that session (DAY) or since the season began (SEASON); a company whose report traded that session ringed green (beat) or red (missed), with its links drawn. Sessions are every market\'s, by date: a Seoul session and a New York one of the same date are one step.' }),
    controls,
    el('div', { class: 'chain-graph-scroll' }, [canvas]),
    log,
  ]);
}
