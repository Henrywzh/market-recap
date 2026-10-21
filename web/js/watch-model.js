// SCENARIO WATCH: the numbers the page shows, as pure functions (tested under
// node). The build measured every figure and checked every condition; these
// name the states, arrange the branches and decide what counts as detected.
// Nothing here forecasts.

import { num, DASH } from './fmt.js';
import { detected } from './scenarios-model.js';

const finite = (v) => v !== null && v !== undefined && Number.isFinite(v);

const STATE_LABELS = { triggered: 'TRIGGERED', near: 'NEAR', quiet: 'QUIET', killed: 'KILLED', expired: 'EXPIRED' };
// The order the page lists conditions in: what has fired first, what is closed last.
const STATE_ORDER = ['triggered', 'near', 'quiet', 'killed', 'expired'];
export const CLASS_LABELS = { above: 'ABOVE FORECAST', inline: 'IN LINE', below: 'BELOW FORECAST' };
const CLASSES = ['above', 'inline', 'below'];
const OPS = { below: '≤', above: '≥' };

export function stateLabel(state) {
  return Object.prototype.hasOwnProperty.call(STATE_LABELS, state) ? STATE_LABELS[state] : 'NO DATA';
}

// Decimals a number needs, read from its own digits, at least `min` and at most three.
export function decimalsOf(value, min = 0) {
  const m = String(value).match(/\.(\d+)$/);
  return Math.min(3, Math.max(min, m ? m[1].length : 0));
}

// The unit as the page writes it: a release's percentage points read as %.
function unitText(unit) {
  if (unit === 'pp') return '%';
  return unit || '';
}

// A number with a true minus sign, and a plus only where a move is signed.
function typeset(value, digits, unit = '', signed = false) {
  if (!finite(value)) return DASH;
  const text = num(value, digits);
  // A dollar price reads $108.9, the sign before it: −$4.
  const [pre, post] = unit === '$' ? ['$', ''] : ['', unit];
  if (text.startsWith('-')) return `−${pre}${text.slice(1)}${post}`;
  const moved = signed && /[1-9]/.test(text);
  return `${moved ? '+' : ''}${pre}${text}${post}`;
}

// A move with its sign: +0.4%, −1.2 bp.
export function figure(value, digits = 1, unit = '') {
  return typeset(value, digits, unit, true);
}

// A level, unsigned: 0.3%, 197k, 158.1. A release's rate prints to one decimal.
export function level(value, unit = '') {
  if (!finite(value)) return DASH;
  return typeset(value, decimalsOf(value, unit === 'pp' ? 1 : 0), unitText(unit));
}

// A market probability as a percentage: 18%, 13.5%.
export function probText(p) {
  if (!finite(p)) return DASH;
  const pct = Math.round(p * 1000) / 10;
  return `${num(pct, decimalsOf(pct, 0))}%`;
}

// A measured mean with its standard error: +6.3 bp ±1.4. A missing error drops the ±.
export function measureText(mean, se, digits = 1, unit = '') {
  if (!finite(mean)) return DASH;
  return finite(se) ? `${figure(mean, digits, unit)} ±${num(se, digits)}` : figure(mean, digits, unit);
}

// A measured mean with its t-statistic and whether it is detected (|t| of 2 or more).
// The figure stays shown when it is not detected; the page dims it.
export function measured(mean, se) {
  const hasMean = finite(mean);
  const t = hasMean && finite(se) && se !== 0 ? mean / se : null;
  return {
    mean: hasMean ? mean : null,
    se: finite(se) ? se : null,
    t,
    detected: detected({ t }),
  };
}

// A change in basis points on a FOMC decision: no change, +25 bp, −25 bp.
export function changeText(bp) {
  if (!finite(bp)) return DASH;
  return bp === 0 ? 'no change' : figure(bp, 0, ' bp');
}

// One trigger or kill condition as a sentence: what it measures now, and where it fires.
// `verb` is 'triggers' for a trigger and 'kills' for a kill condition.
export function triggerText(t, verb = 'triggers') {
  if (!t) return null;
  const value = t.measure === 'level'
    ? level(t.value, t.unit)
    : figure(t.value, decimalsOf(t.value, 1), unitText(t.unit));
  const op = OPS[t.op] || '';
  const fires = [`${verb} at`, op, level(t.threshold, t.unit)].filter(Boolean).join(' ');
  const near = finite(t.near) ? ` (near ${[op, level(t.near, t.unit)].filter(Boolean).join(' ')})` : '';
  return `${t.label} ${value} · ${fires}${near}`;
}

// How often the condition fired before: "3 episodes since 2016 · last 2024-08-02 to 2024-08-09".
export function episodeText(e) {
  if (!e || !finite(e.count)) return null;
  const since = e.since ? ` since ${e.since.slice(0, 4)}` : '';
  if (e.count === 0) return `never${since}`;
  const noun = e.count === 1 ? 'episode' : 'episodes';
  const last = e.last?.start
    ? ` · last ${e.last.start}${e.last.end && e.last.end !== e.last.start ? ` to ${e.last.end}` : ''}`
    : '';
  return `${e.count} ${noun}${since}${last}`;
}

// What a scenario needs to fire: every trigger, or any one of them.
export function matchText(scenario) {
  if (scenario?.match === 'all') return 'every trigger must hold';
  if (scenario?.match === 'any') return 'any one trigger is enough';
  return null;
}

// The change since the last build, named by the state it came from.
export function changedText(scenario) {
  if (!scenario?.changed) return null;
  return scenario.previous_state ? `CHANGED TODAY (was ${stateLabel(scenario.previous_state)})` : 'CHANGED TODAY';
}

// How an expired or killed scenario ended; null while it is live.
export function outcomeText(scenario) {
  if (!scenario?.outcome) return null;
  if (scenario.outcome === 'killed') return `Killed${scenario.killed_on ? ` on ${scenario.killed_on}` : ''}`;
  const horizon = scenario.horizon ? ` ${scenario.horizon}` : '';
  const first = scenario.first_triggered ? ` · first triggered ${scenario.first_triggered}` : '';
  return `Expired${horizon}: ${scenario.outcome}${first}`;
}

// The trigger's history as two aligned arrays for a chart; a missing value is null, never NaN.
export function historySeries(t) {
  const rows = Array.isArray(t?.history) ? t.history : [];
  return {
    dates: rows.map((row) => row[0]),
    values: rows.map((row) => (finite(row[1]) ? row[1] : null)),
  };
}

// The y-axis range that holds every value and every marked threshold, padded a little
// (ECharts does not widen the axis for a markLine on its own).
export function axisBounds(values, marks = []) {
  const all = [...(values || []), ...(marks || [])].filter(finite);
  if (!all.length) return null;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const pad = (max - min) * 0.08 || 1;
  return { min: min - pad, max: max + pad };
}

// Scheduled items in date order, then by clock time; a new array, the input is untouched.
export function sortEvents(events) {
  const key = (e) => `${e?.date || ''}${e?.time || ''}`;
  return [...(events || [])].sort((a, b) => key(a).localeCompare(key(b)));
}

// The release card's headline figures: the consensus, the prior, and the Kalshi
// median with its 10-90 range and open interest.
export function releaseStats(event) {
  const market = event?.market || null;
  const unit = event?.unit || '';
  const hasRange = market && finite(market.low) && finite(market.high);
  // Market quantiles are interpolated, so they carry the consensus's decimals (one more for a rate).
  const digits = decimalsOf(event?.forecast ?? event?.previous ?? 0, 0) + (unit === 'pp' ? 1 : 0);
  const quoted = (v) => (finite(v) ? typeset(v, digits, unitText(unit)) : DASH);
  return {
    forecast: level(event?.forecast, unit),
    previous: level(event?.previous, unit),
    median: market ? quoted(market.median) : DASH,
    range: hasRange ? `${quoted(market.low)} to ${quoted(market.high)}` : null,
    openInterest: market && finite(market.open_interest) ? num(market.open_interest, 0) : null,
  };
}

// One row per branch of a release: above, in line, below the forecast. Each carries the
// market's probability for it and the measured 2-year and SPY moves on past releases in it.
export function branchRows(event) {
  if (!event) return [];
  const market = event.market || {};
  const branches = event.branches || {};
  return CLASSES.map((cls) => {
    const b = branches[cls] || {};
    return {
      cls,
      label: CLASS_LABELS[cls],
      probability: finite(market[`p_${cls}`]) ? market[`p_${cls}`] : null,
      n: finite(b.n) ? b.n : null,
      dY2: measured(b.dY2, b.dY2_se),
      SPY: measured(b.SPY, b.SPY_se),
    };
  });
}

// The last release's actual against its forecast, and the branch it fell in, with the
// moves that day. Null when the build has no last release for this line.
export function lastReleaseText(event) {
  const last = event?.latest;
  if (!last?.date) return null;
  const unit = event.unit || '';
  const branch = CLASS_LABELS[last.cls] || DASH;
  const moves = [finite(last.dY2) ? `2Y ${figure(last.dY2, 1, ' bp')}` : null, finite(last.SPY) ? `SPY ${figure(last.SPY, 2, '%')}` : null].filter(Boolean);
  return `Last release ${last.date}: actual ${level(last.actual, unit)} vs forecast ${level(last.forecast, unit)} — ${branch}${moves.length ? ` · ${moves.join(', ')}` : ''}`;
}

// The FOMC card's rows: the Kalshi outcomes with their probabilities, then the hawkish
// and dovish branches with the 2-year threshold that defines each and the mean SPY move.
export function fomcRows(event) {
  if (!event) return [];
  const outcomes = (event.market?.outcomes || []).map((o) => ({
    kind: 'market',
    label: o.label,
    changeBp: finite(o.change_bp) ? o.change_bp : null,
    probability: finite(o.probability) ? o.probability : null,
  }));
  const b = event.branches || {};
  const bp = finite(b.bp) ? b.bp : null;
  const branch = (kind, side, label) => {
    const v = b[side] || {};
    return { kind, label: bp === null ? label : `${label} ${bp} bp that day`, bp, n: finite(v.n) ? v.n : null, SPY: finite(v.SPY) ? v.SPY : null };
  };
  return [
    ...outcomes,
    branch('hawkish', 'hawkish', '2Y up ≥'),
    branch('dovish', 'dovish', '2Y down ≥'),
  ];
}

// How many conditions are triggered and how many are near: the page's header counts.
export function countStates(scenarios) {
  const list = scenarios || [];
  return {
    triggered: list.filter((s) => s?.state === 'triggered').length,
    near: list.filter((s) => s?.state === 'near').length,
  };
}

// Triggered first, then near, quiet, killed, expired; then by name. A new array.
export function sortScenarios(list) {
  const rank = (s) => {
    const i = STATE_ORDER.indexOf(s?.state);
    return i < 0 ? STATE_ORDER.length : i;
  };
  return [...(list || [])].sort((a, b) => rank(a) - rank(b) || String(a?.name || '').localeCompare(String(b?.name || '')));
}
