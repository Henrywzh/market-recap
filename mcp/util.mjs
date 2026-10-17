// Small helpers the adapters share. Nothing here knows about any one panel.

export const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

// A finite number or null: an artifact's missing value stays missing.
export const finite = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export function pick(source, keys) {
  const out = {};
  keys.forEach((key) => { out[key] = source && source[key] !== undefined ? source[key] : null; });
  return out;
}

// The first `limit` items and how many were left out, so a client knows the
// list was cut and can ask for the rest with narrower arguments.
export function capList(list, limit) {
  const all = Array.isArray(list) ? list : [];
  return { items: all.slice(0, limit), more: Math.max(0, all.length - limit) };
}

export const last = (list) => (Array.isArray(list) && list.length ? list[list.length - 1] : null);

// The last non-null value of a series, with its date.
export function latestPoint(dates, values) {
  if (!Array.isArray(values)) return null;
  for (let i = values.length - 1; i >= 0; i -= 1) {
    if (finite(values[i]) !== null) return { date: dates?.[i] ?? null, value: values[i] };
  }
  return null;
}

export const text = (value, max = 400) => {
  if (typeof value !== 'string') return null;
  const clean = value.replace(/\s+/g, ' ').trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
};

// Today's date in New York, the clock the calendar and the sessions use.
export function newYorkDate(now = new Date()) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
}

export function addDays(isoDate, days) {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export const ISO_DATE = '^\\d{4}-\\d{2}-\\d{2}$';
