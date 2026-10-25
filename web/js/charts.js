// ECharts wrappers carrying the terminal palette. Charts read their colours
// from the same CSS variables as the tables so a theme switch cannot leave a
// chart on the old palette.

import { formatTick, formatValue, niceStepFromRange } from './axis-format.js';

const registry = new Map();

// Value-axis labels carry the decimals their tick spacing needs (axis-format.js).
// ECharts gives an axisLabel formatter only (value, tick index), not the axis
// extent, so the default is tagged `adaptive` and render() replaces it, once the
// axis has drawn its ticks, with one that knows the step.
function tickLabels(step = null) {
  const label = (v) => formatTick(v, step);
  label.adaptive = true;
  return label;
}

// Tooltip numbers: at most three decimals, unless a chart sets its own valueFormatter.
const tooltipValue = (v) => (v === null || v === undefined || typeof v === 'number' ? formatValue(v) : v);

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function palette() {
  return {
    text: css('--text'),
    dim: css('--text-dim'),
    faint: css('--text-faint'),
    border: css('--border'),
    accent: css('--accent'),
    up: css('--up'),
    down: css('--down'),
    blue: css('--blue'),
    purple: css('--purple'),
    panel: css('--panel'),
  };
}

export const SERIES_COLORS = [
  '#e8a33d', '#60a5fa', '#4ade80', '#f87171', '#a78bfa',
  '#22d3ee', '#fbbf24', '#f472b6', '#34d399', '#94a3b8', '#fb923c',
];

function baseOption(p) {
  return {
    animation: false,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace', fontSize: 10 },
    grid: { left: 52, right: 16, top: 16, bottom: 34 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#000',
      borderColor: p.border,
      borderWidth: 1,
      textStyle: { color: p.text, fontSize: 11, fontFamily: 'ui-monospace, Menlo, monospace' },
      axisPointer: { type: 'line', lineStyle: { color: p.faint, type: 'dashed' } },
      valueFormatter: tooltipValue,
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      axisLine: { lineStyle: { color: p.border } },
      axisTick: { show: false },
      axisLabel: { color: p.dim, fontSize: 10, hideOverlap: true },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: p.dim, fontSize: 10, formatter: tickLabels() },
      splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
    },
  };
}

export function render(node, build) {
  if (!node || !window.echarts) return null;
  let chart = registry.get(node);
  if (chart) chart.dispose();
  chart = window.echarts.init(node, null, { renderer: 'canvas' });
  const p = palette();
  const option = build(baseOption(p), p);
  chart.setOption(option, true);
  fitTickLabels(chart, option);
  if (option.legend && typeof chart.on === 'function') legendSolo(chart, node);
  registry.set(node, chart);
  return chart;
}

// Two clicks on one legend entry within this many milliseconds are a double click.
export const DOUBLE_CLICK_MS = 350;

// What a double click on legend entry ``name`` does, given the legend's state
// before it (``selected``: name -> shown). Shows only that entry; when it is
// already the only one shown, shows them all again.
export function soloAction(selected, name) {
  const names = Object.keys(selected);
  const alone = names.every((n) => Boolean(selected[n]) === (n === name));
  return alone ? { show: names, hide: [] } : { show: [name], hide: names.filter((n) => n !== name) };
}

// The last legend click per chart node, kept by node so a chart redrawn
// between the two clicks (OPENROUTER redraws on every click) still sees both.
const lastLegendClick = new WeakMap();

// A legend click hides or shows its series (ECharts' own toggle); a double
// click shows only that series. The double click's two toggles cancel out, so
// ``selected`` after the second is the state before the first. This listener
// is registered first, so it rewrites ``event.selected`` to the final state for
// the listeners after it (charts that keep their own selection).
function legendSolo(chart, node) {
  chart.on('legendselectchanged', (event) => {
    const now = Date.now();
    const last = lastLegendClick.get(node);
    const twice = last?.name === event.name && now - last.at < DOUBLE_CLICK_MS;
    lastLegendClick.set(node, twice ? { name: null, at: 0 } : { name: event.name, at: now });
    if (!twice) return;
    const { show, hide } = soloAction(event.selected, event.name);
    show.forEach((name) => chart.dispatchAction({ type: 'legendSelect', name }));
    hide.forEach((name) => chart.dispatchAction({ type: 'legendUnSelect', name }));
    show.forEach((name) => { event.selected[name] = true; });
    hide.forEach((name) => { event.selected[name] = false; });
  });
}

// Each adaptive value axis takes the step ECharts drew it with: the spacing of
// its ticks, or the nice step of its extent when it has fewer than two ticks. The
// step is known only after the first draw, so the labels are set again here;
// setOption is synchronous, so the axis scale read below is the drawn one.
// Without the model (an ECharts without this API) the default formatter stays.
function fitTickLabels(chart, option) {
  const model = chart.getModel?.();
  const patch = [].concat(option.yAxis || []).map((axis, index) => {
    if (!axis?.axisLabel?.formatter?.adaptive) return {};
    const scale = model?.getComponent('yAxis', index)?.axis?.scale;
    return scale ? { axisLabel: { formatter: tickLabels(tickStep(scale)) } } : {};
  });
  if (patch.some((entry) => entry.axisLabel)) chart.setOption({ yAxis: patch });
}

function tickStep(scale) {
  const ticks = scale.getTicks().map((tick) => tick.value);
  if (ticks.length > 1 && ticks[1] !== ticks[0]) return Math.abs(ticks[1] - ticks[0]);
  const [min, max] = scale.getExtent();
  return niceStepFromRange(min, max, 5);
}

export function resizeAll() {
  registry.forEach((chart, node) => {
    if (document.body.contains(node)) chart.resize();
  });
}

export function disposeAll() {
  registry.forEach((chart) => chart.dispose());
  registry.clear();
}

export function disposeWithin(host) {
  registry.forEach((chart, node) => {
    if (host.contains(node)) {
      chart.dispose();
      registry.delete(node);
    }
  });
}

// --- Chart recipes -------------------------------------------------------

export function areaLine(node, dates, values, color) {
  return render(node, (option, p) => {
    const tint = color || p.accent;
    return {
      ...option,
      xAxis: { ...option.xAxis, data: dates },
      series: [{
        type: 'line',
        data: values,
        showSymbol: false,
        lineStyle: { width: 1.3, color: tint },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: `${tint}55` },
              { offset: 1, color: `${tint}05` },
            ],
          },
        },
      }],
    };
  });
}

export function barsAroundZero(node, dates, values) {
  return render(node, (option, p) => ({
    ...option,
    xAxis: { ...option.xAxis, data: dates, boundaryGap: true },
    series: [{
      type: 'bar',
      data: values.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? p.up : p.down } })),
      barMaxWidth: 6,
    }],
    markLine: undefined,
  }));
}

export function zeroLine(node, dates, values, color) {
  return render(node, (option, p) => ({
    ...option,
    xAxis: { ...option.xAxis, data: dates },
    series: [{
      type: 'line',
      data: values,
      showSymbol: false,
      lineStyle: { width: 1, color: color || p.blue },
      markLine: {
        silent: true,
        symbol: 'none',
        data: [{ yAxis: 0 }],
        lineStyle: { color: p.faint, type: 'dashed', width: 1 },
        label: { show: false },
      },
    }],
  }));
}

// options: { symbols?, width?, log?: a log value axis (every value > 0), markY?: [{ y, label }] }
export function multiLine(node, dates, seriesMap, options = {}) {
  return render(node, (option, p) => {
    const names = Object.keys(seriesMap);
    const marks = (options.markY || []).map((m) => ({ yAxis: m.y, label: { formatter: m.label, color: p.dim, fontSize: 10 } }));
    return {
      ...option,
      ...(options.log ? { yAxis: { ...option.yAxis, type: 'log', logBase: 10, min: options.min } } : {}),
      grid: { ...option.grid, bottom: 52 },
      legend: {
        bottom: 0,
        textStyle: { color: p.dim, fontSize: 10 },
        icon: 'rect',
        itemWidth: 9,
        itemHeight: 9,
        type: 'scroll',
      },
      xAxis: { ...option.xAxis, data: dates },
      series: names.map((name, index) => ({
        name,
        type: 'line',
        data: seriesMap[name],
        showSymbol: options.symbols || false,
        symbolSize: 5,
        lineStyle: { width: options.width || 1.2, color: SERIES_COLORS[index % SERIES_COLORS.length] },
        itemStyle: { color: SERIES_COLORS[index % SERIES_COLORS.length] },
        ...(index === 0 && marks.length ? { markLine: { silent: true, symbol: 'none', lineStyle: { color: p.dim, type: 'dashed' }, data: marks } } : {}),
      })),
    };
  });
}

// Lines on a time axis, each with its own dates: series from different
// calendars (FRED, futures, monthly prints) need no shared index.
// lines: [{ name, dates, values, color? (a colour or p => colour), axis?: 0|1, dashed?, width? }]
// options: { left?: axis-0 formatter, right?: axis-1 formatter, value?: tooltip
//   formatter (value, line) => text, markY?: [{ y, label }] on axis 0 }
export function timeLines(node, lines, options = {}) {
  return render(node, (option, p) => {
    const colorOf = (line, i) => (typeof line.color === 'function' ? line.color(p) : line.color) || SERIES_COLORS[i % SERIES_COLORS.length];
    // No formatter given: the adaptive default stays, so the decimals follow the ticks.
    const axis = (formatter, extra = {}) => ({
      ...option.yAxis,
      axisLabel: { ...option.yAxis.axisLabel, formatter: formatter || option.yAxis.axisLabel.formatter },
      ...extra,
    });
    const twoAxes = lines.some((l) => l.axis === 1);
    return {
      ...option,
      grid: { ...option.grid, left: 56, right: twoAxes ? 56 : 16, bottom: lines.length > 1 ? 52 : 28 },
      legend: lines.length > 1 ? {
        bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9,
      } : undefined,
      tooltip: {
        ...option.tooltip,
        valueFormatter: undefined,
        formatter: (items) => {
          const rows = [].concat(items).map((it) => {
            const line = lines[it.seriesIndex];
            const v = it.value?.[1];
            const text = options.value && v !== null && v !== undefined ? options.value(v, line) : formatValue(v);
            return `${it.marker}${it.seriesName} <b>${text}</b>`;
          });
          const first = [].concat(items)[0];
          return [first ? first.value[0] : '', ...rows].join('<br>');
        },
      },
      xAxis: { ...option.xAxis, type: 'time', boundaryGap: false, data: undefined },
      yAxis: twoAxes
        ? [axis(options.left), axis(options.right, { position: 'right', splitLine: { show: false } })]
        : axis(options.left),
      series: lines.map((line, i) => ({
        name: line.name,
        type: 'line',
        yAxisIndex: twoAxes ? line.axis || 0 : 0,
        data: line.dates.map((d, k) => [d, line.values[k]]),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: line.width || 1.3, color: colorOf(line, i), type: line.dashed ? 'dashed' : 'solid' },
        itemStyle: { color: colorOf(line, i) },
        markLine: i === 0 && options.markY?.length ? {
          silent: true, symbol: 'none',
          data: options.markY.map((m) => ({ yAxis: m.y, label: { formatter: m.label || '', color: p.dim, fontSize: 9, position: 'insideEndTop' } })),
          lineStyle: { color: p.faint, type: 'dashed' },
        } : undefined,
      })),
    };
  });
}
