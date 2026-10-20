// Uses the dashboard's existing chart runtime and palette, not another renderer.
import { render } from './charts.js';
import { finite } from './reverse-dcf-math.js';
import { niceStepFromRange } from './axis-format.js';

const percent = (v) => finite(v) ? `${v.toFixed(1)}%` : '—';

export function historyOption(base, p, history, scenario, value, metric, asOf) {
  const rows = history.rows;
  const path = value?.error ? [] : value?.path || [];
  const projectionLabels = path.length ? [`NOW ${asOf}`, ...path.map((r) => `M${r.year}`)] : [];
  const labels = [...rows.map((r) => r.period_end), ...projectionLabels];
  const padding = projectionLabels.map(() => null);
  const historical = (key) => [...rows.map((r) => r[key]), ...padding];
  const scenarioValues = metric === 'growth' ? path.map(() => scenario.growth * 100) : path.map((r) => r.margin * 100);
  const seed = metric === 'growth' ? null : scenario?.baseMargin * 100;
  const series = [{ name: metric === 'growth' ? 'Reported YoY growth' : 'Operating margin', type: 'line',
    data: historical(metric === 'growth' ? 'growth' : 'operatingMargin'), connectNulls: false,
    showSymbol: true, symbolSize: 5, lineStyle: { color: p.blue, width: 2 }, itemStyle: { color: p.blue } }];
  if (metric !== 'growth') series.push({ name: 'Gross margin', type: 'line', data: historical('grossMargin'), connectNulls: false,
    showSymbol: true, symbolSize: 4, lineStyle: { color: p.dim, width: 1.5 }, itemStyle: { color: p.dim } });
  if (path.length) series.push({ name: 'Scenario (dashed)', type: 'line',
    data: [...rows.map(() => null), seed, ...scenarioValues], connectNulls: false,
    showSymbol: true, symbolSize: 4, lineStyle: { color: p.accent, width: 2, type: 'dashed' }, itemStyle: { color: p.accent },
    markArea: { silent: true, itemStyle: { color: p.accent, opacity: 0.05 }, data: [[{ xAxis: projectionLabels[0] }, { xAxis: projectionLabels.at(-1) }]] } });
  return { ...base, grid: { ...base.grid, left: 55, bottom: 70, top: 20 },
    legend: { bottom: 0, type: 'scroll', textStyle: { color: p.dim }, itemWidth: 12 },
    tooltip: { ...base.tooltip, valueFormatter: percent },
    xAxis: { ...base.xAxis, data: labels, axisLabel: { ...base.xAxis.axisLabel, formatter: (v) => v.startsWith('NOW') ? 'NOW' : v.startsWith('M') ? v : v.slice(0, 4) } },
    yAxis: { ...base.yAxis, axisLabel: { ...base.yAxis.axisLabel, formatter: (v) => `${v}%` } }, series };
}

export function frontierOption(base, p, curves, history, scenario, cfg, box = null) {
  const colors = [p.blue, p.accent, p.purple];
  const series = curves.map((curve, i) => ({ name: `WACC ${percent(curve.wacc * 100)}`, type: 'line', data: curve.points,
    connectNulls: false, showSymbol: false, lineStyle: { width: curve.shift === 0 ? 2.5 : 1.5, type: curve.shift === 0 ? 'solid' : 'dashed', color: colors[i % colors.length] }, itemStyle: { color: colors[i % colors.length] } }));
  // The box is where the company's own evidence sits: analysts' growth range
  // across its reported margin range. A WACC curve crossing it means the
  // price is met by outcomes already inside that evidence.
  const area = box ? { silent: true, itemStyle: { color: p.accent, opacity: 0.28, borderColor: p.accent, borderWidth: 1.5 },
    label: { show: true, position: 'insideTopLeft', color: p.dim, fontSize: 10, formatter: 'own evidence' },
    data: [[{ xAxis: box.growth[0], yAxis: box.margin[0] }, { xAxis: box.growth[1], yAxis: box.margin[1] }]] } : undefined;
  series.push({ name: 'Your growth / margin', type: 'scatter', symbol: 'diamond', symbolSize: 12,
    data: [[scenario.growth * 100, scenario.margin * 100]], itemStyle: { color: p.text }, markArea: area,
    markLine: history.margin.n ? { silent: true, symbol: 'none', lineStyle: { color: p.dim, type: 'dotted' },
      data: [{ yAxis: history.margin.median, label: { show: false } }] } : undefined });
  const xs = curves.flatMap((c) => c.points.map(([x]) => x));
  // Fit the height to the chosen-WACC curve where the box is (the question
  // the chart answers), so a narrow margin range is not lost under 0-100%.
  // Other curves may leave the top; ECharts clips them.
  const chosen = curves.find((c) => c.shift === 0) || curves[0];
  const near = (chosen?.points || []).filter(([x, y]) => finite(y) && (!box || (x >= box.growth[0] - 1 && x <= box.growth[1] + 1)));
  const ys = [...(near.length ? near : curves.flatMap((c) => c.points)).map(([, y]) => y), scenario.margin * 100, history.margin.max, box?.margin?.[1]].filter(finite);
  // Never cutting off the scenario or the median.
  const fitted = Math.min(cfg.margin_bounds_pct[1], Math.max(10, Math.ceil(Math.max(...ys) * 1.25 / 10) * 10));
  const yTop = Math.max(fitted, ...[scenario.margin * 100, history.margin.median].filter(finite));
  return { ...base, grid: { ...base.grid, left: 55, top: 24, bottom: 77 },
    legend: { bottom: 0, type: 'scroll', textStyle: { color: p.dim }, itemWidth: 12 },
    tooltip: { ...base.tooltip, valueFormatter: undefined, formatter: (items) => [].concat(items).map((item) => `${item.marker}${item.seriesName}: growth ${percent(item.value?.[0])}, margin ${percent(item.value?.[1])}`).join('<br>') },
    xAxis: { ...base.xAxis, type: 'value', data: undefined, name: 'Revenue growth (% / year)', nameLocation: 'middle', nameGap: 30,
      min: xs.length ? Math.min(...xs) : undefined, max: xs.length ? Math.max(...xs) : undefined,
      nameTextStyle: { color: p.dim }, axisLabel: { ...base.xAxis.axisLabel, formatter: (v) => `${v}%` } },
    yAxis: { ...base.yAxis, name: 'Required operating margin', nameTextStyle: { color: p.dim },
      min: Math.min(cfg.margin_bounds_pct[0], ...[scenario.margin * 100, history.margin.median].filter(finite)), max: yTop,
      axisLabel: { ...base.yAxis.axisLabel, formatter: (v) => `${v}%` } }, series };
}

export function sensitivityOption(base, p, rows, targetEv) {
  const shares = [...new Set(rows.map((r) => r.netInvestment))];
  const colors = [p.blue, p.accent, p.purple];
  // ECharts markLine does not extend the value axis automatically. Include
  // working EV explicitly, even when every scenario is below (or above) it.
  const evB = targetEv / 1e9;
  const extent = rows.map((r) => finite(r.ev) ? r.ev / 1e9 : null).filter(finite);
  const low = Math.min(evB, ...extent), high = Math.max(evB, ...extent);
  const padding = (high - low || Math.abs(evB) || 1) * .08;
  const tickStep = niceStepFromRange(low - padding, high + padding);
  return { ...base, grid: { ...base.grid, left: 62, top: 24, bottom: 77 },
    legend: { bottom: 0, type: 'scroll', textStyle: { color: p.dim }, itemWidth: 12 },
    tooltip: { ...base.tooltip, valueFormatter: undefined, formatter: (items) => [].concat(items).map((item) => `${item.marker}${item.seriesName}: WACC ${percent(item.value?.[0])}, EV ${finite(item.value?.[1]) ? `$${item.value[1].toFixed(2)}B` : '—'}`).join('<br>') },
    xAxis: { ...base.xAxis, type: 'value', scale: true, data: undefined, name: 'WACC (%)', nameLocation: 'middle', nameGap: 30,
      nameTextStyle: { color: p.dim }, axisLabel: { ...base.xAxis.axisLabel, formatter: (v) => `${v}%` } },
    yAxis: { ...base.yAxis, min: Math.floor((low - padding) / tickStep) * tickStep,
      max: Math.ceil((high + padding) / tickStep) * tickStep, interval: tickStep,
      name: 'Model EV ($B)', nameTextStyle: { color: p.dim } },
    series: shares.map((share, i) => ({ name: `Reinvest ${percent(share * 100)}`, type: 'line',
      data: rows.filter((r) => r.netInvestment === share).map((r) => [r.wacc * 100, finite(r.ev) ? r.ev / 1e9 : null]),
      connectNulls: false, showSymbol: true, symbolSize: 6,
      lineStyle: { color: colors[i % colors.length], width: 2, type: i === 1 ? 'solid' : 'dashed' }, itemStyle: { color: colors[i % colors.length] },
      markLine: i === 0 ? { silent: true, symbol: 'none', lineStyle: { color: p.dim, type: 'dotted' }, label: { show: false }, data: [{ yAxis: targetEv / 1e9 }] } : undefined })) };
}

export const drawHistory = (node, ...args) => render(node, (base, p) => historyOption(base, p, ...args));
export const drawFrontier = (node, ...args) => render(node, (base, p) => frontierOption(base, p, ...args));
export const drawSensitivity = (node, ...args) => render(node, (base, p) => sensitivityOption(base, p, ...args));
