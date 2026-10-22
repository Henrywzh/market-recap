// TODAY's figure blocks: the day's board by index and sector, the signal chips,
// the movers table with its sparklines, and the events left under it. The pure
// helpers are what the tests check; the builders turn them into nodes. The
// numbers come from the build (or the live quotes for MOVERS while the market is
// open); a missing figure is a dash, never a zero.

import { el, num, card, table, tag, dirClass, DASH } from './fmt.js';
import { render } from './charts.js';
import { tickerHref } from './routes.js';

const valid = (v) => typeof v === 'number' && Number.isFinite(v);
const MINUS = '−';
const STRONG_Z = 3;          // a mover this far beyond its own volatility is bold
const BOARD_STRONG_Z = 2;    // a board bar this far is drawn at full strength
const BOARD_ROW_PX = 22;
const EVENTS_SHOWN = 6;

// A signed figure with a true minus, as the board and the headline print it. A
// value that rounds to zero carries no sign: "-0.0%" would read as a fall.
export function moveText(value, digits = 1, suffix = '%') {
  if (!valid(value)) return DASH;
  const rounded = Number(Math.abs(value).toFixed(digits));
  const sign = rounded === 0 ? '' : value < 0 ? MINUS : '+';
  return `${sign}${num(rounded, digits)}${suffix}`;
}

export const sigmaText = (z) => moveText(z, 1, 'σ');

// The line through a series of closes, scaled into a w by h box. A missing close
// breaks the line rather than dropping to zero; fewer than two closes draw nothing.
export function sparkPath(values, w = 56, h = 16) {
  const list = Array.isArray(values) ? values : [];
  const finite = list.filter(valid);
  if (finite.length < 2) return null;
  const low = Math.min(...finite);
  const span = Math.max(...finite) - low || 1;
  const step = w / (list.length - 1);
  return list
    .map((v, i) => (valid(v) ? `${valid(list[i - 1]) ? 'L' : 'M'}${(i * step).toFixed(1)} ${(h - ((v - low) / span) * h).toFixed(1)}` : null))
    .filter(Boolean)
    .join(' ');
}

// The sparkline as markup: the values are numbers, so nothing in them can break out.
export function sparkSvg(values, w = 56, h = 16) {
  const d = sparkPath(values, w, h);
  return d ? `<svg class="today-spark-svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><path d="${d}"/></svg>` : '';
}

// The headline the build wrote from the board: one line, toned by the S&P 500.
export function headlineNode(headline) {
  if (!headline?.text) return null;
  const tone = ['up', 'down'].includes(headline.tone) ? headline.tone : 'flat';
  return el('div', { class: `today-headline ${tone}`, text: headline.text });
}

// --- The day's board -----------------------------------------------------

// The board's bars: the indices first, a gap, then the sector funds, each group
// highest move first. The gap is a null slot the chart draws as nothing.
export function boardSlots(rows) {
  const usable = (Array.isArray(rows) ? rows : []).filter((r) => r && valid(r.ret_pct));
  const byMove = (a, b) => b.ret_pct - a.ret_pct;
  const indices = usable.filter((r) => r.group === 'index').sort(byMove);
  const sectors = usable.filter((r) => r.group !== 'index').sort(byMove);
  return indices.length && sectors.length ? [...indices, null, ...sectors] : [...indices, ...sectors];
}

const strongBar = (row) => valid(row.z) && Math.abs(row.z) >= BOARD_STRONG_Z;

// The label at a bar's end: the move, its σ, and RARE when the history has seen a
// move this far on 1% of days or fewer.
export function boardLabel(row) {
  const parts = [moveText(row.ret_pct)];
  if (valid(row.z)) parts.push(`${num(Math.abs(row.z), 1)}σ`);
  if (valid(row.share_pct) && row.share_pct <= 1) parts.push('RARE');
  return parts.join(' · ');
}

function boardTip(row) {
  if (!row) return '';
  const rsi = valid(row.rsi6) ? num(row.rsi6, 1) : DASH;
  const share = valid(row.share_pct) ? `${num(row.share_pct, 1)}% of days at this move or beyond` : DASH;
  return [
    row.label ?? row.short ?? row.symbol,
    `Move ${moveText(row.ret_pct)} · ${sigmaText(row.z)}`,
    `Share ${share}`,
    `RSI(6) ${rsi}`,
  ].join('<br>');
}

// The ECharts option for the board: one bar per row, the axis range set by the
// largest move so the bar-end labels fit, a zero line, and a tooltip per row.
export function boardOption(slots, p) {
  const largest = Math.max(1, ...slots.filter(Boolean).map((r) => Math.abs(r.ret_pct)));
  const span = largest * 1.6;
  return {
    animation: false,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace', fontSize: 10 },
    // A fixed label column: containLabel mis-measures truncated labels and clips the longest.
    grid: { left: 116, right: 8, top: 4, bottom: 4 },
    tooltip: {
      trigger: 'item',
      backgroundColor: '#000',
      borderColor: p.border,
      borderWidth: 1,
      textStyle: { color: p.text, fontSize: 11, fontFamily: 'ui-monospace, Menlo, monospace' },
      formatter: (q) => boardTip(slots[q.dataIndex]),
    },
    xAxis: {
      type: 'value',
      min: -span,
      max: span,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { show: false },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: slots.map((r) => (r ? r.short || r.label || r.symbol : '')),
      axisLine: { show: false, onZero: false },
      axisTick: { show: false },
      axisLabel: { color: p.text, fontSize: 11, width: 96, overflow: 'truncate' },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 12,
      markLine: { silent: true, symbol: 'none', data: [{ xAxis: 0 }], lineStyle: { color: p.faint }, label: { show: false } },
      data: slots.map((r) => (r ? {
        value: r.ret_pct,
        itemStyle: { color: r.ret_pct >= 0 ? p.up : p.down, opacity: strongBar(r) ? 1 : 0.55 },
        label: { position: r.ret_pct >= 0 ? 'right' : 'left' },
      } : { value: null })),
      label: { show: true, color: p.dim, fontSize: 11, formatter: (q) => (slots[q.dataIndex] ? boardLabel(slots[q.dataIndex]) : '') },
    }],
  };
}

// The board's bars drawn into the node; a click on a bar opens MOVE CHECK for it.
export function drawBoard(node, slots) {
  const chart = render(node, (option, p) => boardOption(slots, p));
  chart?.on('click', (q) => {
    const row = slots[q.dataIndex];
    if (row) location.hash = `#movecheck/${row.symbol}`;
  });
  return chart;
}

// The day's board as a card. `draw` mounts the chart once the card is in the page,
// so ECharts measures it. Null when no index or sector fund has a close.
export function boardCard(board) {
  const slots = boardSlots(board?.rows);
  if (!slots.some(Boolean)) return null;
  const node = el('div', { class: 'chart today-board-chart' });
  node.style.height = `${slots.length * BOARD_ROW_PX + 10}px`;
  return { node: card('THE DAY BY INDEX AND SECTOR', null, [node]), draw: () => drawBoard(node, slots) };
}

// --- Signals -------------------------------------------------------------

const compactValue = (item) => {
  if (valid(item.days)) return `${item.days} sessions`;
  if (valid(item.value)) return `${num(item.value, 1)}${item.unit === '%' ? '%' : item.unit ? ` ${item.unit}` : ''}`;
  return '';
};

// CHANGED reads as the state itself: the title after its colon, the build's
// parenthesis left out ("Treasuries · technical: MOVE moved to elevated (...)").
function stateText(item) {
  const title = String(item.title ?? '');
  const cut = title.includes(':') ? title.slice(title.indexOf(':') + 1) : title;
  return cut.replace(/\s*\([^)]*\)\s*$/, '').trim() || item.subject;
}

function scenarioText(item) {
  const { value, threshold, state } = item.extra || {};
  if (valid(value) && valid(threshold)) return `${item.subject} ${num(value, 0)} → ${num(threshold, 0)}`;
  return [item.subject, state].filter(Boolean).join(' · ');
}

// The signal chips, one group per kind in the order the page reads them. A group
// with no chip is left out. Each chip carries its full title as a tooltip.
export function signalGroups(unusual, boardRows) {
  const names = new Map((Array.isArray(boardRows) ? boardRows : []).filter(Boolean).map((r) => [r.symbol, r.short || r.label]));
  const nameOf = (item) => names.get(item.extra?.symbol) ?? item.subject;
  const groups = [
    ['OVERSOLD', (unusual?.oversold || []).map((item) => {
      const rsi = item.extra?.rsi ?? item.value;
      return { text: `${nameOf(item)} ${valid(rsi) ? num(rsi, 1) : DASH}`, title: item.detail, href: item.link, tone: item.extra?.line === 20 ? 'down' : 'warn' };
    })],
    ['RARE', (unusual?.tails || []).map((item) => {
      const share = valid(item.extra?.share_pct) ? `${num(item.extra.share_pct, 1)}%` : DASH;
      return {
        text: `${nameOf(item)} ${moveText(item.value)} · ${share}`,
        title: item.detail,
        href: item.extra?.symbol ? `#movecheck/${item.extra.symbol}` : item.link,
        tone: item.value < 0 ? 'down' : 'up',
      };
    })],
    ['CHANGED', (unusual?.states || []).map((item) => ({
      text: stateText(item), title: item.title, href: item.link, tone: item.extra?.active === false ? 'dim' : 'info',
    }))],
    ['SCENARIO', (unusual?.watch || []).map((item) => ({
      text: scenarioText(item), title: item.title, href: item.link || '#watch', tone: item.extra?.state === 'triggered' ? 'down' : 'warn',
    }))],
    ['ONGOING', (unusual?.ongoing || []).map((item) => ({
      text: [item.subject, compactValue(item)].filter(Boolean).join(' · '), title: item.title, href: item.link, tone: 'dim',
    }))],
  ];
  return groups.map(([label, chips]) => ({ label, chips })).filter((group) => group.chips.length);
}

const chipNode = (chip) => el(chip.href ? 'a' : 'span', { class: `chip ${chip.tone || 'dim'}`, href: chip.href, title: chip.title, text: chip.text });

// The SIGNALS card: one row per kind, its label then its chips.
export function signalsCard(groups) {
  if (!groups.length) return card('SIGNALS', null, [el('div', { class: 'today-empty dim', text: 'No signal this session.' })]);
  return card('SIGNALS', null, groups.map((group) => el('div', { class: 'today-chips' }, [
    el('span', { class: 'today-chips-label dim', text: group.label }),
    ...group.chips.map(chipNode),
  ])));
}

// --- Movers --------------------------------------------------------------

// The MOVERS rows: the build's moves, or the live list while the market is open.
// The build's rows carry the market and sector parts and the sparkline; the live
// rows carry their own numbers only. A reporter keeps its E in both.
export function moverRecords(unusual, liveItems = null) {
  const reporters = new Set((unusual?.moves || []).filter((m) => m.extra?.earnings === true).map((m) => m.subject));
  if (liveItems) {
    return liveItems.map((item) => ({
      ticker: item.ticker, href: tickerHref(item.ticker), move: item.ret_pct ?? null, z: item.z ?? null,
      own: item.own_pct ?? null, market: null, sector: null, spark: null, earnings: reporters.has(item.ticker),
    }));
  }
  return (unusual?.moves || []).map((item) => ({
    ticker: item.subject, href: item.link ?? null, move: item.extra?.ret_pct ?? null, z: item.z ?? null,
    own: item.extra?.own_pct ?? null, market: item.extra?.market_pct ?? null, sector: item.extra?.sector_pct ?? null,
    spark: item.extra?.spark ?? null, earnings: item.extra?.earnings === true,
  }));
}

// The table of movers: ticker (with E for a reporter), move, σ, own part, the
// market and sector parts, and a sparkline of the last closes. A row beyond the
// strong σ is bold; no row carries a tag beyond E.
export function moversTable(records) {
  const rows = records.map((r) => el('tr', { class: valid(r.z) && Math.abs(r.z) >= STRONG_Z ? 'is-strong' : null }, [
    el('td', { class: 'today-mover-ticker' }, [
      r.href ? el('a', { href: r.href, text: r.ticker }) : el('span', { text: r.ticker }),
      r.earnings ? tag('E', 'info', 'Reports this session') : null,
    ]),
    el('td', { class: `today-value ${dirClass(r.move)}`, text: moveText(r.move) }),
    el('td', { class: `today-value ${dirClass(r.z)}`, text: sigmaText(r.z) }),
    el('td', { class: `today-value ${dirClass(r.own)}`, text: moveText(r.own) }),
    el('td', { class: 'today-value dim', text: r.market == null && r.sector == null ? DASH : `${moveText(r.market)} / ${moveText(r.sector)}` }),
    el('td', { class: 'today-spark', html: sparkSvg(r.spark) }),
  ]));
  return table(['TICKER', 'MOVE', 'σ', 'OWN PART', 'MARKET / SECTOR', 'SPARK'], rows, { class: 'today-movers' });
}

// The build's sector sell-off: one line above the table, not a row in it.
export function sectorLine(unusual) {
  const item = [...(unusual?.events || []), ...(unusual?.moves || []), ...(unusual?.states || [])].find((i) => i.kind === 'sector_selloff');
  return item ? el(item.link ? 'a' : 'div', { class: 'today-sector-line', href: item.link, text: item.title }) : null;
}

// The events the table does not already show: monitor and catalyst items, and
// reactions whose name is not a mover. The sector sell-off has its own line.
export function remainingEvents(unusual) {
  const movers = new Set((unusual?.moves || []).map((m) => m.subject));
  return (unusual?.events || []).filter((i) => i.kind !== 'sector_selloff' && !movers.has(i.subject));
}

// The rest of the events, as compact rows: title and σ; past six, a fold.
export function eventNodes(items) {
  // An earnings reaction reads as figures, like the movers above it.
  const text = (item) => (item.kind === 'reaction' && valid(item.value)
    ? `${item.subject} ${moveText(item.value)} · after its report` : item.title);
  const row = (item) => el(item.link ? 'a' : 'div', { class: 'today-row', href: item.link, title: item.title }, [
    el('span', { class: 'today-text', text: text(item) }),
    valid(item.z) ? el('span', { class: 'today-value', text: sigmaText(item.z) }) : null,
  ]);
  const shown = items.slice(0, EVENTS_SHOWN).map(row);
  if (items.length <= EVENTS_SHOWN) return shown;
  return [...shown, el('details', { class: 'today-more' }, [
    el('summary', { text: `${items.length - EVENTS_SHOWN} more` }),
    ...items.slice(EVENTS_SHOWN).map(row),
  ])];
}
