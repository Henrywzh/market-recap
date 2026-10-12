// The live strip on MARKETS: intraday prices beside the recap, never in it.
//
// Every other figure on the page is the nightly build's close. This strip is
// one exception, so it says so on its face: each price carries its source
// and its age, the strip states whether the session is open, and a price that
// did not arrive is a dash. Its feed (live-feed.js) refreshes every
// `refresh_seconds` while the session is open and the tab is visible, and on
// demand from its button.
//
// The five a reader scans first sit in one row; the rest open from a toggle.

import { el, card, num, pct, dirClass, DASH } from './fmt.js';
import { ageSeconds, ageText, isStale, bondHoliday, newYorkDate, newYorkDayLabel } from './live-model.js';
import { createFeed } from './live-feed.js';

const ENDPOINT = 'api/quotes';
const MORE_KEY = 'mr-live-more';
export const PRIMARY = ['SPX', 'NDX', 'VIX', 'UST 10Y', 'DXY'];
let active = null;

function valueText(quote) {
  if (quote.price === null || quote.price === undefined) return DASH;
  return quote.kind === 'rate' ? `${num(quote.price, 3)}%` : num(quote.price);
}

function changeText(quote) {
  if (quote.kind === 'rate') {
    if (quote.change_bp === null || quote.change_bp === undefined) return DASH;
    return `${quote.change_bp > 0 ? '+' : ''}${num(quote.change_bp, 1)} bp`;
  }
  if (quote.change === null || quote.change === undefined) return DASH;
  return `${quote.change >= 0 ? '+' : ''}${num(quote.change)} (${pct(quote.change_pct)})`;
}

// The age note after a price: how old it is, STALE once an open session has
// left it behind, or on a bond-market holiday the reason no yield has moved.
function ageNote(time, now, stale, holiday) {
  if (holiday) return ' · bond market closed (holiday)';
  return ` · ${ageText(ageSeconds(time, now))}${stale ? ' STALE' : ''}`;
}

function quoteStat(quote, body, now) {
  if (quote.error) {
    return el('div', { class: 'stat live-stat' }, [
      el('div', { class: 'stat-label', text: quote.label }),
      el('div', { class: 'stat-value dim', text: DASH }),
      el('div', { class: 'stat-note', text: `${quote.source}: ${quote.error}` }),
    ]);
  }
  const stale = isStale(quote, body, now);
  // A Treasury yield that has not moved on a bond-market holiday is correct, not late.
  const holiday = stale && quote.kind === 'rate' && bondHoliday(newYorkDate(now));
  const flagged = stale && !holiday;
  const direction = quote.kind === 'rate' ? quote.change_bp : quote.change_pct;
  return el('div', { class: `stat live-stat${flagged ? ' live-stale' : ''}` }, [
    el('div', { class: 'stat-label', text: quote.label }),
    el('div', { class: 'stat-value', text: valueText(quote) }),
    el('div', { class: 'stat-note' }, [
      el('span', { class: dirClass(direction), text: changeText(quote) }),
      el('span', {
        class: 'live-age',
        'data-time': quote.time ?? '',
        'data-holiday': holiday ? '1' : null,
        text: ageNote(quote.time, now, flagged, holiday),
      }),
    ]),
  ]);
}

// The strip's order: cash indices, volatility, the yields, the dollar and
// commodities; the names to watch on a row of their own.
export function stripRows(quotes) {
  const rank = (q) => {
    if (q.kind === 'index') return 0;
    if (q.kind === 'macro' && q.label === 'VIX') return 1;
    if (q.kind === 'rate') return 2;
    if (q.kind === 'macro') return 3;
    return null;
  };
  const first = quotes.map((q, i) => [rank(q), i, q]).filter(([r]) => r !== null)
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(([, , q]) => q);
  return [first, quotes.filter((q) => q.kind === 'watch')];
}

// The primary quotes in PRIMARY's order; every other quote in stripRows' order.
export function splitPrimary(quotes) {
  const primary = PRIMARY.map((label) => quotes.find((q) => q.label === label)).filter(Boolean);
  const picked = new Set(primary);
  const [top, names] = stripRows(quotes);
  return [primary, [...top, ...names].filter((q) => !picked.has(q))];
}

// The toggle's choice is the reader's own, kept per browser; a private window
// simply forgets it.
function readMore() {
  try { return localStorage.getItem(MORE_KEY) === '1'; } catch { return false; }
}

function writeMore(open) {
  try { localStorage.setItem(MORE_KEY, open ? '1' : '0'); } catch { /* not kept; fine */ }
}

function createController({ asOf } = {}) {
  let more = readMore();
  let title = null;   // the card's title node, set once the card exists
  const primary = el('div', { class: 'stat-strip live-strip live-strip-primary' });
  const toggle = el('button', { type: 'button', class: 'live-refresh live-more-toggle', 'aria-expanded': String(more) });
  const toggleRow = el('div', { class: 'live-more-row' }, [toggle]);
  const rest = el('div', { class: 'stat-strip live-strip live-strip-more' });
  const foot = el('div', { class: 'note-text' });
  const holder = el('div', {});
  const feed = createFeed(ENDPOINT, {
    node: holder,
    onData: () => render(),
    onTick: (state) => {
      const now = Date.now();
      holder.querySelectorAll('.live-age').forEach((span) => {
        const time = span.dataset.time === '' ? null : Number(span.dataset.time);
        const holiday = span.dataset.holiday === '1';
        const stale = Boolean(span.closest('.live-stale'));
        span.textContent = ageNote(time, now, stale, holiday);
      });
      if (!state.body) render();
    },
  });
  toggleRow.hidden = true;
  rest.hidden = true;
  toggle.addEventListener('click', () => {
    more = !more;
    writeMore(more);
    render();
  });

  function render() {
    const body = feed.state.body;
    const now = Date.now();
    if (body) {
      const [top, others] = splitPrimary(body.quotes);
      primary.replaceChildren(...top.map((q) => quoteStat(q, body, now)));
      rest.replaceChildren(...others.map((q) => quoteStat(q, body, now)));
      toggle.textContent = more ? '− less' : `+ ${others.length} more`;
      toggleRow.hidden = others.length === 0;
    }
    toggle.setAttribute('aria-expanded', String(more));
    rest.hidden = !more;
    if (title) title.textContent = `LIVE · ${newYorkDayLabel(now)}`;
    const minutes = Math.round((body?.refresh_seconds ?? 60) / 60);
    foot.textContent = 'Live, intraday, unofficial (Yahoo; Treasury yields are Cboe\'s yield indexes through Yahoo), '
      + `every ${minutes === 1 ? 'minute' : `${minutes} minutes`} while the session is open. `
      + 'Change vs the previous close. '
      + (asOf ? `Everything below is the build's close of ${asOf}.` : 'Everything below is the build\'s close.');
  }

  const node = card(`LIVE · ${newYorkDayLabel(Date.now())}`, feed.controls, [primary, toggleRow, rest, foot]);
  title = node.querySelector('.card-title');
  holder.append(node);
  render();
  const controller = { node: holder, stop: () => { feed.stop(); if (active === controller) active = null; } };
  return controller;
}

export function mountLive({ asOf } = {}) {
  if (active) active.stop();
  active = createController({ asOf });
  return active.node;
}
