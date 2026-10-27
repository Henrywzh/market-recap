// Pure helpers for the STRESS COUNT card: how a vote, a group and the count are
// worded. No DOM, so the rules are tested in node. The build decides every vote;
// this only describes it. An unknown vote is never worded as "off".

const OPS = { gt: 'above', lt: 'below', le: 'at or below' };
const UNIT_SUFFIX = { pct: '%', pp: ' pts', pts: '', index: '' };

const fixed = (value, digits) => Number(value).toFixed(digits);

function reading(value, unit) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const digits = unit === 'pp' || unit === 'index' ? 2 : 1;
  const text = fixed(value, digits);
  return `${text}${UNIT_SUFFIX[unit] ?? ''}`;
}

// "VIX 22.4 · line: above 25". Unknown: "no reading".
export function voteReading(vote) {
  if (vote.on === null || vote.on === undefined) return 'no reading';
  return `${reading(vote.value, vote.unit)} · line: ${OPS[vote.op] ?? vote.op} ${reading(vote.threshold, vote.unit)}`;
}

// 'on' | 'off' | 'unknown'
export function voteState(vote) {
  if (vote.on === true) return 'on';
  if (vote.on === false) return 'off';
  return 'unknown';
}

// "1 of 2 on", or "1 of 1 known on · 1 unknown" when an input is missing.
export function groupText(group) {
  const unknown = group.total - group.known;
  if (group.known === 0) return 'no reading';
  const base = `${group.on} of ${group.known} on`;
  return unknown > 0 ? `${base} · ${unknown} unknown` : base;
}

// Tone of a group: any vote on is a stressed group; all known off is calm; none known is grey.
export function groupTone(group) {
  if (group.known === 0) return 'dim';
  return group.on > 0 ? 'down' : 'up';
}

// The headline: the raw count out of the votes, or the known part when a vote is missing.
export function countText(stress) {
  if (stress.raw !== null && stress.raw !== undefined) return `${stress.raw} of ${stress.total} on`;
  if (!stress.known) return 'no reading';
  return `${stress.on_known} of ${stress.known} known on`;
}

// Where the count stands against the reference line written in config. A description, not a call.
export function referenceText(stress) {
  if (stress.raw === null || stress.raw === undefined || !stress.reference) return null;
  return stress.raw >= stress.reference
    ? `At or above the reference line of ${stress.reference}`
    : `Below the reference line of ${stress.reference}`;
}

// "1 week ago: 3 · now 5 (+2)"; null when the week-ago count is unknown.
export function changeText(stress) {
  if (stress.raw === null || stress.raw === undefined) return null;
  if (stress.week_ago === null || stress.week_ago === undefined) return null;
  const d = stress.raw - stress.week_ago;
  const sign = d > 0 ? '+' : d < 0 ? '−' : '±';
  return `1 week ago: ${stress.week_ago} · now ${stress.raw} (${sign}${Math.abs(d)})`;
}

// The oldest date the count's own history covers with a real count, for the chart caption.
export function firstKnown(history) {
  const at = (history?.raw ?? []).findIndex((v) => v !== null && v !== undefined);
  return at < 0 ? null : history.dates[at];
}

// Dates where an input's last real observation is older than the page's session: for the stale footnote.
export function staleInputs(stress, days = 10) {
  const asOf = Date.parse(stress.as_of);
  if (!Number.isFinite(asOf)) return [];
  const out = [];
  for (const g of stress.groups ?? []) {
    for (const v of g.votes) {
      const seen = v.as_of ? Date.parse(v.as_of) : NaN;
      if (Number.isFinite(seen) && (asOf - seen) / 86400000 > days) out.push({ key: v.key, label: v.label, as_of: v.as_of });
    }
  }
  return out;
}
