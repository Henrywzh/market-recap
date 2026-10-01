// Earnings event cards and the per-name timeline, shared by TICKER and
// CATALYSTS. Everything drawn here is baked by the EVENTS panel: the card
// lists what a report is priced for and who has moved with it; it scores
// nothing and forecasts nothing.

import { el, card, num, pct, tag, table, dirClass, periodSwitch, DASH } from './fmt.js';
import { render } from './charts.js';
import { tickerHref } from './routes.js';
import { availableRanges, sliceRange } from './range.js';

const TIMING = { bmo: 'BEFORE OPEN', amc: 'AFTER CLOSE', intraday: 'DURING SESSION' };
// A timeline reads events, not a decade of price: the longer ranges stay on
// the price chart above it.
const TIMELINE_RANGES = ['6M', '1Y', '3Y'];

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function billions(value) {
  if (value === null || value === undefined) return DASH;
  return value >= 1e9 ? `$${num(value / 1e9, 2)}B` : `$${num(value / 1e6, 0)}M`;
}

function sessionsBetween(from, to) {
  let n = 0;
  const day = new Date(`${from}T00:00:00Z`);
  const end = new Date(`${to}T00:00:00Z`);
  while (day < end) {
    day.setUTCDate(day.getUTCDate() + 1);
    if (day.getUTCDay() % 6 !== 0) n += 1;
  }
  return n;
}

function whenTag(c, asOf) {
  const n = sessionsBetween(asOf, c.date);
  const text = n <= 1 ? 'NEXT SESSION' : `IN ${n} SESSIONS`;
  return tag(`${text} · ${(c.timing || 'time n/a').toUpperCase()}`, n <= 1 ? 'warn' : 'info',
    TIMING[c.timing] || 'timing not on the calendar');
}

function link(symbol) {
  return el('a', { href: tickerHref(symbol), text: symbol });
}

// Implied against the name's own history: a straddle wider than the average
// past move is the market paying up for this report.
function pricedTag(priced) {
  const implied = priced.implied?.straddle_pct;
  if (!implied || !priced.mean_abs) return null;
  const ratio = implied / priced.mean_abs;
  if (ratio > 1.2) return tag(`PRICED ${num(ratio, 1)}× ITS AVG`, 'warn', 'implied move above the average of its last reports');
  if (ratio < 0.8) return tag(`PRICED ${num(ratio, 1)}× ITS AVG`, 'info', 'implied move below the average of its last reports');
  return tag('PRICED NEAR ITS AVG', 'dim');
}

function consensusStats(c) {
  const k = c.consensus || {};
  const eps = k.eps ?? k.eps_yahoo;
  const range = k.eps_low !== undefined && k.eps_low !== null ? `range ${num(k.eps_low)}–${num(k.eps_high)}` : null;
  const revisions = k.eps_change_30d_pct !== undefined && k.eps_change_30d_pct !== null
    ? `30d ${pct(k.eps_change_30d_pct, 1)} (${k.up_30d ?? DASH}↑ ${k.down_30d ?? DASH}↓)` : null;
  const growth = k.eps_growth_pct !== null && k.eps_growth_pct !== undefined ? `${pct(k.eps_growth_pct, 0)} y/y` : null;
  return [
    stat(`EPS CONSENSUS${k.fiscal_quarter ? ` · ${k.fiscal_quarter}` : ''}`, eps === null || eps === undefined ? DASH : num(eps),
      [growth, range, revisions].filter(Boolean).join(' · ') || `${k.eps_estimates ?? DASH} estimates`),
    stat('REVENUE CONSENSUS', billions(k.revenue),
      k.revenue ? [k.revenue_growth_pct !== null && k.revenue_growth_pct !== undefined ? `${pct(k.revenue_growth_pct, 0)} y/y` : null,
        k.revenue_low ? `range ${billions(k.revenue_low)}–${billions(k.revenue_high)}` : null].filter(Boolean).join(' · ')
        : 'Yahoo row is not this quarter, or none'),
  ];
}

function pricedStats(c) {
  const p = c.priced || {};
  const implied = p.implied;
  const impact = c.impact || {};
  const indices = Object.entries(impact.indices || {}).sort((a, b) => b[1].points_pct - a[1].points_pct);
  return [
    stat('IMPLIED MOVE', implied ? `±${num(implied.straddle_pct, 1)}%` : DASH,
      implied ? `straddle to ${implied.expiry} · ${implied.snapshot_day} snapshot` : 'no straddle expiring within a week of the report in the snapshot'),
    stat(`AVG |MOVE| · LAST ${p.reports || 0}`, p.mean_abs ? `±${num(p.mean_abs, 1)}%` : DASH,
      p.reports ? `median ±${num(p.median_abs, 1)}% · up ${p.up} of ${p.reports}${p.beat_implied !== null && p.beat_implied !== undefined ? ` · ${p.beat_implied} beat today's implied` : ''}` : 'no 8-K releases on file'),
    stat('INDEX IMPACT', indices.length ? indices.map(([k, v]) => `${k} ±${num(v.points_pct, 2)}%`).join(' ') : DASH,
      indices.length ? `weight × ${impact.basis} move ±${num(impact.move_pct, 1)}% · ${indices.map(([k, v]) => `${k} ${num(v.weight, 2)}%`).join(', ')}` : 'not an index member'),
  ];
}

// Where the street sits against the range the company itself gave for this
// quarter at its last report: above the top of it is a high bar.
function guideStats(c) {
  const g = c.vs_guide;
  if (!g) return [];
  const fmt = (key, v) => (key === 'revenue' ? billions(v) : num(v));
  return Object.entries(g).map(([key, x]) => stat(`${key === 'eps' ? 'EPS' : 'REVENUE'} VS OWN GUIDE`,
    `${x.vs_mid_pct > 0 ? '+' : ''}${num(x.vs_mid_pct, 1)}%`,
    `consensus ${fmt(key, x.consensus)} vs guide ${fmt(key, x.low)}–${fmt(key, x.high)} · ${x.position} the range`,
    x.position === 'above' ? 'warn' : x.position === 'below' ? 'up' : ''));
}

function guideTag(c) {
  const above = Object.entries(c.vs_guide || {}).filter(([, x]) => x.position === 'above').map(([k]) => (k === 'eps' ? 'EPS' : 'REV'));
  return above.length ? tag(`STREET ABOVE GUIDE · ${above.join(' + ')}`, 'warn', 'consensus above the top of the range the company gave last quarter') : null;
}

function setupStats(c) {
  const s = c.setup || {};
  return [
    stat('GOING IN · 20D', pct(s.ret_20d, 1),
      [s.vs_sector_20d !== null && s.vs_sector_20d !== undefined ? `${s.vs_sector_20d > 0 ? '+' : ''}${num(s.vs_sector_20d, 1)} pp vs ${s.sector_etf}` : null,
        s.ret_5d !== null && s.ret_5d !== undefined ? `5d ${pct(s.ret_5d, 1)}` : null].filter(Boolean).join(' · '), dirClass(s.ret_20d)),
    stat('FROM 1Y HIGH', pct(s.from_high_pct, 1), s.above_50d === null || s.above_50d === undefined ? null : (s.above_50d ? 'above its 50-day average' : 'below its 50-day average'),
      dirClass(s.from_high_pct)),
  ];
}

function betaCell(beta) {
  return el('td', { class: beta >= 0.5 ? 'up' : beta <= 0 ? 'down' : '', text: num(beta, 2) });
}

function hitCell(hit) {
  return el('td', { class: hit === null || hit === undefined ? 'dim' : hit >= 0.75 ? 'up' : hit < 0.5 ? 'down' : '', text: hit === null || hit === undefined ? DASH : `${Math.round(hit * 100)}%` });
}

function withTable(rt, limit) {
  const rows = (rt.with || []).slice(0, limit).map((r) => el('tr', {}, [
    el('td', {}, [link(r.symbol)]),
    el('td', { class: 'dim', text: num(r.corr, 2) }),
    betaCell(r.beta),
    hitCell(r.hit),
    el('td', { class: 'dim', text: `±${num(r.mean_abs, 1)}%` }),
    el('td', { class: 'dim', text: String(r.n) }),
  ]));
  if (rt.sector_etf) {
    const s = rt.sector_etf;
    rows.push(el('tr', { class: 'dim' }, [el('td', { text: s.symbol }), el('td', { text: 'sector' }), betaCell(s.beta), hitCell(s.hit),
      el('td', { text: `±${num(s.mean_abs, 1)}%` }), el('td', { text: String(s.n) })]));
  }
  return rows.length ? table(['PEER', 'CORR', 'BETA', 'SAME WAY', 'AVG |MOVE|', 'N'], rows)
    : el('div', { class: 'dim', text: `Too few past reports to measure (${rt.reports || 0}).` });
}

function intoTable(rt, limit, asOf) {
  const rows = (rt.into || []).slice(0, limit).map((r) => el('tr', {}, [
    el('td', {}, [link(r.symbol)]),
    el('td', { class: r.next ? '' : 'dim', text: r.next ? `${r.next} ${(r.timing || '').toUpperCase()}` : 'not in 30 days' }),
    betaCell(r.beta),
    hitCell(r.hit),
    el('td', { class: 'dim', text: String(r.n) }),
  ]));
  return rows.length ? table(['REPORTER', 'NEXT REPORT', 'BETA', 'SAME WAY', 'N'], rows)
    : el('div', { class: 'dim', text: 'No correlated name with enough past reports.' });
}

// The full card on TICKER; `compact` is the CATALYSTS lead strip's version.
export function eventCard(payload, asOf, { compact = false } = {}) {
  const c = payload.card;
  if (!c) return null;
  const title = compact ? `${payload.symbol} · ${(payload.name || '').toUpperCase()}` : 'NEXT REPORT · EVENT CARD';
  const right = el('span', { class: 'tag-row' }, [whenTag(c, asOf), pricedTag(c.priced), guideTag(c),
    el('span', { class: 'dim', text: `${c.date} · reacts ${c.reaction_session || DASH}` })]);
  const rt = payload.readthrough || {};
  const body = [
    el('div', { class: 'stat-strip event-stats' }, [...consensusStats(c), ...pricedStats(c), ...(compact ? [] : setupStats(c))]),
  ];
  const bar = compact ? [] : guideStats(c);
  if (bar.length) body.push(el('div', { class: 'stat-strip event-stats' }, bar));
  if (compact) {
    const peers = (rt.with || []).slice(0, 4);
    body.push(el('div', { class: 'tag-row event-peers' }, [
      el('span', { class: 'dim', text: 'MOVES WITH IT ' }),
      ...(peers.length ? peers.map((r) => el('a', { href: tickerHref(r.symbol), class: `tag tag-${r.beta >= 0.5 ? 'up' : 'dim'}`, text: `${r.symbol} β${num(r.beta, 1)}`,
        title: `beta ${num(r.beta, 2)} · same way ${Math.round((r.hit || 0) * 100)}% of ${r.n} reports` })) : [el('span', { class: 'dim', text: DASH })]),
      el('a', { href: tickerHref(payload.symbol), class: 'event-open', text: 'OPEN CARD →' }),
    ]));
    return el('div', { class: 'card event-card compact' }, [
      el('div', { class: 'card-head' }, [el('a', { class: 'card-title', href: tickerHref(payload.symbol), text: title }), right]),
      ...body,
    ]);
  }
  body.push(el('div', { class: 'grid two' }, [
    el('div', {}, [el('div', { class: 'card-title', text: `WHO MOVES WITH IT · ON ITS LAST ${rt.reports || 0} REPORTS` }), withTable(rt, 5)]),
    el('div', {}, [el('div', { class: 'card-title', text: 'REPORTS THAT MOVE IT' }), intoTable(rt, 5, asOf)]),
  ]));
  body.push(el('div', { class: 'field-note', text:
    'Peers: the 12 names whose daily moves beyond the S&P 500 tracked this one most closely over the last year, then scored on report days only. '
    + 'BETA = the peer\'s excess move per 1% excess move of the reporter; SAME WAY = share of those sessions both went the same direction. '
    + 'History, not a forecast; N is small. Index impact = index weight × the implied move (the straddle to the first expiry after the report, so it covers more than the report).' }));
  return card(title, right, body);
}

// A report the last session traded on: what it printed, and how it and its
// peers moved against what was priced.
export function outcomeCard(payload, { compact = false } = {}) {
  const o = payload.outcome;
  if (!o) return null;
  const surprise = o.surprise_pct;
  const ratio = o.vs_implied;
  const right = el('span', { class: 'tag-row' }, [
    surprise === null || surprise === undefined ? null : tag(`EPS ${surprise >= 0 ? 'BEAT' : 'MISS'} ${pct(surprise, 1)}`, surprise >= 0 ? 'up' : 'down'),
    ratio ? tag(ratio > 1 ? `MOVED ${num(ratio, 1)}× IMPLIED` : `INSIDE IMPLIED (${num(ratio, 1)}×)`, ratio > 1 ? 'warn' : 'dim') : null,
    el('span', { class: 'dim', text: `reported ${o.date} ${(o.timing || '').toUpperCase()} · traded ${o.session}` }),
  ]);
  const stats = el('div', { class: 'stat-strip event-stats' }, [
    stat('EPS', o.eps === null || o.eps === undefined ? DASH : num(o.eps), o.eps_forecast !== null && o.eps_forecast !== undefined ? `vs ${num(o.eps_forecast)} consensus` : null,
      dirClass(surprise)),
    stat('REACTION', pct(o.move_pct, 1), o.excess_pct !== null && o.excess_pct !== undefined ? `${pct(o.excess_pct, 1)} vs S&P 500` : null, dirClass(o.move_pct)),
    stat('IMPLIED BEFORE', o.implied ? `±${num(o.implied.straddle_pct, 1)}%` : DASH, o.implied ? `${o.implied.snapshot_day} snapshot` : 'no snapshot the day before'),
  ]);
  const peerRows = (o.peers || []).map((r) => el('tr', {}, [
    el('td', {}, [link(r.symbol)]),
    el('td', { class: 'dim', text: num(r.beta, 2) }),
    el('td', { class: dirClass(r.expected_pct), text: pct(r.expected_pct, 1) }),
    el('td', { class: dirClass(r.excess_pct), text: pct(r.excess_pct, 1) }),
  ]));
  const peers = peerRows.length ? table(['PEER', 'BETA', 'HISTORY SAYS', 'ACTUAL (VS S&P)'], peerRows) : null;
  if (compact) {
    return el('div', { class: 'card event-card compact' }, [
      el('div', { class: 'card-head' }, [el('a', { class: 'card-title', href: tickerHref(payload.symbol), text: `${payload.symbol} · ${(payload.name || '').toUpperCase()}` }), right]),
      stats, peers,
    ]);
  }
  return card('LAST REPORT · OUTCOME', right, [stats, peers ? el('div', { class: 'card-title', text: 'READ-THROUGH ON THE SESSION' }) : null, peers]);
}

// --- Report history, revisions, the industry since the last report, filings ---

function signed(v, digits = 1, unit = '%') {
  return v === null || v === undefined ? DASH : `${v > 0 ? '+' : ''}${num(v, digits)}${unit}`;
}

function guideText(g) {
  if (!g) return DASH;
  const parts = [];
  if (g.revenue_low !== undefined) {
    parts.push(`rev ${g.revenue_low === g.revenue_high ? billions(g.revenue_low) : `${billions(g.revenue_low)}–${billions(g.revenue_high)}`}${g.revenue_horizon === 'year' ? ' FY' : ''}`);
  } else if (g.revenue_growth_low !== undefined) {
    parts.push(`rev +${num(g.revenue_growth_low, 0)}–${num(g.revenue_growth_high, 0)}%`);
  }
  if (g.eps_low !== undefined) parts.push(`EPS ${num(g.eps_low)}–${num(g.eps_high)}${g.eps_horizon === 'year' ? ' FY' : ''}`);
  if (g.gross_margin_pct !== undefined && g.gross_margin_pct !== null) parts.push(`GM ${num(g.gross_margin_pct, 1)}%`);
  return parts.join(' · ') || DASH;
}

function historyLine(sum) {
  if (!sum || !sum.reports) return null;
  const parts = [];
  if (sum.measured) parts.push(`beat EPS consensus ${sum.beats} of ${sum.measured} (median surprise ${signed(sum.median_surprise_pct)})`);
  if (sum.beat_and_fell) parts.push(`fell on ${sum.beat_and_fell} of those beats`);
  parts.push(`up vs the S&P on ${sum.up} of ${sum.reports}`);
  if (sum.drift_measured) parts.push(`the first day's direction held 20 sessions on ${sum.held_20d} of ${sum.drift_measured}`);
  if (sum.guides_checked) parts.push(`beat its own EPS guide midpoint ${sum.beat_own_guide} of ${sum.guides_checked}`);
  return parts.join(' · ');
}

// The last reports: what each was measured against, the guide it gave, how
// the stock answered and whether that lasted.
export function historyCard(payload) {
  const rows = payload.history || [];
  if (!rows.length) return null;
  const body = rows.map((r) => {
    const guideLink = r.guide?.url ? el('a', { href: r.guide.url, target: '_blank', rel: 'noopener', text: guideText(r.guide), title: r.guide.quote || '' }) : null;
    return el('tr', {}, [
      el('td', { text: `${r.date} ${(r.timing || '').toUpperCase()}` }),
      el('td', { class: 'dim', text: r.fiscal_quarter || DASH }),
      el('td', { text: r.eps === null || r.eps === undefined ? DASH : `${num(r.eps_consensus)} → ${num(r.eps)}` }),
      el('td', { class: dirClass(r.surprise_pct), text: signed(r.surprise_pct) }),
      el('td', { class: guideLink ? '' : 'dim' }, [guideLink || (r.guide ? guideText(r.guide) : DASH)]),
      el('td', { class: dirClass(r.next_eps_vs_guide_pct), text: signed(r.next_eps_vs_guide_pct), title: 'the next quarter\'s EPS against this guide\'s midpoint' }),
      el('td', { class: dirClass(r.move_pct), text: `${pct(r.move_pct, 1)}${r.excess_pct !== null && r.excess_pct !== undefined ? ` (${signed(r.excess_pct)})` : ''}` }),
      el('td', { class: dirClass(r.drift_5d), text: signed(r.drift_5d) }),
      el('td', { class: dirClass(r.drift_20d), text: signed(r.drift_20d) }),
    ]);
  });
  const line = historyLine(payload.history_summary);
  return card(`LAST ${rows.length} REPORTS`, el('span', { class: 'dim', text: 'EPS vs consensus · the guide each gave · the move and what followed' }), [
    line ? el('div', { class: 'event-history-line', text: line }) : null,
    table(['REPORTED', 'QUARTER', 'EPS EST → ACT', 'SURPRISE', 'GUIDE GIVEN', 'NEXT VS GUIDE', 'DAY 1 (VS S&P)', '+5D VS S&P', '+20D VS S&P'], body),
    el('div', { class: 'field-note', text:
      'EPS and consensus: Nasdaq\'s calendar on the report day (adjusted EPS). Guide: the figures the earnings release (8-K, EX-99) states for the next period -- '
      + 'the last figure in a GAAP / non-GAAP row, checked against the company\'s last quarter (a figure far from its scale is dropped; FY marks a full-year guide). '
      + 'Companies that guide only on the call show none. +5D / +20D: excess return over the S&P 500 from the first session\'s close. Hover a guide for the release\'s wording.' }),
  ]);
}

// Consensus now against 7/30/60/90 days ago, per fiscal period.
export function revisionsCard(payload) {
  const rows = payload.revisions || [];
  if (!rows.length) return null;
  const body = rows.map((r) => el('tr', {}, [
    el('td', { text: r.label }),
    el('td', { class: 'dim', text: r.end || DASH }),
    el('td', { text: num(r.eps) }),
    ...['7d', '30d', '60d', '90d'].map((w) => el('td', { class: dirClass(r.changes[w]), text: signed(r.changes[w]) })),
    el('td', { class: 'dim', text: r.up_30d === null && r.down_30d === null ? DASH : `${r.up_30d ?? 0}↑ ${r.down_30d ?? 0}↓` }),
    el('td', { class: 'dim', text: r.spread_pct === null ? DASH : `${num(r.spread_pct, 0)}%`, title: '(high − low estimate) / consensus' }),
  ]));
  return card('ESTIMATE REVISIONS', el('span', { class: 'dim', text: 'consensus EPS now vs days ago · Yahoo' }), [
    table(['PERIOD', 'ENDS', 'EPS', '7D', '30D', '60D', '90D', 'REVISIONS 30D', 'SPREAD'], body),
  ]);
}

function driverValue(unit, v) {
  if (v === null || v === undefined) return DASH;
  if (unit === 'pct') return signed(v, 1);
  if (unit === 'usd') return `$${num(v, 2)}`;
  if (unit === 'bn') return `${num(v / 1000, 1)}T`;
  if (unit === 'rate') return `${num(v, 2)}%`;
  if (unit === 'count') return `${num(v / 1000, 0)}k`;
  return num(v, 1);
}

// The industry series of the name's themes: where each stood when the
// company last reported, where it is now.
export function sinceCard(payload) {
  const rows = payload.since || [];
  if (!rows.length) return null;
  const last = (payload.history || [])[0]?.date;
  // Periods on hover: a half-width card has no room for them in the cells.
  const body = rows.map((r) => el('tr', {}, [
    el('td', { text: r.label }),
    el('td', { class: 'dim', text: driverValue(r.unit, r.then.value), title: `${r.then.period}, public ${r.then.available}` }),
    el('td', { text: driverValue(r.unit, r.now.value), title: `${r.now.period}, public ${r.now.available}` }),
    el('td', { class: dirClass(r.change_pct ?? r.change_pp), text: r.change_pct !== undefined ? signed(r.change_pct)
      : r.unit === 'rate' ? signed(Math.round(r.change_pp * 100), 0, 'bp') : signed(r.change_pp, 1, 'pp') }),
    el('td', { class: 'dim', text: String(r.releases) }),
  ]));
  return card(`SINCE THE LAST REPORT${last ? ` · ${last}` : ''}`, el('span', { class: 'dim', text: 'the industry data of its themes' }), [
    table(['SERIES', 'THEN', 'NOW', 'CHANGE', 'NEW'], body),
    el('div', { class: 'field-note', text: 'THEN: each series as it was public on the report day (a month\'s figure dates from its publisher\'s release). NOW: its latest. NEW: releases since. y/y series change in pp, rates and spreads in bp, levels in %. Hover a value for its period; series and sources are on THEMES.' }),
  ]);
}

export function filingsCard(payload) {
  const rows = payload.filings || [];
  if (!rows.length) return null;
  return card('OTHER 8-K FILINGS', el('span', { class: 'dim', text: 'last 120 days · earnings releases left out' }), [
    table(['FILED', 'WHAT'], rows.map((f) => el('tr', {}, [
      el('td', { text: f.date }),
      el('td', {}, [el('a', { href: f.url, target: '_blank', rel: 'noopener', text: f.labels.join(' · ') }), el('span', { class: 'dim', text: ` item ${f.items.join(', ')}` })]),
    ]))),
  ]);
}

function addDays(iso, days) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

// Future items for the list and the chart: the next report and its estimated
// buyback blackout, correlated names' reports, and the macro dates.
function futureItems(payload, macro, asOf, days) {
  const end = addDays(asOf, days);
  const items = [];
  const c = payload.card;
  if (c) items.push({ date: c.date, kind: 'report', label: `${payload.symbol} REPORTS ${(c.timing || '').toUpperCase()}`, tone: 'warn' });
  (payload.readthrough?.into || []).filter((r) => r.next && r.next <= end).forEach((r) => items.push({
    date: r.next, kind: 'peer', symbol: r.symbol,
    label: `${r.symbol} reports ${(r.timing || '').toUpperCase()} · moved ${payload.symbol} β${num(r.beta, 2)}, same way ${Math.round((r.hit || 0) * 100)}% of ${r.n}`,
    tone: r.beta >= 0.3 ? 'info' : 'dim',
  }));
  (macro || []).filter((m) => m.date > asOf && m.date <= end).forEach((m) => items.push({
    date: m.date, kind: 'macro', label: `${m.title}${m.time ? ` ${m.time} ET` : ''}`, tone: 'dim',
  }));
  return items.sort((a, b) => a.date.localeCompare(b.date));
}

function pastLabel(item) {
  if (item.kind === 'earnings') {
    return `Report ${item.report} ${(item.timing || '').toUpperCase()}: ${pct(item.move_pct, 1)} (${pct(item.excess_pct, 1)} vs S&P)${item.implied_pct ? ` · implied ±${num(item.implied_pct, 1)}%` : ''}`;
  }
  if (item.kind === 'rating') {
    const target = item.target ? ` · target ${item.prior_target ? `${num(item.prior_target, 0)} → ` : ''}${num(item.target, 0)}` : '';
    const what = item.action === 'up' ? `upgrade to ${item.to}` : item.action === 'down' ? `downgrade to ${item.to}` : item.action === 'init' ? `initiates ${item.to}` : item.to;
    return `${item.firm}: ${what}${target}`;
  }
  if (item.kind === 'insider_buy') return `Insider buy: ${item.owner} $${num((item.value || 0) / 1e6, 1)}m`;
  return item.kind;
}

// Price with the name's own dated events on it, and the next 45 days beyond
// the last close: report, estimated blackout, peers' reports, macro dates.
export function timelineCard(payload, prices, macro, asOf, { daysAhead = 45 } = {}) {
  if (!prices?.dates?.length) return null;
  const node = el('div', { class: 'chart event-timeline' });
  const future = futureItems(payload, macro, asOf, daysAhead);
  const past = payload.timeline || [];
  const ranges = availableRanges(prices.dates).filter((r) => TIMELINE_RANGES.includes(r));
  let active = ranges.includes('6M') ? '6M' : ranges[ranges.length - 1] || 'MAX';
  const draw = () => {
    const { dates, values } = sliceRange(prices.dates, { values: prices.close }, active);
    const byDate = new Map(dates.map((d, i) => [d, values[i]]));
    const start = dates[0];
    const at = (d) => {
      if (byDate.has(d)) return byDate.get(d);
      const k = dates.findIndex((x) => x >= d);
      return k >= 0 ? values[k] : values[values.length - 1];
    };
    const shown = past.filter((i) => i.date >= start);
    const end = addDays(asOf, daysAhead);
    const c = payload.card;
    render(node, (option, p) => {
      const kindStyle = {
        earnings: (i) => ({ symbol: 'circle', symbolSize: 11, color: i.move_pct >= 0 ? p.up : p.down }),
        rating: (i) => ({ symbol: 'triangle', symbolRotate: i.tone === 'down' ? 180 : 0, symbolSize: 7, color: i.tone === 'up' ? p.up : i.tone === 'down' ? p.down : p.dim }),
        insider_buy: () => ({ symbol: 'diamond', symbolSize: 9, color: p.blue }),
      };
      const markers = shown.map((i) => {
        const style = kindStyle[i.kind]?.(i) || { symbol: 'circle', symbolSize: 6, color: p.dim };
        return {
          value: [i.date, at(i.date)], item: i, symbol: style.symbol, symbolSize: style.symbolSize, symbolRotate: style.symbolRotate || 0,
          itemStyle: { color: style.color, borderColor: p.panel, borderWidth: 1 },
          label: i.kind === 'earnings' ? { show: true, position: 'top', color: style.color, fontSize: 9, formatter: pct(i.move_pct, 0) } : { show: false },
        };
      });
      // Only the report and the peers that matter carry a label; the macro
      // dates are faint rules, named in the tooltip and the list below.
      const lines = future.filter((f) => f.kind !== 'peer' || f.tone === 'info').map((f) => ({
        xAxis: f.date,
        lineStyle: { color: f.kind === 'report' ? p.accent : f.kind === 'peer' ? p.blue : p.faint, type: f.kind === 'report' ? 'solid' : 'dashed', width: f.kind === 'report' ? 1.5 : 1, opacity: f.kind === 'macro' ? 0.6 : 1 },
        label: { show: f.kind !== 'macro', formatter: f.kind === 'report' ? 'EARN' : f.symbol, color: f.kind === 'report' ? p.accent : p.blue, fontSize: 9, position: 'end', rotate: 0 },
      }));
      const areas = [];
      if (c) {
        areas.push([{ xAxis: addDays(c.date, -30), itemStyle: { color: p.accent, opacity: 0.07 }, label: { show: true, formatter: 'BLACKOUT (EST.)', color: p.dim, fontSize: 9, position: 'insideBottomLeft' } },
          { xAxis: addDays(c.date, 2) }]);
      }
      areas.push([{ xAxis: asOf, itemStyle: { color: p.faint, opacity: 0.06 } }, { xAxis: end }]);
      return {
        ...option,
        grid: { left: 56, right: 24, top: 26, bottom: 28 },
        tooltip: {
          ...option.tooltip,
          trigger: 'item',
          formatter: (q) => {
            if (q.seriesIndex === 1 && q.data?.item) return `<b>${q.data.item.date}</b><br>${pastLabel(q.data.item)}`;
            if (q.componentType === 'markLine') {
              const f = future.find((x) => x.date === q.data.xAxis);
              return f ? `<b>${f.date}</b><br>${future.filter((x) => x.date === f.date).map((x) => x.label).join('<br>')}` : '';
            }
            return q.value ? `<b>${q.value[0]}</b> close $${num(q.value[1])}` : '';
          },
        },
        xAxis: { ...option.xAxis, type: 'time', boundaryGap: false, data: undefined, min: start, max: end },
        yAxis: { ...option.yAxis },
        series: [
          { type: 'line', name: 'close', data: dates.map((d, i) => [d, values[i]]), showSymbol: false, lineStyle: { color: p.text, width: 1.2 }, itemStyle: { color: p.text },
            markLine: { silent: false, symbol: 'none', data: lines }, markArea: { silent: true, data: areas } },
          { type: 'scatter', name: 'events', data: markers, z: 5 },
        ],
      };
    });
  };
  const head = el('div', { class: 'chart-head' }, [
    el('span', { class: 'tag-row' }, [tag('● REPORT', 'dim'), tag('▲▼ RATING', 'dim'), tag('◆ INSIDER BUY', 'info'), tag('| PEER / MACRO AHEAD', 'dim')]),
    ranges.length > 1 ? Object.assign(periodSwitch(ranges, active, (r) => { active = r; draw(); }), { className: 'period-switch range-switch' }) : null,
  ]);
  requestAnimationFrame(draw);
  const list = future.length ? table(['DATE', 'AHEAD'], future.map((f) => el('tr', {}, [
    el('td', { text: f.date }),
    el('td', {}, [f.kind === 'peer' ? el('span', {}, [link(f.symbol), ` ${f.label.slice(f.symbol.length)}`]) : el('span', { class: f.kind === 'report' ? 'accent-text' : 'dim', text: f.label })]),
  ]))) : null;
  return card('TIMELINE', el('span', { class: 'dim', text: `past events on the price · next ${daysAhead} days shaded` }), [
    head, node,
    list ? el('div', { class: 'card-title', text: `NEXT ${daysAhead} DAYS` }) : null, list,
    el('div', { class: 'field-note', text: 'Blackout: an estimated buyback quiet period from 30 days before to 2 days after the report -- a common convention, not this company\'s policy. Peers ahead are the correlated names whose reports have moved this one (REPORTS THAT MOVE IT). Ratings and insider buys cover the names EVIDENCE tracks in depth.' }),
  ]);
}

export async function loadEvents(symbol) {
  try {
    const response = await fetch(`artifacts/events/${encodeURIComponent(symbol)}.json`, { cache: 'no-cache' });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

