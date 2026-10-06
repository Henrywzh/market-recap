// The live strip on MARKETS: intraday prices beside the recap, never in it.
//
// Every other figure on the page is the nightly build's close. This strip is
// one exception, so it says so on its face: each price carries its source
// and its age, the strip states whether the session is open, and a price that
// did not arrive is a dash. Its feed (live-feed.js) refreshes every
// `refresh_seconds` while the session is open and the tab is visible, and on
// demand from its button.

import { el, card, num, pct, dirClass, DASH } from './fmt.js';
import { ageSeconds, ageText, isStale } from './live-model.js';
import { createFeed } from './live-feed.js';

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

function createController() {
  const first = el('div', { class: 'stat-strip live-strip' });
  const second = el('div', { class: 'stat-strip live-strip live-strip-names' });
  const foot = el('div', { class: 'note-text' });
  const holder = el('div', {});
  const feed = createFeed(ENDPOINT, {
    node: holder,
    onData: () => render(),
    onTick: (state) => {
      const now = Date.now();
      holder.querySelectorAll('.live-age').forEach((span) => {
        const time = span.dataset.time === '' ? null : Number(span.dataset.time);
        const stale = span.closest('.live-stale');
        span.textContent = ` · ${ageText(ageSeconds(time, now))}${stale ? ' STALE' : ''}`;
      });
      if (!state.body) render();
    },
  });

  function render() {
    const body = feed.state.body;
    const now = Date.now();
    if (body) {
      const [top, names] = stripRows(body.quotes);
      first.replaceChildren(...top.map((q) => quoteStat(q, body, now)));
      second.replaceChildren(...names.map((q) => quoteStat(q, body, now)));
    }
    const minutes = Math.round((body?.refresh_seconds ?? 60) / 60);
    foot.textContent = 'Intraday and unofficial: Yahoo (indices, VIX, the dollar, futures, names) and CNBC (Treasury yields), '
      + `fetched through this site every ${minutes === 1 ? 'minute' : `${minutes} minutes`} while the session is open and this tab is visible. `
      + 'Change is against the previous close. Every other figure on this page is the build\'s close.';
  }

  holder.append(card('LIVE', feed.controls, [first, second, foot]));
  render();
  const controller = { node: holder, stop: () => { feed.stop(); if (active === controller) active = null; } };
  return controller;
}

export function mountLive() {
  if (active) active.stop();
  active = createController();
  return active.node;
}
