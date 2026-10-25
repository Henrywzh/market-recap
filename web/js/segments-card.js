// BY BUSINESS: a company's revenue and profit by segment, product and region,
// from its own filings (panels/segments.py). The arithmetic is kept apart from
// the DOM so it can be tested under node.

import { el, table, num, gap, periodSwitch, DASH } from './fmt.js';
import { render, SERIES_COLORS } from './charts.js';

const BILLION = 1e9;
const VIEWS = [['segment', 'SEGMENTS'], ['product', 'PRODUCTS'], ['geography', 'REGIONS']];
const KINDS = [['quarterly', 'QUARTERLY'], ['annual', 'ANNUAL']];
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

const pct = (a, b) => (finite(a) && finite(b) && b !== 0 ? (a / b - 1) * 100 * Math.sign(b) : null);
const share = (a, total) => (finite(a) && finite(total) && total > 0 ? (a / total) * 100 : null);
const margin = (profit, revenue) => (finite(profit) && finite(revenue) && revenue > 0 ? (profit / revenue) * 100 : null);
// A margin past ±100% (a start-up unit losing many times its revenue) is not
// a margin to read or chart: the table says n.m. and the chart leaves it out.
export const MEANINGFUL_MARGIN = 100;
const meaningful = (m) => finite(m) && Math.abs(m) <= MEANINGFUL_MARGIN;
const diff = (a, b) => (finite(a) && finite(b) ? a - b : null);

// One row per member for period i, with its year-ago comparison, then the
// total and what the members leave out (unallocated profit; for a segment
// split that does not reconcile, the revenue gap).
export function periodTable(series, i) {
  const j = yearAgoIndex(series.periods, i);
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
        growth: pct(rev, ago), share: share(rev, total), shareChange: diff(share(rev, total), share(ago, totalAgo)),
        profit: finite(profit) ? profit : null, margin: margin(profit, rev),
        marginChange: diff(margin(profit, rev), margin(profitAgo, ago)),
      };
    })
    .filter((r) => r.revenue !== null)
    .sort((a, b) => b.revenue - a.revenue);
  const sum = members.reduce((s, r) => s + r.revenue, 0);
  const unallocated = series.unallocated?.[i];
  const totalProfit = series.total_profit?.[i];
  return {
    period: series.periods[i], yearAgo: j === null ? null : series.periods[j], members,
    total: finite(total) ? total : null, totalGrowth: pct(total, totalAgo),
    residual: finite(total) && !series.periods[i].reconciled ? total - sum : null,
    unallocated: finite(unallocated) && finite(total) && Math.abs(unallocated) >= Math.abs(total) * 0.001 ? unallocated : null,
    totalProfit: finite(totalProfit) ? totalProfit : null, totalMargin: margin(totalProfit, total),
  };
}

// The bands of the stacked chart: the members largest in the latest periods,
// the rest summed as "Other".
export function bands(series, limit = MAX_BANDS) {
  const n = series.periods.length;
  const weight = (m) => (series.revenue[m.key] || []).slice(-4).reduce((s, v) => s + (finite(v) ? v : 0), 0)
    + (series.revenue[m.key] || []).reduce((s, v) => s + (finite(v) ? v : 0), 0) / 1e6;
  const ranked = [...series.members].sort((a, b) => weight(b) - weight(a));
  const shown = ranked.slice(0, ranked.length > limit ? limit - 1 : limit);
  const rest = ranked.slice(shown.length);
  const out = shown.map((m) => ({ label: m.label, values: series.revenue[m.key] }));
  if (rest.length) {
    const values = Array.from({ length: n }, (_, i) => {
      const parts = rest.map((m) => series.revenue[m.key]?.[i]).filter(finite);
      return parts.length ? parts.reduce((s, v) => s + v, 0) : null;
    });
    out.push({ label: `Other (${rest.length})`, values });
  }
  return out;
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

function stackChart(node, series) {
  const labels = series.periods.map(periodLabel);
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 52, bottom: 58 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9, type: 'scroll' },
    tooltip: { ...option.tooltip, axisPointer: { type: 'shadow' }, valueFormatter: (v) => (finite(v) ? `${num(v, 2)}B` : DASH) },
    xAxis: { ...option.xAxis, boundaryGap: true, data: labels },
    yAxis: { ...option.yAxis, scale: false, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${num(v, 0)}B` } },
    series: bands(series).map((band, index) => ({
      name: band.label, type: 'bar', stack: 'revenue', barMaxWidth: 26,
      itemStyle: { color: SERIES_COLORS[index % SERIES_COLORS.length] },
      data: band.values.map((v) => (finite(v) ? v / BILLION : null)),
    })),
  }));
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
  const ago = t.yearAgo ? `vs ${t.yearAgo.label}` : 'no year-ago period';
  const headers = ['', 'REVENUE', `GROWTH ${ago.toUpperCase()}`, 'SHARE', 'SHARE Δ',
    ...(hasProfit ? ['PROFIT', 'MARGIN', 'MARGIN Δ'] : [])];
  const row = (cells, cls = '') => el('tr', { class: cls }, cells.map((text, k) => el('td', { class: k === 0 ? 'wrap-cell' : '', text })));
  const rows = t.members.map((r) => row([r.label, bn(r.revenue), signed(r.growth), percent(r.share), signed(r.shareChange, ' pp'),
    ...(hasProfit ? [bn(r.profit), marginText(r.margin), meaningful(r.margin) ? signed(r.marginChange, ' pp') : DASH] : [])]));
  if (t.residual !== null && Math.abs(t.residual) >= Math.abs(t.total || 0) * 0.001) {
    rows.push(row(['Not in the segments (reconciling items)', bn(t.residual), DASH, percent(share(t.residual, t.total)), DASH,
      ...(hasProfit ? [DASH, DASH, DASH] : [])], 'dim'));
  }
  if (hasProfit && t.unallocated !== null) {
    rows.push(row(['Unallocated (corporate, other)', DASH, DASH, DASH, DASH, bn(t.unallocated), DASH, DASH], 'dim'));
  }
  rows.push(row(['Company total', bn(t.total), signed(t.totalGrowth), t.total ? '100%' : DASH, DASH,
    ...(hasProfit ? [bn(t.totalProfit), percent(t.totalMargin), DASH] : [])], 'total-row'));
  return table(headers, rows);
}

// The body of the BY BUSINESS card for one company's segments artifact, or a gap.
export function segmentsCard(data) {
  if (!data?.views || !Object.keys(data.views).length) return gap('No breakdown in its filings.');
  const views = VIEWS.filter(([key]) => data.views[key]);
  let view = views[0][0];
  let kind = data.views[view].quarterly ? 'quarterly' : 'annual';
  let index = null;
  const body = el('div', {});
  const draw = () => {
    body.replaceChildren();
    const kinds = KINDS.filter(([k]) => data.views[view][k]);
    if (!data.views[view][kind]) kind = kinds[0][0];
    const series = data.views[view][kind];
    const last = series.periods.length - 1;
    if (index === null || index > last) index = last;
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
    const chart = el('div', { class: 'chart' });
    const parts = [controls, el('div', { class: 'field-note', text: 'REVENUE BY ' + (view === 'segment' ? 'SEGMENT' : view === 'product' ? 'PRODUCT / SERVICE' : 'REGION') + ' · $B' }), chart];
    let marginNode = null;
    if (Object.keys(series.profit || {}).length) {
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
      stackChart(chart, series);
      if (marginNode) marginChart(marginNode, series);
    });
  };
  draw();
  return body;
}
