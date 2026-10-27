// BY VALUATION: how much stocks pay over bonds, four ways, each against its own
// history. Valuation context for multi-year returns, not a timing signal. The
// arithmetic stays apart from the DOM so it can be tested under node.

import { el, card, num, periodSwitch, DASH } from './fmt.js';
import { render, disposeWithin } from './charts.js';

const TITLE = 'STOCKS vs BONDS · HOW MUCH STOCKS PAY OVER BONDS';
const NOTE = 'Valuation context for multi-year returns, not a timing signal. Trailing operating earnings; Damodaran is monthly; Shiller uses ten-year average earnings.';
const CHART_NOTE = 'Each line ranks its measure within its own history up to that date, from the first point shown (2016). Dashed lines at 25 and 75. Tile percentiles use the full history, so the last point can differ from them.';
const SCOPE_NOTE = 'NDX applies to the real premium and the credit spread; the ERP and CAPE yield are S&P 500 series.';
const INDICES = ['SPX', 'NDX'];

const finite = (v) => typeof v === 'number' && Number.isFinite(v);
// A rank needs this many points before it means anything: an early reading
// would be a rank against almost nothing.
export const MIN_POINTS = 52;

// The four measures, in the order the card shows them. ``indexed`` measures
// follow the SPX/NDX switch; the tile-based ones are S&P 500 only.
export const MEASURE_DEFS = [
  {
    key: 'real', short: 'Real premium', label: 'REAL EQUITY PREMIUM', indexed: true,
    field: 'spread_real10y_pct', percentile: 'spread_real10y_percentile',
    why: 'Trailing operating earnings yield less the 10-year TIPS real yield. Both sides are real, so inflation does not distort the comparison.',
  },
  {
    key: 'erp', short: 'Implied ERP', label: 'IMPLIED ERP (DAMODARAN)', indexed: false, tile: 'erp_damodaran',
    why: 'Implied equity risk premium. It includes dividends, buybacks and expected growth, not just one year of earnings. S&P 500.',
  },
  {
    key: 'ecy', short: 'Excess CAPE yield', label: 'EXCESS CAPE YIELD (SHILLER)', indexed: false, tile: 'ecy',
    why: 'Earnings over ten years, so slow-moving; the longest history here (from 1962). S&P 500.',
  },
  {
    key: 'credit', short: 'Stocks vs credit', label: 'STOCKS vs CREDIT', indexed: true,
    field: 'spread_baa_pct', percentile: 'spread_baa_percentile',
    why: 'Operating earnings yield less Moody\'s BAA corporate yield: the same companies\' shares against their bonds.',
  },
];

// Share of the finite values at or below ``latest``, 0-100, latest included.
// Null when there is nothing to rank against.
export function percentileOf(values, latest) {
  if (!finite(latest)) return null;
  const known = (values || []).filter(finite);
  if (!known.length) return null;
  return (100 * known.filter((v) => v <= latest).length) / known.length;
}

// A low premium means stocks are dear against bonds, so the words read the
// measure's own percentile: dear at the bottom, cheap at the top.
export function wordFor(percentile) {
  if (!finite(percentile)) return null;
  if (percentile <= 10) return 'very dear';
  if (percentile <= 25) return 'dear';
  if (percentile >= 90) return 'very cheap';
  if (percentile >= 75) return 'cheap';
  return 'middle';
}

// The CSS tone of a word: dear words share one colour, cheap words another.
export function toneFor(word) {
  if (word === 'dear' || word === 'very dear') return 'dear';
  if (word === 'cheap' || word === 'very cheap') return 'cheap';
  if (word === 'middle') return 'middle';
  return null;
}

// For each point, the percentile of its value within the history up to and
// including that point. Nulls stay null, and a point is ranked only once the
// window holds ``minPoints`` values. Nothing after the point is used.
export function rollingPercentile(values, minPoints = MIN_POINTS) {
  const seen = [];
  return values.map((v) => {
    if (!finite(v)) return null;
    seen.push(v);
    if (seen.length < minPoints) return null;
    return (100 * seen.filter((x) => x <= v).length) / seen.length;
  });
}

// [date, rank] pairs for the chart, with the unranked points left out.
export function rollingPoints(dates, values) {
  const ranks = rollingPercentile(values);
  const out = [];
  for (let i = 0; i < Math.min(dates.length, ranks.length); i += 1) {
    if (finite(ranks[i])) out.push([dates[i], ranks[i]]);
  }
  return out;
}

const ordinalSuffix = (n) => {
  if (n % 100 >= 11 && n % 100 <= 13) return 'th';
  return { 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th';
};

// "12th" for 12, "2nd" for 2 (the percentile is shown whole).
export function ordinal(value) {
  const n = Math.round(value);
  return `${n}${ordinalSuffix(n)}`;
}

// The percentile line of a tile: its rank and the span it is ranked over.
export function percentileText(measure) {
  if (!finite(measure?.percentile) || !measure.span) return DASH;
  return `${ordinal(measure.percentile)} pct since ${measure.span}`;
}

// One line, counts only: never an average, never a score.
export function stocksBondsSummary(measures) {
  const known = (measures || []).filter((m) => finite(m.percentile));
  if (!known.length) return null;
  const dear = known.filter((m) => m.percentile <= 25).length;
  const noun = known.length === 1 ? 'measure' : 'measures';
  return `${dear} of ${known.length} ${noun} put stocks in the dearest quarter of their history vs bonds`;
}

const yearOf = (date) => String(date ?? '').slice(0, 4);

function tileOf(data, key) {
  for (const section of data?.sections || []) {
    const tile = (section.tiles || []).find((t) => t.key === key);
    if (tile) return tile;
  }
  return null;
}

// A fed_model series on the operating basis for one index. The artifact's own
// percentile is used when it has one; it is ranked over the whole history shown.
function fedSeries(fm, index, def) {
  const op = fm?.indices?.find((ix) => ix.key === index)?.operating;
  const values = op?.history?.[def.field];
  if (!finite(op?.[def.field]) || !Array.isArray(values)) return null;
  return {
    value: op[def.field],
    date: fm.as_of,
    dates: fm.dates || [],
    values,
    percentile: finite(op[def.percentile]) ? op[def.percentile] : percentileOf(values, op[def.field]),
    span: yearOf(fm.dates?.[0]),
  };
}

// A risk tile: its own latest value, percentile over its full history (pct_long)
// and its weekly or monthly history.
function tileSeries(tile) {
  if (!tile || !finite(tile.value)) return null;
  const dates = tile.history?.dates || [];
  const values = tile.history?.values || [];
  const hasLong = finite(tile.pct_long);
  return {
    value: tile.value,
    date: tile.date,
    dates,
    values,
    percentile: hasLong ? tile.pct_long : percentileOf(values, tile.value),
    span: hasLong && tile.since ? yearOf(tile.since) : yearOf(dates[0]),
  };
}

// The card's data: the four measures for one index, or null when neither the
// fed_model nor the tiles carry any of them.
export function stocksBondsModel(data, index = 'SPX') {
  const fm = data?.context?.fed_model;
  const measures = MEASURE_DEFS.map((def) => {
    const series = def.tile ? tileSeries(tileOf(data, def.tile)) : fedSeries(fm, index, def);
    const base = {
      key: def.key, short: def.short, label: def.label, why: def.why,
      scope: def.indexed ? index : 'SPX',
    };
    if (!series) {
      return { ...base, value: null, date: null, percentile: null, span: null, word: null, tone: null, points: [] };
    }
    const word = wordFor(series.percentile);
    return {
      ...base,
      value: series.value,
      date: series.date,
      percentile: series.percentile,
      span: series.span,
      word,
      tone: toneFor(word),
      points: rollingPoints(series.dates, series.values),
    };
  });
  if (!measures.some((m) => m.value !== null)) return null;
  return { index, asOf: fm?.as_of ?? null, measures, summary: stocksBondsSummary(measures) };
}

const hasNdx = (data) => Boolean(data?.context?.fed_model?.indices?.some((ix) => ix.key === 'NDX' && ix.operating));

function tile(m) {
  const info = el('span', { class: 'rc-info', title: m.why, 'aria-label': m.why, text: 'ⓘ' });
  const head = el('div', { class: 'sb-name' }, [el('span', { text: m.label }), info]);
  if (m.value === null) {
    return el('div', { class: 'sb-tile' }, [head, el('div', { class: 'sb-value', text: DASH }), el('div', { class: 'sb-meta', text: 'not in the artifact' })]);
  }
  return el('div', { class: 'sb-tile' }, [
    head,
    el('div', { class: 'sb-value', text: `${num(m.value, 2)}%` }),
    el('div', { class: 'sb-meta', text: `${m.scope} · as of ${m.date}` }),
    el('div', { class: 'sb-meta', text: percentileText(m) }),
    el('span', { class: `sb-tag ${m.tone}`, text: m.word }),
  ]);
}

function drawChart(node, measures) {
  const drawn = measures.filter((m) => m.points.length);
  render(node, (option, p) => {
    const colours = [p.accent, p.blue, p.purple, p.dim];
    return {
      ...option,
      grid: { ...option.grid, top: 30 },
      legend: {
        top: 0, right: 0, itemWidth: 14, itemHeight: 2,
        textStyle: { color: p.dim, fontSize: 10 },
        data: drawn.map((m) => m.short),
      },
      xAxis: { ...option.xAxis, type: 'time' },
      yAxis: { ...option.yAxis, scale: false, min: 0, max: 100, interval: 25 },
      series: [
        ...drawn.map((m, i) => ({
          name: m.short, type: 'line', showSymbol: false, data: m.points,
          lineStyle: { width: 1.3, color: colours[i] }, itemStyle: { color: colours[i] },
        })),
        // Reference lines live on their own series, so hiding a legend entry
        // never hides them. It is not in the legend.
        {
          name: 'reference', type: 'line', data: [], silent: true,
          markLine: {
            silent: true, symbol: 'none', label: { show: false },
            lineStyle: { color: p.faint, type: 'dashed' },
            data: [{ yAxis: 25 }, { yAxis: 75 }],
          },
        },
      ],
    };
  });
}

// The STOCKS vs BONDS card, or null when there is no data for it.
export function stocksBondsCard(data) {
  if (!stocksBondsModel(data)) return null;
  const ndx = hasNdx(data);
  let index = 'SPX';
  const body = el('div', {});
  const draw = () => {
    disposeWithin(body);
    body.replaceChildren();
    const model = stocksBondsModel(data, index);
    const chart = el('div', { class: 'chart sb-chart' });
    const parts = [];
    if (model.summary) parts.push(el('div', { class: 'sb-summary', text: model.summary }));
    parts.push(el('div', { class: 'sb-grid' }, model.measures.map(tile)));
    if (model.measures.some((m) => m.points.length)) {
      parts.push(chart, el('div', { class: 'field-note', text: CHART_NOTE }));
    }
    if (ndx) parts.push(el('div', { class: 'field-note', text: SCOPE_NOTE }));
    parts.push(el('div', { class: 'field-note', text: NOTE }));
    body.append(...parts);
    if (model.measures.some((m) => m.points.length)) {
      requestAnimationFrame(() => drawChart(chart, model.measures));
    }
  };
  const switcher = ndx ? periodSwitch(INDICES, index, (label) => { index = label; draw(); }) : null;
  draw();
  return card(TITLE, switcher, body);
}
