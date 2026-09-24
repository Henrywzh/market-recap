// FINANCIALS: ten fiscal years of filed statements for any index member.
//
// Every number is the company's own XBRL fact as most recently filed. A blank
// is a line the filer did not tag -- never a zero -- and each column says when
// it was last filed, because a restated year is a different claim from the
// original one.

import { el, card, table, num, pct, sectionTitle, notice, gap, DASH } from '../fmt.js';
import { render, SERIES_COLORS } from '../charts.js';

const FINANCIALS_BASE = 'artifacts/financials';
const MILLION = 1e6;
const BILLION = 1e9;

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

function trendChart(node, company) {
  const years = company.columns.map((c) => `FY${c.fiscal_year}`);
  const inBillions = (values) => values.map((v) => (v === null ? null : v / BILLION));
  const bars = {
    Revenue: inBillions(company.values.revenue),
    'Operating income': inBillions(company.values.ebit),
    'Free cash flow': inBillions(company.ratios.free_cash_flow),
  };
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, right: 52, bottom: 52 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    xAxis: { ...option.xAxis, data: years, boundaryGap: true },
    yAxis: [
      { ...option.yAxis, scale: false, axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => `$${v}B` } },
      { ...option.yAxis, scale: false, splitLine: { show: false },
        axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => `${v}%` } },
    ],
    series: [
      ...Object.entries(bars).map(([name, data], i) => ({
        name, type: 'bar', data, barMaxWidth: 16, itemStyle: { color: SERIES_COLORS[i] },
      })),
      { name: 'Operating margin', type: 'line', yAxisIndex: 1, data: company.ratios.operating_margin,
        showSymbol: true, symbolSize: 4, lineStyle: { width: 1.2, color: p.text }, itemStyle: { color: p.text } },
    ],
  }));
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

export default async function renderFinancials(root, data) {
  root.append(sectionTitle('FINANCIALS', 'FILED ANNUAL STATEMENTS · SEC XBRL'));

  if (!data.available || !data.available.length) {
    root.append(gap('No statements were extracted in this build. Run the refresh command without --skip-sec.'));
    return;
  }

  const names = new Map(data.available.map((c) => [c.ticker, c.name]));
  const requestedTicker = new URLSearchParams(location.search).get('ticker')?.toUpperCase();
  const tickerInput = el('input', { id: 'fin-ticker', value: requestedTicker || (names.has('AAPL') ? 'AAPL' : data.available[0].ticker), size: '8', list: 'fin-list' });
  const datalist = el('datalist', { id: 'fin-list' },
    data.available.map((c) => el('option', { value: c.ticker, text: c.name || '' })));
  const skippedCount = Object.keys(data.skipped || {}).length;
  const status = el('span', { class: 'field-note', text: '' });
  const host = el('div', {});

  const coverage = `${data.available.length} of ${data.universe} members of ${data.indices.join(' + ')} extracted`;
  const skippedList = skippedCount
    ? el('details', { class: 'field-note' }, [
      el('summary', { text: `${skippedCount} not extracted — why` }),
      table(['TICKER', 'REASON'], Object.entries(data.skipped).map(([t, reason]) => el('tr', {}, [
        el('td', { text: t }), el('td', { class: 'wrap-cell', text: reason }),
      ]))),
    ])
    : null;

  root.append(card('COMPANY', null, [
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field' }, [el('label', { text: 'TICKER' }), tickerInput]),
      el('button', { class: 'action', text: 'LOAD', onclick: () => load() }),
      status,
      datalist,
    ]),
    el('div', { class: 'field-note', text: coverage }),
    skippedList,
  ]));
  root.append(host);

  async function load() {
    const symbol = tickerInput.value.trim().toUpperCase();
    status.textContent = `Loading ${symbol}…`;
    try {
      const company = await loadCompany(symbol);
      host.innerHTML = '';
      const chartNode = el('div', { class: 'chart' });
      host.append(card(`${symbol} — REVENUE, OPERATING INCOME, FREE CASH FLOW ($B) & OPERATING MARGIN`, null, [
        companyHeader(company),
        chartNode,
      ]));
      for (const statement of Object.values(data.statements)) {
        host.append(card(statement.label, null, statementTable(company, statement)));
      }
      host.append(card('KEY RATIOS', null, ratioTable(company, data.ratios)));
      host.append(notice(data.note));
      trendChart(chartNode, company);
      const last = company.columns[company.columns.length - 1];
      status.textContent = `${company.columns.length} fiscal years · latest FY${last.fiscal_year} (period end ${last.period_end})`;
    } catch (error) {
      host.innerHTML = '';
      status.textContent = error.message;
    }
  }

  tickerInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') load(); });
  await load();
}
