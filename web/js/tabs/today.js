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

// JUST OUT: the macro releases and the earnings that came out last session.
export function justOutSection(justOut) {
  const macro = justOut?.macro || [];
  const earnings = justOut?.earnings || [];
  const macroRow = (item) => rowNode(item, {
    value: el('span', { class: 'today-value', text: valueText(item.value, item.unit) }),
    detail: item.detail,
  });
  const earningsRow = (item) => {
    const move = valid(item.extra?.return_1d) ? signed(item.extra.return_1d) : sigma(item.z);
    const moveClass = dirClass(valid(item.extra?.return_1d) ? item.extra.return_1d : item.z);
    return rowNode(item, {
      value: el('span', { class: `today-value ${moveClass}`, text: move }),
    });
  };
  return el('div', { class: 'today-section' }, [
    sectionTitle('JUST OUT', justOut?.session ? `· SESSION ${longDay(justOut.session)}` : ''),
    el('div', { class: 'today-block-title', text: 'MACRO' }),
    ...listNodes(macro, macroRow, 'No macro release came out last session.'),
    el('div', { class: 'today-block-title', text: 'EARNINGS' }),
    ...listNodes(earnings, earningsRow, 'No index-weight earnings came out last session.'),
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
  if (ongoing.length) {
    nodes.push(el('div', {
      class: 'today-ongoing dim',
      // The count is added only where the title does not already give it.
      text: `Ongoing: ${ongoing.map((o) => `${o.title}${valid(o.days) && !String(o.title).includes(String(o.days)) ? ` (${o.days} sessions)` : ''}`).join(' · ')}`,
    }));
  }
  return nodes;
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
