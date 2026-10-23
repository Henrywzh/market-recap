// FLOWS section B: who holds the index futures, by trader type. One card per
// contract: each category's net position as a share of open interest over
// three years of weekly reports, the latest table, and a check of the S&P 500
// trend model against leveraged money in the E-mini.

import { el, card, table, num, DASH } from './fmt.js';
import { render } from './charts.js';
import { rangeSwitch, sliceRange, initialRange } from './range.js';

const MINUS = '−';
export const CATEGORY_ORDER = ['dealer', 'asset_mgr', 'lev_money', 'other', 'nonrept'];
// The four lines on the chart; non-reportables appear in the table only.
export const CHART_CATEGORIES = ['dealer', 'asset_mgr', 'lev_money', 'other'];
const CHART_TONE = { dealer: (p) => p.blue, asset_mgr: (p) => p.purple, lev_money: (p) => p.accent, other: (p) => p.dim };

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const sign = (v) => (v > 0 ? '+' : v < 0 ? MINUS : '');

// Signed number with a true minus sign, so a fall reads as a fall in any font.
export function signedNum(value, digits = 0) {
  if (!present(value)) return DASH;
  const rounded = Math.abs(value) < 0.5 * 10 ** -digits ? 0 : value;
  return `${sign(rounded)}${num(Math.abs(rounded), digits)}`;
}

// Dollar notional in billions, signed: "+$41.50bn", "−$235.08bn".
export function signedBn(value) {
  if (!present(value)) return DASH;
  return `${sign(value)}$${num(Math.abs(value), 2)}bn`;
}

// Percent of open interest, one decimal, signed: "−21.2%".
export function signedPct(value, digits = 1) {
  if (!present(value)) return DASH;
  return `${signedNum(value, digits)}%`;
}

// Ordinal for a percentile: 1st, 2nd, 3rd, 11th, 21st.
export function ordinal(n) {
  const r = Math.round(n);
  const tens = r % 100;
  if (tens >= 11 && tens <= 13) return `${r}th`;
  return `${r}${['th', 'st', 'nd', 'rd'][r % 10] || 'th'}`;
}

export function percentileText(value) {
  return present(value) ? `${ordinal(value)} pct` : DASH;
}

export function zText(value) {
  return present(value) ? `z ${signedNum(value, 2)}` : DASH;
}

// The trend check as one plain sentence. Labelled a check: a correlation over
// three years of weekly reports says how the two co-move, not that either predicts the other.
export function trendCheckLine(check) {
  if (!check) return 'Trend check not built this session.';
  if (check.unavailable) return `Trend check not built this session: ${check.unavailable}.`;
  const rows = (check.categories || []).filter(Boolean);
  if (!rows.length) return 'Trend check not built this session.';
  const corr = (v) => (present(v) ? signedNum(v, 2) : DASH);
  const parts = rows.map((r) => `${r.label}: four-week changes ${corr(r.corr_changes_4w)}, levels ${corr(r.corr_levels)}`);
  const n = Math.max(...rows.map((r) => r.n || 0));
  return `Correlation with the S&P 500 trend model over ${n} weekly reports — ${parts.join('; ')} (model position as of ${check.position_as_of || DASH}). A check, not a validation.`;
}

// Table rows from a contract's categories: strings only, never a raw null.
export function categoryRows(contract) {
  const byKey = Object.fromEntries((contract.categories || []).map((c) => [c.key, c]));
  return CATEGORY_ORDER.filter((key) => byKey[key]).map((key) => {
    const c = byKey[key];
    return {
      key,
      label: c.label,
      net: signedNum(c.net, 0),
      usd: signedBn(c.net_usd_bn),
      pct: signedPct(c.net_pct_oi, 1),
      change: signedNum(c.change_1w, 0),
      pctile: percentileText(c.pctile_3y),
      z: zText(c.z_3y),
    };
  });
}

// Share of open interest per category, each chart line sliced to a range.
export function chartLines(contract, dates, range) {
  const sliced = sliceRange(dates, Object.fromEntries(CHART_CATEGORIES.map((k) => [k, contract.history.categories[k] || []])), range);
  return CHART_CATEGORIES.map((key) => ({
    key,
    label: (contract.categories || []).find((c) => c.key === key)?.label || key,
    values: sliced[key],
    dates: sliced.dates,
  }));
}

function linesChart(node, dates, lines) {
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 52, right: 16, top: 12, bottom: 44 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, valueFormatter: (x) => (present(x) ? `${signedNum(x, 1)}%` : DASH) },
    xAxis: { ...option.xAxis, data: dates },
    yAxis: { ...option.yAxis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => num(v, 0) } },
    series: lines.map((line, i) => ({
      name: line.label,
      type: 'line',
      data: line.values,
      showSymbol: false,
      connectNulls: false,
      lineStyle: { color: CHART_TONE[line.key](p), width: line.key === 'lev_money' ? 1.6 : 1.2 },
      itemStyle: { color: CHART_TONE[line.key](p) },
      ...(i === 0 ? {
        markLine: {
          silent: true, symbol: 'none', data: [{ yAxis: 0 }],
          lineStyle: { color: p.faint, type: 'dashed', width: 1 }, label: { show: false },
        },
      } : {}),
    })),
  }));
}

const METHOD = [
  'Categories in plain words: dealers are banks\' and broker-dealers\' desks; asset managers are pensions, mutual funds and insurers; leveraged money is hedge funds and CTAs, including relative-value and basis positions; other reportables are other large traders that report; non-reportables are small traders that do not.',
  'Positions are as of Tuesday and published the following Friday, three days later. Futures only: no cash, no options. Net is long minus short; % OI divides net by total open interest, so the share stays comparable as open interest grows.',
  'Percentile and z compare the latest net % OI with the last 156 weekly reports (three years). The one-week change is in contracts, and only where the last two reports are seven days apart.',
  'Dollar value is net contracts × multiplier × the cash index close on the report date, not the futures settlement, so it is approximate for all four contracts (it ignores the futures basis). For the VIX future the close is the spot VIX.',
];

function contractCard(contract, dates, extra = null) {
  const title = `${contract.label} · WHO HOLDS THE FUTURES`;
  if (contract.unavailable) {
    return card(title, null, el('div', { class: 'gap', text: `Not built this session: ${contract.unavailable}.` }));
  }
  const hasClose = present(contract.price?.close);
  const priceNote = hasClose
    ? `${contract.index} close ${num(contract.price.close, 2)} on ${contract.price.date}`
    : `no ${contract.index} close, dollar values blank`;
  const meta = `Tuesday ${contract.report_date} · known Friday ${contract.released} · open interest ${num(contract.open_interest, 0)} contracts · ${priceNote}${contract.approximate ? ' (approximate)' : ''}`;
  let range = initialRange(dates, '3Y');
  const node = el('div', { class: 'chart flows-cot-chart', 'aria-label': `${contract.label}: net positions as a share of open interest by trader type` });
  const draw = () => {
    const lines = chartLines(contract, dates, range);
    linesChart(node, lines[0]?.dates || [], lines);
  };
  requestAnimationFrame(draw);
  const grid = table(['CATEGORY', 'NET', '$', '% OI', '1W CHANGE', '3Y PCTILE'],
    categoryRows(contract).map((row) => el('tr', {}, [
      el('td', { text: row.label }),
      el('td', { text: row.net }),
      el('td', { text: row.usd }),
      el('td', { text: row.pct }),
      el('td', { text: row.change }),
      el('td', { text: `${row.pctile} · ${row.z}` }),
    ])));
  return card(title, rangeSwitch(dates, range, (label) => { range = label; draw(); }), [
    el('div', { class: 'field-note', text: meta }),
    el('div', { class: 'field-note', text: 'Net position as % of open interest, by trader type, weekly.' }),
    node,
    grid,
    extra,
    el('details', { class: 'sx-fold' }, [
      el('summary', { text: 'Method & limits' }),
      ...METHOD.map((text) => el('div', { class: 'note-text', text })),
      el('div', { class: 'note-text', text: `History starts ${dates[0] || DASH}; a contract launched later starts later.` }),
    ]),
  ]);
}

// The card set for one session's section. Handles a failed section, no reports and a missing contract.
export function section(data) {
  if (!data) return [card('WHO HOLDS THE FUTURES · CFTC', null, el('div', { class: 'gap', text: 'Not built this session.' }))];
  if (data.unavailable) return [card('WHO HOLDS THE FUTURES · CFTC', null, el('div', { class: 'gap', text: `Not built this session: ${data.unavailable}.` }))];
  const contracts = data.contracts || [];
  if (!contracts.length) return [card('WHO HOLDS THE FUTURES · CFTC', null, el('div', { class: 'gap', text: 'No published report.' }))];
  return contracts.map((contract) => {
    const dates = contract.history?.dates || [];
    // The trend check sits on the S&P 500 card, under its table.
    const extra = contract.key === 'es'
      ? el('div', { class: 'field-note trend-check', text: trendCheckLine(data.trend_check) })
      : null;
    return contractCard(contract, dates, extra);
  });
}
