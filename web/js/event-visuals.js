// Drawings for the earnings event card: where the street sits in its range,
// how the estimate moved, how the stock answered the last reports. The
// geometry and the wording are pure functions (tested under node); the node
// builders only place what those return. Nothing here is scored or
// forecast: it draws numbers the EVENTS panel already baked.

import { el, num, DASH } from './fmt.js';
import { spark } from './spark.js';

const clamp = (v) => Math.max(0, Math.min(100, v));
// Height in px of each half of the reaction chart (the CSS uses the same).
const HALF = 28;
const finite = (v) => v !== null && v !== undefined && Number.isFinite(v);

// Windows of the estimate trail, oldest first. `now` is the consensus itself.
const TRAIL_WINDOWS = ['90d', '60d', '30d', '7d'];

function signed(v, digits = 1) {
  return `${v > 0 ? '+' : ''}${num(v, digits)}%`;
}

// Positions (percent of the axis) of the low-to-high box, the consensus and an
// optional reference (last year's figure). The axis stretches to take the
// reference in, so a year-ago figure outside the range shows as outside it.
export function rangeGeometry(low, high, point, ref = null) {
  if (!finite(low) || !finite(high) || !finite(point) || high < low) return null;
  const members = [low, high, point, ...(finite(ref) ? [ref] : [])];
  const min = Math.min(...members);
  const max = Math.max(...members);
  const pad = (max - min || Math.abs(max) || 1) * 0.06;
  const lo = min - pad;
  const span = max + pad - lo;
  const at = (v) => clamp(((v - lo) / span) * 100);
  return {
    boxLeft: at(low),
    boxWidth: at(high) - at(low),
    pointAt: at(point),
    refAt: finite(ref) ? at(ref) : null,
    outside: point < low || point > high,
  };
}

// Consensus at each window, from the change of the consensus over that window
// (Yahoo gives "now vs N days ago"). A window with no reading is left out; an
// estimate with no reading now has no trail.
export function trailLevels(eps, changes) {
  if (!finite(eps) || !changes) return [];
  const points = TRAIL_WINDOWS
    .filter((w) => finite(changes[w]) && changes[w] > -100)
    .map((w) => ({ label: w, value: eps / (1 + changes[w] / 100) }));
  return points.length ? [...points, { label: 'now', value: eps }] : [];
}

// One sentence on the trail: the net change over the longest window read and
// where in it the change happened. The steps are between the windows Yahoo
// reports, so "between 90d and 60d ago" is as exact as the source allows.
export function trailText(levels) {
  if (levels.length < 2) return null;
  const first = levels[0];
  const last = levels[levels.length - 1];
  const total = (last.value / first.value - 1) * 100;
  if (Math.abs(total) < 0.5) return `flat over ${first.label}`;
  const steps = levels.slice(1).map((p, i) => ({ from: levels[i].label, to: p.label, change: (p.value / levels[i].value - 1) * 100 }));
  const gross = steps.reduce((s, x) => s + Math.abs(x.change), 0);
  const big = steps.reduce((a, b) => (Math.abs(b.change) > Math.abs(a.change) ? b : a));
  const share = gross ? Math.abs(big.change) / gross : 0;
  const where = share >= 0.8 ? ` · most of it between ${big.from} and ${big.to === 'now' ? 'now' : `${big.to} ago`}` : '';
  return `${signed(total)} over ${first.label}${where}`;
}

// Up and down revisions as shares of all that revised; null when none did.
export function splitShares(up, down) {
  const u = finite(up) ? up : 0;
  const d = finite(down) ? down : 0;
  if (u + d <= 0) return null;
  return { up: (u / (u + d)) * 100, down: (d / (u + d)) * 100 };
}

// The last reports as bars, oldest first. `fell` marks a beat the stock sold.
export function moveBars(history) {
  const rows = (history || []).filter((r) => finite(r.move_pct)).slice().reverse();
  const scale = Math.max(0, ...rows.map((r) => Math.abs(r.move_pct)));
  return {
    scale,
    bars: rows.map((r) => ({
      date: r.date,
      move: r.move_pct,
      surprise: finite(r.surprise_pct) ? r.surprise_pct : null,
      fell: finite(r.surprise_pct) && r.surprise_pct > 0 && r.move_pct < 0,
    })),
  };
}

// Hue of each GICS sector, spread so neighbours differ and kept clear of the
// up/down greens and reds; a sector not listed gets one from its name.
const SECTOR_HUE = {
  'Information Technology': 205, 'Communication Services': 275, 'Consumer Discretionary': 325, 'Consumer Staples': 95,
  'Health Care': 170, Financials: 48, Industrials: 235, Energy: 15, Materials: 130, 'Real Estate': 350, Utilities: 60,
};

export function sectorHue(sector) {
  if (!sector) return null;
  if (sector in SECTOR_HUE) return SECTOR_HUE[sector];
  let h = 0;
  for (const ch of sector) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

// The last `sessions` closes as points of a 0-100 box (y grows downward), the
// change over the span, and the dots for report days that fall inside it.
export function priceGeometry(dates, close, marks = [], sessions = 252) {
  if (!dates || !close || dates.length !== close.length) return null;
  const from = Math.max(0, close.length - sessions);
  const d = dates.slice(from);
  const c = close.slice(from);
  if (c.length < 20 || !c.every(finite)) return null;
  const hi = Math.max(...c);
  const lo = Math.min(...c);
  const span = hi - lo || 1;
  const x = (i) => (i / (c.length - 1)) * 100;
  const y = (v) => 100 - ((v - lo) / span) * 100;
  const index = new Map(d.map((day, i) => [day, i]));
  return {
    points: c.map((v, i) => [x(i), y(v)]),
    last: c[c.length - 1],
    first: d[0],
    ret: (c[c.length - 1] / c[0] - 1) * 100,
    high: hi,
    low: lo,
    fromHigh: (c[c.length - 1] / hi - 1) * 100,
    marks: marks.filter((m) => index.has(m.date) && finite(m.move))
      .map((m) => ({ date: m.date, move: m.move, x: x(index.get(m.date)), y: y(c[index.get(m.date)]) })),
  };
}

// --- nodes ---

function labelled(left, middle, right) {
  return el('div', { class: 'ec-rbar-labels' }, [el('span', { text: left }), el('span', { class: 'ec-rbar-mid', text: middle }), el('span', { text: right })]);
}

// A range with the consensus marked in it: `fmt` writes the figures.
export function rangeBarNode(g, { low, high, point, ref, fmt }) {
  if (!g) return null;
  const track = el('div', { class: 'ec-rbar' }, [
    el('div', { class: 'ec-rbar-box', style: `left:${g.boxLeft}%;width:${g.boxWidth}%` }),
    g.refAt !== null ? el('div', { class: 'ec-rbar-ref', style: `left:${g.refAt}%`, title: `year ago ${fmt(ref)}` }) : null,
    el('div', { class: g.outside ? 'ec-rbar-point outside' : 'ec-rbar-point', style: `left:${g.pointAt}%`, title: `consensus ${fmt(point)}` }),
  ]);
  return el('div', { class: 'ec-rbar-wrap' }, [track, labelled(fmt(low), g.refAt !== null ? `┆ year ago ${fmt(ref)}` : '', fmt(high))]);
}

export function splitBarNode(up, down) {
  const s = splitShares(up, down);
  if (!s) return el('div', { class: 'dim ec-vis-note', text: 'no revisions in 30 days' });
  return el('div', { class: 'ec-split-wrap' }, [
    el('div', { class: 'ec-splitbar' }, [
      s.up ? el('div', { class: 'ec-splitbar-up', style: `width:${s.up}%` }) : null,
      s.down ? el('div', { class: 'ec-splitbar-down', style: `width:${s.down}%` }) : null,
    ]),
    el('span', { class: 'ec-vis-note' }, [el('span', { class: 'up', text: `${up ?? 0}↑` }), ' ', el('span', { class: 'down', text: `${down ?? 0}↓` }), ' · 30d']),
  ]);
}

export function trailNode(levels) {
  if (levels.length < 2) return null;
  const rising = levels[levels.length - 1].value >= levels[0].value;
  const line = el('div', { class: `ec-trail-line ${rising ? 'up' : 'down'}` });
  line.append(spark(levels.map((p) => p.value), { width: 150, height: 30, color: 'currentColor' }));
  return el('div', { class: 'ec-trail' }, [
    line,
    el('div', { class: 'ec-trail-labels' }, levels.map((p) => el('span', { text: p.label }))),
  ]);
}

// Bars of the last report-day moves, one dot per report beneath. A dashed line
// at the implied move when the snapshot has one.
export function reactionNode(history, implied) {
  const { scale: seen, bars } = moveBars(history);
  if (!bars.length) return null;
  const impliedPct = implied && finite(implied.straddle_pct) ? implied.straddle_pct : null;
  const scale = Math.max(seen, impliedPct || 0) || 1;
  const h = (v) => `${(Math.abs(v) / scale) * 100}%`;
  const cols = bars.map((b) => el('div', {
    class: 'ec-mbar',
    title: `${b.date}: ${b.move > 0 ? '+' : ''}${num(b.move, 1)}%${b.surprise !== null ? ` · EPS surprise ${b.surprise > 0 ? '+' : ''}${num(b.surprise, 1)}%` : ''}${b.fell ? ' · beat, then fell' : ''}`,
  }, [
    el('div', { class: 'ec-mbar-half top' }, b.move > 0 ? [el('div', { class: 'ec-mbar-fill up', style: `height:${h(b.move)}` })] : []),
    el('div', { class: 'ec-mbar-half bottom' }, b.move < 0 ? [el('div', { class: b.fell ? 'ec-mbar-fill down fell' : 'ec-mbar-fill down', style: `height:${h(b.move)}` })] : []),
    el('div', { class: `ec-mbar-val ${b.move > 0 ? 'up' : 'down'}`, text: `${b.move > 0 ? '+' : ''}${num(b.move, 1)}` }),
  ]));
  // The halves are HALF px tall each, the axis between them; a dashed line a
  // implied-move's height above and below it.
  const reach = impliedPct === null ? 0 : (impliedPct / scale) * HALF;
  const lines = impliedPct === null ? [] : [
    el('div', { class: 'ec-mbar-implied', style: `top:${HALF - reach}px`, title: `implied move ±${num(impliedPct, 1)}%` }),
    el('div', { class: 'ec-mbar-implied', style: `top:${HALF + reach}px` }),
  ];
  const pipRow = el('div', { class: 'ec-pips', title: 'green: the stock rose on the report; red: it fell' }, bars.map((b) => el('span', { class: `ec-pip ${b.move > 0 ? 'up' : 'down'}` })));
  return el('div', { class: 'ec-reaction' }, [el('div', { class: 'ec-mbars' }, [...cols, ...lines]), pipRow]);
}

export function figure(value, digits = 2) {
  return finite(value) ? num(value, digits) : DASH;
}

const SVG = 'http://www.w3.org/2000/svg';

// The year of closes, a dot on each past report day (green rose, red fell).
export function priceNode(g) {
  if (!g) return null;
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('class', 'ec-price-svg');
  const area = document.createElementNS(SVG, 'polygon');
  area.setAttribute('points', `0,100 ${g.points.map(([px, py]) => `${px.toFixed(2)},${py.toFixed(2)}`).join(' ')} 100,100`);
  area.setAttribute('class', 'ec-price-area');
  const line = document.createElementNS(SVG, 'polyline');
  line.setAttribute('points', g.points.map(([px, py]) => `${px.toFixed(2)},${py.toFixed(2)}`).join(' '));
  line.setAttribute('class', 'ec-price-line');
  line.setAttribute('vector-effect', 'non-scaling-stroke');
  svg.append(area, line);
  const dots = g.marks.map((m) => el('span', {
    class: `ec-price-mark ${m.move > 0 ? 'up' : 'down'}`,
    style: `left:${m.x}%;top:${m.y}%`,
    title: `${m.date}: ${m.move > 0 ? '+' : ''}${num(m.move, 1)}% on the report`,
  }));
  const end = g.points[g.points.length - 1];
  const wrap = el('div', { class: `ec-price ${g.ret >= 0 ? 'up' : 'down'}` });
  wrap.append(svg, ...dots, el('span', { class: 'ec-price-now', style: `left:${end[0]}%;top:${end[1]}%` }));
  return el('div', {}, [
    wrap,
    el('div', { class: 'ec-rbar-labels' }, [el('span', { text: `low ${num(g.low, 2)}` }), el('span', { class: 'ec-rbar-mid', text: 'dots = reports' }), el('span', { text: `high ${num(g.high, 2)}` })]),
  ]);
}
