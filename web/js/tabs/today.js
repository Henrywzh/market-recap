// TODAY, the landing page: what just came out, what is coming in the next three
// sessions, and what is unusual now. The build's day is today.json; the one part
// that moves during the session is UNUSUAL NOW's MOVES list, which re-ranks the
// names by today's move (against yesterday's close) while the market is open.

import { el, num, sectionTitle, tag, dirClass, DASH } from '../fmt.js';
import { mountLive } from '../live.js';
import { createFeed } from '../live-feed.js';
import { tickerHref } from '../routes.js';
import { liveView } from '../today-live.js';

const valid = (v) => typeof v === 'number' && Number.isFinite(v);
const signed = (v, digits = 2, suffix = '%') => (valid(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${suffix}` : DASH);
const sigma = (v) => signed(v, 1, 'σ');

const ROWS_SHOWN = 10;
// The earnings tiles are larger than rows, so fewer show before the fold.
const TILES_SHOWN = 8;
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

// A value with its unit, as the reader scans it: 2.5%, +12.0 bp, 1.20×.
function valueText(value, unit) {
  if (!valid(value)) return DASH;
  if (unit === 'bp') return `${value > 0 ? '+' : ''}${num(value, 1)} bp`;
  if (unit === 'pp') return `${value > 0 ? '+' : ''}${num(value, 2)} pp`;
  if (unit === 'x') return `${num(value, 2)}×`;
  if (unit === '%') return `${num(value, 2)}%`;
  return num(value, 2);
}

// The short expectation a coming-up row carries: the build's detail line, with
// the implied move added when the build has one.
function expectationText(item) {
  const parts = [item.detail];
  if (valid(item.extra?.implied_pct)) parts.push(`implied ±${num(item.extra.implied_pct, 1)}%`);
  return parts.filter(Boolean).join(' · ') || null;
}

// One row of a list: when, subject, what happened, and the tags and numbers beside it.
// The title, with its subject in bold: most titles already open with it ("NI rose
// 3.5%"), so the subject is not printed twice; one that does not gets it in front.
export function titleParts(subject, title) {
  const s = String(subject ?? '');
  const t = String(title ?? '');
  if (!s) return ['', t];
  return t.startsWith(s) ? [s, t.slice(s.length)] : [s, ` · ${t}`];
}

// Only HIGH is tagged: a tag on every row is a tag on none.
function rowNode(item, { value = null, extras = [], detail = item.detail } = {}) {
  const [lead, rest] = titleParts(item.subject, item.title);
  const tags = [
    item.importance === 'high' ? tag('HIGH', 'warn') : null,
    item.evidence === 'tested' ? tag('TESTED', 'info', 'Backed by a research table already in the build') : null,
    ...extras,
  ];
  const body = [
    el('span', { class: 'today-when dim', text: whenText(item) }),
    el('span', { class: 'today-text' }, [
      el('span', { class: 'today-title' }, [el('b', { class: 'today-subject', text: lead }), rest]),
      detail ? el('span', { class: 'today-detail dim', text: detail }) : null,
    ]),
    value,
    el('span', { class: 'today-tags' }, tags.filter(Boolean)),
  ];
  const classes = `today-row${item.new === false ? ' is-ongoing' : ''}`;
  return item.link ? el('a', { class: classes, href: item.link }, body) : el('div', { class: classes }, body);
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

// Above or below the forecast, read only when both sides carry the same unit;
// null when there is no forecast or the comparison would mix units.
export function surpriseDirection(item) {
  const forecast = forecastOf(item);
  if (!forecast || !valid(item.value) || forecast.unit !== item.unit) return null;
  if (item.value > forecast.value) return 'above';
  if (item.value < forecast.value) return 'below';
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

// The importance dot: filled for high, hollow for low; the word is for the tooltip.
function importanceDot(importance) {
  const level = ['high', 'medium', 'low'].includes(importance) ? importance : 'low';
  return el('span', { class: `today-dot is-${level}`, title: `${level} importance`, 'aria-label': `${level} importance` });
}

// One macro release as a card: its name, the actual large, the forecast beside it
// when there is one, and the build's detail line.
function macroCard(item) {
  const forecast = forecastOf(item);
  const direction = surpriseDirection(item);
  const glyph = { above: '▲', below: '▼' }[direction] || '';
  const body = [
    el('span', { class: 'today-card-name' }, [importanceDot(item.importance), el('b', { text: item.subject })]),
    el('span', { class: 'today-card-value', text: valueText(item.value, item.unit) }),
    forecast ? el('span', { class: `today-card-forecast${direction ? ` is-${direction}` : ''}` }, [
      glyph ? el('span', { class: 'today-glyph', text: glyph }) : null,
      ` vs forecast ${valueText(forecast.value, forecast.unit)}`,
    ]) : null,
    item.detail ? el('span', { class: 'today-card-detail dim', text: item.detail }) : null,
  ];
  const classes = `today-card${item.importance === 'high' ? ' is-high' : ''}`;
  return item.link
    ? el('a', { class: classes, href: item.link, title: item.title }, body)
    : el('div', { class: classes, title: item.title }, body);
}

// A release with no number (an options expiry, say) as a dim chip on the line below the cards.
function macroChips(items) {
  return el('div', { class: 'today-chips' }, items.map((item) => {
    const children = [importanceDot(item.importance), item.title];
    return item.link
      ? el('a', { class: 'today-chip dim', href: item.link }, children)
      : el('span', { class: 'today-chip dim' }, children);
  }));
}

function macroNodes(items) {
  if (!items.length) return [el('div', { class: 'today-empty dim', text: 'No macro release came out last session.' })];
  const numeric = items.filter((item) => valid(item.value));
  const chips = items.filter((item) => !valid(item.value));
  return [
    ...(numeric.length ? gridNodes(numeric, macroCard, ROWS_SHOWN, 'today-cards') : []),
    ...(chips.length ? [macroChips(chips)] : []),
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

function earningsNodes(items) {
  if (!items.length) return [el('div', { class: 'today-empty dim', text: 'No index-weight earnings came out last session.' })];
  const maxMove = Math.max(0, ...items.map((i) => i.extra?.return_1d).filter(valid).map(Math.abs));
  return [
    el('div', { class: 'today-tiles-summary dim', text: earningsSummary(items) }),
    ...gridNodes([...items].sort(byWeight), (item) => earningsTile(item, maxMove), TILES_SHOWN, 'today-tiles'),
  ];
}

// JUST OUT: the macro releases as cards and the earnings as tiles, for last session.
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

// COMING UP: one block per session, then the high-importance items beyond them.
export function comingUpSection(coming) {
  const days = coming?.days || [];
  const dayNodes = days.map((day) => el('div', { class: 'today-day' }, [
    el('div', { class: 'today-day-head', text: dayLabel(day.date) }),
    ...listNodes(day.items, (item) => rowNode(item, { detail: expectationText(item) }),
      'Nothing on the calendar this session that matters here.'),
  ]));
  const later = el('div', { class: 'today-day' }, [
    el('div', { class: 'today-day-head', text: `LATER · HIGH IMPORTANCE${coming?.later_until ? ` · TO ${dayLabel(coming.later_until)}` : ''}` }),
    ...listNodes(coming?.later, (item) => rowNode(item, { detail: expectationText(item) }),
      'Nothing high-importance in the weeks after.'),
  ]);
  return el('div', { class: 'today-section' }, [
    sectionTitle('COMING UP', days.length ? `· NEXT ${days.length} SESSIONS` : ''),
    ...dayNodes,
    later,
  ]);
}

// A live move, in the terms the build uses: return, its σ, and the own part.
function liveMoveRow(item) {
  const detail = `${signed(item.ret_pct)} today · ${sigma(item.z)} of its own σ · own part ${sigma(item.z_own)}`;
  return rowNode({
    subject: item.ticker,
    title: item.name,
    link: tickerHref(item.ticker),
    importance: null,
    evidence: 'description',
    time: null,
    timing: null,
    new: true,
  }, {
    value: el('span', { class: `today-value ${dirClass(item.ret_pct)}`, text: signed(item.ret_pct) }),
    detail,
  });
}

function officialMoveRow(item) {
  const value = el('span', { class: `today-value ${dirClass(item.z)}`, text: sigma(item.z) });
  return rowNode(item, { value });
}

// The UNUSUAL NOW block (MOVES, STATES, EVENTS) and its ongoing line. `view.live`
// is the live list while the market is open (null for the build's close).
export function unusualNodes(unusual, view) {
  const live = view.live;
  const moves = live ? live.items.map(liveMoveRow) : (unusual?.moves || []).map(officialMoveRow);
  const states = unusual?.states || [];
  const events = unusual?.events || [];
  const ongoing = unusual?.ongoing || [];
  const stamp = live
    ? el('span', { class: 'today-stamp' }, [tag('LIVE · PROVISIONAL', 'warn', 'Today\'s move so far, against the last close; not official'), ` ${clock(live.time)} quotes`])
    : `· AS OF ${longDay(view.asOf)} CLOSE`;
  const nodes = [sectionTitle('UNUSUAL NOW', ''), el('div', { class: 'today-close-head' }, [stamp])];
  const nothing = !moves.length && !states.length && !events.length;
  if (nothing) {
    nodes.push(el('div', { class: 'today-empty dim', text: NOTHING_MOVED }));
  } else {
    const block = (title, rows, empty) => el('div', { class: 'today-block' }, [
      el('div', { class: 'today-block-title', text: title }),
      ...listNodes(rows, (row) => row, empty),
    ]);
    nodes.push(
      block('MOVES', moves, 'No name is beyond its own volatility.'),
      block('STATES', states.map(officialStateRow), 'No market state started or ended.'),
      block('EVENTS', events.map(officialStateRow), 'No event to report.'),
    );
  }
  nodes.push(oversoldBlock(unusual?.oversold || []));
  if (ongoing.length) {
    nodes.push(el('div', {
      class: 'today-ongoing dim',
      // The count is added only where the title does not already give it.
      text: `Ongoing: ${ongoing.map((o) => `${o.title}${valid(o.days) && !String(o.title).includes(String(o.days)) ? ` (${o.days} sessions)` : ''}`).join(' · ')}`,
    }));
  }
  return nodes;
}

// Indices and sector funds whose RSI(6) closed under 30 or 20, deepest first.
// The RSI sits in a small gauge (0-30 shown) so the depth reads at a glance.
export function oversoldGauge(rsi) {
  if (!valid(rsi)) return null;
  return Math.max(0, Math.min(100, (rsi / 30) * 100));
}

function oversoldRow(item) {
  const rsi = item.extra?.rsi ?? item.value;
  const deep = item.extra?.line === 20;
  const width = oversoldGauge(rsi);
  const value = el('span', { class: `today-value today-rsi${deep ? ' is-deep' : ''}` }, [
    num(rsi, 1),
    width === null ? null : el('span', { class: 'today-rsi-bar' }, [el('span', { style: `width:${width.toFixed(0)}%` })]),
  ]);
  // The detail is the same for every row, so the block says it once.
  return rowNode(item, { value, detail: null, extras: [tag(deep ? 'BELOW 20' : 'BELOW 30', deep ? 'warn' : 'info')] });
}

function oversoldBlock(items) {
  return el('div', { class: 'today-block' }, [
    el('div', { class: 'today-block-title', text: 'OVERSOLD · RSI(6), INDICES & SECTOR FUNDS' }),
    ...listNodes(items.map(oversoldRow), (row) => row, 'No index or sector fund is below 30.'),
    items.length ? el('div', { class: 'today-detail dim', text: items[0].detail }) : null,
  ]);
}

function officialStateRow(item) {
  return rowNode(item, { value: valid(item.z) ? el('span', { class: 'today-value', text: sigma(item.z) }) : null });
}

// The live part: the MOVES list follows today's quotes while the market is
// open. Both boards come from the same quote function the heat map uses, on the
// same cadence; the feeds stop when the page leaves the screen. Until the moves
// file and the first quotes arrive, the build's close stands.
function startLive(host, data, ctx) {
  const state = { moves: null, heat: null, etfs: null };
  let showingLive = false;
  const paint = () => {
    const live = liveView(state, data.live);
    showingLive = Boolean(live);
    host.replaceChildren(...unusualNodes(data.unusual, { live, asOf: data.as_of }));
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

export default function renderToday(root, data, manifest, ctx = {}) {
  // One element for the whole page, so its phone gutter is its own (CSS).
  const page = el('div', { class: 'today-page' });
  root.append(page);
  page.append(sectionTitle('TODAY', 'WHAT JUST HAPPENED, WHAT IS COMING, WHAT IS UNUSUAL'));
  const sessions = (data.sessions || []).map(dayLabel).join(' · ');
  page.append(el('div', { class: 'today-close-head', text: `SESSION CLOSE · ${longDay(data.as_of)}${sessions ? ` · NEXT SESSIONS ${sessions}` : ''}` }));
  page.append(el('div', { class: 'today-live' }, [mountLive({ asOf: data.as_of })]));
  const unusualHost = el('div', { class: 'today-unusual' });
  unusualHost.replaceChildren(...unusualNodes(data.unusual, { live: null, asOf: data.as_of }));
  page.append(el('div', { class: 'today-columns' }, [
    el('div', { class: 'today-col' }, [justOutSection(data.just_out), comingUpSection(data.coming_up)]),
    el('div', { class: 'today-col' }, [unusualHost]),
  ]));
  // A part the build could not make is named in a footnote, not by a failed page
  // and not above the news: most are a source that was late, not a broken page.
  const missing = (data.unavailable || []).map((u) => `${u.part}: ${u.reason}`);
  if (missing.length) page.append(el('div', { class: 'field-note dim today-missing', text: `Not in this build · ${missing.join(' · ')}` }));
  if (ctx.loadArtifact && data.live) startLive(unusualHost, data, ctx);
}
