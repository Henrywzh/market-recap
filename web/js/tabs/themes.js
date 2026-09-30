// THEMES (under CATALYSTS): what is coming for each group of names that
// trades together, and the industry data behind CLOUD and SEMIS. Built by
// the THEMES panel; every figure carries its source and date, and a source
// that failed leaves its reason in its own card.

import { el, card, num, pct, tag, table, dirClass, sectionTitle, gap, metaRow, DASH } from '../fmt.js';
import { render, SERIES_COLORS } from '../charts.js';
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

function chartNode(cls = 'short') {
  return el('div', { class: `chart ${cls}` });
}

// Bars on the left axis, a percent line on the right.
function barLine(node, labels, bars, line, { barName, lineName, barFmt = (v) => num(v, 1), color } = {}) {
  requestAnimationFrame(() => render(node, (option, p) => ({
    ...option,
    grid: { left: 52, right: 48, top: 24, bottom: 26 },
    legend: { top: 0, textStyle: { color: p.dim, fontSize: 9 }, itemWidth: 10, itemHeight: 6 },
    tooltip: { ...option.tooltip, trigger: 'axis' },
    xAxis: { ...option.xAxis, boundaryGap: true, data: labels },
    yAxis: [
      { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 9, formatter: barFmt } },
      { ...option.yAxis, position: 'right', splitLine: { show: false }, axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => `${v}%` } },
    ],
    series: [
      { name: barName, type: 'bar', data: bars, barMaxWidth: 14, itemStyle: { color: color ? color(p) : p.blue } },
      ...(line ? [{ name: lineName, type: 'line', yAxisIndex: 1, data: line, showSymbol: false, lineStyle: { color: p.accent, width: 1.4 }, itemStyle: { color: p.accent } }] : []),
    ],
  })));
}

// Several lines on one date axis.
function lines(node, dates, series, { fmt = (v) => num(v, 0), right = null } = {}) {
  requestAnimationFrame(() => render(node, (option, p) => ({
    ...option,
    grid: { left: 52, right: 16, top: 26, bottom: 26 },
    legend: { top: 0, textStyle: { color: p.dim, fontSize: 9 }, itemWidth: 10, itemHeight: 2 },
    tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: (v) => (v === null || v === undefined ? DASH : fmt(v)) },
    xAxis: { ...option.xAxis, data: dates },
    yAxis: { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 9, formatter: fmt } },
    series: series.map((s, i) => ({
      name: s.name, type: 'line', data: s.values, showSymbol: false, connectNulls: true,
      lineStyle: { width: s.width || 1.3, color: s.color ? s.color(p) : SERIES_COLORS[i % SERIES_COLORS.length], type: s.dashed ? 'dashed' : 'solid' },
      itemStyle: { color: s.color ? s.color(p) : SERIES_COLORS[i % SERIES_COLORS.length] },
    })),
    ...(right || {}),
  })));
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
      ? [link(c.symbol), el('span', { class: 'dim', text: ` ${(c.timing || '').toUpperCase()}${c.projected ? ' · projected' : ''}${c.beta !== null && c.beta !== undefined ? ` · proxy β ${num(c.beta, 2)}` : ''}` })]
      : [el('span', { class: c.late ? 'down' : '', text: c.title }), c.time ? el('span', { class: 'dim', text: ` ${c.time} ET` }) : null, c.late ? el('span', { class: 'down', text: ' · late' }) : null]),
  ]));
  return card(`NEXT ${days} DAYS`, el('span', { class: 'dim', text: `from ${asOf}` }), table(['DATE', '', 'WHAT'], rows, { class: 'text-cols' }));
}

function bellwetherCard(g) {
  const rows = g.bellwethers.map((b) => {
    const s = b.impact || {};
    return el('tr', {}, [
      el('td', {}, [link(b.symbol)]),
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
  return card('BELLWETHERS · WHAT THEIR REPORTS DID TO THE THEME', null, [
    table(['NAME', 'NEXT REPORT', 'PROXY β', 'SAME WAY', 'AVG |PROXY|', 'AVG |OWN|', 'LAST: OWN → PROXY', 'N'], rows),
    el('div', { class: 'field-note', text: `${proxyNote} N = past reports scored (8-K Item 2.02; foreign filers have none). History, not a forecast.` }),
  ]);
}

function relativeCard(g) {
  const node = chartNode();
  lines(node, g.relative.dates, [{ name: `${g.proxy_is_etf ? g.proxy : 'basket'} / S&P 500`, values: g.relative.values, color: (p) => p.accent }], { fmt: (v) => num(v, 0) });
  return card('AGAINST THE S&P 500 · 1Y', el('span', { class: 'dim', text: '= 100 a year ago' }), node);
}

// --- CLOUD -------------------------------------------------------------------------

function capexCard(capex) {
  if (capex.unavailable) return card('HYPERSCALER CAPEX', null, unavailable(capex));
  const quarters = [...new Set(capex.companies.flatMap((c) => c.quarters.map((q) => q.quarter)))].sort().slice(-8);
  const node = chartNode('');
  const totals = new Map(capex.totals.map((t) => [t.quarter, t]));
  requestAnimationFrame(() => render(node, (option, p) => ({
    ...option,
    grid: { left: 52, right: 48, top: 26, bottom: 26 },
    legend: { top: 0, textStyle: { color: p.dim, fontSize: 9 }, itemWidth: 10, itemHeight: 6 },
    tooltip: { ...option.tooltip, trigger: 'axis' },
    xAxis: { ...option.xAxis, boundaryGap: true, data: quarters },
    yAxis: [
      { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => `$${v}B` } },
      { ...option.yAxis, position: 'right', splitLine: { show: false }, axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => `${v}%` } },
    ],
    series: [
      ...capex.companies.map((c, i) => ({
        name: c.symbol, type: 'bar', stack: 'capex', barMaxWidth: 26, itemStyle: { color: SERIES_COLORS[i % SERIES_COLORS.length] },
        data: quarters.map((q) => c.quarters.find((x) => x.quarter === q)?.capex_bn ?? null),
      })),
      { name: 'total y/y', type: 'line', yAxisIndex: 1, showSymbol: true, symbolSize: 4, lineStyle: { color: p.text, width: 1.2 }, itemStyle: { color: p.text },
        data: quarters.map((q) => totals.get(q)?.yoy_pct ?? null) },
    ],
  })));
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
    node,
    table(['NAME', 'QUARTER TO', 'CAPEX', 'Y/Y', '+ FINANCE LEASES', 'FILED'], rows),
    el('div', { class: 'field-note', text: 'Purchases of property and equipment from each filing\'s cash-flow statement (quarters derived from year-to-date figures where only those are filed). Finance leases: right-of-use assets taken on under new finance leases, not in capex. Oracle\'s quarters end Aug/Nov/Feb/May and count toward the calendar quarter they mostly cover; a total is shown only where all five have filed.' }),
  ]);
}

function twRevenueCard(title, series, note) {
  if (series.unavailable) return card(title, null, unavailable(series));
  const months = [...new Set(series.flatMap((s) => s.months.map((m) => m.month)))].sort().slice(-24);
  const node = chartNode('');
  lines(node, months, series.map((s) => ({ name: s.label, values: months.map((m) => s.months.find((x) => x.month === m)?.yoy_pct ?? null) })),
    { fmt: (v) => `${num(v, 0)}%` });
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
  return card(title, el('span', { class: 'dim', text: 'MOPS monthly revenue · y/y %' }), [
    node,
    table(['COMPANY', 'MONTH', 'REVENUE', 'Y/Y', 'YTD Y/Y', 'NEXT'], rows),
    el('div', { class: 'field-note', text: note }),
  ]);
}

function openrouterCard(or) {
  if (or.unavailable) return card('OPENROUTER · TOKENS & ESTIMATED REVENUE', null, unavailable(or));
  const dates = or.dates.slice(-120);
  const cut = or.dates.length - dates.length;
  const revNode = chartNode('');
  const tokNode = chartNode('');
  lines(revNode, dates, or.providers.map((p) => ({ name: p.name, values: rolling(p.revenue_k, 7).slice(cut) })), { fmt: (v) => `$${num(v, 0)}k` });
  lines(tokNode, dates, or.providers.map((p) => ({ name: p.name, values: rolling(p.tokens_b, 7).slice(cut) })), { fmt: (v) => `${num(v, 0)}B` });
  const rows = [...or.providers].sort((a, b) => b.week_revenue_k - a.week_revenue_k).map((p) => el('tr', {}, [
    el('td', { text: p.name }),
    el('td', { text: `$${num(p.week_revenue_k / 1000, 2)}M` }),
    el('td', { class: 'dim', text: p.revenue_share_pct === null ? DASH : `${num(p.revenue_share_pct, 1)}%` }),
    pctCell(p.revenue_vs_4w_pct),
    el('td', { text: `${num(p.week_tokens_b / 1000, 2)}T` }),
    pctCell(p.tokens_vs_4w_pct),
  ]));
  return card('OPENROUTER · TOKENS & ESTIMATED REVENUE BY MODEL AUTHOR', el('span', { class: 'dim', text: `through ${or.dates[or.dates.length - 1]}${or.commit ? ` · alternative-data ${or.commit.sha.slice(0, 7)}` : ''}` }), [
    el('div', { class: 'grid two' }, [
      el('div', {}, [el('div', { class: 'card-title', text: 'ESTIMATED REVENUE / DAY · 7D AVG' }), revNode]),
      el('div', {}, [el('div', { class: 'card-title', text: 'TOKENS / DAY · 7D AVG' }), tokNode]),
    ]),
    table(['AUTHOR', 'LAST 7D REVENUE', 'SHARE', 'VS PRIOR 4W', 'LAST 7D TOKENS', 'VS PRIOR 4W'], rows),
    el('div', { class: 'field-note', text: 'OpenRouter\'s routed traffic only -- a slice of each lab\'s demand, not its revenue. Revenue is alternative-data\'s estimate: observed tokens at the model\'s list price at the time. Today\'s partial day is left out.' }),
  ]);
}

function rampCard(ramp) {
  if (ramp.unavailable) return card('RAMP AI INDEX', null, unavailable(ramp));
  const n = ramp.months.length;
  const last = n - 1;
  const spendNode = chartNode('');
  const vendorNode = chartNode('');
  lines(spendNode, ramp.months, [
    { name: 'median $/employee/month', values: ramp.median_pepm, color: (p) => p.accent, width: 1.8 },
  ], { fmt: (v) => `$${num(v, 1)}` });
  const vendorMonths = [...new Set(Object.values(ramp.vendors).flatMap((v) => v.months))].sort();
  lines(vendorNode, vendorMonths, Object.entries(ramp.vendors).map(([name, v]) => ({ name, values: vendorMonths.map((m) => v.pct[v.months.indexOf(m)] ?? null) })),
    { fmt: (v) => `${num(v, 0)}%` });
  const adopt = ramp.adoption.pct[ramp.adoption.pct.length - 1];
  const sectorRows = ramp.sectors.rows.slice(0, 8).map((r) => el('tr', {}, [el('td', { text: r.sector }), el('td', { text: `$${num(r.median_pepm, 2)}` })]));
  return card('RAMP AI INDEX · US BUSINESSES', el('span', { class: 'dim', text: `through ${ramp.months[last]}` }), [
    el('div', { class: 'stat-strip' }, [
      stat('MEDIAN AI SPEND', `$${num(ramp.median_pepm[last], 2)}`, `per employee per month · ${n > 1 ? `${pct(100 * (ramp.median_pepm[last] / ramp.median_pepm[last - 1] - 1), 1)} m/m` : ''}`),
      stat('90TH PERCENTILE', `$${num(ramp.p90_pepm[last], 0)}`, 'per employee per month'),
      stat('TOP-10% MEDIAN', `$${num(ramp.top10_median_pepm[last], 0)}`, 'per employee per month'),
      stat('ADOPTION', `${num(adopt, 1)}%`, `of businesses paying for AI · ${ramp.adoption.months[ramp.adoption.months.length - 1]}`),
    ]),
    el('div', { class: 'grid two' }, [
      el('div', {}, [el('div', { class: 'card-title', text: 'MEDIAN SPEND PER EMPLOYEE' }), spendNode]),
      el('div', {}, [el('div', { class: 'card-title', text: 'ADOPTION BY VENDOR · % OF BUSINESSES' }), vendorNode]),
    ]),
    el('div', { class: 'card-title', text: `MEDIAN SPEND BY SECTOR · ${ramp.sectors.month}` }),
    table(['SECTOR', '$ / EMPLOYEE / MONTH'], sectorRows),
    el('div', { class: 'field-note', text: 'Ramp AI Index (ramp.com/data/ai-index): card and bill-pay spend of businesses on Ramp -- skewed to US small and mid-sized firms. Read from alternative-data\'s collection.' }),
  ]);
}

// --- SEMIS -------------------------------------------------------------------------

function koreaCard(k) {
  if (k.unavailable) return card('KOREA IC EXPORTS', null, unavailable(k));
  const months = k.months.slice(-24);
  const node = chartNode('');
  barLine(node, months.map((m) => m.month), months.map((m) => m.exports_bn), months.map((m) => m.yoy_pct),
    { barName: 'exports $B', lineName: 'y/y %', barFmt: (v) => `$${v}B` });
  const last = k.months[k.months.length - 1] || {};
  return card('KOREA IC EXPORTS · HS 8542', el('span', { class: 'tag-row' }, [
    tag(`${last.month} $${num(last.exports_bn, 1)}B · ${pct(last.yoy_pct, 0)} Y/Y`, last.yoy_pct > 0 ? 'up' : 'down'),
    el('span', { class: k.due?.late ? 'down' : 'dim', text: k.due ? `${k.due.month} due ~${k.due.due}` : '' }),
  ]), [
    node,
    el('div', { class: 'field-note', text: 'Korea Customs Service, confirmed monthly exports of electronic integrated circuits (memory is most of it), customs-acceptance basis, USD. The ministry\'s 1st-of-month flash is earlier but not read here.' }),
  ]);
}

function pcppCard(pc) {
  if (pc.unavailable) return card('RETAIL PRICES · PCPARTPICKER UK', null, unavailable(pc));
  const blocks = [];
  for (const kind of ['memory', 'cpu']) {
    const sec = pc[kind];
    if (!sec) continue;
    const fams = Object.entries(sec.families);
    const node = chartNode('');
    const dates = fams[0]?.[1].index.dates || [];
    lines(node, dates, fams.map(([name, f]) => ({ name, values: f.index.values, width: 1.8 })), { fmt: (v) => num(v, 0) });
    const famRows = fams.map(([name, f]) => el('tr', {}, [el('td', { text: `${name} (median of ${f.count})` }), pctCell(f.chg_1m), pctCell(f.chg_3m), pctCell(f.chg_6m), pctCell(f.chg_12m)]));
    const rows = sec.rows.map((r) => el('tr', {}, [el('td', { class: 'dim', text: r.title }), pctCell(r.chg_1m), pctCell(r.chg_3m), pctCell(r.chg_6m), pctCell(r.chg_12m)]));
    blocks.push(el('div', {}, [
      el('div', { class: 'card-title', text: kind === 'memory' ? 'MEMORY KITS · INDEX, 18 MONTHS AGO = 100' : 'CPUS · INDEX, 18 MONTHS AGO = 100' }),
      node,
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
    return [capexCard(c.capex),
      twRevenueCard('AI SERVER MAKERS · MONTHLY REVENUE', c.odm, 'Quanta, Wiwynn and Wistron build most hyperscaler AI servers; their revenue is capex being delivered, reported by the 10th of the next month. Foxconn is left out: iPhone assembly dominates it.'),
      openrouterCard(c.openrouter), rampCard(c.ramp)];
  }
  if (key === 'semis') {
    const s = data.semis;
    return [el('div', { class: 'grid two' }, [
      twRevenueCard('TSMC & NANYA · MONTHLY REVENUE', s.tw, 'TSMC: leading-edge foundry demand. Nanya: commodity DRAM, the purest listed read on DRAM pricing. Published by the 10th of the next month.'),
      koreaCard(s.korea)]),
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
