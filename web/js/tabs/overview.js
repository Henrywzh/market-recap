// OVERVIEW: the one-glance read and the landing page. Stocks and how far
// they sit from their high, breadth, rates and credit, the dollar,
// commodities and volatility, the latest macro prints -- each a level, its
// recent changes and six months of line -- then the Fed and the next three
// sessions.

import { el, card, num, pct, dirClass, metaRow, DASH } from '../fmt.js';
import { mountLive } from '../live.js';
import { tickerHref } from '../routes.js';
import { spark } from '../spark.js';
import { formatValue } from './risk.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits = 1, suffix = '') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${suffix}` : DASH);
const pctOf = (v) => (present(v) ? `${Math.round(v * 100)}%` : DASH);
const shortDate = (iso) => (iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }).toUpperCase() : DASH);
const quarterOf = (iso) => (iso ? `Q${Math.floor(Number(iso.slice(5, 7)) / 3) + 1} ${iso.slice(0, 4)}` : DASH);
const monthOf = (iso) => (iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' }).toUpperCase() : DASH);

function line(values, cls = '') {
  return el('td', { class: `ov-spark ${cls}` }, [spark(values, { width: 80, height: 22 })]);
}

function grid(headers, rows, cls = '') {
  return el('div', { class: 'table-scroll' }, [el('table', { class: `data ov-table ${cls}` }, [
    el('thead', {}, [el('tr', {}, headers.map((h) => el('th', { text: h })))]),
    el('tbody', {}, rows),
  ])]);
}

function stocksCard(rows) {
  const body = rows.map((r) => el('tr', {}, [
    el('td', { class: 'ov-name', text: r.label }),
    el('td', { text: present(r.last) ? num(r.last) : DASH }),
    ...['1D', '1W', '1M', 'YTD'].map((k) => el('td', { class: dirClass(r[k]), text: pct(r[k]) })),
    el('td', { class: present(r.from_high_pct) && r.from_high_pct < -0.05 ? 'down' : 'dim',
      title: r.high_date ? `52-week high ${r.high_date}, ${r.sessions_since_high} sessions ago` : '',
      text: present(r.from_high_pct) ? (r.from_high_pct > -0.05 ? 'AT HIGH' : pct(r.from_high_pct, 1)) : DASH }),
    line(r.spark),
  ]));
  return card('STOCKS', el('a', { href: '#markets', class: 'dim', text: 'indices ↗' }),
    grid(['', 'LAST', '1D', '1W', '1M', 'YTD', 'OFF 52W HIGH', '6M'], body));
}

function upDown(pair, members) {
  if (!pair) return el('td', { class: 'dim', text: DASH });
  const share = members ? pair.up / (pair.up + pair.down || 1) : 0;
  return el('td', { class: 'ov-ud' }, [
    el('span', { class: 'up', text: pair.up }), el('span', { class: 'dim', text: ' / ' }), el('span', { class: 'down', text: pair.down }),
    el('span', { class: 'ov-bar' }, [el('span', { class: 'ov-bar-up', style: `width:${Math.round(share * 100)}%` })]),
  ]);
}

function breadthCard(blocks) {
  if (!blocks.length) return card('BREADTH', null, el('div', { class: 'gap', text: 'No member closes in this build.' }));
  const row = (label, cell) => el('tr', {}, [el('td', { class: 'ov-name', text: label }), ...blocks.map(cell)]);
  const share = (v) => el('td', { class: present(v) ? (v >= 50 ? 'up' : 'down') : 'dim', text: present(v) ? `${num(v, 0)}%` : DASH });
  const body = [
    row('Up / down · today', (b) => upDown(b['1D'], b.members)),
    row('Up / down · 1 week', (b) => upDown(b['1W'], b.members)),
    row('Up / down · 1 month', (b) => upDown(b['1M'], b.members)),
    row('Above 50-day average', (b) => share(b.above_50d)),
    row('Above 200-day average', (b) => share(b.above_200d)),
    row('New 52-week highs / lows', (b) => el('td', {}, [
      el('span', { class: 'up', text: b.new_highs ?? DASH }), el('span', { class: 'dim', text: ' / ' }), el('span', { class: 'down', text: b.new_lows ?? DASH }),
    ])),
    row('% above 50-day · 6M', (b) => line(b.above_50d_spark)),
  ];
  return card('BREADTH', el('span', { class: 'dim', text: 'index members, counted by their own closes' }),
    grid(['', ...blocks.map((b) => `${b.key} · ${b.members}`)], body, 'ov-breadth'));
}

function ratesCard(rows, fed) {
  const level = (r) => (!present(r.value) ? DASH : r.unit === 'bp' ? `${num(r.value, 0)}bp` : `${num(r.value, 2)}%`);
  const body = rows.map((r) => el('tr', {}, [
    el('td', { class: 'ov-name', text: r.label }),
    el('td', { text: level(r) }),
    ...['change_1d_bp', 'change_1w_bp', 'change_1m_bp'].map((k) => el('td', { class: 'dim', text: signed(r[k], 0) })),
    line(r.spark),
  ]));
  const foot = fed ? el('div', { class: 'ov-fed' }, [
    el('a', { href: '#priced', text: `NEXT FOMC ${shortDate(fed.date)}` }),
    el('span', { text: ` priced ${signed(fed.change_bp, 1, 'bp')}` }),
    el('span', { class: 'dim', text: ` · P(${fed.step.direction === 'hold' ? 'hold' : fed.step.direction}) ${pctOf(fed.step.whole_steps ? 1 : fed.step.p_next_step)} · Kalshi ${pctOf(fed.kalshi_p_hike)} · Polymarket ${pctOf(fed.polymarket_p_hike)} hike · by ${shortDate(fed.year_end.date)} ${signed(fed.year_end.cumulative_bp, 0, 'bp')}` }),
  ]) : el('div', { class: 'ov-fed dim', text: 'Fed pricing was not built for this session.' });
  return card('RATES & CREDIT', el('a', { href: '#rates', class: 'dim', text: 'rates & macro ↗' }), [
    grid(['', 'LEVEL', '1D bp', '1W bp', '1M bp', '6M'], body), foot,
  ]);
}

function crossCard(rows) {
  const body = rows.map((r) => {
    const change = (k) => (r.unit === 'pts'
      ? el('td', { class: present(r[k]) ? (r[k] > 0 ? 'down' : 'up') : 'dim', text: signed(r[k], 1) })
      : el('td', { class: dirClass(r[k]), text: pct(r[k]) }));
    return el('tr', {}, [
      el('td', { class: 'ov-name', text: r.label }),
      el('td', { text: present(r.last) ? num(r.last) : DASH }),
      ...['1D', '1W', '1M', 'YTD'].map(change),
      line(r.spark),
    ]);
  });
  return card('DOLLAR, COMMODITIES & VOLATILITY', el('span', { class: 'dim', text: 'VIX changes in points' }),
    grid(['', 'LAST', '1D', '1W', '1M', 'YTD', '6M'], body));
}

function printsCard(rows) {
  const value = (v, unit) => (!present(v) ? DASH : unit.startsWith('k') ? `${v > 0 ? '+' : ''}${num(v, 0)}k` : `${num(v, unit.includes('y/y') ? 2 : 1)}%`);
  const body = rows.map((r) => el('tr', {}, [
    el('td', { class: 'ov-name', text: r.label }),
    el('td', { text: value(r.value, r.unit) }),
    el('td', { class: 'dim', text: value(r.prior, r.unit) }),
    el('td', { class: 'dim', text: r.monthly ? monthOf(r.period) : quarterOf(r.period) }),
  ]));
  return card('MACRO · LATEST PRINTS', el('a', { href: '#catalysts', class: 'dim', text: 'calendar ↗' }),
    grid(['', 'LATEST', 'PRIOR', 'FOR'], body));
}

function aheadCard(items) {
  const head = el('a', { href: '#catalysts', class: 'dim', text: 'calendar ↗' });
  if (!items.length) return card('NEXT 3 SESSIONS', head, el('div', { class: 'dim', text: 'No high- or medium-importance release and no watchlist or top-20 earnings in the next three sessions.' }));
  return card('NEXT 3 SESSIONS', head, items.map((i) => {
    if (i.kind === 'macro') {
      const m = i.market;
      return el('div', { class: 'ov-event' }, [
        el('span', { class: 'dim', text: `${shortDate(i.date)}${i.time ? ` ${i.time}` : ''}` }),
        el('span', { class: i.importance === 'high' ? '' : 'dim', text: i.title }),
        el('span', { class: 'dim ov-event-figure', text: m ? `${m.label} ${num(m.value, m.decimals ?? 2)}${m.unit === '%' ? '%' : ''}` : '' }),
      ]);
    }
    return el('div', { class: 'ov-event' }, [
      el('span', { class: 'dim', text: `${shortDate(i.date)}${i.time ? ` ${String(i.time).toUpperCase()}` : ''}` }),
      el('a', { href: tickerHref(i.symbol), text: `${i.symbol} earnings` }),
      el('span', { class: 'dim ov-event-figure', text: [i.watchlist ? 'WATCHLIST' : null, present(i.weight) ? `${num(i.weight, 2)}% of SPX` : null].filter(Boolean).join(' · ') }),
    ]);
  }));
}

function riskLine(risk) {
  if (!risk) return null;
  const past = risk.past || [];
  return el('a', { href: '#risk', class: `ov-risk ${past.length ? 'down' : ''}` }, [
    el('span', { class: 'ov-risk-label', text: 'RISK' }),
    el('span', { text: past.length
      ? `${past.length} of ${risk.core} core series past its line: ${past.map((p) => `${p.label} ${formatValue(p.value, p.unit)}`).join(' · ')}`
      : `none of the ${risk.core} core series is past its line` }),
    el('span', { class: 'dim', text: ' →' }),
  ]);
}

export default function renderOverview(root, data) {
  const missing = data.missing || [];
  const failed = Object.keys(data.failed || {});
  root.append(metaRow(`OVERVIEW · SESSION ${data.as_of}${missing.length ? ` · NOT BUILT THIS SESSION: ${missing.join(', ').toUpperCase()}` : ''}${failed.length ? ` · ${failed.length} SOURCE(S) FAILED` : ''}`, [
    'Closing figures of the session above; the live strip is the only thing that moves during the day. Lines are the last six months.',
    'Stocks: the S&P 500 and Nasdaq 100 are the index levels; the Russell 2000 and the equal-weighted S&P 500 are read through IWM and RSP. From 52W high is the drawdown from the highest close of the last 252 sessions.',
    'Breadth counts each index\'s members by their own closes: how many rose and fell over a day, a week (5 sessions) and a month (21 sessions), the share above their 50- and 200-day averages, and how many closed at a 52-week high or low.',
    'Rates and credit are FRED\'s daily series (Treasury constant-maturity yields, the 10-year TIPS yield, ICE BofA option-adjusted spreads), a day behind the equity close. Macro prints are the latest published value with the one before it; GDPNow is the Atlanta Fed\'s running estimate for the current quarter.',
    ...failed.map((k) => `${k}: ${data.failed[k]}`),
  ]));
  root.append(el('div', { class: 'ov-live' }, [mountLive()]));
  const risk = riskLine(data.risk);
  if (risk) root.append(risk);
  root.append(el('div', { class: 'grid two ov-row' }, [stocksCard(data.stocks), breadthCard(data.breadth)]));
  root.append(el('div', { class: 'grid two ov-row' }, [ratesCard(data.rates, data.fed), crossCard(data.cross_asset)]));
  root.append(el('div', { class: 'grid two ov-row' }, [printsCard(data.prints), aheadCard(data.ahead)]));
}
