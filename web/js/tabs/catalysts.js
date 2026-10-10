// CATALYSTS: what the last session brought, and what is scheduled next.
//
// Two lanes, as the build assembles them: MACRO & BROAD INDEX (agency
// releases at the agency's time, the Fed's calendar, announced auctions, rule
// events, hand-kept events) and SINGLE NAME (index members' and watchlist
// earnings). The page leads with the shape of the next three weeks and the
// releases that matter; every event keeps its full detail one click down.

import { el, card, table, num, pct, dirClass, sectionTitle, gap, metaRow, DASH } from '../fmt.js';
import { eventCard, outcomeCard, loadPrices } from '../event-card.js';
import { tickerHref } from '../routes.js';

const NEW_YORK = 'America/New_York';
const IMPORTANCE_RANK = { high: 0, medium: 1, low: 2 };
const TIMING_LABEL = { bmo: 'BEFORE OPEN', amc: 'AFTER CLOSE' };
const TIMING_SHORT = { bmo: 'BMO', amc: 'AMC' };
const TIMING_RANK = { bmo: 0, null: 1, amc: 2 };
const FILTER_KEY = 'mr-catalysts-filter';
const STRIP_SESSIONS = 15;
const KEY_RELEASES = 6;
const SHORT_TITLE = {
  'Employment report': 'Payrolls',
  'FOMC decision (statement)': 'FOMC',
  'FOMC minutes': 'FOMC minutes',
  'FOMC press conference': 'FOMC presser',
  'PCE inflation, income & spending': 'PCE',
  'ISM Manufacturing PMI': 'ISM mfg',
  'ISM Services PMI': 'ISM services',
  'JOLTS job openings': 'JOLTS',
  'Initial jobless claims': 'Claims',
  'Durable goods orders': 'Durables',
  'Housing starts & permits': 'Housing starts',
  'Industrial production': 'Ind. production',
  'Monthly options expiry': 'OpEx',
  'US midterm elections': 'Midterms',
};

// --- Time ---------------------------------------------------------------------

function zoneOffsetMinutes(instant, zone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: zone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).formatToParts(instant);
  const get = (type) => Number(parts.find((p) => p.type === type).value);
  return (Date.UTC(get('year'), get('month') - 1, get('day'), get('hour'), get('minute')) - instant.getTime()) / 60000;
}

// A New York wall-clock time as an instant: the page's reader may be anywhere.
function newYorkInstant(day, time) {
  const [y, m, d] = day.split('-').map(Number);
  const [hh, mm] = time.split(':').map(Number);
  const guess = new Date(Date.UTC(y, m - 1, d, hh, mm));
  return new Date(guess.getTime() - zoneOffsetMinutes(guess, NEW_YORK) * 60000);
}

const viewerZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

function localTime(event) {
  if (!event.time || viewerZone === NEW_YORK) return null;
  return newYorkInstant(event.date, event.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
}

function localZoneName(day) {
  const parts = new Intl.DateTimeFormat([], { timeZoneName: 'short' }).formatToParts(new Date(`${day}T12:00:00Z`));
  return parts.find((p) => p.type === 'timeZoneName')?.value || viewerZone;
}

function timeCell(event) {
  if (event.timing) return el('span', { class: 'cat-time', text: TIMING_SHORT[event.timing], title: TIMING_LABEL[event.timing] });
  if (!event.time) return el('span', { class: 'cat-time dim', text: 'TBA' });
  const local = localTime(event);
  return el('span', { class: 'cat-time' }, [
    `${event.time}`,
    local ? el('span', { class: 'dim', text: ` ${local}` }) : null,
  ]);
}

function dayLabel(day) {
  const d = new Date(`${day}T12:00:00Z`);
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }).toUpperCase();
}

function stripLabel(day) {
  const d = new Date(`${day}T12:00:00Z`);
  const weekday = d.toLocaleDateString('en-US', { weekday: 'short', timeZone: 'UTC' }).toUpperCase();
  return `${weekday} ${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
}

function addDays(day, count) {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + count);
  return d.toISOString().slice(0, 10);
}

function weekdaysAfter(day, count) {
  const out = [];
  let cursor = day;
  while (out.length < count) {
    cursor = addDays(cursor, 1);
    const weekday = new Date(`${cursor}T12:00:00Z`).getUTCDay();
    if (weekday !== 0 && weekday !== 6) out.push(cursor);
  }
  return out;
}

// --- Numbers ----------------------------------------------------------------------

function shortTitle(event) {
  return SHORT_TITLE[event.title] || (event.title.length > 16 ? `${event.title.slice(0, 15)}…` : event.title);
}

function compactCount(value) {
  if (value >= 1e6) return num(value / 1e6, 2) + 'm';
  if (value >= 1e3) return num(value / 1e3, 0) + 'k';
  return num(value, 0);
}

function expectationValue(row) {
  return row.unit === 'p' ? num(row.value * 100, row.decimals) + '%' : num(row.value, row.decimals) + row.unit;
}

function printValue(p) {
  return p.value === null || p.value === undefined ? DASH : `${num(p.value, p.decimals)}${p.unit}`;
}

// The period a print covers, as its release names it: a quarter for q/q
// series, a month otherwise.
function periodOf(p) {
  if (!p?.period) return '';
  const d = new Date(`${p.period.slice(0, 10)}T12:00:00Z`);
  if (/q\/q/i.test(p.label)) return `Q${Math.floor(d.getUTCMonth() / 3) + 1}`;
  return d.toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' });
}

function formatExpectation(row) {
  let range = '';
  if (row.low != null && row.high != null) range = ` (${num(row.low, row.decimals)}–${num(row.high, row.decimals)})`;
  else if (row.low != null) range = ` (p10 ${num(row.low, row.decimals)})`;
  const interest = row.open_interest != null ? ` OI ${compactCount(row.open_interest)}` : '';
  const spread = row.spread != null ? ` spread ${Math.round(row.spread * 100)}¢` : '';
  return `${row.label} ${expectationValue(row)}${range}${interest}${spread} ${row.source_label}`;
}

// Two labels name the same measure when they agree on the change basis
// (y/y, m/m, q/q) and on core-or-headline; without a basis, on the first word.
function sameMeasure(a, b) {
  const basis = (label) => (/(y\/y|m\/m|q\/q)/i.exec(label) || [''])[0].toLowerCase();
  const core = (label) => /\bcore\b/i.test(label);
  if (basis(a) || basis(b)) return basis(a) === basis(b) && core(a) === core(b);
  return a.toLowerCase().split(' ')[0] === b.toLowerCase().split(' ')[0];
}

const KIND_ORDER = ['survey', 'market', 'model'];

function knownPrints(event) {
  return (event.prints || []).filter((p) => p.value !== null && p.value !== undefined);
}

// The headline pair: the first forecast (survey, else market, else nowcast)
// that has a previous print on the same measure; failing that, the first
// forecast alone. A forecast is never set against a different measure.
function headline(event) {
  const rows = [...(event.expectations || [])].sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind));
  const prints = knownPrints(event);
  for (const row of rows) {
    const previous = prints.find((p) => sameMeasure(row.label, p.label));
    if (previous) return { expectation: row, previous };
  }
  return { expectation: rows[0] || null, previous: rows.length ? null : prints[0] || null };
}

function eventWeight(event) {
  return (event.index_weights || {}).SPX || 0;
}

// --- Pieces ------------------------------------------------------------------------

function importanceDot(importance) {
  return el('span', { class: `cat-dot cat-${importance}`, title: `${importance} importance` });
}

function certaintyTag(event, labels) {
  if (event.certainty_class === 'official_schedule' || event.certainty_class === 'official_announcement') return null;
  return el('span', { class: 'cat-tag', title: labels[event.certainty_class] || '', text: event.certainty_class.replace('_', ' ').toUpperCase() });
}

function rangeBar(row) {
  if (row.low == null || row.high == null || row.high <= row.low) return null;
  const pad = (row.high - row.low) * 0.25;
  const lo = row.low - pad;
  const span = row.high + pad - lo;
  const at = (value) => `${Math.max(0, Math.min(100, ((value - lo) / span) * 100))}%`;
  return el('div', { class: 'cat-range', title: formatExpectation(row) }, [
    el('span', { class: 'cat-range-label', text: `${row.source_label} ${row.label}` }),
    el('span', { class: 'cat-range-track' }, [
      el('span', { class: 'cat-range-fill', style: `left:${at(row.low)};right:calc(100% - ${at(row.high)})` }),
      el('span', { class: 'cat-range-dot', style: `left:${at(row.value)}` }),
    ]),
    el('span', { class: 'cat-range-ends', text: `${num(row.low, row.decimals)}–${num(row.high, row.decimals)}` }),
  ]);
}

function actualSpans(event) {
  return (event.actuals || []).map((row) => {
    const unit = row.unit === '%' ? '%' : row.unit ? row.unit : '';
    return el('span', { class: 'cat-actual-item' }, [
      el('span', { class: 'dim', text: `${row.label} ` }),
      el('span', { class: row.surprise == null ? '' : dirClass(row.surprise), text: num(row.value, row.decimals) + unit }),
      row.forecast == null ? null : el('span', { class: 'dim', text: ` vs ${num(row.forecast, row.decimals)}${unit}` }),
    ]);
  });
}

// Everything the build knows about one release, shown when its row is opened.
function macroDetail(event, labels) {
  const rows = event.expectations || [];
  const lines = ['survey', 'market', 'model'].map((kind) => {
    const items = rows.filter((row) => row.kind === kind);
    if (!items.length) return null;
    const label = kind === 'survey' ? 'Survey' : kind === 'market' ? 'Market' : 'Nowcast';
    return el('div', { text: `${label}: ${items.map(formatExpectation).join(' · ')}` });
  });
  const prints = (event.prints || []).filter((p) => p.value !== null);
  return el('div', { class: 'cat-detail' }, [
    event.source_title && event.source_title !== event.title ? el('div', { text: event.source_title }) : null,
    event.detail ? el('div', { text: event.detail }) : null,
    event.actuals?.length ? el('div', { text: `Actual (TradingView; the agency release is authoritative): ${event.actuals.map((a) => `${a.label} ${num(a.value, a.decimals)}${a.unit === '%' ? '%' : a.unit || ''}`).join(' · ')}` }) : null,
    ...lines,
    prints.length ? el('div', { text: `Previous: ${prints.map((p) => `${p.label} ${printValue(p)}${p.period ? ` (${p.period.slice(0, 7)})` : ''}`).join(' · ')}` }) : null,
    el('div', {}, [
      labels[event.certainty_class] ? `Date: ${labels[event.certainty_class]}` : null,
      event.source_url ? el('span', {}, [' · ', el('a', { href: event.source_url, target: '_blank', rel: 'noopener', text: event.source_id })]) : null,
    ]),
  ]);
}

function macroRow(event, labels) {
  const { expectation, previous } = headline(event);
  const figures = [];
  if (event.actuals?.length) figures.push(...actualSpans(event));
  else {
    // A probability names its outcome; a level is read against the previous print.
    if (expectation) figures.push(el('span', {}, [el('span', { class: 'dim', text: expectation.unit === 'p' ? `${expectation.label} ` : 'F ' }), expectationValue(expectation)]));
    if (previous) figures.push(el('span', { class: 'dim', text: `P ${printValue(previous)}` }));
  }
  const summary = el('summary', { class: 'cat-row' }, [
    timeCell(event),
    el('span', { class: 'cat-name' }, [
      importanceDot(event.importance),
      el('span', { class: 'cat-title', text: event.title }),
      event.reference_period ? el('span', { class: 'dim', text: ` · ${event.reference_period}` }) : null,
      certaintyTag(event, labels),
    ]),
    el('span', { class: 'cat-figures' }, figures),
  ]);
  return el('details', { class: 'cat-item' }, [summary, macroDetail(event, labels)]);
}

function earningsRow(event) {
  const weight = eventWeight(event);
  return el('div', { class: 'cat-row cat-row-flat', title: [event.name, event.sector, event.fiscal_quarter ? `FQ ${event.fiscal_quarter}` : null, event.estimates ? `${event.estimates} estimates` : null].filter(Boolean).join(' · ') }, [
    timeCell(event),
    el('span', { class: 'cat-name' }, [
      importanceDot(event.importance),
      el('a', { class: 'cat-title', href: tickerHref(event.symbol), text: event.symbol }),
      el('span', { class: 'dim cat-company', text: ` ${event.name || ''}` }),
      event.watchlist ? el('span', { class: 'cat-tag', text: 'WATCHLIST' }) : null,
    ]),
    el('span', { class: 'cat-figures' }, [
      weight ? el('span', { class: 'dim', text: `${num(weight, 2)}%` }) : null,
      el('span', {}, [el('span', { class: 'dim', text: 'EST ' }), event.eps_forecast === null ? DASH : `$${num(event.eps_forecast, 2)}`]),
      event.last_year_eps === null ? null : el('span', { class: 'dim', text: `YR AGO $${num(event.last_year_eps, 2)}` }),
    ]),
  ]);
}

// --- Sections -------------------------------------------------------------------

// Three weeks as columns: how much of the S&P 500 reports each day, and which
// releases land on it.
function sessionStrip(data, onPick) {
  const weekStatus = new Map(data.week.map((day) => [day.date, day]));
  const days = weekdaysAfter(data.as_of, STRIP_SESSIONS);
  const perDay = days.map((day) => {
    const names = data.events.filter((e) => e.date === day && e.lane === 'single_name');
    const macro = data.events.filter((e) => e.date === day && e.lane === 'macro' && e.importance !== 'low')
      .sort((a, b) => IMPORTANCE_RANK[a.importance] - IMPORTANCE_RANK[b.importance] || String(a.time).localeCompare(String(b.time)));
    return {
      day,
      status: weekStatus.get(day),
      weight: names.reduce((sum, e) => sum + eventWeight(e), 0),
      reports: names.length,
      leaders: [...names].sort((a, b) => eventWeight(b) - eventWeight(a)).slice(0, 2).map((e) => e.symbol),
      macro,
    };
  });
  const top = Math.max(1, ...perDay.map((d) => d.weight));
  const columns = perDay.map((d) => {
    const closed = d.status?.status === 'holiday';
    const chips = d.macro.slice(0, 3).map((e) => el('span', {
      class: `cat-chip cat-chip-${e.importance}`,
      title: `${e.time ? `${e.time} ET · ` : ''}${e.title}${e.reference_period ? ` · ${e.reference_period}` : ''}`,
      text: shortTitle(e),
    }));
    if (d.macro.length > 3) chips.push(el('span', { class: 'cat-chip-more', text: `+${d.macro.length - 3}` }));
    return el('button', {
      type: 'button',
      class: `cat-col ${closed ? 'is-closed' : ''} ${d.day > data.week_sessions[data.week_sessions.length - 1] ? 'is-later' : ''}`,
      title: d.reports ? `${d.reports} reports · ${num(d.weight, 1)}% of S&P 500 weight${d.leaders.length ? ` · largest ${d.leaders.join(', ')}` : ''}` : 'no index member reports',
      onclick: () => onPick(d.day),
    }, [
      el('span', { class: 'cat-col-day', text: stripLabel(d.day), title: dayLabel(d.day) }),
      el('span', { class: 'cat-col-weight', text: d.weight ? `${num(d.weight, d.weight >= 10 ? 0 : 1)}%` : '' }),
      el('span', { class: 'cat-col-bar' }, [
        el('span', { class: 'cat-col-fill', style: `height:${Math.max(d.weight ? 3 : 0, (d.weight / top) * 100)}%` }),
      ]),
      el('span', { class: 'cat-col-names', text: closed ? 'CLOSED' : d.leaders.join(' ') || DASH }),
      el('span', { class: 'cat-col-chips' }, chips),
    ]);
  });
  return card('NEXT THREE WEEKS', el('span', { class: 'dim', text: 'bar = share of S&P 500 weight reporting · chips = macro, red = high' }), [
    el('div', { class: 'cat-strip', style: `grid-template-columns:repeat(${days.length}, minmax(72px, 1fr))` }, columns),
  ]);
}

function keyReleaseCard(event) {
  const { expectation, previous } = headline(event);
  const market = (event.expectations || []).find((r) => r.kind === 'market' && r.low != null && r.high != null);
  const others = (event.expectations || []).length - (expectation ? 1 : 0);
  const local = localTime(event);
  return el('div', { class: 'cat-key' }, [
    el('div', { class: 'cat-key-when', text: `${dayLabel(event.date)} · ${event.time ? `${event.time} ET${local ? ` (${local})` : ''}` : 'TIME TBA'}` }),
    el('div', { class: 'cat-key-title', text: shortTitle(event) }),
    el('div', { class: 'cat-key-period dim', text: event.reference_period || event.title }),
    el('div', { class: 'cat-key-figures' }, [
      el('div', {}, [
        el('div', { class: 'stat-label', text: 'FORECAST', title: expectation ? expectation.source_label : '' }),
        el('div', { class: 'cat-key-value', text: expectation ? expectationValue(expectation) : DASH }),
        el('div', { class: 'stat-note', text: expectation ? `${expectation.label} · ${expectation.source_label}` : 'none published yet' }),
      ]),
      el('div', {}, [
        el('div', { class: 'stat-label', text: 'PREVIOUS' }),
        el('div', { class: 'cat-key-value dim', text: previous ? printValue(previous) : DASH }),
        el('div', { class: 'stat-note', text: previous ? `${previous.label}${previous.period ? ` · ${periodOf(previous)}` : ''}` : 'no print on this measure' }),
      ]),
    ]),
    market ? rangeBar(market) : null,
    others > 0 ? el('div', { class: 'stat-note', title: (event.expectations || []).map(formatExpectation).join('\n'), text: `+${others} more forecast${others === 1 ? '' : 's'} · hover` }) : null,
  ]);
}

function keyReleases(data) {
  const upcoming = data.events
    .filter((e) => e.lane === 'macro' && e.importance === 'high' && e.date > data.as_of)
    .sort((a, b) => a.date.localeCompare(b.date) || String(a.time).localeCompare(String(b.time)))
    .slice(0, KEY_RELEASES);
  if (!upcoming.length) return null;
  return card('KEY RELEASES', el('span', { class: 'dim', text: 'high importance · forecast vs previous' }), [
    el('div', { class: 'cat-keys' }, upcoming.map(keyReleaseCard)),
  ]);
}

function lastSession(recent, labels) {
  const m = recent.market || {};
  const ten = m.ten_year;
  const right = el('span', { class: 'dim' }, [
    'S&P 500 ', el('span', { class: dirClass(m.spx_1d), text: pct(m.spx_1d) }),
    ' · 10Y ', ten ? `${num(ten.level, 2)}% ` : DASH,
    ten ? el('span', { class: dirClass(ten.change_bp), text: `${ten.change_bp >= 0 ? '+' : ''}${num(ten.change_bp, 1)} bp` }) : null,
  ]);
  const macro = recent.macro.map((event) => {
    const previous = knownPrints(event)[0] || null;
    return el('div', { class: 'cat-row cat-row-flat' }, [
      timeCell(event),
      el('span', { class: 'cat-name' }, [importanceDot(event.importance), el('span', { class: 'cat-title', text: event.title })]),
      el('span', { class: 'cat-figures' }, event.actuals?.length ? actualSpans(event)
        : previous ? [el('span', { text: printValue(previous) }), previous.period ? el('span', { class: 'dim', text: periodOf(previous) }) : null] : []),
    ]);
  });
  const reportRow = (e, reacted) => el('tr', {}, [
    el('td', { text: e.symbol }),
    el('td', { class: e.result_pending ? 'dim' : '', text: e.result_pending ? 'not posted' : e.eps === null ? DASH : `$${num(e.eps, 2)}` }),
    el('td', { class: 'dim', text: e.eps_forecast === null ? DASH : `$${num(e.eps_forecast, 2)}` }),
    el('td', { class: dirClass(e.surprise_pct), text: e.surprise_pct === null ? DASH : pct(e.surprise_pct, 1) }),
    el('td', { class: reacted ? dirClass(e.return_1d) : 'dim', text: reacted ? pct(e.return_1d) : 'next session' }),
  ]);
  const reports = [...recent.earnings_reacted.map((e) => reportRow(e, true)), ...recent.earnings_after_close.map((e) => reportRow(e, false))];
  return card(`LAST SESSION · ${dayLabel(recent.session)}`, right, [
    el('div', { class: 'grid two' }, [
      el('div', {}, [el('div', { class: 'cat-lane', text: 'MACRO' }), ...(macro.length ? macro : [el('div', { class: 'dim', text: 'No scheduled release.' })])]),
      el('div', {}, [
        el('div', { class: 'cat-lane', text: 'EARNINGS' }),
        reports.length ? table(['TICKER', 'EPS', 'EST', 'SURPRISE', '1D'], reports) : el('div', { class: 'dim', text: 'No index member or watchlist name reported.' }),
      ]),
    ]),
  ]);
}

function loadFilter() {
  try {
    return { importance: 'medium', lane: 'both', watchlist: false, ...JSON.parse(localStorage.getItem(FILTER_KEY) || '{}') };
  } catch {
    return { importance: 'medium', lane: 'both', watchlist: false };
  }
}

function saveFilter(filter) {
  try { localStorage.setItem(FILTER_KEY, JSON.stringify(filter)); } catch { /* private window */ }
}

function switchGroup(options, active, onPick) {
  const wrap = el('div', { class: 'period-switch' });
  options.forEach(([value, label]) => wrap.append(el('button', {
    type: 'button', text: label, 'aria-pressed': String(value === active),
    onclick: () => {
      [...wrap.children].forEach((b) => b.setAttribute('aria-pressed', String(b.textContent === label)));
      onPick(value);
    },
  })));
  return wrap;
}

function visible(event, filter) {
  if (IMPORTANCE_RANK[event.importance] > IMPORTANCE_RANK[filter.importance]) return false;
  if (filter.lane !== 'both' && event.lane !== filter.lane) return false;
  if (filter.watchlist && event.lane === 'single_name' && !event.watchlist) return false;
  if (filter.query) {
    const q = filter.query.toUpperCase();
    const text = `${event.symbol || ''} ${event.title} ${event.name || ''}`.toUpperCase();
    if (!text.includes(q)) return false;
  }
  return true;
}

function laneColumn(title, events, weekEnd, render) {
  const column = el('div', {}, [el('div', { class: 'cat-lane', text: title })]);
  if (!events.length) {
    column.append(el('div', { class: 'dim', text: 'Nothing matches the filter.' }));
    return column;
  }
  let dividerShown = false;
  const days = [...new Set(events.map((e) => e.date))];
  days.forEach((day) => {
    if (!dividerShown && day > weekEnd) {
      column.append(el('div', { class: 'cat-divider', text: 'BEYOND THE NEXT FIVE SESSIONS' }));
      dividerShown = true;
    }
    column.append(el('div', { class: 'cat-day', id: `cat-${title.startsWith('MACRO') ? 'm' : 's'}-${day}`, text: dayLabel(day) }));
    events.filter((e) => e.date === day).forEach((e) => column.append(render(e)));
  });
  return column;
}

function methodNotes(data) {
  const failed = Object.entries(data.failed_sources || {});
  const expected = data.expected_missing || [];
  return [
    data.note,
    `Times are New York${viewerZone !== NEW_YORK ? `, with your local time (${localZoneName(data.as_of)}) beside them` : ''}. BMO / AMC: the company reports before the open / after the close.`,
    'F = the headline forecast (a survey where one exists, else a prediction market, else a nowcast); P = the previous print on the same measure. Open a release for every source, its range and open interest, and the source link.',
    'KEY RELEASES shows the next six high-importance releases. The Kalshi bar spans the market\'s 10th–90th percentile with the dot at its median.',
    'LAST SESSION: reported before that session\'s open, or after the previous close, is a reaction in that session; an after-close report trades the next one. Actuals are TradingView\'s print against its forecast; the agency release is authoritative.',
    `Date sources: ${Object.entries(data.certainty_labels || {}).map(([k, v]) => `${k.replace('_', ' ')} = ${v}`).join('; ')}.`,
    failed.length ? `Not fetched this build: ${failed.map(([s, why]) => `${s} (${why})`).join('; ')}.` : null,
    expected.length ? `Not found in its agency's calendar, so likely renamed and missing: ${expected.join('; ')}.` : null,
  ];
}

// Reports heavy enough to move an index (or on the watchlist): the next
// week's cards, and the ones the last session traded on.
async function eventLead(events) {
  if (!events || (!events.upcoming?.length && !events.reported?.length)) return null;
  const t = events.thresholds || {};
  const nodes = [];
  if (events.reported?.length) {
    nodes.push(el('div', { class: 'section-sub', text: `JUST REPORTED · TRADED ${events.as_of}` }));
    nodes.push(el('div', { class: 'event-lead' }, events.reported.map((p) => outcomeCard(p, { compact: true }))));
  }
  if (events.upcoming?.length) {
    const prices = await Promise.all(events.upcoming.map((p) => loadPrices(p.symbol)));
    nodes.push(el('div', { class: 'section-sub', text: `REPORTING IN THE NEXT ${events.lead_days} DAYS · SPX ≥ ${t.SPX}% OR NDX ≥ ${t.NDX}% OR WATCHLIST` }));
    nodes.push(el('div', { class: 'event-lead' }, events.upcoming.map((p, i) => eventCard(p, events.as_of, { compact: true, prices: prices[i] }))));
  }
  return el('div', {}, nodes);
}

export default async function renderCatalysts(root, data, _manifest, ctx = {}) {
  root.append(sectionTitle('CATALYSTS', 'WHAT IS SCHEDULED NEXT'));
  if (!data.events) {
    root.append(gap('No catalyst calendar in this build.'));
    return;
  }
  const failed = Object.keys(data.failed_sources || {});
  const horizon = data.high_importance_horizon_end && data.high_importance_horizon_end > data.horizon_end
    ? `THROUGH ${data.horizon_end} · HIGH-IMPORTANCE MACRO THROUGH ${data.high_importance_horizon_end}`
    : `THROUGH ${data.horizon_end}`;
  root.append(metaRow(
    [`AS OF ${data.as_of}`, horizon, 'TIMES ET', failed.length ? `${failed.length} SOURCE${failed.length === 1 ? '' : 'S'} NOT FETCHED: ${failed.join(', ').toUpperCase()}` : null].filter(Boolean).join(' · '),
    methodNotes(data),
  ));
  if ((data.expected_missing || []).length) {
    root.append(gap(`Likely renamed at its agency, so missing below: ${data.expected_missing.join('; ')}`));
  }

  const filter = loadFilter();
  const host = el('div', {});
  const weekEnd = data.week_sessions[data.week_sessions.length - 1];
  const jump = (day) => {
    const target = document.getElementById(`cat-m-${day}`) || document.getElementById(`cat-s-${day}`);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const draw = () => {
    host.innerHTML = '';
    const shown = data.events.filter((e) => visible(e, filter));
    const macro = shown.filter((e) => e.lane === 'macro');
    const names = shown.filter((e) => e.lane === 'single_name').sort((a, b) => a.date.localeCompare(b.date)
      || TIMING_RANK[a.timing] - TIMING_RANK[b.timing]
      || eventWeight(b) - eventWeight(a)
      || a.symbol.localeCompare(b.symbol));
    const columns = [];
    if (filter.lane !== 'single_name') columns.push(laneColumn('MACRO & BROAD INDEX', macro, weekEnd, (e) => macroRow(e, data.certainty_labels)));
    if (filter.lane !== 'macro') columns.push(laneColumn('SINGLE NAME · EARNINGS', names, weekEnd, earningsRow));
    host.append(el('div', { class: columns.length > 1 ? 'grid two' : '' }, columns.map((c) => el('div', { class: 'card' }, [c]))));
  };
  const set = (key) => (value) => { filter[key] = value; saveFilter({ ...filter, query: undefined }); draw(); };

  const search = el('input', { size: '10', placeholder: 'ticker / text' });
  search.addEventListener('input', () => { filter.query = search.value.trim(); draw(); });

  root.append(sessionStrip(data, jump));
  const events = await ctx.loadArtifact?.('events').catch(() => null);
  const lead = events && events.as_of === data.as_of ? await eventLead(events) : null;
  if (lead) root.append(lead);
  const keys = keyReleases(data);
  if (keys) root.append(keys);
  root.append(lastSession(data.recent, data.certainty_labels));
  root.append(el('div', { class: 'field-row cat-filter' }, [
    el('span', { class: 'cat-lane', text: 'ALL EVENTS' }),
    switchGroup([['high', 'HIGH'], ['medium', 'MEDIUM+'], ['low', 'ALL']], filter.importance, set('importance')),
    switchGroup([['both', 'BOTH LANES'], ['macro', 'MACRO'], ['single_name', 'SINGLE NAME']], filter.lane, set('lane')),
    switchGroup([[false, 'ALL NAMES'], [true, 'WATCHLIST']], filter.watchlist, set('watchlist')),
    el('div', { class: 'field' }, [search]),
  ]));
  root.append(host);
  draw();
}
