// EUROPE -> INDICES: the European indices and the STOXX Europe 600 supersector
// funds. Returns are in local currency and, for the indices, in dollars (the
// local return compounded with the currency's move). Prices are Yahoo's.

import { el, card, table, num, pct, dirClass, metaRow, sectionTitle, gap, DASH } from '../fmt.js';
import { multiLine } from '../charts.js';
import { spark } from '../spark.js';
import { flagText } from '../europe-model.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);

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

export default function renderEurope(root, data) {
  if (!data || data.unavailable || !Array.isArray(data.indices)) {
    root.append(gap('No European data in this build.'));
    return;
  }
  root.append(sectionTitle('EUROPE', 'INDICES AND SECTORS'));
  root.append(metaRow(`AS OF ${data.as_of} · PRICES THROUGH ${data.inputs.prices_through}${data.inputs.no_prices?.length ? ` · NO PRICES: ${data.inputs.no_prices.join(', ')}` : ''}`, data.notes));
  root.append(strip(data), indexTable(data), chartCard(data), sectorTable(data));
}
