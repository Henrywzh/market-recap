import { el, card, table, num, bps, sectionTitle, DASH } from '../fmt.js';
import { render, timeLines, SERIES_COLORS } from '../charts.js';
import { rangeSwitch, sliceRange, initialRange } from '../range.js';

// A rising yield is a falling bond price and tighter money: red, as on
// OVERVIEW. Spreads are shape, not direction, so they stay grey.
function yieldClass(change) {
  if (change === null || change === undefined || change === 0) return 'dim';
  return change > 0 ? 'down' : 'up';
}

function historyCard(history) {
  const series = history?.series || {};
  const spreadName = history?.spread;
  const names = Object.keys(series).filter((n) => n !== spreadName);
  if (!names.length) return null;
  const longest = names.map((n) => series[n].dates).reduce((a, b) => (b.length > a.length ? b : a), []);
  let range = initialRange(longest, '1Y');
  const node = el('div', { class: 'chart' });
  const spreadNode = el('div', { class: 'chart short' });
  const cut = (name) => sliceRange(series[name].dates, { values: series[name].values }, range);
  const draw = () => {
    timeLines(node, names.map((name) => ({ name, ...cut(name) })), {
      left: (v) => `${v.toFixed(1)}%`,
      value: (v) => `${num(v, 2)}%`,
    });
    // The spread under the levels, on its own axis: below zero is an inverted curve.
    if (series[spreadName]) {
      const s = cut(spreadName);
      timeLines(spreadNode, [{ name: spreadName, ...s, color: (p) => p.accent }], {
        left: (v) => `${v.toFixed(0)}bp`,
        value: (v) => `${num(v, 0)}bp`,
        markY: [{ y: 0, label: 'inverted below' }],
      });
    }
  };
  requestAnimationFrame(draw);
  return card('YIELDS OVER TIME', rangeSwitch(longest, range, (label) => { range = label; draw(); }), [
    node,
    series[spreadName] ? el('div', { class: 'chart-head' }, [el('span', { class: 'dim', text: `${spreadName} SPREAD · BP` })]) : null,
    series[spreadName] ? spreadNode : null,
    el('div', { class: 'note-text', text: `FRED constant-maturity yields (Treasury's own series), ${history.years} years: daily for the last year, each week's last print before that. FRED posts a day after Treasury, so the last point can trail the table above by a session.` }),
  ]);
}

export default function renderFixedIncome(root, data) {
  root.append(sectionTitle('U.S. TREASURIES', '(FIXED INCOME)'));

  const chartNode = el('div', { class: 'chart tall' });
  const curveCard = card(
    'YIELD CURVE — LATEST VS. 1 WEEK, 1 MONTH AGO AND START OF YEAR',
    null,
    [chartNode, el('div', { class: 'note-text', text: data.note })],
  );
  // The curve's shape beside its history: where each tenor sits today, and
  // how it got there.
  const history = historyCard(data.history);
  root.append(history ? el('div', { class: 'grid two' }, [curveCard, history]) : curveCard);

  requestAnimationFrame(() => render(chartNode, (option, p) => ({
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
  })));

  // Change columns come from the artifact, which took them from the contract:
  // "1W" on this tab is seven calendar days because the curve is published on
  // a calendar schedule, and it says so in the note rather than silently
  // meaning something different from "1W" on the equity tabs.
  const cols = data.change_columns;
  const rows = data.rows.map((row) => el('tr', {}, [
    el('td', { text: row.tenor }),
    el('td', { text: row.yield_pct === null ? DASH : `${num(row.yield_pct)}%` }),
    ...cols.map((c) => el('td', { class: yieldClass(row[c]), text: bps(row[c]) })),
  ]));
  data.spreads.forEach((spread) => {
    rows.push(el('tr', { class: 'emphasis' }, [
      el('td', { text: spread.label }),
      el('td', { text: spread.bps === null ? DASH : `${bps(spread.bps)} bps` }),
      ...cols.map((c) => el('td', { class: 'dim', text: bps(spread[c]) })),
    ]));
  });

  root.append(card('TREASURY YIELDS — LEVEL & CHANGE (BPS)', el('span', { class: 'dim', text: 'red = yield up' }),
    table(['MATURITY', 'YIELD', ...cols.map((c) => `${c} (BPS)`)], rows)));
}
