// RISK: how much risk the market is pricing. One tile per series -- level,
// where it sits in its year and in its whole history, the week's change, and
// whether it is past the line written in config beforehand. No score. Tactical
// (1-4 weeks) and slow (months) sections are kept apart.

import { el, card, num, metaRow, DASH } from '../fmt.js';
import { render } from '../charts.js';
import { spark } from '../spark.js';

const HORIZONS = [
  ['tactical', 'TACTICAL · 1–4 WEEKS'],
  ['slow', 'SLOW · MONTHS'],
];
const present = (v) => v !== null && v !== undefined && Number.isFinite(v);

export function formatValue(value, unit) {
  if (!present(value)) return DASH;
  switch (unit) {
    case 'pct': return `${num(value, 1)}%`;
    case 'bp': return `${num(value, 0)}bp`;
    case 'usd_bn': return `${value > 0 ? '+' : ''}$${num(value, 0)}bn`;
    case 'ratio': return num(value, 2);
    case 'corr': return num(value, 2);
    case 'pct_oi': return `${value > 0 ? '+' : ''}${num(value, 1)}% OI`;
    case 'index': return num(value, 2);
    default: return num(value, 1);
  }
}

function formatChange(value, unit) {
  if (!present(value)) return DASH;
  const sign = value > 0 ? '+' : '';
  const digits = unit === 'bp' || unit === 'usd_bn' ? 0 : unit === 'ratio' || unit === 'corr' || unit === 'index' ? 2 : 1;
  return `${sign}${num(value, digits)}`;
}

function ordinal(n) {
  if (!present(n)) return DASH;
  const r = Math.round(n);
  const t = r % 100;
  return `${r}${t >= 11 && t <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[r % 10] || 'th')}`;
}

function thresholdText(tile) {
  if (tile.risk_when === 'extreme') return `tails: ≤${tile.threshold ?? 5}th / ≥${100 - (tile.threshold ?? 5)}th pct`;
  if (!present(tile.threshold)) return 'no threshold';
  return `risk ${tile.risk_when === 'high' ? '≥' : '≤'} ${formatValue(tile.threshold, tile.unit)}`;
}

// One tile. `onPick` makes it select the section's chart.
export function tileNode(tile, { asOf, onPick = null, selected = false, compact = false } = {}) {
  const state = tile.breach === true ? 'breach' : tile.breach === false ? 'clear' : 'unknown';
  const crossed = tile.crossed === 'into' ? 'NEW' : tile.crossed === 'out' ? 'CLEARED' : null;
  const stale = tile.date && asOf && tile.date !== asOf;
  const node = el('div', {
    class: `risk-tile ${state}${selected ? ' selected' : ''}${onPick ? ' pickable' : ''}`,
    title: [tile.note, ...(tile.sources || []).map((s) => `source: ${s}`), tile.backcalc, tile.error].filter(Boolean).join('\n'),
    onclick: onPick ? () => onPick(tile.key) : null,
  }, [
    el('div', { class: 'risk-tile-head' }, [
      el('span', { class: 'risk-tile-label', text: tile.label }),
      crossed ? el('span', { class: `risk-flag ${tile.crossed}`, text: crossed }) : null,
    ]),
    el('div', { class: 'risk-tile-value', text: tile.error && !present(tile.value) ? DASH : formatValue(tile.value, tile.unit) }),
    compact ? null : spark(tile.spark, {
      threshold: tile.risk_when === 'extreme' ? null : tile.threshold,
      color: state === 'breach' ? 'var(--down)' : 'var(--text-dim)',
    }),
    el('div', { class: 'risk-tile-meta', title: '1Y = percentile over the last year; ALL = over all history the source serves' }, [
      el('span', { text: `1Y ${ordinal(tile.pct_1y)} · ALL ${ordinal(tile.pct_long)}` }),
    ]),
    el('div', { class: 'risk-tile-meta dim' }, [el('span', { text: `1W ${formatChange(tile.change_1w, tile.unit)}` })]),
    compact ? null : el('div', { class: 'risk-tile-foot dim' }, [
      thresholdText(tile),
      stale ? ` · ${tile.frequency === 'weekly' ? 'week of ' : ''}${tile.date}` : '',
      tile.error && !present(tile.value) ? ` · ${tile.error}` : '',
    ].join('')),
  ]);
  return node;
}

function historyChart(node, tile) {
  const h = tile.history || { dates: [], values: [] };
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 56, right: 16, top: 14 },
    tooltip: { ...option.tooltip, valueFormatter: (v) => formatValue(v, tile.unit) },
    xAxis: { ...option.xAxis, data: h.dates },
    yAxis: { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => formatValue(v, tile.unit) } },
    series: [{
      name: tile.label, type: 'line', data: h.values, showSymbol: false,
      lineStyle: { width: 1.3, color: tile.breach ? p.down : p.text },
      markLine: tile.risk_when !== 'extreme' && present(tile.threshold) ? {
        silent: true, symbol: 'none', data: [{ yAxis: tile.threshold }],
        lineStyle: { color: p.down, type: 'dashed', opacity: 0.7 },
        label: { color: p.down, fontSize: 9, formatter: `threshold ${formatValue(tile.threshold, tile.unit)}`, position: 'insideEndTop' },
      } : undefined,
    }],
  }));
}

function termChart(node, charts) {
  const vix = charts.vix_term || { labels: [], curves: [] };
  const vx = charts.vx_curve || { curves: [] };
  const names = { 0: 'today', 7: '1 week ago', 30: '1 month ago' };
  render(node, (option, p) => {
    const tones = { 0: p.text, 7: p.accent, 30: p.faint };
    return {
      ...option,
      grid: [{ left: 40, right: '53%', top: 34, bottom: 30 }, { left: '55%', right: 12, top: 34, bottom: 30 }],
      legend: { top: 0, textStyle: { color: p.dim, fontSize: 10 }, itemWidth: 12, itemHeight: 2, icon: 'rect' },
      title: [
        { text: 'VIX INDICES BY TENOR', left: 40, top: 16, textStyle: { color: p.dim, fontSize: 9, fontWeight: 'normal' } },
        { text: 'VIX FUTURES · M1 = NEAREST EXPIRY', left: '55%', top: 16, textStyle: { color: p.dim, fontSize: 9, fontWeight: 'normal' } },
      ],
      tooltip: { ...option.tooltip, trigger: 'axis' },
      xAxis: [
        { ...option.xAxis, gridIndex: 0, boundaryGap: true, data: vix.labels },
        // By position, nearest contract first: M1 a month ago is a different contract from M1 today.
        { ...option.xAxis, gridIndex: 1, boundaryGap: true, data: (vx.curves[0]?.settles || []).map((_, i) => `M${i + 1}`) },
      ],
      yAxis: [{ ...option.yAxis, gridIndex: 0 }, { ...option.yAxis, gridIndex: 1 }],
      series: [
        ...vix.curves.map((c) => ({
          name: names[c.lag_days], type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: c.values, symbolSize: 5,
          lineStyle: { width: c.lag_days ? 1 : 2, color: tones[c.lag_days], type: c.lag_days === 30 ? 'dashed' : 'solid' },
          itemStyle: { color: tones[c.lag_days] },
        })),
        ...vx.curves.map((c) => ({
          name: names[c.lag_days], type: 'line', xAxisIndex: 1, yAxisIndex: 1,
          // Align by position: each curve's nearest expiry first.
          data: c.settles, symbolSize: 5,
          lineStyle: { width: c.lag_days ? 1 : 2, color: tones[c.lag_days], type: c.lag_days === 30 ? 'dashed' : 'solid' },
          itemStyle: { color: tones[c.lag_days] },
        })),
      ],
    };
  });
}

function sectionCard(section, data) {
  const tiles = section.tiles;
  let selected = tiles.find((t) => t.breach)?.key || tiles[0]?.key;
  const grid = el('div', { class: 'risk-grid' });
  const chartNode = el('div', { class: 'chart' });
  const chartTitle = el('span', { class: 'dim' });
  const draw = () => {
    grid.replaceChildren(...tiles.map((t) => tileNode(t, { asOf: data.as_of, onPick: (key) => { selected = key; draw(); }, selected: t.key === selected })));
    const tile = tiles.find((t) => t.key === selected);
    if (tile) {
      chartTitle.textContent = `${tile.label} · weekly · 10 years or since ${tile.since}`;
      historyChart(chartNode, tile);
    }
  };
  const breached = tiles.filter((t) => t.breach).length;
  const body = [grid, el('div', { class: 'risk-chart-head' }, [chartTitle]), chartNode];
  if (section.key === 'volatility') {
    const termNode = el('div', { class: 'chart' });
    body.push(el('div', { class: 'risk-chart-head' }, [el('span', { class: 'dim', text: 'TERM STRUCTURE · today, a week and a month ago' })]), termNode);
    requestAnimationFrame(() => termChart(termNode, data.charts || {}));
  }
  requestAnimationFrame(draw);
  return card(section.label, el('span', { class: breached ? 'down' : 'dim', text: breached ? `${breached} of ${tiles.length} past threshold` : `${tiles.length} series · none past threshold` }), body);
}

function summary(data) {
  const chips = (items, cls) => items.map((b) => el('span', { class: `mchip ${cls}`, text: `${b.label} ${formatValue(b.value, b.unit)}` }));
  const byHorizon = (h) => data.breaches.filter((b) => b.horizon === h);
  const stat = (label, value, note, cls = '') => el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note' }, note) : null,
  ]);
  const total = data.sections.reduce((n, s) => n + s.tiles.length, 0);
  return el('div', { class: 'stat-strip risk-summary' }, [
    stat('PAST THRESHOLD · TACTICAL', String(byHorizon('tactical').length), chips(byHorizon('tactical'), 'down'), byHorizon('tactical').length ? 'down' : ''),
    stat('PAST THRESHOLD · SLOW', String(byHorizon('slow').length), chips(byHorizon('slow'), 'down'), byHorizon('slow').length ? 'down' : ''),
    stat('CHANGED THIS WEEK', String(data.crossed.length),
      data.crossed.map((b) => el('span', { class: `mchip ${b.crossed === 'into' ? 'down' : 'up'}`, text: `${b.label} ${b.crossed === 'into' ? '↑ in' : '↓ out'}` }))),
    stat('SERIES', String(total), [`${Object.keys(data.failed || {}).length} source(s) failed`]),
  ]);
}

function methodNotes() {
  return [
    'Each tile is one series. Level; 1Y = its percentile over the last 365 days; ALL = its percentile over all the history the source serves (the start is in the chart title); 1W = change over a week. Nothing is combined into a score.',
    'Thresholds were written in config/dashboard.toml on 2026-09-26, before this page drew any series, and are not fitted to it. A red tile is past its line; NEW means it was not a week ago, CLEARED that it was. Positioning and the put/call ratio are read at extremes: the tails of their own history (≤5th or ≥95th percentile), not a level.',
    'Back-calculated history: VIX3M, VIX9D, VIX6M, VIX1Y, VVIX, SKEW and COR1M were launched after the first row of their files; the earlier part is Cboe\'s back-calculation from the option prices of the day, not a value published then. Their ALL percentiles lean on that stretch; each tile says so on hover.',
    'Credit: FRED now serves ICE BofA spreads (HY, IG, CCC) for the last three years only, so their ALL percentile spans those years. Moody\'s Baa − 10Y runs to 1986 and is the long credit series.',
    'CFTC positions are as of Tuesday and published the following Friday; a tile\'s date is the position date. Leveraged-money net is long − short as a share of open interest; contract codes are used so the history runs through CFTC\'s 2022 renaming.',
    'Realised correlation and dispersion come from the S&P 500 members\' own closes and today\'s SPY weights over 21 sessions: correlation = (σI² − Σw²σ²) / ((Σwσ)² − Σw²σ²), dispersion = √(Σwσ² − σI²), annualised. Members are today\'s.',
    'Not included: AAII sentiment (the file refuses non-browser clients), NAAIM (no machine-readable file), CNN Fear & Greed (a composite score, and the endpoint refuses non-browser clients). docs/risk_sources.md has each probe.',
  ];
}

export default function renderRisk(root, data) {
  root.append(metaRow(`RISK · ${data.sections.reduce((n, s) => n + s.tiles.length, 0)} SERIES · AS OF ${data.as_of} · CLICK A TILE FOR ITS HISTORY`, methodNotes()));
  root.append(summary(data));
  for (const [horizon, label] of HORIZONS) {
    const sections = data.sections.filter((s) => s.horizon === horizon);
    if (!sections.length) continue;
    root.append(el('h2', { class: 'section-title risk-horizon', text: label }));
    const wrap = el('div', { class: 'grid two risk-sections' }, sections.map((s) => sectionCard(s, data)));
    root.append(wrap);
  }
}
