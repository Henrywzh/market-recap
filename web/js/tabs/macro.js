import { el, card, table, num, pct, dirClass, sectionTitle, DASH } from '../fmt.js';

// The inflation grid is a heat table: colour encodes each metric's own range
// so a 4% headline print and a 0.5% MoM spending print are each shaded against
// their own history rather than against one another.
function heatColor(value, low, high) {
  if (value === null || value === undefined) return 'transparent';
  if (high === low) return 'transparent';
  const t = (value - low) / (high - low);
  const strength = Math.abs(t - 0.5) * 2;
  const warm = t >= 0.5;
  const base = warm ? [185, 28, 28] : [30, 64, 175];
  return `rgba(${base.join(',')},${(0.15 + strength * 0.6).toFixed(2)})`;
}

export default function renderMacro(root, data) {
  root.append(sectionTitle('MACRO'));

  const cols = ['1D', '1W', '1M', '3M', 'YTD'];
  const rows = data.commodities.map((row) => {
    if (row.status !== 'ok') {
      return el('tr', {}, [
        el('td', {}, [el('span', { text: row.label }), el('span', { class: 'sub', text: row.symbol })]),
        el('td', { class: 'dim', text: 'unavailable' }),
        ...cols.map(() => el('td', { class: 'dim', text: DASH })),
      ]);
    }
    return el('tr', {}, [
      el('td', {}, [el('span', { text: row.label }), el('span', { class: 'sub', text: row.symbol })]),
      el('td', { text: num(row.price) }),
      ...cols.map((c) => el('td', { class: dirClass(row[c]), text: pct(row[c]) })),
    ]);
  });
  root.append(card('COMMODITIES', null, table(['ASSET', 'PRICE', ...cols], rows)));

  const inflation = data.inflation;
  const header = ['METRIC', 'UNIT', ...inflation.months.map((m) => {
    const [year, month] = m.split('-');
    return `${['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'][Number(month) - 1]} ${year}`;
  })];

  const inflationRows = inflation.rows.map((row) => {
    if (row.status !== 'ok' || !row.values.length) {
      return el('tr', {}, [
        el('td', { text: row.label }),
        el('td', { class: 'dim', text: row.unit }),
        el('td', { class: 'dim', colspan: String(inflation.months.length), text: 'series unavailable in this build' }),
      ]);
    }
    const valid = row.values.filter((v) => v !== null);
    const low = Math.min(...valid);
    const high = Math.max(...valid);
    return el('tr', {}, [
      el('td', { text: row.label }),
      el('td', { class: 'dim', text: row.unit }),
      ...row.values.map((v) => el('td', {
        text: v === null ? DASH : num(v, 2),
        style: `background:${heatColor(v, low, high)}`,
      })),
    ]);
  });

  root.append(card('INFLATION — LAST 12 MONTHLY RELEASES', null, [
    table(header, inflationRows),
    el('div', { class: 'note-text', text: data.note }),
  ]));
}
