// THEMES (under CATALYSTS): what is coming for each group of names that
// trades together, and the industry data behind CLOUD and SEMIS. Built by
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
  if (pc.unavailable) return card('RETAIL PRICES · PCPARTPICKER UK', null, unavailable(pc));
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
  return [];
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
    industry(g.key, data).forEach((node) => host.append(node));
  };
  root.append(host);
  draw();
}
