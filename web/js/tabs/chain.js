// AI CHAIN (under CATALYSTS): the AI supply chain from IP and tools to the
// clouds, how its reporting season is going, and what a report has carried
// along it before. Built by the CHAIN panel; the study is over today's graph
// applied to every past report, and says so.

import { el, card, num, pct, tag, table, dirClass, sectionTitle, gap, metaRow, periodSwitch, DASH } from '../fmt.js';
import { chainCard, linksOf, nodeHref, surpriseText, ROLE_LABEL } from '../chain-card.js';
import { drawGraph, attachClicks, graphHeight } from '../chain-graph.js';
import { layersCard } from '../chain-layers.js';

const PERIODS = { ALL: 'all', 'SINCE 2023': 'recent' };
const CATEGORY_ORDER = ['from_customer', 'from_supplier', 'competitor', 'partner', 'unlinked'];
const CATEGORY_SHORT = {
  from_customer: 'CUSTOMER → SUPPLIER',
  from_supplier: 'SUPPLIER → CUSTOMER',
  competitor: 'COMPETITOR',
  partner: 'PARTNER',
  unlinked: 'NO LINK (BASELINE)',
};

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function seasonStrip(data) {
  const s = data.season || {};
  const nodes = data.nodes || [];
  // The next report anywhere in the chain: late in a season it opens the next one.
  const upcoming = nodes.filter((n) => n.next).sort((a, b) => a.next.date.localeCompare(b.next.date));
  const first = upcoming[0];
  return el('div', { class: 'stat-strip' }, [
    stat('SEASON', s.label || DASH, s.start ? `${s.start} → ${s.end}` : null),
    stat('REPORTED', `${s.reported ?? 0} / ${s.companies ?? nodes.length}`, 'companies in the chain'),
    stat('BEAT / MISSED', `${s.beat ?? 0} / ${s.missed ?? 0}`, 'EPS against consensus', (s.beat || 0) >= (s.missed || 0) ? 'up' : 'down'),
    stat('NEXT UP', first ? first.name : DASH, first ? `${first.next.date}${first.next.estimated ? ' (est.)' : ''}` : 'none dated'),
  ]);
}

function chip(node, state) {
  const r = node.season?.reported;
  const cls = ['chain-chip'];
  if (state.selected === node.key) cls.push('selected');
  const role = state.roles.get(node.key);
  if (role) cls.push(`role-${role}`);
  if (state.selected && !role && state.selected !== node.key) cls.push('faded');
  if (r) cls.push((r.surprise ?? 0) > 0 ? 'beat' : (r.surprise ?? 0) < 0 ? 'missed' : 'reported');
  const status = r
    ? [el('span', { class: dirClass(r.surprise), text: `EPS ${surpriseText(r.surprise)}` }), ' ',
      el('span', { class: dirClass(r.move), text: pct(r.move, 1) })]
    : [el('span', { class: 'dim', text: node.next ? `next ${node.next.date.slice(5)}` : 'no date' })];
  return el('button', {
    type: 'button', class: cls.join(' '), onclick: () => state.pick(node.key),
    title: `${node.name} (${node.key}, ${node.market})${role ? ` · ${ROLE_LABEL[role]} of ${state.selected}` : ''}`,
  }, [
    el('div', { class: 'chain-chip-name', text: node.name }),
    el('div', { class: 'chain-chip-key dim', text: `${node.key}${node.market !== 'US' ? ` · ${node.market}` : ''}` }),
    el('div', { class: 'chain-chip-status' }, status),
  ]);
}

// The view the reader last chose, kept in this browser only.
const MODE_KEY = 'chain-view';
const WIDE_PX = 900;

function savedMode() {
  try {
    const mode = localStorage.getItem(MODE_KEY);
    if (mode === 'BOARD' || mode === 'GRAPH') return mode;
  } catch { /* storage refused: fall through to the default */ }
  return window.innerWidth >= WIDE_PX ? 'GRAPH' : 'BOARD';
}

function saveMode(mode) {
  try { localStorage.setItem(MODE_KEY, mode); } catch { /* not kept; fine */ }
}

function boardColumns(data, state) {
  const byLayer = new Map((data.layers || []).map((l) => [l.key, []]));
  (data.nodes || []).forEach((n) => byLayer.get(n.layer)?.push(n));
  return el('div', { class: 'chain-board' }, (data.layers || []).map((l) => el('div', { class: 'chain-col' }, [
    el('div', { class: 'chain-col-head', text: l.label }),
    ...(byLayer.get(l.key) || []).map((n) => chip(n, state)),
  ])));
}

function graphView(data, state) {
  const canvas = el('div', { class: 'chain-graph', style: `height:${graphHeight(data)}px` });
  requestAnimationFrame(() => {
    state.chart = drawGraph(canvas, data, state);
    attachClicks(state.chart, state);
  });
  return el('div', { class: 'chain-graph-scroll' }, [canvas]);
}

function board(data, state) {
  const legend = el('div', { class: 'tag-row chain-legend' }, [
    el('span', { class: 'stat-label', text: 'THIS SEASON' }),
    tag('BEAT', 'up'), tag('MISSED', 'down'), tag('NOT YET', 'dim'),
    el('span', { class: 'stat-label', text: state.selected ? `LINKS OF ${state.selected}` : 'PICK A COMPANY' }),
    tag('SUPPLIER', 'info'), tag('CUSTOMER', 'up'), tag('COMPETITOR', 'warn'), tag('PARTNER', 'dim'),
  ]);
  const note = state.mode === 'GRAPH' ? el('div', { class: 'field-note', text: state.selected
    ? 'Every link of the company picked: line width is how firmly one side\'s reports have moved the other (|t|), dashed below 2; arrows follow the goods. Hover a line for the numbers and the filing; click a company to move to it, the same company again to clear.'
    : 'With nothing picked, only the backbone: links where one side\'s reports have moved the other with t ≥ 3. Click a company for all its links.' }) : null;
  const toggle = periodSwitch(['GRAPH', 'BOARD'], state.mode, (mode) => { state.mode = mode; saveMode(mode); state.redraw(); });
  return card('THE CHAIN', toggle, [legend, note, state.mode === 'GRAPH' ? graphView(data, state) : boardColumns(data, state)]);
}

function studyCell(value, digits, unit = '') {
  return el('td', { class: `num ${dirClass(value)}`, text: value === null || value === undefined ? DASH : `${num(value, digits)}${unit}` });
}

function tCell(t) {
  const strong = t !== null && t !== undefined && Math.abs(t) >= 2;
  return el('td', { class: `num ${strong ? 'strong' : 'dim'}`, text: t === null || t === undefined ? DASH : num(t, 1) });
}

function studyRows(block, question) {
  return CATEGORY_ORDER.filter((c) => block[c]).map((c) => {
    const v = block[c];
    const cells = [el('td', { class: c === 'unlinked' ? 'dim' : '', text: CATEGORY_SHORT[c], title: v.label })];
    if (question === 'immediate') {
      const q = v.immediate;
      cells.push(studyCell(q.mean, 2, ' pp'), tCell(q.t), studyCell(q.rank_corr, 2), el('td', { class: 'num', text: q.same_way_pct === null ? DASH : `${q.same_way_pct}%` }),
        el('td', { class: 'num dim', text: `${q.reports} / ${q.pairs}` }),
        studyCell(v.named_only?.rank_corr, 2));
    } else if (question === 'fundamental') {
      const q = v.fundamental;
      cells.push(el('td', { class: 'num', text: q.follow_beat_after_beat_pct === null ? DASH : `${q.follow_beat_after_beat_pct}%` }),
        el('td', { class: 'num', text: q.follow_beat_after_miss_pct === null ? DASH : `${q.follow_beat_after_miss_pct}%` }),
        el('td', { class: 'num dim', text: q.follow_beat_pct === null ? DASH : `${q.follow_beat_pct}%` }),
        studyCell(q.rank_corr, 2), el('td', { class: 'num dim', text: `${q.after_beat} / ${q.after_miss}` }));
    } else if (question === 'drift') {
      const q = v.drift;
      cells.push(studyCell(q.mean, 2, ' pp'), tCell(q.t), studyCell(q.after_up, 1, ' pp'), studyCell(q.after_down, 1, ' pp'),
        el('td', { class: 'num dim', text: `${q.reports} / ${q.pairs}` }));
    } else {
      const q = v.priced_in || {};
      cells.push(studyCell(q.rank_corr, 2), studyCell(q.beat_reaction_low_read_in, 2, '%'), studyCell(q.beat_reaction_high_read_in, 2, '%'),
        studyCell(q.beat_rank_corr, 2), el('td', { class: 'num dim', text: `${q.reports ?? 0}` }));
    }
    return el('tr', {}, cells);
  });
}

const QUESTIONS = [
  ['immediate', '1 · SAME SESSION', 'Did the linked company move the reporter\'s way on the first session it traded the report?',
    ['LINK', 'MEAN, SIGNED', 't', 'RANK ρ', 'SAME WAY', 'REPORTS / PAIRS', 'ρ NAMED LINKS ONLY']],
  ['fundamental', '2 · ITS OWN NEXT REPORT', 'When the reporter beat (or missed) consensus, how often did the linked company beat at its own next report, within 100 days?',
    ['LINK', 'BEAT AFTER A BEAT', 'BEAT AFTER A MISS', 'BEAT, ANY', 'SURPRISE RANK ρ', 'AFTER BEAT / MISS']],
  ['drift', '3 · DRIFT UNTIL ITS OWN REPORT', 'From the session after, to the eve of its own report: did it keep going the reporter\'s way?',
    ['LINK', 'MEAN, SIGNED', 't', 'AFTER AN UP MOVE', 'AFTER A DOWN MOVE', 'REPORTS / PAIRS']],
  ['priced_in', '4 · PRICED IN BEFORE ITS OWN REPORT', 'Its summed moves on its links\' report sessions in the 90 days before its own report (the read-in), against its own reaction.',
    ['LINK', 'READ-IN ρ REACTION', 'BEAT: REACTION, LOW READ-IN', 'BEAT: REACTION, HIGH READ-IN', 'BEAT: ρ', 'ITS REPORTS']],
];

// Plain sentences from the numbers, against the no-link baseline: what the
// table says without reading every cell.
function readings(block) {
  const base = block.unlinked;
  if (!base) return [];
  const out = [];
  const same = (c) => block[c]?.immediate;
  const fmt = (q) => `ρ ${num(q.rank_corr, 2)}, ${num(q.mean, 2)} pp`;
  const linked = ['competitor', 'from_customer', 'from_supplier'].filter((c) => same(c));
  if (linked.length) {
    out.push(`Same session: ${linked.map((c) => `${CATEGORY_SHORT[c].toLowerCase()} ${fmt(same(c))}`).join('; ')} — against ${fmt(base.immediate)} for two chain companies with no link at all, which is what the whole chain shares.`
      + (block.from_customer?.named_only ? ` Links a filing names: customer → supplier ρ ${num(block.from_customer.named_only.rank_corr, 2)}.` : ''));
  }
  const drifts = linked.map((c) => block[c].drift).filter((q) => q && q.t !== null);
  if (drifts.length) {
    const any = drifts.some((q) => Math.abs(q.t) >= 2);
    out.push(any ? 'Drift: at least one kind of link kept moving the reporter\'s way until its own report (|t| ≥ 2) — see table 3.'
      : 'Drift: no kind of link kept moving the reporter\'s way after the first session (every |t| < 2) — the read-through is traded on the day.');
  }
  const f = block.competitor?.fundamental;
  if (f && f.follow_beat_after_beat_pct !== null && f.follow_beat_after_miss_pct !== null) {
    out.push(`Own next report: a competitor beat ${f.follow_beat_after_beat_pct}% of the time after a beat and ${f.follow_beat_after_miss_pct}% after a miss (any: ${f.follow_beat_pct}%); `
      + `across customer and supplier links the gap is ${block.from_customer ? `${block.from_customer.fundamental.follow_beat_after_beat_pct}% vs ${block.from_customer.fundamental.follow_beat_after_miss_pct}%` : DASH}.`);
  }
  const p = block.from_customer?.priced_in;
  if (p && p.rank_corr !== null && p.rank_corr !== undefined) {
    out.push(`Priced in: a supplier's run-up on its customers' report days and its own reaction to its report correlate at ρ ${num(p.rank_corr, 2)}`
      + `${p.beat_reaction_low_read_in !== undefined ? ` (after a beat: ${pct(p.beat_reaction_low_read_in, 1)} with the smallest run-ups, ${pct(p.beat_reaction_high_read_in, 1)} with the largest)` : ''}.`);
  }
  return out;
}

function studyCard(study) {
  const host = el('div', {});
  let period = 'ALL';
  const draw = () => {
    host.replaceChildren();
    const block = study.categories?.[PERIODS[period]] || {};
    if (!Object.keys(block).length) {
      host.append(gap('No pairs in this window.'));
      return;
    }
    const lines = readings(block);
    if (lines.length) host.append(el('ul', { class: 'evidence-list' }, lines.map((text) => el('li', { text }))));
    QUESTIONS.forEach(([key, title, question, headers]) => {
      host.append(el('div', { class: 'card-title', text: title }), el('div', { class: 'field-note', text: question }));
      host.append(table(headers, studyRows(block, key), { class: 'chain-study' }));
    });
  };
  draw();
  const toggle = periodSwitch(Object.keys(PERIODS), period, (p) => { period = p; draw(); });
  return card('WHAT A REPORT HAS CARRIED · STUDY', toggle, [
    el('div', { class: 'note-text', text: `Every report since ${study.since || DASH}, paired with every other company in the chain. `
      + 'Today\'s graph is applied to every year (a link formed in 2024 counts in 2016), so this is how the chain as drawn today has behaved, not point-in-time evidence. '
      + 'Moves are beyond each company\'s own market index; t-statistics are across reports (a report\'s pairs averaged first), so one report never counts many times.' }),
    host,
  ]);
}

function edgesCard(data) {
  const host = el('div', {});
  const nodes = new Map((data.nodes || []).map((n) => [n.key, n]));
  const kinds = { ALL: null, SUPPLIES: 'supplies', COMPETES: 'competes', PARTNER: 'partner' };
  let kind = 'ALL';
  const draw = () => {
    host.replaceChildren();
    const rows = (data.edges || []).filter((e) => !kinds[kind] || e.type === kinds[kind]);
    host.append(table(['FROM', 'TYPE', 'TO', 'WHY', 'EVIDENCE', 'FILING SAYS'], rows.map((e) => {
      const ev = e.evidence || {};
      const a = nodes.get(e.from) || { key: e.from, name: e.from };
      const b = nodes.get(e.to) || { key: e.to, name: e.to };
      return el('tr', {}, [
        el('td', {}, [el('a', { href: nodeHref(a), text: a.name })]),
        el('td', { class: 'dim', text: e.type }),
        el('td', {}, [el('a', { href: nodeHref(b), text: b.name })]),
        el('td', { class: 'wrap-cell dim', text: e.reason }),
        el('td', {}, [ev.url ? el('a', { href: ev.url, target: '_blank', rel: 'noopener', text: `${ev.filer} ${ev.form} ${ev.filed}` })
          : el('span', { class: 'dim', text: ev.strength === 'group' ? `${e.group}, not named` : 'not in SEC filings' })]),
        el('td', { class: 'wrap-cell dim chain-quote', text: ev.text ? `“${ev.text}”` : '' }),
      ]);
    }), { class: 'text-cols' }));
  };
  draw();
  const toggle = periodSwitch(Object.keys(kinds), kind, (k) => { kind = k; draw(); });
  return card(`EVERY LINK · ${(data.edges || []).length}`, toggle, [
    el('div', { class: 'field-note', text: `Checked ${data.evidence_checked || DASH} against both companies' 10-K / 20-F / 40-F filings of the last three years: `
      + 'the sentence that names the other company. A link to "the hyperscalers" is one the filings make without naming them; one between two companies outside SEC filing is the graph\'s own.' }),
    host,
  ]);
}

export default async function renderChain(root, data, _manifest, ctx = {}) {
  root.append(sectionTitle('AI CHAIN', 'WHO SELLS TO WHOM, AND WHAT A REPORT CARRIES'));
  if (!data?.nodes?.length) {
    root.append(gap('The chain is not in this build.'));
    return;
  }
  root.append(metaRow(`AS OF ${data.as_of} · ${data.nodes.length} COMPANIES · ${data.edges.length} LINKS · ${Object.keys(data.markets || {}).length} MARKETS`, [
    'The graph is hand-kept (config/ai_chain.toml): supplies, competes or partner, each with its reason and, where either company files with the SEC, the sentence of its annual report that names the other.',
    'Reports: Yahoo\'s earnings archive (to mid-2025, with the time of day) and its last four quarters, Korean preliminary results from DART, and for a US filer the SEC release\'s day and timing. One quarter (reports of July–September 2025) is missing for companies outside SEC filing.',
    'Each company is priced on its home exchange against its home index (S&P 500, KOSPI, TAIEX, Nikkei 225, AEX, CAC 40, DAX). A report is traded by each market\'s first session that closes after it came out: an NVIDIA report after New York\'s close is Seoul\'s and Tokyo\'s next morning, then New York\'s next day.',
    'Nothing here is scored or a signal; the study says how the chain has behaved, with its denominators.',
  ]));
  root.append(seasonStrip(data));
  const wanted = ctx.arg && data.nodes.some((n) => n.key === ctx.arg) ? ctx.arg : null;
  const host = el('div', {});
  const state = { selected: wanted, roles: new Map(), mode: savedMode() };
  state.pick = (key) => {
    state.selected = state.selected === key ? null : key;
    ctx.setArg?.(state.selected);
    draw();
  };
  const draw = () => {
    state.redraw = draw;
    // The last graph is dropped before its node leaves the page.
    if (state.chart && !state.chart.isDisposed()) state.chart.dispose();
    state.chart = null;
    state.roles = new Map(state.selected ? linksOf(data, state.selected).map((l) => [l.key, l.role]) : []);
    host.replaceChildren(board(data, state));
    const detail = state.selected ? chainCard(data, state.selected) : null;
    host.append(detail || el('div', { class: 'field-note', text: 'Pick a company to see its suppliers, customers and competitors, how each reported this season, and how they have moved it before.' }));
  };
  root.append(host);
  draw();
  const layers = layersCard(data);
  if (layers) root.append(layers);
  root.append(studyCard(data.study || {}));
  root.append(edgesCard(data));
}
