// Navigation: which view a hash names, and how the views are grouped.
//
// Views are grouped by the question they answer (docs/information_architecture.md),
// not by the kind of data behind them. Every view keeps a stable hash; a view
// that takes an argument reads it after a slash (#ticker/AAPL). Hashes of views
// that were merged into another keep working through ALIASES, so a bookmark or
// a link in a note never lands on an empty page.

export const VIEWS = [
  { id: 'overview', label: 'OVERVIEW', group: 'market', artifact: 'overview', module: 'overview' },
  { id: 'markets', label: 'INDICES', group: 'market', artifact: 'markets', module: 'markets' },
  { id: 'heatmaps', label: 'HEAT MAPS', group: 'market', artifact: 'heatmaps', module: 'heatmaps' },
  { id: 'rotation', label: 'SECTORS', group: 'market', artifact: 'rotation', module: 'rotation' },
  { id: 'risk', label: 'RISK', group: 'risk', artifact: ['risk', 'anchor'], module: 'risk' },
  { id: 'rates', label: 'RATES & MACRO', group: 'risk', artifact: ['fixed_income', 'macro'], module: 'rates' },
  { id: 'priced', label: 'PRICED PATH', group: 'risk', artifact: 'priced', module: 'priced' },
  { id: 'positioning', label: 'POSITIONING', group: 'risk', artifact: 'positioning', module: 'positioning' },
  { id: 'monitor', label: 'MONITOR', group: 'names', artifact: 'monitor', module: 'monitor' },
  { id: 'valuation', label: 'SCREEN', group: 'names', artifact: 'valuation', module: 'valuation', takesArg: true },
  { id: 'ticker', label: 'TICKER', group: 'names', artifact: 'valuation', module: 'ticker', takesArg: true },
  { id: 'cross-listing', label: 'CROSS-LISTING', group: 'names', artifact: 'cross_listing', module: 'cross-listing' },
  { id: 'catalysts', label: 'CALENDAR', group: 'catalysts', artifact: 'catalysts', module: 'catalysts' },
  { id: 'earnings', label: 'EARNINGS', group: 'catalysts', artifact: 'earnings', module: 'earnings' },
  { id: 'themes', label: 'THEMES', group: 'catalysts', artifact: 'themes', module: 'themes', takesArg: true },
  { id: 'chain', label: 'AI CHAIN', group: 'catalysts', artifact: 'chain', module: 'chain', takesArg: true },
  { id: 'technicals', label: 'TECHNICALS', group: 'tools', artifact: 'technicals', module: 'technicals', takesArg: true },
  { id: 'trade', label: 'TRADE DESK', group: 'tools', artifact: 'technicals', module: 'trade', takesArg: true },
  { id: 'xray', label: 'ETF X-RAY', group: 'tools', artifact: 'xray', module: 'xray' },
  { id: 'dcf', label: 'DCF', group: 'tools', artifact: 'dcf', module: 'dcf', takesArg: true },
];

// The market first, then how much risk it carries, then names and dates.
export const GROUPS = [
  { id: 'market', label: 'MARKET' },
  { id: 'risk', label: 'RISK' },
  { id: 'names', label: 'NAMES' },
  { id: 'catalysts', label: 'CATALYSTS' },
  { id: 'tools', label: 'TOOLS' },
];

// Hashes from before the regrouping, and where each now lives.
export const ALIASES = {
  'fixed-income': 'rates',
  macro: 'rates',
  financials: 'ticker',
  sectors: 'rotation',
  brief: 'overview',
  journal: 'overview',
};

export const DEFAULT_VIEW = 'overview';

const TICKER_PATTERN = /^[A-Z0-9^][A-Z0-9.\-=]{0,14}$/;

export function cleanTicker(value) {
  const text = String(value || '').trim().toUpperCase();
  return TICKER_PATTERN.test(text) ? text : null;
}

// The build keys share classes the way Yahoo does (BRK-B, BF-B); readers
// type the exchange's BRK.B. A dotted symbol the build lacks resolves to its
// dashed form when the build has that -- never blindly, as VOD.L is London.
export function resolveTicker(symbol, has) {
  if (!symbol || has(symbol)) return symbol;
  const dashed = symbol.replace(/^([A-Z]{1,6})\.([A-Z])$/, '$1-$2');
  return dashed !== symbol && has(dashed) ? dashed : symbol;
}

// '#ticker/AAPL' -> { id: 'ticker', arg: 'AAPL' }. An unknown view falls back
// to the default; a view that takes no argument ignores one. When no argument
// is in the hash, `search` (the page's query string) may carry ?ticker=, which
// is how links written before the regrouping passed one.
export function parseHash(hash, search = '') {
  const raw = decodeURIComponent(String(hash || '').replace(/^#/, ''));
  const [head, ...rest] = raw.split('/');
  const id = ALIASES[head] || head;
  const view = VIEWS.find((v) => v.id === id);
  if (!view) return { id: DEFAULT_VIEW, arg: null };
  if (!view.takesArg) return { id, arg: null };
  const fromHash = cleanTicker(rest.join('/'));
  const fromQuery = cleanTicker(new URLSearchParams(search).get('ticker'));
  return { id, arg: fromHash || fromQuery || null };
}

export function hashFor(id, arg = null) {
  return arg ? `${id}/${encodeURIComponent(arg)}` : id;
}

// The one link every ticker on the site uses (principle: one entity, one page).
export function tickerHref(symbol) {
  return `#${hashFor('ticker', symbol)}`;
}

export function viewById(id) {
  return VIEWS.find((v) => v.id === id) || null;
}

export function viewsIn(group) {
  return VIEWS.filter((v) => v.group === group);
}
