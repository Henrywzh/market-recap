// TICKER: one company on one page, reached from any ticker on the site.
//
// Nothing here is computed afresh. Each section is the panel that already
// owns the figure (MONITOR's evidence, VALUATION's P/E history, FINANCIALS'
// statements, TECHNICALS' single-ticker readings), drawn for one name. A
// section whose artifact does not cover the name says so and the rest of the
// page still renders.

import { el, card, table, num, pct, dirClass, sectionTitle, gap, tag, DASH } from '../fmt.js';
import { render, multiLine } from '../charts.js';
import { valuationBlock, companyBasket, companyHistory } from '../valuation-block.js';
import { renderStatements } from './financials.js';
import { renderSingleTicker } from './technicals.js';
import { eventCard, outcomeCard, timelineCard, loadEvents, historyCard, revisionsCard, sinceCard, filingsCard, storyCard, situation } from '../event-card.js';
import { resolveTicker } from '../routes.js';
import { chainCard } from '../chain-card.js';
import { moveCard } from '../moves-card.js';
import { viewTabs } from '../view-tabs.js';
import { renderEarningsForward } from './valuation.js';

const BILLION = 1e9;
// The multiples shown in the header block, in this order. The full set is on
// SCREEN; these are the ones a first look needs.
const KEY_METRICS = ['pe', 'ev_ebitda', 'fcf_yield', 'shareholder_yield', 'roic', 'operating_margin',
  'revenue_growth', 'net_debt_ebitda', 'piotroski'];
// A bank has no EBITDA, free cash flow or operating margin: it is valued on
// tangible book beside what it earns on it.
const BANK_METRICS = ['pe', 'pe_forward', 'pb', 'ptbv', 'rotce', 'roe', 'dividend_yield', 'shareholder_yield', 'revenue_growth'];

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
export const isBank = (row) => row?.sector === 'Financials' && present(row?.ptbv_percentile);

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function ordinal(value) {
  const n = Math.round(value);
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
  return `${n}${suffix}`;
}

function format(value, unit) {
  if (value === null || value === undefined) return DASH;
  if (unit === 'x') return `${num(value, 1)}x`;
  if (unit === 'pct') return `${num(value, 1)}%`;
  if (unit === 'score') return num(value, 0);
  return num(value, 1);
}

function median(values) {
  const sorted = values.filter((v) => v !== null && v !== undefined).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const mid = (sorted.length - 1) / 2;
  return (sorted[Math.floor(mid)] + sorted[Math.ceil(mid)]) / 2;
}

// Artifacts other than this view's own are optional: a missing one blanks
// its section, never the page.
async function optional(ctx, name) {
  try {
    return await ctx.loadArtifact(name);
  } catch {
    return null;
  }
}

async function loadPrices(symbol) {
  try {
    const response = await fetch(`artifacts/tickers/${encodeURIComponent(symbol)}.json`, { cache: 'no-cache' });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function searchRow(symbol, universe, ctx) {
  const input = el('input', { value: symbol || '', size: '10', list: 'ticker-list', placeholder: 'ticker' });
  const datalist = el('datalist', { id: 'ticker-list' },
    [...universe.entries()].map(([ticker, name]) => el('option', { value: ticker, text: name || '' })));
  const go = () => {
    const next = input.value.trim().toUpperCase();
    if (next) ctx.navigate('ticker', next);
  };
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter') go(); });
  return el('div', { class: 'field-row' }, [
    el('div', { class: 'field' }, [el('label', { text: 'TICKER' }), input]),
    el('button', { class: 'action', text: 'OPEN', onclick: go }),
    datalist,
  ]);
}

// The summary: the price, what it pays, where estimates are going and the
// next report -- each once, with the detail further down the page.
function headerStats(row, mon, sit, implied) {
  const stats = [];
  const offHigh = mon?.drawdown_pct ?? sit.offHigh;
  if (row || present(sit.change1y)) {
    stats.push(stat('CLOSE', present(row?.price) ? `$${num(row.price)}` : DASH,
      [present(sit.change1y) ? `1Y ${pct(sit.change1y, 0)}` : null, present(offHigh) ? `${pct(offHigh, 1)} from 1Y high` : null,
        row?.market_cap ? `$${num(row.market_cap / BILLION, 0)}B` : null].filter(Boolean).join(' · ') || null));
  }
  if (mon) {
    stats.push(stat('1M VS SECTOR PEERS', present(mon.peer_excess_pct) ? `${mon.peer_excess_pct > 0 ? '+' : ''}${num(mon.peer_excess_pct, 1)} pp` : DASH,
      `${mon.peer_count || 0} peers, company excluded`, dirClass(mon.peer_excess_pct)));
  }
  if (isBank(row)) {
    stats.push(stat('P/TBV VS OWN 10Y', `${ordinal(row.ptbv_percentile)} pct`,
      [`${num(row.ptbv, 2)}x`, present(row.rotce) ? `ROTCE ${num(row.rotce, 1)}%` : null, present(row.pe_forward) ? `fwd P/E ${num(row.pe_forward, 1)}x` : null].filter(Boolean).join(' · ')));
  } else if (row) {
    // On the history's own basis: operating earnings unless the company has none.
    const basis = row.pe_basis && row.pe_basis !== 'reported' ? (row.pe_basis === 'operating' ? 'operating' : 'ex gains') : null;
    const note = [present(row.pe_forward) ? `fwd ${num(row.pe_forward, 1)}x` : null, present(row.pe_operating) ? `trailing ${num(row.pe_operating, 1)}x` : null,
      present(row.pe_vs_median) ? `${row.pe_vs_median > 0 ? '+' : ''}${num(row.pe_vs_median, 0)}% vs median` : null].filter(Boolean).join(' · ');
    stats.push(stat(`P/E VS OWN 10Y${basis ? ` · ${basis.toUpperCase()}` : ''}`, present(row.pe_percentile) ? `${ordinal(row.pe_percentile)} pct` : DASH, note || null));
  }
  if (present(sit.drift)) {
    stats.push(stat('NEXT-YEAR EPS · 90D', pct(sit.drift, 1),
      [present(sit.growth) ? `street ${pct(sit.growth, 0)} on this year` : null, sit.driftNote?.split(' · ').slice(1).join(' · ')].filter(Boolean).join(' · '), dirClass(sit.drift)));
  }
  if (mon) {
    const timing = mon.earnings_status && mon.earnings_status !== 'not_scheduled' ? mon.earnings_status.replace(/_/g, ' ') : null;
    stats.push(stat('NEXT EARNINGS', mon.earnings_date || DASH, mon.earnings_date
      ? [timing, implied ? `implied ±${num(implied.straddle_pct, 1)}%` : null].filter(Boolean).join(' · ') : 'none on the calendar'));
    stats.push(stat('MONITOR', mon.candidate ? 'QUEUED' : 'NOT QUEUED',
      mon.candidate ? `price ${mon.price_state || '?'} · evidence ${mon.evidence_state || '?'}` : null));
  }
  if (!stats.length) return null;
  return el('div', {}, [
    el('div', { class: 'stat-strip' }, stats),
    sit.reads.length ? el('div', { class: 'tag-row ticker-reads' }, sit.reads.map(([text, tone]) => tag(text, tone))) : null,
  ]);
}

// A small heading between the parts of one pane.
function subhead(text) {
  return el('div', { class: 'card-title ticker-subhead', text });
}

// A section that is detail behind something already on the page: folded.
function fold(label, node) {
  return node ? el('details', { class: 'fold' }, [el('summary', { text: label }), node]) : null;
}

function links(symbol, { mon, dcf, pairs }) {
  const items = [
    ['TECHNICALS TOOL', `#technicals/${encodeURIComponent(symbol)}`],
    ['SCREENER', '#valuation'],
  ];
  if (dcf?.available?.includes(symbol)) items.push(['DCF MODEL', `#dcf/${encodeURIComponent(symbol)}`]);
  if (pairs.some((p) => p.us_ticker === symbol)) items.push(['CROSS-LISTING', '#cross-listing']);
  if (mon?.candidate) items.push(['MONITOR QUEUE', '#monitor']);
  const nodes = [];
  items.forEach(([label, href], index) => {
    if (index) nodes.push(' · ');
    nodes.push(el('a', { href, text: label }));
  });
  return el('div', { class: 'field-note' }, nodes);
}

// The CATALYSTS -> THEMES groups this name belongs to: named there (a
// bellwether or basket member) or trading with the theme's proxy.
function themeTags(memberships, threshold) {
  if (!memberships?.length) return null;
  const order = { bellwether: 0, basket: 1, 'trades with': 2 };
  return el('div', { class: 'tag-row theme-tags' }, [
    el('span', { class: 'stat-label', text: 'THEMES' }),
    ...[...memberships].sort((a, b) => order[a.role] - order[b.role] || (b.corr || 0) - (a.corr || 0)).map((m) => el('a', {
      href: `#themes/${m.key.toUpperCase()}`, class: `tag tag-${m.role === 'trades with' ? 'info' : 'warn'}`,
      text: `${m.label} · ${m.role}${m.corr !== null && m.corr !== undefined ? ` ρ${num(m.corr, 2)}` : ''}`,
      title: m.role === 'trades with' ? `daily excess-return correlation with the theme's proxy over the last year, at or above ${threshold}` : `named as a ${m.role} of this theme`,
    })),
  ]);
}

// Only a name with a recorded decision gets the card; an empty one is noise.
function noteCard(mon) {
  const note = mon?.note;
  if (!note) return null;
  const rows = [
    ['Status', note.status.toUpperCase()],
    ['Since', note.since || DASH],
    ['Reason', note.reason],
    ['Outcome', note.outcome || DASH],
  ];
  return card('RESEARCH NOTE', null, table(['', ''], rows.map(([a, b]) => el('tr', {}, [
    el('td', { class: 'dim', text: a }), el('td', { class: 'wrap-cell', text: b }),
  ]))));
}

function factsLine(ev) {
  if (!ev || !ev.focus) return null;
  const parts = [];
  const ins = ev.insiders;
  if (ins) {
    parts.push(ins.buys.length
      ? `Reported Form 4 P purchases ${ins.window_days}d (broad, may include private/indirect): $${num(ins.buy_value / 1e6, 1)}m (${ins.buys.length} displayed trades); S sales $${num(ins.sell_value / 1e6, 1)}m (${ins.sellers} sellers)`
      : `Reported Form 4 P purchases ${ins.window_days}d: none read; S sales $${num(ins.sell_value / 1e6, 1)}m (${ins.sellers} sellers)`);
  }
  const sh = ev.short;
  if (sh) parts.push(`Short interest ${num(sh.interest / 1e6, 1)}m shares, ${num(sh.days_to_cover, 1)} days to cover (${sh.date})${sh.change_1m_pct !== null && sh.change_1m_pct !== undefined ? `, ${sh.change_1m_pct > 0 ? '+' : ''}${num(sh.change_1m_pct, 0)}% in a month` : ''}`);
  const r = ev.ratings;
  if (r) parts.push(`Ratings ${r.window_days}d: ${r.upgrades} up · ${r.downgrades} down · ${r.initiations} initiations · targets ${r.target_raises} raised / ${r.target_cuts} cut`);
  return parts.length ? el('div', { class: 'note-text', text: parts.join(' · ') }) : null;
}

function evidenceCard(mon, ev) {
  if (!mon && !(ev && ev.focus)) return card('EVIDENCE', null, gap('MONITOR does not cover this ticker in this build.'));
  const list = (items, cls) => (items && items.length
    ? el('ul', { class: 'evidence-list' }, items.map((text) => el('li', { class: cls, text })))
    : el('div', { class: 'dim', text: 'none' }));
  const forItems = [...(mon?.evidence_for || []), ...(ev?.evidence_for || [])];
  const againstItems = [...(mon?.evidence_against || []), ...(ev?.evidence_against || [])];
  if (!mon) {
    return card('EVIDENCE — LISTED, NOT SCORED', null, [
      el('div', { class: 'card-title', text: 'FOR' }), list(forItems, 'up'),
      el('div', { class: 'card-title', text: 'AGAINST' }), list(againstItems, 'down'),
      factsLine(ev),
    ]);
  }
  const exp = mon.expectations;
  const revision = exp && exp.eps !== null && exp.eps !== undefined
    ? `FY1 EPS (year to ${exp.fiscal_year_end || '?'}) ${num(exp.eps)} · 30d ${pct(exp.change_30d_pct, 1)} · 90d ${pct(exp.change_90d_pct, 1)} · `
      + `${exp.up_30d ?? DASH} up / ${exp.down_30d ?? DASH} down of ${exp.analysts ?? DASH} analysts`
    : 'No consensus revision data in this build.';
  const reported = mon.reported
    ? `Last reported ${mon.reported.date}${mon.reported.fiscal_quarter ? ` (${mon.reported.fiscal_quarter})` : ''}: EPS ${num(mon.reported.eps)} vs ${num(mon.reported.eps_forecast)}`
      + ` (${pct(mon.reported.surprise_pct, 1)}), next session ${pct(mon.reported.return_1d, 1)}`
    : null;
  return card('EVIDENCE — LISTED, NOT SCORED', null, [
    el('div', { class: 'card-title', text: 'FOR' }), list(forItems, 'up'),
    el('div', { class: 'card-title', text: 'AGAINST' }), list(againstItems, 'down'),
    el('div', { class: 'note-text', text: revision }),
    reported ? el('div', { class: 'note-text', text: reported }) : null,
    factsLine(ev),
  ]);
}

// The options term structure and the implied move's expiry. Past reactions,
// the average move and the report date are on the event card above.
function optionsCard(symbol, ev, evidence) {
  const o = ev?.options;
  if (!o) return null;
  const termNode = el('div', { class: 'chart short' });
  const implied = o.implied_move;
  const term = o.term || [];
  requestAnimationFrame(() => {
    if (!term.length) return;
    render(termNode, (option, p) => ({
      ...option,
      grid: { left: 44, right: 12, top: 26, bottom: 24 },
      legend: { top: 0, textStyle: { color: p.dim, fontSize: 9 }, itemWidth: 10, itemHeight: 2 },
      tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: (v) => (v === null || v === undefined ? DASH : `${num(v * 100, 1)}%`) },
      xAxis: { ...option.xAxis, boundaryGap: true, data: term.map((t) => `${t.days}d`) },
      yAxis: { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => `${Math.round(v * 100)}%` } },
      series: [
        { name: 'ATM', type: 'line', data: term.map((t) => t.atm_iv), lineStyle: { color: p.text, width: 1.6 }, itemStyle: { color: p.text } },
        { name: '25Δ put', type: 'line', data: term.map((t) => t.put_25d_iv), lineStyle: { color: p.down, width: 1 }, itemStyle: { color: p.down } },
        { name: '25Δ call', type: 'line', data: term.map((t) => t.call_25d_iv), lineStyle: { color: p.up, width: 1 }, itemStyle: { color: p.up } },
      ],
    }));
  });
  const stats = el('div', { class: 'stat-strip ticker-eo-stats' }, [
    stat('IMPLIED MOVE', implied ? `±${num(implied.straddle_pct, 1)}%` : DASH,
      implied ? `ATM straddle to ${implied.expiry} (${implied.days}d), not the report alone` : 'no expiry after the report in the snapshot'),
    stat('IV 30D', o.iv30 ? `${num(o.iv30 * 100, 1)}%` : DASH,
      present(o.iv30_percentile) ? `${o.iv30_percentile}th pct of ${o.iv30_history_days} recorded days` : `${o.iv30_history_days} days recorded; percentile after ${evidence.iv_percentile_min_days}`),
  ]);
  return card('OPTIONS · IMPLIED VOL BY EXPIRY', el('span', { class: 'dim', text: `snapshot ${o.snapshot_day}` }), [
    stats, term.length ? termNode : el('div', { class: 'dim', text: `${symbol} has no term structure in the snapshot.` }),
  ]);
}

function valuationCard(symbol, row, data) {
  if (!row) return card('VALUATION & QUALITY', null, gap(`${symbol} is not on SCREEN in this build (not an index member, or no usable filings).`));
  const byKey = new Map(data.metrics.map((m) => [m.key, m]));
  // A bank against banks of its own kind where there are enough of them.
  const kin = isBank(row) ? data.rows.filter((r) => r.sub_sector && r.sub_sector === row.sub_sector) : [];
  const peers = kin.length >= 3 ? kin : data.rows.filter((r) => r.sector === row.sector);
  const against = kin.length >= 3 ? row.sub_sector : row.sector;
  // A metric neither the company nor its sector has is left out, not dashed.
  const rows = (isBank(row) ? BANK_METRICS : KEY_METRICS).filter((key) => byKey.has(key)).map((key) => {
    const metric = byKey.get(key);
    const mid = median(peers.map((r) => r[key]));
    if (!present(row[key]) && !present(mid)) return null;
    return el('tr', {}, [
      el('td', { text: metric.label }),
      el('td', { text: format(row[key], metric.unit) }),
      el('td', { class: 'dim', text: format(mid, metric.unit) }),
    ]);
  }).filter(Boolean);
  return card(`VALUATION & QUALITY — AGAINST ${against?.toUpperCase() || 'SECTOR'} MEDIAN (${peers.length} COMPANIES)`, null, [
    table(['METRIC', symbol, kin.length >= 3 ? 'PEER MEDIAN' : 'SECTOR MEDIAN'], rows),
    el('div', { class: 'field-note', text: `TTM to ${row.period_end} · filed ${row.filed} · full table on SCREENER` }),
  ]);
}

// What the market expects of one company, in the VALUATION block's terms: forward
// P/E and TTM revenue growth from the valuation build's row, and the consensus EPS
// growth for the next fiscal year from the two fiscal-year EPS the row carries. A
// growth rate measured from a loss is not one, so it is left out.
export function companyOutlook(row) {
  const or = (v) => (present(v) ? v : null);
  const eps0 = row?.eps_fy0;
  const eps1 = row?.eps_fy1;
  return {
    forward_pe: or(row?.pe_forward),
    eps_growth_next: present(eps0) && eps0 > 0 && present(eps1) ? (eps1 / eps0 - 1) * 100 : null,
    revenue_growth: or(row?.revenue_growth),
  };
}

// The company's VALUATION block, against its sector's page. Each part comes from
// its own artifact and is null where that artifact does not cover the name, so
// the block shows what it has and says what it lacks. A sector page without its
// price and earnings series cannot be split into the comparison cards, so only
// its strip and history are given.
export async function companyValuation(ctx, symbol, row, sectors, financials = null) {
  const sectorKey = sectors?.sectors?.find((s) => s.label === row.sector)?.key;
  // Ask only for the files the panels say they wrote: VALUATION marks a name with
  // a P/E history, FINANCIALS lists the names it has statements for.
  const hasHistory = Boolean(row?.pe_history);
  const hasStatements = !financials || (financials.available || []).some((a) => a.ticker === symbol);
  const [own, statement, sectorPage] = await Promise.all([
    hasHistory ? optional(ctx, `valuation/${encodeURIComponent(symbol)}`) : null,
    hasStatements ? optional(ctx, `financials/${encodeURIComponent(symbol)}`) : null,
    sectorKey ? optional(ctx, `sectors/${sectorKey}`) : null,
  ]);
  const peer = sectorPage?.valuation?.price ? sectorPage.valuation : null;
  return valuationBlock({
    name: symbol,
    benchmark: row.sector || null,
    own: { valuation: companyBasket(own), outlook: companyOutlook(row), history: companyHistory(statement) },
    other: sectorPage ? { valuation: peer, outlook: sectorPage.outlook, history: sectorPage.history } : null,
    capAxis: true,
  });
}

// Draws one section, turning its failure into a note inside the section.
async function section(root, title, draw) {
  const host = el('div', {});
  const status = el('span', { class: 'field-note', text: 'Loading…' });
  root.append(card(title, status, host));
  try {
    status.textContent = (await draw(host)) || '';
  } catch (error) {
    host.replaceChildren(gap(error.message));
    status.textContent = '';
  }
}

const NEW_PANELS = new Set(['moves', 'credit']);

// The company's equity-implied default risk (CREDIT): its distance to default, the
// model's probability and where today sits in its own five years. A description, not
// a warning; the note says what it is not.
export function creditSummary(row) {
  if (!row) return null;
  const pdText = row.pd_1y == null ? DASH : `${num(row.pd_1y, row.pd_1y < 0.1 ? 2 : 1)}%`;
  return [
    ['DISTANCE TO DEFAULT', row.dd == null ? DASH : num(row.dd, 2), 'lower is riskier; under 2 is thin'],
    ['MODEL 1Y PD', pdText, 'the model\'s own odds, not a market price'],
    ['OWN 5Y HISTORY', row.own_percentile == null ? DASH : `${num(row.own_percentile, 0)}th`, 'low = closer to default than usual'],
    ['DEBT COUNTED', row.counted_debt_bn == null ? DASH : `$${num(row.counted_debt_bn, 1)}B`, 'as filed, last 10-Q/10-K'],
  ];
}

function creditCard(symbol, credit) {
  const title = 'CREDIT · EQUITY-IMPLIED DEFAULT RISK';
  if (!credit) return null;
  const row = (credit.rows || []).find((r) => r.ticker === symbol);
  if (!row) {
    const why = credit.skipped?.[symbol] || ((credit.excluded_sectors || []).length ? 'a bank or insurer, or not measured' : 'not measured');
    return card(title, null, gap(`${symbol}: ${why}.`));
  }
  const chart = el('div', { class: 'chart short' });
  const path = row.monthly || { dates: [], dd: [] };
  if (path.dates.length) queueMicrotask(() => multiLine(chart, path.dates, { 'distance to default, month end': path.dd }));
  return card(title, el('span', { class: 'dim', text: `as of ${credit.as_of}` }), [
    el('div', { class: 'stat-strip' }, creditSummary(row).map(([label, value, note]) => stat(label, value, note))),
    row.debt_check ? el('div', { class: 'notice', text: `Check: ${row.debt_check}.` }) : null,
    path.dates.length ? chart : null,
    el('div', { class: 'field-note', text: credit.method || '' }),
  ]);
}

// The page under its header, in sub-tabs: the reports (what is new and the next
// one), the price and the moves that made it, the valuation in full, the filed statements.
// REPORTS joins what is new since the last report and the next report. The old
// RECENT and REPORT views still open it, so links made before the merge work.
export const TICKER_TABS = [['reports', 'REPORTS'], ['price', 'PRICE'], ['valuation', 'VALUATION'], ['financials', 'FINANCIALS']];
const LEGACY_VIEWS = { RECENT: 'reports', REPORT: 'reports' };

// The hash's argument -> { symbol, view }: NVDA/PRICE. An unknown view is REPORTS.
export function tickerArg(arg) {
  const [symbol, view] = String(arg || '').split('/');
  const key = (view || '').toUpperCase();
  const known = LEGACY_VIEWS[key] || TICKER_TABS.find(([id]) => id.toUpperCase() === key)?.[0];
  return { symbol: symbol || null, view: known || 'reports' };
}
// The default view is left out of the hash.
export function tickerArgFor(symbol, view) {
  return view && view !== 'reports' ? `${symbol}/${view.toUpperCase()}` : symbol;
}

export default async function renderTicker(root, valuation, manifest, ctx) {
  const [monitor, technicals, financials, dcf, crossListing, evidence, events, themes, chain, sectors, moves, credit] = await Promise.all(
    ['monitor', 'technicals', 'financials', 'dcf', 'cross_listing', 'evidence', 'events', 'themes', 'chain', 'sectors', 'moves', 'credit']
      // MOVES and CREDIT are new: asked for only when this build made them (a 404 fails the smoke test).
      .map((name) => (NEW_PANELS.has(name) && !manifest?.panels?.includes(name) ? null : optional(ctx, name))),
  );
  const rows = valuation?.rows || [];
  const universe = new Map(rows.map((r) => [r.ticker, r.name]));
  (technicals?.available || []).forEach((t) => { if (!universe.has(t)) universe.set(t, ''); });

  const asked = tickerArg(ctx.arg);
  const symbol = resolveTicker(asked.symbol, (t) => universe.has(t)) || (universe.has('AAPL') ? 'AAPL' : rows[0]?.ticker);
  if (symbol && tickerArgFor(symbol, asked.view) !== ctx.arg) ctx.setArg(tickerArgFor(symbol, asked.view));
  const row = rows.find((r) => r.ticker === symbol) || null;
  const mon = (monitor?.rows || []).find((r) => r.ticker === symbol) || null;
  const name = row?.name || mon?.name || '';

  root.append(sectionTitle(`${symbol}${name ? ` · ${name}` : ''}`,
    [row?.sector || mon?.sector, row?.indices?.join(' + ') || (mon?.membership === 'watchlist' ? 'watchlist' : null)]
      .filter(Boolean).join(' · ')));
  root.append(card('COMPANY', null, [searchRow(symbol, universe, ctx), links(symbol, { mon, dcf, pairs: crossListing?.pairs || [] }),
    themeTags(themes?.membership?.[symbol], themes?.member_corr)]));

  if (!universe.has(symbol) && !mon) {
    root.append(gap(`${symbol} is not covered by this build: it is not an index member, a watchlist name or a baked ticker.`));
    return;
  }

  const [eventPayload, prices] = await Promise.all([loadEvents(symbol), loadPrices(symbol)]);
  const asOf = events?.as_of || eventPayload?.as_of;
  const ev = evidence?.names?.[symbol] || null;
  const sit = situation(eventPayload, row, prices);
  const stats = headerStats(row, mon, sit, ev?.options?.implied_move);
  if (stats) root.append(stats);
  const company = Boolean(row || mon);
  const keep = (...nodes) => nodes.filter(Boolean);

  // What is new: a report the last session traded on, the evidence listed for
  // and against, the industry data since the last report, recent filings.
  const whatsNew = () => {
    const move = moves ? moveCard((moves.rows || []).find((r) => r.ticker === symbol), moves) : null;
    const pair = [company ? evidenceCard(mon, ev) : null, eventPayload ? filingsCard(eventPayload) : null].filter(Boolean);
    return keep(move, eventPayload ? outcomeCard(eventPayload) : null, company ? noteCard(mon) : null,
      pair.length > 1 ? el('div', { class: 'grid two' }, pair) : pair[0], eventPayload ? sinceCard(eventPayload) : null);
  };
  // The next report: what is expected and priced, what is ahead, and the
  // record behind it, folded. Empty when the build has no report data.
  const nextReport = () => {
    const upcoming = eventPayload ? eventCard(eventPayload, asOf, { prices }) : null;
    if (!upcoming && !eventPayload?.timeline) return [];
    return keep(upcoming, eventPayload ? timelineCard(eventPayload, prices, events?.macro, asOf) : null,
      fold('LAST 8 REPORTS · EPS, GUIDE, MOVE AND DRIFT', eventPayload ? historyCard(eventPayload) : null),
      fold('ESTIMATE REVISIONS BY PERIOD', eventPayload ? revisionsCard(eventPayload) : null),
      optionsCard(symbol, ev, evidence || {}));
  };
  // One page for both: what is new, then the next report, each under a small
  // sub-heading. A part with nothing in it is left out; neither gives one gap.
  const reportsPane = () => {
    const news = whatsNew();
    const next = nextReport();
    const parts = [];
    if (news.length) parts.push(subhead("WHAT'S NEW"), ...news);
    if (next.length) parts.push(subhead('NEXT REPORT'), ...next);
    return parts.length ? parts : [gap(`Nothing recent and no report data for ${symbol} in this build.`)];
  };
  // The price: its trend, the reports and large moves that made it, its AI-chain links.
  const pricePane = async (host) => {
    if (!company) {
      host.append(el('div', { class: 'notice', text:
        `${symbol} has baked prices but no filings in this build (a fund, an index or a non-member), so only its technicals are shown. `
        + 'A fund\'s holdings are on TOOLS → ETF X-RAY.' }));
    }
    if (technicals?.available?.includes(symbol)) {
      const chartHost = el('div', {});
      host.append(chartHost);
      await renderSingleTicker(chartHost, technicals, { symbol, lockTicker: true, compact: true });
    } else {
      host.append(card('PRICE & TREND', null, gap(`${symbol} has no baked price history in this build.`)));
    }
    host.append(...keep(eventPayload ? storyCard(eventPayload) : null, chain ? chainCard(chain, symbol, { compact: true }) : null));
    return null;
  };
  // The valuation: the VALUATION block against its sector (its trailing P/E band
  // switches between operating and reported), the earnings and forward P/E, and
  // the multiples against the sector median.
  const valuationPane = async (host) => {
    if (!company) return [gap(`${symbol} has no filings in this build, so no valuation.`)];
    // A failure here blanks this block only, as the other sections of this page do.
    if (row) {
      try {
        host.append(...await companyValuation(ctx, symbol, row, sectors, financials));
      } catch (error) {
        host.append(card('VALUATION', null, gap(error.message)));
      }
      await section(host, 'EARNINGS & FORWARD P/E', (inner) => renderEarningsForward(inner, symbol, valuation));
    }
    host.append(valuationCard(symbol, row, valuation));
    const creditNode = creditCard(symbol, credit);
    if (creditNode) host.append(creditNode);
    return null;
  };
  const financialsPane = async (host) => {
    if (!company) return [gap(`${symbol} has no filed statements: it is a fund, an index or a non-member.`)];
    await section(host, 'FINANCIALS — FILED ANNUAL STATEMENTS · SEC XBRL', (inner) => {
      if (!financials) throw new Error('FINANCIALS was not built for this session.');
      if (!financials.available.some((c) => c.ticker === symbol)) {
        const why = financials.skipped?.[symbol];
        throw new Error(`${symbol} has no filed statements in this build${why ? `: ${why}` : ' (not a member of the covered indices)'}`);
      }
      return renderStatements(inner, symbol, financials);
    });
    return null;
  };
  const builders = { reports: reportsPane, price: pricePane, valuation: valuationPane, financials: financialsPane };
  const tabs = viewTabs(TICKER_TABS, asked.view, {
    label: `${symbol} views`,
    idPrefix: 'ticker',
    build: (id, host) => builders[id](host),
    onPick: (id) => ctx.setArg(tickerArgFor(symbol, id)),
  });
  root.append(tabs.nav, ...tabs.panes);
  await tabs.show(asked.view);
}
