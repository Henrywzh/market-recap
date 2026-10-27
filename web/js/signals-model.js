// The TODAY signals as one ranked list: pure data, no DOM, so node can test it.
// The build's `unusual` items become signal objects (state, severity, age,
// distance, the chip text and link); today-board.js draws them, and e-mail alerts
// and agents can read the same list. The number formatting is a copy of fmt.js
// `num` because this module imports nothing.

export const GROUP_ORDER = ['OVERSOLD', 'RARE', 'CHANGED', 'SCENARIO', 'ONGOING', 'ETF FLOWS'];
export const MUTED_KEY = 'today.signals.muted';

const DASH = '—';
const MINUS = '−';
const DAY_MS = 86400000;
const valid = (v) => typeof v === 'number' && Number.isFinite(v);

// The same figure as fmt.js num: en-US digits, a value that rounds to zero prints as zero.
function numText(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  const rounded = Math.abs(value) < 0.5 * 10 ** -digits ? 0 : Number(value);
  return rounded.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

// A signed percentage with a true minus; a value that rounds to zero has no sign.
function movePct(value) {
  if (!valid(value)) return DASH;
  const rounded = Number(Math.abs(value).toFixed(1));
  const sign = rounded === 0 ? '' : value < 0 ? MINUS : '+';
  return `${sign}${numText(rounded, 1)}%`;
}

// A figure in its unit ("$113", "0.95", "+42bp"); a dollar sign goes in front.
function figure(value, unit, digits, signed = false) {
  const text = `${signed && value > 0 ? '+' : ''}${numText(value, digits)}`;
  return unit === '$' ? `$${text}` : `${text}${unit || ''}`;
}

// A trigger's figure to the precision its size needs: "$113", "0.95", "+42bp".
function triggerFigure(value, unit, signed = false) {
  const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
  return figure(value, unit, digits, signed);
}

// A fund flow in dollars: "+$4.4bn", "−$310m".
export function flowDollars(v) {
  if (!valid(v)) return DASH;
  const a = Math.abs(v);
  const sign = v > 0 ? '+' : v < 0 ? MINUS : '';
  return a >= 1e9 ? `${sign}$${numText(a / 1e9, 1)}bn` : `${sign}$${numText(a / 1e6, 0)}m`;
}

// CHANGED reads as the state itself: the title after its colon, the build's
// parenthesis left out ("Treasuries · technical: MOVE moved to elevated (...)").
export function stateText(item) {
  const title = String(item.title ?? '');
  const cut = title.includes(':') ? title.slice(title.indexOf(':') + 1) : title;
  return cut.replace(/\s*\([^)]*\)\s*$/, '').trim() || item.subject;
}

// A watch scenario: its figure against its trigger; without figures, the state.
export function scenarioText(item) {
  const { value, threshold, state, unit, op, measure } = item.extra || {};
  if (valid(value) && valid(threshold)) {
    const sign = op === 'below' ? '≤' : '≥';
    return `${item.subject} ${triggerFigure(value, unit, measure && measure !== 'level')} ${sign} ${triggerFigure(threshold, unit)}`;
  }
  return [item.subject, state].filter(Boolean).join(' · ');
}

// A sessions count or a value with its unit, for an ONGOING line.
const compactValue = (item) => {
  if (valid(item.days)) return `${item.days} sessions`;
  if (valid(item.value)) return `${numText(item.value, 1)}${item.unit === '%' ? '%' : item.unit ? ` ${item.unit}` : ''}`;
  return '';
};

// The week's ETF flow: the US equity funds together, then the largest funds in and out.
// Each chip has a key by date and fund, so muting one day's flow does not mute the next.
export function flowChips(flows) {
  if (!flows || !valid(flows.us_equity_1w)) return [];
  const rank = valid(flows.us_equity_1w_pct_rank) ? ` · ${numText(flows.us_equity_1w_pct_rank, 0)}th pct` : '';
  const title = `Creations less redemptions over five sessions to ${flows.date}, from the issuers' published shares outstanding; the percentile ranks it against three years of weeks.`;
  const chip = (id, text, flow) => ({ key: `flows:${flows.date}:${id}`, text, title, href: '#flows', tone: flow < 0 ? 'down' : 'up' });
  const fund = ([ticker, flow]) => chip(ticker, `${ticker} ${flowDollars(flow)}`, flow);
  return [
    chip('US equity', `US equity 1W ${flowDollars(flows.us_equity_1w)}${rank}`, flows.us_equity_1w),
    ...(flows.top_in || []).map(fund),
    ...(flows.top_out || []).map(fund),
  ];
}

// The age in days: the build's `days` when it has one; else from `since` to `date`,
// counted inclusively so a signal that began on its own date is day 1 (as the build counts).
export function ageOf(item) {
  if (valid(item.days)) return item.days;
  const since = Date.parse(item.since);
  const date = Date.parse(item.date);
  if (!Number.isFinite(since) || !Number.isFinite(date) || date < since) return null;
  return Math.round((date - since) / DAY_MS) + 1;
}

// State rules. A watch reads its own state; a risk state that has ended is CLEARED;
// anything the build marks as continuing (new:false, or from `ongoing`) is ONGOING;
// the rest are NEW.
export function stateOf(item, { ongoing = false } = {}) {
  if (item.kind === 'watch' && item.extra?.state === 'triggered') return 'TRIGGERED';
  if (item.kind === 'watch' && item.extra?.state === 'near') return 'NEAR';
  if (item.extra?.active === false) return 'CLEARED';
  if (ongoing || item.new === false) return 'ONGOING';
  return 'NEW';
}

// Severity, higher is more important. TRIGGERED 5; a NEW risk state into stressed, or
// a NEW oversold at the 20 line, 4; any other NEW 3; NEAR 2; ONGOING 1; CLEARED 0.
// Ties in rankSignals go to the rarer move, then to subject A-Z.
export function severityOf(state, hot = false) {
  switch (state) {
    case 'TRIGGERED': return 5;
    case 'NEW': return hot ? 4 : 3;
    case 'NEAR': return 2;
    case 'ONGOING': return 1;
    default: return 0;
  }
}

// How far a near watch is from its trigger: "needs 7.0 more to 120". Null otherwise.
function watchDistance(item) {
  const { value, threshold, unit } = item.extra || {};
  if (!valid(value) || !valid(threshold)) return null;
  return `needs ${figure(Math.abs(threshold - value), unit, 1)} more to ${triggerFigure(threshold, unit)}`;
}

// How far an oversold reading is below its line: "RSI 24.1 · 4.1 below 30". Null if not below.
function oversoldDistance(item) {
  const rsi = item.extra?.rsi ?? item.value;
  const line = item.extra?.line;
  if (!valid(rsi) || !valid(line) || line <= rsi) return null;
  return `RSI ${numText(rsi, 1)} · ${numText(line - rsi, 1)} below ${line}`;
}

// One signal from a build item. `fields` carries what differs by group.
function signal(group, item, fields) {
  const state = fields.state ?? stateOf(item);
  return {
    key: item.key ?? `${group}:${item.subject}:${item.date}`,
    group,
    // The label beside the state: the group, or for an ONGOING line what kind it is
    // (RISK, WATCH), as its state badge already says ONGOING.
    tag: fields.tag ?? group,
    text: fields.text,
    title: fields.title ?? item.title ?? '',
    href: fields.href ?? item.link ?? null,
    tone: fields.tone,
    state,
    age: ageOf(item),
    severity: severityOf(state, fields.hot),
    distance: fields.distance ?? null,
    rarity: valid(item.extra?.share_pct) ? item.extra.share_pct : null,
    subject: String(item.subject ?? fields.text),
  };
}

// The sort: severity high first, then the rarer move (lower share of days), then subject A-Z.
export function rankSignals(list) {
  const rarity = (s) => (valid(s.rarity) ? s.rarity : Infinity);
  const compare = (x, y) => (x === y ? 0 : x < y ? -1 : 1);
  return [...list].sort((a, b) => (b.severity - a.severity)
    || compare(rarity(a), rarity(b))
    || compare(a.subject, b.subject));
}

// Every signal the page shows today, ranked. `boardRows` names the sector funds in
// the chips; `flows` is the week's ETF flow. A kind with nothing in it adds nothing.
export function toSignals(unusual, boardRows, flows) {
  const names = new Map((Array.isArray(boardRows) ? boardRows : []).filter(Boolean).map((r) => [r.symbol, r.short || r.label]));
  const nameOf = (item) => names.get(item.extra?.symbol) ?? item.subject;
  const list = [];
  const each = (items, fn) => (Array.isArray(items) ? items : []).filter(Boolean).forEach((item) => list.push(fn(item)));

  each(unusual?.oversold, (item) => {
    const rsi = item.extra?.rsi ?? item.value;
    const line20 = item.extra?.line === 20;
    return signal('OVERSOLD', item, {
      text: `${nameOf(item)} ${valid(rsi) ? numText(rsi, 1) : DASH}`,
      title: item.detail ?? item.title,
      tone: line20 ? 'down' : 'warn',
      hot: line20,
      distance: oversoldDistance(item),
    });
  });

  each(unusual?.tails, (item) => signal('RARE', item, {
    text: `${nameOf(item)} ${movePct(item.value)} · ${valid(item.extra?.share_pct) ? `${numText(item.extra.share_pct, 1)}%` : DASH}`,
    title: item.detail ?? item.title,
    href: item.extra?.symbol ? `#movecheck/${item.extra.symbol}` : item.link,
    tone: item.value < 0 ? 'down' : 'up',
  }));

  each(unusual?.states, (item) => {
    const state = stateOf(item);
    return signal('CHANGED', item, {
      state,
      text: stateText(item),
      tone: item.extra?.active === false ? 'dim' : 'info',
      hot: state === 'NEW' && item.extra?.state === 'stressed',
    });
  });

  each(unusual?.watch, (item) => {
    const state = stateOf(item);
    return signal('SCENARIO', item, {
      state,
      text: scenarioText(item),
      href: item.link || '#watch',
      tone: state === 'TRIGGERED' ? 'down' : 'warn',
      distance: state === 'NEAR' ? watchDistance(item) : null,
    });
  });

  each(unusual?.ongoing, (item) => signal('ONGOING', item, {
    state: stateOf(item, { ongoing: true }),
    tag: String(item.kind || 'state').toUpperCase(),
    text: [item.subject, compactValue(item)].filter(Boolean).join(' · '),
    tone: 'dim',
  }));

  // The week's flows are one line, the US equity total then the largest funds in and
  // out, so a busy week does not push the other signals down the list.
  const [total, ...funds] = flowChips(flows);
  if (total) {
    const text = [total.text, ...funds.map((f) => f.text)].join(' · ');
    list.push({
      key: `flows:${flows.date}`, group: 'ETF FLOWS', tag: 'ETF FLOWS', text, title: total.title, href: total.href, tone: total.tone,
      state: 'NEW', age: null, severity: 1, distance: null, rarity: null, subject: text,
    });
  }

  return rankSignals(list);
}

// The muted keys from storage. Storage may be missing or blocked: then nothing is muted.
export function readMuted(storage) {
  try {
    const list = JSON.parse(storage?.getItem(MUTED_KEY) ?? '[]');
    return Array.isArray(list) ? list.filter((k) => typeof k === 'string') : [];
  } catch {
    return [];
  }
}

// Saves the muted keys. Returns false when storage refused, so the page keeps them for the session only.
export function writeMuted(storage, keys) {
  try {
    if (!storage) return false;
    storage.setItem(MUTED_KEY, JSON.stringify([...new Set(keys)]));
    return true;
  } catch {
    return false;
  }
}
