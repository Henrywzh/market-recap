// Earnings event cards and the per-name timeline, shared by TICKER and
// CATALYSTS. Everything drawn here is baked by the EVENTS panel: the card
// lists what a report is priced for and who has moved with it; it scores
// nothing and forecasts nothing.

import { el, card, num, pct, tag, table, dirClass, periodSwitch, DASH } from './fmt.js';
import { render } from './charts.js';
import { tickerHref } from './routes.js';
import { availableRanges, sliceRange } from './range.js';
import { rangeGeometry, rangeBarNode, splitBarNode, trailLevels, trailSummary, trailNode, reactionNode, surpriseRows, surpriseNode, figure, sectorHue, priceGeometry, priceNode, scorecardScale, scorecardNode, moveBandNode } from './event-visuals.js';

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

// A block of the strip that carries a drawing under its figure.
function visual(label, value, note, drawing, { cls = '', tail = null } = {}) {
  return el('div', { class: 'stat ec-vis' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: 'ec-vis-value' }, [el('span', { class: `stat-value ${cls}`, text: value }), tail]),
    drawing,
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function yoy(value) {
  return value === null || value === undefined ? null : el('span', { class: `ec-vis-yoy ${dirClass(value)}`, text: `${pct(value, 0)} y/y` });
}

// Consensus with its range drawn, the estimate's trail and the split of the
// last 30 days' revisions. All of it is what Yahoo and Nasdaq gave at the
// build; the card's freshness line says when.
function consensusStats(c, payload, compact) {
  const k = c.consensus || {};
  const eps = k.eps ?? k.eps_yahoo;
  const epsGeo = rangeGeometry(k.eps_low, k.eps_high, eps, k.eps_year_ago);
  const epsBar = rangeBarNode(epsGeo, { low: k.eps_low, high: k.eps_high, point: eps, ref: k.eps_year_ago, fmt: (v) => figure(v) });
  const revGeo = rangeGeometry(k.revenue_low, k.revenue_high, k.revenue, k.revenue_year_ago);
  const revBar = rangeBarNode(revGeo, { low: k.revenue_low, high: k.revenue_high, point: k.revenue, ref: k.revenue_year_ago, fmt: billions });
  const analysts = k.analysts ? `${k.analysts} analysts` : (k.eps_estimates ? `${k.eps_estimates} estimates` : null);
  const thisQuarter = (payload.revisions || []).find((r) => r.period === '0q');
  const levels = thisQuarter ? trailLevels(thisQuarter.eps, thisQuarter.changes) : [];
  const out = [
    visual(`EPS CONSENSUS${k.fiscal_quarter ? ` · ${k.fiscal_quarter}` : ''}`, eps === null || eps === undefined ? DASH : num(eps), analysts, epsBar, { tail: yoy(k.eps_growth_pct) }),
    visual('REVENUE CONSENSUS', billions(k.revenue), k.revenue ? null : 'Yahoo row is not this quarter, or none', revBar, { tail: yoy(k.revenue_growth_pct) }),
  ];
  if (levels.length > 1 || k.up_30d !== undefined) {
    const t = trailSummary(levels);
    const sentence = t && (t.verb === 'held'
      ? `held at ${num(t.to, 2)} for ${t.span}`
      : `${num(t.from, 2)} → ${num(t.to, 2)}${t.when ? ` · almost all of it ${t.when}` : ''}`);
    out.push(visual(`EPS ESTIMATE · LAST ${t ? t.span.toUpperCase() : '90 DAYS'}`,
      t ? (t.verb === 'held' ? 'Unchanged' : `${t.verb === 'raised' ? 'Raised' : 'Cut'} ${num(Math.abs(t.total), 1)}%`) : DASH,
      compact ? null : 'Yahoo\'s own consensus, so it can differ slightly from the EPS above; it gives 7/30/60/90-day windows, not the date of each change',
      el('div', {}, [t ? el('div', { class: 'ec-vis-sub', text: sentence }) : null, trailNode(levels), splitBarNode(k.up_30d, k.down_30d)]),
      { cls: t && t.verb !== 'held' ? (t.verb === 'raised' ? 'up' : 'down') : '' }));
  }
  return out;
}

// What the report moved the stock in the past and what the options market
// asks for this time.
function pricedStats(c, payload, compact, prices) {
  const p = c.priced || {};
  const implied = p.implied;
  const drawing = reactionNode(payload.history, implied, p.mean_abs);
  const impliedNote = implied
    ? `last bar: implied ±${num(implied.straddle_pct, 1)}% (straddle to ${implied.expiry} · ${implied.snapshot_day} snapshot)`
    : 'last bar: no implied move for the coming report yet';
  const out = [
    visual('STOCK MOVE AFTER PAST REPORTS', p.mean_abs ? `±${num(p.mean_abs, 1)}%` : DASH,
      p.reports ? (compact ? null : `Move on the report session, last ${p.reports}; dashed line = the average. Median ±${num(p.median_abs, 1)}%. ${impliedNote}`) : 'no 8-K releases on file',
      drawing, { tail: p.reports ? el('span', { class: 'ec-vis-yoy dim', text: `typical size · up ${p.up} of ${p.reports}` }) : null }),
  ];
  const sur = surpriseRows(payload.history);
  if (sur.n) {
    out.push(visual('BEAT OR MISS, THEN THE STOCK', `beat ${sur.beats} of ${sur.n}`,
      compact ? 'green: stock rose · red: fell' : 'Dot height = EPS surprise against consensus. Green: the stock rose on the report session; red: it fell.',
      surpriseNode(sur.rows), { tail: sur.beats ? el('span', { class: 'ec-vis-yoy dim', text: `stock rose after ${sur.roseOnBeat} of those` }) : null }));
  }
  const g = prices ? priceGeometry(prices.dates, prices.close, (payload.history || []).map((r) => ({ date: r.session || r.date, move: r.move_pct }))) : null;
  if (g) {
    const s = c.setup || {};
    const going = !compact && s.ret_20d !== null && s.ret_20d !== undefined
      ? `20d ${pct(s.ret_20d, 1)}${s.vs_sector_20d !== null && s.vs_sector_20d !== undefined ? ` (${s.vs_sector_20d > 0 ? '+' : ''}${num(s.vs_sector_20d, 1)} pp vs ${s.sector_etf})` : ''}` : null;
    out.push(visual('PRICE · 1Y', pct(g.ret, 0),
      [`${pct(g.fromHigh, 1)} from its high`, s.above_50d === null || s.above_50d === undefined ? null : (s.above_50d ? 'above its 50-day' : 'below its 50-day'), `last ${num(g.last, 2)}`, going].filter(Boolean).join(' · '),
      priceNode(g), { cls: dirClass(g.ret) }));
  }
  return out;
}

// What the name is and what the report can move: its sector and industry
// (coloured by sector) and its weight in the indices at the average move.
function identityRow(payload, c) {
  const hue = sectorHue(payload.sector);
  const style = hue === null ? '' : `--sec:hsl(${hue} 62% 54%)`;
  const impact = c.impact || {};
  const indices = Object.entries(impact.indices || {}).sort((a, b) => b[1].points_pct - a[1].points_pct);
  return el('div', { class: 'tag-row event-identity' }, [
    payload.sector ? el('span', { class: 'tag ec-sector', style, text: payload.sector.toUpperCase(), title: 'GICS sector' }) : null,
    payload.industry ? el('span', { class: 'tag ec-sector ec-industry', style, text: payload.industry, title: 'GICS sub-industry' }) : null,
    indices.length
      ? el('span', {
        class: 'tag tag-dim',
        text: `INDEX IMPACT ${indices.map(([k, v]) => `${k} ±${num(v.points_pct, 2)}%`).join(' · ')}`,
        title: `weight × ${impact.basis} move ±${num(impact.move_pct, 1)}% · ${indices.map(([k, v]) => `${k} ${num(v.weight, 2)}%`).join(', ')}`,
      })
      : el('span', { class: 'tag tag-dim', text: 'NOT AN INDEX MEMBER' }),
  ]);
}

// Where each part of the card came from and how old it is. The estimates are
// the build's; an implied move older than a few sessions is marked.
function freshness(payload, c, asOf) {
  const k = c.consensus || {};
  const implied = c.priced?.implied;
  const days = implied ? Math.round((new Date(`${asOf}T00:00:00Z`) - new Date(`${implied.snapshot_day}T00:00:00Z`)) / 86400000) : null;
  return el('div', { class: 'tag-row event-fresh' }, [
    el('span', { class: 'dim', text: 'DATA' }),
    tag(`ESTIMATES · ${k.source || 'Yahoo'} · build ${payload.as_of || asOf}`, 'info', 'consensus, range, revisions and revenue; refreshed with each nightly build'),
    tag(implied ? `IMPLIED · ${implied.snapshot_day} snapshot${days > 3 ? ' · OLD' : ''}` : 'IMPLIED · none in snapshot', implied && days <= 3 ? 'info' : 'warn',
      'the options snapshot is taken on its own schedule; a straddle must expire within a week of the report'),
    tag(`REPORTS · 8-K history to ${((payload.history || [])[0] || {}).date || DASH}`, 'dim', 'moves and surprises come from the company\'s own releases'),
  ]);
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

function setupStats(c, hasPrice = false) {
  const s = c.setup || {};
  // With the price drawn, its note carries the 20-day move and the 1Y high.
  if (hasPrice) return [];
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

// The reason a name is a peer, short enough for a cell (the full one on hover).
function linkShort(reason) {
  if (!reason) return DASH;
  if (reason.startsWith('theme: ')) return reason.slice(7).split(' ')[0];
  if (reason.startsWith('same industry')) return 'industry';
  return reason.replace('trades with it ', '');
}

function withTable(rt, limit) {
  const rows = (rt.with || []).slice(0, limit).map((r) => el('tr', {}, [
    el('td', { title: r.link || '' }, [link(r.symbol)]),
    el('td', { class: 'dim', text: linkShort(r.link), title: r.link || '' }),
    betaCell(r.beta),
    hitCell(r.hit),
    el('td', { class: 'dim', text: `±${num(r.mean_abs, 1)}%` }),
    el('td', { class: 'dim', text: `${r.n} · t ${num(r.t, 1)}` }),
  ]));
  if (rt.sector_etf) {
    const s = rt.sector_etf;
    rows.push(el('tr', { class: 'dim' }, [el('td', { text: s.symbol }), el('td', { text: 'sector' }), betaCell(s.beta), hitCell(s.hit),
      el('td', { text: `±${num(s.mean_abs, 1)}%` }), el('td', { text: String(s.n) })]));
  }
  return rows.length ? table(['PEER', 'WHY', 'BETA', 'SAME WAY', 'AVG |MOVE|', 'N · T'], rows)
    : el('div', { class: 'dim', text: (rt.reports || 0) < 4 ? `Too few past reports to measure (${rt.reports || 0}).`
      : `No linked peer moved reliably on its ${rt.reports} reports (of ${rt.candidates ?? 0} checked).` });
}

function intoTable(rt, limit, asOf) {
  const rows = (rt.into || []).slice(0, limit).map((r) => el('tr', {}, [
    el('td', { title: r.link || '' }, [link(r.symbol), el('span', { class: 'dim', text: ` ${linkShort(r.link)}` })]),
    el('td', { class: r.next ? '' : 'dim', text: r.next ? `${r.next} ${(r.timing || '').toUpperCase()}` : 'not in 30 days' }),
    betaCell(r.beta),
    hitCell(r.hit),
    el('td', { class: 'dim', text: `${r.n} · t ${num(r.t, 1)}` }),
  ]));
  return rows.length ? table(['REPORTER', 'NEXT REPORT', 'BETA', 'SAME WAY', 'N · T'], rows)
    : el('div', { class: 'dim', text: 'No linked name whose reports have moved it reliably.' });
}

// The full card on TICKER; `compact` is the CATALYSTS lead strip's version.
// The bar a coming report has to clear (docs/expectations_research_v1.md): the
// name's usual beat -- the median of its earlier EPS surprises -- and the EPS
// that clears it; what clearing a usual beat was worth across names; and the
// sub-industry's reaction profile. Each as [label, value, note, tone]; a sector
// whose prices did not answer EPS gets its reason instead.
const signedPct = (v, digits = 1) => (isFinite(v) && v !== null ? `${v > 0 ? '+' : v < 0 ? '−' : ''}${num(Math.abs(v), digits)}%` : DASH);

export function barStats(bar) {
  if (!bar) return [];
  if (bar.no_eps_bar) {
    return [['THE BAR · EPS', 'Not shown', `${bar.no_eps_bar}: over 2024-26 the price did not answer the EPS surprise (FFO, the rate base and rates did), so no EPS bar is set`, 'dim']];
  }
  const out = [];
  if (bar.usual_beat_pct !== null && bar.usual_beat_pct !== undefined) {
    const eps = bar.eps_at_usual_beat !== null && bar.eps_at_usual_beat !== undefined ? ` · EPS ${num(bar.eps_at_usual_beat, 2)} matches it` : '';
    const misses = bar.usual_beat_pct < 0 ? 'it usually reports below consensus: ' : '';
    out.push(['THE BAR · USUAL BEAT', signedPct(bar.usual_beat_pct), `${misses}median EPS surprise of its last ${bar.usual_beat_reports} reports${eps}`, '']);
  } else {
    out.push(['THE BAR · USUAL BEAT', DASH, `fewer than 3 earlier reports with a surprise on record`, 'dim']);
  }
  const above = bar.above_usual;
  const below = bar.at_or_below_usual;
  if (above?.n && below?.n) {
    out.push(['BEATS ABOVE THE USUAL BEAT', `${num(above.up_pct, 0)}% rose`,
      `against ${num(below.up_pct, 0)}% at or below it · first session vs the S&P 500, all names (n ${above.n} and ${below.n}), each against its earlier reports only`, 'up']);
  }
  const ind = bar.industry_profile;
  if (ind && ind.beats_fell_pct !== null && ind.beats_fell_pct !== undefined) {
    out.push([`${(bar.industry || 'SUB-INDUSTRY').toUpperCase()}`, `${num(ind.beats_fell_pct, 0)}% of beats fell`,
      `median beat ${signedPct(ind.median_beat)} · median miss ${signedPct(ind.median_miss)} · usual surprise ${signedPct(ind.median_surprise)} · ${ind.reports} reports, ${ind.names} names since ${ind.since}`,
      ind.beats_fell_pct >= 50 ? 'down' : '']);
  }
  return out;
}

// The compact card's one tag: the usual beat, or why there is none.
export function barTag(bar) {
  if (!bar) return null;
  if (bar.no_eps_bar) return tag('NO EPS BAR', 'dim', `${bar.no_eps_bar}: the price did not answer EPS surprises`);
  if (bar.usual_beat_pct === null || bar.usual_beat_pct === undefined) return null;
  return tag(`BAR ${signedPct(bar.usual_beat_pct)}`, 'info', `Usual beat: median EPS surprise of its last ${bar.usual_beat_reports} reports. Beats above a name's usual beat rose more often than beats at or below it.`);
}

export function eventCard(payload, asOf, { compact = false, prices = null } = {}) {
  const c = payload.card;
  if (!c) return null;
  const title = compact ? `${payload.symbol} · ${(payload.name || '').toUpperCase()}` : 'NEXT REPORT · EVENT CARD';
  const right = el('span', { class: 'tag-row' }, [whenTag(c, asOf), pricedTag(c.priced), guideTag(c), barTag(c.bar),
    el('span', { class: 'dim', text: `${c.date} · reacts ${c.reaction_session || DASH}` })]);
  const rt = payload.readthrough || {};
  const body = [
    identityRow(payload, c),
    el('div', { class: 'stat-strip event-stats visual' }, [...consensusStats(c, payload, compact), ...pricedStats(c, payload, compact, prices), ...(compact ? [] : setupStats(c, Boolean(prices)))]),
    freshness(payload, c, asOf),
  ];
  const bar = compact ? [] : guideStats(c);
  if (bar.length) body.push(el('div', { class: 'stat-strip event-stats' }, bar));
  const hurdle = compact ? [] : barStats(c.bar);
  if (hurdle.length) body.push(el('div', { class: 'stat-strip event-stats event-bar' }, hurdle.map(([label, value, note, tone]) => stat(label, value, note, tone))));
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
    'Peers: names with a reason to move together -- the same GICS industry, a shared theme, or daily moves beyond the S&P 500 correlated at 0.45 or more over the last year -- scored on report days only, '
    + 'and shown only where the report-day beta is positive with a t-statistic of 2 or more (T): with eight reports, chance alone produces plenty of striking betas. '
    + 'BETA = the peer\'s excess move per 1% excess move of the reporter; SAME WAY = share of those sessions both went the same direction. '
    + 'History, not a forecast; N is small. Index impact = index weight × the implied move (the straddle to the first expiry after the report, so it covers more than the report).' }));
  return card(title, right, body);
}

// --- The report card: what a report printed, against what was expected ---

const isNum = (v) => v !== null && v !== undefined && Number.isFinite(v);
const SOURCE = { nasdaq: 'Nasdaq', yahoo: 'Yahoo' };
const POSITION_WORD = { above_range: 'ABOVE EVERY ESTIMATE', beat: 'BEAT', inline: 'IN LINE', miss: 'MISS', below_range: 'BELOW EVERY ESTIMATE' };
const GUIDE_WORD = { above: 'above the street', below: 'below the street', inside: 'in line with the street' };

// The words under a scorecard line: where the actual sits against the range
// and the consensus. DASH when the build could not place it.
export function positionWord(position) {
  return POSITION_WORD[position] ?? DASH;
}

// The colour of a position: green for a beat or above the range, red for a
// miss or below it, plain for in line.
export function positionTone(position) {
  if (position === 'above_range' || position === 'beat') return 'up';
  if (position === 'below_range' || position === 'miss') return 'down';
  return '';
}

// The name a build's source goes by on the card, or null for one it does not know.
export function sourceLabel(source) {
  return SOURCE[source] ?? null;
}

// "reported 2026-10-20 BMO · traded 2026-10-20 · 2 sessions ago".
export function reportLine(o) {
  const parts = [`reported ${o.date || DASH}${o.timing ? ` ${o.timing.toUpperCase()}` : ''}`, `traded ${o.session || DASH}`];
  if (isNum(o.sessions_since) && o.sessions_since > 0) parts.push(`${o.sessions_since} ${o.sessions_since === 1 ? 'session' : 'sessions'} ago`);
  return parts.join(' · ');
}

// The guide's range in its own figures and period: "EPS 7.10–7.40 · FY2026".
export function guideRange(g) {
  if (!g) return null;
  const parts = [];
  if (isNum(g.eps_low) && isNum(g.eps_high)) parts.push(`EPS ${num(g.eps_low)}–${num(g.eps_high)}`);
  if (isNum(g.revenue_low) && isNum(g.revenue_high)) parts.push(`revenue ${billions(g.revenue_low)}–${billions(g.revenue_high)}`);
  if (!parts.length) return null;
  return [parts.join(' · '), g.period].filter(Boolean).join(' · ');
}

// The guide against the street for the same period: where the guide's middle
// sits against the consensus, and by how much. Null when the build has no
// comparison.
export function guideStreet(g) {
  const v = g?.vs_consensus;
  if (!v) return null;
  const rows = [['EPS', v.eps, (x) => num(x.consensus)], ['revenue', v.revenue, (x) => billions(x.consensus)]]
    .filter(([, x]) => x && x.position && GUIDE_WORD[x.position]);
  if (!rows.length) return null;
  return rows.map(([label, x, fmt]) => {
    const mid = isNum(x.vs_mid_pct) ? ` (${signed(x.vs_mid_pct)} at mid)` : '';
    return `${rows.length > 1 ? `${label} ` : ''}street ${fmt(x)} → guide ${GUIDE_WORD[x.position]}${mid}`;
  }).join(' · ');
}

// One consensus revision: "Next quarter 2.30 → 2.41 (+4.8%)".
export function revisionText(r) {
  const change = isNum(r.change_pct) ? ` (${signed(r.change_pct)})` : '';
  return `${r.label ?? r.period ?? DASH} ${num(r.before)} → ${num(r.now)}${change}`;
}

// The excess return N sessions after the reaction, or DASH while it is not yet there.
export function driftText(value, sessions) {
  return isNum(value) ? `${pct(value, 1)} vs S&P ${sessions} sessions later` : DASH;
}

// What "before" means on this card: the consensus snapshot the build used.
export function reportFieldNote(consensusDay) {
  const before = consensusDay
    ? `the consensus recorded on ${consensusDay} (Yahoo, Nasdaq for the EPS point)`
    : 'the consensus recorded before the report (Yahoo, Nasdaq for the EPS point)';
  return `Before = ${before}. Range = the analysts' low and high. Move vs priced: the straddle before the report; it spans more than the report day.`;
}

// The EPS line of the card: the scorecard's, or the build's own EPS fields when
// it wrote no scorecard (the position is then worked out from the cents).
function epsLine(o) {
  if (o.scorecard?.eps) return o.scorecard.eps;
  const actual = o.eps ?? null;
  const consensus = o.eps_forecast ?? null;
  let position = null;
  if (isNum(actual) && isNum(consensus)) {
    const a = Math.round(actual * 100);
    const c = Math.round(consensus * 100);
    position = a === c ? 'inline' : a > c ? 'beat' : 'miss';
  }
  return { actual, consensus, low: null, high: null, surprise_pct: o.surprise_pct ?? null, position, source: null };
}

// A report figure as a visual: the actual large, the consensus and the surprise
// beside it, the range with both marked, and the position under it.
function scoreVisual(label, line, fmt, missing) {
  if (!line) return visual(label, DASH, missing, null);
  const surprise = line.surprise_pct;
  const vs = isNum(line.consensus) ? `vs ${fmt(line.consensus)} consensus${isNum(surprise) ? ` · ${pct(surprise, 1)}` : ''}` : 'no consensus on file';
  const source = sourceLabel(line.source);
  const drawing = scorecardNode(scorecardScale(line.low, line.high, line.consensus, line.actual),
    { low: line.low, high: line.high, consensus: line.consensus, actual: line.actual, fmt, tone: positionTone(line.position) });
  return visual(label, fmt(line.actual), `${positionWord(line.position)}${source ? ` · ${source}` : ''}`, drawing, {
    cls: dirClass(surprise),
    tail: el('span', { class: `ec-vis-yoy ${dirClass(surprise)}`, text: vs }),
  });
}

// A block of the strip with no drawing: a label and its lines.
function block(label, lines) {
  return el('div', { class: 'stat ec-vis' }, [el('div', { class: 'stat-label', text: label }), ...lines]);
}

// The name as the card's title: its symbol and, when the build has it, its name.
function titleOf(payload) {
  return payload.name ? `${payload.symbol} · ${payload.name.toUpperCase()}` : payload.symbol;
}

// A report the last session traded on, as a report card: what it printed
// against the consensus before it, the guide it gave against the street, how
// the estimates moved since, and how the stock took it against the priced
// move. TICKER draws it in full; CATALYSTS' lead strip draws it compact.
export function outcomeCard(payload, { compact = false } = {}) {
  const o = payload.outcome;
  if (!o) return null;
  const sc = o.scorecard || {};
  const surprise = o.surprise_pct;
  const ratio = o.vs_implied;
  const right = el('span', { class: 'tag-row' }, [
    surprise === null || surprise === undefined ? null : tag(`EPS ${surprise >= 0 ? 'BEAT' : 'MISS'} ${pct(surprise, 1)}`, surprise >= 0 ? 'up' : 'down'),
    ratio ? tag(ratio > 1 ? `MOVED ${num(ratio, 1)}× IMPLIED` : `INSIDE IMPLIED (${num(ratio, 1)}×)`, ratio > 1 ? 'warn' : 'dim') : null,
  ]);
  const implied = o.implied;
  const typical = payload.card?.priced?.mean_abs;
  const moveNote = [isNum(o.excess_pct) ? `${pct(o.excess_pct, 1)} vs S&P 500` : null,
    !implied && isNum(typical) ? `typical ±${num(typical, 1)}%` : null].filter(Boolean).join(' · ');
  const move = visual('MOVE VS PRICED', pct(o.move_pct, 1), moveNote || null,
    (implied && moveBandNode(implied.straddle_pct, o.move_pct)) || el('div', { class: 'dim ec-vis-note', text: DASH }),
    { cls: dirClass(o.move_pct) });
  const guide = o.guide
    ? block('GUIDE GIVEN', [el('div', { class: 'stat-value ec-vis-small', text: guideRange(o.guide) || DASH }),
      el('div', { class: 'stat-note', text: guideStreet(o.guide) || 'no street figure for that period' })])
    : block('GUIDE GIVEN', [el('div', { class: 'stat-note', text: 'no guide found in the release' })]);
  const revisions = o.revisions || [];
  const estimates = block('ESTIMATES SINCE', revisions.length
    ? revisions.map((r) => el('div', { class: `stat-note ${dirClass(r.change_pct)}`, text: revisionText(r) }))
    : [el('div', { class: 'stat-note', text: sc.consensus_day ? 'no change yet' : 'no recorded consensus before the report' })]);
  const drift = o.drift || {};
  const after = block('AFTER', [
    el('div', { class: `stat-value ec-vis-small ${dirClass(drift['5d'])}`, text: driftText(drift['5d'], 5) }),
    el('div', { class: `stat-value ec-vis-small ${dirClass(drift['20d'])}`, text: driftText(drift['20d'], 20) }),
  ]);
  const strip = el('div', { class: 'stat-strip event-stats visual' }, [
    scoreVisual('EPS', epsLine(o), (v) => figure(v), 'no EPS figure yet'),
    scoreVisual('REVENUE', sc.revenue ?? null, billions, 'no revenue figure yet'),
    move, guide, estimates, after,
  ]);
  const line = el('div', { class: 'dim event-report-line', text: reportLine(o) });
  const peerRows = (o.peers || []).map((r) => el('tr', {}, [
    el('td', {}, [link(r.symbol)]),
    el('td', { class: 'dim', text: num(r.beta, 2) }),
    el('td', { class: dirClass(r.expected_pct), text: pct(r.expected_pct, 1) }),
    el('td', { class: dirClass(r.excess_pct), text: pct(r.excess_pct, 1) }),
  ]));
  const peers = peerRows.length ? table(['PEER', 'BETA', 'HISTORY SAYS', 'ACTUAL (VS S&P)'], peerRows) : null;
  if (compact) {
    return el('div', { class: 'card event-card compact' }, [
      el('div', { class: 'card-head' }, [el('a', { class: 'card-title', href: tickerHref(payload.symbol), text: titleOf(payload) }), right]),
      line, strip, peers,
    ]);
  }
  return card(titleOf(payload), right, [line, strip,
    peers ? el('div', { class: 'card-title', text: 'READ-THROUGH ON THE SESSION' }) : null, peers,
    el('div', { class: 'field-note', text: reportFieldNote(sc.consensus_day) })]);
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
    el('td', { class: 'dim', text: `${driverValue(r.unit, r.then.value)}${r.then.revised !== undefined ? '*' : ''}`,
      title: `${r.then.period}, public ${r.then.available}${r.then.as ? ', as first published' : ''}${r.then.revised !== undefined ? `; since revised to ${driverValue(r.unit, r.then.revised)}` : ''}` }),
    el('td', { text: driverValue(r.unit, r.now.value), title: `${r.now.period}, public ${r.now.available}${r.now.as ? ', as first published' : ''}` }),
    el('td', { class: dirClass(r.change_pct ?? r.change_pp), text: r.change_pct !== undefined ? signed(r.change_pct)
      : r.unit === 'rate' ? signed(Math.round(r.change_pp * 100), 0, 'bp') : signed(r.change_pp, 1, 'pp') }),
    el('td', { class: 'dim', text: String(r.releases) }),
  ]));
  return card(`SINCE THE LAST REPORT${last ? ` · ${last}` : ''}`, el('span', { class: 'dim', text: 'the industry data of its themes' }), [
    table(['SERIES', 'THEN', 'NOW', 'CHANGE', 'NEW'], body),
    el('div', { class: 'field-note', text: 'THEN: each series as it was public on the report day (a month\'s figure dates from its publisher\'s release). NOW: its latest. FRED series show what each release first said (ALFRED), y/y against the year-earlier figure as then known -- not today\'s revised history; * marks a figure since revised (hover for the revised value). NEW: releases since. y/y series change in pp, rates and spreads in bp, levels in %. Hover a value for its period; series and sources are on THEMES.' }),
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
  const macroKeys = new Set();
  (macro || []).filter((m) => m.date > asOf && m.date <= end).forEach((m) => {
    macroKeys.add(`${m.date}|${m.title}`);
    items.push({ date: m.date, kind: 'macro', label: `${m.title}${m.time ? ` ${m.time} ET` : ''}`, tone: 'dim' });
  });
  (payload.company_events || []).filter((e) => e.date > asOf && e.date <= end).forEach((e) => items.push({
    date: e.date, kind: 'company', label: `${e.kind.toUpperCase()}: ${e.text}`, url: e.url, tone: 'warn',
  }));
  // The industry's own calendar: the data and releases its theme trades on.
  (payload.theme_dates || []).filter((t) => t.date > asOf && t.date <= end && !macroKeys.has(`${t.date}|${t.title}`)).forEach((t) => items.push({
    date: t.date, kind: 'theme', label: `${t.title}${t.time ? ` ${t.time} ET` : ''} · ${t.theme}${t.late ? ' (late)' : ''}`, tone: t.kind === 'data' ? 'up' : 'dim',
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
  if (item.kind === 'filing') return `8-K: ${item.labels.join(', ')} (item ${item.items.join(', ')})`;
  if (item.kind === 'move') {
    const why = [...(item.reasons || []).map((r) => escapeHtml(r.text)), ...(item.news || []).slice(0, 2).map((n) => `“${escapeHtml(n.headline)}” (${escapeHtml(n.source || '')})`)];
    return `Large move: ${pct(item.excess_pct, 1)} vs S&P (${num(Math.abs(item.z), 1)}σ of its own)<br>${why.length ? why.join('<br>') : 'nothing on record explains it'}`;
  }
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
        filing: () => ({ symbol: 'rect', symbolSize: 7, color: p.accent }),
      };
      const moveMarkers = (payload.moves || []).filter((m) => m.date >= start).map((m) => ({
        value: [m.date, at(m.date)], item: { ...m, kind: 'move' }, symbol: 'emptyCircle', symbolSize: Math.min(6 + Math.abs(m.z) * 1.5, 16),
        itemStyle: { color: m.excess_pct >= 0 ? p.up : p.down, borderWidth: 1.5 }, label: { show: false },
      }));
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
        lineStyle: { color: f.kind === 'report' || f.kind === 'company' ? p.accent : f.kind === 'peer' ? p.blue : f.kind === 'theme' && f.tone === 'up' ? p.up : p.faint,
          type: f.kind === 'report' ? 'solid' : 'dashed', width: f.kind === 'report' ? 1.5 : 1, opacity: f.kind === 'macro' || f.kind === 'theme' ? 0.6 : 1 },
        label: { show: f.kind === 'report' || f.kind === 'peer' || f.kind === 'company', formatter: f.kind === 'report' ? 'EARN' : f.kind === 'company' ? 'EVENT' : f.symbol,
          color: f.kind === 'report' || f.kind === 'company' ? p.accent : p.blue, fontSize: 9, position: 'end', rotate: 0 },
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
            if ((q.seriesIndex === 1 || q.seriesIndex === 2) && q.data?.item) return `<b>${q.data.item.date}</b><br>${pastLabel(q.data.item)}`;
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
          { type: 'scatter', name: 'moves', data: moveMarkers, z: 4 },
        ],
      };
    });
  };
  const head = el('div', { class: 'chart-head' }, [
    el('span', { class: 'tag-row' }, [tag('● REPORT', 'dim'), tag('▲▼ RATING', 'dim'), tag('◆ INSIDER BUY', 'info'), tag('■ 8-K', 'warn'), tag('○ LARGE MOVE', 'dim'), tag('| PEER / MACRO / INDUSTRY DATA AHEAD', 'dim')]),
    ranges.length > 1 ? Object.assign(periodSwitch(ranges, active, (r) => { active = r; draw(); }), { className: 'period-switch range-switch' }) : null,
  ]);
  requestAnimationFrame(draw);
  const list = future.length ? table(['DATE', 'AHEAD'], future.map((f) => el('tr', {}, [
    el('td', { text: f.date }),
    el('td', {}, [f.kind === 'peer' ? el('span', {}, [link(f.symbol), ` ${f.label.slice(f.symbol.length)}`])
      : f.kind === 'company' && f.url ? el('a', { class: 'accent-text', href: f.url, target: '_blank', rel: 'noopener', text: f.label })
      : el('span', { class: f.kind === 'report' || f.kind === 'company' ? 'accent-text' : f.kind === 'theme' && f.tone === 'up' ? '' : 'dim', text: f.label })]),
  ]))) : null;
  const events = (payload.company_events || []).filter((e) => e.date > asOf);
  const eventList = events.length ? table(['DATE', 'COMPANY EVENT', 'SOURCE'], events.map((e) => el('tr', {}, [
    el('td', { text: e.date }),
    el('td', {}, [el('span', { class: 'accent-text', text: `${e.kind.toUpperCase()} ` }), e.text]),
    el('td', { class: 'dim' }, [e.url ? el('a', { href: e.url, target: '_blank', rel: 'noopener', text: e.source || 'link' }) : (e.source || DASH),
      e.origin === 'announced' ? ` · ${e.published}` : ' · hand-kept']),
  ]))) : null;
  return card('TIMELINE', el('span', { class: 'dim', text: `past events on the price · next ${daysAhead} days shaded` }), [
    head, node,
    list ? el('div', { class: 'card-title', text: `NEXT ${daysAhead} DAYS` }) : null, list,
    eventList ? el('div', { class: 'card-title', text: 'COMPANY EVENTS AHEAD' }) : null, eventList,
    el('div', { class: 'field-note', text: 'Blackout: an estimated buyback quiet period from 30 days before to 2 days after the report -- a common convention, not this company\'s policy. Peers ahead are the linked names whose reports have moved this one (REPORTS THAT MOVE IT). Industry data: the releases and macro dates of the themes the name belongs to (THEMES). 8-K: material filings -- agreements, acquisitions, restructuring, impairments, restatements, officer changes, equity sales. Company events: dated investor days, product events, FDA dates, meetings and rulings found in the company\'s recent headlines (each with its source; check it), and the hand-kept list in the config. Ratings and insider buys cover the names EVIDENCE tracks in depth.' }),
  ]);
}

// Where the name stands now, in the market's own numbers: what the street
// expects, how fast that has moved, how the stock has taken its reports and
// where the price sits. Facts with short readings -- the reader draws the
// conclusion. TICKER draws them in its summary strip.
export function situation(payload, row, prices) {
  const rev = Object.fromEntries((payload?.revisions || []).map((r) => [r.period, r]));
  const thisYear = rev['0y'];
  const nextYear = rev['+1y'];
  const hs = payload?.history_summary || {};
  const out = { reads: [] };
  if (thisYear?.eps && nextYear?.eps) {
    out.growth = (nextYear.eps / thisYear.eps - 1) * 100;
    out.growthNote = `FY to ${nextYear.end?.slice(0, 7)} ${num(nextYear.eps, 2)} vs ${num(thisYear.eps, 2)}`;
  }
  const drift = nextYear?.changes?.['90d'];
  if (drift !== undefined && drift !== null) {
    out.drift = drift;
    out.driftNote = `this year ${pct(thisYear?.changes?.['90d'], 1)} · ${nextYear.up_30d ?? 0}↑ ${nextYear.down_30d ?? 0}↓ revisions in 30d`;
    if (drift >= 10) out.reads.push(['estimates rising fast', 'up']);
    else if (drift <= -10) out.reads.push(['estimates falling fast', 'down']);
  }
  if (row?.pe_forward) {
    const trailing = row.pe_operating ?? row.pe;
    if (trailing && row.pe_forward < 0.5 * trailing) out.reads.push(['forward multiple under half the trailing: earnings expected to jump', 'info']);
    if (trailing && row.pe_forward > 1.2 * trailing) out.reads.push(['forward above trailing: earnings expected to fall', 'warn']);
  }
  if (hs.measured) {
    out.reports = hs;
    // A count, not a cause: a beat followed by a fall can mean the news was
    // in the price, or that something else in the report mattered more.
    if (hs.beats >= 4 && hs.beat_and_fell >= hs.beats / 2) out.reads.push([`beat ${hs.beats} of last ${hs.measured}, fell after ${hs.beat_and_fell} of them`, 'warn']);
  }
  if (prices?.close?.length > 252) {
    const close = prices.close;
    const last = close[close.length - 1];
    const high = Math.max(...close.slice(-252).filter((v) => v !== null));
    out.change1y = (last / close[close.length - 253] - 1) * 100;
    out.offHigh = (last / high - 1) * 100;
    if (out.offHigh <= -25) out.reads.push([`${pct(out.offHigh, 0)} from its high`, 'down']);
  }
  return out;
}

// Every report reaction and every large move, newest first, each with what was
// happening: the run of events that made the market's view of the name.
export function storyCard(payload) {
  const reports = (payload.timeline || []).filter((i) => i.kind === 'earnings').map((i) => ({ ...i, sort: i.date }));
  const history = new Map((payload.history || []).map((h) => [h.date, h]));
  const moves = (payload.moves || []).map((m) => ({ ...m, kind: 'move', sort: m.date }));
  const rows = [...reports, ...moves].sort((a, b) => b.sort.localeCompare(a.sort));
  if (!rows.length) return null;
  const body = rows.map((r) => {
    if (r.kind === 'earnings') {
      const h = history.get(r.report) || {};
      const bits = [h.eps_surprise_pct !== undefined && h.eps_surprise_pct !== null ? `EPS ${pct(h.eps_surprise_pct, 1)} vs consensus` : null,
        h.guide_text || null].filter(Boolean);
      return el('tr', {}, [
        el('td', { text: r.date }),
        el('td', { class: dirClass(r.excess_pct), text: pct(r.excess_pct, 1) }),
        el('td', {}, [el('span', { class: 'accent-text', text: `REPORT ${(r.timing || '').toUpperCase()}` }), el('span', { class: 'dim', text: bits.length ? ` · ${bits.join(' · ')}` : '' })]),
      ]);
    }
    const reasons = (r.reasons || []).map((x) => (x.url ? el('a', { href: x.url, target: '_blank', rel: 'noopener', text: x.text })
      : x.symbol ? el('span', {}, [link(x.symbol), x.text.slice(x.symbol.length)]) : el('span', { text: x.text })));
    const headlines = (r.news || []).slice(0, 2).map((n) => el('div', { class: 'dim' }, [
      el('a', { href: n.url, target: '_blank', rel: 'noopener', text: n.headline }), ` · ${n.source || ''}`]));
    const none = !reasons.length && !headlines.length;
    return el('tr', {}, [
      el('td', { text: r.date }),
      el('td', { class: dirClass(r.excess_pct), text: pct(r.excess_pct, 1), title: `${num(Math.abs(r.z), 1)}σ of its own volatility` }),
      el('td', {}, [
        reasons.length ? el('div', {}, reasons.flatMap((n, i) => (i ? [' · ', n] : [n]))) : null,
        ...headlines,
        none ? el('span', { class: 'dim', text: r.news_checked ? 'unexplained: no filing, rating, peer report, data release or company headline that day'
          : 'unexplained by filings, ratings, peers or data; headlines not checked (older than a year, or not yet fetched)' }) : null,
      ]),
    ]);
  });
  const unexplained = moves.filter((m) => !(m.reasons || []).length && !(m.news || []).length).length;
  return card('WHAT MOVED IT · REPORTS AND LARGE MOVES', el('span', { class: 'dim', text: `${reports.length} reports · ${moves.length} large moves · ${unexplained} unexplained` }), [
    table(['SESSION', 'VS S&P', 'WHAT HAPPENED'], body),
    el('div', { class: 'field-note', text: 'Large move: a session whose return beyond the S&P 500 was at least 2.5 times the standard deviation of its previous 60 sessions, and at least 2% -- report days are listed as reports. '
      + 'What happened: the name\'s own 8-Ks (that day or the evening before), rating changes and insider buys, linked peers\' reports, its themes\' data released that day, and up to two company headlines (Finnhub, last year only) published between the previous close and this one, roundups left out. '
      + 'A match is a coincidence in time, not proof of cause.' }),
  ]);
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// The name's price file (dates and closes); null when it has none.
export async function loadPrices(symbol) {
  try {
    const response = await fetch(`artifacts/tickers/${encodeURIComponent(symbol)}.json`, { cache: 'no-cache' });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

export async function loadEvents(symbol) {
  try {
    const response = await fetch(`artifacts/events/${encodeURIComponent(symbol)}.json`, { cache: 'no-cache' });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

