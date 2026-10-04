// A chart with a view switch: the series as published (RAW) and its change
// over the lags that suit its frequency -- MoM / YoY for a monthly series,
// QoQ / YoY for a quarterly one, WoW / 4W for a daily one. A percent change
// for levels, a point change (pp) for series that are already percentages.
//
// The change math is exported for the tests; the chart draws with the
// shared ECharts wrapper.

import { el, num, periodSwitch, DASH } from './fmt.js';
import { render, SERIES_COLORS } from './charts.js';

// A RAW view whose positive values span more than this factor draws on a log
// axis: $12 and $3,768 on one linear axis leaves the median as a flat line.
const LOG_SPAN = 25;

export function change(values, lag, kind = 'pct') {
  return values.map((v, i) => {
    const base = i >= lag ? values[i - lag] : null;
    if (v === null || v === undefined || base === null || base === undefined) return null;
    if (kind === 'diff') return Math.round((v - base) * 100) / 100;
    if (!(base > 0)) return null;
    return Math.round(1000 * (v / base - 1)) / 10;
  });
}

export function logSpan(series) {
  const positive = series.flatMap((s) => s.values).filter((v) => typeof v === 'number' && v > 0);
  if (!positive.length) return false;
  return Math.max(...positive) / Math.min(...positive) > LOG_SPAN;
}

// Standard view sets by frequency. `kind` 'diff' is for rates (adoption %).
export const VIEWS = {
  monthly: (kind = 'pct') => [{ id: 'RAW' }, { id: kind === 'diff' ? 'Δ MoM' : 'MoM', lag: 1, kind }, { id: kind === 'diff' ? 'Δ YoY' : 'YoY', lag: 12, kind }],
  quarterly: () => [{ id: 'RAW' }, { id: 'QoQ', lag: 1 }, { id: 'YoY', lag: 4 }],
  daily: () => [{ id: 'RAW' }, { id: 'WoW', lag: 7 }, { id: '4W', lag: 28 }],
  weekly: () => [{ id: 'RAW' }, { id: '4W', lag: 4 }, { id: '13W', lag: 13 }, { id: 'YoY', lag: 52 }],
};

// spec: { dates, series: [{ name, values, color?, hidden? }], views, fmt (raw axis),
//         type: 'line' | 'bar' | 'stack', height, initial, tail (points shown),
//         changeOnly (series drawn only in the change views, e.g. a stack's total) }
export function viewChart(spec) {
  const node = el('div', { class: `chart ${spec.height || ''}` });
  const views = spec.views || VIEWS.monthly();
  let active = spec.initial || views[0].id;
  const note = el('span', { class: 'dim' });
  const draw = () => {
    const view = views.find((v) => v.id === active) || views[0];
    const raw = view.id === 'RAW';
    // Changes are taken on the whole history, then the last `tail` points shown,
    // so the first year of a YoY view is not blank for want of a base.
    const cut = (values) => (spec.tail ? values.slice(-spec.tail) : values);
    const source = raw ? spec.series : [...spec.series, ...(spec.changeOnly || [])];
    // A view may carry the change as its source states it (a release's own
    // y/y) instead of computing it from the levels.
    const series = view.series
      ? view.series.map((s) => ({ ...s, values: cut(s.values) }))
      : source.map((s) => ({ ...s, values: cut(raw ? s.values : change(s.values, view.lag, view.kind)) }));
    const dates = cut(spec.dates);
    const log = raw && spec.type !== 'stack' && spec.type !== 'bar' && logSpan(series);
    note.textContent = raw ? (log ? 'log scale' : '') : (view.kind === 'diff' ? 'change, pp' : 'change, %');
    const fmt = raw ? (spec.fmt || ((v) => num(v, 0))) : (v) => `${v > 0 ? '+' : ''}${num(v, 1)}${view.kind === 'diff' ? 'pp' : '%'}`;
    const asBars = raw ? (spec.type === 'bar' || spec.type === 'stack') : spec.type === 'bar';
    const hidden = Object.fromEntries(spec.series.filter((s) => s.hidden).map((s) => [s.name, false]));
    render(node, (option, p) => ({
      ...option,
      grid: { left: 58, right: 16, top: 28, bottom: 26 },
      legend: { top: 0, textStyle: { color: p.dim, fontSize: 9 }, itemWidth: 10, itemHeight: asBars ? 6 : 2, selected: hidden },
      tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: (v) => (v === null || v === undefined ? DASH : fmt(v)) },
      xAxis: { ...option.xAxis, boundaryGap: asBars, data: dates },
      // Bars are read from zero; the shared axis otherwise fits the data's range.
      yAxis: { ...option.yAxis, type: log ? 'log' : 'value', scale: !asBars, axisLabel: { color: p.dim, fontSize: 9, formatter: fmt } },
      series: series.map((s, i) => {
        const color = s.color ? s.color(p) : SERIES_COLORS[i % SERIES_COLORS.length];
        return {
          name: s.name, data: s.values.map((v) => (log && !(v > 0) ? null : v)),
          type: asBars ? 'bar' : 'line', stack: raw && spec.type === 'stack' ? 'total' : undefined,
          barMaxWidth: 22, showSymbol: spec.showSymbol ?? false, symbolSize: spec.showSymbol ? 3 : undefined,
          connectNulls: spec.connectNulls ?? !asBars,
          lineStyle: { width: s.width || 1.4, color }, itemStyle: { color },
          markLine: !raw && i === 0 ? { silent: true, symbol: 'none', data: [{ yAxis: 0 }], lineStyle: { color: p.faint }, label: { show: false } } : undefined,
        };
      }),
    }));
  };
  const head = el('div', { class: 'chart-head' }, [
    spec.title ? el('span', { class: 'card-title', text: spec.title }) : el('span', {}),
    el('span', { class: 'tag-row' }, [note, views.length > 1 ? Object.assign(periodSwitch(views.map((v) => v.id), active, (id) => { active = id; draw(); }), { className: 'period-switch range-switch' }) : null]),
  ]);
  requestAnimationFrame(draw);
  return el('div', {}, [head, node]);
}
