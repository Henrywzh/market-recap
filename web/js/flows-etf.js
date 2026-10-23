// FLOWS · ETF creations and redemptions (section A). Daily flow is the change
// in each fund's issuer-published share count, priced at that day's NAV: the
// primary-market money that moved through creations less redemptions. It is
// not a read of who the end buyer was.

import { el, card, num, DASH, tag, periodSwitch } from './fmt.js';
import { render } from './charts.js';

const TITLE = 'ETF FLOWS · CREATIONS AND REDEMPTIONS';
const present = (v) => v !== null && v !== undefined && Number.isFinite(v);

// Signed dollars with a unit that keeps three figures: "+$7.7bn", "−$310m".
export function dollars(v) {
  if (!present(v)) return DASH;
  if (v === 0) return '$0';
  const sign = v < 0 ? '−' : '+';
  const a = Math.abs(v);
  if (a >= 1e9) return `${sign}$${num(a / 1e9, 1)}bn`;
  if (a >= 1e6) return `${sign}$${num(a / 1e6, a >= 1e8 ? 0 : 1)}m`;
  return `${sign}$${num(a, 0)}`;
}

// A share of assets, given as a fraction: 0.0131 reads "+1.31%".
export function pctOfAssets(fraction) {
  if (!present(fraction)) return DASH;
  const sign = fraction > 0 ? '+' : fraction < 0 ? '−' : '';
  return `${sign}${num(Math.abs(fraction) * 100, 2)}%`;
}

// A percentile rank as "97th pct", with the right ordinal suffix.
export function rankText(rank) {
  if (!present(rank)) return DASH;
  const n = Math.round(rank);
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' })[n % 10] || 'th';
  return `${n}${suffix} pct`;
}

// One line for the TODAY page: the US equity total, its rank, and the largest moves.
export function headlineText(headline) {
  if (!headline || !present(headline.us_equity_1w)) return null;
  const rank = present(headline.us_equity_1w_pct_rank) ? `, ${rankText(headline.us_equity_1w_pct_rank)} of three years` : '';
  const pick = (rows) => (rows || []).map(([ticker, flow]) => `${ticker} ${dollars(flow)}`).join(', ');
  const parts = [`US equity ETFs ${dollars(headline.us_equity_1w)} over a week${rank}`];
  if (headline.top_in?.length) parts.push(`in: ${pick(headline.top_in)}`);
  if (headline.top_out?.length) parts.push(`out: ${pick(headline.top_out)}`);
  return parts.join('; ');
}

function gap(message) {
  return el('div', { class: 'gap', text: message });
}

function sign(v) {
  return present(v) && v > 0 ? 'up' : present(v) && v < 0 ? 'down' : '';
}

function fundRows(funds) {
  const rows = [];
  let group = null;
  for (const fund of funds) {
    if (fund.group !== group) {
      group = fund.group;
      rows.push(el('tr', { class: 'flow-group' }, [el('td', { colspan: '7', text: group })]));
    }
    const tickerCell = el('td', { class: 'flow-ticker' }, [
      el('span', { text: fund.ticker }),
      el('span', { class: 'dim', text: ` ${fund.label}` }),
      fund.stale ? tag('STALE', 'warn', fund.note || 'share count unchanged') : null,
    ]);
    rows.push(el('tr', {}, [
      tickerCell,
      el('td', { class: sign(fund.flow_1d), text: dollars(fund.flow_1d) }),
      el('td', { class: sign(fund.flow_1w), text: dollars(fund.flow_1w) }),
      el('td', { class: sign(fund.flow_1m), text: dollars(fund.flow_1m) }),
      el('td', { class: sign(fund.flow_1m_pct_aum), text: pctOfAssets(fund.flow_1m_pct_aum) }),
      el('td', { class: 'dim', text: rankText(fund.pct_rank_1w) }),
      el('td', { class: 'dim', text: fund.as_of || DASH }),
    ]));
  }
  return rows;
}

function table(funds) {
  const head = el('thead', {}, [el('tr', {}, ['TICKER', '1D', '1W', '1M', '1M % AUM', '1W RANK', 'AS OF'].map((h) => el('th', { text: h })))]);
  return el('div', { class: 'table-scroll' }, [el('table', { class: 'data flow-table' }, [head, el('tbody', {}, fundRows(funds))])]);
}

// The aggregate's daily flow as bars (green in, red out) with the 20-session sum as a line. Both in $bn.
function aggregateChart(node, aggregate) {
  render(node, (option, p) => {
    const bn = (v) => (present(v) ? v / 1e9 : null);
    return {
      ...option,
      grid: { ...option.grid, right: 16, bottom: 52 },
      legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
      tooltip: { ...option.tooltip, valueFormatter: (x) => (present(x) ? dollars(x * 1e9) : DASH) },
      xAxis: { ...option.xAxis, data: aggregate.dates },
      series: [
        {
          name: 'Daily flow', type: 'bar', barMaxWidth: 4,
          data: aggregate.flow.map(bn),
          itemStyle: { color: (q) => (q.value >= 0 ? p.up : p.down) },
        },
        {
          name: '20-session sum', type: 'line', showSymbol: false, connectNulls: false,
          data: aggregate.rolling_20.map(bn),
          itemStyle: { color: p.accent }, lineStyle: { color: p.accent, width: 1.4 },
        },
      ],
      yAxis: { ...option.yAxis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${num(v, 0)}bn` } },
    };
  });
}

// Sector funds, one bar each: 1M flow as a share of the fund's assets.
function sectorChart(node, sectors) {
  render(node, (option, p) => ({
    ...option,
    grid: { left: 128, right: 56, top: 8, bottom: 24 },
    xAxis: {
      type: 'value', axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => `${num(v, 1)}%` },
      splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
    },
    yAxis: {
      type: 'category', inverse: true, data: sectors.map((s) => `${s.ticker} ${s.label}`),
      axisLine: { lineStyle: { color: p.border } }, axisTick: { show: false },
      axisLabel: { color: p.dim, fontSize: 10 },
    },
    tooltip: { ...option.tooltip, trigger: 'item', valueFormatter: (x) => (present(x) ? `${num(x, 2)}%` : DASH) },
    series: [{
      type: 'bar', barMaxWidth: 12,
      data: sectors.map((s) => (present(s.flow_1m_pct_aum) ? s.flow_1m_pct_aum * 100 : null)),
      itemStyle: { color: (q) => (q.value >= 0 ? p.up : p.down) },
      label: { show: true, position: 'right', color: p.dim, fontSize: 10, formatter: (q) => (present(q.value) ? `${q.value > 0 ? '+' : ''}${num(q.value, 2)}%` : DASH) },
    }],
  }));
}

function methodFold(data) {
  const since = data.invesco_recorded_since;
  const notCovered = (data.not_covered || []).map((n) => `${n.ticker} (${n.label})`).join(', ');
  const paragraphs = [
    'Flow is the change in the fund\'s published shares outstanding, times that day\'s NAV. It is the primary-market money (authorised participants creating and redeeming units), not the end buyer.',
    'Each fund\'s as-of date is its issuer\'s own last published date. The issuer publishes after the close, so the lag is about one session; that lag is not measured here.',
    'Split days: when units and NAV move inversely by a whole-number factor the flow is withheld and listed in the excluded days. Nothing is forward-filled: a window containing a withheld day is blank.',
    `Invesco publishes only today's unit count, so QQQ and RSP flow is recorded nightly${since ? ` since ${since}` : ''}. They have no year on record yet, so they carry no percentile and join no total.`,
    `Not covered: ${notCovered || 'none'}. Vanguard publishes no share-count history on the endpoints this page reads.`,
    'A total sums the funds that have a flow that day; the count is shown per day. A fund whose history starts inside the window is left out.',
    '1W RANK is the latest 5-session flow\'s percentile among every 5-session flow of the last three years. It is blank under a year of history.',
    data.lag,
  ].filter(Boolean);
  return el('details', { class: 'sx-fold' }, [
    el('summary', { text: 'Method & limits' }),
    ...paragraphs.map((text) => el('div', { class: 'note-text', text })),
  ]);
}

// The fund notes, one line each, under the table: anything the numbers depend on.
function fundNotes(funds) {
  const lines = funds.filter((f) => f.note).map((f) => el('div', { class: 'field-note', text: `${f.ticker}: ${f.note}` }));
  return lines.length ? el('div', { class: 'flow-notes' }, lines) : null;
}

export function section(data) {
  if (!data) return [card(TITLE, null, gap('ETF flows were not built this session.'))];
  if (data.unavailable) return [card(TITLE, null, gap(`ETF flows are not available: ${data.unavailable}.`))];

  const funds = data.funds || [];
  if (!funds.length) return [card(TITLE, null, gap('No ETF share history in this build.'))];
  const aggregates = data.aggregates || [];
  const chartNode = el('div', { class: 'chart tall', 'aria-label': 'ETF daily creations less redemptions, with the rolling 20-session sum' });
  const sectorNode = el('div', { class: 'chart flow-sector-chart', 'aria-label': 'Sector ETFs: one-month flow as a share of assets' });
  const latest = el('div', { class: 'stat-note' });

  let active = aggregates[0]?.name;
  const draw = () => {
    const agg = aggregates.find((a) => a.name === active);
    const populated = Boolean(agg && agg.dates.length);
    chartNode.hidden = !populated;
    if (populated) {
      aggregateChart(chartNode, agg);
      const dated = agg.latest_date ? `as of ${agg.latest_date}` : '';
      latest.textContent = `${agg.name}: 1W ${dollars(agg.latest.flow_1w)} · 1M ${dollars(agg.latest.flow_1m)} · 1W rank ${rankText(agg.latest.pct_rank_1w)} · ${agg.funds.join(', ')} ${dated}`;
    } else {
      latest.textContent = `${active}: no total for this build.`;
    }
  };
  const chips = aggregates.length
    ? periodSwitch(aggregates.map((a) => a.name), active, (name) => { active = name; draw(); })
    : null;
  requestAnimationFrame(draw);

  const sectors = (data.sectors || []).filter((s) => present(s.flow_1m_pct_aum));
  if (sectors.length) requestAnimationFrame(() => sectorChart(sectorNode, sectors));

  return [card(TITLE, chips, [
    latest, chartNode,
    table(funds),
    fundNotes(funds),
    sectors.length ? el('div', { class: 'stat-label', text: 'SECTOR ETFS · 1M FLOW AS A SHARE OF ASSETS' }) : null,
    sectors.length ? sectorNode : null,
    methodFold(data),
  ])];
}
