// Pure MONITOR v1 semantics.  The artifact owns the observations; this module
// only derives the adjustable-threshold view and manages the browser-local
// follow list.  Keeping these rules outside the DOM renderer makes threshold
// changes cheap to reason about and test.

export const MONITOR_STATUSES = Object.freeze({
  BASELINE: 'baseline',
  NEWLY_ENTERED: 'newly entered',
  CONTINUING: 'continuing',
  EXITED: 'exited',
  OUTSIDE: 'outside',
  UNKNOWN: 'unknown',
  OUTSIDE_UNIVERSE: 'outside universe',
});

export const FOLLOW_SCHEMA_VERSION = 1;
export const FOLLOW_KIND = 'market-recap-monitor-follows';
export const FOLLOW_STORAGE_KEY = 'market-recap:monitor:follows:v1';

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const TICKER_RE = /^[A-Z0-9][A-Z0-9._-]{0,31}$/;
const STATUS_ORDER = new Map([
  [MONITOR_STATUSES.NEWLY_ENTERED, 0],
  [MONITOR_STATUSES.BASELINE, 1],
  [MONITOR_STATUSES.CONTINUING, 2],
  [MONITOR_STATUSES.EXITED, 3],
  [MONITOR_STATUSES.UNKNOWN, 4],
  [MONITOR_STATUSES.OUTSIDE, 5],
  [MONITOR_STATUSES.OUTSIDE_UNIVERSE, 6],
]);

function finiteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function isObservedValue(value) {
  return value === null || finiteNumber(value) !== null;
}

function isDate(value) {
  if (typeof value !== 'string' || !DATE_RE.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const stamp = new Date(Date.UTC(year, month - 1, day));
  return stamp.getUTCFullYear() === year
    && stamp.getUTCMonth() === month - 1
    && stamp.getUTCDate() === day;
}

function thresholdNumber(value, fallback = 20) {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') {
    return fallback;
  }
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return number;
}

/** Clamp the user-adjustable threshold to the UI's 1–99% contract. */
export function normalizeThreshold(value, fallback = 20) {
  const safeFallback = Math.min(99, Math.max(1, thresholdNumber(fallback, 20)));
  const number = thresholdNumber(value, safeFallback);
  return Math.min(99, Math.max(1, number));
}

/**
 * Normalize daily observations into chronological unique-date observations.
 * The last value supplied for a date wins, which mirrors the artifact writer's
 * replace-same-day rule.  Malformed observations are ignored rather than
 * turning an absent value into zero.
 */
export function normalizeObservedHistory(history) {
  const byDate = new Map();
  for (const item of Array.isArray(history) ? history : []) {
    if (!Array.isArray(item) || item.length < 2) continue;
    const [date, rawValue] = item;
    if (!isDate(date)) continue;
    if (!isObservedValue(rawValue)) continue;
    byDate.set(date, rawValue === undefined ? null : rawValue);
  }
  return [...byDate.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([date, value]) => [date, value]);
}

function qualifies(value, threshold) {
  return value !== null && value <= -normalizeThreshold(threshold);
}

function historyState(history, threshold, asOf = null) {
  const normalized = normalizeObservedHistory(history);
  const limit = normalizeThreshold(threshold);
  if (!normalized.length) {
    return {
      history: normalized,
      latestDate: null,
      latestValue: null,
      currentValue: null,
      currentQualifies: null,
      firstObserved: null,
      firstObservedValue: null,
      previousDate: null,
      previousValue: null,
      unknownGap: false,
      stale: false,
    };
  }

  const latestIndex = normalized.length - 1;
  const [latestDate, latestValue] = normalized[latestIndex];
  const first = normalized.find(([, value]) => qualifies(value, limit));
  let previousIndex = -1;
  for (let index = latestIndex - 1; index >= 0; index -= 1) {
    if (normalized[index][1] !== null) {
      previousIndex = index;
      break;
    }
  }
  const unknownGap = previousIndex >= 0
    && normalized.slice(previousIndex + 1, latestIndex).some(([, value]) => value === null);
  const stale = Boolean(asOf && latestDate !== asOf);
  const currentValue = stale || latestValue === null ? null : latestValue;

  return {
    history: normalized,
    latestDate,
    latestValue,
    currentValue,
    currentQualifies: currentValue === null ? null : qualifies(currentValue, limit),
    firstObserved: first ? first[0] : null,
    firstObservedValue: first ? first[1] : null,
    previousDate: previousIndex >= 0 ? normalized[previousIndex][0] : null,
    previousValue: previousIndex >= 0 ? normalized[previousIndex][1] : null,
    unknownGap,
    stale,
  };
}

/**
 * Derive the pool status from observed history at the supplied threshold.
 * Null observations are uncertainty, never an inferred exit.  A first
 * qualifying observation is labelled BASELINE when there is no known prior
 * observation; FIRST OBSERVED is derived from the supplied history and is not
 * presented as the historical entry date.
 */
export function derivePoolStatus(row, threshold = 20, options = {}) {
  const asOf = typeof options === 'string' ? options : options?.asOf || null;
  const state = historyState(row?.history, threshold, asOf);
  // Watchlist names are explicit non-members, measured like members.
  const inUniverse = row?.in_universe !== false || row?.membership === 'watchlist';

  if (!inUniverse) {
    return {
      status: MONITOR_STATUSES.OUTSIDE_UNIVERSE,
      inUniverse: false,
      ...state,
    };
  }

  if (state.currentQualifies === null) {
    return {
      status: MONITOR_STATUSES.UNKNOWN,
      inUniverse: true,
      ...state,
    };
  }

  if (state.currentQualifies) {
    if (state.previousDate === null) {
      return { status: MONITOR_STATUSES.BASELINE, inUniverse: true, ...state };
    }
    if (state.previousValue !== null && qualifies(state.previousValue, threshold)) {
      // A known qualifying state remains continuing across an unknown gap. It
      // is never relabelled as a fresh entry merely because coverage was null.
      return { status: MONITOR_STATUSES.CONTINUING, inUniverse: true, ...state };
    }
    if (!state.unknownGap && state.previousValue !== null) {
      return { status: MONITOR_STATUSES.NEWLY_ENTERED, inUniverse: true, ...state };
    }
    return { status: MONITOR_STATUSES.BASELINE, inUniverse: true, ...state };
  }

  if (!state.unknownGap && state.previousValue !== null && qualifies(state.previousValue, threshold)) {
    return { status: MONITOR_STATUSES.EXITED, inUniverse: true, ...state };
  }
  return { status: MONITOR_STATUSES.OUTSIDE, inUniverse: true, ...state };
}

/** A history-only convenience for tests and small consumers. */
export function deriveHistoryStatus(history, threshold = 20, options = {}) {
  return derivePoolStatus({ in_universe: true, history }, threshold, options);
}

/**
 * Attach derived status to each artifact row.  The input rows are not mutated;
 * the raw row remains available as `row` for provenance/detail views.
 */
export function deriveMonitorRows(data, threshold = 20, followed = []) {
  const follows = new Set(normalizeFollowList(followed));
  const asOf = data?.as_of || null;
  return (Array.isArray(data?.rows) ? data.rows : []).map((row) => ({
    ...row,
    row,
    followed: follows.has(normalizeTicker(row?.ticker)),
    ...derivePoolStatus(row, threshold, { asOf }),
  }));
}

function comparableValue(view, key) {
  if (key === 'name' || key === 'sector' || key === 'ticker') return view?.row?.[key];
  if (key === 'in_universe') return view?.inUniverse;
  if (key === 'status') return STATUS_ORDER.get(view?.status) ?? Number.POSITIVE_INFINITY;
  if (key === 'followed') return view?.followed;
  if (Object.prototype.hasOwnProperty.call(view || {}, key)) return view[key];
  return view?.row?.[key];
}

function missing(value) {
  return value === null || value === undefined || value === ''
    || (typeof value === 'number' && Number.isNaN(value));
}

/** Stable null-last sorting for the renderer's sortable table. */
export function sortMonitorRows(rows, key, direction = 'asc') {
  const descending = direction === 'desc' || direction === -1;
  return [...(Array.isArray(rows) ? rows : [])]
    .map((row, index) => ({ row, index, value: comparableValue(row, key) }))
    .sort((left, right) => {
      const leftMissing = missing(left.value);
      const rightMissing = missing(right.value);
      if (leftMissing && rightMissing) return left.index - right.index;
      if (leftMissing) return 1;
      if (rightMissing) return -1;
      let result;
      if (typeof left.value === 'string' || typeof right.value === 'string') {
        result = String(left.value).localeCompare(String(right.value));
      } else if (typeof left.value === 'boolean' || typeof right.value === 'boolean') {
        result = Number(left.value) - Number(right.value);
      } else {
        result = left.value - right.value;
      }
      if (result === 0) return left.index - right.index;
      return descending ? -result : result;
    })
    .map(({ row }) => row);
}

/** Apply mode, sector, and free-text filters without changing raw rows. */
export function filterMonitorRows(rows, options = {}) {
  const mode = options.mode || 'queue';
  const sector = String(options.sector || '').trim().toLowerCase();
  const search = String(options.search || '').trim().toLowerCase();
  const quadrant = options.quadrant || '';
  return (Array.isArray(rows) ? rows : []).filter((view) => {
    const modeMatch = mode === 'following'
      ? view.followed
      : mode === 'all'
        ? true
        : inQueue(view);
    if (!modeMatch) return false;
    if (quadrant && quadrantOf(view.row) !== quadrant) return false;

    const rowSector = String(view.row?.sector || '').toLowerCase();
    if (sector && rowSector !== sector) return false;
    if (!search) return true;
    const haystack = [view.row?.ticker, view.row?.name, view.row?.sector, view.status]
      .filter((value) => value !== null && value !== undefined)
      .join(' ')
      .toLowerCase();
    return haystack.includes(search);
  });
}

/**
 * In the research queue at the selected drawdown threshold: past it, or
 * lagging sector peers by the build's margin. A manual exclude hides a name
 * from the queue (it stays under ALL, with its reason).
 */
export function inQueue(view) {
  const row = view?.row || view || {};
  if (row.membership === 'removed' || row.note?.status === 'exclude') return false;
  const peerLaggard = Array.isArray(row.reasons) && row.reasons.includes('peer_laggard');
  return view?.currentQualifies === true || peerLaggard;
}

// Price state x evidence state. A 2x2 of facts, not a ranking: none of the
// four boxes is the "buy" box.
export const QUADRANTS = Object.freeze([
  { key: 'weak-steady', label: 'PRICE WEAK · EVIDENCE STEADY' },
  { key: 'weak-other', label: 'PRICE WEAK · EVIDENCE WEAKER / UNKNOWN' },
  { key: 'stabilising-steady', label: 'STABILISING · EVIDENCE STEADY' },
  { key: 'stabilising-other', label: 'STABILISING · EVIDENCE WEAKER / UNKNOWN' },
]);

export function quadrantOf(row) {
  const price = row?.price_state;
  if (price !== 'weak' && price !== 'stabilising') return null;
  return `${price}-${row?.evidence_state === 'steady' ? 'steady' : 'other'}`;
}

const CHANGE_ORDER = [
  'entered', 'first_observed', 'stabilising', 'evidence_down', 'reported',
  'weakening', 'evidence_up', 'evidence_unknown', 'left', 'left_index',
];

export const CHANGE_LABELS = Object.freeze({
  entered: 'ENTERED THE QUEUE',
  first_observed: 'FIRST OBSERVED (ALREADY IN THE QUEUE)',
  stabilising: 'STABILISING',
  evidence_down: 'EVIDENCE WEAKER',
  reported: 'REPORTED',
  weakening: 'STABILISATION FAILED',
  evidence_up: 'EVIDENCE NO LONGER AGAINST',
  evidence_unknown: 'ESTIMATES WENT STALE',
  left: 'LEFT THE QUEUE',
  left_index: 'LEFT THE INDEX',
});

/**
 * Transitions recorded in a row's state log on the artifact date. Used for
 * browser-local follows, which the build cannot see. On the session the
 * price-state rule changed, a weak/stabilising flip is the rule, not a move.
 */
export function logChanges(row, asOf, { priceRuleChanged = false } = {}) {
  const log = Array.isArray(row?.state_log) ? row.state_log : [];
  const last = log[log.length - 1];
  const prev = log[log.length - 2];
  if (!last || !prev || last[0] !== asOf) return [];
  const out = [];
  const add = (kind, text) => out.push({
    ticker: row.ticker, sector: row.sector ?? null, anomaly: row.anomaly ?? null, kind, text,
  });
  if (priceRuleChanged) {
    // re-labelled, not moved
  } else if (prev[2] === 'weak' && last[2] === 'stabilising') {
    add('stabilising', 'Gaining on its peers over the month and the close is back above its average');
  } else if (prev[2] === 'stabilising' && last[2] === 'weak') {
    add('weakening', 'Stabilisation failed');
  }
  if (last[3] === 'deteriorating' && prev[3] && prev[3] !== 'deteriorating') {
    add('evidence_down', (row.evidence_against || []).join('; '));
  } else if (last[3] === 'steady' && prev[3] === 'deteriorating') {
    add('evidence_up', (row.evidence_for || []).join('; '));
  }
  return out;
}

/** The build's changes plus followed names' own transitions, grouped by kind. */
export function todayChanges(data, followed = []) {
  const follows = new Set(normalizeFollowList(followed));
  const rows = Array.isArray(data?.rows) ? data.rows : [];
  const excluded = new Set(rows.filter((row) => row?.note?.status === 'exclude').map((row) => row.ticker));
  const changes = (Array.isArray(data?.changes) ? data.changes : []).filter((c) => !excluded.has(c.ticker));
  const seen = new Set(changes.map((c) => `${c.ticker}:${c.kind}`));
  for (const row of rows) {
    if (!follows.has(normalizeTicker(row?.ticker)) || excluded.has(row.ticker)) continue;
    for (const change of logChanges(row, data?.as_of, { priceRuleChanged: data?.price_rule_changed === true })) {
      if (!seen.has(`${change.ticker}:${change.kind}`)) changes.push({ ...change, followed: true });
    }
  }
  const groups = new Map();
  for (const change of changes) {
    if (!groups.has(change.kind)) groups.set(change.kind, []);
    groups.get(change.kind).push(change);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (CHANGE_ORDER.indexOf(a) + 1 || 99) - (CHANGE_ORDER.indexOf(b) + 1 || 99))
    .map(([kind, items]) => ({ kind, label: CHANGE_LABELS[kind] || kind.toUpperCase(), items }));
}

export function monitorCoverage(rows) {
  const universeRows = (Array.isArray(rows) ? rows : [])
    .filter((row) => row.inUniverse && row.row?.membership !== 'watchlist');
  const unknown = universeRows.filter((row) => row.status === MONITOR_STATUSES.UNKNOWN).length;
  const pool = universeRows.filter((row) => row.currentQualifies === true).length;
  return {
    universe: universeRows.length,
    known: universeRows.length - unknown,
    unknown,
    pool,
    newlyEntered: universeRows.filter((row) => row.status === MONITOR_STATUSES.NEWLY_ENTERED).length,
    exited: universeRows.filter((row) => row.status === MONITOR_STATUSES.EXITED).length,
  };
}

export function normalizeTicker(value) {
  if (typeof value !== 'string') return null;
  const ticker = value.trim().toUpperCase();
  return TICKER_RE.test(ticker) ? ticker : null;
}

export function normalizeFollowList(value) {
  const values = value instanceof Set ? [...value] : Array.isArray(value) ? value : [];
  return [...new Set(values.map(normalizeTicker).filter(Boolean))].sort();
}

function invalidTickers(values) {
  return values
    .filter((value) => normalizeTicker(value) === null)
    .map((value) => String(value));
}

/** Validate an exported/local follow payload without mutating storage. */
export function validateFollowPayload(payload, { allowBareArray = false } = {}) {
  let values;
  if (Array.isArray(payload)) {
    if (!allowBareArray) {
      return { ok: false, error: 'follow data must include a tickers array' };
    }
    values = payload;
  } else if (payload && typeof payload === 'object') {
    const version = payload.schema_version ?? payload.version;
    if (version !== undefined && Number(version) !== FOLLOW_SCHEMA_VERSION) {
      return { ok: false, error: `unsupported follow data schema_version ${version}` };
    }
    if (payload.kind !== undefined && payload.kind !== FOLLOW_KIND) {
      return { ok: false, error: `unexpected follow data kind ${payload.kind}` };
    }
    if (payload.exported_at !== undefined) {
      if (typeof payload.exported_at !== 'string') {
        return { ok: false, error: 'exported_at must be an ISO timestamp' };
      }
      const datePart = payload.exported_at.slice(0, 10);
      if (!isDate(datePart) || Number.isNaN(Date.parse(payload.exported_at))) {
        return { ok: false, error: `invalid exported_at ${payload.exported_at}` };
      }
    }
    values = payload.tickers;
  }
  if (!Array.isArray(values)) return { ok: false, error: 'follow data tickers must be an array' };
  const invalid = invalidTickers(values);
  if (invalid.length) {
    return { ok: false, error: `invalid ticker${invalid.length === 1 ? '' : 's'}: ${invalid.join(', ')}` };
  }
  return { ok: true, tickers: normalizeFollowList(values) };
}

export function createFollowPayload(tickers, exportedAt = null) {
  const payload = {
    schema_version: FOLLOW_SCHEMA_VERSION,
    kind: FOLLOW_KIND,
    tickers: normalizeFollowList(tickers),
  };
  if (exportedAt) payload.exported_at = exportedAt;
  return payload;
}

export function serializeFollowList(tickers, exportedAt = new Date().toISOString()) {
  return JSON.stringify(createFollowPayload(tickers, exportedAt), null, 2);
}

export function parseFollowImport(raw) {
  let payload;
  try {
    payload = typeof raw === 'string' ? JSON.parse(raw) : raw;
  } catch (error) {
    return { ok: false, error: `invalid JSON: ${error.message}` };
  }
  return validateFollowPayload(payload, { allowBareArray: true });
}

export function mergeFollowLists(...lists) {
  return normalizeFollowList(lists.flatMap((list) => (
    list instanceof Set ? [...list] : Array.isArray(list) ? list : []
  )));
}

function defaultStorage() {
  try {
    return typeof globalThis !== 'undefined' ? globalThis.localStorage || null : null;
  } catch {
    return null;
  }
}

/** Read localStorage while distinguishing unavailable storage from bad JSON. */
export function loadFollowState(storage = defaultStorage(), key = FOLLOW_STORAGE_KEY) {
  if (!storage || typeof storage.getItem !== 'function') {
    return { status: 'unavailable', tickers: [], raw: null, error: 'browser storage is unavailable' };
  }
  let raw;
  try {
    raw = storage.getItem(key);
  } catch (error) {
    return { status: 'unavailable', tickers: [], raw: null, error: error.message };
  }
  if (raw === null || raw === undefined || raw === '') {
    return { status: 'ok', tickers: [], raw: null, missing: true };
  }
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (error) {
    return { status: 'corrupt', tickers: [], raw, error: `invalid JSON: ${error.message}` };
  }
  const validation = validateFollowPayload(payload);
  if (!validation.ok) return { status: 'corrupt', tickers: [], raw, error: validation.error };
  return { status: 'ok', tickers: validation.tickers, raw, missing: false };
}

/**
 * Save only over a valid/missing record.  A corrupt record is left untouched
 * unless the caller explicitly opts into repair, so a failed parse can never
 * be silently replaced by a follow click.
 */
export function saveFollowState(storage = defaultStorage(), key = FOLLOW_STORAGE_KEY, tickers, options = {}) {
  const validation = validateFollowPayload({ tickers });
  if (!validation.ok) return { ok: false, status: 'invalid', error: validation.error };
  const current = loadFollowState(storage, key);
  if (current.status !== 'ok' && !options.allowRepair) {
    return { ok: false, status: current.status, error: current.error };
  }
  if (!storage || typeof storage.setItem !== 'function') {
    return { ok: false, status: 'unavailable', error: 'browser storage is unavailable' };
  }
  try {
    storage.setItem(key, JSON.stringify(createFollowPayload(validation.tickers)));
    return { ok: true, status: 'ok', tickers: validation.tickers };
  } catch (error) {
    return { ok: false, status: 'unavailable', error: error.message };
  }
}
