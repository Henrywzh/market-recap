// EARNINGS (under CATALYSTS): FactSet's Earnings Insight figures, the daily
// bottom-up revision tracker built here, and the reporting season so far.
// Every figure carries its date; coverage and method sit behind METHOD.

import { el, card, num, pct, sectionTitle, notice, periodSwitch, metaRow, DASH } from '../fmt.js';
import { render, multiLine, SERIES_COLORS } from '../charts.js';
import { tickerHref } from '../routes.js';

const WINDOWS = ['7d', '30d', '60d', '90d'];
const SECTOR_SHORT = {
  'Communication Services': 'Comm Services',
  'Consumer Discretionary': 'Cons Discretionary',
  'Consumer Staples': 'Cons Staples',
  'Information Technology': 'Info Tech',
};

function dirCls(value) {
  if (value === null || value === undefined) return 'dim';
  return value > 0 ? 'up' : value < 0 ? 'down' : 'flat';
}

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function link(url, text) {
  return url ? el('a', { href: url, target: '_blank', rel: 'noopener', text }) : el('span', { text });
}

function quarterText(q) {
  const m = /^(\d{4})Q([1-4])$/.exec(q || '');
  return m ? `Q${m[2]} ${m[1]}` : (q || DASH);
}

function shortQuarter(q) {
  const m = /^(\d{4})Q([1-4])$/.exec(q || '');
  return m ? `Q${m[2]} ${m[1].slice(2)}` : (q || DASH);
}

function chartBlock(title, node) {
  return el('div', { class: 'earn-chart' }, [el('div', { class: 'earn-sub', text: title }), node]);
}

// Vertical bars around zero, one colour for positive and one for negative.
function signedBars(node, labels, values, options = {}) {
  return render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, top: 22, right: 20 },
    tooltip: { ...option.tooltip, axisPointer: { type: 'shadow' }, valueFormatter: (v) => (v == null ? DASH : `${num(v, 1)}%`) },
    xAxis: { ...option.xAxis, boundaryGap: true, data: labels },
    series: [{
      type: 'bar',
      barMaxWidth: 26,
      data: values.map((v, i) => ({
        value: v,
        itemStyle: { color: v >= 0 ? p.up : p.down, opacity: options.faint?.[i] ? 0.4 : 0.85 },
      })),
      label: { show: true, position: 'top', color: p.dim, fontSize: 9, formatter: (q) => (q.value == null ? '' : `${num(q.value, 1)}`) },
      markLine: options.reference == null ? undefined : {
        silent: true,
        symbol: 'none',
        data: [{ yAxis: options.reference }],
        lineStyle: { color: p.accent, type: 'dashed' },
        label: { formatter: options.referenceLabel, color: p.accent, fontSize: 9, position: 'insideEndTop' },
      },
    }],
  }));
}

// Horizontal bars, sorted, for a per-sector reading.
function sectorBars(node, rows, tooltip) {
  const sorted = [...rows].sort((a, b) => a.value - b.value);
  return render(node, (option, p) => ({
    ...option,
    grid: { left: 118, right: 46, top: 6, bottom: 22 },
    tooltip: { ...option.tooltip, trigger: 'item', axisPointer: undefined, formatter: (q) => tooltip(sorted[q.dataIndex]) },
    xAxis: {
      type: 'value',
      axisLabel: { color: p.dim, fontSize: 10 },
      splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
    },
    yAxis: {
      type: 'category',
      data: sorted.map((r) => SECTOR_SHORT[r.label] || r.label),
      axisLabel: { color: p.dim, fontSize: 10 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 12,
      data: sorted.map((r) => ({ value: r.value, itemStyle: { color: r.color ? r.color(p) : r.value >= 0 ? p.up : p.down, opacity: 0.85 } })),
      label: { show: true, position: 'right', color: p.dim, fontSize: 9, formatter: (q) => sorted[q.dataIndex].text },
    }],
  }));
}

function factsetCard(f) {
  const body = [];
  const snap = f.snapshot;
  if (snap) {
    const premium = snap.forward_12m_pe && snap.forward_12m_pe_10y_avg
      ? (snap.forward_12m_pe / snap.forward_12m_pe_10y_avg - 1) * 100 : null;
    body.push(el('div', { class: 'earn-sub' }, [
      `SEASON · ${quarterText(snap.reference_quarter)} · `,
      link(snap.source_url, snap.report_date),
    ]));
    body.push(el('div', { class: 'stat-strip' }, [
      stat('EARNINGS GROWTH Y/Y', pct(snap.blended_earnings_growth_yoy, 1), 'blended', dirCls(snap.blended_earnings_growth_yoy)),
      stat('REVENUE GROWTH Y/Y', pct(snap.blended_revenue_growth_yoy, 1), 'blended', dirCls(snap.blended_revenue_growth_yoy)),
      stat('EPS BEAT RATE', snap.eps_beat_rate == null ? DASH : `${num(snap.eps_beat_rate, 0)}%`, snap.eps_surprise_pct == null ? '' : `surprise ${pct(snap.eps_surprise_pct, 1)}`),
      stat('REVENUE BEAT RATE', snap.revenue_beat_rate == null ? DASH : `${num(snap.revenue_beat_rate, 0)}%`, snap.revenue_surprise_pct == null ? '' : `surprise ${pct(snap.revenue_surprise_pct, 1)}`),
      stat('FORWARD 12M P/E', snap.forward_12m_pe == null ? DASH : `${num(snap.forward_12m_pe, 1)}×`,
        (snap.forward_12m_pe_10y_avg == null ? '' : `10Y avg ${num(snap.forward_12m_pe_10y_avg, 1)}× (${pct(premium, 0)})`)
          + (snap.forward_pe_date ? ` · ${snap.forward_pe_date}` : '')),
    ]));
  }
  const rev = f.revision;
  if (rev) {
    const typical5 = (rev.typical || []).find((t) => t.years === 5);
    body.push(el('div', { class: 'earn-sub' }, [
      `ESTIMATE REVISION · ${quarterText(rev.reference_quarter)}${rev.window ? ` · ${rev.window}` : ''} · `,
      link(rev.source_url, rev.report_date),
    ]));
    const named = Object.entries(rev.sectors || {});
    body.push(el('div', { class: 'stat-strip' }, [
      stat('QUARTER BOTTOM-UP EPS', pct(rev.quarterly_eps_revision_pct, 1),
        rev.prior ? `prior note ${pct(rev.prior.quarterly_eps_revision_pct, 1)}` : '', dirCls(rev.quarterly_eps_revision_pct)),
      stat('CALENDAR-YEAR EPS', pct(rev.annual_eps_revision_pct, 1),
        rev.prior && rev.prior.annual_eps_revision_pct != null ? `prior note ${pct(rev.prior.annual_eps_revision_pct, 1)}` : '', dirCls(rev.annual_eps_revision_pct)),
      stat('VS 5Y TYPICAL', typical5 ? `${rev.quarterly_eps_revision_pct >= typical5.value ? '+' : '−'}${num(Math.abs(rev.quarterly_eps_revision_pct - typical5.value), 1)} pp` : DASH,
        typical5 ? `typical ${pct(typical5.value, 1)} · ${(rev.typical || []).filter((t) => t.years !== 5).map((t) => `${t.years}y ${pct(t.value, 1)}`).join(' · ')}` : 'not stated in this note',
        typical5 ? dirCls(rev.quarterly_eps_revision_pct - typical5.value) : ''),
      named.length ? el('div', { class: 'stat' }, [
        el('div', { class: 'stat-label', text: 'SECTORS NAMED' }),
        el('div', { class: 'earn-sectors' }, named.map(([s, v]) => el('span', { class: dirCls(v), text: `${SECTOR_SHORT[s] || s} ${pct(v, 1)}` }))),
      ]) : null,
    ]));
  }

  const growthNode = el('div', { class: 'chart short' });
  const revisionNode = el('div', { class: 'chart short' });
  const peNode = el('div', { class: 'chart short' });
  body.push(el('div', { class: 'grid three earn-charts' }, [
    chartBlock('GROWTH Y/Y BY QUARTER · FAINT = STILL AN ESTIMATE', growthNode),
    chartBlock('EPS REVISION INSIDE EACH QUARTER', revisionNode),
    chartBlock('FORWARD 12M P/E VS 10Y AVERAGE', peNode),
  ]));
  const node = card('FACTSET EARNINGS INSIGHT', el('span', { class: 'dim' }, ['newest article ', link(f.source_url, f.newest_date || DASH)]), body);

  requestAnimationFrame(() => {
    const seasons = [...(f.season_history || [])].sort((a, b) => a.quarter.localeCompare(b.quarter)).slice(-8);
    if (seasons.length) {
      // Before a season has a beat rate, FactSet's growth figure is its estimate.
      signedBars(growthNode, seasons.map((r) => shortQuarter(r.quarter)), seasons.map((r) => r.blended_earnings_growth_yoy),
        { faint: seasons.map((r) => r.eps_beat_rate == null) });
    }
    const revisions = [...(f.revision_history || [])].sort((a, b) => a.quarter.localeCompare(b.quarter)).slice(-8);
    const typical5 = (f.revision?.typical || []).find((t) => t.years === 5);
    if (revisions.length) {
      signedBars(revisionNode, revisions.map((r) => shortQuarter(r.quarter)), revisions.map((r) => r.quarterly_eps_revision_pct),
        typical5 ? { reference: typical5.value, referenceLabel: '5Y TYPICAL' } : {});
    }
    const pe = (f.forward_pe || []).slice(-104);
    if (pe.length) {
      // The weekly PDF also states the 5-year average; the blog's in-season
      // articles state only the 10-year one.
      const lines = {
        'Forward 12M P/E': pe.map((r) => r.forward_12m_pe),
        '10-year average': pe.map((r) => r.ten_year_average),
      };
      if (pe.some((r) => r.five_year_average)) lines['5-year average'] = pe.map((r) => r.five_year_average ?? null);
      multiLine(peNode, pe.map((r) => r.date), lines);
    }
  });
  return node;
}

function trackerCard(t) {
  const periods = ['quarter', 'year', 'next_year'].filter((k) => t[k]).map((k) => t[k]);
  const windowsNode = el('div', { class: 'chart' });
  const sectorNode = el('div', { class: 'chart' });
  const moversHost = el('div', { class: 'earn-movers' });
  const breadth = el('div', { class: 'stat-strip earn-breadth' }, periods.map((p) => stat(
    `${p.label} · REVISED 30D`,
    `${p.breadth_30d.up} ↑ / ${p.breadth_30d.down} ↓`,
    `${p.companies} of ${t.members} companies · 90D ${pct(p.windows['90d']?.pct, 2)}`,
    p.breadth_30d.up >= p.breadth_30d.down ? 'up' : 'down',
  )));

  const draw = (label) => {
    const p = periods.find((x) => x.label === label);
    sectorBars(sectorNode, p.sectors.filter((s) => s['30d'] != null).map((s) => ({
      label: s.sector,
      value: Math.round(s['30d'] * 100) / 100,
      text: pct(s['30d'], 1),
      tip: s,
    })), (row) => `<b>${row.tip.sector}</b> · ${row.tip.companies} companies<br>30D ${pct(row.tip['30d'], 2)} · 90D ${pct(row.tip['90d'], 2)}`
      + (row.tip.leader_30d ? `<br>largest mover ${row.tip.leader_30d.symbol} ${row.tip.leader_30d.pp >= 0 ? '+' : ''}${num(row.tip.leader_30d.pp, 2)} pp` : ''));
    const movers = p.movers_30d || { up: [], down: [] };
    moversHost.replaceChildren(
      el('span', { class: 'earn-sub', text: `MOVED THE ${p.label} AGGREGATE MOST · 30D, PP` }),
      ...[...movers.up, ...movers.down].map((m) => el('a', { class: `mchip ${dirCls(m.pp)}`, href: tickerHref(m.symbol), text: `${m.symbol} ${m.pp >= 0 ? '+' : ''}${num(m.pp, 2)}` })),
    );
  };
  const labels = periods.map((p) => p.label);
  const node = card('BOTTOM-UP REVISIONS · DAILY', periodSwitch(labels, labels[0], draw), [
    breadth,
    el('div', { class: 'grid two earn-charts' }, [
      chartBlock('AGGREGATE EPS CHANGE BY LOOK-BACK, %', windowsNode),
      chartBlock('BY SECTOR · 30D, %', sectorNode),
    ]),
    moversHost,
  ]);
  requestAnimationFrame(() => {
    render(windowsNode, (option, p) => ({
      ...option,
      grid: { ...option.grid, top: 22, bottom: 44 },
      legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
      tooltip: { ...option.tooltip, axisPointer: { type: 'shadow' }, valueFormatter: (v) => (v == null ? DASH : `${num(v, 2)}%`) },
      xAxis: { ...option.xAxis, boundaryGap: true, data: WINDOWS.map((w) => w.toUpperCase()) },
      series: periods.map((period, i) => ({
        name: period.label,
        type: 'bar',
        barMaxWidth: 18,
        itemStyle: { color: SERIES_COLORS[i] },
        data: WINDOWS.map((w) => period.windows[w]?.pct ?? null),
        label: { show: true, position: 'top', color: p.dim, fontSize: 9, formatter: (q) => (q.value == null ? '' : num(q.value, 1)) },
      })),
    }));
    draw(labels[0]);
  });
  return node;
}

function seasonCard(s) {
  const share = s.universe ? (s.reported / s.universe) * 100 : 0;
  const sectorNode = el('div', { class: 'chart' });
  const latestNode = el('div', { class: 'chart' });
  const node = card(`REPORTING SEASON · ${s.quarter}`, el('span', { class: 'dim', text: `reports since ${s.first_day}` }), [
    el('div', { class: 'earn-progress', title: `${s.reported} of ${s.universe} reported` }, [
      el('span', { class: 'earn-progress-fill', style: `width:${Math.min(100, share)}%` }),
      el('span', { class: 'earn-progress-text', text: `${s.reported} of ${s.universe} reported (${num(share, 0)}%) · ${s.upcoming_next_5_sessions} due in the next 5 sessions` }),
    ]),
    el('div', { class: 'stat-strip' }, [
      stat('BEAT EPS CONSENSUS', s.beat_share == null ? DASH : `${num(s.beat_share, 0)}%`, `${s.beat} beat · ${s.in_line} in line · ${s.miss} missed`),
      stat('MEDIAN SURPRISE', pct(s.median_surprise_pct, 1), `aggregate ${pct(s.aggregate_surprise_pct, 1)}`, dirCls(s.median_surprise_pct)),
      stat('EPS GROWTH Y/Y', pct(s.growth_yoy_pct, 1), `${s.growth_companies} companies so far`, dirCls(s.growth_yoy_pct)),
    ]),
    el('div', { class: 'grid two earn-charts' }, [
      chartBlock('BEAT RATE BY SECTOR', sectorNode),
      chartBlock('LATEST SURPRISES, %', latestNode),
    ]),
  ]);
  requestAnimationFrame(() => {
    const sectors = (s.sectors || []).filter((x) => x.with_estimate);
    if (sectors.length) {
      sectorBars(sectorNode, sectors.map((x) => ({
        label: x.sector,
        value: Math.round((100 * x.beat) / x.with_estimate),
        text: `${x.beat}/${x.with_estimate}`,
        color: (p) => p.accent,
        tip: x,
      })), (row) => `<b>${row.tip.sector}</b><br>${row.tip.beat} of ${row.tip.with_estimate} beat · ${row.tip.reported} reported`);
    }
    const latest = (s.latest || []).slice(0, 12).reverse();
    if (latest.length) {
      sectorBars(latestNode, latest.map((r) => ({
        label: r.symbol,
        value: r.surprise_pct,
        text: pct(r.surprise_pct, 1),
        tip: r,
      })), (row) => `<b>${row.tip.symbol}</b> ${row.tip.date}<br>EPS ${num(row.tip.eps, 2)} vs ${num(row.tip.eps_forecast, 2)} consensus`);
    }
  });
  return node;
}

function methodNotes(data) {
  const f = data.factset;
  const t = data.tracker;
  return [
    data.note,
    f ? `FACTSET: ${f.articles} Earnings Insight articles ${f.first_date} to ${f.newest_date}; figures are read from the article text, not FactSet's data feed. FactSet calendarizes and uses its own consensus. Sectors named are only the ones the article names; the rest are not published in the text. Growth bars are the last print of each season; before a season has a beat rate the figure is FactSet's estimate (faint).` : null,
    t ? `BOTTOM-UP REVISIONS: built here on ${data.as_of} from Yahoo's consensus trend for ${t.with_estimates} of ${t.members} members, weighted by float-adjusted shares. Fiscal periods count toward the calendar period holding most of their months, without pro-rating. The 90-day figure is comparable to, not the same as, FactSet's. Movers are the pp each company added to or took from the aggregate over 30 days.` : null,
    data.season ? 'REPORTING SEASON: Nasdaq calendar (Zacks consensus and actuals); a fiscal quarter counts toward the calendar quarter it ends in, so off-cycle reporters (quarters ending July/August) start the season early. A beat is an actual strictly above consensus. Growth covers only companies whose year-ago EPS was captured before they reported; it fills in as the season goes.' : null,
  ];
}

// Names reporting in the next two weeks: how far they moved on their last
// eight reports, and what the options snapshot prices now (phase 3).
function reportersCard(evidence, asOf) {
  const names = evidence?.names || {};
  const horizon = new Date(`${asOf}T00:00:00Z`);
  horizon.setUTCDate(horizon.getUTCDate() + 14);
  const end = horizon.toISOString().slice(0, 10);
  const rows = Object.entries(names)
    .filter(([, n]) => n.next && n.next.date > asOf && n.next.date <= end && (n.mean_abs_move || n.options?.implied_move))
    .sort((a, b) => a[1].next.date.localeCompare(b[1].next.date) || (b[1].mean_abs_move || 0) - (a[1].mean_abs_move || 0));
  if (!rows.length) return null;
  const body = rows.map(([symbol, n]) => {
    const implied = n.options?.implied_move?.straddle_pct;
    const ratio = implied && n.mean_abs_move ? implied / n.mean_abs_move : null;
    return el('tr', {}, [
      el('td', {}, [el('a', { href: tickerHref(symbol), text: symbol })]),
      el('td', { text: `${n.next.date} ${(n.next.timing || '').toUpperCase()}` }),
      el('td', { text: n.mean_abs_move ? `±${num(n.mean_abs_move, 1)}%` : DASH }),
      el('td', { text: n.reactions?.length ? n.reactions.slice(0, 4).map((r) => pct(r.move_pct, 1)).join(' · ') : DASH, class: 'dim' }),
      el('td', { text: implied ? `±${num(implied, 1)}%` : DASH, title: implied ? `ATM straddle to ${n.options.implied_move.expiry}` : 'not in the options snapshot' }),
      el('td', { class: ratio ? (ratio > 1.2 ? 'down' : ratio < 0.8 ? 'up' : '') : 'dim', text: ratio ? `${num(ratio, 2)}×` : DASH }),
    ]);
  });
  return card('REPORTING IN THE NEXT TWO WEEKS · IMPLIED VS REALISED', el('span', { class: 'dim', text: `implied from the options snapshot ${evidence.options_snapshot || '— not recorded yet'}` }), [
    el('div', { class: 'table-scroll' }, [el('table', { class: 'data' }, [
      el('thead', {}, [el('tr', {}, ['NAME', 'REPORT', 'AVG |MOVE| LAST 8', 'LAST 4 MOVES', 'IMPLIED', 'IMPLIED / REALISED'].map((h) => el('th', { text: h })))]),
      el('tbody', {}, body),
    ])]),
    el('div', { class: 'field-note', text: 'Realised: close-to-close move over the session that first traded on each 8-K Item 2.02 release. Implied: the ATM straddle of the first expiry on or after that session, as a share of spot -- it prices the whole period to expiry, not the report alone. Above 1.2× the options price more than the name has moved; below 0.8× less.' }),
  ]);
}

export default async function renderEarnings(root, data, _manifest, ctx = {}) {
  root.append(sectionTitle('EARNINGS', 'S&P 500 ESTIMATES AND THE REPORTING SEASON'));
  root.append(metaRow(`AS OF ${data.as_of || DASH} · ${data.index || 'S&P 500'} · HOLDINGS ${data.holdings_as_of || DASH}`, methodNotes(data)));
  (data.notices || []).forEach((message) => root.append(notice(message)));
  if (data.factset) root.append(factsetCard(data.factset));
  if (data.tracker) root.append(trackerCard(data.tracker));
  if (data.season) root.append(seasonCard(data.season));
  const evidence = await ctx.loadArtifact?.('evidence').catch(() => null);
  const reporters = reportersCard(evidence, data.as_of);
  if (reporters) root.append(reporters);
}
