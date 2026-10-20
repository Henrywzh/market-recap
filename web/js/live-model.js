// The live strip's rules, kept apart from the DOM so they can be tested under
// node: how old a price is, when it counts as stale, and when to ask again.

export function ageSeconds(timeSeconds, nowMs) {
  if (typeof timeSeconds !== 'number') return null;
  return Math.max(0, Math.round(nowMs / 1000 - timeSeconds));
}

export function ageText(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 172800) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

// Only a session that is open can make a price stale: after the close the
// last trade is the right answer however old it is.
export function isStale(quote, body, nowMs) {
  if (!body?.session?.open) return false;
  const age = ageSeconds(quote.time, nowMs);
  return age !== null && age > (body.stale_after_seconds ?? 1200);
}

// Seconds until the next automatic fetch, or null for none. A hidden tab does
// not poll; it catches up when shown (see dueOnShow).
export function nextDelay(body, hidden) {
  if (hidden) return null;
  const open = body?.session?.open;
  if (open === false) return body.closed_refresh_seconds ?? 300;
  return body?.refresh_seconds ?? 60;
}

export function dueOnShow(lastFetchMs, body, nowMs) {
  if (!lastFetchMs) return true;
  const delay = nextDelay(body, false);
  return nowMs - lastFetchMs >= delay * 1000;
}

// Today's date in New York as 'YYYY-MM-DD': the calendar the quotes are read on.
const NY_PARTS = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' });
export function newYorkDate(nowMs) {
  const parts = Object.fromEntries(NY_PARTS.formatToParts(new Date(nowMs)).map((p) => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

// The strip's title day: 'MON OCT 12', in New York.
const NY_DAY = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric' });
export function newYorkDayLabel(nowMs) {
  return NY_DAY.format(new Date(nowMs)).replace(/,/g, '').toUpperCase();
}

// US bond-market-only holidays (stocks trade, SIFMA recommends a full close):
// Treasury yields do not move on them. Columbus Day is the second Monday of
// October; Veterans Day is November 11, observed on Monday the 12th when the
// 11th is a Sunday, and not observed on a Friday or Monday when it is a Saturday.
export function bondHoliday(isoDate) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate ?? '');
  if (!match) return false;
  const month = Number(match[2]);
  const day = Number(match[3]);
  const weekday = new Date(Date.UTC(Number(match[1]), month - 1, day)).getUTCDay();   // 0 Sunday .. 6 Saturday
  if (month === 10) return weekday === 1 && day >= 8 && day <= 14;
  if (month === 11) return (day === 11 && weekday >= 1 && weekday <= 5) || (day === 12 && weekday === 1);
  return false;
}

// Which part of the US trading day it is in New York, by the clock: 'pre'
// (04:00-09:30), 'regular' (09:30-16:00), 'post' (16:00-20:00) or 'closed'
// (overnight and weekends). Holidays are not known here; a quiet holiday shows
// no extended trades, so its tiles stay grey rather than wrong.
const NY_CLOCK = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
function newYorkClock(nowMs) {
  const parts = Object.fromEntries(NY_CLOCK.formatToParts(new Date(nowMs)).map((p) => [p.type, p.value]));
  return { weekday: parts.weekday, minutes: (Number(parts.hour) % 24) * 60 + Number(parts.minute) };
}

export function marketPhase(nowMs) {
  const { weekday, minutes } = newYorkClock(nowMs);
  if (weekday === 'Sat' || weekday === 'Sun') return 'closed';
  if (minutes >= 240 && minutes < 570) return 'pre';
  if (minutes >= 570 && minutes < 960) return 'regular';
  if (minutes >= 960 && minutes < 1200) return 'post';
  return 'closed';
}

// Seconds from now to the next 04:00 New York on a weekday, by stepping in
// minutes from the next whole minute (at most three days and a bit).
export function secondsToPreMarket(nowMs) {
  let t = Math.floor(nowMs / 60000) * 60000 + 60000;
  for (let i = 0; i < 5 * 24 * 60; i += 1, t += 60000) {
    const { weekday, minutes } = newYorkClock(t);
    if (minutes === 240 && weekday !== 'Sat' && weekday !== 'Sun') return Math.round((t - nowMs) / 1000);
  }
  return null;
}

// The heat map's schedule. The regular session keeps the board's own cadence;
// pre-market and after hours ask every extended_refresh_seconds; overnight
// and at weekends nothing is asked until 04:00 New York (REFRESH still works).
export function boardDelay(body, hidden, nowMs) {
  if (hidden) return null;
  const phase = marketPhase(nowMs);
  if (phase === 'regular') return nextDelay(body, false);
  if (phase === 'pre' || phase === 'post') return body?.extended_refresh_seconds ?? body?.closed_refresh_seconds ?? 900;
  return secondsToPreMarket(nowMs);
}

// A name's move outside the regular session: its latest extended-hours price
// against its last regular-session price. Null when there is no extended
// price, or it equals the regular price (no extended trade to show).
export function extendedMove(quote) {
  const ext = quote?.extended_price;
  const base = quote?.price;
  if (!Number.isFinite(ext) || !Number.isFinite(base) || base <= 0 || ext === base) return null;
  return (ext / base - 1) * 100;
}
