import { el, card, table, num, pct, dirClass, sectionTitle, DASH } from '../fmt.js';

const HEAT_WARM = [185, 28, 28];
const HEAT_COOL = [30, 64, 175];
// Never fully transparent (a real reading must be visibly a reading) and never
// fully opaque (the text on top has to stay readable).
const HEAT_MIN_ALPHA = 0.15;
const HEAT_ALPHA_RANGE = 0.6;

const MONTH_NAMES = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

// The inflation grid is a heat table: colour encodes each metric's own range
// so a 4% headline print and a 0.5% MoM spending print are each shaded against
// their own history rather than against one another.
function heatColor(value, low, high) {
  if (value === null || value === undefined) return 'transparent';
  if (high === low) return 'transparent';
  const t = (value - low) / (high - low);
  const strength = Math.abs(t - 0.5) * 2;
  const warm = t >= 0.5;
  const base = warm ? HEAT_WARM : HEAT_COOL;
  return `rgba(${base.join(',')},${(HEAT_MIN_ALPHA + strength * HEAT_ALPHA_RANGE).toFixed(2)})`;
}

export default function renderMacro(root, data) {
  root.append(sectionTitle('MACRO'));

  const cols = data.commodities.periods;
  const rows = data.commodities.rows.map((row) => {
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
    return `${MONTH_NAMES[Number(month) - 1]} ${year}`;
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

  root.append(card(`INFLATION — LAST ${data.inflation.releases ?? data.inflation.months.length} MONTHLY RELEASES`, null, [
    table(header, inflationRows),
    el('div', { class: 'note-text', text: data.note }),
  ]));
}
