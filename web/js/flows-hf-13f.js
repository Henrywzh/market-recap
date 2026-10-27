// FLOWS · HEDGE FUNDS 13F CROWDING: which of the curated hedge funds hold which
// S&P 500 names, read from their quarterly 13F-HR filings. The filings are
// about 45 days old when they first appear, so the quarter is printed from the
// build, not assumed here. The pure helpers are what the tests check; section()
// turns the build's section dict into cards. A missing figure is a dash, never a zero.

import { el, card, num, table, gap, DASH } from './fmt.js';
import { render } from './charts.js';
import { tickerHref } from './routes.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const MINUS = '−';
const TITLE = 'HEDGE FUNDS · 13F CROWDING';

// "+$3.66bn", "−$310m": a dollar change in shares valued at the latest close.
export function dollarsText(v) {
  if (!present(v)) return DASH;
  const sign = v > 0 ? '+' : v < 0 ? MINUS : '';
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${sign}$${num(abs / 1e9, 2)}bn`;
  return `${sign}$${num(abs / 1e6, 0)}m`;
}

// "+2", "−5", "0": a change in the number of funds. Zero is a real zero here.
export function holdersText(n) {
  if (!present(n)) return DASH;
  if (n > 0) return `+${n}`;
  if (n < 0) return `${MINUS}${Math.abs(n)}`;
  return '0';
}

// Share of a total, one decimal. Absence stays a dash.
export function percentText(v) {
  return present(v) ? `${num(v, 1)}%` : DASH;
}

// Crowding ratio: how far the funds' weight runs ahead of the index weight.
export function ratioText(v) {
  return present(v) ? `${num(v, 2)}×` : DASH;
}

// Tilt in percentage points, signed.
export function tiltText(v) {
  if (!present(v)) return DASH;
  const sign = v > 0 ? '+' : v < 0 ? MINUS : '';
  return `${sign}${num(Math.abs(v), 1)} pts`;
}

// Options are counted apart from the longs, so they get their own line.
export function optionsText(options) {
  if (!options) return DASH;
  const puts = present(options.put_value_bn) ? `$${num(options.put_value_bn, 1)}bn` : DASH;
  const calls = present(options.call_value_bn) ? `$${num(options.call_value_bn, 1)}bn` : DASH;
  return `puts ${puts} across ${options.put_rows ?? DASH} lines · calls ${calls} across ${options.call_rows ?? DASH} lines`;
}

// The header line: funds read, value held, the filing deadline and the price date.
export function metaLine(data) {
  const filers = data.filers || {};
  const read = present(filers.read) ? `${filers.read} of ${filers.in_aggregate ?? DASH} funds filed` : DASH;
  const value = present(data.total_value_bn) ? `$${num(data.total_value_bn, 1)}bn of long equity` : DASH;
  const due = data.deadline ? `filings due ${data.deadline}` : DASH;
  const price = data.prices_as_of ? `adds and cuts at the ${data.prices_as_of} close` : DASH;
  return `${read} · ${value} · ${due} · ${price}`;
}

// The method fold: what is in the list, how each figure is built, and where it stops.
export function methodNotes(data) {
  const filers = data.filers || {};
  const names = (filers.list || []).map((f) => f.label).join(', ');
  const excluded = (filers.excluded_style || []).join(', ');
  const outside = data.outside_sp500 || {};
  return [
    `A proxy, not a census: ${filers.in_aggregate ?? DASH} curated managers (fundamental, growth and activist). Names: ${names || DASH}.`,
    excluded ? `Multi-strategy platforms left out of the default aggregate: ${excluded}.` : '',
    `${data.lag || 'Filings are due 45 days after quarter end.'} The quarter read is ${data.period_label || DASH}, its prior ${data.prior_label || DASH}.`,
    'Long equity only. Options are separate: reported amounts reflect underlying securities, not option premiums or delta exposure.',
    'Crowded names are ranked by the number of funds holding them, then by value. HF % is the share of the funds\' combined long dollars; S&P % is the index weight; the ratio is HF % over S&P %.',
    `S&P 500 weights are the SPY file's current weights, not quarter-end (as of ${data.sp_weight_as_of || DASH}). CUSIPs are matched to tickers through that file.`,
    `Adds and cuts are share changes among the ${data.moves?.common_funds ?? DASH} funds that filed both quarters, valued at one price so price moves do not count as buying.`,
    'Sector tilt is each sector\'s share of the funds\' S&P 500 holdings minus its share of the index, both taken over S&P 500 names alone.',
    `Outside the index: ${outside.names ?? DASH} names, ${percentText(outside.value_share_pct)} of value, not ranked.`,
    'Limits: quarter-end long holdings only; shorts, cash, private positions and many foreign securities are absent. Amendments and confidential positions are not fully reconciled. Changes are estimates, not observed trade cash flow.',
  ].filter(Boolean);
}

function crowdedTable(rows) {
  return table(['TICKER', 'FUNDS', 'VALUE', 'HF %', 'S&P %', 'RATIO'], rows.map((r) => el('tr', {}, [
    el('td', {}, [el('a', { href: tickerHref(r.ticker), text: r.ticker, title: r.sector || 'Unclassified' })]),
    el('td', { text: present(r.funds) ? String(r.funds) : DASH }),
    el('td', { text: present(r.value_bn) ? `$${num(r.value_bn, 2)}bn` : DASH }),
    el('td', { text: percentText(r.hf_pct) }),
    el('td', { text: percentText(r.sp_pct) }),
    el('td', { class: present(r.ratio) && r.ratio >= 1.5 ? 'up' : 'dim', text: ratioText(r.ratio) }),
  ])));
}

function movesTable(rows, heading) {
  const body = rows.length
    ? rows.map((r) => el('tr', {}, [
      el('td', {}, [el('a', { href: tickerHref(r.ticker), text: r.ticker })]),
      el('td', { class: r.d_holders > 0 ? 'up' : r.d_holders < 0 ? 'down' : 'dim', text: holdersText(r.d_holders) }),
      el('td', { class: r.d_value > 0 ? 'up' : r.d_value < 0 ? 'down' : 'dim', text: dollarsText(r.d_value) }),
    ]))
    : [el('tr', {}, [el('td', { colspan: '3', class: 'dim', text: 'None in this quarter.' })])];
  return el('div', { class: 'flows-13f-moves' }, [
    el('div', { class: 'stat-label', text: heading }),
    table(['TICKER', 'Δ FUNDS', 'Δ VALUE'], body),
  ]);
}

// Sector tilt, in percentage points: positive where the funds are heavier than the index.
export function tiltOption(rows, p) {
  const data = rows.filter((r) => present(r.tilt_pts));
  return {
    grid: { left: 150, right: 56, top: 8, bottom: 24, containLabel: false },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (x) => tiltText(x) },
    xAxis: { type: 'value', axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => num(v, 0) }, splitLine: { lineStyle: { color: p.border } } },
    yAxis: { type: 'category', inverse: true, data: data.map((r) => r.sector), axisLabel: { color: p.text, fontSize: 10 } },
    series: [{
      type: 'bar',
      data: data.map((r) => ({ value: r.tilt_pts, itemStyle: { color: r.tilt_pts >= 0 ? p.up : p.down } })),
    }],
  };
}

function tiltChart(rows) {
  const node = el('div', { class: 'chart flows-13f-tilt', 'aria-label': 'Hedge-fund sector tilt against the S&P 500, in percentage points' });
  // Drawn after the card is attached, so the chart measures a real box.
  const draw = () => render(node, (option, p) => ({ ...option, ...tiltOption(rows, p) }));
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(draw);
  else draw();
  return node;
}

export function section(data) {
  if (!data || data.unavailable) {
    const reason = data?.unavailable ? `: ${data.unavailable}` : '';
    return [card(TITLE, null, gap(`Not built this session${reason}.`))];
  }
  const title = `${TITLE} (${data.period_label || DASH})`;
  const crowded = Array.isArray(data.crowded) ? data.crowded : [];
  if (!crowded.length) return [card(title, null, gap('No S&P 500 holdings read for this quarter.'))];

  const moves = data.moves || {};
  const body = [
    el('div', { class: 'meta-line', text: metaLine(data) }),
    el('p', { class: 'field-note', text: 'Curated manager sample, reported up to 45 days after quarter-end. Holdings are long-only; share changes are estimates and do not measure net fund flows. Amendments are not fully reconciled.' }),
    el('div', { class: 'stat-label', text: 'MOST CROWDED S&P 500 NAMES (BY FUNDS HOLDING, THEN VALUE)' }),
    crowdedTable(crowded),
    data.quality?.share_changes_split_adjusted ? el('div', { class: 'flows-13f-pair' }, [
      movesTable(moves.adds || [], 'MOST ADDED (SHARES × LATEST CLOSE)'),
      movesTable(moves.cuts || [], 'MOST CUT (SHARES × LATEST CLOSE)'),
    ]) : gap('Estimated share changes withheld: split adjustment has not been verified for this build.'),
    el('div', { class: 'stat-label', text: 'SECTOR TILT: HEDGE FUNDS MINUS S&P 500 WEIGHT' }),
    Array.isArray(data.sector_tilt) && data.sector_tilt.length ? tiltChart(data.sector_tilt) : gap('No sector weights this build.'),
    el('div', { class: 'field-note', text: `Options, not in the longs above: ${optionsText(data.options)}.` }),
    el('details', { class: 'sx-fold' }, [
      el('summary', { text: 'Method & limits' }),
      ...methodNotes(data).map((text) => el('div', { class: 'method-copy', text })),
    ]),
  ];
  return [card(title, null, body)];
}

