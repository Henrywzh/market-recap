// ETF X-RAY: each fund looked through to its holdings, from the issuer's own
// file. Structure (concentration, sectors, countries, overlap, the day's
// attribution) is built nightly; the valuation look-through is joined here
// against the VALUATION tab's rows, so the two tabs cannot disagree.
//
// Every aggregate says how much of the fund it covers. A fund-level P/E over
// the 60% of a fund that could be matched is a claim about that 60%.

import { el, card, table, num, pct, dirClass, sectionTitle, notice, gap, DASH } from '../fmt.js';
import { render, SERIES_COLORS } from '../charts.js';

const XRAY_BASE = 'artifacts/xray';
const BENCHMARK = 'SPY';
const OVERLAP_ROWS = 8;
const STALE_HOLDINGS_DAYS = 7;
const DAY_MS = 86400000;
// Below this share of the fund matched to VALUATION rows, a look-through
// figure describes the few matched names, not the fund, so it is not shown.
// EFA's handful of US listings are 4% of it.
const MIN_COVERAGE = 0.5;

const funds = new Map();
function loadFund(ticker) {
  if (!funds.has(ticker)) {
    funds.set(ticker, fetch(`${XRAY_BASE}/${ticker}.json`, { cache: 'no-cache' }).then((response) => {
      if (!response.ok) throw new Error(`${ticker} has no holdings in this build`);
      return response.json();
    }));
  }
  return funds.get(ticker);
}

function stat(label, value, note, cls) {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls || ''}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

const share = (value, digits = 1) => (value === null || value === undefined ? DASH : `${num(value * 100, digits)}%`);

// --- Look-through valuation ------------------------------------------------
// Multiples aggregate the way an index's do: total earnings over total price,
// losses included, so a fund's P/E is 1 / its weighted earnings yield rather
// than an average of P/Es (which a loss-maker cannot enter and a near-zero
// earner dominates).
const LOOK_THROUGH = [
  { key: 'pe', label: 'P/E (TTM)', unit: 'x', from: 'earnings_yield', inverse: true },
  { key: 'pb', label: 'P / Book', unit: 'x', from: 'book_yield', inverse: true },
  { key: 'roe', label: 'ROE (earnings / book)', unit: 'pct', ratio: ['earnings_yield', 'book_yield'] },
  { key: 'fcf_yield', label: 'FCF yield', unit: 'pct', from: 'fcf_yield', note: 'ex banks' },
  { key: 'dividend_yield', label: 'Dividend yield', unit: 'pct', from: 'dividend_yield' },
  { key: 'revenue_growth', label: 'Revenue growth (TTM y/y)', unit: 'pct', from: 'revenue_growth' },
  { key: 'operating_margin', label: 'Operating margin', unit: 'pct', from: 'operating_margin', note: 'ex banks' },
];

function weightedMean(holdings, rows, field) {
  let sum = 0;
  let weight = 0;
  holdings.symbol.forEach((symbol, i) => {
    const value = rows.get(symbol)?.[field];
    if (value === null || value === undefined) return;
    sum += holdings.weight[i] * value;
    weight += holdings.weight[i];
  });
  return weight > 0 ? { value: sum / weight, weight } : { value: null, weight: 0 };
}

function lookThrough(fund, rows) {
  const total = fund.holdings.weight.reduce((a, b) => a + b, 0);
  const out = {};
  for (const metric of LOOK_THROUGH) {
    let value = null;
    let covered = 0;
    if (metric.ratio) {
      const [top, bottom] = metric.ratio;
      const paired = { symbol: [], weight: [] };
      fund.holdings.symbol.forEach((s, i) => {
        const row = rows.get(s);
        if (row && row[top] !== null && row[top] !== undefined && row[bottom] !== null && row[bottom] !== undefined) {
          paired.symbol.push(s);
          paired.weight.push(fund.holdings.weight[i]);
        }
      });
      const a = weightedMean(paired, rows, top);
      const b = weightedMean(paired, rows, bottom);
      value = a.value !== null && b.value > 0 ? (a.value / b.value) * 100 : null;
      covered = a.weight;
    } else {
      const mean = weightedMean(fund.holdings, rows, metric.from);
      covered = mean.weight;
      value = metric.inverse ? (mean.value > 0 ? 100 / mean.value : null) : mean.value;
    }
    const fraction = total > 0 ? covered / total : 0;
    out[metric.key] = { value: fraction >= MIN_COVERAGE ? value : null, covered: fraction };
  }
  return out;
}

function formatMetric(value, unit) {
  if (value === null || value === undefined) return DASH;
  return unit === 'x' ? `${num(value, 1)}x` : `${num(value, 1)}%`;
}

function valuationTable(ticker, mine, benchmark) {
  const compare = benchmark && ticker !== BENCHMARK;
  const headers = ['METRIC', ticker, ...(compare ? [BENCHMARK] : []), 'COVERS'];
  const rows = LOOK_THROUGH.map((metric) => el('tr', {}, [
    el('td', { text: metric.label + (metric.note ? ` (${metric.note})` : '') }),
    el('td', { text: formatMetric(mine[metric.key].value, metric.unit) }),
    ...(compare ? [el('td', { class: 'dim', text: formatMetric(benchmark[metric.key].value, metric.unit) })] : []),
    el('td', { class: 'dim', text: share(mine[metric.key].covered, 0) }),
  ]));
  return table(headers, rows);
}

// --- Charts ------------------------------------------------------------------

function weightBars(node, labels, series) {
  render(node, (option, p) => ({
    ...option,
    grid: { left: 150, right: 40, top: 8, bottom: series.length > 1 ? 30 : 12 },
    tooltip: { ...option.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' },
      valueFormatter: (v) => (v === null || v === undefined ? DASH : `${num(v, 1)}%`) },
    legend: series.length > 1
      ? { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 }
      : undefined,
    xAxis: { ...option.yAxis, type: 'value', scale: false, axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => `${v}%` } },
    yAxis: { ...option.xAxis, type: 'category', inverse: true, data: labels, boundaryGap: true,
      axisLabel: { color: p.dim, fontSize: 10, width: 140, overflow: 'truncate' } },
    series: series.map((s, i) => ({
      name: s.name, type: 'bar', data: s.values, barMaxWidth: 10, barGap: '15%',
      itemStyle: { color: s.color || SERIES_COLORS[i] },
    })),
  }));
}

function chartNode(rows) {
  return el('div', { class: 'chart', style: `height:${Math.max(140, rows * 22 + 40)}px` });
}

function breakdownChart(title, fund, benchmark, field) {
  const mine = fund[field] || [];
  if (!mine.length) return null;
  const labels = mine.map((row) => row.label);
  const series = [{ name: fund.ticker, values: mine.map((row) => row.weight * 100) }];
  if (benchmark && benchmark.ticker !== fund.ticker && (benchmark[field] || []).length) {
    const theirs = new Map(benchmark[field].map((row) => [row.label, row.weight]));
    series.push({ name: benchmark.ticker, values: labels.map((l) => (theirs.has(l) ? theirs.get(l) * 100 : 0)), color: '#94a3b8' });
  }
  const node = chartNode(labels.length);
  return { node, draw: () => weightBars(node, labels, series), card: card(title, null, node) };
}

// --- Sections ----------------------------------------------------------------

function holdingsAge(fund, asOf) {
  if (!fund.holdings_as_of || !asOf) return null;
  const days = Math.round((new Date(asOf) - new Date(fund.holdings_as_of)) / DAY_MS);
  return days > STALE_HOLDINGS_DAYS ? `${days} days before the prices` : null;
}

function topTable(fund) {
  const hasCountry = fund.top.some((h) => h.country);
  const headers = ['#', 'TICKER', 'NAME', 'WEIGHT', 'SECTOR', ...(hasCountry ? ['COUNTRY'] : []), '1D', 'CONTRIB (PP)'];
  const rows = fund.top.map((h, i) => el('tr', {}, [
    el('td', { class: 'dim', text: String(i + 1) }),
    el('td', { text: h.symbol }),
    el('td', { class: 'dim', text: h.name || DASH }),
    el('td', { text: share(h.weight, 2) }),
    el('td', { class: 'dim', text: h.sector || DASH }),
    ...(hasCountry ? [el('td', { class: 'dim', text: h.country || DASH })] : []),
    el('td', { class: dirClass(h.return_1d), text: pct(h.return_1d) }),
    el('td', { class: dirClass(h.contribution_1d), text: h.contribution_1d === null ? DASH : num(h.contribution_1d, 3) }),
  ]));
  return table(headers, rows);
}

function attributionCard(fund) {
  const a = fund.attribution_1d;
  const lines = (list) => list.map((x) => el('tr', {}, [
    el('td', { text: x.symbol }),
    el('td', { class: dirClass(x.contribution), text: num(x.contribution, 3) }),
  ]));
  const body = a.priced
    ? [
      el('div', { class: 'field-note', text:
        `Priced holdings are ${share(a.covered_weight, 0)} of the fund and explain ${num(a.sum, 2)} pp `
        + `of its ${pct(a.fund_return)} day.` }),
      el('div', { class: 'grid two' }, [
        table(['LEADER', 'PP'], lines(a.leaders)),
        table(['LAGGARD', 'PP'], lines(a.laggards)),
      ]),
    ]
    : [el('div', { class: 'field-note', text:
      'None of this fund\'s holdings are priced by this build (it prices S&P 500 and Nasdaq-100 members), '
      + 'so its day is not attributed.' })];
  return card('1D ATTRIBUTION', null, body);
}

function overlapCard(data, ticker) {
  const { tickers, matrix } = data.overlap;
  const i = tickers.indexOf(ticker);
  if (i < 0) return null;
  const rows = tickers
    .map((other, j) => ({ other, value: matrix[i][j] }))
    .filter((r) => r.other !== ticker)
    .sort((a, b) => b.value - a.value)
    .slice(0, OVERLAP_ROWS)
    .map((r) => el('tr', {}, [el('td', { text: r.other }), el('td', { text: share(r.value, 0) })]));
  return card('OVERLAP WITH OTHER FUNDS', null, [
    el('div', { class: 'field-note', text: 'Sum of the smaller weight of each common holding.' }),
    table(['FUND', 'OVERLAP'], rows),
  ]);
}

function equityView(host, data, fund, benchmark, rows) {
  const draws = [];
  const a = fund.attribution_1d;
  const age = holdingsAge(fund, data.as_of);
  const cash = fund.provider === 'vanguard' ? null : 1 - fund.equity_weight;
  host.append(el('div', { class: 'stat-strip' }, [
    stat('HOLDINGS', num(fund.lines, 0), `as of ${fund.holdings_as_of}${age ? ` · ${age}` : ''}`, age ? 'down' : ''),
    stat('TOP 10 WEIGHT', share(fund.top10_weight), 'of the fund'),
    stat('EFFECTIVE N', num(fund.effective_n, 0), '1 / sum of squared weights'),
    stat('CASH & OTHER', cash === null ? DASH : share(cash), cash === null ? 'Vanguard lists stock holdings only' : 'lines that are not listed equity'),
    stat('1D', pct(a.fund_return), `fund close · holdings priced explain ${num(a.sum, 2)} pp`, dirClass(a.fund_return)),
  ]));

  const mine = lookThrough(fund, rows);
  const theirs = benchmark && benchmark.ticker !== fund.ticker ? lookThrough(benchmark, rows) : null;
  const sectors = breakdownChart('SECTOR WEIGHTS (%)', fund, benchmark, 'sectors');
  host.append(el('div', { class: 'grid two' }, [
    card('LOOK-THROUGH VALUATION & QUALITY', null, [
      el('div', { class: 'field-note', text:
        'Aggregated like an index: total earnings over total price, losses included. '
        + 'COVERS is the share of the fund matched to a VALUATION row (S&P 500 and Nasdaq-100 '
        + `members); under ${MIN_COVERAGE * 100}% the figure is not shown.` }),
      valuationTable(fund.ticker, mine, theirs),
    ]),
    sectors ? sectors.card : gap('No sector labels for this fund.'),
  ]));
  if (sectors) draws.push(sectors.draw);

  const countries = fund.countries && fund.countries.length > 1 ? breakdownChart('COUNTRY WEIGHTS (%)', fund, null, 'countries') : null;
  host.append(el('div', { class: 'grid two' }, [
    card(`TOP ${fund.top.length} HOLDINGS`, null, topTable(fund)),
    el('div', {}, [attributionCard(fund), overlapCard(data, fund.ticker), countries?.card].filter(Boolean)),
  ]));
  if (countries) draws.push(countries.draw);
  return draws;
}

function bondView(host, data, fund) {
  const draws = [];
  host.append(el('div', { class: 'stat-strip' }, [
    stat('HOLDINGS', num(fund.lines, 0), `as of ${fund.holdings_as_of}`),
    stat('DURATION', `${num(fund.duration, 2)}y`, `weighted, ${share(fund.duration_covered, 0)} of the fund`),
    stat('YIELD TO MATURITY', `${num(fund.ytm, 2)}%`, 'weighted by market value'),
    stat('COUPON', `${num(fund.coupon, 2)}%`),
    stat('AVG MATURITY', `${num(fund.maturity_years, 1)}y`, 'dated lines'),
  ]));
  const buckets = { node: chartNode(fund.maturity_buckets.length) };
  const labels = fund.maturity_buckets.map((b) => b.label);
  draws.push(() => weightBars(buckets.node, labels, [{ name: fund.ticker, values: fund.maturity_buckets.map((b) => b.weight * 100) }]));
  const sectors = breakdownChart('SECTOR WEIGHTS (%)', fund, null, 'sectors');
  host.append(el('div', { class: 'grid two' }, [
    card('REMAINING MATURITY (%)', null, [
      el('div', { class: 'field-note', text:
        'Stated final maturity. Mortgage pools are listed at 30 years but pay down much sooner; '
        + 'duration is the better measure of rate exposure.' }),
      buckets.node,
    ]),
    sectors ? sectors.card : gap('No sector labels for this fund.'),
  ]));
  if (sectors) draws.push(sectors.draw);
  const rows = fund.top.map((h, i) => el('tr', {}, [
    el('td', { class: 'dim', text: String(i + 1) }),
    el('td', { text: h.name || DASH }),
    el('td', { class: 'dim', text: h.sector || DASH }),
    el('td', { text: share(h.weight, 2) }),
    el('td', { text: h.coupon === null ? DASH : `${num(h.coupon, 3)}%` }),
    el('td', { class: 'dim', text: h.maturity || DASH }),
    el('td', { text: h.duration === null ? DASH : num(h.duration, 2) }),
    el('td', { text: h.ytm === null ? DASH : `${num(h.ytm, 2)}%` }),
  ]));
  host.append(card(`LARGEST ${fund.top.length} LINES`, null,
    table(['#', 'ISSUE', 'SECTOR', 'WEIGHT', 'COUPON', 'MATURITY', 'DURATION', 'YTM'], rows)));
  return draws;
}

function summaryTable(data, onPick) {
  const rows = data.funds.map((f) => el('tr', {
    class: f.status === 'ok' ? '' : 'dim',
    style: f.status === 'ok' ? 'cursor:pointer' : null,
    onclick: f.status === 'ok' ? () => onPick(f.ticker) : null,
  }, [
    el('td', { text: f.ticker }),
    el('td', { class: 'dim', text: f.group }),
    el('td', { class: 'dim', text: f.status === 'ok' ? f.provider_label : f.reason }),
    el('td', { text: f.holdings_as_of || DASH }),
    el('td', { text: f.lines === undefined ? DASH : num(f.lines, 0) }),
    el('td', { text: f.kind === 'equity' ? share(f.top10_weight) : DASH }),
    el('td', { text: f.kind === 'equity' ? num(f.effective_n, 0) : DASH }),
    el('td', { text: f.kind === 'bond' ? `${num(f.duration, 2)}y` : DASH }),
    el('td', { text: f.kind === 'bond' ? `${num(f.ytm, 2)}%` : DASH }),
  ]));
  return table(['FUND', 'GROUP', 'HOLDINGS SOURCE', 'AS OF', 'LINES', 'TOP 10', 'EFF. N', 'DURATION', 'YTM'], rows);
}

export default async function renderXray(root, data) {
  root.append(sectionTitle('ETF X-RAY', 'LOOK-THROUGH FROM EACH ISSUER\'S HOLDINGS FILE'));
  if (!data.funds || !data.funds.length) {
    root.append(gap('No fund holdings in this build.'));
    return;
  }

  const available = data.funds.filter((f) => f.status === 'ok');
  const picker = el('div', { class: 'period-switch', style: 'flex-wrap:wrap' });
  const host = el('div', {});
  const status = el('span', { class: 'field-note', text: '' });
  const valuation = fetch('artifacts/valuation.json', { cache: 'no-cache' })
    .then((response) => (response.ok ? response.json() : { rows: [] }))
    .then((v) => new Map((v.rows || []).map((row) => [row.ticker, row])))
    .catch(() => new Map());

  available.forEach((f) => picker.append(el('button', {
    type: 'button', text: f.ticker, 'aria-pressed': 'false', onclick: () => show(f.ticker),
  })));

  root.append(card('FUND', status, [picker]));
  root.append(host);
  root.append(card('ALL FUNDS', null, summaryTable(data, (t) => show(t))));
  root.append(notice(data.note));

  async function show(ticker) {
    [...picker.children].forEach((b) => b.setAttribute('aria-pressed', String(b.textContent === ticker)));
    status.textContent = `Loading ${ticker}…`;
    try {
      const [fund, rows, benchmark] = await Promise.all([
        loadFund(ticker),
        valuation,
        loadFund(BENCHMARK).catch(() => null),
      ]);
      host.innerHTML = '';
      const meta = data.funds.find((f) => f.ticker === ticker);
      host.append(sectionTitle(ticker, `${meta.group} · ${meta.provider_label}`), el('div', { class: 'field-note' }, [
        el('a', { href: meta.source_url, target: '_blank', rel: 'noopener', text: 'issuer holdings file' }),
      ]));
      const draws = fund.kind === 'bond'
        ? bondView(host, data, fund)
        : equityView(host, data, fund, benchmark?.kind === 'equity' ? benchmark : null, rows);
      requestAnimationFrame(() => draws.forEach((draw) => draw()));
      status.textContent = '';
    } catch (error) {
      host.innerHTML = '';
      status.textContent = error.message;
    }
  }

  await show(available.some((f) => f.ticker === BENCHMARK) ? BENCHMARK : available[0].ticker);
}
