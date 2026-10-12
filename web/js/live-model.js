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
