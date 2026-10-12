// INDICES -> OVERNIGHT VS INTRADAY: each fund's growth held only from the
// close to the next open, only from the open to the close, and both (the fund
// itself), with each leg's return by window and by calendar year. Drawn from
// the overnight artifact (panels/overnight.py).

import { el, card, table, num, pct, dirClass, periodSwitch, DASH } from './fmt.js';
import { render } from './charts.js';

const LEGS = [
  ['overnight', 'Overnight (close → open)', (p) => p.blue],
  ['intraday', 'Intraday (open → close)', (p) => p.accent],
  ['total', 'Held throughout', (p) => p.text],
];
// Up to two years the daily path; longer ranges the weekly one, on a log scale.
const RANGES = { '1Y': ['daily', 1], '2Y': ['daily', 2], '5Y': ['weekly', 5], '10Y': ['weekly', 10], MAX: ['weekly', null] };

// The part of a path inside the last `years` (all when null), each leg
// rebased to 1 on its first day.
export function rangePath(path, years) {
  const n = path.dates.length;
  if (!n) return { dates: [], overnight: [], intraday: [], total: [] };
  let start = 0;
  if (years) {
    const last = new Date(`${path.dates[n - 1]}T00:00:00Z`);
    const cut = new Date(Date.UTC(last.getUTCFullYear() - years, last.getUTCMonth(), last.getUTCDate())).toISOString().slice(0, 10);
    start = Math.max(0, path.dates.findIndex((d) => d >= cut));
  }
  const out = { dates: path.dates.slice(start) };
  for (const [leg] of LEGS) {
    const base = path[leg][start];
    out[leg] = path[leg].slice(start).map((v) => (v === null || !base ? null : v / base));
  }
  return out;
}

const signed = (v, digits = 1) => (v === null || v === undefined ? DASH : `${v > 0 ? '+' : ''}${num(v, digits)}%`);

function chart(node, view, range) {
  const [kind, years] = RANGES[range];
  const path = rangePath(view[kind], years);
  const log = kind === 'weekly';
  render(node, (option, p) => ({
    ...option,
    grid: { left: 52, right: 16, top: 12, bottom: 48 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, valueFormatter: (v) => (v === null || v === undefined ? DASH : signed((v - 1) * 100, 1)) },
    xAxis: { ...option.xAxis, data: path.dates },
    // A log axis otherwise snaps to powers of ten and flattens a tenfold run.
    yAxis: { ...option.yAxis, type: log ? 'log' : 'value', logBase: 10,
      min: log ? (v) => v.min * 0.95 : undefined, max: log ? (v) => v.max * 1.05 : undefined,
      axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => (log ? `${num(v, v < 10 ? 1 : 0)}×` : signed((v - 1) * 100, 0)) } },
    series: LEGS.map(([leg, label, colour]) => ({
      name: label, type: 'line', data: path[leg], showSymbol: false,
      lineStyle: { width: leg === 'total' ? 1.1 : 1.6, color: colour(p), type: leg === 'total' ? 'dashed' : 'solid' },
      itemStyle: { color: colour(p) },
    })),
  }));
}

function windowsTable(view) {
  return table(['PERIOD', 'OVERNIGHT', 'INTRADAY', 'HELD', 'OVERNIGHT / YR', 'INTRADAY / YR', 'UP NIGHTS', 'UP DAYS'], view.windows.map((w) => el('tr', {}, [
    el('td', { text: w.period === 'MAX' ? `SINCE ${w.from.slice(0, 4)}` : w.period }),
    ...['overnight', 'intraday', 'total'].map((k) => el('td', { class: dirClass(w[k]), text: signed(w[k]) })),
    ...['overnight_ann', 'intraday_ann'].map((k) => el('td', { class: w[k] === null ? 'dim' : dirClass(w[k]), text: signed(w[k]) })),
    el('td', { class: 'dim', text: `${num(w.overnight_up, 0)}%` }),
    el('td', { class: 'dim', text: `${num(w.intraday_up, 0)}%` }),
  ])));
}

function yearsTable(view) {
  return table(['YEAR', 'OVERNIGHT', 'INTRADAY', 'HELD'], [...view.years].reverse().map((y) => el('tr', {}, [
    el('td', { text: `${y.year}${y.to_date ? ' (to date)' : y.partial ? ' (part)' : ''}` }),
    ...['overnight', 'intraday', 'total'].map((k) => el('td', { class: dirClass(y[k]), text: signed(y[k]) })),
  ])));
}

function lastTable(view) {
  return table(['SESSION', 'OVERNIGHT', 'INTRADAY', 'DAY'], view.last.map((r) => el('tr', {}, [
    el('td', { text: r.date }),
    ...['overnight', 'intraday', 'total'].map((k) => el('td', { class: dirClass(r[k]), text: pct(r[k], 2) })),
  ])));
}

export function overnightCard(data) {
  const views = (data?.views || []).filter((v) => v.available);
  if (!views.length) return null;
  let view = views[0];
  let range = '10Y';
  const node = el('div', { class: 'chart' });
  const body = el('div', {});
  const draw = () => {
    chart(node, view, range);
    const stale = Object.entries(view.stale_open_years || {});
    body.replaceChildren(
      el('div', { class: 'table-scroll' }, [windowsTable(view)]),
      el('details', { class: 'fold' }, [el('summary', { text: 'BY CALENDAR YEAR · LAST 10 SESSIONS' }),
        el('div', { class: 'grid two' }, [el('div', { class: 'table-scroll' }, [yearsTable(view)]), el('div', { class: 'table-scroll' }, [lastTable(view)])])]),
      el('div', { class: 'field-note', text: `${view.label}: ${view.sessions} sessions, ${view.since} to ${view.through}. ${data.notes.join(' ')}`
        + (stale.length ? ` In ${stale.map(([y, v]) => `${y} (${v}%)`).join(', ')} more than 5% of the recorded opens equal the previous close: an open the old feed did not record, which moves that day's return into the intraday leg.` : '') }),
    );
  };
  const fundSwitch = periodSwitch(views.map((v) => v.symbol), view.symbol, (symbol) => { view = views.find((v) => v.symbol === symbol); draw(); });
  const rangeSwitch = periodSwitch(Object.keys(RANGES), range, (label) => { range = label; draw(); });
  requestAnimationFrame(draw);
  return card('OVERNIGHT VS INTRADAY · WHERE THE RETURN WAS MADE', el('span', { class: 'tag-row' }, [fundSwitch, rangeSwitch]), [
    el('div', { class: 'note-text', text: 'Growth of 1 held only from each close to the next open, only from each open to the close, and throughout. Up to two years daily, longer ranges weekly on a log scale.' }),
    node, body,
  ]);
}
