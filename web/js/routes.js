// Navigation: which view a hash names, and how the views are grouped.
//
// Views are grouped by the question they answer (docs/information_architecture.md),
// not by the kind of data behind them. Every view keeps a stable hash; a view
// that takes an argument reads it after a slash (#ticker/AAPL). Hashes of views
// that were merged into another keep working through ALIASES, so a bookmark or
// a link in a note never lands on an empty page.

export const VIEWS = [
  // TODAY replaced OVERVIEW as the landing page; the id stays, so old links and DEFAULT_VIEW keep working.
  { id: 'overview', label: 'TODAY', group: 'market', artifact: 'today', module: 'today' },
  { id: 'markets', label: 'INDICES', group: 'market', artifact: 'markets', module: 'markets' },
  { id: 'heatmaps', label: 'HEAT MAPS', group: 'market', artifact: 'heatmaps', module: 'heatmaps' },
  { id: 'europe', label: 'EUROPE', group: 'market', artifact: 'europe', module: 'europe' },
  // One hub for every sector, sub-industry and its names; the cross-sector themes beside it.
  { id: 'sectors', label: 'SECTORS', group: 'sectors', artifact: 'sectors', module: 'sectors', takesArg: true },
  { id: 'themes', label: 'THEMES', group: 'sectors', artifact: 'themes', module: 'themes', takesArg: true },
  // One menu entry, two pages: a switch at the top of each moves between them. SIZE & STYLE is
  // reached from that switch, so it is hidden from the menu and highlights its parent (`menu`).
  { id: 'kshape', label: 'RELATIVE VALUE', group: 'sectors', artifact: 'kshape', module: 'kshape', takesArg: true },
  { id: 'sizek', label: 'SIZE & STYLE', group: 'sectors', artifact: 'sizek', module: 'sizek', takesArg: true, hidden: true, menu: 'kshape' },
  { id: 'chain', label: 'AI CHAIN', group: 'sectors', artifact: 'chain', module: 'chain', takesArg: true },
  { id: 'risk', label: 'RISK', group: 'risk', artifact: 'risk', module: 'risk' },
  { id: 'rates', label: 'RATES & MACRO', group: 'risk', artifact: ['fixed_income', 'macro'], module: 'rates' },
  { id: 'priced', label: 'PRICED PATH', group: 'risk', artifact: 'priced', module: 'priced' },
  { id: 'positioning', label: 'POSITIONING', group: 'risk', artifact: 'positioning', module: 'positioning' },
  { id: 'monitor', label: 'MONITOR', group: 'names', artifact: 'monitor', module: 'monitor' },
  { id: 'ticker', label: 'TICKER', group: 'names', artifact: 'valuation', module: 'ticker', takesArg: true },
  // Every company's multiples in one table. A company's P/E in detail is on its TICKER page;
  // an old #valuation/MSFT link still opens the table with that name in the search box.
  { id: 'valuation', label: 'SCREENER', group: 'names', artifact: 'valuation', module: 'valuation', takesArg: true },
  { id: 'europe-names', label: 'EUROPE NAMES', group: 'names', artifact: 'europe', module: 'europe-names', takesArg: true },
  { id: 'cross-listing', label: 'CROSS-LISTING', group: 'names', artifact: 'cross_listing', module: 'cross-listing' },
  { id: 'catalysts', label: 'CALENDAR', group: 'calendar', artifact: 'catalysts', module: 'catalysts' },
  { id: 'earnings', label: 'EARNINGS', group: 'calendar', artifact: 'earnings', module: 'earnings' },
  { id: 'scenarios', label: 'SCENARIOS', group: 'calendar', artifact: 'scenarios', module: 'scenarios', takesArg: true },
  { id: 'technicals', label: 'TECHNICALS', group: 'tools', artifact: 'technicals', module: 'technicals', takesArg: true },
  { id: 'trade', label: 'TRADE DESK', group: 'tools', artifact: 'technicals', module: 'trade', takesArg: true },
  { id: 'xray', label: 'ETF X-RAY', group: 'tools', artifact: 'xray', module: 'xray' },
  { id: 'dcf', label: 'DCF', group: 'tools', artifact: 'dcf', module: 'dcf', takesArg: true },
];

// The market first, then its sectors and what they hold, how much risk it
// carries, single names, what is coming, and the tools.
export const GROUPS = [
  { id: 'market', label: 'MARKET' },
  { id: 'sectors', label: 'SECTORS' },
  { id: 'risk', label: 'RISK' },
  { id: 'names', label: 'NAMES' },
  { id: 'calendar', label: 'CALENDAR' },
  { id: 'tools', label: 'TOOLS' },
];

// Hashes from before a regrouping, and where each now lives.
export const ALIASES = {
  'fixed-income': 'rates',
  macro: 'rates',
  financials: 'ticker',
  // The rotation graph and the sector scorecard open the SECTORS hub, which draws them.
  rotation: 'sectors',
  brief: 'overview',
  journal: 'overview',
};

export const DEFAULT_VIEW = 'overview';

// Underscores too: SIZE & STYLE pairs are keyed value_growth, ff_hml.
const TICKER_PATTERN = /^[A-Z0-9^][A-Z0-9._\-=]{0,14}$/;

const THEME_ARG_PATTERN = /^[A-Z][A-Z0-9_]{0,23}(\.[A-Z]+(\.[A-Z0-9-]{1,32})?)?$/;

export function cleanThemeArg(value) {
  const text = String(value || '').trim().toUpperCase();
  return THEME_ARG_PATTERN.test(text) ? text : null;
}

// The TICKER page carries its sub-tab after the symbol (NVDA/REPORT); the view
// name is plain letters, so BRK.B/FINANCIALS stays unambiguous.
const TICKER_VIEW_PATTERN = /^[A-Z]{3,12}$/;

export function cleanTickerArg(value) {
  const [symbol, view, ...extra] = String(value || '').trim().toUpperCase().split('/');
  const ticker = cleanTicker(symbol);
  if (!ticker || extra.length) return null;
  return view && TICKER_VIEW_PATTERN.test(view) ? `${ticker}/${view}` : ticker;
}

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
  // THEMES carries its sub-view in the argument (CLOUD.DATA.OPENROUTER), longer
  // than any ticker; it gets its own pattern so the deep link survives a reload.
  const clean = { themes: cleanThemeArg, ticker: cleanTickerArg }[id] || cleanTicker;
  const fromHash = clean(rest.join('/'));
  const fromQuery = cleanTicker(new URLSearchParams(search).get('ticker'));
  return { id, arg: fromHash || fromQuery || null };
}

// A slash inside the argument (the TICKER sub-tab, NVDA/REPORT) stays readable.
export function hashFor(id, arg = null) {
  return arg ? `${id}/${encodeURIComponent(arg).replace(/%2F/gi, '/')}` : id;
}

// The one link every ticker on the site uses (principle: one entity, one page).
export function tickerHref(symbol) {
  return `#${hashFor('ticker', symbol)}`;
}

export function viewById(id) {
  return VIEWS.find((v) => v.id === id) || null;
}

export function viewsIn(group) {
  return VIEWS.filter((v) => v.group === group && !v.hidden);
}
