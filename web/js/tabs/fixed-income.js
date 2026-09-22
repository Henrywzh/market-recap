import { el, card, table, num, bps, dirClass, sectionTitle, DASH } from '../fmt.js';
import { render, SERIES_COLORS } from '../charts.js';

export default function renderFixedIncome(root, data) {
  root.append(sectionTitle('U.S. TREASURIES', '(FIXED INCOME)'));

  const chartNode = el('div', { class: 'chart tall' });
  root.append(card(
    'YIELD CURVE — LATEST PUBLISHED VS. 1 WEEK AGO VS. 1 MONTH AGO VS. START OF YEAR',
    null,
    [chartNode, el('div', { class: 'note-text', text: data.note })],
  ));

  render(chartNode, (option, p) => ({
    ...option,
    grid: { ...option.grid, bottom: 52, left: 56 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, valueFormatter: (v) => (v === null ? DASH : `${v.toFixed(2)}%`) },
    xAxis: { ...option.xAxis, data: data.tenors, boundaryGap: false },
    yAxis: { ...option.yAxis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${v.toFixed(2)}%` } },
    series: data.curves.map((curve, index) => ({
      name: `${curve.label} (${curve.date})`,
      type: 'line',
      data: curve.values,
      showSymbol: true,
      symbolSize: 5,
      // The latest curve is the subject of the panel; the comparisons are
      // context, so they are thinner and cooler.
      lineStyle: { width: index === 0 ? 1.8 : 1.1, color: SERIES_COLORS[index % SERIES_COLORS.length] },
      itemStyle: { color: SERIES_COLORS[index % SERIES_COLORS.length] },
    })),
  }));

  const cols = ['1D', '1W', '1M', 'YTD'];
  const rows = data.rows.map((row) => el('tr', {}, [
    el('td', { text: row.tenor }),
    el('td', { text: row.yield_pct === null ? DASH : `${num(row.yield_pct)}%` }),
    ...cols.map((c) => el('td', { class: dirClass(row[c]), text: bps(row[c]) })),
  ]));
  data.spreads.forEach((spread) => {
    rows.push(el('tr', { class: 'emphasis' }, [
      el('td', { text: spread.label }),
      el('td', { text: spread.bps === null ? DASH : `${bps(spread.bps)} bps` }),
      ...cols.map((c) => el('td', { class: dirClass(spread[c]), text: bps(spread[c]) })),
    ]));
  });

  root.append(card('TREASURY YIELDS — LEVEL & CHANGE (BPS)', null,
    table(['MATURITY', 'YIELD', '1D (BPS)', '1W (BPS)', '1M (BPS)', 'YTD (BPS)'], rows)));
}
