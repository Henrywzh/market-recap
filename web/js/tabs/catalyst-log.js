// CALENDAR -> UNSCHEDULED CATALYSTS: dated events no calendar announces, what
// they moved, and whether consensus estimates followed. A hand-kept log with
// sources; the names are the ones the coverage tied to each event.

import { el, card, table, num, dirClass, tag, DASH } from '../fmt.js';
import { multiLine } from '../charts.js';
import { reading, signed, countsText, kindLabel, medianCell } from '../catalyst-log-model.js';

function nameRows(item, periods) {
  const rows = item.names.map((n) => el('tr', {}, [
    el('td', { text: n.ticker }),
    el('td', { class: dirClass(n.price_pct), title: n.price_since ? `from the close of ${n.price_since}` : '', text: signed(n.price_pct, 1) }),
    ...periods.map((p) => el('td', { class: n.has_estimates ? dirClass(n.eps[p]) : 'dim', text: n.has_estimates ? signed(n.eps[p], 1) : 'not recorded' })),
    el('td', { class: n.has_estimates ? dirClass(n.revenue[periods[0]]) : 'dim', text: n.has_estimates ? signed(n.revenue[periods[0]], 2) : 'not recorded' }),
    el('td', { class: 'dim', text: countsText(n.counts) }),
  ]));
  const b = item.basket;
  rows.push(el('tr', { class: 'ks-top' }, [
    el('td', { text: 'MEDIAN (names)' }), el('td', { class: dirClass(b.price.median), text: medianCell(b.price) }),
    ...periods.map((p) => el('td', { class: dirClass(b.eps[p].median), text: medianCell(b.eps[p]) })),
    el('td', { class: dirClass(b.revenue[periods[0]].median), text: medianCell(b.revenue[periods[0]], 2) }), el('td'),
  ]));
  return rows;
}

function eventCard(item, settings, open) {
  const labels = settings.period_labels || {};
  const periods = settings.periods;
  const read = reading(item.state, labels[item.state?.read_period]);
  const node = el('div', { class: 'chart', style: 'height:170px' });
  const path = item.basket.path;
  if (path) queueMicrotask(() => multiLine(node, path.dates, {
    [`EXPOSED · median of ${item.names.length}`]: path.basket, ...(path.spy ? { SPY: path.spy } : {}),
  }));
  const head = el('summary', { class: 'cat-summary' }, [
    el('span', { class: 'dim', text: item.date }), ' ', kindLabel(item.kind) ? tag(kindLabel(item.kind), 'dim') : null, ' ',
    el('strong', { text: item.title }),
    el('span', { class: `dim`, text: `  ·  ${medianCell(item.basket.price)} exposed names since ${item.reference}` }),
  ]);
  const body = el('div', { class: 'cat-detail' }, [
    el('div', { class: 'note-text', text: item.detail || '' }),
    item.url ? el('div', { class: 'field-note' }, [`Source: `, el('a', { href: item.url, target: '_blank', rel: 'noopener', text: item.source || item.url })]) : null,
    el('div', { class: 'sc-fomc-line', text: read.text }),
    item.snapshots.note ? el('div', { class: 'field-note', text: item.snapshots.note }) : null,
    path ? node : null,
    table(['NAME', 'PRICE SINCE', ...periods.map((p) => `EPS · ${labels[p] || p}`), `REV · ${labels[periods[0]] || periods[0]}`, 'ANALYSTS UP↑ DOWN↓'], nameRows(item, periods)),
    el('div', { class: 'field-note', text: `Price change from the close of ${item.reference}${item.after_close ? ' (the news broke after that close)' : ''} to the page's session. Estimate changes are between the evening snapshots of ${item.snapshots.reference || DASH} and ${item.snapshots.latest || DASH}.` }),
  ]);
  return el('details', { class: 'cat-item', ...(open ? { open: '' } : {}) }, [head, body]);
}

export default function catalystLogSection(log) {
  if (!log || log.unavailable || !Array.isArray(log.items) || !log.items.length) return null;
  const snap = log.snapshots || {};
  return card('UNSCHEDULED CATALYSTS · WHAT MOVED, AND DID ESTIMATES FOLLOW',
    el('span', { class: 'dim', text: snap.days ? `consensus recorded ${snap.first} to ${snap.last} (${snap.days} days)` : 'no consensus snapshots recorded' }),
    [el('div', { class: 'field-note', text: log.notes[0] }), ...log.items.map((item, i) => eventCard(item, log.settings, i === 0)),
     el('div', { class: 'field-note', text: log.notes.slice(1).join(' ') })]);
}
