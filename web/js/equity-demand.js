// FLOWS demand, repurchase history and exposure context.
import { el, card, num, tag, DASH, gap } from './fmt.js';
import { render } from './charts.js';
const finite = Number.isFinite;
const signed = (v, unit = '') => finite(v) ? (v > 0 ? '+' : '') + num(v, 1) + unit : DASH;
function metric(label, reading, note, tone = '') {
  return el('div', { class: 'rc-metric ' + tone }, [el('span', { class: 'rc-eyebrow', text: label }), el('strong', { class: 'rc-number', text: reading }), el('span', { class: 'rc-note', text: note })]);
}
function signedBn(v, digits = 1) {
  if (!finite(v)) return DASH;
  return (v > 0 ? '+' : v < 0 ? '−' : '') + '$' + num(Math.abs(v), digits) + 'B';
}

function buybackHistory(index) {
  const history = index.history || {};
  const container = el('div', {});
  let frequency = 'quarterly';
  let years = 5;
  let view = 'change';
  function draw() {
    const allRows = history[frequency] || [];
    const rows = years ? allRows.slice(-(frequency === 'annual' ? years : years * 4)) : allRows;
    const recent = rows.slice(-12).reverse();
    const chart = el('div', { class: 'chart rc-breadth-chart' });
    const buttons = el('div', { class: 'period-switch', role: 'group', 'aria-label': 'Buyback frequency' },
      [['quarterly', 'QUARTER'], ['ttm', 'ROLLING 4Q'], ['annual', 'YEAR']].map(([key, label]) =>
        el('button', { type: 'button', text: label, 'aria-pressed': String(key === frequency), onclick: () => { frequency = key; if (key !== 'quarterly' && view === 'ratio') view = 'change'; draw(); } })));
    const ranges = el('div', { class: 'period-switch', role: 'group', 'aria-label': 'Buyback history range' },
      [[3, '3Y'], [5, '5Y'], [null, 'MAX']].map(([n, label]) =>
        el('button', { type: 'button', text: label, 'aria-pressed': String(n === years), onclick: () => { years = n; draw(); } })));
    const views = el('div', { class: 'period-switch', role: 'group', 'aria-label': 'Buyback comparison' },
      [['change', 'MATCHED YoY'], ['absolute', 'TOTAL'], ...(frequency === 'quarterly' ? [['ratio', 'BUYBACK / TRADED VALUE']] : [])].map(([key, label]) =>
        el('button', { type: 'button', text: label, 'aria-pressed': String(key === view), onclick: () => { view = key; draw(); } })));
    container.replaceChildren(
      el('div', { class: 'rc-chart-tools' }, [el('strong', { text: view === 'change' ? 'CHANGE VS YEAR AGO · MATCHED ISSUERS · $B' : view === 'ratio' ? 'BUYBACK CASH / TRADED VALUE · MATCHED ISSUERS' : 'COVERED CASH REPURCHASES · $B' }), views, buttons, ranges]),
      el('p', { class: 'rc-note', text: 'Fiscal quarters are grouped by the calendar quarter in which they end. Current index members are used throughout; this creates survivorship bias. Recent periods may be incomplete, and coverage changes over time.' }),
      rows.length ? chart : gap('No historical cash repurchases are available for this index.'),
      el('div', { class: 'table-scroll' }, [el('table', { class: 'data' }, [
        el('thead', {}, [el('tr', {}, ['PERIOD', 'COVERED REPURCHASES', 'ISSUERS', 'COVERAGE', 'MATCHED YoY $B', 'MATCHED YoY %', 'MATCHED ISSUERS', ...(frequency === 'quarterly' ? ['BUYBACK / TRADED', 'RATIO ISSUERS'] : [])].map((x) => el('th', { text: x })))]),
        el('tbody', {}, recent.map((r) => el('tr', {}, [
          el('td', { text: r.period + (r.period_ended ? '' : ' · IN PROGRESS') }),
          el('td', { text: finite(r.covered_sum_bn) ? '$' + num(r.covered_sum_bn, 2) + 'B' : DASH }),
          el('td', { text: r.covered_issuers + ' / ' + r.total_issuers }),
          el('td', { text: finite(r.coverage_pct) ? num(r.coverage_pct, 1) + '%' : DASH }),
          el('td', { text: signedBn(r.matched_yoy?.change_bn, 2) }),
          el('td', { text: finite(r.matched_yoy?.change_pct) ? signed(r.matched_yoy.change_pct, '%') : DASH }),
          el('td', { text: r.matched_yoy?.issuers ?? DASH }),
          ...(frequency === 'quarterly' ? [el('td', { text: finite(r.trading_value_comparison?.ratio_pct) ? num(r.trading_value_comparison.ratio_pct, 2) + '%' : DASH }), el('td', { text: r.trading_value_comparison?.issuers ?? DASH })] : []),
        ]))),
      ])]),
      el('p', { class: 'rc-note', text: 'YoY compares only issuers with both periods reported. Ratio compares cash repurchases with close × volume for the same issuers and fiscal periods; each share class requires at least 90% session coverage. Fiscal end dates differ, current constituents create survivorship bias, and coverage varies. Cash payments (including ASR prepayments) can occur at different times from market purchases. Traded value is a proxy, not net inflow, order flow or price impact; historical filings may include later revisions.' }),
    );
    if (rows.length) requestAnimationFrame(() => render(chart, (option, p) => ({
      ...option,
      legend: { top: 0, textStyle: { color: p.dim, fontSize: 10 } },
      grid: { left: 55, right: 48, top: 30, bottom: 30 },
      xAxis: { ...option.xAxis, data: rows.map((r) => r.period), boundaryGap: true },
      yAxis: [{ ...option.yAxis, min: view === 'change' ? undefined : 0, axisLabel: { color: p.dim, formatter: (v) => view === 'ratio' ? num(v, 1) + '%' : '$' + num(v, 0) + 'B' } },
        { ...option.yAxis, min: 0, max: 100, axisLabel: { color: p.dim, formatter: '{value}%' }, splitLine: { show: false } }],
      series: [
        { name: view === 'change' ? 'Matched YoY change ($B)' : view === 'ratio' ? 'Buyback / traded value (%)' : 'Covered buybacks ($B)', type: 'bar', data: rows.map((r) => view === 'change' ? r.matched_yoy?.change_bn ?? null : view === 'ratio' ? r.trading_value_comparison?.ratio_pct ?? null : r.covered_sum_bn), itemStyle: { color: p.blue } },
        { name: 'Issuer coverage (%)', type: 'line', yAxisIndex: 1, data: rows.map((r) => view === 'ratio' ? (r.total_issuers ? 100 * (r.trading_value_comparison?.issuers || 0) / r.total_issuers : null) : r.coverage_pct), showSymbol: false, itemStyle: { color: p.accent }, lineStyle: { color: p.accent, width: 2 } },
      ],
    })));
  }
  draw();
  return container;
}

function blackoutScenario(dp, index) {
  const b = dp.blackout || {};
  const tradingDays = dp.trading_days_per_year;
  const baseline = [...(index.history?.ttm || [])].reverse().find((r) => r.period_ended && r.coverage_pct >= 60 && finite(r.covered_sum_bn));
  if (!baseline || !finite(b.now_pct) || !finite(tradingDays) || tradingDays <= 0) return gap('Blackout scenario unavailable: a dated calendar and a sufficiently covered historical baseline are needed.');
  const daily = baseline.covered_sum_bn / tradingDays;
  const hypothetical = daily * (1 - b.now_pct / 100);
  const change = finite(b.change_7d_pp) ? -daily * b.change_7d_pp / 100 : null;
  const history = (b.dates || []).map((date, i) => ({ date, blackout: (b.share_pct || [])[i] })).filter((r) => finite(r.blackout));
  const past = history.filter((r) => r.date <= b.as_of).slice(-180);
  const future = history.filter((r) => r.date > b.as_of);
  const points = [...past, ...future];
  const chart = el('div', { class: 'chart rc-breadth-chart', 'aria-label': 'Illustrative buyback scenario from the calendar proxy' });
  if (points.length) requestAnimationFrame(() => render(chart, (option, p) => ({
    ...option,
    legend: { top: 0, textStyle: { color: p.dim, fontSize: 10 } },
    grid: { left: 55, right: 18, top: 30, bottom: 30 },
    xAxis: { ...option.xAxis, data: points.map((r) => r.date) },
    yAxis: { ...option.yAxis, min: 0, axisLabel: { color: p.dim, formatter: (v) => '$' + num(v, 1) + 'B' } },
    series: [
      { name: 'Retrospective scenario ($B/day)', type: 'line', showSymbol: false, data: points.map((r) => r.date <= b.as_of ? daily * (1-r.blackout/100) : null), itemStyle: { color: p.blue }, lineStyle: { color: p.blue, width: 2 } },
      { name: 'Scheduled scenario ($B/day)', type: 'line', showSymbol: false, data: points.map((r) => r.date >= b.as_of ? daily * (1-r.blackout/100) : null), itemStyle: { color: p.accent }, lineStyle: { color: p.accent, width: 2, type: 'dashed' } },
    ],
  })));
  return el('div', {}, [
    el('h3', { class: 'stat-label', text: 'ILLUSTRATIVE BLACKOUT SCENARIO · SPX' }),
    el('div', { class: 'rc-fed-grid' }, [
      metric('ESTIMATED OPEN-WINDOW WEIGHT', num(100 - b.now_pct, 1) + '%', 'Calendar proxy · ' + (b.as_of || DASH)),
      metric('SCENARIO PER TRADING DAY', '$' + num(hypothetical, 2) + 'B', 'Hypothetical scaling of covered historical cash, not a forecast'),
      metric('SCENARIO CHANGE VS 7 DAYS AGO', signedBn(change, 2) + ' / day', 'Only reflects the change in calendar weight'),
      metric('BASELINE · LAST COVERED 4Q', '$' + num(baseline.covered_sum_bn, 1) + 'B', baseline.period + ' · ' + baseline.covered_issuers + '/' + baseline.total_issuers + ' issuers'),
    ]),
    points.length ? chart : null,
    el('p', { class: 'rc-note', text: 'Illustration assumes each issuer buys in proportion to index market weight, uniformly across trading days, and zero in blackout. Actual buyback weights, timing, plans and policies differ, including purchases during blackout. Baseline is the latest completed rolling 4Q with at least 60% issuer coverage, divided by ' + tradingDays + ' trading days; missing issuers are not estimated. Past calendar is reconstructed using current data; the dashed schedule includes projected earnings dates. The same current baseline is applied throughout, so past figures are not point-in-time estimates. This is not observed order flow, a validated forecast, or a measure of market impact. SPX calendar proxy only.' }),
  ]);
}

function blackoutFold(dp, index) {
  const fold = el('details', { class: 'rc-method' }, [el('summary', { text: 'BLACKOUT SCENARIO · ILLUSTRATIVE' })]);
  fold.addEventListener('toggle', () => { if (fold.open && fold.children.length === 1) fold.append(blackoutScenario(dp, index)); });
  return fold;
}

export function demandPipelineSection(dp, { tab = 'z1', only = null } = {}) {
  if (!dp || dp.unavailable) return null;
  const z1 = dp.z1 || {};
  const foreign = dp.foreign || {};
  const bb = dp.buybacks || {};
  const hfm = dp.hedge_fund_monitor || {};

  let activeTab = tab;
  let bbIndex = Object.keys(bb.indices || {})[0];
  const tabSwitch = el('div', { class: 'period-switch', role: 'group', 'aria-label': 'Select demand pipeline section' });
  const bodyNode = el('div', { class: 'rc-demand-body' });

  const tabs = [
    ['z1', '1 · Households, Funds & Pensions (Z.1)'],
    ['foreign', '2 · Foreign Demand (Z.1 vs TIC)'],
    ['buybacks', '3 · Actual Buybacks & Capacity (SPX/NDX)'],
    ['hf', '4 · Hedge-Fund Exposures'],
  ].filter(([key]) => !only || key === only);

  const renderBody = () => {
    [...tabSwitch.children].forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.tab === activeTab)));
    if (activeTab === 'z1') {
      const groups = z1.groups || [];
      const byKey = Object.fromEntries(groups.map((g) => [g.key, g]));
      const nfc = z1.corporate_net_retirement_broad || {};
      const recon = z1.reconciliation || {};
      const cards = [
        ['HOUSEHOLDS & NONPROFITS', byKey.households, 'Residual sector · includes nonprofits'],
        ['MUTUAL FUNDS (EQUITY TRADES)', byKey.mutual_funds, 'Portfolio trades · not fund redemptions'],
        ['PENSION FUNDS (3-SECTOR SUM)', byKey.pensions, 'Private + federal + state/local'],
        ['BROAD NONFIN. NET RETIREMENT', nfc, '-FU103164105.Q · includes private M&A'],
      ].map(([title, g, sub]) => metric(
        title,
        signedBn(g?.latest_bn, 1) + ' (' + (g?.latest_quarter || DASH) + ')',
        'TTM 4Q ' + signedBn(g?.ttm_4q_bn, 1) + ' · YTD ' + signedBn(g?.ytd_bn, 1) + ' · ' + sub,
        finite(g?.latest_bn) ? (g.latest_bn > 0 ? 'good' : g.latest_bn < -100 ? 'stress' : '') : '',
      ));
      const chartNode = el('div', { class: 'chart rc-breadth-chart' });
      const h = z1.history || { quarters: [], dates: [] };
      requestAnimationFrame(() => {
        render(chartNode, (option, p) => ({
          ...option,
          grid: { left: 52, right: 18, top: 24, bottom: 26 },
          legend: { top: 0, textStyle: { color: p.dim, fontSize: 10 } },
          xAxis: { ...option.xAxis, data: h.quarters },
          yAxis: { ...option.yAxis, axisLabel: { color: p.dim, formatter: (v) => '$' + num(v, 0) + 'B' } },
          series: [
            { name: 'Households', type: 'bar', stack: 'flow', data: h.households, itemStyle: { color: p.up } },
            { name: 'Mutual funds', type: 'bar', stack: 'flow', data: h.mutual_funds, itemStyle: { color: p.down } },
            { name: 'Pensions', type: 'bar', stack: 'flow', data: h.pensions, itemStyle: { color: p.accent } },
            { name: 'Foreign (ex-funds)', type: 'line', data: h.foreign, showSymbol: false, itemStyle: { color: p.blue }, lineStyle: { width: 1.8, color: p.blue } },
          ],
        }));
      });
      const rows = [...groups, ...(z1.pension_components || []), nfc].filter((r) => r?.label).map((r) => el('tr', {}, [
        el('td', { text: r.label }),
        el('td', { class: 'dim', text: r.latest_quarter || DASH }),
        el('td', { class: finite(r.latest_bn) ? (r.latest_bn >= 0 ? 'up' : 'down') : '', text: signedBn(r.latest_bn, 2) }),
        el('td', { text: signedBn(r.qoq_bn, 2) }),
        el('td', { text: signedBn(r.ytd_bn, 2) }),
        el('td', { class: finite(r.ttm_4q_bn) ? (r.ttm_4q_bn >= 0 ? 'up' : 'down') : '', text: signedBn(r.ttm_4q_bn, 2) }),
      ]));
      bodyNode.replaceChildren(
        el('div', { class: 'rc-fed-grid' }, cards),
        chartNode,
        el('div', { class: 'table-scroll' }, [el('table', { class: 'data' }, [
          el('thead', {}, [el('tr', {}, ['SECTOR / COMPONENT', 'LATEST Q', 'QUARTER ($B)', 'QOQ ($B)', 'YTD ($B)', 'TTM 4Q ($B)'].map((c) => el('th', { text: c })))]),
          el('tbody', {}, rows),
        ])]),
        el('p', { class: 'rc-note', text: 'Source: Fed Financial Accounts Z.1 (' + (z1.basis || 'FU NSA') + ', released ' + (z1.released || DASH) + ', next ' + (z1.next_release || DASH) + '). Accounting identity verified across ' + (recon.all_quarters_checked || DASH) + ' quarters (' + z1.first_quarter + '–' + z1.latest_quarter + '): holder max residual $' + num((recon.holder_identity_max_residual_bn || 0) * 1000, 1) + 'M, issuer max residual $' + num((recon.issuer_identity_max_residual_bn || 0) * 1000, 1) + 'M.' }),
      );
    } else if (activeTab === 'foreign') {
      const z1For = (z1.groups || []).find((g) => g.key === 'foreign') || {};
      const sb = foreign.scope_bridge || {};
      const stats = el('div', { class: 'rc-fed-grid' }, [
        metric('FED Z.1 FOREIGN (EX-FUNDS)', signedBn(z1For.latest_bn, 1) + ' (' + (z1For.latest_quarter || DASH) + ')', 'TTM 4Q ' + signedBn(z1For.ttm_4q_bn, 1) + ' · FU263064105.Q', 'good'),
        metric('TREASURY TIC MONTHLY (BROAD)', signedBn(foreign.tic_latest_bn, 1) + ' (' + (foreign.tic_latest_month || DASH) + ')', '3M ' + signedBn(foreign.tic_3m_sum_bn, 1) + ' · 12M ' + signedBn(foreign.tic_12m_sum_bn, 1), 'good'),
        metric('RAW Z.1 VS TIC GAP (MEAN ABS)', '$' + num(sb.raw_mean_abs_diff_bn, 2) + 'B / qtr', 'Across ' + (sb.matched_quarters || DASH) + ' complete quarters · different scope', 'watch'),
        metric('SCOPE-ALIGNED BRIDGE GAP', '$' + num(sb.scope_aligned_mean_abs_diff_bn, 2) + 'B / qtr', 'After subtracting foreign fund shares (FU263081205.Q)', 'good'),
      ]);
      const chartNode = el('div', { class: 'chart rc-breadth-chart' });
      const tm = foreign.tic_monthly || { months: [], values_bn: [] };
      requestAnimationFrame(() => {
        render(chartNode, (option, p) => ({
          ...option,
          grid: { left: 52, right: 18, top: 20, bottom: 26 },
          xAxis: { ...option.xAxis, data: tm.months },
          yAxis: { ...option.yAxis, axisLabel: { color: p.dim, formatter: (v) => '$' + num(v, 0) + 'B' } },
          series: [{
            name: 'TIC Monthly Foreign Net Buying (broad, $B)', type: 'bar',
            data: tm.values_bn,
            itemStyle: { color: (params) => (params.value >= 0 ? p.up : p.down) },
          }],
        }));
      });
      const bridgeRows = (sb.rows || []).slice(-8).reverse().map((r) => el('tr', {}, [
        el('td', { text: r.quarter }),
        el('td', { text: signedBn(r.tic_broad_bn, 2) }),
        el('td', { text: signedBn(r.bea_broad_bn, 2) }),
        el('td', { text: signedBn(r.fund_shares_bn, 2) }),
        el('td', { class: finite(r.fed_ex_funds_bn) ? (r.fed_ex_funds_bn >= 0 ? 'up' : 'down') : '', text: signedBn(r.fed_ex_funds_bn, 2) }),
        el('td', { class: 'dim', text: signedBn(r.scope_aligned_diff_bn, 2) }),
      ]));
      bodyNode.replaceChildren(
        stats,
        chartNode,
        el('div', { class: 'table-scroll' }, [el('table', { class: 'data' }, [
          el('thead', {}, [el('tr', {}, ['QUARTER', 'TIC MONTHLY SUM (BROAD)', 'BEA/FED BROAD (EQUITY+FUNDS)', 'LESS: FUND SHARES', 'FED Z.1 EX-FUNDS', 'BROAD BRIDGE RESIDUAL'].map((c) => el('th', { text: c })))]),
          el('tbody', {}, bridgeRows),
        ])]),
        el('p', { class: 'rc-note', text: sb.note || '' }),
      );
    } else if (activeTab === 'buybacks') {
      const indices = bb.indices || {};
      const cur = indices[bbIndex] || {};
      const idxBtns = el('div', { class: 'period-switch', role: 'group' }, Object.keys(indices).map((k) => el('button', {
        type: 'button', text: k, 'aria-pressed': String(k === bbIndex),
        onclick: () => { bbIndex = k; renderBody(); },
      })));
      const reg = cur.regimes || {};
      const stats = el('details', { class: 'rc-method' }, [el('summary', { text: 'Latest issuer reports · mixed fiscal end dates (detail only)' }), el('div', { class: 'rc-fed-grid' }, [
        metric(
          cur.index + ' COVERED TTM BUYBACKS',
          '$' + num(cur.covered_ttm_sum_bn, 1) + 'B',
          cur.ttm_covered_issuers + '/' + cur.unique_issuers + ' issuers · ' + num(cur.ttm_weight_coverage_pct, 1) + '% index weight',
          '',
        ),
        metric(
          cur.index + ' COVERED LATEST Q BUYBACKS',
          '$' + num(cur.covered_quarter_sum_bn, 1) + 'B',
          cur.quarter_covered_issuers + '/' + cur.unique_issuers + ' issuers · ' + num(cur.quarter_weight_coverage_pct, 1) + '% index weight',
          '',
        ),
        metric(
          cur.index + ' ENTITY REMAINING CAPACITY',
          '$' + num(cur.covered_remaining_at_report_bn, 1) + 'B',
          cur.remaining_at_report_issuers + ' at report_end (' + cur.remaining_any_period_issuers + ' any period) + dimensional plans',
          '',
        ),
        metric(
          'EXECUTION REGIMES (ISSUERS)',
          (reg.active || 0) + ' active · ' + (reg.zero_with_prior_execution || 0) + ' zero this quarter',
          (reg.positive_vs_zero_year_ago || 0) + ' positive vs year-ago zero · ' + (reg.zero || 0) + ' zero · ' + (reg.reconciliation_exception || 0) + ' exception · ' + (reg.missing || 0) + ' missing',
          '',
        ),
      ])]);
      const topRows = (cur.top_ttm_buyers || []).slice(0, 12).map((r) => el('tr', {}, [
        el('td', {}, [el('strong', { text: r.ticker }), el('span', { class: 'dim', text: ' · ' + (r.report_end || DASH) })]),
        el('td', { text: '$' + num(r.quarter_bn, 2) + 'B' }),
        el('td', { class: finite(r.quarter_yoy_pct) ? (r.quarter_yoy_pct >= 0 ? 'up' : 'down') : 'dim', text: finite(r.quarter_yoy_pct) ? (r.quarter_yoy_pct > 0 ? '+' : '') + num(r.quarter_yoy_pct, 1) + '%' : DASH }),
        el('td', { class: 'up', text: '$' + num(r.ttm_bn, 2) + 'B' }),
        el('td', { text: finite(r.buyback_yield_pct) ? num(r.buyback_yield_pct, 2) + '%' : DASH }),
        el('td', { text: finite(r.remaining_at_report_bn) ? '$' + num(r.remaining_at_report_bn, 2) + 'B' : (finite(r.latest_remaining_bn) ? '$' + num(r.latest_remaining_bn, 2) + 'B (' + r.latest_remaining_end + ')' : DASH) }),
        el('td', {}, [tag((r.regime || 'active').toUpperCase(), r.regime === 'paused' ? 'warn' : 'up')]),
      ]));
      const pausedRows = (cur.notable_paused || []).slice(0, 6).map((r) => el('tr', {}, [
        el('td', {}, [el('strong', { text: r.ticker }), el('span', { class: 'dim', text: ' · ' + (r.report_end || DASH) })]),
        el('td', { class: 'warn', text: '$0.00B' }),
        el('td', { text: finite(r.ttm_bn) ? '$' + num(r.ttm_bn, 2) + 'B' : DASH }),
        el('td', { text: finite(r.remaining_at_report_bn) ? '$' + num(r.remaining_at_report_bn, 2) + 'B' : 'See dimensional / notes' }),
        el('td', {}, [tag('ZERO EXECUTION', 'warn')]),
      ]));
      bodyNode.replaceChildren(
        el('div', { class: 'rc-chart-tools' }, [el('span', { class: 'rc-chart-key', text: 'DEDUPLICATED BY ISSUER CIK · PARTIAL DISCLOSED SUMS, NEVER IMPUTED AS ZERO' }), idxBtns]),
        ...(bbIndex === Object.keys(indices)[0] ? [blackoutFold(dp, cur)] : []),
        buybackHistory(cur),
        stats,
        el('div', { class: 'table-scroll' }, [el('table', { class: 'data' }, [
          el('thead', {}, [el('tr', {}, ['ISSUER · REPORT END', 'LATEST Q ($B)', 'QTR YOY ACCEL', 'TTM ($B)', 'BUYBACK YIELD', 'REMAINING AUTH ($B)', 'REGIME'].map((c) => el('th', { text: c })))]),
          el('tbody', {}, topRows),
        ])]),
        ...(pausedRows.length ? [el('details', { class: 'rc-method', open: true }, [
          el('summary', { text: 'ZERO EXECUTION IN LATEST QUARTER (' + (cur.notable_paused?.length || 0) + ' ISSUERS WITH $0 LATEST Q DESPITE PRIOR BUYBACKS / CAPACITY)' }),
          el('div', { class: 'table-scroll' }, [el('table', { class: 'data' }, [
            el('thead', {}, [el('tr', {}, ['ISSUER · REPORT END', 'LATEST Q', 'TTM ($B)', 'ENTITY REMAINING AUTH', 'STATUS'].map((c) => el('th', { text: c })))]),
            el('tbody', {}, pausedRows),
          ])]),
        ])] : []),
        el('p', { class: 'rc-note', text: 'Authorization balances are incomplete and do not guarantee future purchases. ' + (bb.note || '') }),
      );
    } else {
      const fpf = hfm.form_pf || {};
      const ceq = fpf.cash_equities || {};
      const deq = fpf.equity_derivatives || {};
      const fin = fpf.financing || {};
      const s13 = hfm.sec_13f || {};
      const cftc = hfm.cftc_futures || {};
      const stats = el('div', { class: 'rc-fed-grid' }, [
        metric(
          '1 · FORM PF CASH EQUITIES (NET)',
          signedBn(ceq.net_bn, 0) + ' (' + (fpf.latest_period || DASH) + ')',
          'Long $' + num(ceq.long_bn, 0) + 'B vs Short $' + num(ceq.short_bn, 0) + 'B · QoQ ' + signedBn(ceq.net_qoq_bn, 0),
          '',
        ),
        metric(
          '1 · FORM PF EQUITY DERIVATIVES (NET)',
          signedBn(deq.net_bn, 0) + ' (' + (fpf.latest_period || DASH) + ')',
          'Long $' + num(deq.long_bn, 0) + 'B vs Short $' + num(deq.short_bn, 0) + 'B · QoQ ' + signedBn(deq.net_qoq_bn, 0),
          '',
        ),
        metric(
          '1 · PRIME BROKERAGE BORROWING',
          '$' + num(fin.prime_broker_borrowing_bn, 0) + 'B',
          'QoQ ' + signedBn(fin.pb_qoq_bn, 0) + ' · YoY ' + signedBn(fin.pb_yoy_bn, 0) + ' · Cash/NAV ' + num(fin.unencumbered_cash_pct_nav, 1) + '% (' + signed(fin.cash_ratio_qoq_pp, ' pp') + ')',
          '',
        ),
        metric(
          '2 & 3 · 13F LONG HOLDINGS & CFTC FUTURES',
          '13F $' + num(s13.total_long_value_bn, 0) + 'B · ES ' + signed(cftc.es_pct_oi, '%'),
          'Exposure snapshots; no verified capital-flow total · NQ ' + signed(cftc.nq_pct_oi, '%') + ' (' + (cftc.date || DASH) + ')',
          '',
        ),
      ]);
      const chartNode = el('div', { class: 'chart rc-breadth-chart' });
      const fh = fpf.history || { dates: [] };
      requestAnimationFrame(() => {
        render(chartNode, (option, p) => ({
          ...option,
          grid: { left: 54, right: 18, top: 24, bottom: 26 },
          legend: { top: 0, textStyle: { color: p.dim, fontSize: 10 } },
          xAxis: { ...option.xAxis, data: fh.dates },
          yAxis: { ...option.yAxis, axisLabel: { color: p.dim, formatter: (v) => '$' + num(v, 0) + 'B' } },
          series: [
            { name: 'Net Cash Equities ($B)', type: 'line', data: fh.net_cash_eq_bn, showSymbol: false, itemStyle: { color: p.up }, lineStyle: { width: 2.0, color: p.up } },
            { name: 'Net Equity Derivatives ($B)', type: 'line', data: fh.net_deriv_eq_bn, showSymbol: false, itemStyle: { color: p.down }, lineStyle: { width: 1.8, color: p.down } },
            { name: 'Prime Broker Borrowing ($B)', type: 'line', data: fh.prime_broker_borrowing_bn, showSymbol: false, itemStyle: { color: p.accent }, lineStyle: { width: 1.6, color: p.accent, type: 'dashed' } },
          ],
        }));
      });
      bodyNode.replaceChildren(
        stats,
        chartNode,
        el('p', { class: 'rc-note', text: fpf.note || '' }),
      );
    }
  };

  tabs.forEach(([k, label]) => {
    const b = el('button', { type: 'button', text: label, onclick: () => { activeTab = k; renderBody(); } });
    b.dataset.tab = k;
    tabSwitch.append(b);
  });
  renderBody();

  return card(({ z1: 'INVESTOR DEMAND · QUARTERLY', foreign: 'FOREIGN DEMAND · MONTHLY & QUARTERLY', buybacks: 'ACTUAL CASH REPURCHASES · INDEX HISTORY', hf: 'HEDGE-FUND EXPOSURES · FORM PF' })[only] || 'EQUITY DEMAND', tag('DATED SOURCES · COVERAGE SHOWN', 'dim'), [
    el('p', { class: 'rc-intro', text: 'Demand snapshot as of ' + (dp.as_of || DASH) + '. Each source keeps its own observation period. Investor transactions, company cash payments and hedge-fund exposure snapshots measure different things; they are not added together.' }),
    only ? null : el('div', { class: 'rc-chart-tools' }, [tabSwitch]),
    bodyNode,
  ]);
}

