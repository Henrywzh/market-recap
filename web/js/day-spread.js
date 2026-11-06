// THE DAY'S SPREAD on INDICES: every member's move in one session as a
// histogram, the ten heaviest names marked where they landed, and the line
// between the typical member (median) and the index's weighted move. It reads
// the build's close, and during the session the heat map's live quotes.

import { el, card, num, periodSwitch, liveBadge, DASH } from './fmt.js';
import { render } from './charts.js';
import { createFeed } from './live-feed.js';
import { isStale } from './live-model.js';
import { members, bins, summary, labelRows, verdict } from './day-spread-model.js';

const GRID = { left: 44, right: 16, bottom: 30 };
const ROW_STEP = 0.13;   // each label row sits this share of the tallest bar higher

const signed = (v, digits = 1) => (Number.isFinite(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}%` : DASH);

export function spreadOption(binned, stats, mode, p, widthPx) {
  const value = (b) => (mode === 'WEIGHT' ? b.weight : b.count);
  const tallest = Math.max(1e-9, ...binned.bins.map(value));
  const clipped = (v) => Math.max(-binned.clip + binned.width / 2, Math.min(binned.clip - binned.width / 2, v));
  // Rows by where a name is drawn: two past the same edge share its bin's x.
  const heavy = labelRows(stats.heavy.map((m) => ({ ...m, at: clipped(m.ret) })).map((m) => ({ ...m, ret: m.at, move: m.ret })),
    (2 * binned.clip * 42) / Math.max(1, widthPx))   // a label's width in points of move
    .map((m) => ({ ...m, ret: m.move }));
  const rows = heavy.reduce((a, m) => Math.max(a, m.row + 1), 0);
  const barWidth = Math.max(2, (widthPx * binned.width) / (2 * binned.clip) - 2);
  const lines = [
    { xAxis: 0, lineStyle: { color: p.faint, type: 'solid' }, label: { show: false } },
    Number.isFinite(stats.median) ? { xAxis: clipped(stats.median), lineStyle: { color: p.dim, type: 'dashed' },
      label: { formatter: `median ${signed(stats.median)}`, color: p.dim, position: 'end', rotate: 0, align: stats.median >= stats.weighted ? 'left' : 'right' } } : null,
    Number.isFinite(stats.weighted) ? { xAxis: clipped(stats.weighted), lineStyle: { color: p.accent, type: 'solid', width: 1.5 },
      label: { formatter: `index ${signed(stats.weighted)}`, color: p.accent, position: 'end', rotate: 0, align: stats.weighted > stats.median ? 'left' : 'right' } } : null,
  ].filter(Boolean);
  return {
    animation: false,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace', fontSize: 10 },
    grid: { ...GRID, top: 28 },
    tooltip: {
      trigger: 'item', confine: true, backgroundColor: '#000', borderColor: p.border, borderWidth: 1,
      extraCssText: 'max-width:min(92vw,360px);white-space:normal;',
      textStyle: { color: p.text, fontSize: 11, fontFamily: 'ui-monospace, Menlo, monospace' },
      formatter: (item) => {
        const tone = (v) => (v > 0 ? p.up : v < 0 ? p.down : p.dim);
        if (item.seriesName === 'heavy') {
          const m = item.data.member;
          return `<b>${m.ticker}</b> <span style="color:${tone(m.ret)}">${signed(m.ret, 2)}</span><br/>`
            + `${m.name || ''}<br/>weight ${num(m.weight, 2)}% · ${signed(m.contribution, 2).replace('%', '')} pts of the index's move`;
        }
        const b = binned.bins[item.dataIndex];
        const first = item.dataIndex === 0; const last = item.dataIndex === binned.bins.length - 1;
        const range = first ? `${signed(b.hi, 2)} or lower` : last ? `${signed(b.lo, 2)} or higher` : `${signed(b.lo, 2)} to ${signed(b.hi, 2)}`;
        const names = b.names.slice(0, 6).map((m) => `${m.ticker} <span style="color:${tone(m.ret)}">${signed(m.ret)}</span>`).join(' · ');
        return `${range}<br/><b>${b.count}</b> members · ${num((b.weight / Math.max(1e-9, stats.total_weight)) * 100, 1)}% of the index's weight`
          + (names ? `<br/>${names}${b.names.length > 6 ? ` · +${b.names.length - 6} more` : ''}` : '');
      },
    },
    xAxis: {
      type: 'value', min: -binned.clip, max: binned.clip,
      axisLine: { lineStyle: { color: p.border } }, axisTick: { show: false },
      axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => (v <= -binned.clip ? `≤${v}%` : v >= binned.clip ? `≥+${v}%` : `${v > 0 ? '+' : ''}${v}%`) },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value', min: 0, max: tallest * (1.08 + rows * ROW_STEP),
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => (v > tallest * 1.02 ? '' : mode === 'WEIGHT' ? `${num(v, 0)}%` : num(v, 0)) },
      splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
    },
    series: [
      {
        name: 'members', type: 'bar', barWidth, barGap: '-100%',
        data: binned.bins.map((b) => ({
          value: [b.center, value(b)],
          itemStyle: { color: b.center > 0 ? p.up : p.down, opacity: 0.8 },
        })),
        markLine: { silent: true, symbol: 'none', data: lines },
      },
      {
        name: 'heavy', type: 'scatter', symbolSize: 7,
        data: heavy.map((m) => ({
          value: [m.at, tallest * (1.06 + m.row * ROW_STEP)], member: m,
          itemStyle: { color: 'transparent', borderColor: m.ret > 0 ? p.up : m.ret < 0 ? p.down : p.dim, borderWidth: 1.5 },
          label: { show: true, position: 'top', distance: 3, formatter: m.ticker, color: p.text, fontSize: 10 },
        })),
      },
    ],
  };
}

function statsLine(stats, live) {
  const cell = (label, text, cls = '') => el('span', { class: 'spread-stat' }, [el('span', { class: 'stat-label', text: label }), el('span', { class: `spread-value ${cls}`, text })]);
  const dir = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : 'dim');
  return el('div', { class: 'spread-stats' }, [
    live ? liveBadge('LIVE · SO FAR TODAY') : null,
    cell('ROSE / FELL', `${stats.up} / ${stats.down}`),
    cell('INDEX (WEIGHTED)', signed(stats.weighted, 2), dir(stats.weighted)),
    cell('MEDIAN MEMBER', signed(stats.median, 2), dir(stats.median)),
    cell('EQUAL WEIGHT', signed(stats.equal, 2), dir(stats.equal)),
    cell(`TOP ${stats.heavy.length} (${num(stats.heavy_weight, 0)}% OF WEIGHT)`, `${signed(stats.heavy_part, 2).replace('%', '')} pts`, dir(stats.heavy_part)),
    cell('THE OTHER MEMBERS', `${signed(stats.rest_part, 2).replace('%', '')} pts`, dir(stats.rest_part)),
  ].filter(Boolean));
}

export function mountDaySpread(host, ctx) {
  host.append(el('div', { class: 'gap', text: 'Loading the day\'s spread…' }));
  ctx.loadArtifact('heatmaps').then((heat) => {
    const universes = [{ label: heat.primary?.label || 'S&P 500', constituents: heat.constituents || [] },
      ...(heat.index_maps || []).map((m) => ({ label: m.label, constituents: m.constituents || [] }))]
      .filter((u) => u.constituents.length);
    if (!universes.length) { host.replaceChildren(el('div', { class: 'gap', text: 'No member returns in this build.' })); return; }
    let universe = universes[0].label; let mode = 'COUNT'; let live = null;
    const chart = el('div', { class: 'chart spread-chart' });
    const stats = el('div', {}); const note = el('div', { class: 'note-text' }); const lead = el('div', { class: 'spread-verdict' });
    const draw = () => {
      const u = universes.find((x) => x.label === universe);
      const { members: list, missing } = members(u.constituents, live);
      const binned = bins(list);
      const s = { ...summary(list), total_weight: list.reduce((a, m) => a + m.weight, 0) };
      stats.replaceChildren(statsLine(s, Boolean(live)));
      lead.textContent = verdict(s) || '';
      note.textContent = `${s.n} members of the ${u.label}${missing ? ` (${missing} with no ${live ? 'live quote' : 'move'} left out)` : ''}, `
        + `${live ? 'moves so far today from the heat map\'s live quotes, against the last close' : `moves on ${heat.as_of}`}, in ${num(binned.width, 2)}-point bins; `
        + `moves past ±${num(binned.clip, 0)}% share the end bins. BY WEIGHT stacks each bin by index weight instead of counting members. `
        + 'The index line is the members\' moves weighted by today\'s index weights; the median is the typical member. Marked: the ten heaviest names, with the points of the index\'s move each accounts for.';
      requestAnimationFrame(() => render(chart, (_o, p) => spreadOption(binned, s, mode, p, Math.max(200, (chart.clientWidth || 600) - GRID.left - GRID.right))));
    };
    const tools = el('div', { class: 'credit-tools' }, [
      universes.length > 1 ? periodSwitch(universes.map((u) => u.label), universe, (label) => { universe = label; draw(); }) : null,
      periodSwitch(['COUNT', 'WEIGHT'], mode, (label) => { mode = label; draw(); }),
    ].filter(Boolean));
    host.replaceChildren(card('THE DAY\'S SPREAD · EVERY MEMBER\'S MOVE', tools, [lead, stats, chart, note]));
    draw();
    // During the session the heat map's quotes carry every member; a board most
    // of whose quotes are stale (its feed stopped) leaves the close standing.
    createFeed('api/quotes?board=heatmap', {
      node: chart,
      onData: (body) => {
        const now = Date.now();
        const quotes = (body?.quotes || []).filter((q) => q && !q.error && Number.isFinite(q.change_pct));
        const fresh = body?.session?.open === true && quotes.length
          && quotes.filter((q) => isStale(q, body, now)).length * 2 <= quotes.length;
        live = fresh ? new Map(quotes.map((q) => [String(q.symbol).toUpperCase().replace('.', '-'), q])) : null;
        draw();
      },
    });
  }).catch((error) => host.replaceChildren(el('div', { class: 'gap', text: `The day's spread is unavailable: ${error.message}.` })));
}
