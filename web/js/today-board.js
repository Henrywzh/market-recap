// TODAY's figure blocks: the day's board by index and sector, the signal list,
// the movers table with its sparklines, and the events left under it. The pure
// helpers are what the tests check; the builders turn them into nodes. The
// numbers come from the build (or the live quotes for MOVERS while the market is
// open); a missing figure is a dash, never a zero.

import { el, num, card, table, tag, liveBadge, dirClass, DASH } from './fmt.js';
import { render } from './charts.js';
import { tickerHref } from './routes.js';
import { toSignals, rankSignals, readMuted, writeMuted, GROUP_ORDER } from './signals-model.js';

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

// A sector named with its move ("Comm services −1.4%", "(rare)" kept with it): the
// name starts with a capital and runs to the figure without crossing a comma,
// semicolon or colon, so "led by" and "and" stay outside it.
const NAMED_MOVE = /[A-Z][^,;:]*? [+−-]\d+(?:\.\d+)?%(?: \(rare\))?/g;

// The title in pieces, each with its own colour: the opening words (what kind of
// day) in the market's tone, every named sector by the sign of its own move, the
// words between them plain. A sector that fell on an up day is red, not green.
export function titleSegments(title, tone) {
  const text = String(title || '');
  const cut = text.search(/[,;]/);
  const head = cut < 0 ? text : text.slice(0, cut);
  const out = [{ text: head, tone }];
  const rest = cut < 0 ? '' : text.slice(cut);
  let at = 0;
  for (const match of rest.matchAll(NAMED_MOVE)) {
    if (match.index > at) out.push({ text: rest.slice(at, match.index), tone: null });
    out.push({ text: match[0], tone: /[−-]\d/.test(match[0]) ? 'down' : 'up' });
    at = match.index + match[0].length;
  }
  if (at < rest.length) out.push({ text: rest.slice(at), tone: null });
  return out.filter((part) => part.text);
}

// The headline the build wrote from the board: a title saying what kind of day it
// was (the broad market first), and the figures behind it underneath. The opening
// words are toned by the S&P 500, each sector by its own move (titleSegments).
// A build from before the title had only the line of figures.
// `live` is the quotes' stamp ("14:32 quotes") when the board is read live, null for the close.
export function headlineNode(headline, live = null) {
  if (!headline?.text) return null;
  const tone = ['up', 'down'].includes(headline.tone) ? headline.tone : 'flat';
  const stamp = live ? el('div', { class: 'today-live-stamp' }, [liveBadge('LIVE · SO FAR TODAY'), ` ${live}`]) : null;
  if (!headline.title) {
    const line = el('div', { class: `today-headline ${tone}`, text: headline.text });
    return stamp ? el('div', { class: 'today-headline-block' }, [stamp, line]) : line;
  }
  return el('div', { class: 'today-headline-block' }, [
    stamp,
    // ``split``: the title's own colour is plain; its pieces carry theirs.
    el('div', { class: `today-headline ${tone} split` }, titleSegments(headline.title, tone)
      .map((part) => (part.tone ? el('span', { class: `today-headline-${part.tone}`, text: part.text }) : part.text))),
    el('div', { class: 'today-headline-text', text: headline.text }),
  ].filter(Boolean));
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

// How often the history moved this far, for a label: "0.5% of days". Shown only
// when it is uncommon (SHARE_SHOWN_PCT or less); RARE marks 1% or less.
const SHARE_SHOWN_PCT = 5;
export function shareText(row) {
  if (!valid(row?.share_pct) || row.share_pct > SHARE_SHOWN_PCT) return null;
  return `${row.share_pct <= 1 ? 'RARE: ' : ''}${num(row.share_pct, 1)}% of days`;
}

// The label at a bar's end: the move, its σ, and how often the history moved this far.
export function boardLabel(row) {
  const parts = [moveText(row.ret_pct)];
  if (valid(row.z)) parts.push(`${num(Math.abs(row.z), 1)}σ`);
  const share = shareText(row);
  if (share) parts.push(share);
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
  // Room on each side for the bar-end move ("−6.8%").
  const span = largest * 1.5;
  // σ and the share of days sit in their own column on the right, so a long one
  // never runs into a bar or a name; RARE is drawn in the accent colour.
  const noteOf = (r) => {
    if (!r) return '';
    const parts = [valid(r.z) ? `${num(Math.abs(r.z), 1)}σ` : null, shareText(r)].filter(Boolean).join(' · ');
    return valid(r.share_pct) && r.share_pct <= 1 ? `{rare|${parts}}` : parts;
  };
  const category = { type: 'category', inverse: true, axisLine: { show: false, onZero: false }, axisTick: { show: false } };
  return {
    animation: false,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace', fontSize: 10 },
    // Fixed label columns: containLabel mis-measures truncated labels and clips the longest.
    grid: { left: 116, right: 176, top: 4, bottom: 4 },
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
    yAxis: [
      { ...category, data: slots.map((r) => (r ? r.short || r.label || r.symbol : '')),
        axisLabel: { color: p.text, fontSize: 11, width: 96, overflow: 'truncate' } },
      { ...category, position: 'right', data: slots.map(noteOf),
        axisLabel: { color: p.dim, fontSize: 10, align: 'left', margin: 12, rich: { rare: { color: p.accent, fontSize: 10 } } } },
    ],
    series: [{
      type: 'bar',
      yAxisIndex: 0,
      barMaxWidth: 12,
      markLine: { silent: true, symbol: 'none', data: [{ xAxis: 0 }], lineStyle: { color: p.faint }, label: { show: false } },
      data: slots.map((r) => (r ? {
        value: r.ret_pct,
        itemStyle: { color: r.ret_pct >= 0 ? p.up : p.down, opacity: strongBar(r) ? 1 : 0.55 },
        label: { position: r.ret_pct >= 0 ? 'right' : 'left' },
      } : { value: null })),
      label: { show: true, color: p.dim, fontSize: 11, formatter: (q) => (slots[q.dataIndex] ? moveText(slots[q.dataIndex].ret_pct) : '') },
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

// The index tiles, broad market first: the S&P 500 is the large one. VIX joins
// them when the build has a same-session reading.
const INDEX_ORDER = ['^GSPC', '^NDX', 'RSP', 'IWM', 'DIA'];

export function indexTiles(board) {
  const rows = (board?.rows || []).filter((r) => r && r.group === 'index' && valid(r.ret_pct));
  const rank = (r) => { const k = INDEX_ORDER.indexOf(r.symbol); return k < 0 ? INDEX_ORDER.length : k; };
  const tiles = [...rows].sort((a, b) => rank(a) - rank(b)).map((r) => {
    // A tile has room for the share however common the move: "1.7σ · 8.1% of days".
    const share = valid(r.share_pct) ? `${r.share_pct <= 1 ? 'RARE: ' : ''}${num(r.share_pct, 1)}% of days` : null;
    const notes = [valid(r.z) ? `${num(Math.abs(r.z), 1)}σ` : null, share].filter(Boolean).join(' · ');
    return el('a', { class: `today-index${r.symbol === '^GSPC' ? ' lead' : ''}`, href: `#movecheck/${r.symbol}`,
      title: boardTip(r).replaceAll('<br>', '\n') }, [
      el('span', { class: 'today-index-label', text: r.short || r.label || r.symbol }),
      // A move that prints as 0.0% is not coloured as a rise or a fall.
      el('span', { class: `today-index-move ${moveText(r.ret_pct).startsWith('0') ? '' : dirClass(r.ret_pct)}`, text: moveText(r.ret_pct) }),
      el('span', { class: 'today-index-note dim', text: notes || ' ' }),
    ]);
  });
  const vix = board?.vix;
  if (valid(vix?.value)) {
    tiles.push(el('div', { class: 'today-index' }, [
      el('span', { class: 'today-index-label', text: 'VIX' }),
      el('span', { class: 'today-index-move', text: num(vix.value, 1) }),
      el('span', { class: `today-index-note ${valid(vix.change) ? dirClass(-vix.change) : 'dim'}`,
        text: valid(vix.change) ? moveText(vix.change, 1, '') : ' ' }),
    ]));
  }
  return tiles;
}

// The day's board as a card: the index tiles, then the sector funds as bars.
// `draw` mounts the chart once the card is in the page, so ECharts measures it.
// Null when no index or sector fund has a close.
export function boardCard(board, live = null) {
  const tiles = indexTiles(board);
  const slots = boardSlots((board?.rows || []).filter((r) => r && r.group !== 'index'));
  if (!tiles.length && !slots.some(Boolean)) return null;
  const node = el('div', { class: 'chart today-board-chart' });
  node.style.height = `${slots.length * BOARD_ROW_PX + 10}px`;
  const body = el('div', { class: 'today-board' }, [
    el('div', { class: 'today-index-grid' }, tiles),
    slots.length ? el('div', { class: 'today-sectors' }, [el('div', { class: 'today-block-title', text: 'SECTORS' }), node]) : null,
  ].filter(Boolean));
  const stamp = live ? el('span', { class: 'today-live-stamp' }, [liveBadge(), ` ${live}`]) : null;
  return { node: card('THE DAY', stamp, [body]), draw: () => (slots.length ? drawBoard(node, slots) : null) };
}

// --- Signals -------------------------------------------------------------

// The signal text and figures live in the model (signals-model.js), which the e-mail
// alerts and agents read too; they are re-exported here for the page and its tests.
export { scenarioText, flowChips, flowDollars } from './signals-model.js';

// The signals grouped as the build's kinds, each group's signals ranked (toSignals).
// A group with no signal is left out.
export function signalGroups(unusual, boardRows, flows) {
  const signals = toSignals(unusual, boardRows, flows);
  return GROUP_ORDER.map((label) => ({ label, chips: signals.filter((s) => s.group === label) }))
    .filter((group) => group.chips.length);
}

// The muted keys live in localStorage; a private window or blocked storage has none,
// and the mute then lasts for this page only.
function mutedStorage() {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}

// The badge's colour class: TRIGGERED and a hot NEW are red, NEW amber, NEAR outlined,
// ONGOING and CLEARED dim. The class is the state's name, lower case.
function badgeClass(signal) {
  if (signal.state === 'NEW') return signal.severity >= 4 ? 'hot' : 'new';
  return signal.state.toLowerCase();
}

// One signal as a row: state, group, the text as a link, the age and distance, and the × to mute it.
function signalRow(signal, muted, onMute) {
  return el('div', { class: `today-signal${signal.state === 'CLEARED' ? ' cleared' : ''}${muted ? ' muted' : ''}` }, [
    el('span', { class: `sig-badge sig-${badgeClass(signal)}`, text: signal.state }),
    el('span', { class: 'sig-group', text: signal.tag ?? signal.group }),
    el(signal.href ? 'a' : 'span', { class: `sig-text ${signal.tone || 'dim'}`, href: signal.href, title: signal.title, text: signal.text }),
    // An ONGOING line already says its sessions ("· 26 sessions"), so no second count beside it.
    signal.age == null || signal.group === 'ONGOING' ? null : el('span', { class: 'sig-age', text: `day ${signal.age}` }),
    signal.distance ? el('span', { class: 'sig-distance', text: signal.distance }) : null,
    el('button', {
      class: 'sig-mute', type: 'button', title: muted ? 'Show this signal again' : 'Hide this signal',
      text: muted ? '↺' : '×', onclick: () => onMute(signal.key),
    }),
  ]);
}

// The SIGNALS card: one ranked list, severity high first, CLEARED last. A row's × hides
// that signal by its key; the hidden ones come back under "show N muted". With `live`,
// RARE and OVERSOLD are read from today's quotes (the badge says so); the rest are the build's.
export function signalsCard(groups, live = null) {
  const stamp = live ? el('span', { class: 'today-live-stamp' }, [liveBadge('LIVE · RARE, OVERSOLD'), ` ${live}`]) : null;
  const signals = rankSignals((Array.isArray(groups) ? groups : []).flatMap((group) => group.chips || []));
  if (!signals.length) return card('SIGNALS', stamp, [el('div', { class: 'today-empty dim', text: 'No signal this session.' })]);
  const storage = mutedStorage();
  const muted = new Set(readMuted(storage));
  let showMuted = false;
  const list = el('div', { class: 'today-signals' });
  const draw = () => {
    const hidden = signals.filter((s) => muted.has(s.key));
    const shown = signals.filter((s) => !muted.has(s.key));
    const onMute = (key) => {
      if (muted.has(key)) muted.delete(key);
      else muted.add(key);
      writeMuted(storage, [...muted]);
      draw();
    };
    const toggle = hidden.length ? el('button', {
      class: 'sig-more', type: 'button', text: showMuted ? `hide ${hidden.length} muted` : `show ${hidden.length} muted`,
      onclick: () => { showMuted = !showMuted; draw(); },
    }) : null;
    list.replaceChildren(...[
      ...shown.map((s) => signalRow(s, false, onMute)),
      ...(showMuted ? hidden.map((s) => signalRow(s, true, onMute)) : []),
      toggle,
    ].filter(Boolean));
  };
  draw();
  return card('SIGNALS', stamp, [list]);
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
