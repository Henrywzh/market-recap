// BRIEF: the five-minute read. Live quotes, the systematic anchor, the risk
// and pricing strips, what changed, the next 72 hours and my list -- each
// line from the page that owns it, and each linking there.

import { el, card, num, pct, metaRow, DASH } from '../fmt.js';
import { render } from '../charts.js';
import { mountLive } from '../live.js';
import { tickerHref } from '../routes.js';
import { tileNode, formatValue } from './risk.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const bp = (v, digits = 1) => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}bp` : DASH);
const pctOf = (v) => (present(v) ? `${Math.round(v * 100)}%` : DASH);
const shortDate = (iso) => (iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }).toUpperCase() : DASH);

function stat(label, value, note, cls = '', href = null) {
  const node = el(href ? 'a' : 'div', { class: `stat${href ? ' stat-link' : ''}`, href }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
  return node;
}

function anchorCard(a) {
  if (!a) return card('SYSTEMATIC ANCHOR', null, el('div', { class: 'gap', text: 'The anchor was not built for this session.' }));
  const c = a.components;
  const chip = (text, cls = '') => el('span', { class: `mchip ${cls}`, text });
  const chartNode = el('div', { class: 'chart short' });
  requestAnimationFrame(() => render(chartNode, (option, p) => ({
    ...option,
    grid: { left: 36, right: 40, top: 8, bottom: 22 },
    tooltip: { ...option.tooltip, trigger: 'axis' },
    xAxis: { ...option.xAxis, data: a.history.dates },
    yAxis: [
      { ...option.yAxis, min: 0, max: 1, axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => `${Math.round(v * 100)}%` } },
      { ...option.yAxis, position: 'right', splitLine: { show: false }, axisLabel: { color: p.faint, fontSize: 9 } },
    ],
    series: [
      { name: 'anchor exposure', type: 'line', step: 'end', data: a.history.exposure, showSymbol: false, areaStyle: { opacity: 0.12 }, lineStyle: { width: 1.4, color: p.accent }, itemStyle: { color: p.accent } },
      { name: 'SPY', type: 'line', yAxisIndex: 1, data: a.history.spy, showSymbol: false, lineStyle: { width: 1, color: p.faint } },
    ],
  })));
  const last = a.changes[a.changes.length - 1];
  return card('SYSTEMATIC ANCHOR', el('a', { href: '#risk', class: 'dim', text: 'frozen v1 rule ↗' }), [
    el('div', { class: 'brief-anchor' }, [
      el('div', { class: 'brief-anchor-head' }, [
        el('span', { class: 'brief-anchor-value', text: pctOf(a.held) }),
        el('span', { class: 'dim', text: ` held · next session ${pctOf(a.next)}${last ? ` · since ${last.date}` : ''}` }),
      ]),
      el('div', { class: 'brief-anchor-chips' }, [
        chip(`VOL ${present(c.realised_vol) ? num(c.realised_vol * 100, 1) : DASH}% → ×${num(c.vol_scaled, 2)}`),
        chip(`TREND ${c.trend_on ? 'ON · SPY > 200D' : 'OFF · cap 50%'}`, c.trend_on ? 'up' : 'down'),
        chip(`COPPER/OIL ${c.copper_oil_on === false ? `OFF · z ${num(c.copper_oil_z, 2)} · cap 50%` : c.copper_oil_on ? `ON · z ${num(c.copper_oil_z, 2)}` : DASH}`, c.copper_oil_on === false ? 'down' : 'up'),
        chip(`LADDER ×${num(c.ladder, 1)} · overlay ${num((c.overlay_drawdown || 0) * 100, 1)}%`, c.ladder < 1 ? 'down' : ''),
        chip('RECESSION GATE not ported · neutral'),
      ]),
    ]),
    chartNode,
  ]);
}

function pricedStrip(p) {
  if (!p) return card('PRICED', null, el('div', { class: 'gap', text: 'PRICED PATH was not built for this session.' }));
  const n = p.next_meeting;
  const pMove = n.step.whole_steps ? 1 : n.step.p_next_step;
  const cpi = p.cpi;
  const iv = p.implied_vs_realised;
  return card('PRICED', el('a', { href: '#priced', class: 'dim', text: 'priced path ↗' }), [el('div', { class: 'stat-strip brief-priced' }, [
    stat(`NEXT FOMC · ${shortDate(n.date)}`, bp(n.change_bp),
      `P(${n.step.direction === 'hold' ? 'hold' : n.step.direction}) ${pctOf(pMove)} · 1D ${bp(n.change_1d_bp)} · 1W ${bp(n.change_1w_bp)} · Kalshi ${pctOf(n.kalshi_p_hike)} · Poly ${pctOf(n.polymarket_p_hike)}`,
      n.change_bp > 0 ? 'down' : n.change_bp < 0 ? 'up' : '', '#priced'),
    stat(`PRICED BY ${shortDate(p.by_year_end.date)}`, bp(p.by_year_end.cumulative_bp, 0), `${num(p.by_year_end.cumulative_bp / 25, 1)} × 25bp`, '', '#priced'),
    cpi ? stat(`${cpi.label.toUpperCase()} · ${shortDate(cpi.release)}`, `${num(cpi.value, 2)}%`, `Kalshi median · 10–90% ${num(cpi.low, 2)}–${num(cpi.high, 2)}`, '', '#priced') : stat('NEXT CPI', DASH, 'no open Kalshi ladder'),
    stat('SPX 30D IMPLIED VS REALISED', `${num(iv.vix, 1)} / ${num(iv.realised, 1)}`, present(iv.vix) && present(iv.realised) ? `VIX ${iv.vix >= iv.realised ? 'above' : 'below'} 20-day realised by ${num(Math.abs(iv.vix - iv.realised), 1)}` : null, '', '#risk'),
  ])]);
}

function riskStrip(risk, asOf) {
  const row = (label, tiles) => el('div', { class: 'brief-risk-row' }, [
    el('div', { class: 'brief-risk-label', text: label }),
    el('div', { class: 'risk-grid brief-risk-grid' }, tiles.map((t) => tileNode(t, { asOf, onPick: () => { location.hash = 'risk'; } }))),
  ]);
  return card('RISK', el('a', { href: '#risk', class: risk.breaches ? 'down' : 'dim', text: `${risk.breaches} of all series past threshold · risk page ↗` }), [
    row('TACTICAL · 1–4 WEEKS', risk.tactical),
    row('SLOW · MONTHS', risk.slow),
  ]);
}

function changedCard(changed) {
  const section = (title, nodes, empty) => el('div', { class: 'brief-block' }, [
    el('div', { class: 'brief-block-title', text: title }),
    nodes.length ? el('div', { class: 'brief-chips' }, nodes) : el('div', { class: 'dim', text: empty }),
  ]);
  const risk = changed.risk.map((c) => el('a', { href: '#risk', class: `mchip ${c.crossed === 'into' ? 'down' : 'up'}`,
    text: `${c.label} ${formatValue(c.value, c.unit)} ${c.crossed === 'into' ? '↑ past line' : '↓ back inside'}` }));
  const entered = changed.monitor.filter((c) => c.kind === 'entered').map((c) => el('a', { href: tickerHref(c.ticker), class: 'mchip down', text: `+ ${c.ticker}`, title: c.text || '' }));
  const left = changed.monitor.filter((c) => c.kind === 'left').map((c) => el('a', { href: tickerHref(c.ticker), class: 'mchip', text: `− ${c.ticker}`, title: c.text || '' }));
  const moves = changed.earnings.map((e) => el('a', { href: tickerHref(e.ticker), class: `mchip ${e.return_1d >= 0 ? 'up' : 'down'}`,
    text: `${e.ticker} ${pct(e.return_1d, 1)}`, title: `reported ${e.date}; surprise ${pct(e.surprise_pct, 1)}` }));
  return card('WHAT CHANGED', null, [
    section('RISK LINES CROSSED THIS WEEK', risk, 'none'),
    section('MONITOR QUEUE · ENTERED / LEFT', [...entered, ...left], 'no change since the last session'),
    section('POST-EARNINGS MOVES ≥ 5%', moves, 'none since the last session'),
  ]);
}

function next72(items) {
  if (!items.length) return card('NEXT 72 HOURS', el('a', { href: '#catalysts', class: 'dim', text: 'calendar ↗' }), el('div', { class: 'dim', text: 'Nothing high- or medium-importance, and no watchlist or top-20 earnings, in the next three sessions.' }));
  const rows = items.map((i) => {
    if (i.kind === 'macro') {
      const m = i.market;
      return el('div', { class: 'brief-event' }, [
        el('span', { class: 'brief-event-when dim', text: `${shortDate(i.date)}${i.time ? ` ${i.time}` : ''}` }),
        el('span', { class: `brief-event-title ${i.importance === 'high' ? '' : 'dim'}`, text: i.title }),
        el('span', { class: 'brief-event-figure dim', text: m ? `${m.label} ${num(m.value, m.decimals ?? 2)}${m.unit === '%' ? '%' : ''} (${num(m.low, m.decimals ?? 2)}–${num(m.high, m.decimals ?? 2)})` : '' }),
      ]);
    }
    return el('div', { class: 'brief-event' }, [
      el('span', { class: 'brief-event-when dim', text: `${shortDate(i.date)}${i.time ? ` ${String(i.time).toUpperCase()}` : ''}` }),
      el('a', { class: 'brief-event-title', href: tickerHref(i.symbol), text: `${i.symbol} earnings` }),
      el('span', { class: 'brief-event-figure dim', text: [i.watchlist ? 'WATCHLIST' : null, present(i.weight) ? `${num(i.weight, 2)}% of SPX` : null, present(i.eps_forecast) ? `EST $${num(i.eps_forecast, 2)}` : null].filter(Boolean).join(' · ') }),
    ]);
  });
  return card('NEXT 72 HOURS', el('a', { href: '#catalysts', class: 'dim', text: 'calendar ↗' }), rows);
}

function myList(rows) {
  if (!rows.length) return card('MY LIST', null, el('div', { class: 'dim', text: 'No watchlist names and no open checkpoints.' }));
  const head = ['NAME', 'PRICE', 'EVIDENCE', 'FROM 1Y HIGH', 'VS PEERS 1M', 'NEXT EARNINGS', 'NEXT CHECKPOINT'];
  const body = rows.map((r) => el('tr', {}, [
    el('td', {}, [el('a', { href: tickerHref(r.ticker), text: r.ticker }), el('span', { class: 'dim', text: ` ${r.name || ''}` })]),
    el('td', { class: r.price_state === 'weak' ? 'down' : r.price_state === 'stabilising' ? 'up' : 'dim', text: (r.price_state || DASH).toUpperCase() }),
    el('td', { class: r.evidence_state === 'deteriorating' ? 'down' : r.evidence_state === 'steady' ? 'up' : 'dim', text: (r.evidence_state || DASH).toUpperCase() }),
    el('td', { text: pct(r.drawdown_pct, 1) }),
    el('td', { class: present(r.peer_excess_pct) ? (r.peer_excess_pct >= 0 ? 'up' : 'down') : '', text: present(r.peer_excess_pct) ? `${r.peer_excess_pct > 0 ? '+' : ''}${num(r.peer_excess_pct, 1)} pp` : DASH }),
    el('td', { text: r.earnings_date || DASH }),
    el('td', { class: 'wrap-cell', text: r.checkpoint ? `${r.checkpoint.date} · ${r.checkpoint.text}` : DASH }),
  ]));
  return card('MY LIST', el('a', { href: '#journal', class: 'dim', text: 'journal ↗' }), el('div', { class: 'table-scroll' }, [
    el('table', { class: 'data brief-list' }, [el('thead', {}, [el('tr', {}, head.map((h) => el('th', { text: h })))]), el('tbody', {}, body)]),
  ]));
}

export default function renderBrief(root, data) {
  const missing = data.missing || [];
  root.append(metaRow(`BRIEF · SESSION ${data.as_of}${missing.length ? ` · NOT BUILT THIS SESSION: ${missing.join(', ').toUpperCase()}` : ''}`, [
    'The daily read. Every line is taken from the page that owns it, for this session only; a page that did not build leaves its line empty rather than showing another day\'s numbers.',
    'SYSTEMATIC ANCHOR: quantamental-lab\'s frozen v1 control, ported and checked to reproduce its daily exposure exactly over 1993–2026. Vol-targeted to 12% on 63-day realised volatility, capped at 50% while SPY is not above its 200-day average or while the copper/oil gate is off (z-score of log copper/oil below −0.25 against the prior year, back on above +0.25), and stepped down to ×0.6 / ×0.3 when its own drawdown passes −8% / −12%. Its recession gate is that repository\'s model output and is not ported: treated as neutral, the rule\'s own policy for a missing input. It is a reference, not a recommendation; a different exposure is a decision to log in the journal.',
  ]));
  root.append(el('div', { class: 'brief-live' }, [mountLive()]));
  root.append(el('div', { class: 'grid brief-top' }, [anchorCard(data.anchor), pricedStrip(data.priced)]));
  root.append(riskStrip(data.risk, data.as_of));
  root.append(el('div', { class: 'grid two brief-bottom' }, [changedCard(data.changed), next72(data.next_72h)]));
  root.append(myList(data.my_list));
}
