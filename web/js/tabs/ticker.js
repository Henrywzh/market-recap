// TICKER: one company on one page, reached from any ticker on the site.
//
// Nothing here is computed afresh. Each section is the panel that already
// owns the figure (MONITOR's evidence, VALUATION's P/E history, FINANCIALS'
// statements, TECHNICALS' single-ticker readings), drawn for one name. A
// section whose artifact does not cover the name says so and the rest of the
// page still renders.

import { el, card, table, num, pct, dirClass, sectionTitle, gap, DASH } from '../fmt.js';
import { renderPeHistory } from './valuation.js';
import { renderStatements } from './financials.js';
import { renderSingleTicker } from './technicals.js';

const BILLION = 1e9;
// The multiples shown in the header block, in this order. The full set is on
// SCREEN; these are the ones a first look needs.
const KEY_METRICS = ['pe', 'ev_ebitda', 'fcf_yield', 'shareholder_yield', 'roic', 'operating_margin',
  'revenue_growth', 'net_debt_ebitda', 'piotroski'];

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

function headerStats(symbol, row, mon) {
  const stats = [];
  if (row) {
    stats.push(stat('CLOSE', row.price === null || row.price === undefined ? DASH : `$${num(row.price)}`,
      row.market_cap ? `mkt cap $${num(row.market_cap / BILLION, 1)}B` : null));
  }
  if (mon) {
    stats.push(stat('FROM 1Y HIGH', pct(mon.drawdown_pct, 1), `as of ${mon.price_as_of || DASH}`, dirClass(mon.drawdown_pct)));
    stats.push(stat('1M VS SECTOR PEERS', mon.peer_excess_pct === null || mon.peer_excess_pct === undefined
      ? DASH : `${mon.peer_excess_pct > 0 ? '+' : ''}${num(mon.peer_excess_pct, 1)} pp`,
    `${mon.peer_count || 0} peers, company excluded`, dirClass(mon.peer_excess_pct)));
    stats.push(stat('MONITOR', mon.candidate ? 'QUEUED' : 'NOT QUEUED',
      mon.candidate ? `price ${mon.price_state || '?'} · evidence ${mon.evidence_state || '?'}` : null));
    const timing = mon.earnings_status && mon.earnings_status !== 'not_scheduled' ? mon.earnings_status.replace(/_/g, ' ') : null;
    stats.push(stat('NEXT EARNINGS', mon.earnings_date || DASH, mon.earnings_date ? timing : 'none on the calendar'));
  }
  if (row) {
    stats.push(stat('P/E VS OWN 10Y', row.pe_percentile === null || row.pe_percentile === undefined ? DASH : `${ordinal(row.pe_percentile)} pct`,
      row.pe_vs_median === null || row.pe_vs_median === undefined ? null : `${row.pe_vs_median > 0 ? '+' : ''}${num(row.pe_vs_median, 0)}% vs median`));
  }
  return stats.length ? el('div', { class: 'stat-strip' }, stats) : null;
}

function links(symbol, { mon, dcf, pairs }) {
  const items = [
    ['TECHNICALS TOOL', `#technicals/${encodeURIComponent(symbol)}`],
    ['P/E ON SCREEN', `#valuation/${encodeURIComponent(symbol)}`],
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

function evidenceCard(mon) {
  if (!mon) return card('EVIDENCE', null, gap('MONITOR does not cover this ticker in this build.'));
  const list = (items, cls) => (items && items.length
    ? el('ul', { class: 'evidence-list' }, items.map((text) => el('li', { class: cls, text })))
    : el('div', { class: 'dim', text: 'none' }));
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
    el('div', { class: 'card-title', text: 'FOR' }), list(mon.evidence_for, 'up'),
    el('div', { class: 'card-title', text: 'AGAINST' }), list(mon.evidence_against, 'down'),
    el('div', { class: 'note-text', text: revision }),
    reported ? el('div', { class: 'note-text', text: reported }) : null,
  ]);
}

function valuationCard(symbol, row, data) {
  if (!row) return card('VALUATION & QUALITY', null, gap(`${symbol} is not on SCREEN in this build (not an index member, or no usable filings).`));
  const byKey = new Map(data.metrics.map((m) => [m.key, m]));
  const peers = data.rows.filter((r) => r.sector === row.sector);
  const rows = KEY_METRICS.filter((key) => byKey.has(key)).map((key) => {
    const metric = byKey.get(key);
    return el('tr', {}, [
      el('td', { text: metric.label }),
      el('td', { text: format(row[key], metric.unit) }),
      el('td', { class: 'dim', text: format(median(peers.map((r) => r[key])), metric.unit) }),
    ]);
  });
  return card(`VALUATION & QUALITY — AGAINST ${row.sector?.toUpperCase() || 'SECTOR'} MEDIAN (${peers.length} COMPANIES)`, null, [
    table(['METRIC', symbol, 'SECTOR MEDIAN'], rows),
    el('div', { class: 'field-note', text: `TTM to ${row.period_end} · filed ${row.filed} · full table on SCREEN` }),
  ]);
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

export default async function renderTicker(root, valuation, _manifest, ctx) {
  const [monitor, technicals, financials, dcf, crossListing] = await Promise.all(
    ['monitor', 'technicals', 'financials', 'dcf', 'cross_listing'].map((name) => optional(ctx, name)),
  );
  const rows = valuation?.rows || [];
  const universe = new Map(rows.map((r) => [r.ticker, r.name]));
  (technicals?.available || []).forEach((t) => { if (!universe.has(t)) universe.set(t, ''); });

  const symbol = ctx.arg || (universe.has('AAPL') ? 'AAPL' : rows[0]?.ticker);
  if (!ctx.arg && symbol) ctx.setArg(symbol);
  const row = rows.find((r) => r.ticker === symbol) || null;
  const mon = (monitor?.rows || []).find((r) => r.ticker === symbol) || null;
  const name = row?.name || mon?.name || '';

  root.append(sectionTitle(`${symbol}${name ? ` · ${name}` : ''}`,
    [row?.sector || mon?.sector, row?.indices?.join(' + ') || (mon?.membership === 'watchlist' ? 'watchlist' : null)]
      .filter(Boolean).join(' · ')));
  root.append(card('COMPANY', null, [searchRow(symbol, universe, ctx), links(symbol, { mon, dcf, pairs: crossListing?.pairs || [] })]));

  if (!universe.has(symbol) && !mon) {
    root.append(gap(`${symbol} is not covered by this build: it is not an index member, a watchlist name or a baked ticker.`));
    return;
  }

  const stats = headerStats(symbol, row, mon);
  if (stats) root.append(stats);
  // Company sections need filings. A fund, an index or a name no index holds
  // gets its price readings and one line saying why the rest is absent.
  // Order: the price first, then what it is worth against its own history,
  // then against its sector and the evidence, then the filings behind it.
  const company = Boolean(row || mon);
  const note = company ? noteCard(mon) : null;
  if (note) root.append(note);
  if (!company) {
    root.append(el('div', { class: 'notice', text:
      `${symbol} has baked prices but no filings in this build (a fund, an index or a non-member), so only its technicals are shown. `
      + 'A fund\'s holdings are on TOOLS → ETF X-RAY.' }));
  }
  if (technicals?.available?.includes(symbol)) {
    const host = el('div', {});
    root.append(host);
    await renderSingleTicker(host, technicals, { symbol, lockTicker: true, compact: true });
  } else {
    root.append(card('PRICE & TREND', null, gap(`${symbol} has no baked price history in this build.`)));
  }
  if (row) {
    await section(root, 'P/E AGAINST ITS OWN 10 YEARS', (host) => {
      if (!row.pe_history) throw new Error(`${symbol} has no P/E history in this build (a loss, too little history, or no EPS filed)`);
      return renderPeHistory(host, symbol, valuation);
    });
  }
  if (company) {
    root.append(el('div', { class: 'grid two' }, [valuationCard(symbol, row, valuation), evidenceCard(mon)]));
  }
  if (!company) return;
  await section(root, 'FINANCIALS — FILED ANNUAL STATEMENTS · SEC XBRL', (host) => {
    if (!financials) throw new Error('FINANCIALS was not built for this session.');
    if (!financials.available.some((c) => c.ticker === symbol)) {
      const why = financials.skipped?.[symbol];
      throw new Error(`${symbol} has no filed statements in this build${why ? `: ${why}` : ' (not a member of the covered indices)'}`);
    }
    return renderStatements(host, symbol, financials);
  });
}
