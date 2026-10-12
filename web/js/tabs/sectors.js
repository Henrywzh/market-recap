// SECTORS: one hub for the market, its eleven GICS sectors, their sub-industries
// and the names in each. The hash argument picks the page: none is the market
// (#sectors), a sector's SPDR fund is a sector (#sectors/XLP), and a
// sub-industry's key is its page (#sectors/XLP-SDNB). The rotation graph and
// its valuation sit under the market, where they were a page of their own.
// The figures come from sectors.json; sectors-model.js reads them.

import { el, card, table, num, pct, dirClass, metaRow, sectionTitle, periodSwitch, tag, gap, DASH } from '../fmt.js';
import { tickerHref, hashFor } from '../routes.js';
import renderRotation from './rotation.js';
import { themeBlocks } from './themes.js';
import {
  PERIODS, DEFAULT_PERIOD, REPORT_WINDOW_DAYS, levelOf, membersOf, subsOf, sortRows, upcoming,
  timingLabel, timingTitle, quadrantTag, evidenceFlags, extremesOf, themedSubs, ordinal, boolMark, nameColumns,
} from '../sectors-model.js';

const THIN_TITLE = 'fewer than 5 names: medians are fragile';
const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits = 1, unit = '') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${unit}` : DASH);
const share = (v, digits = 1) => (present(v) ? `${num(v, digits)}%` : DASH);
const multiple = (v) => (present(v) ? `${num(v, 1)}×` : DASH);
const sectorHref = (key) => `#${hashFor('sectors', key)}`;
const themeHref = (key) => `#${hashFor('themes', String(key).toUpperCase())}`;
const markTone = (v) => (v === true ? 'up' : v === false ? 'down' : 'dim');

// A link inside a clickable row keeps its own destination: the row ignores it.
function link(text, href, className = null) {
  return el('a', { href, class: className, text });
}

function go(ctx, id, arg) {
  if (ctx.navigate) ctx.navigate(id, arg);
  else location.hash = `#${hashFor(id, arg)}`;
}

// A table row that opens a sector or sub-industry page when clicked.
function openRow(cells, ctx, key, title) {
  return el('tr', {
    class: 'sx-row',
    title,
    onclick: (event) => {
      if (!event.target.closest('a')) go(ctx, 'sectors', key);
    },
  }, cells);
}

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`.trim(), text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function strip(cells) {
  return el('div', { class: 'stat-strip sx-stats' }, cells);
}

// The period every return on the page reads: one switch, shared by the strip,
// the sub-industry table and the names table.
function periodControls(state, onPick) {
  return el('div', { class: 'sx-controls' }, [
    el('span', { class: 'dim', text: 'PERIOD' }),
    periodSwitch(PERIODS, state.period, (p) => {
      state.period = p;
      onPick();
    }),
  ]);
}

function crumbs(parts) {
  return el('nav', { class: 'sx-crumbs', 'aria-label': 'Breadcrumb' }, parts.flatMap((part, i) => [
    i ? el('span', { class: 'sx-sep', text: '›' }) : null,
    part.href ? link(part.label, part.href) : el('span', { class: 'sx-here', text: part.label, 'aria-current': 'page' }),
  ]));
}

function subLabelOf(data) {
  return Object.fromEntries((data.sub_industries || []).map((s) => [s.key, s.label]));
}

function performanceCells(row, period, { bench = null, fund = null, quadrant = null }) {
  const ret = row.returns?.[period];
  const vs = row.vs_index?.[period];
  const rev = row.revision || {};
  const cells = [
    stat(`RETURN · ${period}`, pct(ret, 1), bench ? `S&P 500 ${pct(bench[period], 1)}` : null, dirClass(ret)),
    stat(`VS S&P 500 · ${period}`, signed(vs, 1, ' pp'), 'percentage points, this less the index', dirClass(vs)),
  ];
  if (fund) cells.push(stat(`FUND · ${period}`, pct(fund[period], 1), 'the SPDR fund, for comparison', dirClass(fund[period])));
  if (quadrant) {
    cells.push(stat('ROTATION', quadrant.label, 'where it sits on the rotation graph',
      quadrant.tone === 'up' || quadrant.tone === 'down' ? quadrant.tone : ''));
  }
  cells.push(
    stat('ABOVE 200-DAY', share(row.above_200d, 0), 'share of its names above their 200-day average'),
    stat('MEDIAN DRAWDOWN', pct(row.median_drawdown, 1), 'the median name, from its 1-year high', dirClass(row.median_drawdown)),
    stat('EPS REVISIONS · 90D', pct(rev['90d'], 1), `30 days ${pct(rev['30d'], 1)} · ${rev.names ?? DASH} names`, dirClass(rev['90d'])),
  );
  return cells;
}

// The forward P/E is the median of the names; the sector's own P/E now against
// its ten years (valuation aggregates) and, for Financials, P/TBV when present.
function valuationCells(row, { valuation = null, showPtbv = false }) {
  const pctl = present(row.pe_percentile)
    ? `${ordinal(row.pe_percentile)} percentile of its own ten years`
    : 'too little history to place it';
  const cells = [stat('FORWARD P/E · MEDIAN', multiple(row.forward_pe), pctl)];
  if (valuation) {
    const now = valuation.pe_now;
    const median = valuation.pe_median_10y;
    const vs = present(now) && present(median) && median !== 0 ? ` · ${signed((now / median - 1) * 100, 0, '%')} now` : '';
    cells.push(stat('P/E NOW', multiple(now), `10-year median ${multiple(median)}${vs}`));
  }
  if (showPtbv) {
    const now = valuation?.ptbv_now;
    const median = valuation?.ptbv_median_10y;
    cells.push(stat('P/TBV NOW', multiple(now), present(median) ? `10-year median ${multiple(median)}` : 'kept for the bank groups only: on their sub-industry pages'));
  }
  return cells;
}

// The evidence flags as tags, then the best and worst names over three months.
function flagsLine(row, extremes) {
  const flags = evidenceFlags(row.evidence).map((f) => tag(f.text, f.tone, f.title));
  const name = (label, pick) => (pick ? el('span', { class: 'sx-extreme' }, [
    el('span', { class: 'dim', text: `${label} 3M ` }),
    link(pick.ticker, tickerHref(pick.ticker)),
    ` ${signed(pick.return, 1, '%')}`,
  ]) : null);
  return el('div', { class: 'sx-flags' }, [...flags, name('BEST', extremes?.best), name('WORST', extremes?.worst)]);
}

function nextCell(m) {
  const next = m.next_report;
  if (!next?.date) return el('td', { class: 'dim', text: DASH });
  const label = timingLabel(next.timing);
  return el('td', { title: timingTitle(next.timing) }, [next.date, label ? el('span', { class: 'dim', text: ` ${label}` }) : null]);
}

function nameCell(key, m, period, subLabel) {
  switch (key) {
    case 'ticker': return el('td', {}, [link(m.ticker, tickerHref(m.ticker), 'sx-ticker')]);
    case 'name': return el('td', { class: 'wrap-cell', text: m.name || DASH });
    case 'sub': return el('td', {}, [link(subLabel[m.sub_key] || m.sub_key, sectorHref(m.sub_key))]);
    case 'weight': return el('td', { text: share(m.weight, 2) });
    case 'ret': return el('td', { class: dirClass(m.returns?.[period]), text: pct(m.returns?.[period], 1) });
    case 'y1': return el('td', { class: dirClass(m.returns?.['1Y']), text: pct(m.returns?.['1Y'], 1) });
    case 'high': return el('td', { class: dirClass(m.drawdown), text: pct(m.drawdown, 1) });
    case 'a200': return el('td', { class: markTone(m.above_200d), text: boolMark(m.above_200d) });
    case 'rev': return el('td', { class: dirClass(m.revision_90d), text: pct(m.revision_90d, 1) });
    case 'pe': return el('td', { text: multiple(m.forward_pe) });
    case 'pctl': return el('td', { class: 'dim', text: ordinal(m.pe_percentile) });
    case 'ptbv': return el('td', { text: multiple(m.ptbv) });
    case 'ptbvPctl': return el('td', { class: 'dim', text: ordinal(m.ptbv_percentile) });
    case 'next': return nextCell(m);
    case 'monitor': return el('td', {}, [m.monitor?.queued === true ? tag('QUEUED', 'warn', 'the monitor has queued this name') : DASH]);
    default: return el('td', {});
  }
}

// The names of a sector or a sub-industry, sortable by any column. The sort
// state lives with the page, so a period change keeps the reader's order.
function namesCard(members, state, { withSub, financials, subLabel, title }) {
  const wrap = el('div', { class: 'table-scroll' });
  const draw = () => {
    if (!members.length) {
      wrap.replaceChildren(el('div', { class: 'dim', text: 'No names.' }));
      return;
    }
    const cols = nameColumns(state.period, { withSub, financials, subLabel });
    if (!cols.some((c) => c.key === state.sort.key)) state.sort = { key: 'weight', direction: 'desc' };
    const col = cols.find((c) => c.key === state.sort.key);
    const head = el('tr', {}, cols.map((c) => {
      const active = state.sort.key === c.key;
      const arrow = active ? (state.sort.direction === 'desc' ? ' ▼' : ' ▲') : '';
      return el('th', { 'aria-sort': active ? (state.sort.direction === 'desc' ? 'descending' : 'ascending') : null }, [
        el('button', {
          type: 'button',
          class: 'sx-sort',
          text: c.label + arrow,
          onclick: () => {
            state.sort = { key: c.key, direction: active ? (state.sort.direction === 'desc' ? 'asc' : 'desc') : c.first };
            draw();
          },
        }),
      ]);
    }));
    const rows = sortRows(members, col.get, state.sort.direction).map((m) => el('tr', {},
      cols.map((c) => nameCell(c.key, m, state.period, subLabel))));
    wrap.replaceChildren(el('table', { class: 'data sx-names' }, [el('thead', {}, [head]), el('tbody', {}, rows)]));
  };
  draw();
  return {
    node: card(title, el('span', { class: 'dim', text: 'heaviest first · click a column to sort' }), [
      wrap,
      el('div', { class: 'field-note', text: 'A missing figure sits last whichever way the column runs. ✓ and ✗ are the names above and below their 200-day average.' }),
    ]),
    draw,
  };
}

function reportsCard(members, asOf) {
  const list = upcoming(members, asOf, REPORT_WINDOW_DAYS);
  const weeks = REPORT_WINDOW_DAYS / 7;
  const body = list.length
    ? table(['DATE', 'TICKER', 'TIMING', 'WEIGHT'], list.map((m) => el('tr', {}, [
      el('td', { text: m.next_report.date }),
      el('td', {}, [link(m.ticker, tickerHref(m.ticker), 'sx-ticker')]),
      el('td', { class: 'dim', title: timingTitle(m.next_report.timing), text: timingLabel(m.next_report.timing) || DASH }),
      el('td', { text: share(m.weight, 2) }),
    ])))
    : el('div', { class: 'field-note', text: `No member reports in the next ${weeks} weeks.` });
  return card(`REPORTS IN THE NEXT ${weeks} WEEKS`, el('span', { class: 'dim', text: `${list.length} names after ${asOf}` }), [body]);
}

// The sector's or sub-industry's THEMES group, drawn in full beneath the page.
async function industryData(host, themeKey, subThemes, ctx) {
  host.append(sectionTitle('INDUSTRY DATA', themeKey ? `from THEMES · ${themeKey.toUpperCase()}` : 'on sub-industry pages'));
  if (subThemes.length) {
    host.append(el('div', { class: 'sx-theme-line' }, [
      el('span', { class: 'dim', text: 'Industry data on sub-industry pages: ' }),
      ...subThemes.flatMap((s, i) => [
        i ? el('span', { class: 'dim', text: ' · ' }) : null,
        link(s.label, sectorHref(s.key)),
        ' → ',
        link(s.theme.toUpperCase(), themeHref(s.theme), 'tag tag-info'),
      ]),
    ]));
  }
  if (!themeKey) return;
  const body = el('div', {});
  host.append(body);
  try {
    const themes = await ctx.loadArtifact('themes');
    const blocks = themeBlocks(themeKey, themes, { title: false });
    body.replaceChildren(...(blocks.length ? blocks : [gap(`The THEMES page has no group called ${themeKey} in this build.`)]));
  } catch (error) {
    body.replaceChildren(gap(`Industry data is unavailable: ${error.message}.`));
  }
}

function sectorTable(data, state, ctx) {
  const period = state.period;
  const rows = sortRows(data.sectors, 'weight', 'desc').map((s) => {
    const ret = s.returns?.[period];
    const vs = s.vs_index?.[period];
    const q = quadrantTag(s.quadrant);
    const rev = s.revision || {};
    return openRow([
      el('td', {}, [el('span', { class: 'sx-name', text: s.label }), el('span', { class: 'sub', text: `${s.etf} · ${s.members} names` })]),
      el('td', { text: share(s.weight, 1) }),
      el('td', { class: dirClass(ret), text: pct(ret, 1) }),
      el('td', { class: dirClass(vs), text: signed(vs, 1, ' pp') }),
      el('td', {}, [q ? tag(q.label, q.tone) : DASH]),
      el('td', { text: share(s.above_200d, 0) }),
      el('td', { class: dirClass(s.median_drawdown), text: pct(s.median_drawdown, 1) }),
      el('td', { class: dirClass(rev['90d']), text: pct(rev['90d'], 1) }),
      el('td', { text: multiple(s.forward_pe) }),
      el('td', { class: 'dim', text: ordinal(s.pe_percentile) }),
      el('td', {}, [s.theme ? link(s.theme.toUpperCase(), themeHref(s.theme), 'tag tag-info') : DASH]),
    ], ctx, s.key, `${s.label} · ${s.members} names · ${share(s.weight)} of the index`);
  });
  return table(['SECTOR', 'WEIGHT', 'RETURN', 'VS S&P', 'ROTATION', 'ABOVE 200D', 'MEDIAN DRAWDOWN', 'EPS REV 90D', 'FWD P/E', 'P/E PCTL', 'THEME'], rows);
}

function subTable(subs, state, ctx) {
  const period = state.period;
  const rows = subs.map((s) => {
    const ret = s.returns?.[period];
    const vs = s.vs_index?.[period];
    const rev = s.revision || {};
    return openRow([
      el('td', {}, [link(s.label, sectorHref(s.key)), s.thin ? ' ' : null, s.thin ? tag('THIN', 'dim', THIN_TITLE) : null]),
      el('td', { text: String(s.members) }),
      el('td', { text: share(s.weight, 2) }),
      el('td', { class: dirClass(ret), text: pct(ret, 1) }),
      el('td', { class: dirClass(vs), text: signed(vs, 1, ' pp') }),
      el('td', { text: share(s.above_200d, 0) }),
      el('td', { class: dirClass(s.median_drawdown), text: pct(s.median_drawdown, 1) }),
      el('td', { class: dirClass(rev['90d']), text: pct(rev['90d'], 1) }),
      el('td', { text: multiple(s.forward_pe) }),
      el('td', { class: 'dim', text: ordinal(s.pe_percentile) }),
      el('td', {}, [s.theme ? link(s.theme.toUpperCase(), themeHref(s.theme), 'tag tag-info') : DASH]),
    ], ctx, s.key, `${s.label} · ${s.members} names`);
  });
  return table(['SUB-INDUSTRY', 'NAMES', 'WEIGHT', 'RETURN', 'VS S&P', 'ABOVE 200D', 'MEDIAN DRAWDOWN', 'EPS REV 90D', 'FWD P/E', 'P/E PCTL', 'THEME'], rows);
}

function hubNotes(data) {
  const noPe = data.sectors.filter((s) => !present(s.forward_pe)).map((s) => s.label);
  return [
    'Market, then sector, then sub-industry, then names. A sector is one SPDR fund\'s GICS group of the S&P 500; a row opens it, and each sector page opens its sub-industries and their names.',
    'Returns are cap-weighted from the names\' heat-map returns. VS S&P is the sector\'s return less the index\'s over the same period, in percentage points. A theme tag opens the THEMES page for that group.',
    'ABOVE 200D is the share of names above their 200-day average. MEDIAN DRAWDOWN is the median name\'s fall from its 1-year high. EPS REV 90D is the median change in FY1 EPS consensus over 90 days.',
    'FWD P/E is the median name\'s forward multiple. P/E PCTL is where the current figure sits within its own ten years of history.',
    noPe.length ? `No forward P/E in this build for: ${noPe.join(', ')}.` : null,
    ...(data.notes || []),
  ];
}

function sectorNotes(sector) {
  return [
    'Returns and the S&P comparison are cap-weighted, from the names\' heat-map returns. VS S&P is the difference in percentage points. FUND is the SPDR fund\'s own return, for comparison.',
    'Medians are of the names. ABOVE 200D is the share above their 200-day average. P/E PCTL is where the current figure sits within its own ten years of history.',
    'NEXT REPORT: BMO reports before the open, AMC after the close, TBC has a date but no confirmed time of day. QUEUED marks a name the monitor has queued.',
    present(sector.forward_pe) ? null : 'This sector has no forward P/E in this build.',
  ];
}

// The market: every sector in one table, then the cross-sector themes, then the
// rotation graph and the sector valuation the page held before.
async function renderHub(root, data, manifest, ctx) {
  const state = { period: DEFAULT_PERIOD, sort: { key: 'weight', direction: 'desc' } };
  const thin = data.sub_industries.filter((s) => s.thin).length;
  root.append(sectionTitle('SECTORS', 'MARKET → SECTOR → SUB-INDUSTRY → NAMES'));
  root.append(metaRow(`AS OF ${data.as_of} · ${data.sectors.length} SECTORS · ${data.sub_industries.length} SUB-INDUSTRIES, ${thin} THIN · ${data.members.length} NAMES`, hubNotes(data)));

  const tableHost = el('div');
  const draw = () => tableHost.replaceChildren(sectorTable(data, state, ctx));
  root.append(card(`${data.sectors.length} SECTORS`, periodSwitch(PERIODS, state.period, (p) => {
    state.period = p;
    draw();
  }), [tableHost]));
  draw();

  if ((data.themes || []).length) {
    root.append(card('CROSS-SECTOR THEMES', el('span', { class: 'dim', text: `${data.themes.length} · not one sector` }), [
      el('div', { class: 'field-note', text: 'A theme that spans sectors: its names also appear on their own sector pages.' }),
      ...data.themes.map((t) => el('div', { class: 'sx-theme' }, [
        el('div', { class: 'sx-theme-head' }, [
          link(t.label, themeHref(t.key), 'sx-theme-name'),
          t.proxy ? el('span', { class: 'dim', text: t.proxy }) : null,
        ]),
        el('div', { class: 'tag-row' }, (t.members || []).map((sym) => link(sym, tickerHref(sym), 'tag tag-dim'))),
      ])),
    ]));
  }

  // The rotation page, as the market's own section. Its charts draw on the
  // next frame, so the host must be in the page first.
  const rotationHost = el('div', { class: 'sectors-rotation' });
  root.append(rotationHost);
  try {
    const rotation = await ctx.loadArtifact('rotation');
    await renderRotation(rotationHost, rotation, manifest, ctx);
  } catch (error) {
    rotationHost.replaceChildren(gap(`The rotation page is unavailable: ${error.message}.`));
  }
}

async function renderSector(root, data, _manifest, ctx, sector) {
  const state = { period: DEFAULT_PERIOD, sort: { key: 'weight', direction: 'desc' } };
  const subs = subsOf(data, sector.key);
  const members = membersOf(data, { sectorKey: sector.key });
  const subLabel = subLabelOf(data);
  const financials = sector.key === 'XLF';
  const valuation = sector.valuation || null;
  const showPtbv = financials || present(valuation?.ptbv_now);

  root.append(crumbs([{ label: 'SECTORS', href: '#sectors' }, { label: sector.label }]));
  root.append(sectionTitle(sector.label.toUpperCase(), `${sector.etf} · ${share(sector.weight, 2)} OF THE S&P 500 · ${sector.members} NAMES`));
  root.append(metaRow(`AS OF ${data.as_of} · ${subs.length} SUB-INDUSTRIES, ${subs.filter((s) => s.thin).length} THIN`, sectorNotes(sector)));

  const perfHost = el('div');
  const subsHost = el('div');
  const drawPerf = () => perfHost.replaceChildren(strip(performanceCells(sector, state.period, {
    bench: data.benchmark?.returns,
    fund: sector.etf_returns,
    quadrant: quadrantTag(sector.quadrant),
  })));
  const drawSubs = () => subsHost.replaceChildren(subTable(subs, state, ctx));
  const names = namesCard(members, state, { withSub: true, financials, subLabel, title: `NAMES · ${members.length}` });
  const redraw = () => {
    drawPerf();
    drawSubs();
    names.draw();
  };
  drawPerf();
  drawSubs();
  root.append(
    periodControls(state, redraw),
    perfHost,
    strip(valuationCells(sector, { valuation, showPtbv })),
    flagsLine(sector, { best: sector.best, worst: sector.worst }),
    card(`SUB-INDUSTRIES · ${subs.length}`, el('span', { class: 'dim', text: 'heaviest first · click a row' }), [subsHost]),
    names.node,
    reportsCard(members, data.as_of),
  );

  const subThemes = themedSubs(data, sector.key);
  if (sector.theme || subThemes.length) {
    const section = el('div', { class: 'sx-industry' });
    root.append(section);
    await industryData(section, sector.theme, subThemes, ctx);
  }
}

async function renderSub(root, data, _manifest, ctx, sub) {
  const state = { period: DEFAULT_PERIOD, sort: { key: 'weight', direction: 'desc' } };
  const sector = data.sectors.find((s) => s.key === sub.sector_key) || null;
  const sectorLabel = sector?.label || sub.sector;
  const members = membersOf(data, { subKey: sub.key });
  const extremes = members.length > 1 ? extremesOf(members, '3M') : null;

  root.append(crumbs([
    { label: 'SECTORS', href: '#sectors' },
    { label: sectorLabel, href: sectorHref(sub.sector_key) },
    { label: sub.label },
  ]));
  root.append(sectionTitle(sub.label.toUpperCase(), `${sectorLabel} · ${share(sub.weight, 2)} OF THE S&P 500 · ${sub.members} NAMES`));
  root.append(metaRow(`AS OF ${data.as_of} · ${sub.key} · ${sub.members} names in this sub-industry`, [
    'Medians are of the names; a sub-industry with fewer than five is thin, and its medians move with any one name.',
    'Returns are cap-weighted from the names\' heat-map returns. VS S&P is the difference in percentage points.',
  ]));
  if (sub.thin) {
    root.append(el('div', { class: 'sx-flags' }, [tag('THIN', 'warn', THIN_TITLE), el('span', { class: 'dim', text: THIN_TITLE })]));
  }

  const perfHost = el('div');
  const drawPerf = () => perfHost.replaceChildren(strip(performanceCells(sub, state.period, { bench: data.benchmark?.returns })));
  const financials = sub.sector_key === 'XLF';
  const names = namesCard(members, state, {
    withSub: false, financials, subLabel: {}, title: `NAMES · ${members.length}`,
  });
  drawPerf();
  root.append(
    periodControls(state, () => {
      drawPerf();
      names.draw();
    }),
    perfHost,
    strip(valuationCells(sub, { valuation: sub.valuation || null, showPtbv: present(sub.valuation?.ptbv_now) })),
    flagsLine(sub, extremes),
    names.node,
    reportsCard(members, data.as_of),
  );

  if (sub.theme) {
    const section = el('div', { class: 'sx-industry' });
    root.append(section);
    await industryData(section, sub.theme, [], ctx);
  }
}

export default async function renderSectors(root, data, manifest, ctx = {}) {
  if (!data || !Array.isArray(data.sectors) || !Array.isArray(data.members) || !Array.isArray(data.sub_industries)) {
    root.append(gap('No sector data in this build. Run the refresh command to rebuild it.'));
    return;
  }
  const found = levelOf(ctx.arg, data);
  if (found.level === 'sector') return renderSector(root, data, manifest, ctx, found.sector);
  if (found.level === 'sub') return renderSub(root, data, manifest, ctx, found.sub);
  if (found.level === 'unknown') {
    root.append(gap(`There is no sector or sub-industry called ${ctx.arg} in this build. The sectors are below.`));
  }
  return renderHub(root, data, manifest, ctx);
}
