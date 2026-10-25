// Ticker suggestions under a ticker box: as the reader types, the symbols that
// start with it (GOOG → GOOG, GOOGL; A → A, AAPL, ABBV …), then the names that
// contain it as a word (AMAZON → AMZN). Arrow keys move, Enter or a click picks,
// Escape closes. The list is the build's own symbols, so a pick always loads.

import { el } from './fmt.js';

export const SUGGESTION_LIMIT = 12;

// The suggestions for `query`: exact symbol first, then symbols starting with it,
// then names with a word starting with it. Within each, `rank` (the build's symbols
// by index weight) puts the larger companies first; unranked ones follow, shorter
// first, then A–Z. Pure.
export function matchTickers(query, tickers, names = {}, limit = SUGGESTION_LIMIT, rank = []) {
  const q = String(query || '').trim().toUpperCase();
  if (!q) return [];
  const order = new Map(rank.map((t, i) => [t, i]));
  const byRank = (a, b) => (order.get(a) ?? Infinity) - (order.get(b) ?? Infinity) || a.length - b.length || a.localeCompare(b);
  const bySymbol = tickers.filter((t) => t.startsWith(q))
    .sort((a, b) => (a === q ? -1 : b === q ? 1 : byRank(a, b)));
  const seen = new Set(bySymbol);
  const word = new RegExp(`(^|[^A-Z0-9])${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`);
  const byName = tickers.filter((t) => !seen.has(t) && word.test(String(names[t] || '').toUpperCase()))
    .sort(byRank);
  return [...bySymbol, ...byName].slice(0, limit).map((ticker) => ({ ticker, name: names[ticker] || '' }));
}

// Wraps `input` with the list and returns the wrapper to put in the page in its
// place. `onPick(ticker)` runs after the box takes the picked symbol.
export function withSuggestions(input, tickers, names, onPick = () => {}, rank = []) {
  const list = el('div', { class: 'ticker-suggest', role: 'listbox', hidden: '' });
  const wrap = el('span', { class: 'ticker-suggest-wrap' }, [input, list]);
  input.setAttribute('autocomplete', 'off');
  let items = [];
  let active = -1;

  const close = () => { list.hidden = true; active = -1; };
  const pick = (ticker) => {
    input.value = ticker;
    close();
    onPick(ticker);
  };
  const paint = () => {
    list.replaceChildren(...items.map((item, i) => el('div', {
      class: `ticker-suggest-item${i === active ? ' active' : ''}`, role: 'option',
      // mousedown, not click: the box's blur would close the list first.
      onmousedown: (event) => { event.preventDefault(); pick(item.ticker); },
    }, [el('b', { text: item.ticker }), item.name ? el('span', { text: item.name }) : null])));
    list.hidden = !items.length;
  };

  input.addEventListener('input', () => {
    items = matchTickers(input.value, tickers, names, SUGGESTION_LIMIT, rank);
    // A box that already holds a whole symbol has nothing to suggest but itself.
    if (items.length === 1 && items[0].ticker === input.value.trim().toUpperCase()) items = [];
    active = -1;
    paint();
  });
  input.addEventListener('keydown', (event) => {
    if (list.hidden) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      active = (active + step + items.length) % items.length;
      paint();
    } else if (event.key === 'Enter' && active >= 0) {
      // The pick, not the half-typed text: stop the box's own Enter handler loading that.
      event.preventDefault();
      event.stopImmediatePropagation();
      pick(items[active].ticker);
    } else if (event.key === 'Escape') {
      close();
    }
  });
  input.addEventListener('blur', close);
  return wrap;
}
