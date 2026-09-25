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
