// The RAMP TOKENOMICS card's body: one control bar (metric, breakdown or token
// type, display, scale, range) shared by the chart and the table, one full-width
// line chart, the latest week's table, and what the numbers are not. The
// arithmetic lives in ramp-tokenomics-model.js; this file only draws it.

import { el, notice, gap, table, periodSwitch, DASH } from './fmt.js';
import { render, SERIES_COLORS } from './charts.js';
import {
  RANGES, pickSeries, rangeStartIndex, shareSeries, logValues, defaultVisible,
  latestIndex, latestRows, formatVolume, formatSpend, formatPrice, formatPriceValue, formatShare,
} from './ramp-tokenomics-model.js';

const METRICS = ['VOLUME', 'SPEND', 'PRICE'];
const BREAKDOWNS = ['BY MAKER', 'BY MODEL'];
const DISPLAYS = ['LEVEL', 'SHARE'];
const SCALES = ['LOG', 'RAW'];
const TOKEN_TYPES = ['ALL', 'UNCACHED INPUT', 'OUTPUT'];
const CHART_HEIGHT = 'height:360px';
// A newest observation older than this many days gets a visible warning.
const STALE_DAYS = 21;

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

// Per metric: the level formatter (tooltip and table), the axis formatter, the title.
const LEVEL = { VOLUME: formatVolume, SPEND: formatSpend, PRICE: formatPrice };
const AXIS = { VOLUME: formatVolume, SPEND: formatSpend, PRICE: formatPriceValue };
const TITLE = {
  VOLUME: 'TOKEN VOLUME · BILLION TOKENS A WEEK',
  SPEND: 'SPEND · USD MILLION A WEEK',
  PRICE: 'OBSERVED PRICE · USD PER MILLION TOKENS, DAILY',
};
const SHARE_TITLE = {
  VOLUME: 'TOKEN VOLUME · SHARE OF REPORTED SAMPLE',
  SPEND: 'SPEND · SHARE OF REPORTED SAMPLE',
};

function control(label, node) {
  return el('span', { class: 'tag-row' }, [el('span', { class: 'dim', text: label }), node]);
}

// The axis tooltip: the date, then each series' own figure (the raw level, not
// the log-safe copy). In LEVEL mode a volume or spend figure also gives its
// share of the reported sample when there is one.
function tooltipOf(series, dates, { weekly, share, fmt }) {
  const byName = new Map(series.map((s) => [s.name, s]));
  return (params) => {
    const list = [].concat(params);
    if (!list.length) return '';
    const i = list[0].dataIndex;
    const date = dates[i];
    const head = date === undefined ? '' : weekly ? `week ending ${date}` : String(date);
    const rows = list.map((q) => {
      const s = byName.get(q.seriesName);
      if (!s) return '';
      const level = s.raw[i];
      const sharePart = !share && isNum(level) && isNum(s.shares[i]) ? ` · ${formatShare(s.shares[i])} of sample` : '';
      return `${q.marker}${esc(q.seriesName)} ${share ? formatShare(s.shares[i]) : fmt(level)}${sharePart}`;
    });
    return [esc(head), ...rows].join('<br/>');
  };
}

export function ramptokenomicsCharts(payload) {
  const p = payload !== null && typeof payload === 'object' ? payload : {};
  const state = { metric: 'VOLUME', breakdown: 'BY MAKER', display: 'LEVEL', scale: 'RAW', tokenType: 'ALL', range: '6M' };
  // The legend's selection, per series group (metric and breakdown, or token
  // type), so a toggle survives a switch to another group and back.
  const selections = new Map();

  const metricNode = periodSwitch(METRICS, state.metric, (v) => { state.metric = v; draw(); });
  const breakdownNode = periodSwitch(BREAKDOWNS, state.breakdown, (v) => { state.breakdown = v; draw(); });
  const displayNode = periodSwitch(DISPLAYS, state.display, (v) => { state.display = v; draw(); });
  const tokenNode = periodSwitch(TOKEN_TYPES, state.tokenType, (v) => { state.tokenType = v; draw(); });
  const scaleNode = periodSwitch(SCALES, state.scale, (v) => { state.scale = v; draw(); });
  const rangeNode = periodSwitch(RANGES, state.range, (v) => { state.range = v; draw(); });
  const controls = {
    metric: control('METRIC', metricNode),
    breakdown: control('BREAKDOWN', breakdownNode),
    display: control('DISPLAY', displayNode),
    token: control('TOKEN TYPE', tokenNode),
    scale: control('SCALE', scaleNode),
    range: control('RANGE', rangeNode),
  };
  const bar = el('div', { class: 'chart-head' }, [el('span', { class: 'tag-row' }, Object.values(controls))]);

  const title = el('span', { class: 'card-title' });
  const hint = el('span', { class: 'dim' });
  const node = el('div', { class: 'chart', style: CHART_HEIGHT });
  const tableCaption = el('div', { class: 'card-title' });
  const tableHost = el('div', {});

  const shown = p.models_shown ?? DASH;
  const total = p.models_total ?? DASH;
  const stale = isNum(p.stale_days) && p.stale_days > STALE_DAYS
    ? notice(`The newest observation is ${p.stale_days} days old.`)
    : null;
  const notes = [
    'Ramp Token Spend Management: usage and billing of connected providers from participating Ramp businesses. This is not Ramp\'s monthly AI Index sample and does not represent total Ramp AI spend, any provider\'s revenue, or ARR.',
    `Weeks run Monday to Sunday. Model series keep Ramp's raw identifiers, including aliases: they are not a count of distinct models. Showing the top ${shown} of ${total}; shares use every reported series.`,
    'Spend and volume have different coverage, so spend divided by volume is not a price. Prices are observed effective prices (rolling 7-day cost / tokens), not list prices; the all-token price also moves with the mix of input, output and cached tokens; only OpenAI and Anthropic are covered, with no model-level prices.',
    'Missing weeks are gaps; reported zeros are zeros.',
  ].map((text) => el('div', { class: 'field-note', text }));

  const draw = () => {
    const isPrice = state.metric === 'PRICE';
    const share = !isPrice && state.display === 'SHARE';
    const log = !share && state.scale === 'LOG';

    // Controls that do not apply to this metric are hidden; SCALE is off for SHARE.
    controls.breakdown.style.display = isPrice ? 'none' : '';
    controls.display.style.display = isPrice ? 'none' : '';
    controls.token.style.display = isPrice ? '' : 'none';
    for (const b of scaleNode.querySelectorAll('button')) b.disabled = share;
    controls.scale.style.opacity = share ? '0.35' : '';
    controls.scale.title = share ? 'Share is always linear' : '';

    const picked = pickSeries(p, { metric: state.metric, breakdown: state.breakdown, tokenType: state.tokenType });
    const start = rangeStartIndex(picked.dates, state.range);
    const dates = picked.dates.slice(start);
    const group = isPrice ? `PRICE|${state.tokenType}` : `${state.metric}|${state.breakdown}`;
    if (!selections.has(group)) {
      const visible = defaultVisible(picked.series, p, isPrice ? 'BY MAKER' : state.breakdown);
      selections.set(group, Object.fromEntries(picked.series.map((s) => [s.name, visible.has(s.key)])));
    }

    // Colours follow each series' index in the full list, not the visible list.
    const series = picked.series.map((s, index) => {
      const raw = s.values.slice(start);
      const shares = shareSeries(s.values, picked.total).slice(start);
      const plotted = share ? shares : raw;
      return { name: s.name, index, raw, shares, plotted: log ? logValues(plotted) : plotted };
    });

    title.textContent = share ? SHARE_TITLE[state.metric] : TITLE[state.metric];
    hint.textContent = share ? 'linear · shares of every reported series' : log ? 'log scale' : 'linear';

    const onLegend = (selected) => selections.set(group, { ...selected });
    const chart = render(node, (option, pal) => ({
      ...option,
      grid: { left: 64, right: 16, top: 52, bottom: 26 },
      legend: {
        type: 'scroll',
        top: 0,
        textStyle: { color: pal.dim, fontSize: 9 },
        pageTextStyle: { color: pal.dim },
        itemWidth: 10,
        itemHeight: 2,
        selected: selections.get(group),
      },
      tooltip: { ...option.tooltip, trigger: 'axis', formatter: tooltipOf(series, dates, { weekly: !isPrice, share, fmt: share ? formatShare : LEVEL[state.metric] }) },
      xAxis: { ...option.xAxis, data: dates },
      yAxis: {
        ...option.yAxis,
        type: log ? 'log' : 'value',
        scale: true,
        ...(share ? { min: 0 } : {}),
        axisLabel: { color: pal.dim, fontSize: 9, formatter: share ? formatShare : AXIS[state.metric] },
      },
      series: series.map((s) => {
        const color = SERIES_COLORS[s.index % SERIES_COLORS.length];
        return {
          name: s.name,
          type: 'line',
          data: s.plotted,
          // Weekly points are few enough to mark, so a lone week between gaps still shows.
          showSymbol: !isPrice,
          symbolSize: 4,
          connectNulls: false,
          lineStyle: { width: 1.4, color },
          itemStyle: { color },
        };
      }),
    }));
    if (chart) chart.on('legendselectchanged', (e) => onLegend(e.selected));

    // The table: the latest week (latest day for prices) with any figure, every
    // series of the breakdown, and no change columns.
    const idx = latestIndex(picked.series);
    const when = idx < 0 ? DASH : picked.dates[idx] ?? DASH;
    tableCaption.textContent = isPrice
      ? `LATEST DAY WITH DATA · ${when}`
      : `LATEST WEEK WITH DATA · WEEK ENDING ${when} · ${String(picked.unitLabel).toUpperCase()}`;
    if (!picked.series.length) {
      tableHost.replaceChildren(gap('No series in this build for this selection.'));
    } else {
      const rows = latestRows(picked.series, picked.total).map((r) => el('tr', {}, [
        el('td', { text: r.name }),
        el('td', { text: LEVEL[state.metric](r.value) }),
        ...(isPrice ? [] : [el('td', { class: 'dim', text: formatShare(r.share) })]),
      ]));
      const headers = isPrice ? ['SERIES', 'VALUE'] : ['SERIES', 'VALUE', 'SHARE OF REPORTED SAMPLE'];
      tableHost.replaceChildren(table(headers, rows));
    }
  };

  // The chart needs its node in the page to size itself, so the first draw waits a frame.
  requestAnimationFrame(draw);
  return el('div', { class: 'ramp-tokenomics' }, [
    bar,
    el('div', { class: 'chart-head' }, [title, hint]),
    node,
    tableCaption,
    tableHost,
    stale,
    ...notes,
  ]);
}
