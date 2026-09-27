// RISK: how much risk the market is pricing. The systematic anchor and ten
// core series first; every other series folded beneath, by group. One tile
// per series -- level, where it sits in its year and in its whole history,
// the week's change, and whether it is past the line written in config
// beforehand. No score.

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

// The long percentile names its span: ICE spreads reach back three years,
// SPX a century, and "ALL" alone read the same for both.
function sinceLabel(tile) {
  return tile.since ? `${tile.since.slice(0, 4)}–` : 'ALL';
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
    el('div', { class: 'risk-tile-meta', title: 'Percentile over the last year, and over all the history the source serves' }, [
      el('span', { text: `1Y ${ordinal(tile.pct_1y)} · ${sinceLabel(tile)} ${ordinal(tile.pct_long)}` }),
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

// `charts` histories are drawn one above the other; a click puts that tile's history
// first and drops the oldest. Series past their line are shown first.
function sectionCard(section, data, { charts = 1 } = {}) {
  const tiles = section.tiles;
  let selected = [...tiles.filter((t) => t.breach), ...tiles.filter((t) => !t.breach)].slice(0, charts).map((t) => t.key);
  const grid = el('div', { class: 'risk-grid' });
  const slots = selected.map(() => ({ node: el('div', { class: 'chart' }), title: el('span', { class: 'dim' }) }));
  const pick = (key) => {
    if (selected.includes(key)) return;
    selected = [key, ...selected].slice(0, charts);
    draw();
  };
  const draw = () => {
    grid.replaceChildren(...tiles.map((t) => tileNode(t, { asOf: data.as_of, onPick: pick, selected: selected.includes(t.key) })));
    selected.forEach((key, i) => {
      const tile = tiles.find((t) => t.key === key);
      if (!tile) return;
      slots[i].title.textContent = `${tile.label} · weekly · 10 years or since ${tile.since}`;
      historyChart(slots[i].node, tile);
    });
  };
  const chartBlocks = slots.map((slot) => el('div', {}, [el('div', { class: 'risk-chart-head' }, [slot.title]), slot.node]));
  const breached = tiles.filter((t) => t.breach).length;
  const body = [grid, charts > 1 ? el('div', { class: 'risk-charts' }, chartBlocks) : chartBlocks[0]];
  if (section.key === 'volatility') {
    const termNode = el('div', { class: 'chart' });
    body.push(el('div', { class: 'risk-chart-head' }, [el('span', { class: 'dim', text: 'TERM STRUCTURE · today, a week and a month ago' })]), termNode);
    requestAnimationFrame(() => termChart(termNode, data.charts || {}));
  }
  requestAnimationFrame(draw);
  return card(section.label, el('span', { class: breached ? 'down' : 'dim', text: breached ? `${breached} of ${tiles.length} past threshold` : `${tiles.length} series · none past threshold` }), body);
}

const pctOf = (v) => (present(v) ? `${Math.round(v * 100)}%` : DASH);

function anchorCard(a) {
  if (!a || a.unavailable) return card('SYSTEMATIC ANCHOR', null, el('div', { class: 'gap', text: 'The anchor was not built for this session.' }));
  const c = a.components;
  const chip = (text, cls = '') => el('span', { class: `mchip ${cls}`, text });
  const chartNode = el('div', { class: 'chart short' });
  const keep = 252;
  const h = { dates: a.history.dates.slice(-keep), exposure: a.history.exposure.slice(-keep), spy: a.history.spy.slice(-keep) };
  requestAnimationFrame(() => render(chartNode, (option, p) => ({
    ...option,
    grid: { left: 36, right: 40, top: 8, bottom: 22 },
    tooltip: { ...option.tooltip, trigger: 'axis' },
    xAxis: { ...option.xAxis, data: h.dates },
    yAxis: [
      { ...option.yAxis, min: 0, max: 1, axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => `${Math.round(v * 100)}%` } },
      { ...option.yAxis, position: 'right', splitLine: { show: false }, axisLabel: { color: p.faint, fontSize: 9 } },
    ],
    series: [
      { name: 'anchor exposure', type: 'line', step: 'end', data: h.exposure, showSymbol: false, areaStyle: { opacity: 0.12 }, lineStyle: { width: 1.4, color: p.accent }, itemStyle: { color: p.accent } },
      { name: 'SPY', type: 'line', yAxisIndex: 1, data: h.spy, showSymbol: false, lineStyle: { width: 1, color: p.faint } },
    ],
  })));
  const last = a.changes[a.changes.length - 1];
  return card('SYSTEMATIC ANCHOR · EQUITY EXPOSURE', el('span', { class: 'dim', text: 'quantamental-lab frozen v1' }), [
    el('div', { class: 'anchor-head' }, [
      el('span', { class: 'anchor-value', text: pctOf(a.held) }),
      el('span', { class: 'dim', text: `held · next session ${pctOf(a.next)}${last ? ` · since ${last.date}` : ''}` }),
    ]),
    el('div', { class: 'anchor-chips' }, [
      chip(`VOL ${present(c.realised_vol) ? num(c.realised_vol * 100, 1) : DASH}% → ×${num(c.vol_scaled, 2)}`),
      chip(`TREND ${c.trend_on ? 'ON · SPY > 200D' : 'OFF · cap 50%'}`, c.trend_on ? 'up' : 'down'),
      chip(`COPPER/OIL ${c.copper_oil_on === false ? `OFF · z ${num(c.copper_oil_z, 2)} · cap 50%` : c.copper_oil_on ? `ON · z ${num(c.copper_oil_z, 2)}` : DASH}`, c.copper_oil_on === false ? 'down' : 'up'),
      chip(`DRAWDOWN LADDER ×${num(c.ladder, 1)}`, c.ladder < 1 ? 'down' : ''),
    ]),
    chartNode,
  ]);
}

// Self-computed after CNN's seven components (compute/sentiment.py); it
// follows CNN's outline, not its number.
const FG_UNITS = { momentum: '%', strength: '% of members', breadth: '', put_call: '', volatility: '%', safe_haven: 'pp', junk_bond: 'bp' };
function fgReading(c) {
  if (!present(c.value)) return DASH;
  const digits = c.key === 'breadth' || c.key === 'junk_bond' ? 0 : 2;
  const signedKeys = ['momentum', 'strength', 'volatility', 'safe_haven'];
  const text = `${signedKeys.includes(c.key) && c.value > 0 ? '+' : ''}${num(c.value, digits)}`;
  const unit = FG_UNITS[c.key] ?? '';
  return unit ? `${text}${unit.startsWith('%') && unit.length > 1 ? ` ${unit}` : unit}` : text;
}

function sentimentCard(g) {
  const head = el('span', { class: 'dim', text: 'self-computed · not CNN\'s index' });
  if (!g || !present(g.score)) return card('FEAR & GREED', head, el('div', { class: 'gap', text: `Not computed this session${g?.error ? `: ${g.error}` : ''}.` }));
  const tone = (v) => (!present(v) ? 'dim' : v < 45 ? 'down' : v > 55 ? 'up' : '');
  const chartNode = el('div', { class: 'chart short' });
  requestAnimationFrame(() => render(chartNode, (option, p) => ({
    ...option,
    grid: { left: 30, right: 12, top: 8, bottom: 22 },
    tooltip: { ...option.tooltip, trigger: 'axis' },
    xAxis: { ...option.xAxis, data: g.history.dates },
    yAxis: { ...option.yAxis, min: 0, max: 100, interval: 25, axisLabel: { color: p.dim, fontSize: 9 } },
    series: [{
      name: 'fear & greed', type: 'line', data: g.history.score, showSymbol: false, lineStyle: { width: 1.3, color: p.text },
      markArea: { silent: true, data: [
        [{ yAxis: 0, itemStyle: { color: p.down, opacity: 0.08 } }, { yAxis: 25 }],
        [{ yAxis: 75, itemStyle: { color: p.up, opacity: 0.08 } }, { yAxis: 100 }],
      ] },
      markLine: { silent: true, symbol: 'none', data: [{ yAxis: 50 }], lineStyle: { color: p.faint, type: 'dashed' }, label: { show: false } },
    }],
  })));
  const rows = g.components.map((c) => el('tr', {}, [
    el('td', { class: 'fg-label', text: c.label }),
    el('td', { class: 'dim', text: fgReading(c) }),
    el('td', { class: 'fg-bar-cell' }, [el('span', { class: 'fg-bar' }, [el('span', { class: `fg-bar-fill ${tone(c.score)}`, style: `width:${present(c.score) ? c.score : 0}%` })])]),
    el('td', { class: tone(c.score), text: present(c.score) ? num(c.score, 0) : DASH }),
  ]));
  const ago = (label, v) => `${label} ${present(v) ? num(v, 0) : DASH}`;
  return card('FEAR & GREED', head, [
    el('div', { class: 'anchor-head' }, [
      el('span', { class: `anchor-value fg-value ${tone(g.score)}`, text: num(g.score, 0) }),
      el('span', { class: tone(g.score), text: g.rating }),
      el('span', { class: 'dim', text: `${ago('1W', g.week_ago)} · ${ago('1M', g.month_ago)} · ${ago('1Y', g.year_ago)}${g.components_counted < g.components.length ? ` · ${g.components_counted} of ${g.components.length} components` : ''}` }),
    ]),
    chartNode,
    el('div', { class: 'table-scroll' }, [el('table', { class: 'data fg-table' }, [
      el('thead', {}, [el('tr', {}, ['COMPONENT', 'READING', '', 'SCORE'].map((h) => el('th', { text: h })))]),
      el('tbody', {}, rows),
    ])]),
  ]);
}

function summary(data, core) {
  const past = core.filter((t) => t.breach);
  const others = data.sections.flatMap((s) => s.tiles).filter((t) => !t.core);
  const stat = (label, value, note, cls = '') => el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note' }, note) : null,
  ]);
  const changed = data.crossed.filter((b) => core.some((t) => t.key === b.key));
  return el('div', { class: 'stat-strip risk-summary' }, [
    stat('CORE PAST THEIR LINE', `${past.length} of ${core.length}`, past.map((t) => el('span', { class: 'mchip down', text: `${t.label} ${formatValue(t.value, t.unit)}` })), past.length ? 'down' : ''),
    stat('CHANGED THIS WEEK', String(changed.length),
      changed.map((b) => el('span', { class: `mchip ${b.crossed === 'into' ? 'down' : 'up'}`, text: `${b.label} ${b.crossed === 'into' ? '↑ in' : '↓ out'}` }))),
    stat('OTHER SERIES', `${others.filter((t) => t.breach).length} of ${others.length}`, ['past their line · listed below']),
  ]);
}

function methodNotes() {
  return [
    'The anchor is quantamental-lab\'s frozen v1 control, re-implemented here and checked to reproduce its daily exposure exactly over 1993–2026: vol-targeted to 12% on 63-day realised volatility, capped at 50% while SPY is not above its 200-day average or while the copper/oil gate is off (z below −0.25, back on above +0.25), and stepped down to ×0.6 / ×0.3 when its own drawdown passes −8% / −12%. Its recession gate is that repository\'s model output and is not ported (treated as neutral). A reference, not a recommendation.',
    'Core series: trend and breadth (SPX against its 200-day average and its 1-year high, the share of members above their 200-day average), volatility (VIX and VIX/VIX3M), credit (high-yield OAS), rates (10-year real yield), the dollar, copper/oil and financial conditions (NFCI). Everything else is folded under ALL SERIES: most of it restates one of these.',
    'Each tile is one series. 1Y = its percentile over the last 365 days; 1990– = over all the history the source serves, from the year shown; 1W = change over a week. Nothing is combined into a score.',
    'Thresholds were written in config/dashboard.toml before this page drew any series, and are not fitted to it. A red tile is past its line; NEW means it was not a week ago, CLEARED that it was. Positioning and the put/call ratio are read at extremes: the tails of their own history (≤5th or ≥95th percentile).',
    'Back-calculated history: VIX3M, VIX9D, VIX6M, VIX1Y, VVIX, SKEW and COR1M were launched after the first row of their files; the earlier part is Cboe\'s back-calculation. ICE BofA spreads (HY, IG, CCC) come from FRED, which serves the last three years only; the site archives what FRED serves each evening (a full-history baseline first, then the daily tail), and those archived dates extend the series back as the archive grows. The archive is current-vintage history, not point-in-time; Moody\'s Baa − 10Y runs to 1986.',
    'CFTC positions are as of Tuesday and published the following Friday. Realised correlation and dispersion come from the S&P 500 members\' own closes and today\'s SPY weights over 21 sessions.',
    'Fear & Greed is computed here after CNN\'s outline, not taken from CNN (whose feed refuses non-browser clients): seven components, each z-scored against its own trailing year and mapped to 0–100 through the normal distribution (flipped where a high reading is fear), then averaged equally. Where the data differs from CNN\'s: strength counts S&P 500 members at 52-week highs and lows rather than the NYSE; breadth is a McClellan summation of S&P 500 advances and declines by count rather than NYSE volume; junk bond demand is the ICE BofA HY less IG spread; safe-haven demand is the S&P 500\'s 20-day return less IEF\'s. Bands: below 25 extreme fear, 25–45 fear, 45–55 neutral, 55–75 greed, above 75 extreme greed. It will sit near CNN\'s number, not on it.',
    'Not included: AAII sentiment and NAAIM (docs/risk_sources.md has each probe).',
  ];
}

export default function renderRisk(root, payload) {
  const [data, anchor] = Array.isArray(payload) ? payload : [payload, null];
  if (!data || data.unavailable) throw new Error(data?.unavailable || 'risk artifact missing');
  const core = data.sections.flatMap((s) => s.tiles.map((t) => ({ ...t, horizon: s.horizon }))).filter((t) => t.core);
  const total = data.sections.reduce((n, s) => n + s.tiles.length, 0);
  root.append(metaRow(`RISK · ANCHOR AND ${core.length} CORE SERIES · AS OF ${data.as_of} · CLICK A TILE FOR ITS HISTORY (TWO SHOWN)`, methodNotes()));
  root.append(summary(data, core));
  root.append(el('div', { class: 'grid risk-top' }, [
    el('div', { class: 'risk-left' }, [anchorCard(anchor), sentimentCard(data.sentiment)]),
    sectionCard({ key: 'core', label: 'CORE SERIES', tiles: core }, data, { charts: 2 }),
  ]));

  // Everything else, drawn only when opened: a chart laid out while folded
  // has no width.
  const more = el('details', { class: 'risk-more' }, [el('summary', { text: `ALL ${total} SERIES BY GROUP` })]);
  let drawn = false;
  more.addEventListener('toggle', () => {
    if (!more.open || drawn) return;
    drawn = true;
    for (const [horizon, label] of HORIZONS) {
      const sections = data.sections.filter((s) => s.horizon === horizon);
      if (!sections.length) continue;
      more.append(el('h2', { class: 'section-title risk-horizon', text: label }));
      more.append(el('div', { class: 'grid two risk-sections' }, sections.map((s) => sectionCard(s, data))));
    }
  });
  root.append(more);
}
