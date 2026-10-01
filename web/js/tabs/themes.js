// THEMES (under CATALYSTS): what is coming for each group of names that
// trades together, and the industry data behind CLOUD, SEMIS, ENERGY,
// HOUSING, BANKS and CONSUMER. Built by
// the THEMES panel; every figure carries its source and date, and a source
// that failed leaves its reason in its own card.

import { el, card, num, pct, tag, table, dirClass, sectionTitle, gap, metaRow, periodSwitch, DASH } from '../fmt.js';
import { viewChart, VIEWS } from '../viewchart.js';
import { availableRanges, sliceRange } from '../range.js';
import { render } from '../charts.js';
import { tickerHref } from '../routes.js';

const KIND_TONE = { earnings: 'warn', macro: 'info', data: 'up' };
const KIND_LABEL = { earnings: 'EARN', macro: 'MACRO', data: 'DATA' };

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function unavailable(section) {
  return section && section.unavailable ? gap(`Not built this time: ${section.unavailable}`) : null;
}

function pctCell(value, digits = 1) {
  return el('td', { class: dirClass(value), text: pct(value, digits) });
}

function link(symbol) {
  return el('a', { href: tickerHref(symbol), text: symbol });
}

function rolling(values, n) {
  return values.map((_, i) => {
    if (i + 1 < n) return null;
    const window = values.slice(i + 1 - n, i + 1);
    return Math.round((window.reduce((a, b) => a + (b || 0), 0) / n) * 10) / 10;
  });
}

// --- every theme -----------------------------------------------------------------

function runInTags(g) {
  const r = g.run_in || {};
  return el('span', { class: 'tag-row' }, [
    tag(`1M ${pct(r.vs_spx_1m, 1)} vs SPX`, r.vs_spx_1m > 0 ? 'up' : r.vs_spx_1m < 0 ? 'down' : 'dim'),
    tag(`3M ${pct(r.vs_spx_3m, 1)}`, r.vs_spx_3m > 0 ? 'up' : r.vs_spx_3m < 0 ? 'down' : 'dim'),
  ]);
}

function overviewStrip(data, active, pick) {
  return el('div', { class: 'theme-strip' }, data.groups.map((g) => {
    const next = g.calendar.find((c) => c.kind === 'earnings' && !c.projected) || g.calendar.find((c) => c.kind === 'earnings');
    return el('button', {
      type: 'button', class: `theme-tile${g.key === active ? ' active' : ''}`, onclick: () => pick(g.key),
    }, [
      el('div', { class: 'theme-tile-label', text: g.label }),
      runInTags(g),
      el('div', { class: 'stat-note', text: next ? `next: ${next.symbol} ${next.date}${next.projected ? ' (proj.)' : ''}` : 'no bellwether report in six weeks' }),
      el('div', { class: 'stat-note', text: `${g.calendar.length} dated items · proxy ${g.proxy_is_etf ? g.proxy : 'basket'}` }),
    ]);
  }));
}

function calendarCard(g, asOf, days) {
  if (!g.calendar.length) return card(`NEXT ${days} DAYS`, null, gap('Nothing dated for this theme in the window.'));
  const rows = g.calendar.map((c) => el('tr', {}, [
    el('td', { text: c.date }),
    el('td', {}, [tag(KIND_LABEL[c.kind], c.projected ? 'dim' : KIND_TONE[c.kind], c.projected ? 'projected from its own report rhythm' : null)]),
    el('td', {}, c.kind === 'earnings'
      ? [c.listing ? el('span', { text: c.symbol }) : link(c.symbol), el('span', { class: 'dim', text: ` ${(c.timing || '').toUpperCase()}${c.projected ? ' · projected' : ''}${c.beta !== null && c.beta !== undefined ? ` · proxy β ${num(c.beta, 2)}` : ''}` })]
      : [el('span', { class: c.late ? 'down' : '', text: c.title }), c.time ? el('span', { class: 'dim', text: ` ${c.time} ET` }) : null, c.late ? el('span', { class: 'down', text: ' · late' }) : null]),
  ]));
  return card(`NEXT ${days} DAYS`, el('span', { class: 'dim', text: `from ${asOf}` }), table(['DATE', '', 'WHAT'], rows, { class: 'text-cols' }));
}

function bellwetherCard(g) {
  const rows = g.bellwethers.map((b) => {
    const s = b.impact || {};
    return el('tr', {}, [
      el('td', {}, [b.listing
        ? el('a', { href: b.source_url || '#', target: '_blank', rel: 'noopener', text: b.symbol, title: `${b.listing} · results dates from DART` })
        : link(b.symbol)]),
      el('td', { class: b.next?.projected ? 'dim' : '', text: b.next ? `${b.next.date}${b.next.timing ? ` ${b.next.timing.toUpperCase()}` : ''}${b.next.projected ? ' (proj.)' : ''}` : DASH }),
      el('td', { class: s.beta >= 0.3 ? 'up' : s.beta < 0 ? 'down' : '', text: s.beta === undefined ? DASH : num(s.beta, 2) }),
      el('td', { class: s.hit >= 0.75 ? 'up' : s.hit < 0.5 ? 'down' : '', text: s.hit === undefined || s.hit === null ? DASH : `${Math.round(s.hit * 100)}%` }),
      el('td', { class: 'dim', text: s.mean_abs === undefined ? DASH : `±${num(s.mean_abs, 1)}%` }),
      el('td', { class: 'dim', text: b.own_mean_abs ? `±${num(b.own_mean_abs, 1)}%` : DASH }),
      el('td', { class: dirClass(b.last?.move_pct), text: b.last ? `${pct(b.last.move_pct, 1)} → ${pct(b.last.proxy_pct, 1)}` : DASH }),
      el('td', { class: 'dim', text: String(s.n ?? b.reports ?? 0) }),
    ]);
  });
  const proxyNote = g.proxy_is_etf
    ? `Proxy ${g.proxy}: its move beyond the S&P 500 on each bellwether's reaction session, per 1% of the bellwether's own excess move. The ETF holds the bellwether itself, so part of the beta is its own weight.`
    : `Proxy: ${g.proxy}, leaving the bellwether out of the basket for its own score.`;
  const korean = g.bellwethers.some((b) => b.listing)
    ? ' Korean names: results dates from DART; own move on the Korean session beyond KOSPI, the proxy on the US session of the same date (the first to trade after a Korean-morning release).' : '';
  return card('BELLWETHERS · WHAT THEIR REPORTS DID TO THE THEME', null, [
    table(['NAME', 'NEXT REPORT', 'PROXY β', 'SAME WAY', 'AVG |PROXY|', 'AVG |OWN|', 'LAST: OWN → PROXY', 'N'], rows),
    el('div', { class: 'field-note', text: `${proxyNote} N = past reports scored (8-K Item 2.02; TSMC and ASML from their 6-K results filings).${korean} History, not a forecast.` }),
  ]);
}

// The proxy against both indices, rebased to 100 at the start of the range.
function relativeCard(g) {
  const spx = g.relative?.SPX;
  const ndx = g.relative?.NDX;
  if (!spx?.dates?.length) return card('AGAINST THE INDICES', null, gap('No proxy history.'));
  const node = el('div', { class: 'chart short' });
  const ranges = availableRanges(spx.dates);
  let active = ranges.includes('1Y') ? '1Y' : ranges[ranges.length - 1];
  const ndxBy = new Map((ndx?.dates || []).map((d, i) => [d, ndx.values[i]]));
  const draw = () => {
    const cut = sliceRange(spx.dates, { spx: spx.values, ndx: spx.dates.map((d) => ndxBy.get(d) ?? null) }, active);
    const rebase = (values) => {
      const first = values.find((v) => v !== null && v !== undefined);
      return values.map((v) => (v === null || v === undefined || !first ? null : Math.round((1000 * v) / first) / 10));
    };
    const label = g.proxy_is_etf ? g.proxy : 'basket';
    render(node, (option, p) => ({
      ...option,
      grid: { left: 44, right: 16, top: 26, bottom: 26 },
      legend: { top: 0, textStyle: { color: p.dim, fontSize: 9 }, itemWidth: 10, itemHeight: 2 },
      tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: (v) => (v === null || v === undefined ? DASH : num(v, 1)) },
      xAxis: { ...option.xAxis, data: cut.dates },
      yAxis: { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 9 } },
      series: [
        { name: `${label} / S&P 500`, type: 'line', data: rebase(cut.spx), showSymbol: false, lineStyle: { color: p.accent, width: 1.5 }, itemStyle: { color: p.accent },
          markLine: { silent: true, symbol: 'none', data: [{ yAxis: 100 }], lineStyle: { color: p.faint }, label: { show: false } } },
        ...(ndx ? [{ name: `${label} / Nasdaq 100`, type: 'line', data: rebase(cut.ndx), showSymbol: false, connectNulls: true, lineStyle: { color: p.blue, width: 1.3 }, itemStyle: { color: p.blue } }] : []),
      ],
    }));
  };
  requestAnimationFrame(draw);
  const pick = Object.assign(periodSwitch(ranges, active, (r) => { active = r; draw(); }), { className: 'period-switch range-switch' });
  return card('AGAINST THE S&P 500 AND NASDAQ 100', el('span', { class: 'tag-row' }, [el('span', { class: 'dim', text: '= 100 at the start · rising = outperforming' }), pick]), node);
}

// --- CLOUD -------------------------------------------------------------------------

function capexCard(capex) {
  if (capex.unavailable) return card('HYPERSCALER CAPEX', null, unavailable(capex));
  const quarters = [...new Set(capex.companies.flatMap((c) => c.quarters.map((q) => q.quarter)))].sort();
  const totals = new Map(capex.totals.map((t) => [t.quarter, t]));
  const chart = viewChart({
    dates: quarters, type: 'stack', views: VIEWS.quarterly(), tail: 8, fmt: (v) => `$${num(v, 0)}B`,
    series: capex.companies.map((c) => ({ name: c.symbol, values: quarters.map((q) => c.quarters.find((x) => x.quarter === q)?.capex_bn ?? null) })),
    changeOnly: [{ name: 'all five', width: 2.2, color: (p) => p.text, values: quarters.map((q) => (totals.get(q)?.complete ? totals.get(q).capex_bn : null)) }],
  });
  const rows = capex.companies.map((c) => {
    const q = c.quarters[c.quarters.length - 1] || {};
    return el('tr', {}, [
      el('td', {}, [link(c.symbol)]),
      el('td', { text: `${q.end || DASH}` }),
      el('td', { text: q.capex_bn === undefined ? DASH : `$${num(q.capex_bn, 1)}B` }),
      pctCell(q.yoy_pct),
      el('td', { class: 'dim', text: q.leases_bn === null || q.leases_bn === undefined ? DASH : `$${num(q.leases_bn, 1)}B` }),
      el('td', { class: 'dim', text: q.filed || DASH }),
    ]);
  });
  const last = capex.totals.filter((t) => t.complete).pop();
  return card('HYPERSCALER CAPEX · SEC 10-Q / 10-K', el('span', { class: 'tag-row' }, [
    last ? tag(`${last.quarter} TOTAL $${num(last.capex_bn, 0)}B · ${pct(last.yoy_pct, 0)} Y/Y`, 'warn') : null,
    el('span', { class: 'dim', text: `latest filing ${capex.latest_filed || DASH}` }),
  ]), [
    chart,
    table(['NAME', 'QUARTER TO', 'CAPEX', 'Y/Y', '+ FINANCE LEASES', 'FILED'], rows),
    el('div', { class: 'field-note', text: 'Purchases of property and equipment from each filing\'s cash-flow statement (quarters derived from year-to-date figures where only those are filed). Finance leases: right-of-use assets taken on under new finance leases, not in capex. Oracle\'s quarters end Aug/Nov/Feb/May and count toward the calendar quarter they mostly cover; the five-company line in the change views is shown only where all five have filed.' }),
  ]);
}

function twRevenueCard(title, series, note) {
  if (series.unavailable) return card(title, null, unavailable(series));
  const months = [...new Set(series.flatMap((s) => s.months.map((m) => m.month)))].sort();
  const chart = viewChart({
    dates: months, views: VIEWS.monthly(), tail: 24, initial: 'YoY', fmt: (v) => `NT$${num(v, 0)}B`,
    series: series.map((s) => ({ name: s.label, values: months.map((m) => { const r = s.months.find((x) => x.month === m); return r?.revenue_k ? r.revenue_k / 1e6 : null; }) })),
  });
  const rows = series.map((s) => {
    const m = s.months[s.months.length - 1] || {};
    return el('tr', {}, [
      el('td', { text: `${s.label} (${s.code})` }),
      el('td', { text: m.month || DASH }),
      el('td', { text: m.revenue_k ? `NT$${num(m.revenue_k / 1e6, 1)}B` : DASH }),
      pctCell(m.yoy_pct),
      pctCell(m.ytd_yoy_pct),
      el('td', { class: s.due?.late ? 'down' : 'dim', text: s.due ? `${s.due.month} due ${s.due.due}${s.due.late ? ' · late' : ''}` : DASH }),
    ]);
  });
  return card(title, el('span', { class: 'dim', text: 'MOPS monthly revenue' }), [
    chart,
    table(['COMPANY', 'MONTH', 'REVENUE', 'Y/Y', 'YTD Y/Y', 'NEXT'], rows),
    el('div', { class: 'field-note', text: note }),
  ]);
}

function openrouterCard(or) {
  if (or.unavailable) return card('OPENROUTER · TOKENS & ESTIMATED REVENUE', null, unavailable(or));
  const common = { dates: or.dates, views: VIEWS.daily(), tail: 150 };
  const revenue = viewChart({ ...common, title: 'ESTIMATED REVENUE / DAY · 7D AVG', fmt: (v) => `$${num(v, 0)}k`,
    series: or.providers.map((p) => ({ name: p.name, values: rolling(p.revenue_k, 7) })) });
  const tokens = viewChart({ ...common, title: 'TOKENS / DAY · 7D AVG', fmt: (v) => `${num(v, 0)}B`,
    series: or.providers.map((p) => ({ name: p.name, values: rolling(p.tokens_b, 7) })) });
  const rows = [...or.providers].sort((a, b) => b.week_revenue_k - a.week_revenue_k).map((p) => el('tr', {}, [
    el('td', { text: p.name }),
    el('td', { text: `$${num(p.week_revenue_k / 1000, 2)}M` }),
    el('td', { class: 'dim', text: p.revenue_share_pct === null ? DASH : `${num(p.revenue_share_pct, 1)}%` }),
    pctCell(p.revenue_vs_4w_pct),
    el('td', { text: `${num(p.week_tokens_b / 1000, 2)}T` }),
    pctCell(p.tokens_vs_4w_pct),
  ]));
  return card('OPENROUTER · TOKENS & ESTIMATED REVENUE BY MODEL AUTHOR', el('span', { class: 'dim', text: `through ${or.dates[or.dates.length - 1]}${or.commit ? ` · alternative-data ${or.commit.sha.slice(0, 7)}` : ''}` }), [
    el('div', { class: 'grid two' }, [revenue, tokens]),
    table(['AUTHOR', 'LAST 7D REVENUE', 'SHARE', 'VS PRIOR 4W', 'LAST 7D TOKENS', 'VS PRIOR 4W'], rows),
    el('div', { class: 'field-note', text: 'OpenRouter\'s routed traffic only -- a slice of each lab\'s demand, not its revenue. Revenue is alternative-data\'s estimate: observed tokens at the model\'s list price at the time. Today\'s partial day is left out. WoW / 4W compare the 7-day average with the one 7 / 28 days earlier.' }),
  ]);
}

function rampCard(ramp) {
  if (ramp.unavailable) return card('RAMP AI INDEX', null, unavailable(ramp));
  const last = ramp.months.length - 1;
  const mom = (values) => (last > 0 && values[last - 1] ? `${pct(100 * (values[last] / values[last - 1] - 1), 1)} m/m` : '');
  const spend = viewChart({
    title: 'AI SPEND PER EMPLOYEE PER MONTH', dates: ramp.months, views: VIEWS.monthly(), fmt: (v) => `$${num(v, v < 10 ? 1 : 0)}`,
    series: [
      { name: 'median', values: ramp.median_pepm, color: (p) => p.accent, width: 2 },
      { name: '90th pct', values: ramp.p90_pepm, color: (p) => p.blue },
      { name: '99th pct', values: ramp.p99_pepm, color: (p) => p.purple },
      { name: 'top-10% median', values: ramp.top10_median_pepm, hidden: true },
      { name: 'top-1% median', values: ramp.top1_median_pepm, hidden: true },
    ],
  });
  const adoption = viewChart({
    title: 'ADOPTION · % OF BUSINESSES', dates: ramp.adoption.months, views: VIEWS.monthly('diff'), fmt: (v) => `${num(v, 0)}%`,
    series: [{ name: 'paying for AI', values: ramp.adoption.pct, color: (p) => p.accent, width: 2 }],
  });
  const vendorMonths = [...new Set(Object.values(ramp.vendors).flatMap((v) => v.months))].sort();
  const vendors = viewChart({
    title: 'ADOPTION BY VENDOR · % OF BUSINESSES', dates: vendorMonths, views: VIEWS.monthly('diff'), fmt: (v) => `${num(v, 0)}%`,
    series: Object.entries(ramp.vendors).map(([name, v]) => ({ name, values: vendorMonths.map((m) => v.pct[v.months.indexOf(m)] ?? null) })),
  });
  const adopt = ramp.adoption.pct[ramp.adoption.pct.length - 1];
  const sectorRows = ramp.sectors.rows.slice(0, 8).map((r) => el('tr', {}, [el('td', { text: r.sector }), el('td', { text: `$${num(r.median_pepm, 2)}` })]));
  return card('RAMP AI INDEX · US BUSINESSES', el('span', { class: 'dim', text: `through ${ramp.months[last]}` }), [
    el('div', { class: 'stat-strip' }, [
      stat('MEDIAN', `$${num(ramp.median_pepm[last], 2)}`, `per employee per month · ${mom(ramp.median_pepm)}`),
      stat('90TH PERCENTILE', `$${num(ramp.p90_pepm[last], 0)}`, mom(ramp.p90_pepm)),
      stat('99TH PERCENTILE', `$${num(ramp.p99_pepm[last], 0)}`, mom(ramp.p99_pepm)),
      stat('TOP-10% MEDIAN', `$${num(ramp.top10_median_pepm[last], 0)}`, mom(ramp.top10_median_pepm)),
      stat('ADOPTION', `${num(adopt, 1)}%`, `of businesses paying for AI · ${ramp.adoption.months[ramp.adoption.months.length - 1]}`),
    ]),
    spend,
    el('div', { class: 'grid two' }, [adoption, vendors]),
    el('div', { class: 'card-title', text: `MEDIAN SPEND BY SECTOR · ${ramp.sectors.month}` }),
    table(['SECTOR', '$ / EMPLOYEE / MONTH'], sectorRows),
    el('div', { class: 'field-note', text: 'Ramp AI Index (ramp.com/data/ai-index): card and bill-pay spend of businesses on Ramp -- skewed to US small and mid-sized firms. Per-employee spend is across businesses paying for AI. Percentiles span 300×, so RAW draws on a log axis; top-10% / top-1% medians are in the legend, off by default. Read from alternative-data\'s collection.' }),
  ]);
}

function nvdaCard(nv) {
  if (nv.unavailable) return card('NVIDIA DATA CENTER', null, unavailable(nv));
  const q = nv.quarters;
  const labels = q.map((r) => r.filed);
  const chart = viewChart({
    dates: labels, type: 'bar', views: [{ id: 'RAW' }, { id: 'QoQ', lag: 1 },
      { id: 'YoY (stated)', series: [{ name: 'Data Center y/y', values: q.map((r) => r.dc_yoy_pct), color: (p) => p.accent }] }],
    fmt: (v) => `$${num(v, 0)}B`,
    series: [{ name: 'Data Center revenue', values: q.map((r) => r.dc_bn), color: (p) => p.up }],
  });
  const last = q[q.length - 1];
  return card('NVIDIA DATA CENTER REVENUE · FROM ITS RELEASES', el('span', { class: 'tag-row' }, [
    tag(`$${num(last.dc_bn, 1)}B · ${pct(last.dc_yoy_pct, 0)} Y/Y`, 'up'),
    last.outlook_bn ? tag(`NEXT Q REVENUE OUTLOOK $${num(last.outlook_bn, 1)}B`, 'warn') : null,
    el('a', { href: last.url, target: '_blank', rel: 'noopener', text: `release ${last.filed}` }),
  ]), [
    chart,
    el('div', { class: 'field-note', text: 'Quarters are labelled by release date. Segment revenue is not in XBRL company facts, so it is read from each earnings release (8-K Exhibit 99.1); the y/y view is the release\'s own figure. Outlook: total revenue guided for the next quarter.' }),
  ]);
}

function guidanceCard(g) {
  if (g.unavailable) return card('CAPEX GUIDANCE', null, unavailable(g));
  const rows = g.companies.map((c) => {
    const [latest, prior] = c.releases;
    const said = latest?.statements?.length ? latest.statements.join(' ') : null;
    return el('tr', {}, [
      el('td', {}, [link(c.symbol)]),
      el('td', {}, [latest ? el('a', { href: latest.url, target: '_blank', rel: 'noopener', text: latest.filed }) : DASH]),
      el('td', { class: said ? 'wrap-cell' : 'dim wrap-cell', text: said || 'Not stated in the release (given on the call, if at all).' }),
      el('td', { class: 'dim wrap-cell', text: prior?.statements?.length ? `${prior.filed}: ${prior.statements.join(' ')}` : '' }),
    ]);
  });
  return card('CAPEX GUIDANCE · AS WRITTEN IN THE EARNINGS RELEASES', null, [
    table(['NAME', 'RELEASE', 'LATEST', 'PREVIOUS RELEASE'], rows, { class: 'text-cols' }),
    el('div', { class: 'field-note', text: 'Sentences about capital expenditures ahead, quoted from each 8-K Exhibit 99.1. Microsoft, Alphabet and Amazon give their outlook on the call, not in the release, so they show none here.' }),
  ]);
}

function heatmapCard(h) {
  if (!h?.dates?.length) return null;
  const max = Math.max(...h.rows.flatMap((r) => r.cells.map((c) => c?.w || 0)), 0.01);
  const day = (d) => new Date(`${d}T00:00:00Z`).toUTCString().slice(0, 11);
  const head = el('tr', {}, [el('th', { text: 'SECTOR' }), ...h.dates.map((d) => el('th', { class: 'heat-day', text: day(d) })), el('th', { text: 'TOTAL' })]);
  const rows = h.rows.map((r) => el('tr', {}, [
    el('td', { class: 'heat-sector', text: r.sector }),
    ...r.cells.map((c) => el('td', {
      class: 'heat-cell', style: c ? `--heat:${Math.round((100 * c.w) / max)}%` : null,
      title: c ? `${c.n} reporting · ${c.top.join(', ')}` : '', text: c ? num(c.w, c.w < 1 ? 2 : 1) : '',
    })),
    el('td', { class: 'dim', text: `${num(r.total, 1)}%` }),
  ]));
  const totals = el('tr', {}, [el('td', { class: 'dim', text: 'ALL' }), ...h.day_totals.map((t) => el('td', { class: 'dim heat-total', text: t ? num(t, 1) : '' })), el('td', {})]);
  return card('EARNINGS WEIGHT BY SECTOR · NEXT THREE WEEKS', el('span', { class: 'dim', text: '% of S&P 500 weight reporting; hover for names' }),
    el('div', { class: 'table-scroll' }, [el('table', { class: 'data heatmap-table' }, [el('thead', {}, [head]), el('tbody', {}, [...rows, totals])])]));
}

// --- SEMIS -------------------------------------------------------------------------

function koreaCard(k) {
  if (k.unavailable) return card('KOREA IC EXPORTS', null, unavailable(k));
  const chart = viewChart({
    dates: k.months.map((m) => m.month), type: 'bar', views: VIEWS.monthly(), tail: 24, fmt: (v) => `$${num(v, 0)}B`,
    series: [{ name: 'IC exports $B', values: k.months.map((m) => m.exports_bn), color: (p) => p.blue }],
  });
  const last = k.months[k.months.length - 1] || {};
  return card('KOREA IC EXPORTS · HS 8542', el('span', { class: 'tag-row' }, [
    tag(`${last.month} $${num(last.exports_bn, 1)}B · ${pct(last.yoy_pct, 0)} Y/Y`, last.yoy_pct > 0 ? 'up' : 'down'),
    el('span', { class: k.due?.late ? 'down' : 'dim', text: k.due ? `${k.due.month} due ~${k.due.due}` : '' }),
  ]), [
    chart,
    el('div', { class: 'field-note', text: 'Korea Customs Service, confirmed monthly exports of electronic integrated circuits (memory is most of it), customs-acceptance basis, USD. The ministry\'s 1st-of-month flash is earlier but not read here.' }),
  ]);
}

function koreaFlashCard(k) {
  if (k.unavailable) return card('KOREA EXPORTS · 1ST-OF-MONTH RELEASE', null, unavailable(k));
  const m = k.months;
  const chart = viewChart({
    dates: m.map((r) => r.month), type: 'bar', fmt: (v) => `$${num(v, 0)}B`,
    views: [{ id: 'RAW' }, { id: 'MoM', lag: 1 },
      { id: 'YoY (stated)', series: [
        { name: 'semiconductors y/y', values: m.map((r) => r.semis_yoy_pct), color: (p) => p.accent },
        { name: 'all exports y/y', values: m.map((r) => r.total_yoy_pct), color: (p) => p.dim },
      ] }],
    series: [{ name: 'semiconductor exports $B', values: m.map((r) => r.semis_bn), color: (p) => p.blue }],
  });
  const last = m[m.length - 1] || {};
  return card('KOREA EXPORTS · 1ST-OF-MONTH RELEASE', el('span', { class: 'tag-row' }, [
    tag(`${last.month} SEMIS $${num(last.semis_bn, 1)}B · ${pct(last.semis_yoy_pct, 0)} Y/Y`, last.semis_yoy_pct > 0 ? 'up' : 'down'),
    el('span', { class: k.due?.late ? 'down' : 'dim', text: k.due ? `${k.due.month} due ${k.due.due}` : '' }),
    last.url ? el('a', { href: last.url, target: '_blank', rel: 'noopener', text: `released ${last.released || ''}` }) : null,
  ]), [
    chart,
    el('div', { class: 'field-note', text: 'Ministry of Trade release on the 1st (09:00 Seoul, the previous evening in New York), read from its PDF: about two weeks before customs confirms the month. Semiconductors here are the ministry\'s item (chips, not only HS 8542); y/y as the release states it.' }),
  ]);
}

function pcppCard(pc) {
  if (pc.unavailable) {
    // PCPartPicker's Cloudflare answers cloud servers with 403; it is read
    // from a home connection only, and not worked around.
    const refused = /\b403\b/.test(pc.unavailable);
    return card('RETAIL PRICES · PCPARTPICKER UK', null, refused
      ? gap('PCPartPicker refuses requests from the cloud build\'s servers (HTTP 403), so this build has no retail prices. It reads fine from a home connection; its bot protection is not worked around.')
      : unavailable(pc));
  }
  const blocks = [];
  for (const kind of ['memory', 'cpu']) {
    const sec = pc[kind];
    if (!sec) continue;
    const fams = Object.entries(sec.families);
    const dates = fams[0]?.[1].index.dates || [];
    const chart = viewChart({ dates, views: VIEWS.weekly(), fmt: (v) => num(v, 0),
      series: fams.map(([name, f]) => ({ name, values: f.index.values, width: 1.8 })) });
    const famRows = fams.map(([name, f]) => el('tr', {}, [el('td', { text: `${name} (median of ${f.count})` }), pctCell(f.chg_1m), pctCell(f.chg_3m), pctCell(f.chg_6m), pctCell(f.chg_12m)]));
    const rows = sec.rows.map((r) => el('tr', {}, [el('td', { class: 'dim', text: r.title }), pctCell(r.chg_1m), pctCell(r.chg_3m), pctCell(r.chg_6m), pctCell(r.chg_12m)]));
    blocks.push(el('div', {}, [
      el('div', { class: 'card-title', text: kind === 'memory' ? 'MEMORY KITS · INDEX, 18 MONTHS AGO = 100' : 'CPUS · INDEX, 18 MONTHS AGO = 100' }),
      chart,
      table(['', '1M', '3M', '6M', '12M'], famRows),
      el('details', { class: 'method-fold' }, [el('summary', { text: `EACH ${kind === 'memory' ? 'KIT' : 'CPU GROUP'} · CHANGE %` }),
        table(['', '1M', '3M', '6M', '12M'], rows)]),
    ]));
  }
  const date = pc.memory?.rows?.[0]?.image_date || pc.cpu?.rows?.[0]?.image_date;
  return card('RETAIL PRICES · PCPARTPICKER UK', el('span', { class: 'dim', text: `charts of ${date || DASH}` }), [
    el('div', { class: 'grid two' }, blocks),
    pc.failed?.length ? el('div', { class: 'field-note down', text: `Not read: ${pc.failed.join('; ')}` }) : null,
    el('div', { class: 'field-note', text: 'Average UK retail price across sellers, read from the pixels of PCPartPicker\'s daily trend charts (the axis starts at zero, so ratios need no scale; about ±2.5% at a tenth of the axis). Kit averages jump when sellers enter or leave. Source: uk.pcpartpicker.com/trends.' }),
  ]);
}

function adataCard(a) {
  if (a.unavailable) return card('ADATA MEMORY MARKET WATCH', null, unavailable(a));
  const [latest, ...older] = a.notes || [];
  if (!latest) return card('ADATA MEMORY MARKET WATCH', null, gap('No note read.'));
  const para = (label, text) => (text ? el('div', { class: 'adata-para' }, [el('span', { class: 'stat-label', text: label }), el('div', { text })]) : null);
  return card('ADATA MEMORY & FLASH MARKET WATCH', el('span', { class: 'tag-row' }, [
    ...(latest.figures || []).map((f) => tag(f, f.startsWith('-') ? 'down' : 'warn')),
    el('a', { href: latest.url, target: '_blank', rel: 'noopener', text: latest.month }),
  ]), [
    latest.headline ? el('div', { class: 'adata-headline', text: latest.headline }) : null,
    el('div', { class: 'grid two' }, [
      el('div', {}, [para('DRAM PRICE', latest.dram_price), para('DRAM SUPPLY', latest.dram_sufficiency)]),
      el('div', {}, [para('NAND PRICE', latest.nand_price), para('NAND SUPPLY', latest.nand_sufficiency)]),
    ]),
    older.length ? el('details', { class: 'method-fold' }, [el('summary', { text: 'EARLIER MONTHS' }),
      ...older.map((n) => el('div', { class: 'method-copy' }, [el('a', { href: n.url, target: '_blank', rel: 'noopener', text: n.month }), ` ${n.headline || n.dram_price || ''}`]))]) : null,
    el('div', { class: 'field-note', text: 'A memory-module maker\'s monthly read, quoted as written; its charts are images and are not read.' }),
  ]);
}

// --- page --------------------------------------------------------------------------

// --- ENERGY & HOUSING ---------------------------------------------------------------

// One card, a series picker over it: each series keeps its own chart views.
function pickerCard(title, right, entries, note) {
  const ids = entries.map((e) => e.id);
  let active = ids[0];
  const host = el('div', {});
  const draw = () => host.replaceChildren(entries.find((e) => e.id === active).chart());
  draw();
  const picker = ids.length > 1 ? periodSwitch(ids, active, (id) => { active = id; draw(); }) : null;
  return card(title, el('span', { class: 'tag-row' }, [right, picker]), [host, note ? el('div', { class: 'field-note', text: note }) : null]);
}

const EIA_ORDER = ['crude_stocks', 'gasoline_stocks', 'distillate_stocks', 'gas_storage', 'refinery_utilization', 'crude_production'];
const EIA_SHORT = { crude_stocks: 'CRUDE', gasoline_stocks: 'GASOLINE', distillate_stocks: 'DISTILLATE', gas_storage: 'NAT GAS',
  refinery_utilization: 'REFINERY UTIL', crude_production: 'PRODUCTION' };

function eiaValue(unit, v) {
  if (v === null || v === undefined) return DASH;
  if (unit === 'mb') return `${num(v / 1000, 1)} mb`;
  if (unit === 'pct') return `${num(v, 1)}%`;
  if (unit === 'kbd') return `${num(v / 1000, 2)} mb/d`;
  return `${num(v, 0)} bcf`;
}

function eiaCard(e) {
  if (!e || e.unavailable) return card('EIA WEEKLY', null, unavailable(e));
  const keys = EIA_ORDER.filter((k) => e.eia[k] && !e.eia[k].unavailable);
  const strip = el('div', { class: 'stat-strip' }, keys.map((k) => {
    const x = e.eia[k];
    const l = x.latest;
    const change = x.unit === 'pct' ? `${l.change > 0 ? '+' : ''}${num(l.change, 1)}pp w/w` : `${l.change > 0 ? '+' : ''}${eiaValue(x.unit, l.change)} w/w`;
    return stat(EIA_SHORT[k], eiaValue(x.unit, l.value),
      `${change} · ${l.vs_avg5_pct === null ? DASH : `${l.vs_avg5_pct > 0 ? '+' : ''}${num(l.vs_avg5_pct, 1)}% vs 5y`} · wk ${l.date.slice(5)}`,
      // Inventories above the seasonal norm weigh on prices, below support them.
      k.endsWith('stocks') || k === 'gas_storage' ? (l.vs_avg5_pct > 0 ? 'down' : 'up') : '');
  }));
  const entries = keys.map((k) => {
    const x = e.eia[k];
    const fmt = (v) => eiaValue(x.unit, v);
    return { id: EIA_SHORT[k], chart: () => viewChart({
      dates: x.dates, fmt, views: [{ id: 'RAW' }, { id: 'WoW', lag: 1, kind: x.unit === 'pct' ? 'diff' : 'pct' }, { id: 'YoY', lag: 52, kind: x.unit === 'pct' ? 'diff' : 'pct' },
        { id: 'VS 5Y AVG', series: [{ name: `${x.label} vs 5-year average, %`, values: x.value.map((v, i) => (v === null || !x.avg5[i] ? null : Math.round((v / x.avg5[i] - 1) * 1000) / 10)), color: (p) => p.accent }] }],
      series: [{ name: x.label, values: x.value, color: (p) => p.text, width: 1.6 },
        { name: 'same week, 5-year average', values: x.avg5, color: (p) => p.dim }],
    }) };
  });
  const next = e.next || {};
  return el('div', {}, [
    card('EIA WEEKLY · INVENTORIES AGAINST THE SAME WEEK OF THE LAST 5 YEARS', el('span', { class: 'dim', text: `next: petroleum ${next.petroleum || DASH} · gas ${next.gas_storage || DASH}` }), [strip]),
    pickerCard('EIA WEEKLY · CHART', null, entries,
      'EIA Weekly Petroleum Status Report (Wednesdays 10:30 ET) and Natural Gas Storage Report (Thursdays 10:30 ET), from EIA\'s history pages; week-ending dates. '
      + '5-year average: the same week of the year over the five years before, as EIA compares it. Inventory above it is coloured red (weighs on prices), below green.'),
  ]);
}

function pricesCard(e) {
  if (!e || e.unavailable || !e.prices) return null;
  const p = e.prices;
  const series = (key, color) => (p[key] ? { name: p[key].label, values: p[key].values, color } : null);
  const dated = (key) => p[key]?.dates || [];
  const entries = [];
  if (p['CL=F']) {
    entries.push({ id: 'CRUDE', chart: () => viewChart({ dates: dated('CL=F'), views: VIEWS.daily(), fmt: (v) => `$${num(v, 0)}`,
      series: [series('CL=F', (c) => c.text), p['BZ=F'] && p['BZ=F'].dates.length === p['CL=F'].dates.length ? series('BZ=F', (c) => c.accent) : null].filter(Boolean) }) });
  }
  if (p['NG=F']) entries.push({ id: 'NAT GAS', chart: () => viewChart({ dates: dated('NG=F'), views: VIEWS.daily(), fmt: (v) => `$${num(v, 2)}`, series: [series('NG=F', (c) => c.blue)] }) });
  if (p.crack) entries.push({ id: '3-2-1 CRACK', chart: () => viewChart({ dates: dated('crack'), views: [{ id: 'RAW' }, { id: 'WoW', lag: 5, kind: 'diff' }, { id: '4W', lag: 20, kind: 'diff' }], fmt: (v) => `$${num(v, 0)}`, series: [series('crack', (c) => c.accent)] }) });
  if (e.retail_gasoline) entries.push({ id: 'PUMP PRICE', chart: () => viewChart({ dates: e.retail_gasoline.dates, views: VIEWS.weekly(), fmt: (v) => `$${num(v, 2)}`, series: [{ name: 'US regular gasoline, $/gal', values: e.retail_gasoline.values, color: (c) => c.text }] }) });
  const last = (key) => (p[key] ? p[key].values[p[key].values.length - 1] : null);
  const right = el('span', { class: 'dim', text: [last('CL=F') !== null ? `WTI $${num(last('CL=F'), 2)}` : null, last('NG=F') !== null ? `HH $${num(last('NG=F'), 2)}` : null,
    last('crack') !== null ? `crack $${num(last('crack'), 1)}` : null].filter(Boolean).join(' · ') });
  return pickerCard('OIL, GAS & REFINING MARGIN', right, entries,
    'Front-month futures (Yahoo: CL, BZ, NG, RB, HO). 3-2-1 crack = (2 bbl gasoline + 1 bbl heating oil − 3 bbl crude) / 3, $/bbl -- the refiners\' margin. Pump price: EIA weekly US regular, via FRED.');
}

// How each name's excess return over the S&P 500 has moved with each driver
// over the last year: it says which data the basket actually trades on.
function sensitivityCard(title, s, note) {
  if (!s || !s.rows?.length) return null;
  const keys = Object.keys(s.drivers);
  const rows = s.rows.map((r) => el('tr', {}, [
    el('td', {}, [link(r.symbol)]),
    ...keys.flatMap((k) => {
      const x = r[k];
      return [el('td', { class: !x ? 'dim' : Math.abs(x.corr) >= 0.5 ? 'accent-text' : Math.abs(x.corr) < 0.2 ? 'dim' : '', text: x ? num(x.corr, 2) : DASH }),
        el('td', { class: 'dim', text: x ? num(x.beta, 3) : DASH })];
    }),
  ]));
  const head = ['NAME', ...keys.flatMap((k) => [`${k.toUpperCase().replace('_', ' ')} CORR`, 'BETA'])];
  return card(title, el('span', { class: 'dim', text: keys.map((k) => s.drivers[k]).join(' · ') }), [
    table(head, rows), el('div', { class: 'field-note', text: note }),
  ]);
}

function housingCards(h) {
  if (!h || h.unavailable) return [card('HOUSING DATA', null, unavailable(h))];
  const s = h.series;
  const ok = (id) => s[id] && !s[id].unavailable;
  const mortgage = ok('MORTGAGE30US') ? (() => {
    const m = s.MORTGAGE30US;
    const last = m.values[m.values.length - 1];
    const yearAgo = m.values[m.values.length - 53];
    return card('30-YEAR MORTGAGE RATE · WEEKLY', el('span', { class: 'tag-row' }, [
      tag(`${num(last, 2)}% · ${m.dates[m.dates.length - 1]}`, 'dim'),
      yearAgo ? tag(`${last - yearAgo > 0 ? '+' : ''}${num(last - yearAgo, 2)}pp y/y`, last > yearAgo ? 'down' : 'up') : null,
      el('span', { class: 'dim', text: `next ${h.next?.mortgage_rate || DASH}` }),
    ]), [viewChart({ dates: m.dates, views: [{ id: 'RAW' }, { id: 'Δ 4W', lag: 4, kind: 'diff' }, { id: 'Δ 13W', lag: 13, kind: 'diff' }, { id: 'Δ YoY', lag: 52, kind: 'diff' }],
      fmt: (v) => `${num(v, 2)}%`, series: [{ name: '30-year fixed, %', values: m.values, color: (p) => p.accent }] })]);
  })() : null;
  const monthly = (ids, fmt) => {
    const first = s[ids[0]];
    return () => viewChart({ dates: first.dates.map((d) => d.slice(0, 7)), views: VIEWS.monthly(), fmt,
      series: ids.filter(ok).map((id, i) => ({ name: s[id].label, values: s[id].values, color: i ? (p) => p.dim : (p) => p.text })) });
  };
  const entries = [];
  if (ok('HOUST')) entries.push({ id: 'STARTS', chart: monthly(['HOUST', 'HOUST1F'], (v) => num(v, 0)) });
  if (ok('PERMIT')) entries.push({ id: 'PERMITS', chart: monthly(['PERMIT'], (v) => num(v, 0)) });
  if (ok('HSN1F')) entries.push({ id: 'NEW HOME SALES', chart: monthly(['HSN1F'], (v) => num(v, 0)) });
  if (ok('MSACSR')) entries.push({ id: 'MONTHS SUPPLY', chart: monthly(['MSACSR'], (v) => num(v, 1)) });
  if (ok('CSUSHPINSA')) entries.push({ id: 'CASE-SHILLER', chart: monthly(['CSUSHPINSA'], (v) => num(v, 0)) });
  const latest = (id) => (ok(id) ? s[id].values[s[id].values.length - 1] : null);
  const right = el('span', { class: 'dim', text: [latest('HOUST') !== null ? `starts ${num(latest('HOUST'), 0)}k` : null,
    latest('HSN1F') !== null ? `new sales ${num(latest('HSN1F'), 0)}k` : null, latest('MSACSR') !== null ? `${num(latest('MSACSR'), 1)} months' supply` : null].filter(Boolean).join(' · ') });
  return [mortgage, pickerCard('HOUSING ACTIVITY & PRICES · MONTHLY', right, entries,
    'Census (starts, permits, new home sales, months\' supply; SAAR, thousands) and S&P CoreLogic Case-Shiller (not seasonally adjusted), via FRED -- the current vintage, so revised months show their revised value. '
    + 'Release days are on the calendar above.')].filter(Boolean);
}

// --- BANKS & CONSUMER ---------------------------------------------------------------

const POINTS = new Set(['rate', 'pct']);

function fredValue(unit, v) {
  if (v === null || v === undefined) return DASH;
  if (unit === 'bn') return `$${num(v / 1000, 2)}T`;
  if (unit === 'm') return v >= 1e6 ? `$${num(v / 1e6, 2)}T` : `$${num(v / 1000, 1)}bn`;
  if (unit === 'rate') return `${num(v, 2)}%`;
  if (unit === 'pct') return `${num(v, 1)}%`;
  if (unit === 'count') return `${num(v / 1000, 0)}k`;
  return num(v, 1);
}

// A rate or spread moves in basis points, a net-percent survey in points, a level in percent.
function fredChange(unit, v) {
  if (v === null || v === undefined) return DASH;
  if (unit === 'rate') return `${v > 0 ? '+' : ''}${num(v * 100, 0)}bp`;
  if (unit === 'pct') return `${v > 0 ? '+' : ''}${num(v, 1)}pp`;
  return `${v > 0 ? '+' : ''}${num(v, 1)}%`;
}

function fredViews(x) {
  const kind = POINTS.has(x.unit) ? 'diff' : 'pct';
  if (x.freq === 'daily') return [{ id: 'RAW' }, { id: 'Δ 1M', lag: 21, kind: 'diff' }, { id: 'Δ 3M', lag: 63, kind: 'diff' }, { id: 'Δ 1Y', lag: 252, kind: 'diff' }];
  if (x.freq === 'weekly') return [{ id: 'RAW' }, { id: '4W', lag: 4, kind }, { id: '13W', lag: 13, kind }, { id: 'YoY', lag: 52, kind }];
  if (x.freq === 'quarterly') return [{ id: 'RAW' }, { id: 'QoQ', lag: 1, kind }, { id: 'YoY', lag: 4, kind }];
  return VIEWS.monthly(kind);
}

const STEP = { daily: 'd/d', weekly: 'w/w', monthly: 'm/m', quarterly: 'q/q' };

// One stat per series (latest, its change on the prior print and on a year
// earlier), then each series' chart behind a picker. `tone(id, x)` colours a
// stat: 'up' when it helps the names, 'down' when it hurts, '' when neutral.
function fredCards(section, order, title, chartTitle, note, tone, right) {
  if (!section || section.unavailable) return [card(title, null, unavailable(section))];
  const s = section.series || {};
  const ids = order.filter((id) => s[id] && !s[id].unavailable);
  const failed = order.filter((id) => s[id]?.unavailable);
  const strip = el('div', { class: 'stat-strip' }, ids.map((id) => {
    const x = s[id];
    const l = x.latest;
    return stat(x.short, fredValue(x.unit, l.value),
      `${fredChange(x.unit, l.change)} ${STEP[x.freq]} · ${fredChange(x.unit, l.yoy)} y/y · ${x.freq === 'monthly' || x.freq === 'quarterly' ? l.date.slice(0, 7) : l.date.slice(5)}`,
      tone(id, x));
  }));
  const entries = ids.map((id) => {
    const x = s[id];
    const monthly = x.freq === 'monthly' || x.freq === 'quarterly';
    return { id: x.short, chart: () => viewChart({ dates: monthly ? x.dates.map((d) => d.slice(0, 7)) : x.dates, views: fredViews(x),
      fmt: (v) => fredValue(x.unit, v), series: [{ name: x.label, values: x.values, color: (p) => p.text, width: 1.6 }] }) };
  });
  return [
    card(title, right, [strip, failed.length ? gap(`Not built this time: ${failed.join(', ')}`) : null]),
    pickerCard(chartTitle, null, entries, note),
  ];
}

const BANK_ORDER = ['TOTLL', 'DPSACBW027SBOG', 'T10Y2Y', 'T10Y3M', 'BAMLH0A0HYM2', 'DRALACBS', 'DRCCLACBS', 'DRCRELEXFACBS', 'DRTSCILM'];
const CONSUMER_ORDER = ['RSAFS', 'RSFSXMV', 'PCEC96', 'PSAVERT', 'TOTALSL', 'UMCSENT', 'ICSA', 'CCSA'];

function bankTone(id, x) {
  const l = x.latest;
  if (id === 'TOTLL' || id === 'DPSACBW027SBOG') return l.yoy > 0 ? 'up' : 'down';
  if (id === 'T10Y2Y' || id === 'T10Y3M') return l.value > 0 ? 'up' : 'down';      // banks lend long, fund short
  if (id.startsWith('DR') || id === 'BAMLH0A0HYM2') return l.yoy > 0 ? 'down' : 'up'; // wider, more delinquent, tighter: worse
  return '';
}

function consumerTone(id, x) {
  const l = x.latest;
  if (id === 'ICSA' || id === 'CCSA') return l.yoy > 0 ? 'down' : 'up';
  if (id === 'PSAVERT' || id === 'TOTALSL') return '';
  return l.yoy > 0 ? 'up' : 'down';
}

function banksCards(b) {
  const next = b?.next || {};
  return fredCards(b, BANK_ORDER, 'BANK LENDING, CURVE & CREDIT', 'BANKS · CHART',
    'Fed H.8 (all commercial banks, seasonally adjusted; Fridays 16:15 ET for the week ended nine days before), Treasury curve spreads (FRED T10Y2Y, T10Y3M), ICE BofA US high-yield OAS, '
    + 'call-report delinquency rates (quarterly, about two months after the quarter) and the Senior Loan Officer Survey (net % of banks tightening C&I standards; positive is tightening), via FRED -- the current vintage. '
    + 'Green helps the banks (loans and deposits growing, a positive curve, spreads, delinquencies and standards easing on the year), red hurts.',
    bankTone, el('span', { class: 'dim', text: `next H.8: ${next.h8 || DASH}` }));
}

function consumerCards(c) {
  const next = c?.next || {};
  return fredCards(c, CONSUMER_ORDER, 'CONSUMER SPENDING, CREDIT & JOBS', 'CONSUMER · CHART',
    'Census advance retail sales (nominal, about the 16th of the next month), BEA real PCE and saving rate (end of the next month), Fed G.19 consumer credit (about the 8th, two months on), '
    + 'University of Michigan sentiment (final, late in the month -- FRED carries it a month behind) and Labor Department claims (Thursdays 08:30), via FRED -- the current vintage. '
    + 'Pump prices are on ENERGY. Green: up on the year (claims: down).',
    consumerTone, el('span', { class: 'dim', text: `next claims: ${next.claims || DASH}` }));
}

// --- Release days ------------------------------------------------------------------

function studyValue(unit, v, signedOut = true) {
  if (v === null || v === undefined) return DASH;
  const sign = signedOut && v > 0 ? '+' : '';
  if (unit === 'pct') return `${sign}${num(v, 2)}%`;
  if (unit === 'k') return `${sign}${num(v, 0)}k`;
  if (unit === 'count') return `${sign}${num(v / 1000, 1)}k`;
  if (unit === 'mb') return `${sign}${num(v / 1000, 1)} mb`;
  return `${sign}${num(v, 2)}`;
}

// How the theme's ETF moved beyond the S&P 500 on each release's session:
// whether the market cares (|move| on the day against any other day) and
// whether it moved with the print.
function studyCard(study, failed) {
  if (failed) return card('RELEASE DAYS', null, unavailable(failed));
  if (!study?.rows?.length) return null;
  const head = ['RELEASE', 'SINCE', 'N', '|ETF−SPX| ON THE DAY', 'VS OTHER DAYS', 'UP · ABOVE TREND', 'UP · BELOW TREND', 'RANK CORR', 'LAST PRINT'];
  const rows = study.rows.map((r) => {
    if (r.unavailable) return el('tr', {}, [el('td', { text: r.label }), el('td', { class: 'dim', colspan: '8', text: r.unavailable })]);
    const last = r.recent?.[0];
    return el('tr', {}, [
      el('td', { text: r.label }),
      el('td', { class: 'dim', text: r.since.slice(0, 7) }),
      el('td', { text: String(r.n) }),
      el('td', { text: `${num(r.abs_move, 2)}%` }),
      el('td', { class: r.attention >= 1.3 ? 'accent-text' : r.attention < 1.1 ? 'dim' : '', text: r.attention ? `${num(r.attention, 2)}×` : DASH }),
      el('td', { text: r.up_above === null ? DASH : `${r.up_above}% of ${r.n_above}` }),
      el('td', { text: r.up_below === null ? DASH : `${r.up_below}% of ${r.n_below}` }),
      el('td', { class: r.corr === null ? 'dim' : Math.abs(r.corr) >= 0.2 ? 'accent-text' : 'dim', text: r.corr === null ? DASH : num(r.corr, 2) }),
      el('td', {}, last ? [`${last.released.slice(5)} ${studyValue(r.unit, last.headline)} `,
        el('span', { class: 'dim', text: `(${studyValue(r.unit, last.surprise)} vs trend) ` }), el('span', { class: dirClass(last.move), text: pct(last.move, 2) })] : [DASH]),
    ]);
  });
  const details = study.rows.filter((r) => r.recent?.length).map((r) => el('details', { class: 'method-fold' }, [
    el('summary', { text: `${r.label.toUpperCase()} · LAST ${r.recent.length}` }),
    table(['PERIOD', 'RELEASED', 'PRINT', 'VS TREND', `${study.proxy} − SPX`], r.recent.map((x) => el('tr', {}, [
      el('td', { text: r.unit === 'pct' || r.unit === 'k' ? x.period.slice(0, 7) : x.period }),
      el('td', { class: 'dim', text: x.released }),
      el('td', { text: studyValue(r.unit, x.headline) }),
      el('td', { class: 'dim', text: studyValue(r.unit, x.surprise) }),
      el('td', { class: dirClass(x.move), text: pct(x.move, 2) }),
    ]))),
  ]));
  return card(`RELEASE DAYS · WHAT ${study.proxy} DID AGAINST THE S&P 500`, el('span', { class: 'dim', text: 'history, not a forecast' }), [
    table(head, rows), ...details,
    el('div', { class: 'field-note', text: 'Each release\'s session (all come out before or during it): the ETF\'s return less the S&P 500\'s. VS OTHER DAYS: its average size against every other session since -- near 1×, the release day looks like any other. '
      + 'With no free consensus history, a print is "above trend" when its change beats the median of the 12 before it, not when it beats forecasts. RANK CORR: between that and the move. '
      + 'Release days and first prints (the prior month as it stood that day) from ALFRED, FRED\'s vintage archive; EIA on the Wednesday after the week. Other news the same day counts too.' }),
  ]);
}

function industry(key, data) {
  if (key === 'cloud') {
    const c = data.cloud;
    return [capexCard(c.capex), guidanceCard(c.guidance), nvdaCard(c.nvda),
      twRevenueCard('AI SERVER MAKERS · MONTHLY REVENUE', c.odm, 'Quanta, Wiwynn and Wistron build most hyperscaler AI servers; their revenue is capex being delivered, reported by the 10th of the next month. Foxconn is left out: iPhone assembly dominates it.'),
      openrouterCard(c.openrouter), rampCard(c.ramp)];
  }
  if (key === 'semis') {
    const s = data.semis;
    return [el('div', { class: 'grid two' }, [
      twRevenueCard('TSMC & NANYA · MONTHLY REVENUE', s.tw, 'TSMC: leading-edge foundry demand. Nanya: commodity DRAM, the purest listed read on DRAM pricing. Published by the 10th of the next month.'),
      koreaFlashCard(s.korea_flash)]),
    koreaCard(s.korea),
    adataCard(s.adata), pcppCard(s.pcpp)];
  }
  if (key === 'energy' && data.energy) {
    const e = data.energy;
    return [eiaCard(e), pricesCard(e), sensitivityCard('WHAT MOVES THE NAMES · LAST 252 SESSIONS', e.sensitivity,
      'Correlation and beta of each name\'s daily return beyond the S&P 500 with the driver\'s daily change. Producers trade on crude; refiners also on the crack; services on neither as much. History, not a forecast.')].filter(Boolean);
  }
  if (key === 'housing' && data.housing) {
    const h = data.housing;
    return [...housingCards(h), sensitivityCard('WHAT MOVES THE NAMES · LAST 252 SESSIONS', h.sensitivity,
      'Correlation and beta (% per 1bp) of each name\'s daily return beyond the S&P 500 with the daily change in the 10-year Treasury yield (FRED DGS10). Negative: the names fall when rates rise.')].filter(Boolean);
  }
  if (key === 'banks' && data.banks) {
    return [...banksCards(data.banks), sensitivityCard('WHAT MOVES THE NAMES · LAST 252 SESSIONS', data.banks.sensitivity,
      'Correlation and beta (% per 1bp) of each name\'s daily return beyond the S&P 500 with the daily change in the 2s10s curve, the 10-year yield and the high-yield spread. History, not a forecast.')].filter(Boolean);
  }
  if (key === 'consumer' && data.consumer) {
    return [...consumerCards(data.consumer), sensitivityCard('WHAT MOVES THE NAMES · LAST 252 SESSIONS', data.consumer.sensitivity,
      'Correlation and beta of each name\'s daily return beyond the S&P 500 with the daily change in the 10-year yield (per 1bp), RBOB gasoline futures (per 1%) and the high-yield spread (per 1bp). History, not a forecast.')].filter(Boolean);
  }
  return [];
}

function themeCards(key, data) {
  const failed = data.studies?.unavailable ? data.studies : null;
  return [...industry(key, data), studyCard(failed ? null : data.studies?.[key], failed)].filter(Boolean);
}

export default async function renderThemes(root, data, _manifest, ctx = {}) {
  root.append(sectionTitle('THEMES', 'WHAT IS COMING, BY WHAT TRADES TOGETHER'));
  if (!data.groups?.length) {
    root.append(gap('No themes in this build.'));
    return;
  }
  root.append(metaRow(`AS OF ${data.as_of} · ${data.groups.length} THEMES · NEXT ${data.calendar_days} DAYS`, [
    'A theme is a group of names that trades together, not a GICS sector. Each has a proxy (an ETF, or an equal-weight basket where no ETF isolates it), bellwethers, and the macro releases that bear on it.',
    'Bellwether reports: scheduled on the Nasdaq calendar, or projected from the company\'s own report rhythm (median gap between past reports) and marked so.',
    'Data dates: when each monthly series is due -- Taiwan revenue by the 10th, Korea\'s confirmed customs figures around the 15th; a series past due is marked late.',
  ]));
  const heat = heatmapCard(data.heatmap);
  if (heat) root.append(heat);
  const host = el('div', {});
  // The hash argument is upper-cased like a ticker (#themes/SEMIS).
  const wanted = String(ctx.arg || '').toLowerCase();
  let active = data.groups.some((g) => g.key === wanted) ? wanted : data.groups[0].key;
  const draw = () => {
    host.replaceChildren();
    const g = data.groups.find((x) => x.key === active);
    host.append(overviewStrip(data, active, (key) => { active = key; ctx.setArg?.(key); draw(); }));
    host.append(el('h2', { class: 'section-title' }, [g.label, el('span', { class: 'muted', text: ` proxy ${g.proxy}` })]));
    host.append(el('div', { class: 'grid two' }, [calendarCard(g, data.as_of, data.calendar_days), relativeCard(g)]));
    host.append(bellwetherCard(g));
    themeCards(g.key, data).forEach((node) => host.append(node));
  };
  root.append(host);
  draw();
}
