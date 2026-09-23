// CATALYSTS: what the last session brought, and what is scheduled next.
//
// Two lanes, as the build assembles them: MACRO & BROAD INDEX (agency
// releases at the agency's time, the Fed's calendar, announced auctions, rule
// events, hand-kept events) and SINGLE NAME (index members' and watchlist
// earnings). Every row says how its date is known, because an agency's
// schedule and a vendor's earnings calendar are different claims.

import { el, card, table, num, pct, dirClass, sectionTitle, notice, gap, DASH } from '../fmt.js';

const NEW_YORK = 'America/New_York';
const IMPORTANCE_RANK = { high: 0, medium: 1, low: 2 };
const TIMING_LABEL = { bmo: 'BEFORE OPEN', amc: 'AFTER CLOSE' };
const TIMING_RANK = { bmo: 0, null: 1, amc: 2 };
const FILTER_KEY = 'mr-catalysts-filter';

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

function timeCell(event) {
  if (event.timing) return el('span', { class: 'cat-time', text: TIMING_LABEL[event.timing] });
  if (!event.time) return el('span', { class: 'cat-time dim', text: 'TIME TBA' });
  const children = [el('span', { text: `${event.time} ET` })];
  if (viewerZone !== NEW_YORK) {
    const local = newYorkInstant(event.date, event.time).toLocaleTimeString([], {
      hour: '2-digit', minute: '2-digit', hour12: false, timeZoneName: 'short',
    });
    children.push(el('span', { class: 'dim', text: ` · ${local}` }));
  }
  return el('span', { class: 'cat-time' }, children);
}

function dayLabel(day) {
  const d = new Date(`${day}T12:00:00Z`);
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }).toUpperCase();
}

// --- Pieces ---------------------------------------------------------------------

function importanceDot(importance) {
  return el('span', { class: `cat-dot cat-${importance}`, title: `${importance} importance` });
}

function formatPrint(p) {
  if (p.value === null || p.value === undefined) return `${p.label}: ${DASH}`;
  const period = p.period ? ` (${p.period.slice(0, 7)})` : '';
  return `${p.label} ${num(p.value, p.decimals)}${p.unit}${period}`;
}

function certaintyTag(event, labels) {
  if (event.certainty_class === 'official_schedule' || event.certainty_class === 'official_announcement') return null;
  return el('span', { class: 'cat-tag', title: labels[event.certainty_class] || '', text: event.certainty_class.replace('_', ' ').toUpperCase() });
}

function weightText(event) {
  const w = event.index_weights || {};
  const parts = Object.entries(w).map(([k, v]) => `${k} ${num(v, 2)}%`);
  return parts.length ? parts.join(' · ') : (event.watchlist ? 'watchlist' : '');
}

function macroRow(event, labels) {
  const prints = (event.prints || []).filter((p) => p.value !== null);
  return el('div', { class: 'cat-row' }, [
    timeCell(event),
    el('div', {}, [
      el('div', {}, [
        importanceDot(event.importance),
        el('span', { class: 'cat-title', text: event.title }),
        event.reference_period ? el('span', { class: 'dim', text: ` · ${event.reference_period}` }) : null,
        certaintyTag(event, labels),
        event.source_url ? el('a', { class: 'cat-src', href: event.source_url, target: '_blank', rel: 'noopener', text: event.source_id }) : null,
      ]),
      event.detail ? el('div', { class: 'cat-detail', text: event.detail }) : null,
      prints.length ? el('div', { class: 'cat-detail', text: `Previous: ${prints.map(formatPrint).join(' · ')}` }) : null,
    ]),
  ]);
}

function earningsRow(event) {
  const estimate = event.eps_forecast === null
    ? 'no consensus'
    : `EPS est $${num(event.eps_forecast, 2)}${event.estimates ? ` (${event.estimates})` : ''}`;
  const lastYear = event.last_year_eps === null ? '' : ` · yr ago $${num(event.last_year_eps, 2)}`;
  return el('div', { class: 'cat-row' }, [
    timeCell(event),
    el('div', {}, [
      el('div', {}, [
        importanceDot(event.importance),
        el('span', { class: 'cat-title', text: event.symbol }),
        el('span', { class: 'dim', text: ` ${event.name || ''}` }),
      ]),
      el('div', { class: 'cat-detail', text:
        [weightText(event), event.sector, `${estimate}${lastYear}`, event.fiscal_quarter ? `FQ ${event.fiscal_quarter}` : null]
          .filter(Boolean).join(' · ') }),
    ]),
  ]);
}

// --- Sections -------------------------------------------------------------------

function lastSession(recent, labels) {
  const m = recent.market || {};
  const ten = m.ten_year;
  const marketLine = el('div', { class: 'field-note' }, [
    `S&P 500 ${pct(m.spx_1d)} · 10Y ${ten ? `${num(ten.level, 2)}% (${ten.change_bp >= 0 ? '+' : ''}${num(ten.change_bp, 1)} bp)` : DASH}`,
    ' — the session\'s moves, not attributed to any one event.',
  ]);
  const macro = recent.macro.length
    ? recent.macro.map((e) => macroRow(e, labels))
    : [el('div', { class: 'field-note', text: 'No scheduled macro event in this session.' })];

  const reportRow = (e, reacted) => el('tr', {}, [
    el('td', { text: e.symbol }),
    el('td', { class: 'dim', text: e.timing ? TIMING_LABEL[e.timing].toLowerCase() : 'time n/a' }),
    el('td', { text: e.eps === null ? DASH : `$${num(e.eps, 2)}` }),
    el('td', { class: 'dim', text: e.eps_forecast === null ? DASH : `$${num(e.eps_forecast, 2)}` }),
    el('td', { class: dirClass(e.surprise_pct), text: e.surprise_pct === null ? DASH : pct(e.surprise_pct, 1) }),
    el('td', { class: reacted ? dirClass(e.return_1d) : 'dim', text: reacted ? pct(e.return_1d) : 'next session' }),
    el('td', { class: 'dim', text: weightText(e) }),
  ]);
  const headers = ['TICKER', 'TIMING', 'EPS', 'EST', 'SURPRISE', '1D', 'WEIGHT'];
  const reports = [...recent.earnings_reacted.map((e) => reportRow(e, true)), ...recent.earnings_after_close.map((e) => reportRow(e, false))];

  return card(`LAST SESSION · ${dayLabel(recent.session)}`, null, [
    marketLine,
    el('div', { class: 'grid two' }, [
      el('div', {}, [el('div', { class: 'cat-lane', text: 'MACRO & BROAD INDEX' }), ...macro]),
      el('div', {}, [
        el('div', { class: 'cat-lane', text: 'EARNINGS' }),
        reports.length ? table(headers, reports) : el('div', { class: 'field-note', text: 'No index member or watchlist name reported.' }),
        el('div', { class: 'field-note', text:
          `Reacted: reported before this session's open, or after the previous close (${dayLabel(recent.previous_session)}). `
          + 'After-close reports trade next session.' }),
      ]),
    ]),
  ]);
}

function weekStrip(data, onPick) {
  return el('div', { class: 'stat-strip cat-week' }, data.week.map((day) => {
    const top = data.events.filter((e) => e.date === day.date && e.importance === 'high').slice(0, 3);
    return el('div', { class: 'stat', style: 'cursor:pointer', onclick: () => onPick(day.date) }, [
      el('div', { class: 'stat-label', text: dayLabel(day.date) }),
      day.status === 'holiday'
        ? el('div', { class: 'stat-value dim', text: 'CLOSED' })
        : el('div', { class: 'stat-value', text: `${day.macro_high + day.earnings_high} high` }),
      el('div', { class: 'stat-note', text:
        day.status === 'holiday' ? day.note
          : `${day.macro} macro · ${day.earnings} earnings${day.status === 'early_close' ? ` · 1:00 pm close (${day.note})` : ''}` }),
      ...top.map((e) => el('div', { class: 'stat-note cat-high-line', text: e.lane === 'single_name' ? `${e.symbol} earnings` : e.title })),
    ]);
  }));
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
    column.append(el('div', { class: 'field-note', text: 'Nothing matches the filter.' }));
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

export default async function renderCatalysts(root, data) {
  root.append(sectionTitle('CATALYSTS', 'THINGS TO WATCH · TIMES IN NEW YORK AND YOURS'));
  if (!data.events) {
    root.append(gap('No catalyst calendar in this build.'));
    return;
  }
  const failed = Object.entries(data.failed_sources || {});
  if (failed.length) {
    root.append(notice(`Not fetched this build, so missing below: ${failed.map(([s, why]) => `${s} (${why})`).join('; ')}`));
  }

  root.append(lastSession(data.recent, data.certainty_labels));

  const filter = loadFilter();
  const host = el('div', {});
  const weekEnd = data.week_sessions[data.week_sessions.length - 1];

  const draw = () => {
    host.innerHTML = '';
    const shown = data.events.filter((e) => visible(e, filter));
    const macro = shown.filter((e) => e.lane === 'macro');
    const names = shown.filter((e) => e.lane === 'single_name').sort((a, b) => a.date.localeCompare(b.date)
      || TIMING_RANK[a.timing] - TIMING_RANK[b.timing]
      || IMPORTANCE_RANK[a.importance] - IMPORTANCE_RANK[b.importance]
      || a.symbol.localeCompare(b.symbol));
    const columns = [];
    if (filter.lane !== 'single_name') columns.push(laneColumn('MACRO & BROAD INDEX', macro, weekEnd, (e) => macroRow(e, data.certainty_labels)));
    if (filter.lane !== 'macro') columns.push(laneColumn('SINGLE NAME · EARNINGS', names, weekEnd, earningsRow));
    host.append(el('div', { class: columns.length > 1 ? 'grid two' : '' }, columns.map((c) => el('div', { class: 'card' }, [c]))));
  };
  const set = (key) => (value) => { filter[key] = value; saveFilter({ ...filter, query: undefined }); draw(); };

  const search = el('input', { size: '10', placeholder: 'ticker / text' });
  search.addEventListener('input', () => { filter.query = search.value.trim(); draw(); });

  root.append(weekStrip(data, (day) => {
    const target = document.getElementById(`cat-m-${day}`) || document.getElementById(`cat-s-${day}`);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
  root.append(card('FILTER', null, el('div', { class: 'field-row' }, [
    switchGroup([['high', 'HIGH'], ['medium', 'MEDIUM+'], ['low', 'ALL']], filter.importance, set('importance')),
    switchGroup([['both', 'BOTH LANES'], ['macro', 'MACRO'], ['single_name', 'SINGLE NAME']], filter.lane, set('lane')),
    switchGroup([[false, 'ALL NAMES'], [true, 'WATCHLIST']], filter.watchlist, set('watchlist')),
    el('div', { class: 'field' }, [el('label', { text: 'FIND' }), search]),
    el('span', { class: 'field-note', text: `Through ${data.horizon_end}` }),
  ])));
  root.append(host);
  root.append(notice(data.note));
  draw();
}
