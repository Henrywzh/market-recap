// INDEX HISTORY, one layout for INDICES (S&P 500, Nasdaq 100) and EUROPE (FTSE 100,
// EURO STOXX 50): the index's price, its members above their averages with the
// day's up / down in one line, what moved it, and the day's movers.

import { el, card, table, num, pct, dirClass, periodSwitch, sectionTitle, DASH } from './fmt.js';
import { render, areaLine, SERIES_COLORS } from './charts.js';
import { contributionsCard } from './session-cards.js';

const present = (v) => typeof v === 'number' && Number.isFinite(v);
const BREADTH_SESSIONS = { '1M': 21, '3M': 63, '6M': 126, '1Y': null };

export function moverTable(title, rows) {
  const body = rows.map((row) => el('tr', {}, [
    el('td', { class: 'wrap-cell' }, [
      el('span', { text: row.ticker }),
      el('span', { class: 'sub', text: row.name }),
    ]),
    el('td', { class: 'wrap-cell dim', text: row.sector }),
    el('td', { class: 'wrap-cell dim', text: row.sub_sector }),
    el('td', { text: num(row.price) }),
    el('td', { class: dirClass(row.change_pct), text: pct(row.change_pct) }),
  ]));
  return card(title, null, table(['TICKER', 'SECTOR', 'SUB-SECTOR', 'PRICE', '% CHG'], body));
}

// Today's count in one line above the chart: up / down, the two averages, highs and lows.
export function breadthLine(b) {
  const share = (v) => el('span', { class: present(v) ? (v >= 50 ? 'up' : 'down') : 'dim', text: present(v) ? `${num(v, 0)}%` : DASH });
  const pair = (up, down) => [el('span', { class: 'up', text: up ?? DASH }), el('span', { class: 'dim', text: ' / ' }), el('span', { class: 'down', text: down ?? DASH })];
  return el('div', { class: 'ih-breadth-line' }, [
    el('span', { class: 'dim', text: 'UP / DOWN TODAY ' }), ...pair(b?.['1D']?.up, b?.['1D']?.down),
    el('span', { class: 'dim', text: ' · ABOVE 50D ' }), share(b?.above_50d),
    el('span', { class: 'dim', text: ' · ABOVE 200D ' }), share(b?.above_200d),
    el('span', { class: 'dim', text: ' · 52W HIGHS / LOWS ' }), ...pair(b?.new_highs, b?.new_lows),
  ]);
}

function drawAbove(node, h, period) {
  if (!h?.dates?.length) return;
  const n = BREADTH_SESSIONS[period];
  const from = n ? Math.max(0, h.dates.length - n) : 0;
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, top: 28 },
    legend: { top: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: (v) => `${num(v, 0)}%` },
    xAxis: { ...option.xAxis, data: h.dates.slice(from) },
    yAxis: { ...option.yAxis, min: 0, max: 100, interval: 25, axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => `${v}%` } },
    series: [
      { name: '% above 50-day', type: 'line', showSymbol: false, data: h.above_50d.slice(from), lineStyle: { width: 1.2, color: SERIES_COLORS[1] }, itemStyle: { color: SERIES_COLORS[1] },
        markLine: { silent: true, symbol: 'none', data: [{ yAxis: 50 }], lineStyle: { color: p.faint, type: 'dashed' }, label: { show: false } } },
      { name: '% above 200-day', type: 'line', showSymbol: false, data: h.above_200d.slice(from), lineStyle: { width: 1.6, color: SERIES_COLORS[0] }, itemStyle: { color: SERIES_COLORS[0] } },
    ],
  }));
}

// ``v``: { key, label, members, date, price_chart, breadth, history, contributions,
// gainers, losers } and how the contributions card reads (``contrib``).
export function indexHistory(host, v, { contrib = {} } = {}) {
  const priceNode = el('div', { class: 'chart' });
  const aboveNode = el('div', { class: 'chart' });
  const pricePeriods = Object.keys(v.price_chart || {});
  const priceDefault = pricePeriods.includes('1Y') ? '1Y' : pricePeriods.at(-1);
  const drawPrice = (p) => { const x = v.price_chart[p]; if (x) areaLine(priceNode, x.dates, x.values); };
  const name = v.key && v.key !== v.label ? `${v.label} (${v.key})` : v.label;
  host.replaceChildren(
    sectionTitle(name, `· ${v.members} MEMBERS · AS OF ${v.date || DASH}`),
    el('div', { class: 'grid two' }, [
      card(`${v.label} — PRICE`, periodSwitch(pricePeriods, priceDefault, drawPrice), priceNode),
      card(`${v.label} MEMBERS ABOVE THEIR AVERAGES`, periodSwitch(Object.keys(BREADTH_SESSIONS), '1Y', (p) => drawAbove(aboveNode, v.history, p)),
        v.history ? [breadthLine(v.breadth), aboveNode] : [breadthLine(v.breadth), el('div', { class: 'gap', text: 'Under a year of member closes: no history yet.' })]),
    ]),
    contributionsCard(v.contributions, { index: v.label, ...contrib }),
    el('div', { class: 'grid two' }, [
      moverTable(`TOP ${v.gainers.length} GAINERS — ${v.label}`, v.gainers),
      moverTable(`TOP ${v.losers.length} LOSERS — ${v.label}`, v.losers),
    ]),
  );
  requestAnimationFrame(() => { drawPrice(priceDefault); drawAbove(aboveNode, v.history, '1Y'); });
}
