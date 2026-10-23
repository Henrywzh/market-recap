// FLOWS · HEDGE FUNDS: how levered and how exposed to equities the hedge funds
// are, from the quarterly SEC Form PF aggregates the OFR publishes. Quarter-end
// figures, months behind the market: the lag is printed from the build, not
// assumed here. The pure helpers are what the tests check; section() turns the
// build's section dict into cards. A missing figure is a dash, never a zero.

import { el, card, num, table, tag, gap, DASH } from './fmt.js';
import { timeLines } from './charts.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const MINUS = '−';
const TITLE = 'HEDGE FUNDS · LEVERAGE AND EQUITY EXPOSURE (FORM PF)';

// A signed figure with a true minus. A value that rounds to zero carries no sign:
// "-0.0x" would read as a fall.
function signed(value, digits) {
  if (!present(value)) return DASH;
  const rounded = Number(Math.abs(value).toFixed(digits));
  const sign = rounded === 0 ? '' : value < 0 ? MINUS : '+';
  return `${sign}${num(rounded, digits)}`;
}

// Dollar amounts arrive in $bn. Above a trillion they read in $tn: "$6.19tn".
export function dollarBnText(value, withSign = false) {
  if (!present(value)) return DASH;
  const size = Math.abs(value);
  const scaled = size >= 1000 ? Number((size / 1000).toFixed(2)) : Math.round(size);
  const unit = size >= 1000 ? 'tn' : 'bn';
  const body = `$${num(scaled, size >= 1000 ? 2 : 0)}${unit}`;
  if (scaled === 0) return body;
  if (withSign) return `${value < 0 ? MINUS : '+'}${body}`;
  return value < 0 ? `${MINUS}${body}` : body;
}

// A level in its own unit: "2.52x", "37.6%", "$6.19tn".
export function levelText(unit, value) {
  if (!present(value)) return DASH;
  if (unit === '$bn') return dollarBnText(value);
  if (unit === 'x') return `${num(value, 2)}x`;
  if (unit === '%') return `${num(value, 1)}%`;
  return num(value, 2);
}

// A change in its own unit, with its percentage in brackets where one exists.
// A percentage-unit series moves in points, not per cent of a per cent.
export function changeText(unit, change, changePct) {
  if (!present(change)) return DASH;
  let head;
  if (unit === '$bn') head = dollarBnText(change, true);
  else if (unit === 'x') head = `${signed(change, 2)}x`;
  else if (unit === '%') head = `${signed(change, 1)} pts`;
  else head = signed(change, 2);
  return present(changePct) ? `${head} (${signed(changePct, 1)}%)` : head;
}

// "91st pct": where the latest quarter sits in its own history.
export function ordinal(percentile) {
  if (!present(percentile)) return DASH;
  const n = Math.round(percentile);
  const teen = n % 100 >= 11 && n % 100 <= 13;
  const suffix = teen ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
  return `${n}${suffix} pct`;
}

// The two charts: leverage on the left axis against net equity exposure on the
// right; long, short and borrowed equity exposure in $bn on one axis.
export function chartLines(data) {
  const byId = Object.fromEntries((data?.series || []).map((s) => [s.id, s]));
  const line = (id, name, extra) => {
    const s = byId[id];
    return s ? { name, dates: s.dates, values: s.values, unit: s.unit, ...extra } : null;
  };
  const leverage = [
    line('gross_leverage', 'gross assets ÷ net assets (left)', { axis: 0, color: (p) => p.accent, width: 1.6 }),
    line('equity_net_pct_nav', 'net equity exposure, % of net assets (right)', { axis: 1, color: (p) => p.blue, width: 1.4 }),
  ].filter(Boolean);
  const flows = [
    line('equity_long', 'long equity exposure', { axis: 0, color: (p) => p.up, width: 1.4 }),
    line('equity_short', 'short equity exposure', { axis: 0, color: (p) => p.down, width: 1.4 }),
    line('equity_borrowing', 'borrowing, equity strategy funds', { axis: 0, color: (p) => p.purple, width: 1.2 }),
  ].filter(Boolean);
  return { leverage, flows };
}

function schedule(fn) {
  // Charts draw once the node is in the page, as positioning.js does.
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(fn);
  else fn();
}

function leverageChart(lines) {
  const node = el('div', { class: 'chart', 'aria-label': 'Hedge fund gross leverage and net equity exposure, quarterly' });
  schedule(() => timeLines(node, lines, {
    left: (v) => `${num(v, 1)}x`,
    right: (v) => `${num(v, 0)}%`,
    value: (v, line) => levelText(line.unit, v),
  }));
  return node;
}

function flowsChart(lines) {
  const node = el('div', { class: 'chart', 'aria-label': 'Hedge fund long and short equity notional and equity borrowing, quarterly, $bn' });
  schedule(() => timeLines(node, lines, {
    left: (v) => dollarBnText(v),
    value: (v, line) => levelText(line.unit, v),
  }));
  return node;
}

function latestTable(series) {
  const rows = series.map((s) => {
    const latest = s.latest || {};
    return el('tr', {}, [
      el('td', { text: s.label }),
      el('td', { text: levelText(s.unit, latest.value) }),
      el('td', { text: changeText(s.unit, latest.q_change, latest.q_change_pct) }),
      el('td', { text: changeText(s.unit, latest.y_change, latest.y_change_pct) }),
      el('td', { text: ordinal(latest.percentile) }),
    ]);
  });
  return table(['SERIES', 'LATEST', 'Q/Q', 'Y/Y', 'PCTILE'], rows, { class: 'hf-leverage-table' });
}

function methodFold(data) {
  const src = data.source || {};
  const notes = [
    `Source: OFR Hedge Fund Monitor, SEC Form PF statistics (dataset ${src.dataset || 'fpf'}), ${src.url || 'the OFR site'}. ${src.lag || ''}`,
    `Vintage: ${src.vintage || 'current vintage'}. Each quarter is restated when a later filing revises it, so the history can change between builds.`,
    'Qualifying hedge funds: the Form PF filers the OFR aggregates. Totals are sums across funds, so the big funds dominate them.',
    'Gross assets ÷ net assets is the ratio of the two totals. OFR also publishes fund-level leverage averages, which are not this figure.',
    'Net equity exposure is long minus short equity notional, as a percentage of net assets. Notional counts derivatives at their exposure, so it is not cash invested.',
    'Stress line: the median fund\'s change in net assets if equity prices fall 20%, as the filers estimate it.',
    'Percentile: the share of quarters since the series began at or below the latest value.',
    'Limits: aggregates only, no single manager. Values OFR withholds to avoid identifying a filer are absent, not zero.',
  ];
  return el('details', { class: 'sx-fold' }, [
    el('summary', { text: 'Method & limits' }),
    ...notes.map((text) => el('div', { class: 'method-copy', text })),
  ]);
}

export function section(data) {
  if (!data || data.unavailable) {
    const reason = data?.unavailable ? `: ${data.unavailable}` : '';
    return [card(TITLE, null, gap(`Not built this session${reason}.`))];
  }
  const series = Array.isArray(data.series) ? data.series : [];
  if (!series.length) return [card(TITLE, null, gap('No Form PF series in this build.'))];
  const src = data.source || {};
  const lines = chartLines(data);
  const head = tag(`LATEST ${src.latest_period || DASH}`, 'info');
  const body = [
    el('div', { class: 'meta-line', text: src.lag || '' }),
    lines.leverage.length ? leverageChart(lines.leverage) : null,
    lines.flows.length ? flowsChart(lines.flows) : null,
    latestTable(series),
    methodFold(data),
  ];
  return [card(TITLE, head, body)];
}
