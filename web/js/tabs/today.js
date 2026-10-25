// TODAY, the landing page: the picture of the day first (the headline, the board by
// index and sector), then what the signals say, the movers, what just came out and
// what is coming in the next three sessions. The build's day is today.json; the one
// part that moves during the session is the MOVERS table, which re-ranks the names
// by today's move (against yesterday's close) while the market is open.

import { el, num, sectionTitle, tag, liveBadge, dirClass, table, DASH } from '../fmt.js';
import { mountLive } from '../live.js';
import { createFeed } from '../live-feed.js';
import { liveView, liveIsCurrent } from '../today-live.js';
import { liveBoard, headlineOf, liveSignals } from '../today-live-board.js';
import {
  boardCard, headlineNode, signalGroups, signalsCard, moverRecords, moversTable, sectorLine, remainingEvents, eventNodes,
} from '../today-board.js';

const valid = (v) => typeof v === 'number' && Number.isFinite(v);
const signed = (v, digits = 2, suffix = '%') => (valid(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${suffix}` : DASH);

const ROWS_SHOWN = 10;
// The earnings tiles are larger than rows, so fewer show before the fold.
const TILES_SHOWN = 8;
const LATER_SHOWN = 8;
const LATER_HEAD = ['DATE', 'TIME', 'EVENT', 'EXPECTED'];
const NOTHING_MOVED = 'Nothing crossed a threshold this session.';

// Dates are calendar days, not instants: read them in UTC so no zone shifts them.
const DAY = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric' });
const LONG_DAY = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric' });

export function dayLabel(iso) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso || '')) return iso || DASH;
  return DAY.format(new Date(`${iso}T00:00:00Z`)).replace(/,/g, '').toUpperCase();
}

// The session's date as a header reads it: 'OCT 16, 2026'.
function longDay(iso) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso || '')) return iso || DASH;
  return LONG_DAY.format(new Date(`${iso}T00:00:00Z`)).toUpperCase();
}

// The quote time of a live price, in New York, as the markets quote it.
function clock(seconds) {
  if (!valid(seconds)) return DASH;
  return `${new Date(seconds * 1000).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'America/New_York', hour12: false })} ET`;
}

// When an item happens: its clock time, else its timing relative to the session.
export function whenText(item) {
  if (item.time) return `${item.time} ET`;
  if (item.timing === 'bmo') return 'BEFORE OPEN';
  if (item.timing === 'amc') return 'AFTER CLOSE';
  return '';
}

// A value with its unit, as the reader scans it: 2.5%, +12.0 bp, 1.20×, 194k, 7.08M.
function valueText(value, unit) {
  if (!valid(value)) return DASH;
  if (unit === 'bp') return `${value > 0 ? '+' : ''}${num(value, 1)} bp`;
  if (unit === 'pp') return `${value > 0 ? '+' : ''}${num(value, 2)} pp`;
  if (unit === 'x') return `${num(value, 2)}×`;
  if (unit === '%') return `${num(value, 2)}%`;
  if (unit === 'k') return `${num(value, 0)}k`;
  if (unit === 'M') return `${num(value, 2)}M`;
  return num(value, 2);
}

// The shortened expectation text for the LATER table, the full line in its title.
const shorten = (text, max = 56) => (text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text);

// The median of the numbers in a list, or null when there are none. The median
// keeps one large move from setting the whole day's tone.
export function median(values) {
  const sorted = (values || []).filter(valid).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

// The EPS verdict a surprise gives. A surprise of exactly zero is in line, and a
// missing surprise gets no verdict at all rather than a guess.
export function epsVerdict(surprise) {
  if (!valid(surprise)) return null;
  if (surprise > 0) return { word: 'BEAT', tone: 'up' };
  if (surprise < 0) return { word: 'MISS', tone: 'down' };
  return { word: 'IN LINE', tone: 'flat' };
}

// The one-line summary over every reporter, not only the tiles shown.
export function earningsSummary(items) {
  if (!items?.length) return null;
  const surprises = items.map((i) => i.extra?.surprise_pct);
  const beat = surprises.filter((s) => valid(s) && s > 0).length;
  const miss = surprises.filter((s) => valid(s) && s < 0).length;
  const parts = [`${items.length} reported`, `${beat} beat`, `${miss} miss`];
  const medianMove = median(items.map((i) => i.extra?.return_1d));
  if (valid(medianMove)) parts.push(`median move ${signed(medianMove, 1)}`);
  const heaviest = items.filter((i) => valid(i.extra?.weight))
    .reduce((top, i) => (!top || i.extra.weight > top.extra.weight ? i : top), null);
  if (heaviest) parts.push(`largest weight: ${heaviest.subject}`);
  return parts.join(' · ');
}

// The survey consensus for a release, the forecast the actual is read against.
// Market-implied and model rows are not used: they are not the number the
// release is expected to print.
export function forecastOf(item) {
  return (item.extra?.expectations || []).find((e) => e.kind === 'survey' && valid(e.value)) || null;
}

// What the market priced the release at the evening before (Kalshi, then
// Polymarket), in the release's own unit; null when none was recorded or it
// is a different quantity (a probability of a hike is not a rate).
export function marketOf(item) {
  const readings = item.extra?.market_before?.readings || [];
  return readings.find((e) => valid(e.value) && e.unit === item.unit) || null;
}

// Above or below a reference (the survey forecast unless one is given), read only
// when both sides carry the same unit; null when there is none or the units differ.
export function surpriseDirection(item, reference = forecastOf(item)) {
  if (!reference || !valid(item.value) || reference.unit !== item.unit) return null;
  if (item.value > reference.value) return 'above';
  if (item.value < reference.value) return 'below';
  return 'in-line';
}

// A grid of the first `shown` items, the rest folded under "N more" as the rows are.
function gridNodes(items, toNode, shown, gridClass) {
  const head = el('div', { class: gridClass }, items.slice(0, shown).map(toNode));
  if (items.length <= shown) return [head];
  const rest = el('div', { class: gridClass }, items.slice(shown).map(toNode));
  return [head, el('details', { class: 'today-more' }, [
    el('summary', { text: `${items.length - shown} more` }),
    rest,
  ])];
}

// The rows of a list, with the rest behind a fold once there are many.
function listNodes(items, toRow, emptyText) {
  if (!items?.length) return [el('div', { class: 'today-empty dim', text: emptyText })];
  const shown = items.slice(0, ROWS_SHOWN).map(toRow);
  if (items.length <= ROWS_SHOWN) return shown;
  const rest = items.slice(ROWS_SHOWN).map(toRow);
  return [...shown, el('details', { class: 'today-more' }, [
    el('summary', { text: `${rest.length} more` }),
    ...rest,
  ])];
}

// The period a release covers: the print's own date, else the build's detail line.
function periodOf(item) {
  const period = item.extra?.prints?.[0]?.period || (item.detail ? String(item.detail).replace(/^For /, '') : null);
  return period || DASH;
}

// The macro releases with a number as one table: the actual, the survey forecast
// beside it with the direction it was read in, and the period. A release with no
// number is named on one line under the table.
function macroTable(items) {
  // The actual against one reference: the glyph of its direction and the reference's figure.
  const against = (item, reference, source = null) => {
    const direction = surpriseDirection(item, reference);
    const glyph = { above: '▲', below: '▼' }[direction] || '';
    return el('td', { class: `today-value${direction ? ` is-${direction}` : ''}`, title: source }, reference ? [
      glyph ? el('span', { class: 'today-glyph', text: glyph }) : null,
      ` ${valueText(reference.value, reference.unit)}`,
    ] : [DASH]);
  };
  const rows = items.map((item) => {
    const market = marketOf(item);
    return el('tr', {}, [
      el('td', {}, [item.importance === 'high' ? el('b', { text: item.subject }) : item.subject]),
      el('td', { class: 'today-value', text: valueText(item.value, item.unit) }),
      against(item, forecastOf(item), 'Survey consensus'),
      against(item, market, market ? `${market.source_label || market.source} median, as priced at the ${item.extra.market_before.as_of} evening build` : null),
      el('td', { class: 'dim', text: periodOf(item) }),
    ]);
  });
  return table(['EVENT', 'ACTUAL', 'VS FORECAST', 'VS MARKET', 'PERIOD'], rows, { class: 'today-macro' });
}

function macroNodes(items) {
  if (!items.length) return [el('div', { class: 'today-empty dim', text: 'No macro release came out last session.' })];
  const numeric = items.filter((item) => valid(item.value));
  const quiet = items.filter((item) => !valid(item.value));
  return [
    ...(numeric.length ? [macroTable(numeric)] : []),
    ...(quiet.length ? [el('div', { class: 'today-detail dim', text: `Also: ${quiet.map((item) => item.subject).join(', ')}` })] : []),
  ];
}

// One reporter as a tile: ticker, EPS verdict and surprise, the session move, and a
// bar for its size against the largest move in the set. The bar is scaled by the
// caller so the tiles compare with one another.
function earningsTile(item, maxMove) {
  const verdict = epsVerdict(item.extra?.surprise_pct);
  const move = item.extra?.return_1d;
  const fill = el('span', { class: `today-tile-bar-fill ${dirClass(move)}` });
  if (valid(move) && maxMove > 0) fill.style.width = `${(Math.abs(move) / maxMove) * 100}%`;
  const body = [
    el('span', { class: 'today-tile-head' }, [
      el('b', { class: 'today-tile-ticker', text: item.subject }),
      valid(item.extra?.weight) ? el('span', { class: 'today-tile-weight dim', text: `${num(item.extra.weight, 2)}% wt` }) : null,
    ]),
    el('span', { class: 'today-tile-eps' }, [
      verdict ? el('span', { class: `today-tile-verdict ${verdict.tone}`, text: verdict.word }) : null,
      el('span', { class: `today-value ${verdict ? verdict.tone : ''}`, text: signed(item.extra?.surprise_pct, 1) }),
    ]),
    el('span', { class: `today-tile-move today-value ${dirClass(move)}`, text: signed(move, 1) }),
    el('span', { class: 'today-tile-bar' }, [fill]),
  ];
  const classes = `today-tile${item.importance === 'high' ? ' is-high' : ''}`;
  return item.link
    ? el('a', { class: classes, href: item.link, title: item.title }, body)
    : el('div', { class: classes, title: item.title }, body);
}

// Heaviest index weight first, so the names that move the index lead.
const byWeight = (a, b) => (b.extra?.weight ?? -1) - (a.extra?.weight ?? -1);

// A reporter with no result yet: one line, names by weight, each a link. Its
// results come with the next build, so it gets no tile.
function pendingLine(items) {
  const names = items.flatMap((item, i) => [
    i ? ', ' : '',
    el(item.link ? 'a' : 'span', { href: item.link, text: item.subject }),
  ]);
  const lead = items.length === 1 ? 'Reports after the close: ' : `${items.length} report after the close: `;
  return el('div', { class: 'today-pending dim' }, [lead, ...names, ' — results in the next build']);
}

// The reported earnings as tiles, then the reporters still waiting on a result.
function earningsNodes(items) {
  const reported = items.filter((item) => valid(item.extra?.eps)).sort(byWeight);
  const pending = items.filter((item) => !valid(item.extra?.eps)).sort(byWeight);
  const nodes = [];
  if (reported.length) {
    const maxMove = Math.max(0, ...reported.map((i) => i.extra?.return_1d).filter(valid).map(Math.abs));
    nodes.push(
      el('div', { class: 'today-tiles-summary dim', text: earningsSummary(reported) }),
      ...gridNodes(reported, (item) => earningsTile(item, maxMove), TILES_SHOWN, 'today-tiles'),
    );
  } else if (!pending.length) {
    nodes.push(el('div', { class: 'today-empty dim', text: 'No index-weight earnings came out last session.' }));
  }
  if (pending.length) nodes.push(pendingLine(pending));
  return nodes;
}

// JUST OUT: the macro releases as a table and the earnings as tiles, for last session.
export function justOutSection(justOut) {
  const macro = justOut?.macro || [];
  const earnings = justOut?.earnings || [];
  return el('div', { class: 'today-section' }, [
    sectionTitle('JUST OUT', justOut?.session ? `· SESSION ${longDay(justOut.session)}` : ''),
    el('div', { class: 'today-block-title', text: 'MACRO' }),
    ...macroNodes(macro),
    el('div', { class: 'today-block-title', text: 'EARNINGS' }),
    ...earningsNodes(earnings),
  ]);
}

// The day's coming-up row: when, the subject, and the one figure the build has.
function dayRow(item) {
  const figure = valid(item.extra?.implied_pct) ? `implied ±${num(item.extra.implied_pct, 1)}%` : item.detail;
  const classes = `today-row${item.importance === 'high' ? ' is-high' : ''}`;
  const body = [
    el('span', { class: 'today-when dim', text: whenText(item) }),
    el('span', { class: 'today-subject', text: item.subject }),
    figure ? el('span', { class: 'today-detail dim', text: figure }) : null,
  ];
  return item.link ? el('a', { class: classes, href: item.link }, body) : el('div', { class: classes }, body);
}

// The expected figure for the LATER table: the implied move, else the expectation text.
export function expectedOf(item) {
  const detail = item.detail || '';
  const implied = valid(item.extra?.implied_pct) ? item.extra.implied_pct
    : Number((detail.match(/options price an? ([\d.]+)% move/) || [])[1]);
  const eps = (detail.match(/EPS forecast (-?[\d.]+)/) || [])[1];
  const parts = [valid(implied) ? `±${num(implied, 1)}%` : null, eps ? `EPS ${eps}` : null].filter(Boolean);
  if (parts.length) return parts.join(' · ');
  return detail ? shorten(detail.replace(/^Expected:\s*/, ''), 30) : DASH;
}

// LATER: the high-importance items past the sessions, as one table, past eight a fold.
function laterNodes(items, until) {
  const high = (items || []).filter((item) => item.importance === 'high');
  const head = el('div', { class: 'today-block-title', text: `LATER · HIGH IMPORTANCE${until ? ` · TO ${dayLabel(until)}` : ''}` });
  if (!high.length) return [head, el('div', { class: 'today-empty dim', text: 'Nothing high-importance in the weeks after.' })];
  const rowOf = (item) => el('tr', {}, [
    el('td', { text: dayLabel(item.date) }),
    el('td', { text: whenText(item) || DASH }),
    el('td', { text: item.subject }),
    el('td', { class: 'today-value', text: expectedOf(item), title: item.detail || '' }),
  ]);
  const rest = high.slice(LATER_SHOWN);
  return [
    head,
    table(LATER_HEAD, high.slice(0, LATER_SHOWN).map(rowOf), { class: 'today-later' }),
    ...(rest.length ? [el('details', { class: 'today-more' }, [
      el('summary', { text: `${rest.length} more` }),
      table(LATER_HEAD, rest.map(rowOf), { class: 'today-later' }),
    ])] : []),
  ];
}

// COMING UP: one column per session, then the high-importance items beyond them.
export function comingUpSection(coming) {
  const days = coming?.days || [];
  const dayNodes = days.map((day) => el('div', { class: 'today-day' }, [
    el('div', { class: 'today-day-head', text: dayLabel(day.date) }),
    ...listNodes(day.items, dayRow, 'Nothing on the calendar this session that matters here.'),
  ]));
  return el('div', { class: 'today-section' }, [
    sectionTitle('COMING UP', days.length ? `· NEXT ${days.length} SESSIONS` : ''),
    el('div', { class: 'today-days' }, dayNodes),
    ...laterNodes(coming?.later, coming?.later_until),
  ]);
}

// The MOVERS block: the build's close, or the live list while the market is open
// (`view.live` is the live list, null for the close). The sector line, the table and
// the rest of the events follow the stamp.
export function moversNodes(unusual, view) {
  const live = view.live;
  const records = moverRecords(unusual, live ? live.items : null);
  const events = remainingEvents(unusual);
  const sector = sectorLine(unusual);
  const stamp = live
    ? el('span', { class: 'today-stamp' }, [liveBadge('LIVE · PROVISIONAL', 'Today\'s move so far, against the last close; not official'), ` ${clock(live.time)} quotes`])
    : `· AS OF ${longDay(view.asOf)} CLOSE`;
  const nodes = [
    el('div', { class: 'today-block-title', text: 'MOVERS' }),
    el('div', { class: 'today-close-head' }, [stamp]),
  ];
  if (!records.length && !events.length && !sector) return [...nodes, el('div', { class: 'today-empty dim', text: NOTHING_MOVED })];
  // replaceChildren would print a null as the word "null", so only nodes go out.
  return [
    ...nodes,
    sector,
    records.length ? moversTable(records) : null,
    ...eventNodes(events),
  ].filter(Boolean);
}

// The page's explanatory text, folded at the bottom: the build's notes, the detail
// of the oversold and rare-move signals, and what the build could not make.
function notesNode(data) {
  const details = [
    ...(data.notes || []),
    data.unusual?.oversold?.[0]?.detail,
    data.unusual?.tails?.[0]?.detail,
  ].filter(Boolean);
  const missing = (data.unavailable || []).map((u) => `${u.part}: ${u.reason}`);
  if (!details.length && !missing.length) return null;
  return el('details', { class: 'method-fold today-notes' }, [
    el('summary', { text: 'ⓘ NOTES' }),
    ...[...new Set(details)].map((text) => el('div', { class: 'method-copy', text })),
    missing.length ? el('div', { class: 'field-note dim today-missing', text: `Not in this build · ${missing.join(' · ')}` }) : null,
  ]);
}

// The live part: the MOVERS table follows today's quotes while the market is
// open. Both boards come from the same quote function the heat map uses, on the
// same cadence; the feeds stop when the page leaves the screen. Until the moves
// file and the first quotes arrive, the build's close stands.
function startLive(host, data, ctx) {
  const state = { moves: null, heat: null, etfs: null };
  let showingLive = false;
  const paint = () => {
    const live = liveView(state, data.live);
    showingLive = Boolean(live);
    host.replaceChildren(...moversNodes(data.unusual, { live, asOf: data.as_of }));
  };
  ctx.loadArtifact('moves').then((moves) => {
    state.moves = moves.rows || [];
    createFeed('api/quotes?board=heatmap', {
      node: host,
      onData: (body) => { state.heat = body; paint(); },
      // A quote going stale flips the list back to the close without new data.
      onTick: () => { if (Boolean(liveView(state, data.live)) !== showingLive) paint(); },
    });
    createFeed('api/quotes?board=sector_etfs', {
      node: host,
      onData: (body) => { state.etfs = body; paint(); },
    });
  }).catch(() => { /* no moves file: the build's close stands, with no live list */ });
}

// The top of the page read live: the headline, THE DAY and the RARE and OVERSOLD
// chips follow the 'today' quote board while the session is open and the S&P 500's
// quote is fresh; otherwise -- closed, stale, or no quotes -- the build's close stands.
// The other signal groups (CHANGED, SCENARIO, ONGOING, ETF FLOWS) are the build's.
function startLiveBoard(parts, data) {
  let body = null;
  let showing = false;
  const view = () => {
    const quotes = new Map((body?.quotes || []).filter((q) => q?.symbol && !q.error).map((q) => [q.symbol, q]));
    const spx = quotes.get('^GSPC');
    if (!liveIsCurrent(body, spx, Date.now())) return null;
    return liveBoard(data.board, quotes);
  };
  const paint = () => {
    const board = view();
    showing = Boolean(board);
    const stamp = board ? `${clock(board.time)} quotes` : null;
    const headline = board ? headlineOf(board) : data.headline;
    const unusual = board
      ? { ...data.unusual, ...liveSignals(board, { oversoldDetail: data.live?.oversold_detail || '' }) }
      : data.unusual;
    parts.headline.replaceChildren(...[headlineNode(headline, stamp)].filter(Boolean));
    const card = boardCard(board || data.board, stamp);
    parts.board.replaceChildren(...(card ? [card.node] : []));
    card?.draw();
    parts.signals.replaceChildren(signalsCard(signalGroups(unusual, (board || data.board)?.rows, data.flows), stamp));
  };
  createFeed('api/quotes?board=today', {
    node: parts.board,
    onData: (answer) => { body = answer; paint(); },
    // A quote going stale flips the page back to the close without new data.
    onTick: () => { if (Boolean(view()) !== showing) paint(); },
  });
}

export default function renderToday(root, data, manifest, ctx = {}) {
  // One element for the whole page, so its phone gutter is its own (CSS).
  const page = el('div', { class: 'today-page' });
  root.append(page);
  page.append(sectionTitle('TODAY', 'WHAT JUST HAPPENED, WHAT IS COMING, WHAT IS UNUSUAL'));
  const sessions = (data.sessions || []).map(dayLabel).join(' · ');
  page.append(el('div', { class: 'today-close-head', text: `SESSION CLOSE · ${longDay(data.as_of)}${sessions ? ` · NEXT SESSIONS ${sessions}` : ''}` }));
  page.append(el('div', { class: 'today-live' }, [mountLive({ asOf: data.as_of })]));
  const parts = { headline: el('div', { class: 'today-headline-host' }), board: el('div', { class: 'today-board-host' }),
    signals: el('div', { class: 'today-signals-host' }) };
  const headline = headlineNode(data.headline);
  if (headline) parts.headline.append(headline);
  const board = boardCard(data.board);
  if (board) parts.board.append(board.node);
  page.append(parts.headline, parts.board);
  const moversHost = el('div', { class: 'today-movers-host' });
  moversHost.replaceChildren(...moversNodes(data.unusual, { live: null, asOf: data.as_of }));
  page.append(el('div', { class: 'today-columns' }, [
    el('div', { class: 'today-col' }, [justOutSection(data.just_out), comingUpSection(data.coming_up)]),
    el('div', { class: 'today-col' }, [
      sectionTitle('UNUSUAL NOW', ''),
      parts.signals,
      moversHost,
    ]),
  ]));
  const notes = notesNode(data);
  if (notes) page.append(notes);
  parts.signals.append(signalsCard(signalGroups(data.unusual, data.board?.rows, data.flows)));
  board?.draw();
  if (ctx.loadArtifact && data.live) startLive(moversHost, data, ctx);
  if (ctx.loadArtifact && data.board?.rows?.length) startLiveBoard(parts, data);
}
