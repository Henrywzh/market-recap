// THEMES board: how the build's measurements read on the page. Pure, tested
// under node. The label and its numbers come from the build; these functions
// only choose a tone and phrase a cell.

import { num, DASH } from './fmt.js';

const finite = (v) => v !== null && v !== undefined && Number.isFinite(v);

// A state's tone: filled green only for strong price with rising estimates; a
// divergence (price and estimates apart) is amber or blue, never red-or-green
// by itself; red is weak price with falling estimates.
const TONES = {
  strong_rising: 'up',
  strong_steady: 'warn',
  strong_falling: 'warn',
  flat_rising: 'info',
  flat_steady: 'dim',
  flat_falling: 'warn',
  weak_rising: 'info',
  weak_steady: 'info',
  weak_falling: 'down',
};

export function stateTone(key) {
  return TONES[key] || 'dim';
}

// Why a theme has its label, in the numbers the rule used.
export function stateWhy(board) {
  const s = board?.state;
  const r = board?.revision;
  if (!s || !s.key) return 'no label: a price or an estimate reading is missing';
  const price = finite(s.relative_3m) ? `${s.relative_3m > 0 ? '+' : ''}${num(s.relative_3m, 1)} pp against the S&P 500 over 3 months (strong or weak beyond ±${num(s.relative_pp, 1)})` : DASH;
  const est = finite(r?.median_pct) ? `median ${r.period} EPS estimate ${r.median_pct > 0 ? '+' : ''}${num(r.median_pct, 2)}% over ${r.window} across ${r.of} names (rising or falling beyond ±${num(r.move_pct, 1)}%)` : DASH;
  return `${price}; ${est}`;
}

export function breadthText(b) {
  if (!b || !b.of) return null;
  return { main: `${b.above_ma}/${b.of}`, note: `above ${b.ma_sessions}d avg · ${b.up_month} up 1M`, share: b.above_ma / b.of };
}

// The estimate cell: the median change and how the names split.
export function revisionText(r) {
  if (!r || !r.of || !finite(r.median_pct)) return null;
  const steady = r.of - r.rising - r.falling;
  return { main: `${r.median_pct > 0 ? '+' : ''}${num(r.median_pct, 2)}%`, note: `${r.rising}↑ ${steady}= ${r.falling}↓ of ${r.of}`, rising: r.rising, steady, falling: r.falling, of: r.of };
}

export function valuationText(v) {
  if (!v || !finite(v.median_percentile)) return null;
  return { main: `${num(v.median_percentile, 0)}`, note: `own-history P/E pct · ${v.of} names`, share: v.median_percentile / 100 };
}

export function quadrantTone(q) {
  return q === 'leading' ? 'up' : q === 'lagging' ? 'down' : q ? 'warn' : 'dim';
}

// The share of each estimate class as percent widths of one bar.
export function splitWidths(r) {
  const t = revisionText(r);
  if (!t) return null;
  return { up: (t.rising / t.of) * 100, flat: (t.steady / t.of) * 100, down: (t.falling / t.of) * 100 };
}
