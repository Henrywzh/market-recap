// RISK: how much risk the market is pricing. A matrix first: six channels down
// the side, three kinds of evidence across. Each cell is coloured by its lead
// series' percentile in its own history, and opens its member series on click.
// Every other series is folded beneath, by group. One tile per series -- level,
// where it sits in its year and in its whole history, the week's change, and
// whether it is past the line written in config beforehand. No score.

import { el, card, num, metaRow, tag, gap, DASH } from '../fmt.js';
import { render } from '../charts.js';
import { rangeSwitch, sliceRange, initialRange } from '../range.js';
import { spark } from '../spark.js';
import { cellsByRow, stateCounts, stateOf, stateWord, chipWord, countParts, isPlaceholder, arrowFor, tagFor, scaleText, VALUATION_STATES, upcomingFor } from '../risk-matrix.js';

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

export function ordinal(n) {
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
  const weekly = tile.frequency === 'weekly';
  // A daily source a session behind the page (Cboe's and FRED's files land a
  // day late) is marked, so its 1D is not read as the page's session.
  const behind = !weekly && tile.date && asOf && tile.date < asOf;
  const node = el('div', {
    class: `risk-tile ${state}${selected ? ' selected' : ''}${onPick ? ' pickable' : ''}`,
    title: [tile.note, ...(tile.sources || []).map((s) => `source: ${s}`), tile.backcalc, tile.error].filter(Boolean).join('\n'),
    onclick: onPick ? () => onPick(tile.key) : null,
  }, [
    el('div', { class: 'risk-tile-head' }, [
      el('span', { class: 'risk-tile-label', text: tile.label }),
      el('span', { class: 'risk-tags' }, [
        weekly ? el('span', { class: 'risk-freq', title: 'Published weekly: no one-session change', text: 'WEEKLY' }) : null,
        crossed ? el('span', { class: `risk-flag ${tile.crossed}`, text: crossed }) : null,
      ]),
    ]),
    el('div', { class: 'risk-tile-value', text: tile.error && !present(tile.value) ? DASH : formatValue(tile.value, tile.unit) }),
    compact ? null : spark(tile.spark, {
      threshold: tile.risk_when === 'extreme' ? null : tile.threshold,
      color: state === 'breach' ? 'var(--down)' : 'var(--text-dim)',
    }),
    el('div', { class: 'risk-tile-meta', title: 'Percentile over the last year, and over all the history the source serves' }, [
      el('span', { text: `1Y ${ordinal(tile.pct_1y)} · ${sinceLabel(tile)} ${ordinal(tile.pct_long)}` }),
    ]),
    el('div', { class: 'risk-tile-meta dim' }, [el('span', {
      title: weekly ? null : `1D: since ${tile.previous_date || 'the previous observation'}`,
      text: weekly ? `1W ${formatChange(tile.change_1w, tile.unit)}`
        : `1D ${formatChange(tile.change_1d, tile.unit)} · 1W ${formatChange(tile.change_1w, tile.unit)}`,
    })]),
    compact ? null : el('div', { class: 'risk-tile-foot dim' }, [
      thresholdText(tile),
      // Month and day only: the foot is one line, and the year is the page's.
      weekly && tile.date ? el('span', { title: tile.date, text: ` · week of ${tile.date.slice(5)}` }) : null,
      behind ? el('span', { class: 'risk-behind', title: `The source's latest observation is ${tile.date}; the page is ${asOf}`, text: ` · data ${tile.date.slice(5)}` }) : null,
      tile.error && !present(tile.value) ? ` · ${tile.error}` : null,
    ]),
  ]);
  return node;
}

// Weekly points for the long history, then the last year day by day where
// the source is daily.
export function chartHistory(tile) {
  const weekly = tile.history || { dates: [], values: [] };
  const recent = tile.recent;
  if (!recent?.dates?.length) return weekly;
  const keep = weekly.dates.findIndex((d) => d >= recent.dates[0]);
  const cut = keep === -1 ? weekly.dates.length : keep;
  return { dates: [...weekly.dates.slice(0, cut), ...recent.dates], values: [...weekly.values.slice(0, cut), ...recent.values] };
}

export function historyChart(node, tile, range = 'MAX') {
  const full = chartHistory(tile);
  const h = sliceRange(full.dates, { values: full.values }, range);
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 56, right: 16, top: 14 },
    // A time axis: weekly points then daily ones, each at its own date, so
    // the daily last year is not stretched across more of the width.
    tooltip: {
      ...option.tooltip,
      formatter: (items) => {
        const it = [].concat(items)[0];
        return it ? `${it.value[0]}<br>${it.marker}${tile.label} <b>${formatValue(it.value[1], tile.unit)}</b>` : '';
      },
    },
    xAxis: { ...option.xAxis, type: 'time', boundaryGap: false, data: undefined },
    yAxis: { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => formatValue(v, tile.unit) } },
    series: [{
      name: tile.label, type: 'line', data: h.dates.map((d, i) => [d, h.values[i]]), showSymbol: false,
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
// `lead` (a tile key) is drawn first, ahead of the past-their-line order.
function sectionCard(section, data, { charts = 1, head = null, lead = null } = {}) {
  const tiles = section.tiles;
  const order = lead
    ? [...tiles.filter((t) => t.key === lead), ...tiles.filter((t) => t.key !== lead)]
    : [...tiles.filter((t) => t.breach), ...tiles.filter((t) => !t.breach)];
  let selected = order.slice(0, charts).map((t) => t.key);
  const grid = el('div', { class: 'risk-grid' });
  const slots = selected.map(() => ({ node: el('div', { class: 'chart' }), title: el('span', { class: 'dim' }) }));
  // One range for the card's charts; offered as far as its longest history.
  const longest = tiles.map((t) => chartHistory(t).dates).reduce((a, b) => (b.length > a.length ? b : a), []);
  let range = initialRange(longest, 'MAX');
  const switcher = rangeSwitch(longest, range, (label) => { range = label; draw(); });
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
      slots[i].title.textContent = `${tile.label} · ${tile.recent?.dates?.length ? 'daily for the last year, weekly before' : 'weekly'} · 10 years or since ${tile.since}`;
      historyChart(slots[i].node, tile, range);
    });
  };
  const chartBlocks = slots.map((slot, i) => el('div', {}, [el('div', { class: 'chart-head risk-chart-head' }, [slot.title, i === 0 ? switcher : null]), slot.node]));
  const breached = tiles.filter((t) => t.breach).length;
  const body = [grid, charts > 1 ? el('div', { class: 'risk-charts' }, chartBlocks) : chartBlocks[0]];
  if (section.key === 'volatility') {
    const termNode = el('div', { class: 'chart' });
    body.push(el('div', { class: 'risk-chart-head' }, [el('span', { class: 'dim', text: 'TERM STRUCTURE · today, a week and a month ago' })]), termNode);
    requestAnimationFrame(() => termChart(termNode, data.charts || {}));
  }
  requestAnimationFrame(draw);
  return card(section.label, head ? el('span', { class: 'dim', text: head }) : el('span', { class: breached ? 'down' : 'dim', text: breached ? `${breached} of ${tiles.length} past threshold` : `${tiles.length} series · none past threshold` }), body);
}

// The matrix's headline words: how a cell's percentile reads, and the rule
// that colours it. Both come from the build's own thresholds.
function percentText(cell, years) {
  if (cell.scale === 'valuation' && present(cell.percentile)) {
    return `thinner than ${num(cell.percentile, 0)}% since ${(cell.since || '').slice(0, 4)}`;
  }
  // A banded cell is read against its lines, so the lines are what it shows.
  if (cell.scale === 'bands' && cell.bands) {
    const dir = cell.risk_when === 'low' ? '≤' : '≥';
    return `elev ${dir} ${formatValue(cell.bands.elevated, cell.unit)} · stress ${dir} ${formatValue(cell.bands.stressed, cell.unit)}`;
  }
  if (!present(cell.percentile)) return 'no percentile';
  // A source shorter than the window (ICE spreads on FRED: three years) says so.
  const span = present(cell.years_used) && cell.years_used < years ? num(cell.years_used, cell.years_used < 3 ? 1 : 0) : years;
  return `${ordinal(cell.percentile)} of ${span}y`;
}

function ruleText(matrix, cell) {
  return `${scaleText(cell, matrix, (v) => formatValue(v, cell.unit))} `
    + 'Grey: no reading, or a stale lead.';
}

function cellClass(cell, selected) {
  return ['risk-cell', stateOf(cell), selected ? 'selected' : ''].filter(Boolean).join(' ');
}

// What a screen reader hears for a cell: where it is, the lead, its reading,
// its state in words, and its evidence.
function cellLabel(row, column, cell, years) {
  const arrow = arrowFor(cell);
  const parts = [
    `${row.label} · ${column.label}`,
    `${cell.label}${present(cell.value) ? ` ${formatValue(cell.value, cell.unit)}` : ''}`,
    percentText(cell, years),
    cell.scale === 'bands' && present(cell.percentile) ? `${ordinal(cell.percentile)} percentile of 10 years` : null,
    stateWord(stateOf(cell)),
    arrow ? arrow.word : null,
    ...tagFor(cell).map((t) => t.title || t.text.toLowerCase()),
  ];
  return parts.filter(Boolean).join(', ');
}

// A placeholder is only its pending text: there is no series to open yet.
function placeholderNode(row, column, cell) {
  return el('div', { class: 'risk-cell grey placeholder', 'aria-label': `${row.label} · ${column.label}: no series yet` }, [
    el('span', { class: 'risk-cell-col', text: column.label }),
    cellHead(null, cell),
    el('span', { class: 'risk-cell-pending dim', text: cell?.pending || DASH }),
  ]);
}

// The label and the state chip on one line. Calm gets a quiet chip too, so every
// cell reads the same way; the chip's words repeat the cell's state in capitals.
function cellHead(label, cell) {
  return el('span', { class: 'risk-cell-head' }, [
    label ? el('span', { class: 'risk-cell-label', text: label }) : null,
    el('span', { class: `risk-chip risk-chip-${stateOf(cell)}`, text: chipWord(cell) }),
  ]);
}

// One cell as a button. The tint carries the state; the words are in the label.
function cellButton(row, column, cell, years, onPick) {
  if (isPlaceholder(cell)) {
    return el('button', {
      type: 'button', class: cellClass(cell, false) + ' placeholder', 'aria-expanded': 'false',
      'aria-label': `${row.label} · ${column.label}: ${cell.pending || 'no series yet'}`, onclick: onPick,
    }, [
      el('span', { class: 'risk-cell-col', text: column.label }),
      cellHead(null, cell),
      el('span', { class: 'risk-cell-pending dim', text: cell.pending || DASH }),
    ]);
  }
  const arrow = arrowFor(cell);
  return el('button', {
    type: 'button',
    class: cellClass(cell, false),
    'aria-expanded': 'false',
    'aria-label': cellLabel(row, column, cell, years),
    title: cell.note || null,
    onclick: onPick,
  }, [
    el('span', { class: 'risk-cell-col', text: column.label }),
    cellHead(cell.label, cell),
    el('span', { class: 'risk-cell-reading' }, [
      el('span', { class: 'risk-cell-value', text: formatValue(cell.value, cell.unit) }),
      arrow ? el('span', { class: `risk-cell-arrow ${arrow.tone}`, title: arrow.word, text: arrow.arrow }) : null,
    ]),
    el('span', { class: 'risk-cell-pct', text: percentText(cell, years) }),
    el('span', { class: 'risk-cell-tags' }, tagFor(cell).map((t) => tag(t.text, t.tone, t.title))),
  ]);
}

// What a cell opens: the rule, its note and caution, then its member series
// through the same tiles and history chart as the folded groups.
function comingUp(row, calendar) {
  const next = upcomingFor(calendar?.events, row.key, calendar?.as_of);
  if (!next.length) return null;
  return el('div', { class: 'risk-drill-note' }, [
    el('span', { class: 'dim', text: `NEXT FOR ${row.label}: ` }),
    ...next.flatMap((e, i) => [i ? ' · ' : '', el('a', { href: '#catalysts', text: `${e.title} ${e.date.slice(5)}` })]),
  ]);
}

function drillNode(matrix, row, column, cell, data, tiles, calendar) {
  const members = (cell.members || []).map((key) => tiles.get(key)).filter(Boolean);
  const notes = isPlaceholder(cell) ? [] : [el('div', { class: 'risk-drill-rule dim', text: ruleText(matrix, cell) })];
  const upcoming = comingUp(row, calendar);
  if (upcoming) notes.push(upcoming);
  if (cell.note) notes.push(el('div', { class: 'risk-drill-note', text: cell.note }));
  if (cell.caution) notes.push(el('div', { class: 'risk-drill-note down', text: `Caution: ${cell.caution}.` }));
  const body = members.length
    ? sectionCard({ key: `${row.key}-${column.key}`, label: `${row.label} · ${column.label}`, tiles: members }, data,
      { charts: 1, head: 'click a series for its history', lead: cell.lead })
    : gap('No series to draw for this cell yet.');
  return el('div', { class: 'risk-drill' }, [...notes, body]);
}

// The headline: channels down, evidence across. One cell open at a time; a
// second click on the same cell closes it. Enter and Space are a button's own
// click, so they need no handler here.
function matrixBlock(matrix, data, calendarOf = () => null) {
  const years = matrix.years ?? 10;
  const tiles = new Map(data.sections.flatMap((s) => s.tiles).map((t) => [t.key, t]));
  const drill = el('div', { class: 'risk-drill-host' });
  const buttons = new Map();
  let open = null;

  const choose = (key, row, column, cell) => {
    open = open === key ? null : key;
    for (const [k, node] of buttons) {
      node.setAttribute('aria-expanded', String(k === open));
      node.className = cellClass(node.cell, k === open);
    }
    drill.replaceChildren(...(open ? [drillNode(matrix, row, column, cell, data, tiles, calendarOf())] : []));
  };

  const rows = cellsByRow(matrix).map((row) => el('div', { class: 'risk-row', 'data-row': row.key }, [
    el('div', { class: 'risk-row-label', text: row.label }),
    ...row.cells.map((cell, i) => {
      const column = matrix.columns[i];
      // A placeholder with no member series has nothing to open; one that
      // names members still opens them, under its pending text.
      if (isPlaceholder(cell) && !(cell?.members || []).length) return placeholderNode(row, column, cell);
      const key = `${row.key}|${column.key}`;
      const node = cellButton(row, column, cell, years, () => choose(key, row, column, cell));
      node.cell = cell;
      buttons.set(key, node);
      return node;
    }),
  ]));
  const head = el('div', { class: 'risk-matrix-head' }, [
    el('span'),
    ...matrix.columns.map((c) => el('span', { text: c.label })),
  ]);
  return el('div', { class: 'risk-matrix' }, [head, ...rows, drill]);
}

// One line: how many cells sit in each state. Placeholders count as no reading.
// Each count carries its state's tone, so the reds and ambers read at a glance.
function summary(matrix) {
  const cells = cellsByRow(matrix).flatMap((r) => r.cells);
  const isValuation = (cell) => cell?.column === 'valuation';
  const counts = stateCounts(cells.filter((c) => !isValuation(c)));
  const worth = stateCounts(cells.filter(isValuation));
  const stateStates = ['stressed', 'elevated', 'calm', ...(counts.unrated ? ['unrated'] : []), 'grey'];
  const valuationStates = [...VALUATION_STATES, 'grey'].filter((s) => worth[s]);
  const parts = (list) => list.flatMap((part, i) => [i ? el('span', { class: 'dim', text: ' · ' }) : null,
    el('span', { class: part.tone ? `risk-count risk-count-${part.tone}` : 'risk-count', text: part.text })]);
  return el('div', { class: 'risk-status' }, [
    el('span', { class: 'risk-status-count' }, parts(countParts(counts, stateStates))),
    valuationStates.length ? el('span', { class: 'risk-status-count dim' }, [
      el('span', { text: 'VALUATION: ' }),
      ...parts(countParts(worth, valuationStates)),
    ]) : null,
  ]);
}

// Self-computed after CNN's seven components (compute/sentiment.py); it
// follows CNN's outline, not its number.
// The five CNN bands as tag tones: the two fear bands red, the two greed
// bands green, neutral grey.
export function fgTone(score) {
  if (!present(score)) return 'dim';
  return score < 45 ? 'down' : score > 55 ? 'up' : 'dim';
}

// The score's own colour: red in fear, green in greed, plain in between.
const valueTone = (v) => (!present(v) ? 'dim' : v < 45 ? 'down' : v > 55 ? 'up' : '');

// Where the marker sits on the 0–100 bar; a score outside the range is pinned to its end.
export function fgMarkerPercent(score) {
  if (!present(score)) return null;
  return Math.min(100, Math.max(0, score));
}

const agoText = (label, v) => `${label} ${present(v) ? num(v, 0) : DASH}`;

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
  const tone = valueTone;
  const chartNode = el('div', { class: 'chart short' });
  let range = initialRange(g.history.dates, '1Y');
  const draw = () => {
    const h = sliceRange(g.history.dates, { score: g.history.score }, range);
    render(chartNode, (option, p) => ({
      ...option,
      grid: { left: 30, right: 12, top: 8, bottom: 22 },
      tooltip: { ...option.tooltip, trigger: 'axis' },
      xAxis: { ...option.xAxis, data: h.dates },
      yAxis: { ...option.yAxis, min: 0, max: 100, interval: 25, axisLabel: { color: p.dim, fontSize: 9 } },
      series: [{
        name: 'fear & greed', type: 'line', data: h.score, showSymbol: false, lineStyle: { width: 1.3, color: p.text },
        markArea: { silent: true, data: [
          [{ yAxis: 0, itemStyle: { color: p.down, opacity: 0.08 } }, { yAxis: 25 }],
          [{ yAxis: 75, itemStyle: { color: p.up, opacity: 0.08 } }, { yAxis: 100 }],
        ] },
        markLine: { silent: true, symbol: 'none', data: [{ yAxis: 50 }], lineStyle: { color: p.faint, type: 'dashed' }, label: { show: false } },
      }],
    }));
  };
  requestAnimationFrame(draw);
  const rows = g.components.map((c) => el('tr', {}, [
    el('td', { class: 'fg-label', text: c.label }),
    el('td', { class: 'dim', text: fgReading(c) }),
    el('td', { class: 'fg-bar-cell' }, [el('span', { class: 'fg-bar' }, [el('span', { class: `fg-bar-fill ${tone(c.score)}`, style: `width:${present(c.score) ? c.score : 0}%` })])]),
    el('td', { class: tone(c.score), text: present(c.score) ? num(c.score, 0) : DASH }),
  ]));
  const ago = agoText;
  return card('FEAR & GREED', head, [
    el('div', { class: 'anchor-head' }, [
      el('span', { class: `anchor-value fg-value ${tone(g.score)}`, text: num(g.score, 0) }),
      tag(g.rating, fgTone(g.score)),
      el('span', { class: 'dim', text: `${ago('1W', g.week_ago)} · ${ago('1M', g.month_ago)} · ${ago('1Y', g.year_ago)}${g.components_counted < g.components.length ? ` · ${g.components_counted} of ${g.components.length} components` : ''}` }),
    ]),
    el('div', { class: 'chart-head' }, [el('span', { class: 'dim', text: 'DAILY · shaded: extreme fear below 25, extreme greed above 75' }), rangeSwitch(g.history.dates, range, (label) => { range = label; draw(); })]),
    chartNode,
    el('div', { class: 'table-scroll' }, [el('table', { class: 'data fg-table' }, [
      el('thead', {}, [el('tr', {}, ['COMPONENT', 'READING', '', 'SCORE'].map((h) => el('th', { text: h })))]),
      el('tbody', {}, rows),
    ])]),
  ]);
}

// The page's headline reading: one row with the score, its rating, a 0–100 bar
// and the week and month before. The full card (history, components) folds below it.
function sentimentStrip(g) {
  if (!g || !present(g.score)) return gap(`FEAR & GREED · not computed this session${g?.error ? `: ${g.error}` : ''}.`);
  const marker = fgMarkerPercent(g.score);
  return el('div', { class: 'fg-strip', title: "self-computed · not CNN's index" }, [
    el('span', { class: 'fg-strip-title dim', text: 'FEAR & GREED' }),
    el('span', { class: `anchor-value fg-value ${valueTone(g.score)}`, text: num(g.score, 0) }),
    tag(g.rating, fgTone(g.score)),
    el('span', { class: 'fg-strip-track', title: 'Score from 0 (extreme fear) to 100 (extreme greed)' }, [
      el('span', { class: 'fg-strip-marker', style: `left:${marker}%` }),
    ]),
    el('span', { class: 'dim fg-strip-ago', text: `${agoText('1W', g.week_ago)} · ${agoText('1M', g.month_ago)}` }),
  ]);
}

function methodNotes() {
  return [
    'The matrix: six channels down the side (equities, treasuries, credit, volatility, cross-asset, macro), and three kinds of evidence across (structure, technical, fundamental / premium). Each cell has one lead series. The first two columns say how stressed the market is, read on one of two scales. Levels with a meaning in any decade (VIX, the VIX curve, MOVE, drawdowns, NFCI, BAA − 10Y) are read against fixed lines, set from where each stood in past drawdowns or from a line with its own meaning (an inverted VIX curve at 1.0, NFCI\'s average at 0); a ten-year percentile would compress the tail and let a quiet decade decide what elevated means. Changes and spreads with no outside anchor are read by their percentile in their own last ten years: elevated from the 75th, stressed from the 95th. A lead that failed its out-of-sample test is shown but not coloured. The VALUATION column says how thin the compensation is for holding each risk -- the equity risk premium (Shiller\'s excess CAPE yield, from Robert J. Shiller\'s "Irrational Exuberance" data, shillerdata.com, with Aswath Damodaran\'s implied ERP beside it), the term premium (Kim and Wright, via FRED), the BAA spread and the volatility premium -- against its whole history since 1960 (1990 where it starts then): cheap, fair, rich or very rich. It describes the cushion, not the timing. Grey means no reading yet. Cells are never averaged or scored; the other series in a cell open on click.',
    'Each tile is one series. 1Y = its percentile over the last 365 days; 1990– = over all the history the source serves, from the year shown; 1W = change over a week. Nothing is combined into a score.',
    'Thresholds were written in config/dashboard.toml before this page drew any series, and are not fitted to it. A red tile is past its line; NEW means it was not a week ago, CLEARED that it was. Positioning and the put/call ratio are read at extremes: the tails of their own history (≤5th or ≥95th percentile).',
    'Back-calculated history: VIX3M, VIX9D, VIX6M, VIX1Y, VVIX, SKEW and COR1M were launched after the first row of their files; the earlier part is Cboe\'s back-calculation. ICE BofA spreads (HY, IG, CCC) come from FRED, which serves the last three years only; the site archives what FRED serves each evening (a full-history baseline first, then the daily tail), and those archived dates extend the series back as the archive grows. The archive is current-vintage history, not point-in-time; Moody\'s Baa − 10Y runs to 1986.',
    'CFTC positions are as of Tuesday and published the following Friday. Realised correlation and dispersion come from the S&P 500 members\' own closes and today\'s SPY weights over 21 sessions.',
    'Fear & Greed is computed here after CNN\'s outline, not taken from CNN (whose feed refuses non-browser clients): seven components, each z-scored against its own trailing year and mapped to 0–100 through the normal distribution (flipped where a high reading is fear), then averaged equally. Where the data differs from CNN\'s: strength counts S&P 500 members at 52-week highs and lows rather than the NYSE; breadth is a McClellan summation of S&P 500 advances and declines by count rather than NYSE volume; junk bond demand is the ICE BofA HY less IG spread; safe-haven demand is the S&P 500\'s 20-day return less IEF\'s. Bands: below 25 extreme fear, 25–45 fear, 45–55 neutral, 55–75 greed, above 75 extreme greed. It will sit near CNN\'s number, not on it.',
    'Not included: AAII sentiment and NAAIM (docs/risk_sources.md has each probe).',
  ];
}

// The full Fear & Greed card, folded under the strip and built on first open.
function sentimentFold(g) {
  const fold = el('details', { class: 'risk-fg-more' }, [el('summary', { text: 'FEAR & GREED · HISTORY AND COMPONENTS' })]);
  let drawn = false;
  fold.addEventListener('toggle', () => {
    if (!fold.open || drawn) return;
    drawn = true;
    fold.append(sentimentCard(g));
  });
  return fold;
}

export default function renderRisk(root, data, _manifest, ctx = {}) {
  if (!data || data.unavailable) throw new Error(data?.unavailable || 'risk artifact missing');
  const total = data.sections.reduce((n, s) => n + s.tiles.length, 0);
  root.append(metaRow(`RISK · MATRIX · AS OF ${data.as_of}`, methodNotes()));
  root.append(sentimentStrip(data.sentiment));
  if (present(data.sentiment?.score)) root.append(sentimentFold(data.sentiment));
  if (data.matrix) {
    root.append(summary(data.matrix));
    // The calendar's tagged events, for "next for this channel" in a cell's drill-down; optional.
    let calendar = null;
    ctx.loadArtifact?.('catalysts').then((c) => { calendar = c; }).catch(() => {});
    root.append(matrixBlock(data.matrix, data, () => calendar));
  } else {
    root.append(gap('The risk matrix was not built for this session.'));
  }
  // The strip sits above the matrix; the full card is built only when opened,
  // because its chart is laid out from the page's width and a folded one has none.

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
