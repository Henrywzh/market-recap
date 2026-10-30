// EUROPE -> INDICES: the European indices and the STOXX Europe 600 supersector
// funds. Returns are in local currency and, for the indices, in dollars (the
// local return compounded with the currency's move). Prices are Yahoo's.

import { el, card, table, num, pct, dirClass, metaRow, sectionTitle, gap, notice, periodSwitch, DASH } from '../fmt.js';
import { multiLine, disposeWithin } from '../charts.js';
import { performanceCard } from '../session-cards.js';
import { indexHistory } from '../index-history.js';
import { spark } from '../spark.js';
import { flagText, mapPeriods, mapGroups, mapColourCap, mapNote, marketCapText } from '../europe-model.js';
import { drawTreemap, returnColor } from '../treemap.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);

export function heatmap(data, kind) {
  const indices = kind === 'indices';
  const rows = data[kind];
  let period = '1M';
  let mode = indices ? 'LOCAL' : 'RETURN';
  const modes = indices ? ['LOCAL', 'USD'] : ['RETURN', 'VS STOXX 600'];
  const periods = ['1D', '1W', '1M', '3M', '6M', 'YTD', '1Y'].filter((p) => rows.some((r) => Object.hasOwn(r.returns || {}, p)));
  const grid = el('div', { class: 'eu-heatmap' });
  const note = el('div', { class: 'field-note' });
  const draw = () => {
    const relative = mode === 'VS STOXX 600';
    const field = relative ? 'relative' : mode === 'USD' ? 'returns_usd' : 'returns';
    const scale = Math.max(1, ...rows.map((r) => Math.abs(r[field]?.[period] ?? 0)));
    grid.replaceChildren(...rows.map((r) => {
      const value = r[field]?.[period];
      const tint = present(value) ? `background:color-mix(in srgb, var(${value >= 0 ? '--up' : '--down'}) ${Math.round(8 + 25 * Math.min(Math.abs(value) / scale, 1))}%, var(--panel))` : '';
      return el('div', { class: `eu-heat-tile ${present(value) ? '' : 'dim'}`, style: tint, title: `${r.symbol} · ${r.date || data.inputs.prices_through}` }, [
        el('div', { class: 'eu-heat-name', text: r.label }),
        el('div', { class: `eu-heat-value ${dirClass(value)}`, text: present(value) ? `${value > 0 ? '+' : ''}${num(value, 1)}${relative ? ' pp' : '%'}` : DASH }),
        el('div', { class: 'field-note', text: `${period} · ${relative ? 'vs STOXX 600' : mode === 'USD' ? 'USD' : r.currency}` }),
      ]);
    }));
    note.textContent = `Equal-size tiles, not market-cap weights. Color intensity is scaled within this view. ${relative ? 'Fund return less the STOXX 600 fund return, in percentage points.' : 'Price returns; local currencies and USD are not interchangeable.'} As of ${data.as_of}.`;
  };
  draw();
  return card(indices ? 'EUROPE INDICES · PERFORMANCE MAP' : 'EUROPE SECTORS · PERFORMANCE MAP', periodSwitch(periods, period, (p) => { period = p; draw(); }), [
    el('div', { class: 'pc-controls' }, [periodSwitch(modes, mode, (m) => { mode = m; draw(); })]), grid, note,
  ]);
}

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function sparkCell(values) {
  return el('td', { class: 'eu-spark' }, [spark(values, { width: 80, height: 20 })]);
}

function strip(data) {
  const fx = data.fx.map((f) => stat(`${f.symbol.replace('=X', '')}`, present(f.last) ? num(f.last, 4) : DASH,
    `1D ${pct(f.returns['1D'], 2)} · 1M ${pct(f.returns['1M'], 2)} · YTD ${pct(f.returns.YTD, 1)}`));
  const b = data.benchmark;
  return el('div', { class: 'stat-strip' }, [...fx, stat(`${b.symbol} (USD)`, present(b.last) ? num(b.last, 2) : DASH, `1M ${pct(b.returns['1M'], 1)} · YTD ${pct(b.returns.YTD, 1)} · 1Y ${pct(b.returns['1Y'], 1)}`)]);
}

function indexTable(data) {
  const periods = ['1D', '1W', '1M', '3M', 'YTD', '1Y'];
  const head = ['INDEX', 'LAST', ...periods.map((p) => p), '1M $', 'YTD $', '1Y $', 'FROM 52W HIGH', '>50D', '>200D', '6M'];
  const rows = data.indices.map((r) => el('tr', {}, [
    el('td', { title: `${r.symbol} · ${r.currency} · ${r.date || ''}` }, [el('span', { class: 'ms-name', text: r.label }), el('span', { class: 'sub', text: r.currency })]),
    el('td', { text: present(r.last) ? num(r.last, r.last >= 1000 ? 0 : 2) : DASH }),
    ...periods.map((p) => el('td', { class: dirClass(r.returns[p]), text: pct(r.returns[p], 2) })),
    ...['1M', 'YTD', '1Y'].map((p) => el('td', { class: dirClass(r.returns_usd?.[p]), text: r.returns_usd ? pct(r.returns_usd[p], 1) : DASH })),
    el('td', { class: dirClass(r.drawdown_pct), title: r.high_date ? `high ${r.high_date}` : '', text: pct(r.drawdown_pct, 1) }),
    el('td', { class: r.above_50 ? 'up' : r.above_50 === false ? 'down' : 'dim', text: flagText(r.above_50) }),
    el('td', { class: r.above_200 ? 'up' : r.above_200 === false ? 'down' : 'dim', text: flagText(r.above_200) }),
    sparkCell(r.spark),
  ]));
  return card('INDICES · LOCAL CURRENCY, WITH DOLLAR RETURNS BESIDE THEM', el('span', { class: 'dim', text: `through ${data.inputs.prices_through}` }),
    [table(head, rows), el('div', { class: 'field-note', text: 'Returns run on each index\'s own trading days. $ columns are the same index in dollars: the local return and the currency\'s move against the dollar together. The 52-week drawdown is from the highest close of the last 252 sessions.' })]);
}

function chartCard(data) {
  const c = data.chart;
  if (!c?.dates?.length) return card('INDICES IN DOLLARS', null, [gap('No chart history.')]);
  const node = el('div', { class: 'chart', style: 'height:300px' });
  queueMicrotask(() => multiLine(node, c.dates, c.series));
  return card(`INDICES IN DOLLARS · REBASED TO 100 · LAST ${data.settings.chart_years} YEARS, WEEKLY`, el('span', { class: 'dim', text: 'with SPY' }), [node]);
}

function sectorTable(data) {
  const sorted = [...data.sectors].sort((a, b) => (b.relative['3M'] ?? -999) - (a.relative['3M'] ?? -999));
  const head = ['SECTOR (STOXX 600)', '1M', '3M', 'YTD', '1Y', '1M VS 600', '3M VS 600', 'YTD VS 600', 'FROM 52W HIGH', '>200D', '6M'];
  const rows = sorted.map((r) => el('tr', {}, [
    el('td', { title: `${r.symbol} · ${r.currency}` }, [el('span', { text: r.label })]),
    ...['1M', '3M', 'YTD', '1Y'].map((p) => el('td', { class: dirClass(r.returns[p]), text: pct(r.returns[p], 1) })),
    ...['1M', '3M', 'YTD'].map((p) => el('td', { class: dirClass(r.relative[p]), text: present(r.relative[p]) ? `${r.relative[p] > 0 ? '+' : ''}${num(r.relative[p], 1)}` : DASH })),
    el('td', { class: dirClass(r.drawdown_pct), text: pct(r.drawdown_pct, 1) }),
    el('td', { class: r.above_200 ? 'up' : r.above_200 === false ? 'down' : 'dim', text: flagText(r.above_200) }),
    sparkCell(r.spark),
  ]));
  return card('SECTORS · THE iSHARES STOXX EUROPE 600 SUPERSECTOR FUNDS, IN EURO', el('span', { class: 'dim', text: `against ${data.settings.rotation_benchmark} · sorted by 3M relative` }),
    [table(head, rows), el('div', { class: 'field-note', text: 'The Europe analogue of the SPDR sector funds: each is a STOXX Europe 600 supersector index fund listed on Xetra. "VS 600" is the fund\'s return less the STOXX Europe 600 fund\'s, in percentage points. Personal & Household Goods holds the luxury houses; Oil & Gas and Basic Resources are the commodity legs.' })]);
}

// The tooltip is the page's shared #tooltip element, as on the heatmaps. A
// treemap tile's hover needs the event for placement, so it is passed in.
function showTip(html, event) {
  const node = document.getElementById('tooltip');
  if (!node) return;
  node.innerHTML = html;
  node.style.display = 'block';
  const pad = 14;
  const rect = node.getBoundingClientRect();
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + rect.width > window.innerWidth) x = event.clientX - rect.width - pad;
  if (y + rect.height > window.innerHeight) y = event.clientY - rect.height - pad;
  node.style.left = `${Math.max(4, x)}px`;
  node.style.top = `${Math.max(4, y)}px`;
}

function hideTip() {
  const node = document.getElementById('tooltip');
  if (node) node.style.display = 'none';
}

// FTSE 100 / EURO STOXX 50 members sized by market cap. The indices and sector
// funds above are equal-size maps because the build has no caps for them.
export function membersCard(data) {
  const universes = Object.entries(data.universes || {}).filter(([, u]) => Array.isArray(u?.names) && u.names.length);
  // A member list that failed is named, with why, rather than dropped from the switch unseen.
  const failed = Object.entries(data.inputs?.universes_unavailable || {}).map(([key, why]) =>
    `${data.universes?.[key]?.label || key} members could not be read this build (${why}).`);
  const missing = failed.length ? notice(failed.join(' ')) : null;
  if (!universes.length) return failed.length ? card('FTSE 100 / EURO STOXX 50 · MEMBERS BY MARKET CAP', null, [missing]) : null;
  const state = { key: universes[0][0], period: '1M' };
  const periodHost = el('div', { class: 'pc-controls' });
  const node = el('div', { class: 'treemap eu-members-map' });
  const note = el('div', { class: 'field-note' });
  const universe = () => data.universes[state.key];

  const draw = () => {
    const names = universe().names;
    const periods = mapPeriods(names);
    if (!periods.includes(state.period)) state.period = periods.includes('1M') ? '1M' : periods[0];
    const period = state.period;
    const shaped = mapGroups(names, period, (ret) => returnColor(ret, mapColourCap(period)));
    periodHost.replaceChildren(periodSwitch(periods, period, (p) => { state.period = p; draw(); }));
    note.textContent = mapNote(shaped);
    drawTreemap(node, shaped.groups, (payload, event) => {
      const ret = payload.ret;
      showTip(`<div class="t-head">${payload.symbol} <span class="${dirClass(ret)}">${present(ret) ? `${ret > 0 ? '+' : ''}${num(ret, 1)}%` : DASH}</span> <span class="dim">${period}</span></div>
        <div class="t-meta">${payload.name}<br>${payload.sector} · ${marketCapText(payload.market_cap, payload.currency)}</div>`, event);
    }, hideTip);
  };

  const switcher = periodSwitch(universes.map(([, u]) => u.label), universe().label, (label) => {
    state.key = universes.find(([, u]) => u.label === label)?.[0] || state.key;
    draw();
  });
  // Drawing needs the node in the page, so the first draw waits a microtask; a
  // resize relays the map out in pixels.
  queueMicrotask(draw);
  window.addEventListener('resize', draw);
  return card('FTSE 100 / EURO STOXX 50 · MEMBERS BY MARKET CAP', null, [
    missing, el('div', { class: 'pc-controls' }, [switcher]), periodHost, node, note,
  ]);
}

// INDEX HISTORY for the FTSE 100 or the EURO STOXX 50, on the index's own days:
// its price, its members above their averages (with the day's up / down), what
// moved it and the day's movers; then the indices against the S&P 500.
function indexSection(data) {
  const universes = Object.entries(data.universes || {}).filter(([, u]) => u?.session);
  if (!universes.length) return data.performance ? [performance(data)] : [];
  const history = el('div', { class: 'index-history' });
  const draw = (label) => {
    const [, u] = universes.find(([, x]) => x.label === label) || universes[0];
    disposeWithin(history);
    const v = u.session;
    indexHistory(history, { ...v, label: u.label, breadth: v, date: v.date || data.as_of }, { contrib: { link: false,
      note: `Each member's share of the members' combined market cap times its return on the day, in percentage points. Yahoo's market caps stand in for the index's free-float weights, so the sum is set beside the index's own move. ${v.contributions ? `${v.contributions.weighted} of ${v.contributions.members} members have a market cap.` : ''}` } });
  };
  const labels = universes.map(([, u]) => u.label);
  queueMicrotask(() => draw(labels[0]));
  return [
    card('INDEX HISTORY · SELECT A UNIVERSE', periodSwitch(labels, labels[0], draw), history),
    performance(data),
  ];
}

function performance(data) {
  return performanceCard(data.performance, null, 'PERFORMANCE · EUROPEAN INDICES IN LOCAL CURRENCY, S&P 500 IN DOLLARS');
}

export default function renderEurope(root, data) {
  if (!data || data.unavailable || !Array.isArray(data.indices)) {
    root.append(gap('No European data in this build.'));
    return;
  }
  root.append(sectionTitle('EUROPE', 'INDICES AND SECTORS'));
  root.append(metaRow(`AS OF ${data.as_of} · PRICES THROUGH ${data.inputs.prices_through}${data.inputs.no_prices?.length ? ` · NO PRICES: ${data.inputs.no_prices.join(', ')}` : ''}`, data.notes));
  // The performance maps and the members' market-cap map are on HEAT MAPS.
  root.append(strip(data), el('div', { class: 'field-note', text: 'Performance maps of the indices, the STOXX 600 sectors and the FTSE 100 / EURO STOXX 50 members: MARKET → HEAT MAPS.' }),
    ...indexSection(data));
  const details = el('details', { class: 'sx-fold' }, [el('summary', { text: 'Exact readings, trend flags & dollar history' })]);
  let loaded = false;
  details.addEventListener('toggle', () => {
    if (!details.open || loaded) return;
    loaded = true;
    details.append(indexTable(data), chartCard(data), sectorTable(data));
  });
  root.append(details);
}
