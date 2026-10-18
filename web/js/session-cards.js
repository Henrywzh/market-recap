// The session cards that used to make up OVERVIEW and now sit on INDICES:
// how breadth moved (counts, the year's chart, the wider windows), what moved
// the S&P 500, how the four index lines performed, and the bond-vs-equity
// volatility reading. Each is a pure render from overview.json, so the numbers
// are the session's close wherever they are drawn.

import { el, card, num, pct, dirClass, periodSwitch, tag, DASH } from './fmt.js';
import { render, SERIES_COLORS } from './charts.js';
import { tickerHref } from './routes.js';
import { ordinal } from './tabs/risk.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits = 1, suffix = '') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${suffix}` : DASH);

function grid(headers, rows, cls = '') {
  return el('div', { class: 'table-scroll' }, [el('table', { class: `data ov-table ${cls}` }, [
    el('thead', {}, [el('tr', {}, [...headers].map((h) => el('th', { text: h })))]),
    el('tbody', {}, rows),
  ])]);
}

// --- what moved the S&P 500 ----------------------------------------------------

function contributionChip(x) {
  return el('a', { href: tickerHref(x.ticker), class: `mchip ${x.contribution_pp >= 0 ? 'up' : 'down'}`,
    title: `${x.ticker} ${pct(x.return_pct)} on the day`, text: `${x.ticker} ${signed(x.contribution_pp, 2)}` });
}

// The leaders and laggards as chips, then the sectors that carried the day.
function contributionBody(c) {
  const sectors = c.sectors.filter((x) => Math.abs(x.contribution_pp) >= 0.005);
  const top = [...sectors.slice(0, 3), ...sectors.slice(-2).filter((x) => x.contribution_pp < 0 && !sectors.slice(0, 3).includes(x))];
  return el('div', { class: 'ov-contrib' }, [
    el('div', { class: 'ov-chips' }, [...c.leaders.map(contributionChip), ...c.laggards.map(contributionChip)]),
    el('div', { class: 'ov-chips-sectors dim', text: top.map((x) => `${x.sector} ${signed(x.contribution_pp, 2)}`).join(' · ') }),
  ]);
}

export function contributionsCard(c) {
  if (!c) return null;
  return card('WHAT MOVED THE S&P 500', el('span', { class: 'dim', text: `${c.date} · members sum to ${signed(c.total_pp, 2)} pp` }), [
    contributionBody(c),
    el('div', { class: 'note-text', text: 'Each member\'s published weight times its return on the day, in percentage points of the index.' }),
  ]);
}

// --- performance ---------------------------------------------------------------

// Index lines rebased to 100 at the start of the period the reader picks.
const PERF_PERIODS = { '1M': 21, '3M': 63, YTD: null, '1Y': 252 };

export function performanceCard(perf, eqcap) {
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

// --- breadth -------------------------------------------------------------------

function upDown(pair, members) {
  if (!pair) return el('td', { class: 'dim', text: DASH });
  const share = members ? pair.up / (pair.up + pair.down || 1) : 0;
  return el('td', { class: 'ov-ud' }, [
    el('span', { class: 'up', text: pair.up }), el('span', { class: 'dim', text: ' / ' }), el('span', { class: 'down', text: pair.down }),
    el('span', { class: 'ov-bar' }, [el('span', { class: 'ov-bar-up', style: `width:${Math.round(share * 100)}%` })]),
  ]);
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
export function breadthCard(blocks, history, dist) {
  if (!blocks?.length) return card('BREADTH', null, el('div', { class: 'gap', text: 'No member closes in this build.' }));
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

// --- bond vs equity volatility -------------------------------------------------

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

export function volatilityLine(vol) {
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

// The four session cards in reading order, from one overview.json. A card whose
// input is absent drops out rather than leaving a hole.
export function sessionCards(overview) {
  return [
    breadthCard(overview.breadth, overview.breadth_history, overview.distribution),
    contributionsCard(overview.contributions),
    performanceCard(overview.performance, overview.equal_vs_cap),
    volatilityLine(overview.vol),
  ].filter(Boolean);
}
