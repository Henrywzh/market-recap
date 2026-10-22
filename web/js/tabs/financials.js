// FINANCIALS: ten fiscal years of filed statements for any index member,
// drawn as a section of the ticker page (tabs/ticker.js).
//
// Every number is the company's own XBRL fact as most recently filed. A blank
// is a line the filer did not tag -- never a zero -- and each column says when
// it was last filed, because a restated year is a different claim from the
// original one.

import { el, card, table, num, pct, DASH } from '../fmt.js';
import { render } from '../charts.js';
import { MODES, defaultMode, hasQuarters, pointNotes, seriesFor } from '../fundamentals-model.js';
import { formatValue as formatAxis } from '../axis-format.js';

const FINANCIALS_BASE = 'artifacts/financials';
const MILLION = 1e6;
const TREND_GROUP = 'fundamental-trends';
const MODE_LABELS = { annual: 'ANNUAL', quarterly: 'QUARTERLY', ttm: 'TTM' };
const NO_QUARTERS = 'Quarterly statements are not built for this ticker';
const TREND_TITLES = [
  'REVENUE & GROWTH ($B, %)', 'MARGINS (%)', 'NET INCOME & DILUTED EPS', 'FREE CASH FLOW & FCF MARGIN', 'RETURNS (%)', 'BALANCE SHEET ($B)',
];

async function loadCompany(symbol) {
  const response = await fetch(`${FINANCIALS_BASE}/${symbol}.json`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`${symbol} has no filed statements in this build`);
  return response.json();
}

// Units come from the XBRL fact itself: dollars, dollars per share, shares.
function formatValue(value, unit) {
  if (value === null || value === undefined) return DASH;
  if (unit === 'USD/shares') return num(value, 2);
  if (unit === 'shares') return num(value / MILLION, 1);
  return num(value / MILLION, 0);
}

function unitNote(unit) {
  if (unit === 'USD/shares') return '$';
  if (unit === 'shares') return 'M';
  return '$M';
}

function formatRatio(value, unit) {
  if (value === null || value === undefined) return DASH;
  if (unit === 'pct') return `${num(value, 1)}%`;
  if (unit === 'x') return `${num(value, 1)}x`;
  return num(value / MILLION, 0);
}

function columnHeaders(company) {
  return ['LINE ITEM', 'UNIT', ...company.columns.map((c) => `FY${c.fiscal_year}`)];
}

// The period end and filing date under each fiscal-year label: "FY2025" alone
// is ambiguous for a retailer, and a restated column should say so.
function periodRows(company) {
  return [
    el('tr', { class: 'dim' }, [
      el('td', { text: 'Period end' }), el('td', {}),
      ...company.columns.map((c) => el('td', { text: c.period_end })),
    ]),
    el('tr', { class: 'dim' }, [
      el('td', { text: 'Last filed' }), el('td', {}),
      ...company.columns.map((c) => el('td', { text: c.filed || DASH })),
    ]),
  ];
}

function statementTable(company, statement) {
  const rows = statement.items.map((item) => el('tr', {}, [
    el('td', { text: item.label }),
    el('td', { class: 'dim', text: unitNote(item.unit) }),
    ...company.values[item.key].map((value, i) => {
      const derived = item.key === 'nwc_change' && company.nwc_basis[i]?.startsWith('derived');
      return el('td', {
        class: value === null ? 'dim' : '',
        text: formatValue(value, item.unit) + (derived ? '*' : ''),
        title: derived ? 'Derived: change in current assets less current liabilities' : null,
      });
    }),
  ]));
  return table(columnHeaders(company), [...periodRows(company), ...rows]);
}

function ratioTable(company, ratios) {
  const rows = ratios.map((ratio) => el('tr', {}, [
    el('td', { text: ratio.label }),
    el('td', { class: 'dim', text: ratio.unit === 'usd' ? '$M' : '' }),
    ...company.ratios[ratio.key].map((value) => el('td', {
      class: value === null ? 'dim' : '',
      text: ratio.key === 'revenue_growth' && value !== null ? pct(value, 1) : formatRatio(value, ratio.unit),
    })),
  ]));
  return table(columnHeaders(company), rows);
}

// One colour per series, the same in each of the six charts.
function trendColors(p) {
  return {
    revenue: p.blue, growth: p.accent, gross: p.purple, operating: '#22d3ee', net: p.text,
    netIncome: '#fb923c', eps: '#f472b6', fcf: '#34d399', fcfMargin: '#fbbf24',
    roe: '#94a3b8', roic: '#e2e8f0', cash: '#4ade80', debt: '#f87171', netDebt: '#c084fc',
  };
}

// Tooltip text per kind of value, and axis text per kind of axis.
const FORMAT = {
  money: (v) => `${v < 0 ? '-' : ''}$${num(Math.abs(v), 1)}B`,
  pct: (v) => `${num(v, 1)}%`,
  growth: (v) => pct(v, 1),
  eps: (v) => `${v < 0 ? '-' : ''}$${num(Math.abs(v), 2)}`,
};
const AXIS = {
  money: (v) => `${v < 0 ? '-' : ''}$${formatAxis(Math.abs(v))}B`,
  pct: (v) => `${formatAxis(v)}%`,
  eps: (v) => `$${formatAxis(v)}`,
};

// One of the six charts: bars and lines are { name, data, color, kind }, a line
// on the right-hand axis carries axis: 1. left and right name the axis kinds.
function drawTrend(node, labels, spec, notes) {
  return render(node, (option, p) => {
    const colors = trendColors(p);
    const kindOf = {};
    const bars = spec.bars.map((s) => {
      kindOf[s.name] = s.kind;
      return { name: s.name, type: 'bar', data: s.data, barMaxWidth: 14, itemStyle: { color: colors[s.color] } };
    });
    const lines = spec.lines.map((s) => {
      kindOf[s.name] = s.kind;
      const marks = s.marks?.map((i) => ({ coord: [i, s.data[i]] }));
      return {
        name: s.name, type: 'line', yAxisIndex: s.axis || 0, data: s.data, showSymbol: false, connectNulls: false,
        lineStyle: { width: 1.4, color: colors[s.color] }, itemStyle: { color: colors[s.color] },
        markPoint: marks?.length ? {
          symbol: 'circle', symbolSize: 7, itemStyle: { color: 'transparent', borderColor: p.text, borderWidth: 1.5 }, data: marks,
        } : undefined,
      };
    });
    const axis = (kind, extra = {}) => ({
      ...option.yAxis,
      scale: extra.position ? true : spec.bars.length === 0,
      axisLabel: { color: p.dim, fontSize: 10, formatter: AXIS[kind] },
      ...extra,
    });
    return {
      ...option,
      grid: { ...option.grid, left: 52, right: spec.right ? 52 : 16, bottom: 52 },
      legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9, type: 'scroll' },
      tooltip: {
        ...option.tooltip,
        valueFormatter: undefined,
        formatter: (items) => {
          const list = [].concat(items);
          const rows = list.map((it) => {
            const text = it.value === null || it.value === undefined ? DASH : FORMAT[kindOf[it.seriesName]](it.value);
            return `${it.marker}${it.seriesName} <b>${text}</b>`;
          });
          const extra = (notes[list[0]?.dataIndex] || []).map((note) => `<i>${note}</i>`);
          return [list[0]?.axisValue ?? '', ...rows, ...extra].join('<br>');
        },
      },
      xAxis: { ...option.xAxis, data: labels, boundaryGap: spec.bars.length > 0 },
      yAxis: spec.right ? [axis(spec.left), axis(spec.right, { position: 'right', splitLine: { show: false } })] : axis(spec.left),
      series: [...bars, ...lines],
    };
  });
}

// The six charts of the grid, in TREND_TITLES order.
function trendSpecs(s) {
  return [
    { left: 'money', right: 'pct',
      bars: [{ name: 'Revenue', data: s.revenue, color: 'revenue', kind: 'money' }],
      lines: [{ name: 'Revenue growth', data: s.growth, color: 'growth', kind: 'growth', axis: 1 }] },
    { left: 'pct', right: null,
      bars: [],
      lines: [
        { name: 'Gross margin', data: s.gross, color: 'gross', kind: 'pct' },
        { name: 'Operating margin', data: s.operating, color: 'operating', kind: 'pct' },
        { name: 'Net margin', data: s.net, color: 'net', kind: 'pct', marks: s.oneOff.flatMap((one, i) => (one ? [i] : [])) },
      ] },
    { left: 'money', right: 'eps',
      bars: [{ name: 'Net income', data: s.netIncome, color: 'netIncome', kind: 'money' }],
      lines: [{ name: 'Diluted EPS', data: s.eps, color: 'eps', kind: 'eps', axis: 1 }] },
    { left: 'money', right: 'pct',
      bars: [{ name: 'Free cash flow', data: s.fcf, color: 'fcf', kind: 'money' }],
      lines: [{ name: 'FCF margin', data: s.fcfMargin, color: 'fcfMargin', kind: 'pct', axis: 1 }] },
    { left: 'pct', right: null,
      bars: [],
      lines: [
        { name: 'ROE', data: s.roe, color: 'roe', kind: 'pct' },
        { name: 'ROIC', data: s.roic, color: 'roic', kind: 'pct' },
      ] },
    { left: 'money', right: null,
      bars: [
        { name: 'Cash & short-term investments', data: s.cash, color: 'cash', kind: 'money' },
        { name: 'Total debt', data: s.debt, color: 'debt', kind: 'money' },
      ],
      lines: [{ name: 'Net debt', data: s.netDebt, color: 'netDebt', kind: 'money' }] },
  ];
}

// Redraws the six charts for one mode. Charts share a connect group, so a
// hover on one moves the tooltip on all six.
function drawGrid(nodes, company, mode) {
  const series = seriesFor(company, mode);
  const notes = pointNotes(series);
  const charts = trendSpecs(series).map((spec, i) => drawTrend(nodes[i], series.labels, spec, notes));
  charts.forEach((chart) => { if (chart) chart.group = TREND_GROUP; });
  globalThis.window?.echarts?.connect?.(TREND_GROUP);
}

// ANNUAL | QUARTERLY | TTM. The quarterly views are disabled when the artifact
// has no quarters.
function modeSwitch(company, mode, onPick) {
  const available = (id) => id === 'annual' || hasQuarters(company);
  const buttons = MODES.map((id) => el('button', {
    type: 'button',
    text: MODE_LABELS[id],
    disabled: available(id) ? null : '',
    title: available(id) ? null : NO_QUARTERS,
    'aria-pressed': String(id === mode),
    onclick: () => {
      if (!available(id) || id === mode) return;
      mode = id;
      buttons.forEach((b, i) => b.setAttribute('aria-pressed', String(MODES[i] === id)));
      onPick(id);
    },
  }));
  return el('div', { class: 'period-switch fund-mode' }, buttons);
}

function trendGrid(nodes) {
  return el('div', { class: 'fund-grid' }, TREND_TITLES.map((title, i) => el('div', { class: 'fund-cell' }, [
    el('div', { class: 'fund-title', text: title }),
    nodes[i],
  ])));
}

function companyHeader(company) {
  const predecessor = company.source_ciks.length > 1
    ? ` · history continued from predecessor CIK ${company.source_ciks.slice(1).join(', ')}`
    : '';
  return el('div', { class: 'field-note' }, [
    `${company.name || company.entity_name} · ${company.sector || DASH} · SEC: ${company.entity_name}, CIK ${company.cik}${predecessor} · `,
    el('a', { href: company.source_url, target: '_blank', rel: 'noopener', text: 'company facts' }),
  ]);
}

// One company's statements into `host`. Returns a one-line status; throws
// when the company has no statements in this build.
export async function renderStatements(host, symbol, data) {
  const company = await loadCompany(symbol);
  host.innerHTML = '';
  const nodes = TREND_TITLES.map(() => el('div', { class: 'chart fund-chart' }));
  let mode = defaultMode(company);
  const switcher = modeSwitch(company, mode, (next) => {
    mode = next;
    drawGrid(nodes, company, mode);
  });
  host.append(card(`${symbol} — FUNDAMENTAL TRENDS`, switcher, [
    companyHeader(company),
    trendGrid(nodes),
  ]));
  for (const statement of Object.values(data.statements)) {
    host.append(card(statement.label, null, statementTable(company, statement)));
  }
  host.append(card('KEY RATIOS', null, ratioTable(company, data.ratios)));
  host.append(el('details', { class: 'method-fold' }, [el('summary', { text: 'ⓘ METHOD & DATA' }), el('div', { class: 'method-copy', text: data.note })]));
  drawGrid(nodes, company, mode);
  const last = company.columns[company.columns.length - 1];
  return `${company.columns.length} fiscal years · latest FY${last.fiscal_year} (period end ${last.period_end})`;
}
