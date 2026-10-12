// EUROPE -> NAMES: the FTSE 100 and EURO STOXX 50 members and the named groups
// (luxury, UK financials): price, returns, distance from the 52-week high,
// moving averages and Yahoo's multiples, sortable, with the sector summary above.

import { el, card, table, num, pct, dirClass, metaRow, sectionTitle, periodSwitch, gap, DASH } from '../fmt.js';
import { priceText, multipleText, growthText, flagText, sortRows, NAME_COLUMNS, medianOf } from '../europe-model.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);

function sectorTable(sectors, periods) {
  const head = ['SECTOR', 'N', ...periods.filter((p) => ['1M', '3M', 'YTD', '1Y'].includes(p)).map((p) => `MEDIAN ${p}`), '>50D', 'MEDIAN FWD P/E'];
  const shown = periods.filter((p) => ['1M', '3M', 'YTD', '1Y'].includes(p));
  const rows = sectors.map((s) => el('tr', {}, [
    el('td', { text: s.sector }), el('td', { class: 'dim', text: String(s.n) }),
    ...shown.map((p) => el('td', { class: dirClass(s.median_returns[p]), text: pct(s.median_returns[p], 1) })),
    el('td', { text: present(s.above_50_share) ? `${num(s.above_50_share, 0)}%` : DASH }),
    el('td', { text: multipleText(s.median_forward_pe) }),
  ]));
  return card('BY SECTOR · MEDIAN OF THE NAMES', null, [table(head, rows)]);
}

function namesTable(names, group) {
  const state = { key: 'g', direction: 'desc', sector: 'ALL' };
  const body = el('tbody', {});
  const head = el('tr', {});
  const median = medianOf(names.map((n) => n.forward_pe));
  const draw = () => {
    const col = NAME_COLUMNS.find((c) => c.key === state.key) || NAME_COLUMNS[0];
    const rows = sortRows(names.filter((n) => state.sector === 'ALL' || n.sector === state.sector), col.get, state.direction);
    body.replaceChildren(...rows.map((r) => el('tr', {}, [
      el('td', {}, [el('b', { text: r.symbol })]),
      el('td', { class: 'wrap-cell', text: r.name }),
      el('td', { class: 'dim', title: r.sector_source || '', text: r.sector }),
      el('td', { title: r.first_price && r.first_price > '2021-01-01' ? `prices from ${r.first_price}` : '', text: priceText(r.last, r.currency) }),
      ...['1D', '1M', '3M', 'YTD', '1Y'].map((p) => el('td', { class: dirClass(r.returns?.[p]), text: pct(r.returns?.[p], p === '1D' ? 2 : 1) })),
      el('td', { class: dirClass(r.drawdown_pct), title: r.high_date ? `high ${r.high_date}` : '', text: pct(r.drawdown_pct, 1) }),
      el('td', { text: multipleText(r.forward_pe), title: present(r.forward_pe) && present(median) ? `group median ${num(median, 1)}×` : '' }),
      el('td', { class: 'dim', text: multipleText(r.trailing_pe) }),
      el('td', { class: dirClass(r.eps_growth), title: r.eps_growth_out_of_range ? 'off a profit near zero: not a growth rate' : '', text: growthText(r) }),
      el('td', { class: r.above_50 ? 'up' : r.above_50 === false ? 'down' : 'dim', text: flagText(r.above_50) }),
      el('td', { class: r.above_200 ? 'up' : r.above_200 === false ? 'down' : 'dim', text: flagText(r.above_200) }),
    ])));
  };
  const heads = [...NAME_COLUMNS, { key: 'a50', label: '>50D' }, { key: 'a200', label: '>200D' }];
  heads.forEach((c) => {
    head.append(el('th', {
      class: c.get ? 'eu-sortable' : '', text: c.label,
      onclick: c.get ? () => { state.direction = state.key === c.key ? (state.direction === 'desc' ? 'asc' : 'desc') : c.first; state.key = c.key; draw(); } : null,
    }));
  });
  draw();
  const sectors = [...new Set(names.map((n) => n.sector))].sort();
  const filter = periodSwitch(['ALL', ...sectors], 'ALL', (s) => { state.sector = s; draw(); });
  return card(`${group.label} · ${names.length} NAMES`, filter, [
    el('div', { class: 'table-scroll' }, [el('table', { class: 'data' }, [el('thead', {}, [head]), body])]),
    el('div', { class: 'field-note', text: 'Click a column to sort. Returns are in local currency on each name\'s own trading days; London prices are in pence. FWD P/E and TRAIL P/E are Yahoo\'s own; EPS G is consensus EPS this fiscal year against last year\'s. A dash means Yahoo has none.' }),
  ]);
}

export default function renderEuropeNames(root, data, _manifest, ctx = {}) {
  if (!data || data.unavailable || !data.universes) {
    root.append(gap('No European data in this build.'));
    return;
  }
  root.append(sectionTitle('EUROPE', 'INDEX MEMBERS AND NAMED GROUPS'));
  root.append(metaRow(`AS OF ${data.as_of} · PRICES THROUGH ${data.inputs.prices_through}`, data.notes));
  const lists = [
    ...Object.entries(data.universes).map(([key, u]) => ({ key, label: u.label, names: u.names, sectors: u.sectors, note: null, unavailable: u.unavailable })),
    ...data.groups.map((g) => ({ key: g.key, label: g.label, names: g.names, sectors: g.sectors, note: g.note })),
  ];
  const wanted = String(ctx.arg || '').toLowerCase();
  const first = lists.find((l) => l.key === wanted) || lists[0];
  const host = el('div', {});
  const draw = (list) => {
    if (list.unavailable) {
      host.replaceChildren(gap(`${list.label} is unavailable: ${list.unavailable}.`));
      return;
    }
    host.replaceChildren(
      list.note ? el('div', { class: 'note-text', text: list.note }) : null,
      sectorTable(list.sectors, data.settings.periods),
      namesTable(list.names, list),
    );
  };
  root.append(periodSwitch(lists.map((l) => l.label), first.label, (label) => {
    const list = lists.find((l) => l.label === label);
    ctx.setArg?.(list.key);
    draw(list);
  }));
  root.append(host);
  draw(first);
}
