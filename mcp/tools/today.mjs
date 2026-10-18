// today: what matters for the next session, as the TODAY page shows it. It
// reads the build's artifacts/today.json and trims it to the size budget; the
// lists, order and wording are the build's, nothing is recomputed here.

import { outputSchema } from '../context.mjs';
import { T } from '../schema.mjs';
import { capList, finite, pick, text } from '../util.mjs';

const SECTIONS = ['all', 'just_out', 'coming_up', 'unusual'];
// Items per list. The build already caps the unusual lists; this keeps the
// rest, and the 20 KB backstop in context.mjs handles anything larger.
const LIST_LIMIT = 15;

// One item as the build wrote it, with each value kept only when it is what
// the item says (a missing number stays null, not 0).
function compactItem(item) {
  return {
    key: item.key ?? null, kind: item.kind ?? null, date: item.date ?? null, time: item.time ?? null,
    timing: item.timing ?? null, subject: item.subject ?? null, title: text(item.title, 300), detail: text(item.detail, 300),
    value: finite(item.value), unit: item.unit ?? null, z: finite(item.z), importance: item.importance ?? null,
    new: item.new === true, since: item.since ?? null, days: finite(item.days), evidence: item.evidence ?? null,
    link: item.link ?? null, extra: item.extra && typeof item.extra === 'object' ? item.extra : {},
  };
}

// The first LIST_LIMIT items and how many were left out.
function list(items, limit = LIST_LIMIT) {
  const page = capList(Array.isArray(items) ? items : [], limit);
  return { items: page.items.map(compactItem), more: page.more };
}

function justOut(data) {
  const block = data.just_out || {};
  const macro = list(block.macro);
  const earnings = list(block.earnings);
  return {
    session: block.session ?? null,
    macro: macro.items, earnings: earnings.items,
    more_macro: macro.more, more_earnings: earnings.more,
  };
}

function comingUp(data) {
  const block = data.coming_up || {};
  const days = (Array.isArray(block.days) ? block.days : []).map((day) => {
    const page = list(day.items);
    return { date: day.date ?? null, items: page.items, more: page.more };
  });
  const later = list(block.later);
  return { days, later: later.items, more_later: later.more, later_until: block.later_until ?? null };
}

function unusual(data) {
  const block = data.unusual || {};
  const moves = list(block.moves);
  const states = list(block.states);
  const events = list(block.events);
  const ongoing = list(block.ongoing);
  return {
    moves: moves.items, more_moves: moves.more,
    states: states.items, more_states: states.more,
    events: events.items, more_events: events.more,
    ongoing: ongoing.items, more_ongoing: ongoing.more,
  };
}

function live(data) {
  return pick(data.live || {}, ['threshold_sigma', 'market', 'sector_funds', 'max_items']);
}

// The build's own list of parts it could not read. They join the envelope's
// `unavailable`, so a client sees the same gaps the page shows as dashes.
function carryUnavailable(data, ctx) {
  (Array.isArray(data.unavailable) ? data.unavailable : []).forEach((u) => {
    if (u && typeof u.part === 'string') ctx.missing(u.part, text(u.reason, 300) || 'the build could not read this part');
  });
}

export async function today(ctx, args = {}) {
  const section = args.section || 'all';
  const data = await ctx.get('today', 'TODAY');
  ctx.caveat(
    'Unusual means beyond the stock\'s own recent volatility after removing the market and its sector. It describes the session, not news or a signal.',
    'Items marked TESTED are backed by a research table in the build; the others are descriptions.',
    'Dates are sessions in New York time. Expectations come from survey and market-implied sources, not facts.',
  );
  const out = { sessions: data ? (Array.isArray(data.sessions) ? data.sessions : []) : null };
  if (!data) {
    if (section === 'all' || section === 'just_out') out.just_out = null;
    if (section === 'all' || section === 'coming_up') out.coming_up = null;
    if (section === 'all' || section === 'unusual') out.unusual = null;
    if (section === 'all') out.live = null;
    return out;
  }
  (Array.isArray(data.notes) ? data.notes : []).forEach((note) => ctx.note(text(note, 400)));
  carryUnavailable(data, ctx);
  if (section === 'all' || section === 'just_out') out.just_out = justOut(data);
  if (section === 'all' || section === 'coming_up') out.coming_up = comingUp(data);
  if (section === 'all' || section === 'unusual') out.unusual = unusual(data);
  if (section === 'all') out.live = live(data);
  return out;
}

export const todayTool = {
  name: 'today',
  title: 'Today',
  description: 'What matters for the next session: what just came out, what is coming in the next three sessions, and what is unusual now (moves beyond each stock\'s own volatility, market states that started or ended).',
  inputSchema: T.obj({
    section: { type: 'string', enum: SECTIONS, description: 'One part only: just_out, coming_up or unusual. Default all.' },
  }),
  outputSchema: outputSchema({
    sessions: T.maybe(T.arr(T.str)),
    just_out: T.maybe(T.obj({ session: T.strNull, macro: T.arr(T.obj({ key: T.str, kind: T.str, title: T.strNull }, ['key', 'kind'])), earnings: T.arr(T.obj({ key: T.str, kind: T.str, title: T.strNull }, ['key', 'kind'])) }, ['macro', 'earnings'])),
    coming_up: T.maybe(T.obj({
      days: T.arr(T.obj({ date: T.strNull, items: T.arr(T.obj({ key: T.str, kind: T.str, title: T.strNull }, ['key', 'kind'])) }, ['date', 'items'])),
      later: T.arr(T.obj({ key: T.str, kind: T.str, title: T.strNull }, ['key', 'kind'])), later_until: T.strNull,
    }, ['days', 'later'])),
    unusual: T.maybe(T.obj({
      moves: T.arr(T.obj({ key: T.str, kind: T.str, title: T.strNull }, ['key', 'kind'])), states: T.arr(T.obj({ key: T.str, kind: T.str, title: T.strNull }, ['key', 'kind'])),
      events: T.arr(T.obj({ key: T.str, kind: T.str, title: T.strNull }, ['key', 'kind'])), ongoing: T.arr(T.obj({ key: T.str, kind: T.str, title: T.strNull }, ['key', 'kind'])),
    }, ['moves', 'states', 'events', 'ongoing'])),
    live: T.maybe(T.obj({ threshold_sigma: T.num, market: T.strNull, max_items: T.num })),
  }, []),
  run: today,
};
