// One live feed: a URL on the quote function, fetched on the schedule its own
// answer sets (refresh_seconds while the session is open, closed_refresh_seconds
// after), paused while the tab is hidden, and asked again on REFRESH. The strip,
// the heat map and the index charts each hold one; nothing here draws prices.

import { el } from './fmt.js';
import { ageText, nextDelay, dueOnShow } from './live-model.js';

export function sessionText(body) {
  const open = body?.session?.open;
  if (open === true) return 'SESSION OPEN';
  if (open === false) return 'MARKET CLOSED · LAST PRICES';
  return 'SESSION UNKNOWN';
}

// The status line every live block shows: whether the session is open, how
// old the prices are, when they are next asked for, and any failure.
export function statusText(state, now = Date.now()) {
  const parts = [];
  if (state.error) parts.push(`LAST FETCH FAILED: ${state.error}`);
  if (state.body) {
    parts.push(sessionText(state.body));
    parts.push(`UPDATED ${ageText(Math.round((now - state.lastFetch) / 1000))} AGO`);
    if (state.nextAt) parts.push(`NEXT IN ${ageText(Math.max(0, Math.round((state.nextAt - now) / 1000)))}`);
  } else if (!state.error) {
    parts.push('LOADING…');
  }
  return parts.join(' · ');
}

export function withFresh(url) {
  return `${url}${url.includes('?') ? '&' : '?'}fresh=1`;
}

// `onData(body)` after each answer; `node` is the element the feed belongs to:
// once it leaves the page the feed stops, so a reader on another tab is not
// polling for this one.
export function createFeed(url, { node, onData, onTick }) {
  const state = { body: null, lastFetch: 0, nextAt: null, timer: null, ticker: null, inflight: false, error: null, stopped: false };
  const button = el('button', { type: 'button', class: 'live-refresh', text: 'REFRESH' });
  const status = el('span', { class: 'live-status', text: 'LOADING…' });

  function tick() {
    status.textContent = statusText(state);
    status.className = `live-status${state.error ? ' down' : ''}`;
    onTick?.(state);
  }

  function schedule(delaySeconds) {
    clearTimeout(state.timer);
    state.timer = null;
    state.nextAt = null;
    if (delaySeconds === null || state.stopped) return;
    state.nextAt = Date.now() + delaySeconds * 1000;
    state.timer = setTimeout(() => fetchNow(false), delaySeconds * 1000);
  }

  async function fetchNow(fresh) {
    if (state.inflight) return;
    state.inflight = true;
    button.disabled = true;
    button.textContent = 'REFRESHING…';
    try {
      const response = await fetch(fresh ? withFresh(url) : url, { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json();
      if (!Array.isArray(body.quotes)) throw new Error(body.error || 'malformed response');
      state.body = body;
      state.error = null;
    } catch (error) {
      // The previous prices stay up and their ages keep growing: the reader
      // sees how old they are rather than a blank that hides the failure.
      state.error = error.message;
    } finally {
      state.lastFetch = Date.now();
      state.inflight = false;
      button.disabled = false;
      button.textContent = 'REFRESH';
    }
    if (state.stopped || !node.isConnected) { stop(); return; }
    if (state.body && !state.error) onData(state.body);
    schedule(nextDelay(state.body, document.hidden));
    tick();
  }

  function onVisibility() {
    if (document.hidden) { schedule(null); tick(); return; }
    const now = Date.now();
    if (dueOnShow(state.lastFetch, state.body, now)) fetchNow(false);
    else schedule((state.lastFetch + nextDelay(state.body, false) * 1000 - now) / 1000);
  }

  function stop() {
    state.stopped = true;
    clearTimeout(state.timer);
    clearInterval(state.ticker);
    document.removeEventListener('visibilitychange', onVisibility);
  }

  button.addEventListener('click', () => { schedule(null); fetchNow(true); });
  document.addEventListener('visibilitychange', onVisibility);
  state.ticker = setInterval(() => {
    if (!node.isConnected && state.lastFetch) { stop(); return; }
    tick();
  }, 1000);
  // The node is attached by the caller after this returns: ask once it is.
  setTimeout(() => fetchNow(false), 0);
  return { state, stop, controls: el('div', { class: 'live-controls' }, [status, button]) };
}

// The status line of a block that asks only when the reader presses REFRESH:
// before then it says the page shows the build's close; after, how old the
// prices are. Nothing is scheduled, so there is no "next in".
export function manualStatusText(state, now = Date.now()) {
  if (state.inflight && !state.body) return 'FETCHING…';
  const parts = [];
  if (state.error) parts.push(`LAST FETCH FAILED: ${state.error}`);
  if (state.body) {
    const open = state.body.session?.open;
    if (open !== null && open !== undefined) parts.push(sessionText(state.body));
    parts.push(`LIVE AS OF ${ageText(Math.round((now - state.lastFetch) / 1000))} AGO · PRESS REFRESH TO UPDATE`);
  } else if (!state.error) {
    parts.push('BUILD CLOSE · PRESS REFRESH FOR LIVE PRICES');
  }
  return parts.join(' · ');
}

// One or more URLs on the quote function, asked together and only on a
// click: SECTORS, MACRO and the Treasury table. `onData(bodies)` gets the
// answers in the order of `urls`; the page keeps the build's close until then.
export function createManualFeed(urls, { onData }) {
  const state = { body: null, bodies: null, lastFetch: 0, inflight: false, error: null };
  const button = el('button', { type: 'button', class: 'live-refresh', text: 'REFRESH' });
  const status = el('span', { class: 'live-status', text: manualStatusText(state) });
  const controls = el('div', { class: 'live-controls' }, [status, button]);

  function tick() {
    status.textContent = manualStatusText(state);
    status.className = `live-status${state.error ? ' down' : ''}`;
  }

  // A click while a fetch is out waits for that fetch instead of starting another.
  let pending = null;
  function fetchNow() {
    if (!pending) pending = run().finally(() => { pending = null; });
    return pending;
  }

  async function run() {
    state.inflight = true;
    button.disabled = true;
    button.textContent = 'REFRESHING…';
    tick();
    try {
      const bodies = await Promise.all(urls.map(async (url) => {
        const response = await fetch(withFresh(url), { cache: 'no-store' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        if (!Array.isArray(body.quotes)) throw new Error(body.error || 'malformed response');
        return body;
      }));
      state.bodies = bodies;
      state.body = bodies[0];
      state.error = null;
      state.lastFetch = Date.now();
    } catch (error) {
      state.error = error.message;
    } finally {
      state.inflight = false;
      button.disabled = false;
      button.textContent = 'REFRESH';
    }
    if (state.bodies && !state.error) onData(state.bodies);
    tick();
  }

  button.addEventListener('click', fetchNow);
  // Only the age moves; once the block leaves the page the clock stops.
  let shown = false;
  const ticker = setInterval(() => {
    if (controls.isConnected) shown = true;
    else if (shown) { clearInterval(ticker); return; }
    if (state.body) tick();
  }, 5000);
  return { state, controls, refresh: fetchNow };
}
