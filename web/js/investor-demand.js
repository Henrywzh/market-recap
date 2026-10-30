// FLOWS -> INVESTOR DEMAND: who bought US stocks, by holder, from the Fed's Z.1
// (quarterly), and foreign buying from Treasury's TIC (monthly). Each holder is
// a tile with its quarter, its last three years as bars and its four-quarter
// sum; one chart compares them; the exact figures and the Z.1-vs-TIC
// reconciliation sit beneath. Colours: green/red only ever mean bought/sold;
// the holders in the chart take the categorical palette.

import { el, card, num, tag, periodSwitch, DASH } from './fmt.js';
import { render, SERIES_COLORS } from './charts.js';

const finite = Number.isFinite;
const NS = 'http://www.w3.org/2000/svg';

// The holders, in the chart's colour order. ``history`` names z1.history's field.
export const HOLDERS = [
  { key: 'households', name: 'Households', history: 'households', note: 'Residual sector: includes nonprofits and estimation error, not just retail brokerage flow.' },
  { key: 'foreign', name: 'Foreign investors', history: 'foreign', note: 'Rest of the world, excluding purchases of US fund shares.' },
  { key: 'etfs', name: 'ETFs', history: 'etfs', note: 'Exchange-traded funds as a holder of US corporate equities.' },
  { key: 'mutual_funds', name: 'Mutual funds', history: 'mutual_funds', note: 'The funds\' portfolio trades, not investors\' redemptions.' },
  { key: 'pensions', name: 'Pensions', history: 'pensions', note: 'Private, federal and state & local retirement funds together.' },
];

export function signedBn(v, digits = 1) {
  if (!finite(v)) return DASH;
  const abs = Math.abs(v);
  const text = abs >= 1000 ? `$${num(abs / 1000, 2)}T` : `$${num(abs, digits)}B`;
  return (v > 0 ? '+' : v < 0 ? '−' : '') + text;
}

const tone = (v) => (finite(v) ? (v > 0 ? 'up' : v < 0 ? 'down' : '') : 'dim');

// Rolling four-quarter sums; a window with a gap is a gap.
export function rolling4(values) {
  return (values || []).map((_, i, a) => {
    if (i < 3) return null;
    const window = a.slice(i - 3, i + 1);
    return window.every(finite) ? window.reduce((s, v) => s + v, 0) : null;
  });
}

// Bars around zero for a tile: the last ``n`` values, up green, down red.
function miniBars(values, n = 12, { width = 132, height = 30 } = {}) {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('class', 'idm-bars');
  svg.setAttribute('preserveAspectRatio', 'none');
  const tail = (values || []).slice(-n);
  const reach = Math.max(1e-9, ...tail.filter(finite).map(Math.abs));
  const mid = height / 2;
  const step = width / Math.max(tail.length, 1);
  tail.forEach((v, i) => {
    if (!finite(v)) return;
    const h = Math.max(1, (Math.abs(v) / reach) * (mid - 1));
    const rect = document.createElementNS(NS, 'rect');
    rect.setAttribute('x', String(i * step + step * 0.15));
    rect.setAttribute('width', String(step * 0.7));
    rect.setAttribute('y', String(v >= 0 ? mid - h : mid));
    rect.setAttribute('height', String(h));
    rect.setAttribute('class', `${v >= 0 ? 'up' : 'down'}${i === tail.length - 1 ? ' last' : ''}`);
    svg.append(rect);
  });
  const axis = document.createElementNS(NS, 'line');
  axis.setAttribute('x1', '0'); axis.setAttribute('x2', String(width));
  axis.setAttribute('y1', String(mid)); axis.setAttribute('y2', String(mid));
  axis.setAttribute('class', 'idm-axis');
  svg.append(axis);
  return svg;
}

function holderTile(holder, group, history) {
  const v = group?.latest_bn;
  const verb = finite(v) ? (v > 0 ? 'BOUGHT' : v < 0 ? 'SOLD' : 'FLAT') : 'NO DATA';
  const ttmChange = group?.ttm_change_bn;
  return el('div', { class: `idm-tile ${tone(v)}`, title: group?.note || holder.note }, [
    el('div', { class: 'idm-tile-head' }, [el('span', { class: 'idm-name', text: holder.name }), el('span', { class: `idm-verb ${tone(v)}`, text: verb })]),
    el('div', { class: `idm-value ${tone(v)}`, text: signedBn(v) }),
    el('div', { class: 'idm-sub', text: `in ${group?.latest_quarter || DASH} · QoQ ${signedBn(group?.qoq_bn)}` }),
    miniBars(history),
    el('div', { class: 'idm-foot' }, [
      el('span', {}, [el('span', { class: 'dim', text: '4Q ' }), el('strong', { class: tone(group?.ttm_4q_bn), text: signedBn(group?.ttm_4q_bn) })]),
      el('span', {}, [el('span', { class: 'dim', text: 'YTD ' }), el('strong', { class: tone(group?.ytd_bn), text: signedBn(group?.ytd_bn) })]),
      finite(ttmChange) ? el('span', { class: 'dim', title: '4-quarter sum against the 4 quarters before it', text: `${ttmChange >= 0 ? '▲' : '▼'} ${signedBn(ttmChange)} vs prior 4Q` }) : null,
    ]),
  ]);
}

function holderChart(node, h, view, years) {
  const n = years ? years * 4 : h.quarters.length;
  const start = Math.max(0, h.quarters.length - n);
  const shape = (values) => (view === '4Q' ? rolling4(values) : values || []).slice(start);
  render(node, (option, p) => ({
    ...option,
    grid: { left: 58, right: 16, top: 34, bottom: 28 },
    legend: { top: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: (v) => signedBn(v) },
    xAxis: { ...option.xAxis, data: h.quarters.slice(start) },
    yAxis: { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => signedBn(v, 0) } },
    series: HOLDERS.map((holder, i) => ({
      name: holder.name, type: 'bar', stack: 'flow', stackStrategy: 'samesign', barMaxWidth: 18,
      data: shape(h[holder.history]), itemStyle: { color: SERIES_COLORS[i] },
      emphasis: { focus: 'series' },
    })),
  }));
}

function demandTable(z1) {
  const groups = Object.fromEntries((z1.groups || []).map((g) => [g.key, g]));
  const rows = HOLDERS.map((h) => [h.name, groups[h.key], false, groups[h.key]?.note || h.note]);
  for (const c of z1.pension_components || []) rows.push([c.label, c, true, '']);
  const nfc = z1.corporate_net_retirement_broad;
  const reach = Math.max(1, ...rows.map(([, g]) => Math.abs(g?.ttm_4q_bn || 0)));
  const bar = (v) => el('td', { class: 'idm-bar-cell' }, finite(v) ? [el('span', { class: 'idm-bar-track' }, [
    el('span', { class: `idm-bar ${v >= 0 ? 'up' : 'down'}`, style: `width:${(Math.abs(v) / reach) * 50}%;${v >= 0 ? 'left:50%' : `right:50%`}` }),
  ])] : []);
  const line = ([label, g, sub, note]) => el('tr', { class: sub ? 'idm-sub-row' : '', title: note }, [
    el('td', { text: sub ? `└ ${label}` : label }),
    el('td', { class: tone(g?.latest_bn), text: signedBn(g?.latest_bn, 1) }),
    el('td', { class: tone(g?.qoq_bn), text: signedBn(g?.qoq_bn, 1) }),
    el('td', { class: tone(g?.ytd_bn), text: signedBn(g?.ytd_bn, 1) }),
    el('td', { class: tone(g?.ttm_4q_bn), text: signedBn(g?.ttm_4q_bn, 1) }),
    bar(g?.ttm_4q_bn),
  ]);
  const body = [...rows.map(line)];
  if (nfc) {
    body.push(el('tr', { class: 'idm-section-row' }, [el('td', { colspan: '6', text: 'SUPPLY · COMPANIES' })]));
    body.push(line(['Nonfinancial corporates · net retirement (broad)', nfc, false, '−FU103164105.Q: shares retired less shares issued by nonfinancial companies, including private M&A.']));
  }
  return el('div', { class: 'table-scroll' }, [el('table', { class: 'data idm-table' }, [
    el('thead', {}, [el('tr', {}, [`HOLDER · ${z1.latest_quarter || ''}`, 'QUARTER', 'VS PRIOR Q', 'YTD', '4Q SUM', '4Q SUM · SCALE'].map((t) => el('th', { text: t })))]),
    el('tbody', {}, body),
  ])]);
}

function z1Card(z1) {
  const groups = Object.fromEntries((z1.groups || []).map((g) => [g.key, g]));
  const h = z1.history || { quarters: [] };
  const recon = z1.reconciliation || {};
  // Buyers first, by the quarter's purchases.
  const ordered = [...HOLDERS].sort((a, b) => (groups[b.key]?.latest_bn ?? -Infinity) - (groups[a.key]?.latest_bn ?? -Infinity));
  const chart = el('div', { class: 'chart idm-chart', 'aria-label': 'Net purchases of US corporate equities by holder' });
  let view = 'QUARTER';
  let years = 5;
  const title = el('span', { class: 'idm-tools-title' });
  const draw = () => {
    title.textContent = view === 'ROLLING 4Q' ? 'NET PURCHASES · ROLLING 4 QUARTERS' : 'NET PURCHASES · EACH QUARTER';
    requestAnimationFrame(() => holderChart(chart, h, view === 'ROLLING 4Q' ? '4Q' : 'Q', years));
  };
  draw();
  return card('WHO BOUGHT US STOCKS · BY HOLDER', tag(`${z1.latest_quarter || DASH} · Z.1 · NEXT ${z1.next_release || DASH}`, 'dim'), [
    el('div', { class: 'idm-tiles' }, ordered.map((holder) => holderTile(holder, groups[holder.key], h[holder.history]))),
    el('div', { class: 'idm-tools' }, [
      title,
      periodSwitch(['QUARTER', 'ROLLING 4Q'], view, (v) => { view = v; draw(); }),
      periodSwitch(['5Y', '10Y'], `${years}Y`, (v) => { years = Number(v.replace('Y', '')); draw(); }),
    ]),
    chart,
    el('div', { class: 'field-note', text: 'Click a holder in the legend to hide it, double-click to show it alone. Bars above zero bought, below sold; a holder\'s buying and another\'s selling are not netted.' }),
    demandTable(z1),
    el('details', { class: 'rc-method' }, [el('summary', { text: 'Source & method' }), el('p', { class: 'rc-note', text:
      `Fed Financial Accounts Z.1, ${z1.basis || 'unadjusted quarterly transactions'}, released ${z1.released || DASH}; next release ${z1.next_release || DASH}. `
      + `Net purchases of US corporate equities by holding sector, in billions of dollars in the quarter. The accounting identity (holders sum to issuance) is checked across ${recon.all_quarters_checked || DASH} quarters (${z1.first_quarter || DASH}–${z1.latest_quarter || DASH}): `
      + `largest holder residual $${num((recon.holder_identity_max_residual_bn || 0) * 1000, 1)}M, largest issuer residual $${num((recon.issuer_identity_max_residual_bn || 0) * 1000, 1)}M. `
      + 'Households are the residual sector, so their line also carries every other sector\'s measurement error. Transactions, company cash payments and hedge-fund exposures measure different things and are never added together.' })]),
  ]);
}

function foreignChart(node, tm, years) {
  const n = years ? years * 12 : tm.months.length;
  const start = Math.max(0, tm.months.length - n);
  const values = tm.values_bn.slice(start);
  const avg = tm.values_bn.map((_, i, a) => (i >= 2 && a.slice(i - 2, i + 1).every(finite) ? (a[i - 2] + a[i - 1] + a[i]) / 3 : null)).slice(start);
  render(node, (option, p) => ({
    ...option,
    grid: { left: 58, right: 16, top: 30, bottom: 28 },
    legend: { top: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: (v) => signedBn(v) },
    xAxis: { ...option.xAxis, data: tm.months.slice(start) },
    yAxis: { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => signedBn(v, 0) } },
    series: [
      { name: 'Net purchases in the month', type: 'bar', barMaxWidth: 14, data: values.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? p.up : p.down } })), itemStyle: { color: p.up } },
      { name: '3-month average', type: 'line', showSymbol: false, data: avg, lineStyle: { color: p.accent, width: 2 }, itemStyle: { color: p.accent } },
    ],
  }));
}

function foreignCard(foreign, z1) {
  const tm = foreign.tic_monthly || { months: [], values_bn: [] };
  const sb = foreign.scope_bridge || {};
  const z1For = (z1.groups || []).find((g) => g.key === 'foreign') || {};
  const chart = el('div', { class: 'chart idm-chart short-ish', 'aria-label': 'Foreign net purchases of US equities by month' });
  let years = 3;
  const draw = () => requestAnimationFrame(() => foreignChart(chart, tm, years));
  draw();
  const stat = (label, value, note) => el('div', { class: 'idm-stat' }, [
    el('span', { class: 'idm-name', text: label }), el('strong', { class: `idm-value ${tone(value)}`, text: signedBn(value) }), el('span', { class: 'idm-sub', text: note }),
  ]);
  const bridgeRows = (sb.rows || []).slice(-8).reverse().map((r) => el('tr', {}, [
    el('td', { text: r.quarter }),
    el('td', { class: tone(r.tic_broad_bn), text: signedBn(r.tic_broad_bn, 2) }),
    el('td', { text: signedBn(r.bea_broad_bn, 2) }),
    el('td', { text: signedBn(r.fund_shares_bn, 2) }),
    el('td', { class: tone(r.fed_ex_funds_bn), text: signedBn(r.fed_ex_funds_bn, 2) }),
    el('td', { class: 'dim', text: signedBn(r.scope_aligned_diff_bn, 2) }),
  ]));
  return card('FOREIGN BUYING · MONTHLY', tag(`TIC THROUGH ${foreign.tic_latest_month || DASH}`, 'dim'), [
    el('div', { class: 'idm-stats' }, [
      stat('LATEST MONTH', foreign.tic_latest_bn, foreign.tic_latest_month || DASH),
      stat('LAST 3 MONTHS', foreign.tic_3m_sum_bn, 'sum'),
      stat('LAST 12 MONTHS', foreign.tic_12m_sum_bn, 'sum'),
      stat('Z.1 · QUARTER', z1For.latest_bn, `${z1For.latest_quarter || DASH} · excludes fund shares`),
    ]),
    el('div', { class: 'idm-tools' }, [el('span', { class: 'idm-tools-title', text: 'FOREIGN NET PURCHASES OF US STOCKS · TREASURY TIC' }), periodSwitch(['3Y', 'MAX'], '3Y', (v) => { years = v === 'MAX' ? null : 3; draw(); })]),
    chart,
    el('details', { class: 'rc-method' }, [
      el('summary', { text: 'Z.1 vs TIC · how the two sources reconcile' }),
      el('p', { class: 'rc-note', text: `TIC counts foreign purchases of US equities including fund shares; Z.1's foreign line excludes them. Raw gap ${finite(sb.raw_mean_abs_diff_bn) ? `$${num(sb.raw_mean_abs_diff_bn, 1)}B` : DASH} a quarter on average across ${sb.matched_quarters || DASH} complete quarters; ${finite(sb.scope_aligned_mean_abs_diff_bn) ? `$${num(sb.scope_aligned_mean_abs_diff_bn, 2)}B once fund shares are taken out of the broad series.` : 'the scope-aligned gap is unavailable this build.'}` }),
      el('div', { class: 'table-scroll' }, [el('table', { class: 'data' }, [
        el('thead', {}, [el('tr', {}, ['QUARTER', 'TIC · 3-MONTH SUM', 'BEA/FED BROAD', 'LESS FUND SHARES', 'Z.1 EX-FUNDS', 'RESIDUAL'].map((c) => el('th', { text: c })))]),
        el('tbody', {}, bridgeRows),
      ])]),
      el('p', { class: 'rc-note', text: sb.note || '' }),
    ]),
  ]);
}

export function investorDemandView(dp) {
  if (!dp || dp.unavailable) return [];
  return [
    dp.z1?.groups?.length ? z1Card(dp.z1) : null,
    dp.foreign?.tic_monthly ? foreignCard(dp.foreign, dp.z1 || {}) : null,
  ].filter(Boolean);
}
