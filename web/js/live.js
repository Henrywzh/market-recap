// The live strip on MARKETS: intraday prices beside the recap, never in it.
//
// Every other figure on the page is the nightly build's close. This strip is
// the one exception, so it says so on its face: each price carries its source
// and its age, the strip states whether the session is open, and a price that
// did not arrive is a dash. It refreshes itself every `refresh_seconds` while
// the session is open and the tab is visible, and on demand from its button.

import { el, card, num, pct, dirClass, DASH } from './fmt.js';
import { ageSeconds, ageText, isStale, nextDelay, dueOnShow } from './live-model.js';

const ENDPOINT = 'api/quotes';
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

function quoteStat(quote, body, now) {
  if (quote.error) {
    return el('div', { class: 'stat live-stat' }, [
      el('div', { class: 'stat-label', text: quote.label }),
      el('div', { class: 'stat-value dim', text: DASH }),
      el('div', { class: 'stat-note', text: `${quote.source}: ${quote.error}` }),
    ]);
  }
  const stale = isStale(quote, body, now);
  const direction = quote.kind === 'rate' ? quote.change_bp : quote.change_pct;
  return el('div', { class: `stat live-stat${stale ? ' live-stale' : ''}` }, [
    el('div', { class: 'stat-label', text: quote.label }),
    el('div', { class: 'stat-value', text: valueText(quote) }),
    el('div', { class: 'stat-note' }, [
      el('span', { class: dirClass(direction), text: changeText(quote) }),
      el('span', {
        class: 'live-age',
        'data-time': quote.time ?? '',
        text: ` · ${ageText(ageSeconds(quote.time, now))}${stale ? ' STALE' : ''}`,
      }),
    ]),
  ]);
}

function sessionText(body) {
  const open = body?.session?.open;
  if (open === true) return 'SESSION OPEN';
  if (open === false) return 'MARKET CLOSED · LAST PRICES';
  return 'SESSION UNKNOWN';
}

function createController() {
  const status = el('span', { class: 'live-status', text: 'LOADING…' });
  const button = el('button', { type: 'button', class: 'live-refresh', text: 'REFRESH' });
  const strip = el('div', { class: 'stat-strip live-strip' });
  const foot = el('div', { class: 'note-text' });
  const node = card('LIVE — INTRADAY, UNOFFICIAL', el('div', { class: 'live-controls' }, [status, button]), [strip, foot]);

  const state = {
    body: null, lastFetch: 0, nextAt: null, timer: null, ticker: null, inflight: false, error: null, stopped: false,
  };

  function render() {
    const now = Date.now();
    if (state.body) {
      strip.replaceChildren(...state.body.quotes.filter((q) => ['etf', 'index', 'watchlist', 'rate'].includes(q.kind))
        .map((q) => quoteStat(q, state.body, now)));
    }
    const minutes = Math.round((state.body?.refresh_seconds ?? 60) / 60);
    foot.textContent = 'Yahoo (ETFs, indices, watchlist) and CNBC (Treasury yields), fetched through this site '
      + `every ${minutes === 1 ? 'minute' : `${minutes} minutes`} while the session is open and this tab is visible. `
      + 'Change is against the previous close. Not part of the recap: every other figure on this page is the build\'s close.';
    updateStatus();
  }

  function updateStatus() {
    const now = Date.now();
    const parts = [];
    if (state.error) parts.push(`LAST FETCH FAILED: ${state.error}`);
    if (state.body) {
      parts.push(sessionText(state.body));
      parts.push(`UPDATED ${ageText(Math.round((now - state.lastFetch) / 1000))} AGO`);
      if (state.nextAt) parts.push(`NEXT IN ${ageText(Math.max(0, Math.round((state.nextAt - now) / 1000)))}`);
    } else if (!state.error) {
      parts.push('LOADING…');
    }
    status.textContent = parts.join(' · ');
    status.className = `live-status${state.error ? ' down' : ''}`;
    strip.querySelectorAll('.live-age').forEach((span) => {
      const time = span.dataset.time === '' ? null : Number(span.dataset.time);
      const stale = span.closest('.live-stale');
      span.textContent = ` · ${ageText(ageSeconds(time, now))}${stale ? ' STALE' : ''}`;
    });
  }

  function schedule(delaySeconds) {
    clearTimeout(state.timer);
    state.timer = null;
    state.nextAt = null;
    if (delaySeconds === null || state.stopped) return;
    state.nextAt = Date.now() + delaySeconds * 1000;
    state.timer = setTimeout(fetchNow, delaySeconds * 1000);
  }

  async function fetchNow() {
    if (state.inflight) return;
    state.inflight = true;
    button.disabled = true;
    button.textContent = 'REFRESHING…';
    try {
      const response = await fetch(ENDPOINT, { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json();
      if (!Array.isArray(body.quotes)) throw new Error(body.error || 'malformed response');
      state.body = body;
      state.error = null;
    } catch (error) {
      // The previous prices stay up, and their ages keep growing: the reader
      // sees how old they are rather than a blank that hides the failure.
      state.error = error.message;
    } finally {
      state.lastFetch = Date.now();
      state.inflight = false;
      button.disabled = false;
      button.textContent = 'REFRESH';
    }
    if (state.stopped || !node.isConnected) { stop(); return; }
    render();
    schedule(nextDelay(state.body, document.hidden));
  }

  function onVisibility() {
    if (document.hidden) { schedule(null); updateStatus(); return; }
    const now = Date.now();
    if (dueOnShow(state.lastFetch, state.body, now)) fetchNow();
    else schedule((state.lastFetch + nextDelay(state.body, false) * 1000 - now) / 1000);
  }

  function stop() {
    state.stopped = true;
    clearTimeout(state.timer);
    clearInterval(state.ticker);
    document.removeEventListener('visibilitychange', onVisibility);
    if (active === controller) active = null;
  }

  const controller = { node, stop };
  button.addEventListener('click', () => { schedule(null); fetchNow(); });
  document.addEventListener('visibilitychange', onVisibility);
  // The ages tick between fetches; leaving the tab removes the node and ends
  // the strip, so a reader on another tab is not polling for MARKETS.
  state.ticker = setInterval(() => {
    if (!node.isConnected) { stop(); return; }
    updateStatus();
  }, 1000);
  render();
  fetchNow();
  return controller;
}

export function mountLive() {
  if (active) active.stop();
  active = createController();
  return active.node;
}
