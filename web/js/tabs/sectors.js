// SECTORS: one hub for the market, its eleven GICS sectors, their sub-industries
// and the names in each. The hash argument picks the page: none is the market
// (#sectors), a sector's SPDR fund is a sector (#sectors/XLP), and a
// sub-industry's key is its page (#sectors/XLP-SDNB). The hub keeps the rotation
// graph and the valuation under its sector table. A sector or sub-industry page
// opens on its charts -- against the market, its valuation now and next, the
// map of its sub-industries and names -- and folds the tables away beneath them.
// The figures come from sectors.json and each page's history from
// artifacts/sectors/<KEY>.json; sectors-model.js reads and shapes them.

import { el, card, table, num, pct, dirClass, metaRow, sectionTitle, periodSwitch, tag, gap, DASH } from '../fmt.js';
import { tickerHref, hashFor } from '../routes.js';
import { render } from '../charts.js';
import { valuationBlock } from '../valuation-block.js';
import { WINDOWS, pickWindow, sliceWindow, windowSwitch } from '../windows.js';
import { renderRotationGraph, renderRotationDetail } from './rotation.js';
import { themeBlocks } from './themes.js';
import {
  PERIODS, DEFAULT_PERIOD, REPORT_WINDOW_DAYS, CHART_PERIODS, DEFAULT_CHART_PERIOD, DEFAULT_WINDOW, NAMED_LIMIT,
  levelOf, membersOf, subsOf, sortRows, upcoming,
  timingLabel, timingTitle, quadrantTag, evidenceFlags, extremesOf, themedSubs, ordinal, boolMark, nameColumns,
  sectorShort, shortName, subBars, subMapPoints, nameMapPoints, symmetricRange, pathBars, longestDates,
  pageValuation,
} from '../sectors-model.js';

const THIN_TITLE = 'fewer than 5 names: medians are fragile';
// The lookback window the reader last picked on a sector or sub-industry page.
const WINDOW_KEY = 'mr-window-sectors';
const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits = 1, unit = '') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${unit}` : DASH);
const share = (v, digits = 1) => (present(v) ? `${num(v, digits)}%` : DASH);
const multiple = (v) => (present(v) ? `${num(v, 1)}×` : DASH);
const sectorHref = (key) => `#${hashFor('sectors', key)}`;
const themeHref = (key) => `#${hashFor('themes', String(key).toUpperCase())}`;
const markTone = (v) => (v === true ? 'up' : v === false ? 'down' : 'dim');
const chartNode = () => el('div', { class: 'chart' });
const slot = () => el('div', { class: 'sx-slot' });

// The four corners of the map, named by what a bubble there is: its return
// against the index (lagging or leading) and its P/E against its own history
// (rich or cheap).
const MAP_CAPTIONS = [
  { text: 'LAGGING AND RICH', at: { left: 62, top: 18 } },
  { text: 'LEADING AND RICH', at: { right: 30, top: 18 } },
  { text: 'LAGGING AND CHEAP', at: { left: 62, bottom: 46 } },
  { text: 'LEADING AND CHEAP', at: { right: 30, bottom: 46 } },
];

// A link inside a clickable row keeps its own destination: the row ignores it.
function link(text, href, className = null) {
  return el('a', { href, class: className, text });
}

function go(ctx, id, arg) {
  if (ctx.navigate) ctx.navigate(id, arg);
  else location.hash = `#${hashFor(id, arg)}`;
}

// A table row that opens a sector or sub-industry page when clicked.
function openRow(cells, ctx, key, title) {
  return el('tr', {
    class: 'sx-row',
    title,
    onclick: (event) => {
      if (!event.target.closest('a')) go(ctx, 'sectors', key);
    },
  }, cells);
}

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`.trim(), text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function strip(cells) {
  return el('div', { class: 'stat-strip sx-stats' }, cells);
}

// A table folded away until asked for: the page reads as charts first.
function fold(summary, body) {
  return el('details', { class: 'sx-fold' }, [el('summary', { text: summary }), body]);
}

// The period the tables' returns read: one switch, shared by the sub-industry
// table and the names table, so a period change keeps the reader's sort.
function periodControls(state, onPick) {
  return el('div', { class: 'sx-controls' }, [
    el('span', { class: 'dim', text: 'TABLE PERIOD' }),
    periodSwitch(PERIODS, state.period, (p) => {
      state.period = p;
      onPick();
    }),
  ]);
}

function crumbs(parts) {
  return el('nav', { class: 'sx-crumbs', 'aria-label': 'Breadcrumb' }, parts.flatMap((part, i) => [
    i ? el('span', { class: 'sx-sep', text: '›' }) : null,
    part.href ? link(part.label, part.href) : el('span', { class: 'sx-here', text: part.label, 'aria-current': 'page' }),
  ]));
}

function subLabelOf(data) {
  return Object.fromEntries((data.sub_industries || []).map((s) => [s.key, s.label]));
}

// A table whose headers carry a tooltip where a column needs its meaning spelled out.
function titledTable(headers, rows, titles = {}) {
  const wrap = table(headers, rows);
  wrap.querySelectorAll('th').forEach((th, i) => {
    if (titles[headers[i]]) th.title = titles[headers[i]];
  });
  return wrap;
}

// The forward P/E is the aggregate (market cap over consensus EPS, as an index
// is priced); P/E PCTL places the trailing P/E within its own ten years.
const HUB_TITLES = {
  'FWD P/E': 'aggregate NTM P/E: total market cap over total consensus EPS for the next twelve months',
  'P/E PCTL': 'where its trailing P/E sits within its own ten years of weekly readings',
};

// The evidence flags as tags, then the best and worst names over three months.
function flagsLine(row, extremes) {
  const flags = evidenceFlags(row.evidence).map((f) => tag(f.text, f.tone, f.title));
  const name = (label, pick) => (pick ? el('span', { class: 'sx-extreme' }, [
    el('span', { class: 'dim', text: `${label} 3M ` }),
    link(pick.ticker, tickerHref(pick.ticker)),
    ` ${signed(pick.return, 1, '%')}`,
  ]) : null);
  return el('div', { class: 'sx-flags' }, [...flags, name('BEST', extremes?.best), name('WORST', extremes?.worst)]);
}

// Financials' P/TBV, from the build's valuation figures where it has them.
function ptbvLine(row) {
  const v = row.valuation;
  if (!present(v?.ptbv_now)) return null;
  return el('div', { class: 'sx-flags' }, [
    el('span', { class: 'dim', text: 'P/TBV' }),
    el('span', { text: `${multiple(v.ptbv_now)} now · 10-year median ${multiple(v.ptbv_median_10y)}` }),
  ]);
}

// The three figures across the top of a sector or sub-industry page: the return
// against the index over the quarter and the year, and how many of its names sit
// above their 200-day average. The valuation and growth figures are in the
// VALUATION block beneath, each beside the benchmark's.
function headlineCells(row) {
  const vs3 = row.vs_index?.['3M'];
  const vsYtd = row.vs_index?.YTD;
  return [
    stat('VS S&P 500 · 3M', signed(vs3, 1, ' pp'), 'percentage points, this less the index', dirClass(vs3)),
    stat('VS S&P 500 · YTD', signed(vsYtd, 1, ' pp'), 'percentage points, this less the index', dirClass(vsYtd)),
    stat('ABOVE 200D', share(row.above_200d, 0), 'names above their 200-day average'),
  ];
}

function nextCell(m) {
  const next = m.next_report;
  if (!next?.date) return el('td', { class: 'dim', text: DASH });
  const label = timingLabel(next.timing);
  return el('td', { title: timingTitle(next.timing) }, [next.date, label ? el('span', { class: 'dim', text: ` ${label}` }) : null]);
}

function nameCell(key, m, period, subLabel) {
  switch (key) {
    case 'ticker': return el('td', {}, [link(m.ticker, tickerHref(m.ticker), 'sx-ticker')]);
    case 'name': return el('td', { class: 'wrap-cell', text: m.name || DASH });
    case 'sub': return el('td', {}, [link(subLabel[m.sub_key] || m.sub_key, sectorHref(m.sub_key))]);
    case 'weight': return el('td', { text: share(m.weight, 2) });
    case 'ret': return el('td', { class: dirClass(m.returns?.[period]), text: pct(m.returns?.[period], 1) });
    case 'y1': return el('td', { class: dirClass(m.returns?.['1Y']), text: pct(m.returns?.['1Y'], 1) });
    case 'high': return el('td', { class: dirClass(m.drawdown), text: pct(m.drawdown, 1) });
    case 'a200': return el('td', { class: markTone(m.above_200d), text: boolMark(m.above_200d) });
    case 'rev': return el('td', { class: dirClass(m.revision_90d), text: pct(m.revision_90d, 1) });
    case 'pe': return el('td', { text: multiple(m.forward_pe) });
    case 'pctl': return el('td', { class: 'dim', text: ordinal(m.pe_percentile) });
    case 'ptbv': return el('td', { text: multiple(m.ptbv) });
    case 'ptbvPctl': return el('td', { class: 'dim', text: ordinal(m.ptbv_percentile) });
    case 'next': return nextCell(m);
    case 'monitor': return el('td', {}, [m.monitor?.queued === true ? tag('QUEUED', 'warn', 'the monitor has queued this name') : DASH]);
    default: return el('td', {});
  }
}

// The names of a sector or a sub-industry, sortable by any column. The sort
// state lives with the page, so a period change keeps the reader's order.
function namesCard(members, state, { withSub, financials, subLabel, title }) {
  const wrap = el('div', { class: 'table-scroll' });
  const draw = () => {
    if (!members.length) {
      wrap.replaceChildren(el('div', { class: 'dim', text: 'No names.' }));
      return;
    }
    const cols = nameColumns(state.period, { withSub, financials, subLabel });
    if (!cols.some((c) => c.key === state.sort.key)) state.sort = { key: 'weight', direction: 'desc' };
    const col = cols.find((c) => c.key === state.sort.key);
    const head = el('tr', {}, cols.map((c) => {
      const active = state.sort.key === c.key;
      const arrow = active ? (state.sort.direction === 'desc' ? ' ▼' : ' ▲') : '';
      return el('th', { 'aria-sort': active ? (state.sort.direction === 'desc' ? 'descending' : 'ascending') : null }, [
        el('button', {
          type: 'button',
          class: 'sx-sort',
          text: c.label + arrow,
          onclick: () => {
            state.sort = { key: c.key, direction: active ? (state.sort.direction === 'desc' ? 'asc' : 'desc') : c.first };
            draw();
          },
        }),
      ]);
    }));
    const rows = sortRows(members, col.get, state.sort.direction).map((m) => el('tr', {},
      cols.map((c) => nameCell(c.key, m, state.period, subLabel))));
    wrap.replaceChildren(el('table', { class: 'data sx-names' }, [el('thead', {}, [head]), el('tbody', {}, rows)]));
  };
  draw();
  return {
    node: card(title, el('span', { class: 'dim', text: 'heaviest first · click a column to sort' }), [
      wrap,
      el('div', { class: 'field-note', text: 'A missing figure sits last whichever way the column runs. ✓ and ✗ are the names above and below their 200-day average.' }),
    ]),
    draw,
  };
}

function reportsCard(members, asOf) {
  const list = upcoming(members, asOf, REPORT_WINDOW_DAYS);
  const weeks = REPORT_WINDOW_DAYS / 7;
  const body = list.length
    ? table(['DATE', 'TICKER', 'TIMING', 'WEIGHT'], list.map((m) => el('tr', {}, [
      el('td', { text: m.next_report.date }),
      el('td', {}, [link(m.ticker, tickerHref(m.ticker), 'sx-ticker')]),
      el('td', { class: 'dim', title: timingTitle(m.next_report.timing), text: timingLabel(m.next_report.timing) || DASH }),
      el('td', { text: share(m.weight, 2) }),
    ])))
    : el('div', { class: 'field-note', text: `No member reports in the next ${weeks} weeks.` });
  return card(`REPORTS IN THE NEXT ${weeks} WEEKS`, el('span', { class: 'dim', text: `${list.length} names after ${asOf}` }), [body]);
}

// The sector's or sub-industry's THEMES group, drawn in full beneath the page.
async function industryData(host, themeKey, subThemes, ctx) {
  host.append(sectionTitle('INDUSTRY DATA', themeKey ? `from THEMES · ${themeKey.toUpperCase()}` : 'on sub-industry pages'));
  if (subThemes.length) {
    host.append(el('div', { class: 'sx-theme-line' }, [
      el('span', { class: 'dim', text: 'Industry data on sub-industry pages: ' }),
      ...subThemes.flatMap((s, i) => [
        i ? el('span', { class: 'dim', text: ' · ' }) : null,
        link(s.label, sectorHref(s.key)),
        ' → ',
        link(s.theme.toUpperCase(), themeHref(s.theme), 'tag tag-info'),
      ]),
    ]));
  }
  if (!themeKey) return;
  const body = el('div', {});
  host.append(body);
  try {
    const themes = await ctx.loadArtifact('themes');
    const blocks = themeBlocks(themeKey, themes, { title: false });
    body.replaceChildren(...(blocks.length ? blocks : [gap(`The THEMES page has no group called ${themeKey} in this build.`)]));
  } catch (error) {
    body.replaceChildren(gap(`Industry data is unavailable: ${error.message}.`));
  }
}

function sectorTable(data, state, ctx) {
  const period = state.period;
  const rows = sortRows(data.sectors, 'weight', 'desc').map((s) => {
    const ret = s.returns?.[period];
    const vs = s.vs_index?.[period];
    const q = quadrantTag(s.quadrant);
    const rev = s.revision || {};
    return openRow([
      el('td', {}, [el('span', { class: 'sx-name', text: s.label }), el('span', { class: 'sub', text: `${s.etf} · ${s.members} names` })]),
      el('td', { text: share(s.weight, 1) }),
      el('td', { class: dirClass(ret), text: pct(ret, 1) }),
      el('td', { class: dirClass(vs), text: signed(vs, 1, ' pp') }),
      el('td', {}, [q ? tag(q.label, q.tone) : DASH]),
      el('td', { text: share(s.above_200d, 0) }),
      el('td', { class: dirClass(s.median_drawdown), text: pct(s.median_drawdown, 1) }),
      el('td', { class: dirClass(rev['90d']), text: pct(rev['90d'], 1) }),
      el('td', { text: multiple(s.forward_pe) }),
      el('td', { class: 'dim', text: ordinal(s.pe_percentile) }),
      el('td', {}, [s.theme ? link(s.theme.toUpperCase(), themeHref(s.theme), 'tag tag-info') : DASH]),
    ], ctx, s.key, `${s.label} · ${s.members} names · ${share(s.weight)} of the index`);
  });
  return titledTable(['SECTOR', 'WEIGHT', 'RETURN', 'VS S&P', 'ROTATION', 'ABOVE 200D', 'MEDIAN DRAWDOWN', 'EPS REV 90D', 'FWD P/E', 'P/E PCTL', 'THEME'], rows, HUB_TITLES);
}

function subTable(subs, state, ctx) {
  const period = state.period;
  const rows = subs.map((s) => {
    const ret = s.returns?.[period];
    const vs = s.vs_index?.[period];
    const rev = s.revision || {};
    return openRow([
      el('td', {}, [link(s.label, sectorHref(s.key)), s.thin ? ' ' : null, s.thin ? tag('THIN', 'dim', THIN_TITLE) : null]),
      el('td', { text: String(s.members) }),
      el('td', { text: share(s.weight, 2) }),
      el('td', { class: dirClass(ret), text: pct(ret, 1) }),
      el('td', { class: dirClass(vs), text: signed(vs, 1, ' pp') }),
      el('td', { text: share(s.above_200d, 0) }),
      el('td', { class: dirClass(s.median_drawdown), text: pct(s.median_drawdown, 1) }),
      el('td', { class: dirClass(rev['90d']), text: pct(rev['90d'], 1) }),
      el('td', { text: multiple(s.forward_pe) }),
      el('td', { class: 'dim', text: ordinal(s.pe_percentile) }),
      el('td', {}, [s.theme ? link(s.theme.toUpperCase(), themeHref(s.theme), 'tag tag-info') : DASH]),
    ], ctx, s.key, `${s.label} · ${s.members} names`);
  });
  return titledTable(['SUB-INDUSTRY', 'NAMES', 'WEIGHT', 'RETURN', 'VS S&P', 'ABOVE 200D', 'MEDIAN DRAWDOWN', 'EPS REV 90D', 'FWD P/E', 'P/E PCTL', 'THEME'], rows, HUB_TITLES);
}

function hubNotes(data) {
  const noPe = data.sectors.filter((s) => !present(s.forward_pe)).map((s) => s.label);
  return [
    'Market, then sector, then sub-industry, then names. A sector is one SPDR fund\'s GICS group of the S&P 500; a row opens it, and each sector page opens its sub-industries and their names.',
    'Returns are cap-weighted from the names\' heat-map returns. VS S&P is the sector\'s return less the index\'s over the same period, in percentage points. A theme tag opens the THEMES page for that group.',
    'ABOVE 200D is the share of names above their 200-day average. MEDIAN DRAWDOWN is the median name\'s fall from its 1-year high. EPS REV 90D is the median change in FY1 EPS consensus over 90 days.',
    'FWD P/E is aggregate: total market cap over total consensus EPS for the next twelve months, as an index is priced. P/E PCTL is where the trailing P/E sits within its own ten years.',
    noPe.length ? `No forward P/E in this build for: ${noPe.join(', ')}.` : null,
    ...(data.notes || []),
  ];
}

function sectorNotes(sector) {
  return [
    'The relative line is the sector\'s basket against the S&P 500\'s, each cap-weighted from the names\' daily closes, rebased to 100 at the start of the window.',
    'FORWARD P/E is aggregate, as an index is priced: total market cap over total consensus EPS for the next twelve months. The VALUATION section\'s trailing P/E band marks the 25th to 75th percentile of its weekly readings over ten years, and its line the median.',
    'The sub-industry bars, the map and the names chart use the PERIOD chosen above. A sub-industry with no P/E percentile is not on the map.',
    'NEXT REPORT: BMO reports before the open, AMC after the close, TBC has a date but no confirmed time of day. QUEUED marks a name the monitor has queued.',
    present(sector.forward_pe) ? null : 'This sector has no forward P/E in this build.',
  ];
}

function subNotes(sub) {
  return [
    'The relative line is the sub-industry\'s basket against the S&P 500\'s, each cap-weighted from the names\' daily closes, rebased to 100 at the start of the window.',
    'FORWARD P/E is aggregate: total market cap over total consensus EPS for the next twelve months. The trailing P/E band marks the 25th to 75th percentile of its weekly readings over ten years, and its line the median. The valuation section sets it against its sector.',
    'A sub-industry with fewer than five names is thin, and its medians and P/E history move with any one name.',
    'NEXT REPORT: BMO reports before the open, AMC after the close, TBC has a date but no confirmed time of day. QUEUED marks a name the monitor has queued.',
    present(sub.forward_pe) ? null : 'This sub-industry has no forward P/E in this build.',
  ];
}

// --- Charts and their history -------------------------------------------------

// A page's own history file and the comparison's. Either may be missing in an
// older build: the charts then say so in one line rather than failing the page.
async function loadPage(ctx, key) {
  if (!key) return { page: null, error: 'it has no page of its own' };
  if (!ctx.loadArtifact) return { page: null, error: 'the page cannot load its history' };
  try {
    return { page: await ctx.loadArtifact(`sectors/${key}`), error: null };
  } catch (error) {
    return { page: null, error: error.message };
  }
}

// The one line a chart shows in place of itself, saying why its history is absent.
function missing(loaded, what) {
  return gap(loaded?.error ? `${what} is unavailable: ${loaded.error}.` : `${what} is not in this build.`);
}

function offLine(list, what) {
  return list.length ? el('div', { class: 'field-note', text: `${what}: ${list.join(', ')}.` }) : null;
}

// The window the reader last picked, if it is one the page knows.
function readWindow() {
  try {
    const saved = localStorage.getItem(WINDOW_KEY);
    return WINDOWS.includes(saved) ? saved : null;
  } catch {
    return null;
  }
}

function writeWindow(window) {
  try {
    localStorage.setItem(WINDOW_KEY, window);
  } catch {
    // Private windows keep nothing: the choice then lasts the visit only.
  }
}

// The basket against the S&P 500 over the window, rebased to 100 at its start,
// with the 100 line across: above it, the basket has led the index since then.
function relativeChart(node, relative, window) {
  if (!relative?.dates?.length || !Array.isArray(relative.basket)) return false;
  const cut = sliceWindow(relative.dates, { basket: relative.basket }, window, { basket: 'index' });
  render(node, (option, p) => ({
    ...option,
    xAxis: { ...option.xAxis, data: cut.dates },
    series: [{
      name: 'basket ÷ S&P 500', type: 'line', data: cut.series.basket, showSymbol: false,
      lineStyle: { width: 1.4, color: p.text }, itemStyle: { color: p.text },
      markLine: {
        silent: true, symbol: 'none', label: { show: false },
        lineStyle: { color: p.faint, type: 'dashed' }, data: [{ yAxis: 100 }],
      },
    }],
  }));
  return true;
}

// Sub-industries against the S&P 500 over the period, largest first: green at
// or above zero, red below. A click opens the sub-industry's page.
function subBarChart(node, rows, period, onPick) {
  node.style.height = `${Math.max(180, rows.length * 22 + 40)}px`;
  const chart = render(node, (option, p) => ({
    ...option,
    grid: { left: 150, right: 46, top: 4, bottom: 20 },
    tooltip: {
      ...option.tooltip,
      trigger: 'item',
      axisPointer: undefined,
      formatter: (q) => `<b>${rows[q.dataIndex].full}</b><br>${period} vs S&P 500 ${signed(rows[q.dataIndex].value, 1, ' pp')}`,
    },
    xAxis: { type: 'value', axisLabel: { color: p.dim, fontSize: 10 }, splitLine: { lineStyle: { color: p.border, opacity: 0.4 } } },
    yAxis: {
      type: 'category', inverse: true, data: rows.map((r) => r.label), triggerEvent: true,
      axisLabel: { color: p.dim, fontSize: 10, width: 140, overflow: 'truncate' },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar', barMaxWidth: 12,
      data: rows.map((r) => ({ value: r.value, itemStyle: { color: r.value >= 0 ? p.up : p.down, opacity: 0.85 } })),
      label: { show: true, position: 'right', color: p.dim, fontSize: 10, formatter: (q) => signed(q.value, 1) },
      markLine: { silent: true, symbol: 'none', data: [{ xAxis: 0 }], lineStyle: { color: p.faint }, label: { show: false } },
    }],
  }));
  chart?.on('click', (q) => {
    const index = q.componentType === 'yAxis' ? rows.findIndex((r) => r.label === q.value) : q.dataIndex;
    if (rows[index]) onPick(rows[index].key);
  });
}

// The valuation path: the P/E at four stages on one analyst basis, with each
// step's earnings growth written between the bars. The next twelve months is
// the highlighted bar.
function pathChart(node, bars) {
  const top = Math.max(1, ...bars.map((b) => (present(b.pe) ? b.pe : 0)));
  // Each stage's earnings growth on the stage before, under its label.
  const labels = bars.map((b) => (present(b.growth) ? `${b.label}\nEPS ${signed(b.growth, 0, '%')}` : b.label));
  render(node, (option, p) => ({
    ...option,
    grid: { left: 44, right: 16, top: 26, bottom: 40 },
    tooltip: {
      ...option.tooltip,
      trigger: 'item',
      axisPointer: undefined,
      formatter: (q) => {
        const b = bars[q.dataIndex];
        const growth = present(b.growth) ? `<br>earnings ${signed(b.growth, 1, '%')} on the stage before` : '';
        return `<b>${b.label}</b><br>P/E ${multiple(b.pe)}${growth}`;
      },
    },
    xAxis: {
      type: 'category', data: labels, boundaryGap: true,
      axisLabel: { color: p.dim, fontSize: 10, interval: 0 }, axisLine: { lineStyle: { color: p.border } }, axisTick: { show: false },
    },
    yAxis: {
      type: 'value', min: 0, max: Math.ceil((top * 1.25) / 5) * 5,
      axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => `${v}×` },
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: p.border, opacity: 0.4 } },
    },
    series: [{
      type: 'bar', barMaxWidth: 36,
      data: bars.map((b) => ({ value: b.pe, itemStyle: { color: b.ntm ? p.accent : p.faint, opacity: b.ntm ? 0.95 : 0.6 } })),
      label: {
        show: true, position: 'top', color: p.text, fontSize: 10,
        formatter: (q) => multiple(bars[q.dataIndex].pe),
      },
    }],
  }));
}

// A scatter of bubbles, each sized by its weight, with dashed lines through
// zero on x and the middle on y. `spec` gives the axes, labels and tooltip.
function bubbleChart(node, points, spec) {
  return render(node, (option, p) => {
    const axis = (range, name, nameGap) => ({
      type: 'value', min: range[0], max: range[1], name, nameLocation: 'middle', nameGap,
      nameTextStyle: { color: p.dim, fontSize: 10 },
      axisLabel: { color: p.dim, fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: p.border, opacity: 0.35 } },
    });
    return {
      ...option,
      grid: { left: 58, right: 26, top: 14, bottom: 42 },
      tooltip: { ...option.tooltip, trigger: 'item', axisPointer: undefined, formatter: (q) => spec.tip(points[q.dataIndex]) },
      graphic: (spec.captions || []).map((c) => ({
        type: 'text', ...c.at, style: { text: c.text, fill: p.faint, font: '10px ui-monospace, Menlo, monospace' },
      })),
      xAxis: axis(spec.xRange, spec.xName, 26),
      yAxis: axis(spec.yRange, spec.yName, 40),
      series: [{
        type: 'scatter',
        labelLayout: { moveOverlap: 'shiftY' },
        data: points.map((pt) => {
          const color = spec.colorOf(pt, p);
          return {
            value: [pt.x, pt.y],
            symbolSize: pt.size,
            itemStyle: { color, opacity: 0.72, borderColor: color, borderWidth: 1 },
            label: { show: spec.labelOf(pt), position: 'right', color: p.dim, fontSize: 10, formatter: () => pt.label },
          };
        }),
        markLine: {
          silent: true, symbol: 'none', label: { show: false },
          lineStyle: { color: p.faint, type: 'dashed' },
          data: [{ xAxis: 0 }, { yAxis: spec.yMid }],
        },
      }],
    };
  });
}

// The sub-industry map: where each sits against the index over the period, and
// where its P/E sits in its own ten years. A click opens its page.
function subMapChart(node, points, period, onPick) {
  const chart = bubbleChart(node, points, {
    xRange: symmetricRange(points.map((pt) => pt.x)),
    yRange: [0, 100],
    yMid: 50,
    xName: `${period} VS S&P 500, PERCENTAGE POINTS →`,
    yName: 'P/E PERCENTILE, OWN TEN YEARS →',
    labelOf: () => true,
    colorOf: (pt, p) => (pt.x >= 0 ? p.up : p.down),
    tip: (pt) => `<b>${pt.full}</b><br>${period} vs S&P 500 ${signed(pt.x, 1, ' pp')}`
      + `<br>P/E ${ordinal(pt.y)} percentile of its own ten years<br>${share(pt.weight, 2)} of the index`,
    captions: MAP_CAPTIONS,
  });
  chart?.on('click', (q) => {
    const pt = points[q.dataIndex];
    if (pt) onPick(pt.key);
  });
}

// The names: each one's return against the index over the period, and its
// 90-day EPS revision. The heaviest are labelled; a click opens its ticker page.
function namesChart(node, points, period) {
  const chart = bubbleChart(node, points, {
    xRange: symmetricRange(points.map((pt) => pt.x)),
    yRange: symmetricRange(points.map((pt) => pt.y)),
    yMid: 0,
    xName: `${period} RETURN LESS THE S&P 500, PERCENTAGE POINTS →`,
    yName: '90-DAY EPS REVISION, % →',
    labelOf: (pt) => pt.named,
    colorOf: (pt, p) => (pt.x >= 0 ? p.up : p.down),
    tip: (pt) => `<b>${pt.ticker}</b> ${pt.full}<br>${period} ${signed(pt.x, 1, ' pp')} vs S&P 500`
      + `<br>90-day EPS revision ${pct(pt.y, 1)}<br>${share(pt.weight, 2)} of the index`,
  });
  chart?.on('click', (q) => {
    const pt = points[q.dataIndex];
    if (pt) location.hash = tickerHref(pt.ticker);
  });
}

// The period switch and the window switch that drive every chart on a page.
function controlBar(chart, dates, onChange) {
  return el('div', { class: 'sx-controls' }, [
    el('span', { class: 'dim', text: 'WINDOW' }),
    windowSwitch(dates, chart.window, (w) => {
      chart.window = w;
      writeWindow(w);
      onChange();
    }),
    el('span', { class: 'dim', text: 'PERIOD' }),
    periodSwitch(CHART_PERIODS, chart.period, (p) => {
      chart.period = p;
      onChange();
    }),
  ]);
}

// A sector or a sub-industry page, the same at both levels: the market-relative
// line and the valuation charts first, the sub-industry map and the names
// chart, then the tables folded away.
async function renderLevel(root, data, ctx, row, isSector) {
  const sector = isSector ? row : (data.sectors.find((s) => s.key === row.sector_key) || null);
  const sectorLabel = sector?.label || row.sector || '';
  const subs = isSector ? subsOf(data, row.key) : [];
  const members = isSector ? membersOf(data, { sectorKey: row.key }) : membersOf(data, { subKey: row.key });
  const subLabel = subLabelOf(data);
  const financials = isSector ? row.key === 'XLF' : row.sector_key === 'XLF';
  const [own, other] = await Promise.all([
    loadPage(ctx, row.key),
    loadPage(ctx, isSector ? 'MARKET' : row.sector_key),
  ]);
  const ownLabel = isSector ? sectorShort(row.label) : shortName(row.label, 24);
  const otherLabel = isSector ? 'S&P 500' : sectorShort(sectorLabel);
  const dates = longestDates(own.page?.relative?.dates, own.page?.valuation?.dates);
  const chart = { window: pickWindow(dates, readWindow() || DEFAULT_WINDOW), period: DEFAULT_CHART_PERIOD };
  const tables = { period: DEFAULT_PERIOD, sort: { key: 'weight', direction: 'desc' } };

  const slots = {
    relative: slot(), bars: slot(), path: slot(), map: slot(), names: slot(),
  };
  const nodes = {
    relative: chartNode(), bars: chartNode(), path: chartNode(), map: chartNode(), names: chartNode(),
  };

  const drawRelative = () => {
    const drawn = relativeChart(nodes.relative, own.page?.relative, chart.window);
    slots.relative.replaceChildren(card(`${ownLabel.toUpperCase()} ÷ S&P 500 · ${chart.window}`,
      el('span', { class: 'dim', text: '=100 at the window\'s start' }),
      [drawn ? nodes.relative : missing(own, 'The relative line')]));
  };

  const drawBars = () => {
    const rows = subBars(subs, chart.period);
    slots.bars.replaceChildren(card(`SUB-INDUSTRIES · ${chart.period} VS S&P 500`,
      el('span', { class: 'dim', text: 'pp · click a bar for its page' }),
      [rows.length ? nodes.bars : gap('No sub-industry has a return for this period.')]));
    if (rows.length) subBarChart(nodes.bars, rows, chart.period, (key) => go(ctx, 'sectors', key));
  };

  const drawPath = () => {
    const bars = pathBars(row.path);
    const cover = row.path ? [
      present(row.path.companies) ? `${row.path.companies} companies` : null,
      present(row.path.coverage) ? `${num(row.path.coverage * 100, 0)}% of cap` : null,
    ].filter(Boolean).join(' · ') : '';
    slots.path.replaceChildren(card('VALUATION PATH · CONSENSUS', cover ? el('span', { class: 'dim', text: cover }) : null,
      [bars.length ? nodes.path : gap(`${row.label}: no valuation path in this build.`)]));
    if (bars.length) pathChart(nodes.path, bars);
  };

  const drawMap = () => {
    const { points, off } = subMapPoints(subs, chart.period);
    slots.map.replaceChildren(card(`SUB-INDUSTRIES · ${chart.period} VS S&P 500, AGAINST THEIR OWN P/E`,
      el('span', { class: 'dim', text: 'bubble ~ weight · click for its page' }),
      [points.length ? nodes.map : gap('No sub-industry has both a return and a P/E percentile for this period.'),
        offLine(off, 'not on the map')]));
    if (points.length) subMapChart(nodes.map, points, chart.period, (key) => go(ctx, 'sectors', key));
  };

  const drawNames = () => {
    const bench = data.benchmark?.returns?.[chart.period];
    const { points, off } = nameMapPoints(members, chart.period, bench);
    let empty = 'No name has both a return and a 90-day revision for this period.';
    if (!present(bench)) empty = 'The S&P 500 has no return for this period.';
    slots.names.replaceChildren(card(`NAMES · ${chart.period} VS S&P 500, AND 90-DAY EPS REVISIONS`,
      el('span', { class: 'dim', text: `bubble ~ weight · the ${NAMED_LIMIT} heaviest labelled · click for its page` }),
      [points.length ? nodes.names : gap(empty), offLine(off, 'not on the map')]));
    if (points.length) namesChart(nodes.names, points, chart.period);
  };

  const subsHost = el('div');
  const drawSubs = () => subsHost.replaceChildren(subTable(subs, tables, ctx));
  const names = namesCard(members, tables, {
    withSub: isSector, financials, subLabel: isSector ? subLabel : {}, title: `NAMES · ${members.length}`,
  });
  const redrawTables = () => {
    drawSubs();
    names.draw();
  };
  const redraw = () => {
    drawRelative();
    if (isSector) drawBars();
    drawPath();
    if (isSector) drawMap();
    drawNames();
  };
  redrawTables();

  // The valuation block does not follow the window switch: it covers every
  // window itself, so it is built once. Its charts draw on a microtask, which
  // runs after the synchronous append below has put them in the page. A page
  // whose history failed to load says so in one line; a page that merely lacks
  // a part shows a dash or a gap line for it inside the block.
  const valuation = own.error
    ? [gap(`${row.label}'s history is unavailable: ${own.error}.`)]
    : [
      ...valuationBlock({
        name: ownLabel, benchmark: otherLabel, title: '2 · VALUATION',
        own: pageValuation(own.page), other: pageValuation(other.page),
      }),
      other.error ? gap(`${otherLabel}'s history is unavailable: ${other.error}.`) : null,
    ].filter(Boolean);

  const meta = isSector
    ? `AS OF ${data.as_of} · ${subs.length} SUB-INDUSTRIES, ${subs.filter((s) => s.thin).length} THIN`
    : `AS OF ${data.as_of} · ${row.key} · ${row.members} names in this sub-industry`;
  const extremes = isSector ? { best: row.best, worst: row.worst } : (members.length > 1 ? extremesOf(members, '3M') : null);
  const folds = [];
  if (isSector) folds.push(fold(`SUB-INDUSTRY TABLE · ${subs.length}`, subsHost));
  folds.push(fold(`NAME TABLE · ${members.length}`, names.node));
  folds.push(fold(`REPORTS AHEAD · ${upcoming(members, data.as_of).length}`, reportsCard(members, data.as_of)));

  const crumbParts = isSector
    ? [{ label: 'SECTORS', href: '#sectors' }, { label: row.label }]
    : [{ label: 'SECTORS', href: '#sectors' }, { label: sectorLabel, href: sectorHref(row.sector_key) }, { label: row.label }];
  const subtitle = isSector
    ? `${row.etf} · ${share(row.weight, 2)} OF THE S&P 500 · ${row.members} NAMES`
    : `${sectorLabel} · ${share(row.weight, 2)} OF THE S&P 500 · ${row.members} NAMES`;

  // A null child (a line that does not apply) is dropped here: the DOM would
  // otherwise print it as the word "null".
  const parts = [
    crumbs(crumbParts),
    sectionTitle(row.label.toUpperCase(), subtitle),
    metaRow(meta, isSector ? sectorNotes(row) : subNotes(row)),
    strip(headlineCells(row)),
    flagsLine(row, extremes),
    ptbvLine(row),
    !isSector && row.thin ? el('div', { class: 'sx-flags' }, [tag('THIN', 'warn', THIN_TITLE), el('span', { class: 'dim', text: THIN_TITLE })]) : null,
    sectionTitle('1 · AGAINST THE MARKET', isSector ? 'the basket against the S&P 500, and the sub-industries against it' : 'the basket against the S&P 500'),
    controlBar(chart, dates, redraw),
    isSector ? el('div', { class: 'grid two' }, [slots.relative, slots.bars]) : slots.relative,
    ...valuation,
    slots.path,
    ...(isSector ? [sectionTitle('3 · INSIDE THE SECTOR', 'sub-industries: excess return against their own P/E'), slots.map] : []),
    sectionTitle(`${isSector ? 4 : 3} · NAMES`, 'return against the S&P 500 and the 90-day EPS revision'),
    slots.names,
    sectionTitle('TABLES', 'the figures behind the charts, folded away'),
    periodControls(tables, redrawTables),
    ...folds,
  ];
  root.append(...parts.filter(Boolean));
  requestAnimationFrame(redraw);

  const subThemes = isSector ? themedSubs(data, row.key) : [];
  if (row.theme || subThemes.length) {
    const section = el('div', { class: 'sx-industry' });
    root.append(section);
    await industryData(section, row.theme, subThemes, ctx);
  }
}

// --- The market hub ----------------------------------------------------------

// The market: where money is rotating first, then every sector in one table,
// the cross-sector themes, and the industry scorecard and sector valuation.
async function renderHub(root, data, _manifest, ctx) {
  const state = { period: DEFAULT_PERIOD, sort: { key: 'weight', direction: 'desc' } };
  const thin = data.sub_industries.filter((s) => s.thin).length;
  // The rotation graph's charts draw on the next frame, so its host must be
  // in the page before it renders. Its per-sector drill-down is left out: the
  // sector pages open from the table below.
  const rotationHost = el('div', { class: 'sectors-rotation' });
  root.append(rotationHost);
  try {
    renderRotationGraph(rotationHost, await ctx.loadArtifact('rotation'), { drill: false });
  } catch (error) {
    rotationHost.replaceChildren(gap(`The rotation graph is unavailable: ${error.message}.`));
  }

  root.append(sectionTitle('SECTORS', 'MARKET → SECTOR → SUB-INDUSTRY → NAMES'));
  root.append(metaRow(`AS OF ${data.as_of} · ${data.sectors.length} SECTORS · ${data.sub_industries.length} SUB-INDUSTRIES, ${thin} THIN · ${data.members.length} NAMES`, hubNotes(data)));

  const tableHost = el('div');
  const draw = () => tableHost.replaceChildren(sectorTable(data, state, ctx));
  root.append(card(`${data.sectors.length} SECTORS`, periodSwitch(PERIODS, state.period, (p) => {
    state.period = p;
    draw();
  }), [tableHost]));
  draw();

  if ((data.themes || []).length) {
    root.append(card('CROSS-SECTOR THEMES', el('span', { class: 'dim', text: `${data.themes.length} · not one sector` }), [
      el('div', { class: 'field-note', text: 'A theme that spans sectors: its names also appear on their own sector pages.' }),
      ...data.themes.map((t) => el('div', { class: 'sx-theme' }, [
        el('div', { class: 'sx-theme-head' }, [
          link(t.label, themeHref(t.key), 'sx-theme-name'),
          t.proxy ? el('span', { class: 'dim', text: t.proxy }) : null,
        ]),
        el('div', { class: 'tag-row' }, (t.members || []).map((sym) => link(sym, tickerHref(sym), 'tag tag-dim'))),
      ])),
    ]));
  }

  const detailHost = el('div', { class: 'sectors-detail' });
  root.append(detailHost);
  await renderRotationDetail(detailHost, ctx);
}

export default async function renderSectors(root, data, manifest, ctx = {}) {
  if (!data || !Array.isArray(data.sectors) || !Array.isArray(data.members) || !Array.isArray(data.sub_industries)) {
    root.append(gap('No sector data in this build. Run the refresh command to rebuild it.'));
    return;
  }
  const found = levelOf(ctx.arg, data);
  if (found.level === 'sector') return renderLevel(root, data, ctx, found.sector, true);
  if (found.level === 'sub') return renderLevel(root, data, ctx, found.sub, false);
  if (found.level === 'unknown') {
    root.append(gap(`There is no sector or sub-industry called ${ctx.arg} in this build. The sectors are below.`));
  }
  return renderHub(root, data, manifest, ctx);
}
