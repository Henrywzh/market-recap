// VALUATION & QUALITY: every index member from its own filings and the close.
//
// Colour is a within-sector rank, not an absolute judgement: a utility's P/E
// is compared with other utilities, never with software. The top fifth by the
// metric's own "better" direction is green, the bottom fifth red.

import { el, card, table, num, sectionTitle, notice, metaRow, DASH } from '../fmt.js';
import { render, SERIES_COLORS } from '../charts.js';

const BILLION = 1e9;
const HISTORY_BASE = 'artifacts/valuation';
// Share of a sector, from each end, that is coloured.
const TAIL_SHARE = 0.2;
// Scatter axes stop at these percentiles so a handful of extreme multiples
// (a P/E of 900 on near-zero earnings) do not flatten everything else; at
// the 98th, EV/EBITDA's axis ran to 165x and the market sat in its first fifth.
const AXIS_PERCENTILES = [0.05, 0.95];
const ALL = '';

function format(value, unit) {
  if (value === null || value === undefined) return DASH;
  if (unit === 'x') return `${num(value, 1)}x`;
  if (unit === 'pct') return `${num(value, 1)}%`;
  if (unit === 'pp') return num(value, 1);
  if (unit === 'score') return num(value, 0);
  return num(value, 2);
}

function quantile(sorted, q) {
  if (!sorted.length) return null;
  const position = (sorted.length - 1) * q;
  const low = Math.floor(position);
  const high = Math.ceil(position);
  return sorted[low] + (sorted[high] - sorted[low]) * (position - low);
}

const median = (values) => quantile([...values].sort((a, b) => a - b), 0.5);
const present = (v) => v !== null && v !== undefined;

// Within-sector percentile of each row's value, oriented so 1 is "better".
function sectorRanks(rows, metrics) {
  const ranks = new Map(rows.map((r) => [r, {}]));
  const bySector = Map.groupBy ? Map.groupBy(rows, (r) => r.sector) : groupBy(rows, (r) => r.sector);
  for (const members of bySector.values()) {
    for (const metric of metrics) {
      const valued = members.filter((r) => present(r[metric.key]));
      const sorted = valued.map((r) => r[metric.key]).sort((a, b) => a - b);
      for (const row of valued) {
        const below = sorted.filter((v) => v < row[metric.key]).length;
        const share = sorted.length > 1 ? below / (sorted.length - 1) : 0.5;
        ranks.get(row)[metric.key] = metric.better === 'high' ? share : 1 - share;
      }
    }
  }
  return ranks;
}

function groupBy(items, key) {
  const out = new Map();
  for (const item of items) {
    const k = key(item);
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(item);
  }
  return out;
}

function rankClass(rank) {
  if (rank === undefined) return '';
  if (rank >= 1 - TAIL_SHARE) return 'up';
  if (rank <= TAIL_SHARE) return 'down';
  return '';
}

function rowNote(row, data) {
  const parts = [
    `${row.name || row.ticker} · data to ${row.period_end} (filed ${row.filed})`,
    `shares: ${row.shares_basis}`,
    `debt: ${row.debt_basis}`,
  ];
  if (row.lagged.length) parts.push(`from the prior quarter (not tagged in the latest 10-Q): ${row.lagged.join(', ')}`);
  if (row.sector === data.financials_sector) parts.push('Financials: EV, gross-profit, FCF and accrual metrics not computed');
  if (row.piotroski === null && row.piotroski_tested) parts.push(`Piotroski: ${row.piotroski_tested} of 9 signals testable`);
  return parts.join('\n');
}

function scatter(node, rows, xMetric, yMetric) {
  const points = rows.filter((r) => present(r[xMetric.key]) && present(r[yMetric.key]));
  const bounds = (key) => {
    const sorted = points.map((r) => r[key]).sort((a, b) => a - b);
    const [low, high] = AXIS_PERCENTILES.map((q) => quantile(sorted, q));
    // Out to a round number either side, so the axis labels are readable.
    const step = 10 ** Math.floor(Math.log10(Math.max(Math.abs(high - low), 1e-9)));
    return [Math.floor(low / step) * step, Math.ceil(high / step) * step];
  };
  const [xMin, xMax] = bounds(xMetric.key);
  const [yMin, yMax] = bounds(yMetric.key);
  const outside = points.filter((r) => r[xMetric.key] < xMin || r[xMetric.key] > xMax
    || r[yMetric.key] < yMin || r[yMetric.key] > yMax).length;
  const sectors = [...new Set(points.map((r) => r.sector))].sort();
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 60, bottom: 70 },
    legend: { bottom: 0, type: 'scroll', textStyle: { color: p.dim, fontSize: 10 }, itemWidth: 9, itemHeight: 9 },
    tooltip: {
      ...option.tooltip,
      trigger: 'item',
      formatter: (item) => {
        const row = item.data.row;
        return `<b>${row.ticker}</b> ${row.name || ''}<br>${row.sector}<br>`
          + `${xMetric.label}: ${format(row[xMetric.key], xMetric.unit)}<br>`
          + `${yMetric.label}: ${format(row[yMetric.key], yMetric.unit)}`;
      },
    },
    xAxis: { ...option.xAxis, type: 'value', boundaryGap: false, min: xMin, max: xMax, scale: true,
      name: xMetric.label, nameLocation: 'middle', nameGap: 26, nameTextStyle: { color: p.dim, fontSize: 10 },
      splitLine: { lineStyle: { color: p.border, opacity: 0.35 } } },
    yAxis: { ...option.yAxis, min: yMin, max: yMax,
      name: yMetric.label, nameLocation: 'middle', nameGap: 44, nameTextStyle: { color: p.dim, fontSize: 10 } },
    series: sectors.map((sector, i) => ({
      name: sector,
      type: 'scatter',
      symbolSize: 6,
      itemStyle: { color: SERIES_COLORS[i % SERIES_COLORS.length], opacity: 0.8 },
      data: points.filter((r) => r.sector === sector).map((r) => ({ value: [r[xMetric.key], r[yMetric.key]], row: r })),
    })),
  }));
  return { shown: points.length - outside, outside, total: points.length };
}

// ------------------------------------------------------------ P/E history

async function loadHistory(symbol) {
  const response = await fetch(`${HISTORY_BASE}/${symbol}.json`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`${symbol} has no P/E history in this build (a loss, too little history, or no EPS filed)`);
  return response.json();
}

// `cap` stops the axis where a year of near-zero group earnings would
// otherwise stretch it to hundreds and flatten the decade into a line.
function historyChart(node, history, { cap = null } = {}) {
  const s = history.stats;
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, right: 60, bottom: 30 },
    xAxis: { ...option.xAxis, data: history.dates },
    yAxis: { ...option.yAxis, max: cap ? Math.ceil(cap) : undefined, axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => `${v}x` } },
    series: [{
      name: 'P/E', type: 'line', data: history.pe, showSymbol: false, connectNulls: false,
      lineStyle: { width: 1.4, color: p.text },
      markArea: { silent: true, itemStyle: { color: 'rgba(232,163,61,0.12)' },
        data: [[{ yAxis: s.p25 }, { yAxis: s.p75 }]] },
      markLine: {
        silent: true, symbol: 'none',
        label: { color: p.dim, fontSize: 10, position: 'end', formatter: (d) => d.name },
        data: [
          { name: `median ${num(s.median, 1)}x`, yAxis: s.median, lineStyle: { color: p.accent, type: 'dashed' } },
          { name: `p10 ${num(s.p10, 1)}x`, yAxis: s.p10, lineStyle: { color: p.faint, type: 'dotted' } },
          { name: `p90 ${num(s.p90, 1)}x`, yAxis: s.p90, lineStyle: { color: p.faint, type: 'dotted' } },
        ],
      },
    }],
  }));
}

// Axis top for an index or sector decade, as a multiple of its 90th percentile.
const AGGREGATE_AXIS_CAP = 1.6;
const SECTOR_SHORT = {
  'Communication Services': 'Comm Services',
  'Consumer Discretionary': 'Cons Discretionary',
  'Consumer Staples': 'Cons Staples',
  'Information Technology': 'Info Tech',
};

// Where each index and sector P/E sits in its own ten years, most expensive
// on top; a click draws that group's decade beside it.
function percentileChart(node, series, selected, onPick) {
  const shown = series.filter((s) => s.stats && s.stats.percentile !== null)
    .sort((a, b) => a.stats.percentile - b.stats.percentile);
  const chart = render(node, (option, p) => ({
    ...option,
    grid: { left: 124, right: 92, top: 6, bottom: 24 },
    tooltip: {
      ...option.tooltip,
      trigger: 'item',
      axisPointer: undefined,
      formatter: (q) => {
        const s = shown[q.dataIndex];
        return `<b>${s.label}</b> · ${s.companies} companies<br>P/E ${num(s.stats.current, 1)}x · 10Y median ${num(s.stats.median, 1)}x`
          + `<br>${num(s.stats.percentile, 0)}th percentile of its own ten years`;
      },
    },
    xAxis: {
      type: 'value', min: 0, max: 100, interval: 25,
      axisLabel: { color: p.dim, fontSize: 10, formatter: '{value}' },
      splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
    },
    yAxis: {
      type: 'category',
      // Labels answer clicks too: a bar at the 1st percentile is too short to hit.
      triggerEvent: true,
      data: shown.map((s) => SECTOR_SHORT[s.label] || s.label),
      axisLabel: {
        fontSize: 10,
        color: (value, index) => (shown[index]?.kind === 'index' ? p.text : p.dim),
        fontWeight: (value, index) => (shown[index]?.kind === 'index' ? 'bold' : 'normal'),
      },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 13,
      data: shown.map((s) => {
        const pct = s.stats.percentile;
        const color = s.kind === 'index' ? p.blue : pct >= 80 ? p.down : pct <= 20 ? p.up : p.accent;
        return {
          value: Math.round(pct),
          itemStyle: { color, opacity: s.key === selected ? 1 : 0.7, borderColor: s.key === selected ? p.text : color, borderWidth: s.key === selected ? 1 : 0 },
        };
      }),
      label: {
        show: true, position: 'right', color: p.dim, fontSize: 10,
        formatter: (q) => `${num(shown[q.dataIndex].stats.current, 1)}x · ${q.value}th`,
      },
      markLine: {
        silent: true, symbol: 'none',
        data: [{ xAxis: 50 }],
        lineStyle: { color: p.faint, type: 'dashed' },
        label: { show: false },
      },
    }],
  }));
  chart?.on('click', (q) => {
    const index = q.componentType === 'yAxis'
      ? shown.findIndex((s) => (SECTOR_SHORT[s.label] || s.label) === q.value)
      : q.dataIndex;
    if (shown[index]) onPick(shown[index].key);
  });
}

function aggregateSection(data) {
  const agg = data.aggregates;
  if (!agg || !agg.series?.length) return null;
  const primary = agg.series.find((s) => s.kind === 'index') || agg.series[0];
  let selected = primary.key;
  const barsNode = el('div', { class: 'chart tall' });
  const lineNode = el('div', { class: 'chart tall' });
  const lineTitle = el('span', { class: 'dim' });
  const stats = el('div', { class: 'stat-strip val-agg-stats' });
  const stat = (label, value, note, cls = '') => el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
  const draw = () => {
    const s = agg.series.find((x) => x.key === selected);
    percentileChart(barsNode, agg.series, selected, (key) => { selected = key; draw(); });
    lineTitle.textContent = `${s.label} · ${s.companies} companies · weekly`;
    if (s.stats) {
      const cap = s.stats.max > s.stats.p90 * AGGREGATE_AXIS_CAP ? s.stats.p90 * AGGREGATE_AXIS_CAP : null;
      historyChart(lineNode, { dates: agg.dates, pe: s.pe, stats: s.stats }, { cap });
    }
    const st = s.stats || {};
    stats.replaceChildren(
      stat('P/E (TTM)', present(st.current) ? `${num(st.current, 1)}x` : DASH, s.label),
      stat('OWN 10Y PERCENTILE', present(st.percentile) ? `${num(st.percentile, 0)}th` : DASH, `range ${num(st.min, 1)}x – ${num(st.max, 1)}x`,
        st.percentile >= 80 ? 'down' : st.percentile <= 20 ? 'up' : ''),
      stat('VS 10Y MEDIAN', present(st.vs_median) ? `${st.vs_median > 0 ? '+' : ''}${num(st.vs_median, 0)}%` : DASH, `median ${num(st.median, 1)}x · IQR ${num(st.p25, 1)}–${num(st.p75, 1)}x`),
      stat('COVERAGE', present(s.coverage) ? `${num(s.coverage * 100, 0)}%` : DASH, 'of its market cap with filed EPS'),
    );
  };
  const section = el('div', { class: 'grid two val-agg' }, [
    card('P/E VS OWN 10 YEARS · INDICES & SECTORS', el('span', { class: 'dim', text: 'percentile · red ≥ 80th · green ≤ 20th · click to chart' }), [barsNode]),
    card('P/E · 10 YEARS', lineTitle, [stats, lineNode]),
  ]);
  requestAnimationFrame(draw);
  return section;
}

function epsChart(node, history) {
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, top: 10, bottom: 24 },
    xAxis: { ...option.xAxis, data: history.eps.map((e) => e.filed) },
    series: [{ name: 'TTM EPS', type: 'line', step: 'end', data: history.eps.map((e) => e.eps),
      showSymbol: false, lineStyle: { width: 1.2, color: p.blue } }],
  }));
}

function historyTable(history) {
  const s = history.stats;
  const rows = [
    ['Current P/E', s.current === null ? 'n/m (loss)' : `${num(s.current, 1)}x`],
    ['Percentile in own 10 years', s.percentile === null ? DASH : `${num(s.percentile, 0)}th`],
    ['vs 10-year median', s.vs_median === null ? DASH : `${s.vs_median > 0 ? '+' : ''}${num(s.vs_median, 0)}%`],
    ['Median · 25th–75th', `${num(s.median, 1)}x · ${num(s.p25, 1)}–${num(s.p75, 1)}x`],
    ['10th–90th · min–max', `${num(s.p10, 1)}–${num(s.p90, 1)}x · ${num(s.min, 1)}–${num(s.max, 1)}x`],
    ['Sessions with positive earnings', `${s.sessions} since ${s.first}`],
  ];
  return table(['', ''], rows.map(([a, b]) => el('tr', {}, [el('td', { class: 'dim', text: a }), el('td', { text: b })])));
}

function sectorTable(rows, metrics) {
  const sectors = [...groupBy(rows, (r) => r.sector).entries()].sort((a, b) => b[1].length - a[1].length);
  const body = sectors.map(([sector, members]) => el('tr', {}, [
    el('td', { text: sector }),
    el('td', { class: 'dim', text: members.length }),
    ...metrics.map((m) => {
      const values = members.map((r) => r[m.key]).filter(present);
      return el('td', { text: values.length ? format(median(values), m.unit) : DASH });
    }),
  ]));
  return table(['SECTOR (MEDIAN)', 'N', ...metrics.map((m) => m.label.toUpperCase())], body);
}

function mainTable(rows, metrics, data, sort, onSort, onPick) {
  const ranks = sectorRanks(rows, metrics);
  const columns = [
    { key: 'ticker', label: 'TICKER' },
    { key: 'sector', label: 'SECTOR' },
    { key: 'market_cap', label: 'MKT CAP $B' },
    ...metrics.map((m) => ({ key: m.key, label: m.label.toUpperCase(), metric: m })),
    { key: 'period_end', label: 'DATA TO' },
  ];
  const sorted = [...rows].sort((a, b) => {
    const av = a[sort.key];
    const bv = b[sort.key];
    if (!present(av) && !present(bv)) return 0;
    if (!present(av)) return 1;
    if (!present(bv)) return -1;
    const order = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
    return sort.descending ? -order : order;
  });
  const head = el('tr', {}, columns.map((c) => el('th', {
    text: c.label + (sort.key === c.key ? (sort.descending ? ' ▼' : ' ▲') : ''),
    style: 'cursor:pointer',
    onclick: () => onSort(c.key),
  })));
  const body = sorted.map((row) => el('tr', {}, columns.map((c) => {
    if (c.key === 'ticker') {
      // The ticker draws its P/E history above; the arrow opens its ticker page.
      return el('td', {}, [
        el('span', { text: row.ticker, title: rowNote(row, data), style: 'cursor:pointer;text-decoration:underline dotted', onclick: () => onPick(row.ticker) }),
        ' ',
        el('a', { href: `#ticker/${encodeURIComponent(row.ticker)}`, class: 'dim', title: `${row.ticker} ticker page`, text: '↗' }),
      ]);
    }
    if (c.key === 'sector') return el('td', { class: 'dim', text: row.sector || DASH });
    if (c.key === 'market_cap') return el('td', { text: present(row.market_cap) ? num(row.market_cap / BILLION, 1) : DASH });
    if (c.key === 'period_end') return el('td', { class: 'dim', text: row.period_end + (row.lagged.length ? '*' : '') });
    const rank = ranks.get(row)[c.key];
    return el('td', { class: rankClass(rank), text: format(row[c.key], c.metric.unit) });
  })));
  const node = el('table', { class: 'data' }, [el('thead', {}, head), el('tbody', {}, body)]);
  return el('div', { class: 'table-scroll' }, node);
}

// One company's P/E against its own ten years into `host`. Returns a one-line
// status; throws when the company has no P/E history in this build.
export async function renderPeHistory(host, symbol, data) {
  const history = await loadHistory(symbol);
  const historyNode = el('div', { class: 'chart tall' });
  const epsNode = el('div', { class: 'chart short' });
  const historyStats = historyTable(history);
  host.replaceChildren(
    el('div', { class: 'grid two' }, [
      el('div', {}, [historyNode]),
      el('div', {}, [historyStats, el('div', { class: 'card-title', text: 'TTM DILUTED EPS, TODAY\'S SHARE BASIS, BY FILING DATE' }), epsNode]),
    ]),
    el('div', { class: 'note-text', text:
      `Each session's P/E is the split-adjusted close (not dividend-adjusted) over the TTM diluted EPS `
      + `public by then: every quarter is built only from filings made by the day it was first reported, `
      + `so the history never uses a number before it was published. A loss leaves a gap; an EPS with no `
      + `successor for two quarters expires rather than being carried forward. Band: 25th–75th percentile. `
      + `The table's P/E (market cap / net income) and this one (price / EPS) disagree by more than `
      + `${Math.round(data.pe_history.agreement_tolerance * 100)}% for ${data.pe_history.disagree.length} companies`
      + (data.pe_history.disagree.length ? ` (${data.pe_history.disagree.join(', ')}) — usually a merger or spin-off `
        + 'moving the share count, preferred dividends, or a large minority interest' : '')
      + '.' }),
  );
  historyChart(historyNode, history);
  epsChart(epsNode, history);
  const row = data.rows.find((r) => r.ticker === symbol);
  return `${row?.name || symbol} · weekly, ${history.dates[0]} → ${history.dates[history.dates.length - 1]}`;
}

export default async function renderValuation(root, data, _manifest, ctx = {}) {
  root.append(sectionTitle('VALUATION & QUALITY', 'FILED FUNDAMENTALS × CLOSING PRICE'));
  if (!data.rows || !data.rows.length) {
    root.append(el('div', { class: 'gap', text: 'No companies were valued in this build. Run the refresh command without --skip-sec.' }));
    return;
  }
  const agg = data.aggregates;
  root.append(metaRow(`AS OF ${data.as_of} · ${data.rows.length} COMPANIES FROM THEIR OWN FILINGS`, [
    agg ? `INDEX & SECTOR P/E: total market cap over total TTM diluted earnings, each company's EPS as filed at the time (split-adjusted close over the TTM EPS public that day). Losses count, as in an index's own P/E. `
      + `Each company is held at today's share count, one listing per company: its own P/E is exact on every date, but the weights between companies are today's, and the members are today's -- a company that has left the index is not in its past. `
      + `A week is drawn only when companies with an EPS in force hold at least ${num(agg.min_coverage * 100, 0)}% of the group's priced market cap. `
      + `When a group's total earnings approach zero (Energy through 2016's losses, Utilities in 2019–20, most sectors on 2020's earnings in early 2021) its P/E runs into the hundreds; the chart's axis stops at ${AGGREGATE_AXIS_CAP}x the group's 90th percentile, and the range in the stats is the true one. `
      + 'An EPS more than twice the share price either way is taken as a units error in the filing and left out. '
      + 'This is trailing GAAP, not FactSet\'s forward operating P/E (on EARNINGS), so it runs higher and moves more around recessions. Percentile and band are over the last ten years of sessions.' : null,
  ]));
  const aggregates = aggregateSection(data);
  if (aggregates) root.append(aggregates);

  const metrics = data.metrics;
  const valuationMetrics = metrics.filter((m) => m.group === 'valuation');
  const qualityMetrics = metrics.filter((m) => m.group === 'quality');
  const byKey = new Map(metrics.map((m) => [m.key, m]));

  const select = (options, value) => {
    const node = el('select', {}, options.map(([v, label]) => el('option', { value: v, text: label })));
    node.value = value;
    return node;
  };
  const universe = select([[ALL, 'All'], ...data.indices.map((k) => [k, k])], ALL);
  const sectors = [...new Set(data.rows.map((r) => r.sector).filter(Boolean))].sort();
  const sector = select([[ALL, 'All sectors'], ...sectors.map((s) => [s, s])], ALL);
  const search = el('input', { placeholder: 'ticker or name', size: '14' });
  const xSelect = select(valuationMetrics.map((m) => [m.key, m.label]), 'ev_ebitda');
  const ySelect = select(qualityMetrics.map((m) => [m.key, m.label]), 'roic');
  const status = el('span', { class: 'field-note', text: '' });

  const scatterNode = el('div', { class: 'chart tall' });
  const scatterNote = el('div', { class: 'field-note', text: '' });
  const sectorHost = el('div', {});
  const tableHost = el('div', {});
  const sort = { key: 'market_cap', descending: true };

  function filtered() {
    const text = search.value.trim().toUpperCase();
    return data.rows.filter((r) => (!universe.value || r.indices.includes(universe.value))
      && (!sector.value || r.sector === sector.value)
      && (!text || r.ticker.includes(text) || (r.name || '').toUpperCase().includes(text)));
  }

  function draw() {
    const rows = filtered();
    const x = byKey.get(xSelect.value);
    const y = byKey.get(ySelect.value);
    const shown = scatter(scatterNode, rows, x, y);
    scatterNote.textContent = `${shown.shown} of ${shown.total} companies with both figures shown; `
      + `${shown.outside} beyond the ${AXIS_PERCENTILES[0] * 100}th–${AXIS_PERCENTILES[1] * 100}th percentile axes are off-chart.`;
    sectorHost.replaceChildren(sectorTable(rows, metrics));
    tableHost.replaceChildren(mainTable(rows, metrics, data, sort, (key) => {
      sort.descending = sort.key === key ? !sort.descending : typeof data.rows[0][key] !== 'string';
      sort.key = key;
      draw();
    }, (ticker) => {
      historyInput.value = ticker;
      loadPeHistory();
      historyCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
    status.textContent = `${rows.length} companies`;
  }

  for (const control of [universe, sector, xSelect, ySelect]) control.addEventListener('change', draw);
  search.addEventListener('input', draw);

  root.append(card('FILTER', null, el('div', { class: 'field-row' }, [
    el('div', { class: 'field' }, [el('label', { text: 'UNIVERSE' }), universe]),
    el('div', { class: 'field' }, [el('label', { text: 'SECTOR' }), sector]),
    el('div', { class: 'field' }, [el('label', { text: 'SEARCH' }), search]),
    el('div', { class: 'field' }, [el('label', { text: 'X · VALUATION' }), xSelect]),
    el('div', { class: 'field' }, [el('label', { text: 'Y · QUALITY' }), ySelect]),
    status,
  ])));
  root.append(card('VALUATION × QUALITY', null, [scatterNode, scatterNote]));

  // ---------------- P/E against its own history ---------------------------
  const requestedTicker = ctx.arg;
  const historyInput = el('input', { value: requestedTicker || 'AAPL', size: '8' });
  const historyStatus = el('span', { class: 'field-note', text: '' });
  const historyHost = el('div', {});
  async function loadPeHistory() {
    const symbol = historyInput.value.trim().toUpperCase();
    historyStatus.textContent = `Loading ${symbol}…`;
    try {
      historyStatus.textContent = await renderPeHistory(historyHost, symbol, data);
    } catch (error) {
      historyHost.replaceChildren();
      historyStatus.textContent = error.message;
    }
  }
  historyInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') loadPeHistory(); });
  const historyCard = card('P/E AGAINST ITS OWN 10 YEARS — PRICE ÷ TTM EPS AS FILED AT THE TIME', null, [
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field' }, [el('label', { text: 'TICKER' }), historyInput]),
      el('button', { class: 'action', text: 'LOAD', onclick: loadPeHistory }),
      historyStatus,
    ]),
    historyHost,
  ]);
  root.append(historyCard);
  root.append(card('SECTOR MEDIANS', null, sectorHost));
  root.append(card('ALL COMPANIES — COLOURED BY RANK WITHIN SECTOR (TOP / BOTTOM FIFTH)', null, tableHost));

  const check = data.weight_check;
  root.append(notice(
    `${data.note} Share counts checked against each company's SPY weight: ${check.checked} companies, `
    + `${check.flagged.length} outside a ${check.factor}x band`
    + (check.flagged.length ? ` (${check.flagged.map((f) => `${f.ticker} ${f.ratio}x`).join(', ')})` : '')
    + `. No market cap (no complete share count filed): ${data.without_market_cap.join(', ') || 'none'}. `
    + `Not valued: ${Object.keys(data.skipped).join(', ') || 'none'}. * = a line taken from the prior quarter; hover a ticker for its sources.`,
  ));
  draw();
  await loadPeHistory();
}
