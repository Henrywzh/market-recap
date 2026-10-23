// FLOWS section C: who bought US equities, by sector, from the Fed's Z.1
// accounts. Quarterly net purchases by holding sector as stacked bars (buyers
// above zero, sellers below), the nonfinancial net-issues line beside them, and the
// latest quarter by group with its trailing four-quarter sum and percentile.

import { el, card, table, num, DASH } from './fmt.js';
import { render } from './charts.js';

const MINUS = '−';
const present = (v) => v !== null && v !== undefined && Number.isFinite(v);

// Signed dollars in billions, a true minus sign: "+$350.5bn", "−$1,163.6bn".
// Under a billion it reads in millions: "−$310m".
export function signedBn(value, digits = 1) {
  if (!present(value)) return DASH;
  const sign = value > 0 ? '+' : value < 0 ? MINUS : '';
  const a = Math.abs(value);
  if (a < 1 && a > 0) return `${sign}$${num(a * 1000, 0)}m`;
  return `${sign}$${num(a, digits)}bn`;
}

export function ordinal(n) {
  const r = Math.round(n);
  const tens = r % 100;
  if (tens >= 11 && tens <= 13) return `${r}th`;
  return `${r}${['th', 'st', 'nd', 'rd'][r % 10] || 'th'}`;
}

// Percentile of the trailing four-quarter sum since 1990, as "91st pct".
export function pctileText(value) {
  return present(value) ? `${ordinal(value)} pct` : DASH;
}

// Chart tones per group. Up and down are reserved for buying and selling, so no group takes them.
const TONE = {
  households: (p) => p.blue,
  mutual_funds: (p) => p.purple,
  etfs: (p) => p.accent,
  pensions: () => '#22d3ee',
  insurers: () => '#fbbf24',
  rest_of_world: () => '#f472b6',
  broker_dealers: () => '#34d399',
  other: (p) => p.dim,
};
export const GROUP_KEYS = ['households', 'mutual_funds', 'etfs', 'pensions', 'insurers', 'rest_of_world', 'broker_dealers', 'other'];

// Table rows: strings only, never a raw null. The issuer block follows the holder groups.
export function summaryRows(data) {
  const row = (r) => ({
    key: r.key,
    label: r.label,
    latest: signedBn(r.q_bn),
    last4: signedBn(r.trailing_4q_bn, 1),
    pctile: pctileText(r.pctile_4q),
  });
  const latest = data.latest || [];
  const byKey = Object.fromEntries(latest.map((r) => [r.key, r]));
  const holders = GROUP_KEYS.filter((k) => byKey[k]).map((k) => row(byKey[k]));
  const total = byKey.total ? row(byKey.total) : null;
  const issuers = (data.issuers || []).map(row);
  return { holders, total, issuers };
}

// Stacked bars per group plus the nonfinancial net-issues line, on the chart's quarters.
export function chartSeries(history) {
  const groups = history?.groups || {};
  const bars = GROUP_KEYS.filter((k) => Array.isArray(groups[k])).map((key) => ({
    key,
    values: groups[key],
  }));
  const line = Array.isArray(history?.nfc_issues) ? history.nfc_issues : null;
  return { dates: history?.dates || [], bars, line };
}

function flowChart(node, data) {
  const { dates, bars, line } = chartSeries(data.history);
  const labelOf = Object.fromEntries((data.groups || []).map((g) => [g.key, g.label]));
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 56, right: 16, top: 12, bottom: 58 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9, type: 'scroll' },
    tooltip: { ...option.tooltip, valueFormatter: (x) => (present(x) ? signedBn(x, 1) : DASH) },
    xAxis: { ...option.xAxis, data: dates },
    yAxis: { ...option.yAxis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => num(v, 0) } },
    series: [
      ...bars.map((bar) => ({
        name: labelOf[bar.key] || bar.key,
        type: 'bar',
        stack: 'holders',
        data: bar.values,
        barMaxWidth: 10,
        itemStyle: { color: TONE[bar.key](p) },
      })),
      ...(line ? [{
        name: 'Nonfinancial corporate net issues (below zero: net buybacks)',
        type: 'line',
        data: line,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: p.text, width: 1.6 },
        itemStyle: { color: p.text },
      }] : []),
    ],
  }));
}

function groupTable(rows) {
  const body = [];
  for (const r of rows.holders) {
    body.push(el('tr', {}, [el('td', { text: r.label }), el('td', { text: r.latest }), el('td', { text: r.last4 }), el('td', { text: r.pctile })]));
  }
  if (rows.total) {
    body.push(el('tr', { class: 'total' }, [el('td', { text: rows.total.label }), el('td', { text: rows.total.latest }), el('td', { text: rows.total.last4 }), el('td', { text: rows.total.pctile })]));
  }
  if (rows.issuers.length) {
    body.push(el('tr', {}, [el('td', { class: 'dim', text: 'Issuer side' }), el('td'), el('td'), el('td')]));
    for (const r of rows.issuers) {
      body.push(el('tr', {}, [el('td', { text: r.label }), el('td', { text: r.latest }), el('td', { text: r.last4 }), el('td', { text: r.pctile })]));
    }
  }
  return table(['GROUP', 'LATEST Q', 'LAST 4Q', 'PCTILE'], body);
}

const METHOD = [
  'Net purchases of corporate equities by holding sector, from the Fed\'s Z.1 table of corporate equity transactions (F51.1.t, formerly F.224). The series come from FRED\'s non-seasonally-adjusted family: each quarter is that quarter\'s own total, in dollars, so no annual-rate conversion is applied. The seasonally adjusted copies are missing on FRED for households, rest of world and the financial and nonfinancial issuer lines, so one basis is used throughout.',
  'Households are the Fed\'s residual sector: the household line is the one the Fed derives as the balance of the other sectors. Other is everything else in the total: nonfinancial corporates\' holdings of other companies\' shares, banks and depositories, hedge funds, closed-end and other funds, government and other financial business. The groups sum to the total in every quarter.',
  'Buyers are positive and sellers negative. On the issuer side, nonfinancial corporate net issues are new shares less buybacks and shares retired for cash in takeovers: below zero, companies took more stock out of the market than they issued. FRED does not carry that line, so it is derived from the Fed\'s identity: total net issues less the domestic financial and foreign issuer lines. Financial corporate net issues are mostly ETF shares created.',
  'The Fed revises each release, so these are the current vintage only, not what was published at the time. The latest quarter is published about ten weeks after it ends. The next release is on the Fed\'s schedule for 2026:Q3 (noon).',
  'The percentile ranks the latest trailing four-quarter sum against every trailing four-quarter sum since 1990. The percentile is a comparison of paces, not a forecast.',
];

export function section(data) {
  const title = 'WHO BOUGHT US EQUITIES · FED Z.1';
  if (!data) return [card(title, null, el('div', { class: 'gap', text: 'Not built this session.' }))];
  if (data.unavailable) return [card(title, null, el('div', { class: 'gap', text: `Not built this session: ${data.unavailable}.` }))];
  const rows = summaryRows(data);
  if (!rows.total || !(data.history?.dates || []).length) {
    return [card(title, null, el('div', { class: 'gap', text: 'No Z.1 quarters in this build.' }))];
  }
  const meta = `Quarter ${data.latest_quarter} (ended ${data.latest_quarter_end}) · released ${data.released} · next release ${data.next_release} (Z.1 schedule) · $bn per quarter, not seasonally adjusted`;
  const node = el('div', { class: 'chart flows-z1-chart', 'aria-label': 'Quarterly net purchases of US corporate equities by holding sector, with nonfinancial corporate net issues' });
  requestAnimationFrame(() => flowChart(node, data));
  return [card(title, null, [
    el('div', { class: 'field-note', text: meta }),
    el('div', { class: 'field-note', text: 'Net purchases by holder, $bn per quarter. Buyers above zero, sellers below.' }),
    node,
    groupTable(rows),
    el('details', { class: 'sx-fold' }, [
      el('summary', { text: 'Method & limits' }),
      ...METHOD.map((text) => el('div', { class: 'note-text', text })),
      ...(data.not_covered || []).map((text) => el('div', { class: 'note-text', text: `Not covered: ${text}.` })),
      ...(data.revisions ? [el('div', { class: 'note-text', text: data.revisions })] : []),
    ]),
  ])];
}
