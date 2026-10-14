// INDUSTRIES: each sub-industry and sector as the median of its names. A section of
// the SECTORS view (rotation.js draws it), not a view of its own.
//
// ROTATION shows how a group moved against the index, cap-weighted, so a few
// large names speak for it. This view reads the typical member and puts the
// evidence beside the move: how many names fell, the drawdown, the share above
// the long average, the FY1 EPS revisions and the P/E against its own ten years.
// Evidence is listed, never scored; a tag appears only where a reading crosses
// a threshold the build took from config.

import { el, table, num, pct, dirClass, sectionTitle, notice, metaRow, periodSwitch, tag, DASH } from '../fmt.js';
import { tickerHref, hashFor } from '../routes.js';
import { LEVELS, FILTERS, applyFilters, sortRows, evidenceTags, sectorsOf } from '../industries-model.js';

const COLUMNS = [
  { key: 'label', label: 'GROUP' },
  { key: 'members', label: 'NAMES' },
  { key: 'weight', label: 'WT %' },
  { key: 'r1M', label: '1M' },
  { key: 'r3M', label: '3M' },
  { key: 'r6M', label: '6M' },
  { key: 'down_share', label: 'DOWN 1M %' },
  { key: 'drawdown', label: 'FROM 1Y HIGH' },
  { key: 'above_ma', label: '> MA %' },
  { key: 'rev30', label: 'EPS 30D' },
  { key: 'rev90', label: 'EPS 90D' },
  { key: 'forward_pe', label: 'FWD P/E' },
  { key: 'pe_percentile', label: 'P/E PCTL' },
  { key: 'evidence', label: 'EVIDENCE' },
];

const x = (value) => (value === null || value === undefined ? DASH : `${num(value, 1)}×`);
const whole = (value) => (value === null || value === undefined ? DASH : num(value, 0));

// A thin sub-industry (fewer names than the build's threshold) is left off the
// table: a median of so few names is noise, and its page is under SECTORS.
// Sectors are never hidden. `hidden` counts the thin rows the filter kept.
export function splitThin(rows, level) {
  if (level !== 'sub_industries') return { shown: rows, hidden: 0 };
  const shown = rows.filter((r) => !r.thin);
  return { shown, hidden: rows.length - shown.length };
}

function memberTable(row) {
  const rows = row.member_rows.map((m) => el('tr', {}, [
    el('td', {}, [el('a', { href: tickerHref(m.ticker), text: m.ticker }), el('span', { class: 'dim', text: ` ${m.name}` })]),
    el('td', { text: num(m.weight, 2) }),
    el('td', { class: dirClass(m.returns['1M']), text: pct(m.returns['1M'], 1) }),
    el('td', { class: dirClass(m.returns['3M']), text: pct(m.returns['3M'], 1) }),
    el('td', { class: dirClass(m.returns['6M']), text: pct(m.returns['6M'], 1) }),
    el('td', { text: m.drawdown === null ? DASH : pct(m.drawdown, 1) }),
    el('td', { text: m.above_ma === null ? DASH : (m.above_ma ? 'above' : 'below') }),
    el('td', { class: dirClass(m.revision['30d']), text: pct(m.revision['30d'], 1) }),
    el('td', { class: dirClass(m.revision['90d']), text: pct(m.revision['90d'], 1) }),
    el('td', { text: x(m.forward_pe) }),
    el('td', { text: whole(m.pe_percentile) }),
  ]));
  return table(['NAME', 'WT %', '1M', '3M', '6M', 'FROM 1Y HIGH', 'TREND', 'EPS 30D', 'EPS 90D', 'FWD P/E', 'P/E PCTL'], rows, { class: 'industries-members' });
}

function cells(row, settings, href) {
  const sold = row.evidence.sold_off === true;
  return [
    el('td', {}, [
      el(href ? 'a' : 'span', { href, text: row.label, onclick: href ? (event) => event.stopPropagation() : null, title: row.best ? `best ${row.best.ticker} ${pct(row.best.return, 1)} · worst ${row.worst.ticker} ${pct(row.worst.return, 1)}` : null }),
      row.thin ? el('span', { class: 'dim', text: ' thin', title: `fewer than ${settings.thin_below} names: a median of this few is noise` }) : null,
      row.kind === 'sub_industry' ? el('div', { class: 'dim', text: row.sector }) : null,
    ]),
    el('td', { text: String(row.members) }),
    el('td', { text: num(row.weight, 1) }),
    el('td', { class: dirClass(row.returns['1M']), text: pct(row.returns['1M'], 1) }),
    el('td', { class: dirClass(row.returns['3M']), text: pct(row.returns['3M'], 1) }),
    el('td', { class: dirClass(row.returns['6M']), text: pct(row.returns['6M'], 1) }),
    el('td', { class: sold ? 'down' : '', text: whole(row.down_share) }),
    el('td', { text: row.drawdown === null ? DASH : pct(row.drawdown, 1) }),
    el('td', { text: whole(row.above_ma) }),
    el('td', { class: dirClass(row.revision['30d']), text: pct(row.revision['30d'], 1) }),
    el('td', { class: dirClass(row.revision['90d']), text: pct(row.revision['90d'], 1) }),
    el('td', { text: x(row.forward_pe.median) }),
    el('td', { text: whole(row.pe_percentile.median) }),
    el('td', {}, evidenceTags(row, settings).map((t) => tag(t.text, t.tone, t.title))),
  ];
}

export default function renderIndustries(root, data, groups = null) {
  const settings = data.settings;
  root.append(sectionTitle('INDUSTRIES', 'MEDIAN MEMBER, WITH THE EVIDENCE BESIDE IT'));
  if ((data.missing || []).length) {
    root.append(notice(`${data.missing.map((m) => m.toUpperCase()).join(' and ')} did not build for this session, so the columns that come from `
      + 'it (drawdown, EPS revisions, forward P/E and its percentile) are empty. Nothing from another session is used in their place.'));
  }
  root.append(metaRow(
    `${data.index.label} · closes to ${data.as_of} · medians of each group's names, groups of ${settings.min_members}+ shown`,
    [
      `1M, 3M and 6M are the median member's return over ${data.windows['1M']}, ${data.windows['3M']} and ${data.windows['6M']} sessions, the same windows as SECTORS. `
        + `DOWN 1M is the share of names that fell. > MA is the share above their ${settings.ma_sessions}-session average.`,
      'FROM 1Y HIGH and the EPS columns come from MONITOR: the FY1 consensus EPS revision over 30 and 90 days, read only for names whose EPS is positive (a percentage off a loss is not a revision). '
        + 'FWD P/E and P/E PCTL come from VALUATION; the percentile is against the company\'s own ten years. Sectors in which P/E is not the multiple '
        + `(${settings.no_pe_sectors.join(', ')}) show neither.`,
      `Tags are evidence, not a verdict. SOLD OFF: median 1M at or below ${settings.sold_off_return_pct}% with at least ${Math.round(settings.sold_off_down_share * 100)}% of names down. `
        + `EST CUT / EST HELD: median revision below ${settings.estimates_cut_30d_pct}% (30d) or ${settings.estimates_cut_90d_pct}% (90d), or not. P/E LOW: percentile at or below ${settings.cheap_percentile}. `
        + 'Estimates cover this fiscal year only: a fall the estimates do not explain can still be a fall about the years after it.',
      `A sub-industry with fewer than ${settings.thin_below} names is thin and left off this table; its page is under SECTORS. ${groups ? 'Click a group name for its combined valuation / industry page; click elsewhere in the row to expand names.' : 'Click a group to see its names.'} Hover its name for its best and worst.`,
    ],
  ));

  const state = { level: 'sub_industries', filter: 'all', sector: '', sort: { key: 'r1M', descending: false }, open: new Set() };
  const levelSwitch = periodSwitch(LEVELS.map((l) => l.label), LEVELS[0].label, (label) => {
    state.level = LEVELS.find((l) => l.label === label).id;
    state.open.clear();
    draw();
  });
  const filterSwitch = periodSwitch(FILTERS.map((f) => f.label), FILTERS[0].label, (label) => {
    state.filter = FILTERS.find((f) => f.label === label).id;
    draw();
  });
  const sectorSelect = el('select', {}, [
    el('option', { value: '', text: 'All sectors' }),
    ...sectorsOf(data.sectors).map((s) => el('option', { value: s, text: s })),
  ]);
  sectorSelect.addEventListener('change', () => { state.sector = sectorSelect.value; draw(); });
  root.append(el('div', { class: 'field-row' }, [levelSwitch, filterSwitch, el('label', { class: 'field' }, [sectorSelect])]));

  const host = el('div', {});
  const thinLine = el('div', { class: 'field-note' });
  const note = el('div', { class: 'field-note' });
  root.append(host, thinLine, note);

  function draw() {
    const { shown, hidden } = splitThin(applyFilters(data[state.level], state), state.level);
    const rows = sortRows(shown, state.sort.key, state.sort.descending);
    thinLine.textContent = hidden
      ? `${hidden} thin sub-${hidden === 1 ? 'industry' : 'industries'} hidden (fewer than ${settings.thin_below} names): `
        + `${hidden === 1 ? 'its page is' : 'their pages are'} under SECTORS.`
      : '';
    const head = COLUMNS.map((c) => el('th', {
      text: c.label + (state.sort.key === c.key ? (state.sort.descending ? ' ▼' : ' ▲') : ''),
      style: c.key === 'evidence' ? null : 'cursor:pointer',
      onclick: c.key === 'evidence' ? null : () => {
        state.sort = { key: c.key, descending: state.sort.key === c.key ? !state.sort.descending : c.key === 'label' ? false : true };
        draw();
      },
    }));
    const body = [];
    rows.forEach((row) => {
      const id = `${row.kind}:${row.sector}:${row.label}`;
      const sector = groups?.sectors.find((s) => s.label === (row.kind === 'sector' ? row.label : row.sector));
      const group = row.kind === 'sector' ? sector : groups?.sub_industries.find((s) => s.label === row.label && s.sector_key === sector?.key);
      const href = group ? `#${hashFor('sectors', group.key)}` : null;
      const tr = el('tr', { class: row.member_rows ? 'clickable' : null, onclick: row.member_rows ? () => {
        if (state.open.has(id)) state.open.delete(id); else state.open.add(id);
        draw();
      } : null }, cells(row, settings, href));
      body.push(tr);
      if (row.member_rows && state.open.has(id)) {
        body.push(el('tr', {}, [el('td', { colspan: String(COLUMNS.length) }, [memberTable(row)])]));
      }
    });
    const node = el('table', { class: 'data industries' }, [el('thead', {}, [el('tr', {}, head)]), el('tbody', {}, body)]);
    host.replaceChildren(rows.length ? el('div', { class: 'table-scroll' }, node)
      : el('div', { class: 'gap', text: 'No group matches this filter.' }));
    const omitted = data.omitted;
    note.textContent = state.level === 'sub_industries' && omitted.groups
      ? `${omitted.names} names in ${omitted.groups} sub-industries with fewer than ${settings.min_members} names are in no row `
        + `(for example ${omitted.examples.slice(0, 4).join(', ')}); their sector's row still counts them.`
      : '';
  }
  draw();
}
