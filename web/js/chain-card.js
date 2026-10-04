// One company's place in the AI chain (CATALYSTS -> AI CHAIN, and the
// TICKER page): who it buys from, sells to and competes with; how each of
// them has reported this season; and how its stock has answered their
// reports before. Built by the CHAIN panel.

import { el, card, num, pct, tag, table, dirClass, DASH } from './fmt.js';
import { tickerHref } from './routes.js';

export const ROLE_LABEL = { supplier: 'SUPPLIER', customer: 'CUSTOMER', competitor: 'COMPETITOR', partner: 'PARTNER' };
const ROLE_TONE = { supplier: 'info', customer: 'up', competitor: 'warn', partner: 'dim' };
const ROLE_ORDER = { supplier: 0, customer: 1, partner: 2, competitor: 3 };
const STRENGTH = {
  stated: ['FILING STATES IT', 'up'],
  // The sentence is picked automatically: only one that states the tie in
  // so many words is called that; the rest just name the other company.
  relationship: ['NAMED IN FILING', 'info'],
  mention: ['NAMED IN FILING', 'dim'],
  group: ['CUSTOMERS NOT NAMED', 'dim'],
  unverified: ['NOT IN SEC FILINGS', 'dim'],
};
// From here a surprise is a near-zero EPS base or a one-off gain, not a size;
// the study clips at the same point.
const SURPRISE_CAP = 50;

export function surpriseText(value) {
  if (value === null || value === undefined) return DASH;
  if (Math.abs(value) >= SURPRISE_CAP) return `${value > 0 ? '≥+' : '≤−'}${SURPRISE_CAP}%`;
  return pct(value, 1);
}

export function nodeHref(node) {
  return node.site ? tickerHref(node.key) : `#chain/${encodeURIComponent(node.key)}`;
}

// Every company linked to `key`, once each, with its role seen from `key`
// and the edge that makes it so (a supply link before a rivalry).
export function linksOf(chain, key) {
  const out = new Map();
  for (const e of chain.edges || []) {
    let other = null;
    let role = null;
    if (e.from === key) {
      other = e.to;
      role = e.type === 'supplies' ? 'customer' : e.type === 'partner' ? 'partner' : 'competitor';
    } else if (e.to === key) {
      other = e.from;
      role = e.type === 'supplies' ? 'supplier' : e.type === 'partner' ? 'partner' : 'competitor';
    }
    if (!other) continue;
    const prior = out.get(other);
    if (!prior || ROLE_ORDER[role] < ROLE_ORDER[prior.role]) out.set(other, { key: other, role, edge: e });
  }
  return [...out.values()].sort((a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || a.key.localeCompare(b.key));
}

function statText(s) {
  if (!s) return DASH;
  return `β ${num(s.beta, 2)} · t ${num(s.t, 1)} · ${s.n}`;
}

function statCell(s) {
  const strong = s && s.t !== null && s.t !== undefined && Math.abs(s.t) >= 2;
  return el('td', {
    class: `num ${strong ? (s.beta > 0 ? 'up' : 'down') : 'dim'}`,
    text: statText(s),
    title: s ? `on ${s.n} reports since ${s.since}: moved ${num(s.beta, 2)}% per 1% of the reporter's own move beyond its index; `
      + `same direction ${Math.round((s.hit || 0) * 100)}% of the time; t ${num(s.t, 1)}`
      + (s.drift_signed !== null && s.drift_signed !== undefined ? `; until its own next report it drifted ${num(s.drift_signed, 1)} pp further the reporter's way` : '')
      : 'fewer than 8 shared reports',
  });
}

function seasonText(node) {
  const r = node?.season?.reported;
  if (r) return `${r.date} · EPS ${surpriseText(r.surprise)} · ${pct(r.move, 1)}`;
  if (node?.next) return `next ${node.next.date}${node.next.estimated ? ' (est.)' : ''}`;
  return DASH;
}

function evidenceNode(e) {
  const ev = e.evidence || {};
  const [label, tone] = STRENGTH[ev.strength] || STRENGTH.unverified;
  const title = ev.text ? `${ev.filer} ${ev.form} (${ev.filed}): “${ev.text}”` : (ev.strength === 'group'
    ? `the link is to the ${e.group} as a group: its filings speak of cloud customers without naming them`
    : 'neither company\'s 10-K / 20-F of the last three years names the other');
  const t = tag(label, tone, title);
  return ev.url ? el('a', { href: ev.url, target: '_blank', rel: 'noopener', title }, [t]) : t;
}

// The table of a company's links, with how each has moved it.
export function linksTable(chain, key, { limit = null } = {}) {
  const nodes = new Map((chain.nodes || []).map((n) => [n.key, n]));
  // Within a role, the links whose reports have moved this stock most firmly first.
  const firm = (l) => { const s = l.edge.stats?.[`${l.key}>${key}`]; return s && s.t !== null && s.t !== undefined ? s.t : -Infinity; };
  let links = linksOf(chain, key).sort((a, b) => ROLE_ORDER[a.role] - ROLE_ORDER[b.role] || firm(b) - firm(a));
  if (limit) links = links.slice(0, limit);
  const rows = links.map((l) => {
    const other = nodes.get(l.key) || { key: l.key, name: l.key };
    const stats = l.edge.stats || {};
    return el('tr', {}, [
      el('td', { class: 'chain-who' }, [el('a', { href: nodeHref(other), text: other.name || other.key }),
        el('span', { class: 'dim', text: ` ${other.key}${other.market && other.market !== 'US' ? ` · ${other.market}` : ''}` }),
        el('div', { class: 'chain-why dim', text: l.edge.reason })]),
      el('td', {}, [tag(ROLE_LABEL[l.role], ROLE_TONE[l.role])]),
      el('td', { class: other.season?.reported ? dirClass(other.season.reported.move) : 'dim', text: seasonText(other) }),
      statCell(stats[`${l.key}>${key}`]),
      statCell(stats[`${key}>${l.key}`]),
      el('td', {}, [evidenceNode(l.edge)]),
    ]);
  });
  return table(['COMPANY · WHY', 'ROLE', 'THIS SEASON', 'ITS REPORTS MOVE THIS', 'THIS MOVES IT', 'EVIDENCE'], rows,
    { class: 'text-cols chain-links' });
}

function heardTable(chain, node) {
  const heard = node.season?.heard || [];
  if (!heard.length) return null;
  const names = new Map((chain.nodes || []).map((n) => [n.key, n.name]));
  const role = { from_customer: 'CUSTOMER', from_supplier: 'SUPPLIER', competitor: 'COMPETITOR', partner: 'PARTNER' };
  return table(['SESSION', 'REPORTED', 'ROLE', 'ITS EPS', 'ITS MOVE', `${node.key} MOVE`],
    heard.map((h) => el('tr', {}, [
      el('td', { text: h.day }),
      el('td', { text: names.get(h.lead) || h.lead }),
      el('td', { class: 'dim', text: role[h.category] || h.category }),
      el('td', { class: dirClass(h.lead_surprise), text: surpriseText(h.lead_surprise) }),
      el('td', { class: dirClass(h.lead_move), text: pct(h.lead_move, 1) }),
      el('td', { class: dirClass(h.move), text: pct(h.move, 1) }),
    ])), { class: 'text-cols' });
}

// A one-paragraph read of where the company stands in the season.
export function seasonLine(chain, node) {
  const s = node.season || {};
  const label = chain.season?.label || 'this season';
  const parts = [];
  if (s.reported) {
    parts.push(`${label}: reported ${s.reported.date}, EPS ${surpriseText(s.reported.surprise)} vs consensus, `
      + `${pct(s.reported.move, 1)} beyond its index on the session.`);
  } else {
    parts.push(`${label}: not reported yet${node.next ? `; next report ${node.next.date}${node.next.estimated ? ' (estimated)' : ''}` : ''}.`);
  }
  const before = (s.heard || []).filter((h) => !s.reported || h.day <= s.reported.date);
  if (s.read_in !== null && s.read_in !== undefined && before.length) {
    const sessions = new Set(before.map((h) => h.day)).size;
    parts.push(`Before its own report it moved ${pct(s.read_in, 1)} in all on the ${sessions} sessions its linked companies' reports traded.`);
  }
  return parts.join(' ');
}

export function chainCard(chain, key, { compact = false } = {}) {
  const node = (chain?.nodes || []).find((n) => n.key === key);
  if (!node) return null;
  const layer = (chain.layers || []).find((l) => l.key === node.layer);
  const head = el('span', { class: 'tag-row' }, [
    tag(layer ? layer.label : node.layer, 'info'),
    el('a', { href: `#chain/${encodeURIComponent(key)}`, class: 'tag tag-dim', text: 'AI CHAIN →' }),
  ]);
  const heard = compact ? null : heardTable(chain, node);
  return card(`AI CHAIN · ${node.name}`, head, [
    el('div', { class: 'note-text', text: seasonLine(chain, node) }),
    linksTable(chain, key),
    el('div', { class: 'field-note', text: 'ITS REPORTS MOVE THIS: on each past report of the linked company, this stock\'s move beyond its own index '
      + 'on the first session it traded the news, per 1% of the reporter\'s own move (β), its t, and the reports counted; THIS MOVES IT the other way round. '
      + 'Coloured where |t| ≥ 2. Hover a cell or an evidence tag for the detail.' }),
    heard ? el('div', { class: 'card-title', text: 'LINKED REPORTS THIS SEASON' }) : null,
    heard,
  ]);
}
