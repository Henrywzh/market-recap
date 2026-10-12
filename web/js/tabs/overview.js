// OVERVIEW: the one-glance read and the landing page. Stocks and how far
// they sit from their high, breadth, rates and credit, the dollar,
// commodities and volatility, the latest macro prints -- each a level, its
// recent changes and six months of line -- then the Fed and the next three
// sessions.

import { el, card, num, pct, dirClass, metaRow, periodSwitch, tag, DASH } from '../fmt.js';
import { render, SERIES_COLORS } from '../charts.js';
import { mountLive } from '../live.js';
import { tickerHref } from '../routes.js';
import { spark } from '../spark.js';
import { formatValue, ordinal } from './risk.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits = 1, suffix = '') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${suffix}` : DASH);
const pctOf = (v) => (present(v) ? `${Math.round(v * 100)}%` : DASH);
const shortDate = (iso) => (iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }).toUpperCase() : DASH);
// The same day without the comma: FRI OCT 9.
const longDate = (iso) => shortDate(iso).replace(',', '');
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

function contributionLine(c) {
  if (!c) return null;
  const chip = (x) => el('a', { href: tickerHref(x.ticker), class: `mchip ${x.contribution_pp >= 0 ? 'up' : 'down'}`,
    title: `${x.ticker} ${pct(x.return_pct)} on the day`, text: `${x.ticker} ${signed(x.contribution_pp, 2)}` });
  const sectors = c.sectors.filter((x) => Math.abs(x.contribution_pp) >= 0.005);
  const top = [...sectors.slice(0, 3), ...sectors.slice(-2).filter((x) => x.contribution_pp < 0 && !sectors.slice(0, 3).includes(x))];
  return el('div', { class: 'ov-contrib' }, [
    el('div', { class: 'ov-contrib-head dim', text: `WHAT MOVED THE S&P 500 · ${c.date} · members' contributions sum to ${signed(c.total_pp, 2)} pp` }),
    el('div', { class: 'ov-chips' }, [...c.leaders.map(chip), ...c.laggards.map(chip)]),
    el('div', { class: 'ov-chips-sectors dim', text: top.map((x) => `${x.sector} ${signed(x.contribution_pp, 2)}`).join(' · ') }),
  ]);
}

function stocksCard(rows, contrib) {
  const body = rows.map((r) => el('tr', {}, [
    el('td', { class: 'ov-name', text: r.label }),
    el('td', { text: present(r.last) ? num(r.last) : DASH }),
    ...['1D', '1W', '1M', 'YTD'].map((k) => el('td', { class: dirClass(r[k]), text: pct(r[k]) })),
    el('td', { class: present(r.from_high_pct) && r.from_high_pct < -0.05 ? 'down' : 'dim',
      title: r.high_date ? `52-week high ${r.high_date}, ${r.sessions_since_high} sessions ago` : '',
      text: present(r.from_high_pct) ? (r.from_high_pct > -0.05 ? 'AT HIGH' : pct(r.from_high_pct, 1)) : DASH }),
    line(r.spark),
  ]));
  return card('STOCKS', el('a', { href: '#markets', class: 'dim', text: 'indices ↗' }), [
    grid(['', 'LAST', '1D', '1W', '1M', 'YTD', 'OFF 52W HIGH', '6M'], body),
    contributionLine(contrib),
  ]);
}

// Index lines rebased to 100 at the start of the period the reader picks.
const PERF_PERIODS = { '1M': 21, '3M': 63, YTD: null, '1Y': 252 };
function performanceCard(perf, eqcap) {
  if (!perf) return card('PERFORMANCE', null, el('div', { class: 'gap', text: 'No index history in this build.' }));
  const node = el('div', { class: 'chart ov-perf' });
  const draw = (period) => {
    const n = perf.dates.length;
    const sessions = PERF_PERIODS[period];
    let start = sessions === null ? perf.dates.findIndex((d) => d.slice(0, 4) === perf.dates[n - 1].slice(0, 4)) - 1 : n - 1 - sessions;
    start = Math.max(0, start);
    const dates = perf.dates.slice(start);
    const names = Object.keys(perf.series);
    render(node, (option, p) => ({
      ...option,
      grid: { left: 40, right: 64, top: 10, bottom: 40 },
      legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
      tooltip: { ...option.tooltip, valueFormatter: (v) => `${v >= 100 ? '+' : ''}${num(v - 100, 1)}%` },
      xAxis: { ...option.xAxis, data: dates },
      yAxis: { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => `${v >= 100 ? '+' : ''}${Math.round(v - 100)}%` } },
      series: names.map((name, i) => {
        const values = perf.series[name].slice(start);
        const base = values[0];
        const color = SERIES_COLORS[i % SERIES_COLORS.length];
        const last = values[values.length - 1] / base * 100;
        return {
          name, type: 'line', showSymbol: false, data: values.map((v) => (v && base ? +(v / base * 100).toFixed(2) : null)),
          lineStyle: { width: i === 0 ? 1.8 : 1.2, color }, itemStyle: { color },
          endLabel: { show: true, color, fontSize: 10, formatter: () => `${last >= 100 ? '+' : ''}${num(last - 100, 1)}%` },
          markLine: i === 0 ? { silent: true, symbol: 'none', data: [{ yAxis: 100 }], lineStyle: { color: p.faint, type: 'dashed' }, label: { show: false } } : undefined,
        };
      }),
    }));
  };
  requestAnimationFrame(() => draw('3M'));
  const gap = eqcap ? el('div', { class: 'ov-note' }, [
    el('span', { class: 'dim', text: 'Equal weight vs cap weight (RSP − SPY): ' }),
    ...['1M', '3M', 'YTD'].flatMap((k, i) => [i ? el('span', { class: 'dim', text: ' · ' }) : null,
      el('span', { class: dirClass(eqcap.gap_pp[k]), text: `${k} ${signed(eqcap.gap_pp[k], 1, 'pp')}` })]).filter(Boolean),
  ]) : null;
  return card('PERFORMANCE · SPY QQQ IWM RSP', periodSwitch(Object.keys(PERF_PERIODS), '3M', draw), [node, gap]);
}

// One tile per sector ETF, coloured by the period's return. Tiles are equal
// in size so small sectors stay readable; the weight is written on each.
function sectorHeatCard(rows) {
  if (!rows?.length) return null;
  const grid = el('div', { class: 'ov-heat' });
  const draw = (period) => {
    const values = rows.map((r) => r[period]).filter(present);
    const scale = Math.max(0.5, ...values.map((v) => Math.abs(v)));
    grid.replaceChildren(...rows.map((r) => {
      const v = r[period];
      const share = present(v) ? Math.round(Math.min(1, Math.abs(v) / scale) * 70) + 8 : 0;
      const colour = present(v) ? `color-mix(in srgb, var(${v >= 0 ? '--up' : '--down'}) ${share}%, var(--panel))` : 'var(--panel)';
      return el('a', { class: 'ov-heat-tile', href: '#rotation', style: `background:${colour}`, title: `${r.sector} (${r.etf}) · ${num(r.weight_pct, 1)}% of the S&P 500` }, [
        el('span', { class: 'ov-heat-name', text: r.etf }),
        el('span', { class: 'ov-heat-value', text: pct(v, 1) }),
        el('span', { class: 'ov-heat-sector', text: r.sector.replace('Information Technology', 'Info Tech').replace('Communication Services', 'Comm Services').replace('Consumer Discretionary', 'Cons Discretionary') }),
      ]);
    }));
  };
  draw('1D');
  return card('SECTORS', periodSwitch(['1D', '1W', '1M', 'YTD'], '1D', draw), [grid,
    el('div', { class: 'ov-note dim', text: 'Sector SPDR ETFs, ordered by index weight; colour scaled to the period\'s largest move. Click for SECTORS.' })]);
}

function breadthChart(h) {
  if (!h) return null;
  const node = el('div', { class: 'chart ov-mid' });
  requestAnimationFrame(() => render(node, (option, p) => ({
    ...option,
    grid: { left: 34, right: 12, top: 10, bottom: 38 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, valueFormatter: (v) => `${num(v, 0)}%` },
    xAxis: { ...option.xAxis, data: h.dates },
    yAxis: { ...option.yAxis, min: 0, max: 100, interval: 25, axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => `${v}%` } },
    series: [
      { name: '% above 50-day', type: 'line', data: h.above_50d, showSymbol: false, lineStyle: { width: 1.2, color: SERIES_COLORS[1] }, itemStyle: { color: SERIES_COLORS[1] },
        markLine: { silent: true, symbol: 'none', data: [{ yAxis: 50 }], lineStyle: { color: p.faint, type: 'dashed' }, label: { show: false } } },
      { name: '% above 200-day', type: 'line', data: h.above_200d, showSymbol: false, lineStyle: { width: 1.6, color: SERIES_COLORS[0] }, itemStyle: { color: SERIES_COLORS[0] } },
    ],
  })));
  return el('div', { class: 'ov-sub' }, [el('div', { class: 'ov-contrib-head dim', text: 'S&P 500 MEMBERS ABOVE THEIR AVERAGES · 1 YEAR' }), node]);
}

function ratesChart(h) {
  if (!h) return null;
  const node = el('div', { class: 'chart ov-mid' });
  const names = Object.keys(h.series);
  requestAnimationFrame(() => render(node, (option, p) => ({
    ...option,
    grid: { left: 38, right: 12, top: 10, bottom: 38 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, valueFormatter: (v) => `${num(v, 2)}%` },
    xAxis: { ...option.xAxis, data: h.dates },
    yAxis: { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => `${num(v, 1)}%` } },
    series: names.map((name, i) => ({ name, type: 'line', data: h.series[name], showSymbol: false, connectNulls: true,
      lineStyle: { width: 1.3, color: SERIES_COLORS[(i + 2) % SERIES_COLORS.length] }, itemStyle: { color: SERIES_COLORS[(i + 2) % SERIES_COLORS.length] } })),
  })));
  return el('div', { class: 'ov-sub' }, [el('div', { class: 'ov-contrib-head dim', text: 'YIELDS · 1 YEAR' }), node]);
}

function upDown(pair, members) {
  if (!pair) return el('td', { class: 'dim', text: DASH });
  const share = members ? pair.up / (pair.up + pair.down || 1) : 0;
  return el('td', { class: 'ov-ud' }, [
    el('span', { class: 'up', text: pair.up }), el('span', { class: 'dim', text: ' / ' }), el('span', { class: 'down', text: pair.down }),
    el('span', { class: 'ov-bar' }, [el('span', { class: 'ov-bar-up', style: `width:${Math.round(share * 100)}%` })]),
  ]);
}

// How many S&P 500 members rose and fell by how much: losses to the left,
// gains to the right, the largest moves on the top row. Bars share one scale
// so the two sides compare directly.
function distributionBlock(dist) {
  const periods = ['1D', '1W', '1M'].filter((k) => dist?.[k]);
  if (!periods.length) return null;
  const body = el('div', { class: 'ov-dist' });
  const summary = el('div', { class: 'ov-dist-summary dim' });
  const draw = (period) => {
    const d = dist[period];
    const labels = [`0–${d.edges[0]}%`, ...d.edges.slice(0, -1).map((e, i) => `${e}–${d.edges[i + 1]}%`), `≥${d.edges[d.edges.length - 1]}%`];
    const max = Math.max(1, ...d.up, ...d.down);
    const bar = (n, side) => el('div', { class: `ov-dist-side ${side}` }, [
      side === 'down' ? el('span', { class: 'ov-dist-n', text: n }) : null,
      el('span', { class: `ov-dist-bar ${side}`, style: `width:${(n / max) * 82}%` }),
      side === 'up' ? el('span', { class: 'ov-dist-n', text: n }) : null,
    ]);
    body.replaceChildren(...labels.map((label, i) => i).reverse().map((i) => el('div', { class: 'ov-dist-row' }, [
      bar(d.down[i], 'down'), el('span', { class: 'ov-dist-label dim', text: labels[i] }), bar(d.up[i], 'up'),
    ])));
    const up = d.up.reduce((a, b) => a + b, 0);
    const down = d.down.reduce((a, b) => a + b, 0);
    summary.replaceChildren(
      el('span', { class: 'down', text: `${down} fell` }), el('span', { text: ' · ' }),
      el('span', { class: 'up', text: `${up} rose` }), el('span', { text: ` · ${d.flat} unchanged · ${d.members} members` }),
    );
  };
  draw(periods[0]);
  return el('div', { class: 'ov-sub' }, [
    el('div', { class: 'ov-dist-head' }, [el('span', { class: 'ov-contrib-head dim', text: 'S&P 500 MEMBERS BY SIZE OF MOVE' }), periodSwitch(periods, periods[0], draw)]),
    body, summary,
  ]);
}

// Today, the two averages, and the highs and lows stay in view with the year's
// chart; the one-week and one-month counts and the size of move sit behind a
// disclosure, for a reader who wants the wider window.
function breadthCard(blocks, history, dist) {
  if (!blocks.length) return card('BREADTH', null, el('div', { class: 'gap', text: 'No member closes in this build.' }));
  const headers = ['', ...blocks.map((b) => `${b.key} · ${b.members}`)];
  const row = (label, cell) => el('tr', {}, [el('td', { class: 'ov-name', text: label }), ...blocks.map(cell)]);
  const share = (v) => el('td', { class: present(v) ? (v >= 50 ? 'up' : 'down') : 'dim', text: present(v) ? `${num(v, 0)}%` : DASH });
  const body = [
    row('Up / down · today', (b) => upDown(b['1D'], b.members)),
    row('Above 50-day average', (b) => share(b.above_50d)),
    row('Above 200-day average', (b) => share(b.above_200d)),
    row('New 52-week highs / lows', (b) => el('td', {}, [
      el('span', { class: 'up', text: b.new_highs ?? DASH }), el('span', { class: 'dim', text: ' / ' }), el('span', { class: 'down', text: b.new_lows ?? DASH }),
    ])),
  ];
  const wider = [
    row('Up / down · 1 week', (b) => upDown(b['1W'], b.members)),
    row('Up / down · 1 month', (b) => upDown(b['1M'], b.members)),
  ];
  return card('BREADTH', el('span', { class: 'dim', text: 'index members, counted by their own closes' }), [
    grid(headers, body, 'ov-breadth'),
    breadthChart(history),
    el('details', { class: 'ov-more' }, [
      el('summary', { text: 'MORE BREADTH · 1W / 1M and size of move' }),
      grid(headers, wider, 'ov-breadth'),
      distributionBlock(dist),
    ]),
  ]);
}

// Rising yields and wider spreads are red (bond prices fall, conditions
// tighten); the curve's slope has no good or bad direction and stays grey.
function rateClass(row, change) {
  if (!present(change) || change === 0 || row.key === '2s10s') return 'dim';
  return change > 0 ? 'down' : 'up';
}

function ratesCard(rows, fed, history) {
  const level = (r) => (!present(r.value) ? DASH : r.unit === 'bp' ? `${num(r.value, 0)}bp` : `${num(r.value, 2)}%`);
  const body = rows.map((r) => el('tr', { title: r.date ? `${r.source}, ${r.date}` : '' }, [
    el('td', { class: 'ov-name', text: r.label }),
    el('td', { text: level(r) }),
    ...['change_1d_bp', 'change_1w_bp', 'change_1m_bp'].map((k) => el('td', { class: rateClass(r, r[k]), text: signed(r[k], 0) })),
    line(r.spark),
  ]));
  const foot = fed ? el('div', { class: 'ov-fed' }, [
    el('a', { href: '#priced', text: `NEXT FOMC ${shortDate(fed.date)}` }),
    el('span', { text: ` priced ${signed(fed.change_bp, 1, 'bp')}` }),
    el('span', { class: 'dim', text: ` · P(${fed.step.direction === 'hold' ? 'hold' : fed.step.direction}) ${pctOf(fed.step.whole_steps ? 1 : fed.step.p_next_step)} · Kalshi ${pctOf(fed.kalshi_p_hike)} · Polymarket ${pctOf(fed.polymarket_p_hike)} hike · by ${shortDate(fed.year_end.date)} ${signed(fed.year_end.cumulative_bp, 0, 'bp')}` }),
  ]) : el('div', { class: 'ov-fed dim', text: 'Fed pricing was not built for this session.' });
  const dates = [...new Set(rows.filter((r) => r.date).map((r) => `${r.source} ${r.date}`))];
  return card('RATES & CREDIT', el('a', { href: '#rates', class: 'dim', text: 'rates & macro ↗' }), [
    grid(['', 'LEVEL', '1D bp', '1W bp', '1M bp', '6M'], body),
    ratesChart(history),
    el('div', { class: 'note-text', text: `As of: ${dates.join(' · ')}. Yields from Treasury's par curve, published the evening of the session; the TIPS yield and ICE spreads from FRED, a day later.` }),
    foot,
  ]);
}

// MOVE beside VIX: each one's place in its own last year, the ratio's place in
// RISK's weekly history, and -- when they disagree by a wide margin -- which
// market is calm while the other is not.
const VOL_READINGS = {
  rates: ['RATES STRESS, EQUITIES CALM', 'warn', 'Treasury volatility is high for its year while the VIX is low: rate risk the stock market is not showing.'],
  equities: ['EQUITY STRESS, RATES CALM', 'warn', 'The VIX is high for its year while Treasury volatility is low: the strain is in stocks, not in rates.'],
  both: ['BOTH ELEVATED', 'down', 'Both are high for their year.'],
  in_line: ['IN LINE', 'dim', 'Neither is far from the other against its own year.'],
};

export function volReading(vol) {
  return vol && VOL_READINGS[vol.reading] ? VOL_READINGS[vol.reading] : null;
}

function volLine(vol) {
  const reading = volReading(vol);
  if (!vol || !reading) return null;
  const [label, tone, text] = reading;
  return el('div', { class: 'ov-vol' }, [
    el('div', { class: 'ov-vol-head' }, [
      el('span', { class: 'dim', text: 'BOND VS EQUITY VOLATILITY' }),
      tag(label, tone),
      el('a', { href: '#risk', class: 'dim', text: 'risk ↗' }),
    ]),
    el('div', { class: 'ov-vol-stats', text: `MOVE ${num(vol.move, 1)} (1Y ${ordinal(vol.move_pct_1y)}) · VIX ${num(vol.vix, 1)} (1Y ${ordinal(vol.vix_pct_1y)})`
      + ` · MOVE/VIX ${num(vol.ratio, 1)}${vol.ratio_pct !== null && vol.ratio_pct !== undefined ? `, ${ordinal(vol.ratio_pct)} since ${String(vol.ratio_since || '').slice(0, 4)} (weekly)` : ''}` }),
    el('div', { class: 'note-text', text: `${text} MOVE is the implied volatility of one-month Treasury options, in basis points of yield; its line on RISK is ${num(vol.move_threshold, 0)}.` }),
  ]);
}

function crossCard(rows, vol) {
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
  return card('DOLLAR, COMMODITIES & VOLATILITY', el('span', { class: 'dim', text: 'VIX and MOVE change in points' }),
    [grid(['', 'LAST', '1D', '1W', '1M', 'YTD', '6M'], body), volLine(vol)].filter(Boolean));
}

// Banks are valued on tangible book, and only beside what they earn on it:
// each bank group's P/TBV against its own ten years, with its ROTCE. Only
// the groups VALUATION can draw it for (not insurers or payments).
function bankBookCard(rows) {
  if (!rows?.length) return null;
  const body = rows.map((r) => el('tr', {}, [
    el('td', { class: 'ov-name', title: `${r.companies} index members, cap-weighted; 10Y since ${r.since}`, text: r.label }),
    el('td', { text: `${num(r.ptbv, 2)}x` }),
    el('td', { class: r.percentile >= 80 ? 'down' : r.percentile <= 20 ? 'up' : 'dim', text: ordinal(r.percentile) }),
    el('td', { class: 'dim', text: `${num(r.median, 2)}x` }),
    el('td', { text: present(r.rotce) ? `${num(r.rotce, 1)}%` : DASH }),
  ]));
  return card('BANKS · PRICE / TANGIBLE BOOK', el('a', { href: '#valuation', class: 'dim', text: 'valuation ↗' }),
    grid(['', 'P/TBV', '10Y PCTL', 'MEDIAN', 'ROTCE'], body));
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
    risk.fear_greed ? el('span', { class: 'ov-fg' }, [
      el('span', { class: 'dim', text: ' · Fear & Greed (self-computed) ' }),
      el('span', { class: risk.fear_greed.score < 45 ? 'down' : risk.fear_greed.score > 55 ? 'up' : '', text: `${num(risk.fear_greed.score, 0)} ${risk.fear_greed.rating}` }),
    ]) : null,
    el('span', { class: 'dim', text: ' →' }),
  ]);
}

export default function renderOverview(root, data) {
  const missing = data.missing || [];
  const failed = Object.keys(data.failed || {});
  root.append(metaRow(`OVERVIEW · SESSION ${data.as_of}${missing.length ? ` · NOT BUILT THIS SESSION: ${missing.join(', ').toUpperCase()}` : ''}${failed.length ? ` · ${failed.length} SOURCE(S) FAILED` : ''}`, [
    'Closing figures of the session above; the live strip is the only thing that moves during the day. Lines are the last six months.',
    'Stocks: the S&P 500 and Nasdaq 100 rows are index levels (price only); the Russell 2000 and equal-weighted S&P 500 rows are IWM and RSP on dividend-adjusted closes. Off 52W high is the drawdown from the highest close of the last 252 sessions.',
    'Performance draws SPY, QQQ, IWM and RSP, all on dividend-adjusted closes so none is credited with dividends the others lack, rebased to 100 at the start of the period chosen.',
    'What moved the S&P 500: each member\'s published weight times its return on the day, in percentage points of the index; the members\' sum differs slightly from the index\'s own change. Equal weight vs cap weight: RSP against SPY, the gap in percentage points of return over 1M, 3M and YTD; a falling line means the average stock is lagging the largest ones.',
    'Size of move: each S&P 500 member\'s return over the day, week (5 sessions) or month (21 sessions), counted into buckets whose edges widen with the window (1D 1/2/4%, 1W 2/5/10%, 1M 5/10/20%); a bucket includes its lower edge.',
    'Breadth counts each index\'s members by their own closes: how many rose and fell over a day, a week (5 sessions) and a month (21 sessions), the share above their 50- and 200-day averages, and how many closed at a 52-week high or low.',
    'Rates and credit: a rising yield or a widening spread is red (bond prices fall, conditions tighten), a falling one green; the 10Y − 2Y slope stays grey. The 2Y and 10Y are Treasury\'s daily par yields, published the evening of the session; the 10-year TIPS yield and the ICE BofA spreads are FRED\'s, a day behind. Macro prints are the latest published value with the one before it; GDPNow is the Atlanta Fed\'s running estimate for the current quarter.',
    ...failed.map((k) => `${k}: ${data.failed[k]}`),
  ]));
  root.append(el('div', { class: 'ov-live' }, [mountLive({ asOf: data.as_of })]));
  // The line between the live strip and the build's close: everything below is
  // the session's close, whatever the strip above says.
  root.append(el('div', { class: 'ov-close-head', text: `SESSION CLOSE · ${longDate(data.as_of)} — every figure below` }));
  const risk = riskLine(data.risk);
  if (risk) root.append(risk);
  // Two columns that stack independently, so a short card never leaves a
  // hole beside a tall one. Read top to bottom: how stocks did and why,
  // where rates are, then breadth, the rest of the market and what is next.
  root.append(el('div', { class: 'ov-columns' }, [
    el('div', { class: 'ov-col' }, [
      stocksCard(data.stocks, data.contributions),
      sectorHeatCard(data.sectors),
      bankBookCard(data.bank_book),
      ratesCard(data.rates, data.fed, data.rates_history),
      printsCard(data.prints),
    ].filter(Boolean)),
    el('div', { class: 'ov-col' }, [
      performanceCard(data.performance, data.equal_vs_cap),
      breadthCard(data.breadth, data.breadth_history, data.distribution),
      crossCard(data.cross_asset, data.vol),
      aheadCard(data.ahead),
    ].filter(Boolean)),
  ]));
}
