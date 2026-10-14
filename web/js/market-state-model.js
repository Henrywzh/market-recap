// MARKET STATE: how the build's measurements read on the page. Pure, tested
// under node. The numbers and the detection flags come from the build; these
// functions phrase a cell and choose a tone.

import { num, DASH } from './fmt.js';

const finite = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits) => `${v > 0 ? '+' : ''}${num(v, digits)}`;

const UNIT_TEXT = { pp: ' pp', '%': '%', pts: '' };

// A reading's value as the strip shows it: "-4.2 pp", "45%", "14.8".
export function readingText(reading) {
  if (!reading || !finite(reading.value)) return DASH;
  const unit = UNIT_TEXT[reading.unit] ?? '';
  return `${reading.unit === 'pp' ? signed(reading.value, 1) : num(reading.value, 1)}${unit}`;
}

// The line under the value: "5 of 11 funds" for the sector shares.
export function readingNote(reading) {
  const c = reading?.count;
  return c ? `${c.above} OF ${c.of} FUNDS` : null;
}

// Which way a detected difference is good or bad for someone holding the
// market: a higher return is good, a deeper worst fall and a likelier fall of
// the floor are bad. Undetected is never coloured.
const BAD_WHEN = { ret: 'lower', worst_dd: 'lower', hit: 'higher' };

// One outcome cell: the mean inside the state against outside it, the
// difference and its 95% range. `unit` is 'pp' or '%'. Dim unless the range
// excludes zero.
export function outcomeCell(key, o, unit) {
  if (!o || !finite(o.diff)) return { text: DASH, tone: 'dim', title: 'too few days to measure' };
  const range = finite(o.lo) && finite(o.hi) ? `${signed(o.lo, 1)} to ${signed(o.hi, 1)}` : DASH;
  const text = `${signed(o.diff, 1)} (${range})`;
  const title = `${num(o.inside, 1)}${unit === 'pp' ? '%' : unit} inside the state, ${num(o.outside, 1)}${unit === 'pp' ? '%' : unit} outside; `
    + `difference ${signed(o.diff, 1)} ${unit}, 95% range ${range}`;
  if (!o.detected) return { text, tone: 'dim', title: `${title}; no difference detected` };
  const bad = (BAD_WHEN[key] === 'lower') === (o.diff < 0);
  return { text, tone: bad ? 'down' : 'up', title };
}

// What holds now and which of it has a detected consequence, in the build's own
// words (labels) and numbers. Returns { holding, detected, undetected } where
// `detected` lists {label, parts} with the outcomes whose range excludes zero.
export function stateSummary(states, floor = null) {
  const now = (states || []).filter((s) => s.active_now);
  const detected = [];
  const undetected = [];
  const fall = floor === null ? 'chance of a fall' : `chance of a ${floor}%+ fall`;
  for (const s of now) {
    const parts = [];
    if (s.status === 'ok') {
      for (const [key, label] of [['ret', 'return'], ['worst_dd', 'worst fall'], ['hit', fall]]) {
        const o = s.outcomes?.[key];
        if (o?.detected) parts.push(`${label} ${signed(o.diff, 1)} pp`);
      }
    }
    (parts.length ? detected : undetected).push({ label: s.label, parts, days: s.days, episodes: s.episodes, status: s.status });
  }
  return { holding: now.map((s) => s.label), detected, undetected };
}

// "13 days" / "since 2026-09-21" would need a date; the build gives the days.
export function daysNow(state) {
  return state?.active_now ? `NOW · ${state.days_now} D` : null;
}

// Colour current conditions by adverse historical evidence, not the rule's
// alarming name. Require the reported flag AND a finite, adverse 95% range.
export function statePresentation(state) {
  if (!state?.active_now) return { tone: 'dim', level: 'inactive', label: 'NOT ACTIVE', reason: 'Rule does not hold on this artifact date.' };
  if (state.status !== 'ok') return { tone: 'warn', level: 'active', label: 'ACTIVE', reason: 'Rule holds; too little history to assess subsequent risk.' };
  const adverse = [];
  for (const [key, label] of [['ret', 'lower return'], ['worst_dd', 'deeper drawdown'], ['hit', 'higher fall probability']]) {
    const o = state.outcomes?.[key];
    if (!o?.detected || ![o.diff, o.lo, o.hi].every(finite) || o.lo > o.hi) continue;
    if (key === 'hit' ? o.diff > 0 && o.lo > 0 : o.diff < 0 && o.hi < 0) adverse.push(label);
  }
  if (!adverse.length) return { tone: 'warn', level: 'active', label: 'ACTIVE', reason: 'Rule holds; no clear adverse historical difference.' };
  const ret = state.outcomes?.ret;
  const rebound = ret?.detected && [ret.lo, ret.hi, ret.diff].every(finite) && ret.lo <= ret.hi && ret.lo > 0 && ret.diff > 0;
  return { tone: 'down', level: 'risk', label: 'CAUTION', reason: `${adverse.join(' · ')}${rebound ? '; stronger rebound too' : ''}.` };
}

// A sector fund against its 200-day line.
export function sectorFlag(row) {
  if (row.above_200 === null || row.above_200 === undefined) return { text: DASH, tone: 'dim' };
  return { text: `${row.above_200 ? '▲' : '▼'} ${finite(row.vs_200_pct) ? signed(row.vs_200_pct, 1) : DASH}%`, tone: row.above_200 ? 'up' : 'down' };
}
