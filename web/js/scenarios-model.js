// SCENARIOS: the numbers behind the page's drawings, as pure functions (tested
// under node). Nothing here estimates anything: the build measured it. These
// decide only what is shown as detected, how a difference's noise is carried
// and where a bar sits.

import { num, DASH } from './fmt.js';

// A figure counts as detected at |t| of 2 or more. Under it the page still
// shows the figure, dimmed, with its n: "not detected" is not "zero".
export const DETECTED_T = 2;
export const NORMAL_95 = 1.96;

const finite = (v) => v !== null && v !== undefined && Number.isFinite(v);

export function detected(entry) {
  return Boolean(entry) && finite(entry.t) && Math.abs(entry.t) >= DETECTED_T;
}

// The difference of two class means with its standard error (independent
// samples); null when either has no figure.
export function diffWithSe(a, b) {
  if (!a || !b || !finite(a.mean) || !finite(b.mean)) return null;
  const se = finite(a.se) && finite(b.se) ? Math.hypot(a.se, b.se) : null;
  const diff = a.mean - b.mean;
  return { diff, se, t: se ? diff / se : null, within: se === null ? true : Math.abs(diff) < NORMAL_95 * se };
}

// Above-minus-below for each sector, largest first. `sectors` is the panel's
// {sector, etf} list: the ETF names the class means' keys.
export function sectorDiffs(classes, sectors) {
  const rows = [];
  for (const s of sectors || []) {
    const d = diffWithSe(classes?.above?.[s.etf], classes?.below?.[s.etf]);
    if (d) rows.push({ sector: s.sector, etf: s.etf, ...d });
  }
  return rows.sort((x, y) => y.diff - x.diff);
}

// A bar from the centre of a track: `left` and `width` in percent for a value
// on a scale that fills half of it. A value past the scale is cut at the edge.
export function barSpan(value, scale) {
  if (!finite(value) || !finite(scale) || scale <= 0) return null;
  const share = Math.min(1, Math.abs(value) / scale) * 50;
  return value >= 0 ? { left: 50, width: share } : { left: 50 - share, width: share };
}

// The shared scale for a column of bars: the largest magnitude present.
export function columnScale(values) {
  const v = values.filter(finite).map(Math.abs);
  return v.length ? Math.max(...v) : null;
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function nextText(next) {
  if (!next || !next.date) return null;
  const d = new Date(`${next.date}T00:00:00Z`);
  const when = `${WEEKDAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}${next.time ? ` ${next.time}` : ''}`;
  const unit = next.unit === 'k' || next.unit === 'pts' ? '' : '';
  const fmt = (v) => (finite(v) ? num(v, next.unit === 'k' ? 0 : 1) + unit : DASH);
  return { when, forecast: fmt(next.forecast), previous: fmt(next.previous) };
}

// How the sector-ordering test reads: tested with its rho and permutation p,
// or too few releases to test.
export function persistenceView(p) {
  if (!p || p.status !== 'tested') return { text: 'too few releases', tone: 'dim', title: 'a class has fewer releases than the test needs' };
  const rho = `${p.rho > 0 ? '+' : ''}${num(p.rho, 2)}`;
  const text = `ρ ${rho} · p ${num(p.p_perm, 2)}`;
  const title = `sector ordering of above-minus-below, found before ${p.split} and checked after: `
    + `${p.train_above}/${p.train_below} releases before, ${p.test_above}/${p.test_below} after (above/below); `
    + `p from ${p.permutations} label shuffles`;
  return { text, tone: p.p_perm < 0.05 ? 'info' : 'dim', title };
}
