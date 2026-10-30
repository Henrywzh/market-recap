// Cards shared by INDICES and EUROPE: what moved an index (each member's weight
// times its return), how index lines performed, and the bond-vs-equity
// volatility reading. Each is a pure render, so the numbers are the session's
// close wherever they are drawn. Breadth is in index-history.js.

import { el, card, num, pct, dirClass, periodSwitch, tag, DASH } from './fmt.js';
import { render, SERIES_COLORS } from './charts.js';
import { tickerHref } from './routes.js';
import { ordinal } from './tabs/risk.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits = 1, suffix = '') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${suffix}` : DASH);

// --- what moved the S&P 500 ----------------------------------------------------

// A name with no ticker page here (a European member) is a plain chip.
function contributionChip(x, link = true) {
  return el(link ? 'a' : 'span', { href: link ? tickerHref(x.ticker) : undefined, class: `mchip ${x.contribution_pp >= 0 ? 'up' : 'down'}`,
    title: `${x.name ? `${x.name} · ` : ''}${x.ticker} ${pct(x.return_pct)} on the day`, text: `${x.ticker} ${signed(x.contribution_pp, 2)}` });
}

// The leaders and laggards as chips, then the sectors that carried the day.
function contributionBody(c, link = true) {
  const sectors = c.sectors.filter((x) => Math.abs(x.contribution_pp) >= 0.005);
  const top = [...sectors.slice(0, 3), ...sectors.slice(-2).filter((x) => x.contribution_pp < 0 && !sectors.slice(0, 3).includes(x))];
  return el('div', { class: 'ov-contrib' }, [
    el('div', { class: 'ov-chips' }, [...c.leaders.map((x) => contributionChip(x, link)), ...c.laggards.map((x) => contributionChip(x, link))]),
    el('div', { class: 'ov-chips-sectors dim', text: top.map((x) => `${x.sector} ${signed(x.contribution_pp, 2)}`).join(' · ') }),
  ]);
}

export function contributionsCard(c, { index = 'S&P 500', link = true, note = 'Each member\'s published weight times its return on the day, in percentage points of the index.' } = {}) {
  if (!c) return null;
  const check = present(c.index_pct) ? ` · index ${signed(c.index_pct, 2)}%` : '';
  return card(`WHAT MOVED THE ${index}`, el('span', { class: 'dim', text: `${c.date} · members sum to ${signed(c.total_pp, 2)} pp${check}` }), [
    contributionBody(c, link),
    el('div', { class: 'note-text', text: note }),
  ]);
}

// --- performance ---------------------------------------------------------------

// Index lines rebased to 100 at the start of the period the reader picks.
const PERF_PERIODS = { '1M': 21, '3M': 63, YTD: null, '1Y': 252 };

export function performanceCard(perf, eqcap, title = 'PERFORMANCE · SPY QQQ IWM RSP') {
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
  return card(title, periodSwitch(Object.keys(PERF_PERIODS), '3M', draw), [node, gap]);
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
