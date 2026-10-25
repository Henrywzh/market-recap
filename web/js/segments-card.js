// BY BUSINESS: a company's revenue and profit by segment, product and region,
// from its own filings (panels/segments.py). The arithmetic is kept apart from
// the DOM so it can be tested under node.

import { el, table, num, gap, periodSwitch, DASH } from './fmt.js';
import { render, SERIES_COLORS } from './charts.js';

const BILLION = 1e9;
const VIEWS = [['segment', 'SEGMENTS'], ['product', 'PRODUCTS'], ['geography', 'REGIONS']];
const KINDS = [['quarterly', 'QUARTERLY'], ['annual', 'ANNUAL']];
const METRICS = [['revenue', 'REVENUE'], ['profit', 'PROFIT']];
const MEASURES = [['value', '$B'], ['share', '% SHARE'], ['yoy', 'YOY %'], ['qoq', 'QOQ %']];
// Growth past this, either way, is a base effect (a unit growing from almost
// nothing), not a rate to chart: left out of the growth lines.
export const GROWTH_CAP = 300;
// Bars drawn per period; the rest of the members are one "Other" band.
const MAX_BANDS = 8;
const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const DAY = 86400000;

// The period a year before period i: the same quarter last year, or last year.
export function yearAgoIndex(periods, i) {
  const end = Date.parse(periods[i]?.end);
  if (!Number.isFinite(end)) return null;
  for (let j = i - 1; j >= 0; j -= 1) {
    const days = (end - Date.parse(periods[j].end)) / DAY;
    if (days >= 350 && days <= 380) return j;
    if (days > 380) break;
  }
  return null;
}

// The quarter before period i: 80 to 100 days earlier, or null (an annual
// series, or a quarter missing from the filings).
export function previousIndex(periods, i) {
  if (i < 1) return null;
  const days = (Date.parse(periods[i]?.end) - Date.parse(periods[i - 1]?.end)) / DAY;
  return days >= 80 && days <= 100 ? i - 1 : null;
}

const pct = (a, b) => (finite(a) && finite(b) && b !== 0 ? (a / b - 1) * 100 * Math.sign(b) : null);
const share = (a, total) => (finite(a) && finite(total) && total > 0 ? (a / total) * 100 : null);
const margin = (profit, revenue) => (finite(profit) && finite(revenue) && revenue > 0 ? (profit / revenue) * 100 : null);
// A margin past ±100% (a start-up unit losing many times its revenue) is not
// a margin to read or chart: the table says n.m. and the chart leaves it out.
export const MEANINGFUL_MARGIN = 100;
const meaningful = (m) => finite(m) && Math.abs(m) <= MEANINGFUL_MARGIN;
const diff = (a, b) => (finite(a) && finite(b) ? a - b : null);
// Growth from a positive base only: from a loss it has no sign to read.
const growth = (a, b) => (finite(a) && finite(b) && b > 0 ? (a / b - 1) * 100 : null);
const sumOf = (values) => {
  const parts = values.filter(finite);
  return parts.length ? parts.reduce((s, v) => s + v, 0) : null;
};

// One row per member for period i, with its year-ago comparison, then the
// total and what the members leave out (unallocated profit; for a segment
// split that does not reconcile, the revenue gap).
export function periodTable(series, i) {
  const j = yearAgoIndex(series.periods, i);
  const q = previousIndex(series.periods, i);
  const profitSum = sumOf(series.members.map((m) => series.profit?.[m.key]?.[i]));
  const total = series.total_revenue?.[i];
  const totalAgo = j === null ? null : series.total_revenue?.[j];
  const members = series.members
    .map((m) => {
      const rev = series.revenue[m.key]?.[i];
      const ago = j === null ? null : series.revenue[m.key]?.[j];
      const profit = series.profit?.[m.key]?.[i];
      const profitAgo = j === null ? null : series.profit?.[m.key]?.[j];
      return {
        key: m.key, label: m.label, revenue: finite(rev) ? rev : null,
        growth: pct(rev, ago), qoq: q === null ? null : growth(rev, series.revenue[m.key]?.[q]),
        share: share(rev, total), shareChange: diff(share(rev, total), share(ago, totalAgo)),
        profit: finite(profit) ? profit : null, profitGrowth: growth(profit, profitAgo),
        profitShare: finite(profit) && finite(profitSum) && profitSum > 0 ? (profit / profitSum) * 100 : null,
        margin: margin(profit, rev),
        marginChange: diff(margin(profit, rev), margin(profitAgo, ago)),
      };
    })
    .filter((r) => r.revenue !== null)
    .sort((a, b) => b.revenue - a.revenue);
  const sum = members.reduce((s, r) => s + r.revenue, 0);
  const unallocated = series.unallocated?.[i];
  const totalProfit = series.total_profit?.[i];
  return {
    period: series.periods[i], yearAgo: j === null ? null : series.periods[j],
    previous: q === null ? null : series.periods[q], members,
    total: finite(total) ? total : null, totalGrowth: pct(total, totalAgo),
    totalQoq: q === null ? null : growth(total, series.total_revenue?.[q]),
    residual: finite(total) && !series.periods[i].reconciled ? total - sum : null,
    unallocated: finite(unallocated) && finite(total) && Math.abs(unallocated) >= Math.abs(total) * 0.001 ? unallocated : null,
    totalProfit: finite(totalProfit) ? totalProfit : null, totalMargin: margin(totalProfit, total),
    totalProfitGrowth: j === null ? null : growth(totalProfit, series.total_profit?.[j]),
  };
}

// The bands of the stacked chart: the members largest in the latest periods,
// the rest summed as "Other". ``metric``: revenue, or the segments' profit
// (ranked by its size either side of zero).
export function bands(series, limit = MAX_BANDS, metric = 'revenue') {
  const n = series.periods.length;
  const of = series[metric] || {};
  const members = series.members.filter((m) => of[m.key]);
  const size = (v) => (finite(v) ? Math.abs(v) : 0);
  const weight = (m) => of[m.key].slice(-4).reduce((s, v) => s + size(v), 0)
    + of[m.key].reduce((s, v) => s + size(v), 0) / 1e6;
  const ranked = [...members].sort((a, b) => weight(b) - weight(a));
  const shown = ranked.slice(0, ranked.length > limit ? limit - 1 : limit);
  const rest = ranked.slice(shown.length);
  const out = shown.map((m) => ({ label: m.label, values: of[m.key] }));
  if (rest.length) {
    const values = Array.from({ length: n }, (_, i) => sumOf(rest.map((m) => of[m.key]?.[i])));
    out.push({ label: `Other (${rest.length})`, values });
  }
  return out;
}

// What the chart draws for each band: dollars, its share of the bands' sum
// (they add to 100), or its growth on the year-ago period or the quarter
// before. A share needs a positive sum (a profit split with net losses has
// none); growth needs a positive base and stays inside GROWTH_CAP.
export function measureBands(list, periods, measure) {
  const n = periods.length;
  const sums = Array.from({ length: n }, (_, i) => sumOf(list.map((b) => b.values?.[i])));
  const base = (i) => (measure === 'yoy' ? yearAgoIndex(periods, i) : previousIndex(periods, i));
  return list.map((band) => ({
    label: band.label,
    values: Array.from({ length: n }, (_, i) => {
      const v = band.values?.[i];
      if (!finite(v)) return null;
      if (measure === 'value') return v / BILLION;
      if (measure === 'share') return finite(sums[i]) && sums[i] > 0 ? (v / sums[i]) * 100 : null;
      const k = base(i);
      const g = k === null ? null : growth(v, band.values[k]);
      return finite(g) && Math.abs(g) <= GROWTH_CAP ? g : null;
    }),
  }));
}

const bn = (v, digits = 1) => (finite(v) ? `${num(v / BILLION, digits)}B` : DASH);
// Signed after rounding, so a change that rounds to zero reads 0.0, not −0.0.
const signed = (v, unit = '%', digits = 1) => {
  if (!finite(v)) return DASH;
  const r = Number(v.toFixed(digits));
  return `${r > 0 ? '+' : r < 0 ? '−' : ''}${num(Math.abs(r), digits)}${unit}`;
};
const percent = (v) => (finite(v) ? `${num(v, 1)}%` : DASH);
const marginText = (v) => (finite(v) && !meaningful(v) ? 'n.m.' : percent(v));
const periodLabel = (p) => `${p.label}${p.derived ? '*' : ''}`;

// The main chart: stacked bars of dollars or shares, or one growth line per
// band with the company total dashed beside them.
function stackChart(node, series, metric, measure) {
  const labels = series.periods.map(periodLabel);
  const list = measureBands(bands(series, MAX_BANDS, metric), series.periods, measure);
  const growthView = measure === 'yoy' || measure === 'qoq';
  const total = metric === 'profit' ? series.total_profit : series.total_revenue;
  const totalLine = growthView && total
    ? measureBands([{ label: 'Company total', values: total }], series.periods, measure)[0] : null;
  const unit = measure === 'value' ? 'B' : '%';
  const text = (v, digits) => (finite(v) ? `${measure === 'value' ? '' : growthView && v > 0 ? '+' : ''}${num(v, digits)}${unit}` : DASH);
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 52, bottom: 58 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9, type: 'scroll' },
    tooltip: { ...option.tooltip, axisPointer: { type: growthView ? 'line' : 'shadow' }, valueFormatter: (v) => text(v, measure === 'value' ? 2 : 1) },
    xAxis: { ...option.xAxis, boundaryGap: true, data: labels },
    yAxis: { ...option.yAxis, scale: false, ...(measure === 'share' ? { max: (e) => (e.max <= 100 ? 100 : null) } : {}),
      axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${num(v, 0)}${unit}` } },
    series: [
      ...list.map((band, index) => {
        const color = SERIES_COLORS[index % SERIES_COLORS.length];
        return growthView
          ? { name: band.label, type: 'line', data: band.values, connectNulls: false, symbolSize: 4,
            lineStyle: { width: 1.4, color }, itemStyle: { color },
            ...(index === 0 ? { markLine: { silent: true, symbol: 'none', label: { show: false },
              lineStyle: { color: p.faint, type: 'solid' }, data: [{ yAxis: 0 }] } } : {}) }
          : { name: band.label, type: 'bar', stack: metric, barMaxWidth: 26, itemStyle: { color }, data: band.values };
      }),
      ...(totalLine ? [{ name: totalLine.label, type: 'line', data: totalLine.values, symbolSize: 4,
        lineStyle: { width: 1.6, type: 'dashed', color: p.text }, itemStyle: { color: p.text } }] : []),
    ],
  }));
}

function chartTitle(view, metric, measure, kind) {
  const by = view === 'segment' ? 'SEGMENT' : view === 'product' ? 'PRODUCT / SERVICE' : 'REGION';
  const what = metric === 'profit' ? 'SEGMENT PROFIT' : 'REVENUE';
  const how = {
    value: '$B',
    share: `% OF THE ${metric === 'profit' ? 'SEGMENTS\' PROFIT' : 'BREAKDOWN\'S SUM'} · each period adds to 100`,
    yoy: `% CHANGE ON THE ${kind === 'annual' ? 'YEAR BEFORE' : 'SAME QUARTER A YEAR EARLIER'} · company total dashed`,
    qoq: '% CHANGE ON THE QUARTER BEFORE (seasonal) · company total dashed',
  }[measure];
  return `${what} BY ${by} · ${how}`;
}

function marginChart(node, series) {
  const labels = series.periods.map(periodLabel);
  const marginsOf = (m) => series.periods.map((_, i) => margin(series.profit[m.key][i], series.revenue[m.key]?.[i]));
  const lines = series.members.filter((m) => series.profit?.[m.key] && marginsOf(m).some(meaningful));
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, bottom: 52 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9, type: 'scroll' },
    tooltip: { ...option.tooltip, valueFormatter: (v) => (finite(v) ? `${num(v, 1)}%` : DASH) },
    xAxis: { ...option.xAxis, data: labels },
    yAxis: { ...option.yAxis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${num(v, 0)}%` } },
    series: lines.map((m, index) => ({
      name: m.label, type: 'line', showSymbol: false, connectNulls: false,
      lineStyle: { width: 1.4, color: SERIES_COLORS[index % SERIES_COLORS.length] },
      itemStyle: { color: SERIES_COLORS[index % SERIES_COLORS.length] },
      data: marginsOf(m).map((v) => (meaningful(v) ? v : null)),
    })),
  }));
}

function tableNode(series, i) {
  const t = periodTable(series, i);
  const hasProfit = t.members.some((r) => r.profit !== null);
  const quarterly = series.periods.some((_, k) => previousIndex(series.periods, k) !== null);
  const headers = ['', 'REVENUE', 'YOY', ...(quarterly ? ['QOQ'] : []), 'SHARE', 'SHARE Δ',
    ...(hasProfit ? ['PROFIT', 'PROFIT YOY', 'PROFIT SHARE', 'MARGIN', 'MARGIN Δ'] : [])];
  const row = (cells, cls = '') => el('tr', { class: cls }, cells.map((text, k) => el('td', { class: k === 0 ? 'wrap-cell' : '', text })));
  const qoq = (v) => (quarterly ? [signed(v)] : []);
  const blank = (count) => Array(count).fill(DASH);
  const rows = t.members.map((r) => row([r.label, bn(r.revenue), signed(r.growth), ...qoq(r.qoq), percent(r.share), signed(r.shareChange, ' pp'),
    ...(hasProfit ? [bn(r.profit), signed(r.profitGrowth), percent(r.profitShare), marginText(r.margin),
      meaningful(r.margin) ? signed(r.marginChange, ' pp') : DASH] : [])]));
  if (t.residual !== null && Math.abs(t.residual) >= Math.abs(t.total || 0) * 0.001) {
    rows.push(row(['Not in the segments (reconciling items)', bn(t.residual), DASH, ...qoq(null), percent(share(t.residual, t.total)), DASH,
      ...(hasProfit ? blank(5) : [])], 'dim'));
  }
  if (hasProfit && t.unallocated !== null) {
    rows.push(row(['Unallocated (corporate, other)', DASH, DASH, ...qoq(null), DASH, DASH, bn(t.unallocated), ...blank(4)], 'dim'));
  }
  rows.push(row(['Company total', bn(t.total), signed(t.totalGrowth), ...qoq(t.totalQoq), t.total ? '100%' : DASH, DASH,
    ...(hasProfit ? [bn(t.totalProfit), signed(t.totalProfitGrowth), DASH, percent(t.totalMargin), DASH] : [])], 'total-row'));
  const against = [t.yearAgo ? `YOY vs ${t.yearAgo.label}` : 'no year-ago period', quarterly && t.previous ? `QOQ vs ${t.previous.label}` : null]
    .filter(Boolean).join(' · ');
  return el('div', {}, [
    el('div', { class: 'field-note', text: `${periodLabel(t.period)} · ${against}${hasProfit ? ' · profit share: of the segments\' profit summed' : ''}` }),
    table(headers, rows),
  ]);
}

// The body of the BY BUSINESS card for one company's segments artifact, or a gap.
export function segmentsCard(data) {
  if (!data?.views || !Object.keys(data.views).length) return gap('No breakdown in its filings.');
  const views = VIEWS.filter(([key]) => data.views[key]);
  let view = views[0][0];
  let kind = data.views[view].quarterly ? 'quarterly' : 'annual';
  let index = null;
  let metric = 'revenue';
  let measure = 'value';
  const body = el('div', {});
  const draw = () => {
    body.replaceChildren();
    const kinds = KINDS.filter(([k]) => data.views[view][k]);
    if (!data.views[view][kind]) kind = kinds[0][0];
    const series = data.views[view][kind];
    const last = series.periods.length - 1;
    if (index === null || index > last) index = last;
    const hasProfit = Object.keys(series.profit || {}).length > 0;
    if (!hasProfit) metric = 'revenue';
    const measures = MEASURES.filter(([k]) => k !== 'qoq' || kind === 'quarterly');
    if (!measures.some(([k]) => k === measure)) measure = 'yoy';
    const picker = el('select', { 'aria-label': 'Period for the table' }, series.periods.map((p, i) => el('option', { value: String(i), text: periodLabel(p) })));
    picker.value = String(index);
    picker.addEventListener('change', () => { index = Number(picker.value); draw(); });
    const controls = el('div', { class: 'tag-row segments-controls' }, [
      views.length > 1 ? periodSwitch(views.map(([, label]) => label), VIEWS.find(([k]) => k === view)[1], (label) => {
        view = VIEWS.find(([, l]) => l === label)[0]; index = null; draw();
      }) : null,
      kinds.length > 1 ? periodSwitch(kinds.map(([, label]) => label), KINDS.find(([k]) => k === kind)[1], (label) => {
        kind = KINDS.find(([, l]) => l === label)[0]; index = null; draw();
      }) : null,
      el('label', { class: 'dim', text: 'TABLE ' }, [picker]),
    ]);
    const chartControls = el('div', { class: 'tag-row segments-controls' }, [
      hasProfit ? periodSwitch(METRICS.map(([, l]) => l), METRICS.find(([k]) => k === metric)[1], (l) => {
        metric = METRICS.find(([, x]) => x === l)[0]; draw();
      }) : null,
      periodSwitch(measures.map(([, l]) => l), MEASURES.find(([k]) => k === measure)[1], (l) => {
        measure = MEASURES.find(([, x]) => x === l)[0]; draw();
      }),
      el('span', { class: 'dim segments-hint', text: 'legend: click hides · double-click shows only that one' }),
    ]);
    const chart = el('div', { class: 'chart' });
    const parts = [controls, chartControls, el('div', { class: 'field-note', text: chartTitle(view, metric, measure, kind) }), chart];
    if (measure === 'share' && metric === 'profit') {
      parts.push(el('div', { class: 'field-note', text: 'A unit\'s loss is drawn below zero, so in that period the others add to more than 100.' }));
    }
    if (measure === 'yoy' || measure === 'qoq') {
      parts.push(el('div', { class: 'field-note', text: `Growth from a loss, or past ±${GROWTH_CAP}%, is left out.${measure === 'qoq' ? ' Quarter on quarter carries the season: a fourth quarter is often the year\'s largest.' : ''}` }));
    }
    let marginNode = null;
    if (hasProfit) {
      marginNode = el('div', { class: 'chart', style: 'height:220px' });
      parts.push(el('div', { class: 'field-note', text: 'SEGMENT OPERATING MARGIN · the company\'s own segment profit measure · margins past ±100% left out' }), marginNode);
    }
    parts.push(tableNode(series, index));
    const notes = [];
    if (series.periods.some((p) => p.derived)) notes.push('* fourth quarter derived: the year less nine months.');
    if (series.periods.some((p) => !p.reconciled)) notes.push('Segments that do not add up to the reported total show the gap as reconciling items.');
    if (view === 'segment' && series.profit_concept && series.profit_concept !== 'OperatingIncomeLoss') notes.push('Segment profit is pre-tax income, the measure this company reports by segment.');
    notes.push(`${data.filings_read} filings read${data.filings_pending ? `, ${data.filings_pending} still to read (history fills over the next builds)` : ''} · latest filed ${data.latest_filed}.`);
    parts.push(el('div', { class: 'field-note', text: notes.join(' ') }));
    body.append(...parts);
    requestAnimationFrame(() => {
      stackChart(chart, series, metric, measure);
      if (marginNode) marginChart(marginNode, series);
    });
  };
  draw();
  return body;
}
