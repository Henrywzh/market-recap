// ROTATION: GICS sectors against the S&P 500. The picture first -- where each
// sector sits on the rotation graph and how its relative strength has moved --
// then one sector at a time: its sub-industries and the names that moved it.

import { el, card, num, metaRow, periodSwitch, sectionTitle, tag, DASH } from '../fmt.js';
import { render, SERIES_COLORS } from '../charts.js';
import { renderAggregates } from './valuation.js';
import { tickerHref } from '../routes.js';
import { createManualFeed } from '../live-feed.js';
import { TODAY, todayFrom, applyToday } from '../rotation-live.js';

const WINDOWS = ['1M', '3M', '6M', '12M'];
// Weekly points drawn on the rotation graph for each window. Past a quarter
// the weekly path is noise, so the longer windows keep thirteen weeks.
const TAIL_WEEKS = { [TODAY]: 5, '1M': 5, '3M': 13, '6M': 13, '12M': 13 };
// Every other sector keeps a short tail: eleven half-year paths are a tangle.
const OTHER_TAIL = 5;
const SCHEMES = { cap: 'CAP-WTD', equal: 'EQUAL-WTD' };
const QUADRANTS = {
  leading: { label: 'LEADING', color: (p) => p.up, tone: 'up' },
  weakening: { label: 'WEAKENING', color: (p) => p.accent, tone: 'warn' },
  lagging: { label: 'LAGGING', color: (p) => p.down, tone: 'down' },
  improving: { label: 'IMPROVING', color: (p) => p.blue, tone: 'info' },
};
const SECTOR_SHORT = {
  'Communication Services': 'Comm Services',
  'Consumer Discretionary': 'Cons Discretionary',
  'Consumer Staples': 'Cons Staples',
  'Information Technology': 'Info Tech',
};
const short = (label) => SECTOR_SHORT[label] || label;
const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits = 1, unit = '') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${unit}` : DASH);

const over = (w) => (w === TODAY ? 'today so far' : `over ${w}`);

function quadrantOf(ratio, momentum) {
  if (!present(ratio) || !present(momentum)) return null;
  if (ratio >= 100) return momentum >= 100 ? 'leading' : 'weakening';
  return momentum >= 100 ? 'improving' : 'lagging';
}

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function rrgChart(node, groups, view, onPick) {
  const tail = TAIL_WEEKS[view.window];
  const paths = groups.map((g) => ({
    g, points: g[view.scheme].rrg.slice(-(g.key === view.selected ? tail : Math.min(tail, OTHER_TAIL))),
  })).filter((x) => x.points.length);
  let dx = 1, dy = 1;
  paths.forEach(({ points }) => points.forEach(([, r, m]) => {
    dx = Math.max(dx, Math.abs(r - 100));
    dy = Math.max(dy, Math.abs(m - 100));
  }));
  const pad = (d) => Math.ceil(d * 1.12 * 2) / 2;
  const [xr, yr] = [pad(dx), pad(dy)];
  const chart = render(node, (option, p) => {
    const area = (x0, y0, x1, y1, color, label, position) => [
      { coord: [x0, y0], itemStyle: { color, opacity: 0.07 },
        label: { show: true, position, color, opacity: 0.8, fontSize: 10, fontWeight: 'bold', formatter: label } },
      { coord: [x1, y1] },
    ];
    const series = [{
      type: 'scatter', data: [], silent: true,
      markArea: {
        silent: true,
        data: [
          area(100, 100, 100 + xr, 100 + yr, p.up, 'LEADING', 'insideTopRight'),
          area(100, 100 - yr, 100 + xr, 100, p.accent, 'WEAKENING', 'insideBottomRight'),
          area(100 - xr, 100 - yr, 100, 100, p.down, 'LAGGING', 'insideBottomLeft'),
          area(100 - xr, 100, 100, 100 + yr, p.blue, 'IMPROVING', 'insideTopLeft'),
        ],
      },
      markLine: {
        silent: true, symbol: 'none', label: { show: false },
        lineStyle: { color: p.faint, type: 'solid', width: 1 },
        data: [{ xAxis: 100 }, { yAxis: 100 }],
      },
    }];
    paths.forEach(({ g, points }) => {
      const last = points[points.length - 1];
      const color = QUADRANTS[quadrantOf(last[1], last[2])]?.color(p) || p.dim;
      const chosen = g.key === view.selected;
      series.push({
        type: 'line', name: g.key, smooth: 0.12,
        data: points.map(([date, r, m]) => ({ value: [r, m], date })),
        symbol: 'circle',
        symbolSize: (value, q) => (q.dataIndex === points.length - 1 ? 0 : 3),
        lineStyle: { color, width: chosen ? 2.4 : 1.2, opacity: chosen ? 0.95 : 0.55 },
        itemStyle: { color, opacity: chosen ? 0.95 : 0.55 },
        z: chosen ? 4 : 2,
      });
    });
    series.push({
      type: 'scatter', name: 'heads', z: 5,
      data: paths.map(({ g, points }) => {
        const last = points[points.length - 1];
        const color = QUADRANTS[quadrantOf(last[1], last[2])]?.color(p) || p.dim;
        const chosen = g.key === view.selected;
        return {
          value: [last[1], last[2]], name: g.key, date: last[0],
          symbolSize: 7 + Math.sqrt(g.weight || 0) * 1.6,
          itemStyle: { color, borderColor: chosen ? p.text : color, borderWidth: chosen ? 1.5 : 0 },
          label: { fontWeight: chosen ? 'bold' : 'normal', color: chosen ? p.text : p.dim },
        };
      }),
      label: { show: true, position: 'right', fontSize: 10, formatter: (q) => short(q.name) },
      labelLayout: { moveOverlap: 'shiftY' },
    });
    return {
      ...option,
      grid: { left: 44, right: 20, top: 12, bottom: 36 },
      tooltip: {
        ...option.tooltip, trigger: 'item', axisPointer: undefined,
        formatter: (q) => {
          const key = q.seriesName === 'heads' ? q.name : q.seriesName;
          const [r, m] = q.value || [];
          const quad = QUADRANTS[quadrantOf(r, m)]?.label || '';
          return `<b>${key}</b> · week to ${q.data?.date || ''}<br>RS-Ratio ${num(r, 2)} · RS-Momentum ${num(m, 2)}<br>${quad}`;
        },
      },
      xAxis: {
        type: 'value', min: 100 - xr, max: 100 + xr, name: 'RS-RATIO →', nameLocation: 'middle', nameGap: 22,
        nameTextStyle: { color: p.dim, fontSize: 10 },
        axisLabel: { color: p.dim, fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: p.border, opacity: 0.35 } },
      },
      yAxis: {
        type: 'value', min: 100 - yr, max: 100 + yr, name: 'RS-MOMENTUM →', nameLocation: 'middle', nameGap: 30,
        nameTextStyle: { color: p.dim, fontSize: 10 },
        axisLabel: { color: p.dim, fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: p.border, opacity: 0.35 } },
      },
      series,
    };
  });
  chart?.on('click', (q) => {
    const key = q.seriesName === 'heads' ? q.name : q.seriesName;
    if (groups.some((g) => g.key === key)) onPick(key);
  });
}

function rsLines(node, data, ranked, view, colorOf) {
  const n = data.windows[view.window];
  const dates = data.dates.slice(-(n + 1));
  const shownKeys = [...ranked.slice(0, 3), ...ranked.slice(-3)].map((g) => g.key);
  if (!shownKeys.includes(view.selected)) shownKeys.push(view.selected);
  const shown = data.groups.filter((g) => shownKeys.includes(g.key));
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 44, right: 18, top: 34 },
    legend: {
      top: 0, left: 0, itemWidth: 12, itemHeight: 2, icon: 'rect',
      textStyle: { color: p.dim, fontSize: 10 },
      data: shown.map((g) => short(g.label)),
    },
    tooltip: {
      ...option.tooltip,
      valueFormatter: (v) => (present(v) ? num(v, 1) : DASH),
    },
    xAxis: { ...option.xAxis, data: dates },
    series: shown.map((g) => {
      const rs = g[view.scheme].rs.slice(-(n + 1));
      const base = rs.find(present);
      const chosen = g.key === view.selected;
      return {
        name: short(g.label), type: 'line', showSymbol: false,
        data: rs.map((v) => (present(v) && base ? (v / base) * 100 : null)),
        lineStyle: { width: chosen ? 2.4 : 1.3, color: colorOf(g.key) },
        itemStyle: { color: colorOf(g.key) },
        z: chosen ? 3 : 2,
        markLine: g === shown[0] ? {
          silent: true, symbol: 'none', data: [{ yAxis: 100 }],
          lineStyle: { color: p.faint, type: 'dashed' },
          label: { color: p.faint, fontSize: 9, formatter: 'S&P 500', position: 'insideEndTop' },
        } : undefined,
      };
    }),
  }));
}

function etfCell(etf) {
  if (!etf || !present(etf.excess)) return el('td', { class: 'rot-cell dim', title: etf?.error || '', text: etf ? `${etf.symbol} ${DASH}` : DASH });
  return el('td', { class: `rot-cell rot-etf ${etf.excess >= 0 ? 'up' : 'down'}`, title: `${etf.symbol} ${signed(etf.return, 2, '%')} today`,
    text: `${etf.symbol} ${signed(etf.excess, 2)}` });
}

// TODAY has no path to draw: each sector's basket against the S&P 500 so far,
// beside its SPDR fund against SPY.
function todayBars(node, ranked, view, today, onPick) {
  const labels = ranked.map((g) => short(g.label));
  node.style.height = `${Math.max(260, ranked.length * 26 + 50)}px`;
  const chart = render(node, (option, p) => ({
    ...option,
    grid: { left: 120, right: 46, top: 28, bottom: 20 },
    legend: { top: 0, left: 0, itemWidth: 10, itemHeight: 8, textStyle: { color: p.dim, fontSize: 10 } },
    tooltip: {
      ...option.tooltip, trigger: 'axis',
      formatter: (items) => {
        const g = ranked[items[0].dataIndex];
        const etf = today.etfs[g.key];
        return `<b>${g.label}</b><br>basket ${signed(g[view.scheme].windows[TODAY].return, 2, '%')} · ${signed(g[view.scheme].windows[TODAY].excess, 2)} pp vs S&P`
          + (etf ? `<br>${etf.symbol} ${signed(etf.return, 2, '%')} · ${signed(etf.excess, 2)} pp vs ${today.etfBenchmark?.symbol || 'SPY'}` : '');
      },
    },
    xAxis: { type: 'value', axisLabel: { color: p.dim, fontSize: 10 }, splitLine: { lineStyle: { color: p.border, opacity: 0.4 } } },
    yAxis: {
      type: 'category', inverse: true, data: labels, triggerEvent: true,
      axisLabel: { color: p.dim, fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false },
    },
    series: [
      {
        name: `BASKET vs S&P (${view.scheme === 'cap' ? 'cap' : 'equal'}-wtd)`, type: 'bar', barMaxWidth: 9,
        itemStyle: { color: p.accent },
        data: ranked.map((g) => ({ value: g[view.scheme].windows[TODAY].excess,
          itemStyle: { color: (g[view.scheme].windows[TODAY].excess ?? 0) >= 0 ? p.up : p.down, opacity: 0.85 } })),
        label: { show: true, position: 'right', color: p.dim, fontSize: 9, formatter: (q) => signed(q.value, 2) },
        markLine: { silent: true, symbol: 'none', data: [{ xAxis: 0 }], lineStyle: { color: p.faint }, label: { show: false } },
      },
      {
        name: `SPDR ETF vs ${today.etfBenchmark?.symbol || 'SPY'}`, type: 'bar', barMaxWidth: 9,
        itemStyle: { color: p.faint },
        data: ranked.map((g) => ({ value: today.etfs[g.key]?.excess ?? null, itemStyle: { color: p.faint, opacity: 0.9 } })),
        label: { show: true, position: 'right', color: p.faint, fontSize: 9, formatter: (q) => (present(q.value) ? signed(q.value, 2) : '') },
      },
    ],
  }));
  chart?.on('click', (q) => {
    const index = q.componentType === 'yAxis' ? labels.indexOf(q.value) : q.dataIndex;
    if (ranked[index]) onPick(ranked[index].key);
  });
}

function heatGrid(ranked, view, benchmark, onPick, today = null) {
  const windows = today ? [TODAY, ...WINDOWS] : WINDOWS;
  const scale = {};
  windows.forEach((w) => {
    scale[w] = Math.max(1, ...ranked.map((g) => Math.abs(g[view.scheme].windows[w].excess ?? 0)));
  });
  const cell = (value, w) => {
    if (!present(value)) return el('td', { class: 'rot-cell', text: DASH });
    const alpha = Math.round(Math.min(1, Math.abs(value) / scale[w]) * 55);
    const tone = value >= 0 ? 'var(--up)' : 'var(--down)';
    return el('td', {
      class: `rot-cell${w === view.window ? ' active' : ''}`,
      style: `background: color-mix(in srgb, ${tone} ${alpha}%, transparent)`,
      text: signed(value),
    });
  };
  const rows = ranked.map((g) => {
    const s = g[view.scheme];
    const quad = QUADRANTS[s.quadrant];
    const breadth = s.breadth[view.window];
    return el('tr', {
      class: g.key === view.selected ? 'selected' : '',
      onclick: () => onPick(g.key),
      title: `${g.label} · ${g.members} names · ${num(g.weight, 1)}% of the index`,
    }, [
      el('td', { class: 'rot-name' }, [
        el('span', { class: `rot-dot q-${s.quadrant || 'none'}` }),
        short(g.label),
      ]),
      ...windows.map((w) => cell(s.windows[w].excess, w)),
      ...(today ? [etfCell(today.etfs[g.key])] : []),
      el('td', { class: 'rot-breadth' }, [
        el('span', { class: 'rot-breadth-bar' }, [
          el('span', { class: 'rot-breadth-fill', style: `width:${present(breadth) ? breadth : 0}%` }),
        ]),
        el('span', { class: 'rot-breadth-text', text: present(breadth) ? `${num(breadth, 0)}%` : DASH }),
      ]),
      el('td', { class: 'rot-quad' }, [quad ? tag(quad.label, quad.tone) : DASH]),
    ]);
  });
  const head = el('tr', {}, [
    el('th', { text: 'SECTOR' }),
    ...windows.map((w) => el('th', { class: w === view.window ? 'active' : '', text: w })),
    ...(today ? [el('th', { title: `SPDR sector fund vs ${today.etfBenchmark?.symbol || 'SPY'}, today so far`, text: 'ETF TODAY' })] : []),
    el('th', { text: `BEAT S&P · ${view.window}` }),
    el('th', { text: 'NOW' }),
  ]);
  return el('div', { class: 'table-scroll' }, [
    el('table', { class: 'data rot-grid' }, [el('thead', {}, [head]), el('tbody', {}, rows)]),
    el('div', { class: 'rot-foot dim', text: `pp vs the S&P 500 (${view.scheme === 'cap' ? 'cap' : 'equal'}-weighted: ${windows.map((w) => `${w} ${signed(benchmark[w], 1, '%')}`).join(' · ')})`
      + (today ? ` · ETF TODAY: the SPDR sector fund vs ${today.etfBenchmark?.symbol || 'SPY'} (${signed(today.etfBenchmark?.return, 2, '%')}), for comparison; the baskets are the page's sectors` : '') }),
  ]);
}

function hbars(node, items, p0 = {}) {
  node.style.height = `${Math.max(150, items.length * 20 + 30)}px`;
  const chart = render(node, (option, p) => ({
    ...option,
    grid: { left: p0.left || 150, right: 46, top: 4, bottom: 20 },
    tooltip: { ...option.tooltip, trigger: 'item', axisPointer: undefined, formatter: (q) => items[q.dataIndex].tip },
    xAxis: {
      type: 'value', axisLabel: { color: p.dim, fontSize: 10 },
      splitLine: { lineStyle: { color: p.border, opacity: 0.4 } },
    },
    yAxis: {
      type: 'category', inverse: true, data: items.map((i) => i.label), triggerEvent: Boolean(p0.onPick),
      axisLabel: { color: p.dim, fontSize: 10, width: (p0.left || 150) - 10, overflow: 'truncate' },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar', barMaxWidth: 12,
      data: items.map((i) => ({ value: i.value, itemStyle: { color: i.value >= 0 ? p.up : p.down, opacity: 0.8 } })),
      label: { show: true, position: 'right', color: p.dim, fontSize: 10, formatter: (q) => signed(q.value, 1) },
      markLine: { silent: true, symbol: 'none', data: [{ xAxis: 0 }], lineStyle: { color: p.faint }, label: { show: false } },
    }],
  }));
  if (p0.onPick) {
    chart?.on('click', (q) => {
      const index = q.componentType === 'yAxis' ? items.findIndex((i) => i.label === q.value) : q.dataIndex;
      if (items[index]) p0.onPick(items[index]);
    });
  }
}

function drillDown(data, view) {
  const group = data.groups.find((g) => g.key === view.selected);
  if (!group) return null;
  const s = group[view.scheme];
  const subs = data.sub_industries
    .filter((x) => x.sector === group.key && present(x[view.scheme][view.window].excess))
    .sort((a, b) => b[view.scheme][view.window].excess - a[view.scheme][view.window].excess);
  const members = data.members
    .filter((m) => m.sector === group.key && present(m.contribution?.[view.scheme]?.[view.window]))
    .sort((a, b) => b.contribution[view.scheme][view.window] - a.contribution[view.scheme][view.window]);
  const movers = members.length <= 12 ? members : [...members.slice(0, 6), ...members.slice(-6)];

  const subNode = el('div', { class: 'chart' });
  const memberNode = el('div', { class: 'chart' });
  requestAnimationFrame(() => {
    hbars(subNode, subs.map((x) => ({
      label: x.label,
      value: x[view.scheme][view.window].excess,
      tip: `<b>${x.label}</b> · ${x.members} names<br>${view.window} return ${signed(x[view.scheme][view.window].return, 1, '%')} · vs S&P ${signed(x[view.scheme][view.window].excess, 1)} pp`,
    })), { left: 170 });
    hbars(memberNode, movers.map((m) => ({
      label: m.ticker,
      value: m.contribution[view.scheme][view.window],
      tip: `<b>${m.ticker}</b> ${m.name}<br>${m.sub_sector}<br>${view.window} return ${signed(m.returns[view.window], 1, '%')} · adds ${signed(m.contribution[view.scheme][view.window], 2)} pp to the sector`,
    })), { left: 56, onPick: (item) => { location.hash = tickerHref(item.label); } });
  });
  const excess = s.windows[view.window].excess;
  const top = members[0];
  const summary = [
    `${group.label}: ${signed(excess, 1)} pp vs the S&P 500 ${over(view.window)}`,
    `${present(s.breadth[view.window]) ? num(s.breadth[view.window], 0) : DASH}% of ${group.members} names beat it`,
    top ? `biggest lift ${top.ticker} ${signed(top.contribution[view.scheme][view.window], 1)} pp` : null,
  ].filter(Boolean).join(' · ');
  return card(`INSIDE ${group.label.toUpperCase()}`, el('span', { class: 'dim', text: `${view.window} · ${SCHEMES[view.scheme].toLowerCase()}` }), [
    el('div', { class: 'rot-summary', text: summary }),
    el('div', { class: 'grid two' }, [
      el('div', {}, [el('div', { class: 'rot-chart-title', text: `SUB-INDUSTRIES · pp vs S&P 500 · ≥ ${data.min_sub_members} names` }), subs.length ? subNode : el('div', { class: 'dim', text: 'No sub-industry with enough names.' })]),
      el('div', {}, [el('div', { class: 'rot-chart-title', text: 'WHO MOVED IT · contribution to the sector\'s pp, top and bottom 6 · click a name for its page' }), memberNode]),
    ]),
  ]);
}

function methodNotes(data) {
  const etf = data.index?.holdings_etf || 'SPY';
  return [
    `Each sector is a basket of the S&P 500's current members with that GICS sector, built from the same daily closes as the rest of the site. No extra data is fetched.`,
    `TODAY appears when you press REFRESH (or pick TODAY); the page never asks on its own. It is the same baskets and benchmark priced at each member's live change since the previous close (Yahoo, unofficial, a few minutes old), weighted by today's official ${etf} weight. Members without a live price are left out of every average and counted. ETF TODAY is the SPDR sector fund against ${etf} over the same session: a tradable comparison, not the basket. The rotation graph stays on weekly closes.`,
    `Cap-weighted: each member is held at today's official ${etf} weight turned into a share count and kept there, so weights drift with prices as an index's do between rebalances. Equal-weighted: the average daily return of the members. The benchmark is the whole index built the same way from the same dividend-adjusted closes, so dividends and the weighting scheme cancel.`,
    `Relative strength (pp) = sector return − index return over the window (21/63/126/252 sessions). A member's contribution is its weight in the sector at the window's start × (its return − the index's); a sector's contributions add up to its pp.`,
    `Rotation graph, weekly: RS = sector ÷ index at each week's last close. RS-Ratio = 100 × RS ÷ its ${data.rrg_weeks?.ratio ?? 10}-week average (above 100: outperforming its recent trend). RS-Momentum = 100 × RS-Ratio ÷ its ${data.rrg_weeks?.momentum ?? 4}-week average (above 100: that lead is growing). Sectors usually travel clockwise: improving → leading → weakening → lagging. The selected sector's tail shows the last ${Object.entries(TAIL_WEEKS).map(([w, n]) => `${n} weeks for ${w}`).join(', ')}; the others keep ${OTHER_TAIL}. The current week ends at the latest close. This is an open approximation of the idea, not the proprietary JdK RS-Ratio.`,
    `Membership and classification are today's, applied to the whole window: a name that joined the index recently counts over periods it was not a member, and names that left are absent (survivorship). GICS labels are the current Wikipedia list, not GICS Direct. Research tool, not investment advice.`,
  ];
}

// SECTORS: where money is rotating (this panel), then how expensive each
// index and sector is against its own ten years (VALUATION's aggregates).
export default async function renderRotation(root, data, _manifest, ctx = {}) {
  root.append(sectionTitle('ROTATION', 'RELATIVE STRENGTH VS THE S&P 500'));
  renderRotationSection(root, data);
  const valuation = await ctx.loadArtifact?.('valuation').catch(() => null);
  const host = el('div', { class: 'sectors-valuation' });
  root.append(sectionTitle('VALUATION', 'P/E AGAINST OWN 10 YEARS'), host);
  if (!renderAggregates(host, valuation)) {
    host.append(el('div', { class: 'gap', text: 'Index and sector P/E were not built for this session.' }));
  }
}

function renderRotationSection(root, data) {
  const groups = data.groups || [];
  if (!groups.length) {
    root.append(el('div', { class: 'gap', text: 'No sector baskets were built for this session.' }));
    return;
  }
  const colors = new Map(groups.map((g, i) => [g.key, SERIES_COLORS[i % SERIES_COLORS.length]]));
  const view = { scheme: 'cap', window: '1M', selected: null, picked: false };
  // TODAY exists once the reader has pressed REFRESH (or picked TODAY):
  // the page never asks for live prices on its own.
  let today = null;
  let wantToday = false;

  const statsHost = el('div', { class: 'stat-strip rot-stats' });
  const rrgNode = el('div', { class: 'chart tall' });
  const linesNode = el('div', { class: 'chart tall' });
  const rrgNote = el('span', { class: 'dim' });
  const linesNote = el('span', { class: 'dim' });
  const gridHost = el('div');
  const drillHost = el('div');

  const pick = (key) => { view.selected = key; view.picked = true; draw(); };

  function draw() {
    const ranked = [...groups].sort((a, b) => (b[view.scheme].windows[view.window].excess ?? -Infinity)
      - (a[view.scheme].windows[view.window].excess ?? -Infinity));
    if (!view.picked || !groups.some((g) => g.key === view.selected)) view.selected = ranked[0].key;

    const bench = data.benchmark[view.scheme] || {};
    const beat = data.members.filter((m) => present(m.returns[view.window]) && present(bench[view.window]));
    const beating = beat.filter((m) => m.returns[view.window] > bench[view.window]).length;
    const leading = groups.filter((g) => g[view.scheme].quadrant === 'leading');
    const strongest = ranked[0];
    const weakest = ranked[ranked.length - 1];
    statsHost.replaceChildren(
      stat(`S&P 500 · ${view.window}`, signed(data.benchmark.cap[view.window], 1, '%'),
        `equal-weight ${signed(data.benchmark.equal[view.window], 1, '%')}`,
        (data.benchmark.cap[view.window] ?? 0) >= 0 ? 'up' : 'down'),
      stat('STRONGEST', short(strongest.label), `${signed(strongest[view.scheme].windows[view.window].excess, 1)} pp vs S&P`, 'up'),
      stat('WEAKEST', short(weakest.label), `${signed(weakest[view.scheme].windows[view.window].excess, 1)} pp vs S&P`, 'down'),
      stat('LEADING NOW', `${leading.length} of ${groups.length}`, leading.map((g) => short(g.label)).join(' · ') || 'none'),
      stat('NAMES BEATING S&P', beat.length ? `${Math.round((100 * beating) / beat.length)}%` : DASH, `${beating} of ${beat.length} · ${view.window} · vs ${view.scheme === 'cap' ? 'cap' : 'equal'}-wtd`),
    );

    const tail = TAIL_WEEKS[view.window];
    rrgNote.textContent = `${view.window === TODAY ? 'weekly closes, not live · ' : ''}${SCHEMES[view.scheme].toLowerCase()} · ${tail > OTHER_TAIL ? `${tail}-week tail on ${short(groups.find((g) => g.key === view.selected).label)}, ${OTHER_TAIL} on the rest` : `${tail}-week tails`} · click to inspect`;
    rrgChart(rrgNode, groups, view, pick);
    if (view.window === TODAY) {
      linesTitle.textContent = 'TODAY SO FAR · BASKET VS SPDR ETF';
      linesNote.textContent = `pp · ${today.priced} of ${today.total} members priced · click a sector`;
      todayBars(linesNode, ranked, view, today, pick);
    } else {
      linesTitle.textContent = 'RELATIVE STRENGTH VS S&P 500';
      linesNote.textContent = `top 3 / bottom 3 · ${view.window} · rebased to 100`;
      linesNode.style.height = '';
      rsLines(linesNode, data, ranked, view, (key) => colors.get(key));
    }
    gridHost.replaceChildren(card('RELATIVE STRENGTH BY WINDOW', el('span', { class: 'dim', text: 'pp vs S&P 500 · click a row to inspect' }),
      [heatGrid(ranked, view, bench, pick, today)]));
    drillHost.replaceChildren(...[drillDown(data, view)].filter(Boolean));
  }

  const pressed = () => [...windowSwitch.children].forEach((b) => b.setAttribute('aria-pressed', String(b.textContent === view.window)));
  const feed = createManualFeed(['api/quotes?board=heatmap', 'api/quotes?board=sector_etfs'], {
    onData: ([members, etfs]) => {
      today = todayFrom(data, members.quotes, etfs.quotes);
      applyToday(data, today);
      if (wantToday) view.window = TODAY;
      wantToday = false;
      pressed();
      draw();
    },
  });
  // Picking TODAY before any live prices is the reader asking for them.
  const windowSwitch = periodSwitch([TODAY, ...WINDOWS], view.window, async (w) => {
    if (w === TODAY && !today) {
      wantToday = true;
      await feed.refresh();
      if (!today) { wantToday = false; pressed(); }
      return;
    }
    view.window = w;
    draw();
  });
  const controls = el('div', { class: 'rot-controls' }, [
    el('span', { class: 'dim', text: 'WEIGHT' }),
    periodSwitch(Object.values(SCHEMES), SCHEMES[view.scheme], (label) => {
      view.scheme = Object.keys(SCHEMES).find((k) => SCHEMES[k] === label);
      draw();
    }),
    el('span', { class: 'dim', text: 'WINDOW' }),
    windowSwitch,
    el('span', { class: 'dim rot-live-label', text: 'LIVE' }),
    feed.controls,
  ]);
  const linesTitle = el('span', { class: 'card-title', text: 'RELATIVE STRENGTH VS S&P 500' });
  const linesCard = card('', linesNote, [linesNode]);
  linesCard.querySelector('.card-title').replaceWith(linesTitle);

  root.append(
    metaRow(`SECTOR ROTATION · GICS sectors vs the ${data.index?.label || 'S&P 500'} · ${data.members.length} members · as of ${data.as_of}`, methodNotes(data)),
    controls,
    statsHost,
    el('div', { class: 'grid two rot-top' }, [
      card('RELATIVE ROTATION GRAPH', rrgNote, [rrgNode]),
      linesCard,
    ]),
    el('div', { class: 'grid two rot-bottom' }, [gridHost, drillHost]),
  );
  requestAnimationFrame(draw);
}
