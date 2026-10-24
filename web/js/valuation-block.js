// VALUATION: one section, the same wherever something is valued -- a sector, a
// sub-industry, a theme, a K-SHAPE leg, a SIZE & STYLE arm, one company. It
// answers three questions in the same order everywhere:
//
//   what the market pays and expects   a strip: trailing P/E and where it sits
//                                      in its own ten years, forward P/E,
//                                      expected EPS growth, revenue growth and
//                                      operating margin, each beside the
//                                      benchmark's
//   is that price backed by the        two charts: the trailing P/E over ten
//   business                           years with its median and middle half;
//                                      revenue growth and margins by fiscal year
//   against the benchmark              the P/E premium and why the ratio moved
//                                      (basket-view.js relativeCards)
//
// valuationBlock({ name, benchmark, own, other, reference, referenceLabel })
//   own / other: { valuation: {dates, pe, stats, price?, earnings?},
//                  outlook: {forward_pe, eps_growth_next, revenue_growth},
//                  history: {years, revenue_growth, gross_margin, operating_margin} }
//   other (the benchmark) may be null; any part may be missing in an older build.
//   reference: the real ratio {dates, ratio}, only where membership changes.

import { el, card, num, gap, sectionTitle, periodSwitch, DASH } from './fmt.js';
import { render } from './charts.js';
import { relativeCards } from './basket-view.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits = 1, unit = '%') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${unit}` : DASH);
const times = (v) => (present(v) ? `${num(v, 1)}×` : DASH);

// 1st, 2nd, 3rd, 4th ... 11th, 12th, 13th, 21st.
export function ordinalOf(v) {
  const n = Math.round(v);
  const tail = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
  return `${n}${tail}`;
}

function chartNode(height = 240) {
  return el('div', { class: 'chart', style: `height:${height}px` });
}

// The last year a history has a figure for, and that figure.
export function lastOf(history, field) {
  const years = history?.years || [];
  const values = history?.[field] || [];
  for (let i = values.length - 1; i >= 0; i -= 1) if (present(values[i])) return { year: years[i], value: values[i] };
  return null;
}

// A history cut to the years that have at least one figure (a fiscal year
// still being reported is dropped rather than drawn as a gap at the end).
export function trimHistory(history) {
  if (!history?.years?.length) return null;
  const fields = ['revenue_growth', 'gross_margin', 'operating_margin'];
  const keep = history.years.map((_, i) => fields.some((f) => present(history[f]?.[i])));
  let end = keep.lastIndexOf(true);
  if (end < 0) return null;
  const start = keep.indexOf(true);
  end += 1;
  return Object.fromEntries([['years', history.years.slice(start, end)],
    ...fields.map((f) => [f, (history[f] || []).slice(start, end)])]);
}

function versus(a, b, format) {
  if (!present(a)) return DASH;
  return present(b) ? `${format(a)} vs ${format(b)}` : format(a);
}

// The strip's cells, as data (tested): label, value, note.
export function stripCells(name, benchmark, own, other) {
  const st = own?.valuation?.stats || {};
  const o = own?.outlook || {};
  const b = other?.outlook || {};
  const margin = lastOf(own?.history, 'operating_margin');
  const marginB = lastOf(other?.history, 'operating_margin');
  const premium = present(o.forward_pe) && present(b.forward_pe) ? (o.forward_pe / b.forward_pe - 1) * 100 : null;
  const against = benchmark ? ` · vs ${benchmark}` : '';
  return [
    { label: 'TRAILING P/E', value: times(st.current),
      note: present(st.percentile) ? `${ordinalOf(st.percentile)} pctl of its own ten years · median ${times(st.median)} · history, not fair value` : 'too little history to rank' },
    { label: 'FORWARD P/E · NTM', value: versus(o.forward_pe, b.forward_pe, times),
      note: present(premium) ? `${name} at a ${num(Math.abs(premium), 0)}% ${premium >= 0 ? 'premium' : 'discount'}${against}` : 'consensus, next twelve months' },
    { label: 'EPS GROWTH · NEXT FY', value: versus(o.eps_growth_next, b.eps_growth_next, (v) => signed(v, 0)), note: `consensus${against}` },
    { label: 'REVENUE GROWTH · TTM', value: versus(o.revenue_growth, b.revenue_growth, (v) => signed(v, 0)), note: `from filings${against}` },
    { label: `OPERATING MARGIN${margin ? ` · FY${margin.year}` : ''}`,
      value: versus(margin?.value, marginB?.value, (v) => `${num(v, 1)}%`),
      note: `pre-tax where there is no operating line${against}` },
  ];
}

function strip(cells) {
  return el('div', { class: 'stat-strip' }, cells.map((c) => el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: c.label }),
    el('div', { class: 'stat-value', text: c.value }),
    c.note ? el('div', { class: 'stat-note', text: c.note }) : null,
  ].filter(Boolean))));
}

// The axis of a company's band stops at this multiple of its 90th percentile
// when a spike (earnings near zero) would flatten the rest, as its P/E history
// chart always did. Sectors and baskets are not capped.
const BAND_AXIS_CAP = 1.6;

// `view` is one basis: {name, dates, pe, stats}. `compare`, when given, is the
// other basis, drawn as a thin dashed line so the switch's effect is visible.
function bandChart(node, view, { compare = null, capAxis = false } = {}) {
  const st = view.stats;
  const capped = capAxis && st.max > st.p90 * BAND_AXIS_CAP ? Math.ceil(st.p90 * BAND_AXIS_CAP) : null;
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, right: 92, top: compare ? 24 : 14, bottom: 30 },
    legend: compare ? { top: 0, textStyle: { color: p.dim, fontSize: 9 }, itemWidth: 10, itemHeight: 2 } : undefined,
    tooltip: { ...option.tooltip, valueFormatter: (v) => times(v) },
    xAxis: { ...option.xAxis, data: view.dates },
    yAxis: {
      ...option.yAxis,
      min: (v) => Math.floor(Math.min(v.min, st.p25) * 0.95),
      max: capped ?? ((v) => Math.ceil(Math.max(v.max, st.p75) * 1.05)),
      axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${v}×` },
    },
    series: [
      ...(compare ? [{
        name: compare.name, type: 'line', data: compare.pe, showSymbol: false, connectNulls: false, z: 1,
        lineStyle: { width: 1, color: p.faint, type: 'dashed' }, itemStyle: { color: p.faint },
      }] : []),
      {
        name: view.name, type: 'line', data: view.pe, showSymbol: false, connectNulls: false, z: 2,
        lineStyle: { width: 1.4, color: p.text }, itemStyle: { color: p.text },
        markArea: { silent: true, itemStyle: { color: p.accent, opacity: 0.12 }, data: [[{ yAxis: st.p25 }, { yAxis: st.p75 }]] },
        markLine: {
          silent: true, symbol: 'none', label: { color: p.dim, fontSize: 10, position: 'end', formatter: (d) => d.name },
          data: [{ name: `median ${times(st.median)}`, yAxis: st.median, lineStyle: { color: p.accent, type: 'dashed' } }],
        },
      },
    ],
  }));
}

const BASIS_WORDS = { operating: 'OPERATING', ex_gains: 'EX GAINS', reported: 'REPORTED' };
const basisWord = (basis) => BASIS_WORDS[basis] || String(basis || 'reported').replace(/_/g, ' ').toUpperCase();

// The trailing P/E band of one valuation. A company whose history has a second
// earnings basis (operating against reported EPS) gets the switch; the others get
// the plain card, exactly as before.
function trailingPeCard(valuation, capAxis, historyFold) {
  const alt = valuation.alternate?.pe?.length && valuation.alternate.stats
    ? { basis: valuation.alternate.basis, pe: valuation.alternate.pe, stats: valuation.alternate.stats } : null;
  const views = [{ basis: valuation.basis, pe: valuation.pe, stats: valuation.stats }, ...(alt ? [alt] : [])]
    .map((v) => ({ ...v, dates: valuation.dates, name: alt ? basisWord(v.basis).toLowerCase() : 'trailing P/E' }));
  let active = views[0];
  const titleOf = (v) => `TRAILING P/E · ${views.length > 1 ? `${basisWord(v.basis)} ` : ''}${times(v.stats.current)} · `
    + `${present(v.stats.percentile) ? ordinalOf(v.stats.percentile) : DASH} OF ITS OWN TEN YEARS`;
  const node = chartNode();
  const draw = () => bandChart(node, active, { compare: views.length > 1 ? views.find((v) => v !== active) : null, capAxis });
  const note = el('span', { class: 'dim', text: 'weekly · historical band, not a valuation target' });
  const right = views.length > 1
    ? el('span', { class: 'tag-row' }, [note, periodSwitch(views.map((v) => basisWord(v.basis)), basisWord(active.basis), (word) => {
      active = views.find((v) => basisWord(v.basis) === word);
      cardNode.querySelector('.card-title').textContent = titleOf(active);
      draw();
    })])
    : note;
  const cardNode = card(titleOf(active), right, [node]);
  // Hidden details have no layout width. Initialise only after opening and
  // redraw on reopening so the canvas fits the current viewport.
  if (historyFold) historyFold.addEventListener('toggle', () => {
    if (historyFold.open) requestAnimationFrame(() => { if (historyFold.open && node.isConnected) draw(); });
  });
  else queueMicrotask(draw);
  return cardNode;
}

// Revenue growth as bars (left axis), margins as lines (right axis); the
// benchmark's operating margin dashed, when there is one.
function businessChart(node, own, other, name, benchmark) {
  const years = own.years;
  const otherMargin = other ? years.map((y) => {
    const i = other.years.indexOf(y);
    return i < 0 ? null : other.operating_margin[i];
  }) : null;
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 46, right: 46, bottom: 52 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, valueFormatter: (v) => (present(v) ? `${num(v, 1)}%` : DASH) },
    xAxis: { ...option.xAxis, data: years.map((y) => `FY${y}`), boundaryGap: true },
    yAxis: [
      { ...option.yAxis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${v}%` } },
      { ...option.yAxis, splitLine: { show: false }, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${v}%` } },
    ],
    series: [
      { name: `${name} revenue growth`, type: 'bar', barMaxWidth: 14, itemStyle: { color: p.up }, data: own.revenue_growth.map((v) => (present(v) ? { value: v, itemStyle: { color: v >= 0 ? p.up : p.down, opacity: 0.75 } } : null)) },
      { name: `${name} gross margin`, type: 'line', yAxisIndex: 1, data: own.gross_margin, showSymbol: false, connectNulls: false, lineStyle: { width: 1.3, color: p.blue }, itemStyle: { color: p.blue } },
      { name: `${name} operating margin`, type: 'line', yAxisIndex: 1, data: own.operating_margin, showSymbol: false, lineStyle: { width: 1.6, color: p.accent }, itemStyle: { color: p.accent } },
      ...(otherMargin ? [{ name: `${benchmark} operating margin`, type: 'line', yAxisIndex: 1, data: otherMargin, showSymbol: false, lineStyle: { width: 1.2, type: 'dashed', color: p.dim }, itemStyle: { color: p.dim } }] : []),
    ],
  }));
}

// A single company's VALUATION artifact as a basket the comparison can read:
// its price is its split-adjusted close, its earnings the close over its P/E.
export function companyBasket(history) {
  if (!history?.dates?.length || !history.pe) return null;
  const close = history.close || null;
  return {
    dates: history.dates, pe: history.pe, stats: history.stats || null,
    // The company's second earnings basis, when its history carries one.
    basis: history.basis || null, alternate: history.alternate || null,
    price: close, earnings: close ? close.map((c, i) => (present(c) && present(history.pe[i]) ? c / history.pe[i] : null)) : null,
  };
}

// capAxis: the company case only (see BAND_AXIS_CAP).
export function valuationBlock({ name, benchmark = null, own, other = null, reference = null, referenceLabel = 'the real ratio', title = 'VALUATION', capAxis = false }) {
  const nodes = [sectionTitle(title, `${name}${benchmark ? ` against ${benchmark}` : ''}: what the market pays, what the business earns`)];
  if (!own || (!own.valuation && !own.outlook && !own.history)) {
    nodes.push(gap(`${name}: no filings history, so no valuation.`));
    return nodes;
  }
  nodes.push(strip(stripCells(name, benchmark, own, other)));

  const band = el('div', {});
  const business = el('div', {});
  // Company-only reading order. Sector / relative-value pages retain their
  // existing paired layout and fold state.
  const historyFold = capAxis ? el('details', { class: 'fold valuation-history-fold' }) : null;
  const st = own.valuation?.stats;
  if (own.valuation?.dates?.length && st && present(st.median)) {
    band.append(trailingPeCard(own.valuation, capAxis, historyFold));
  } else {
    band.append(card('TRAILING P/E', null, [gap('Too little P/E history to draw (a loss-making stretch, or a short listing).')]));
  }
  const mine = trimHistory(own.history);
  if (mine) {
    const node = chartNode();
    business.append(card('THE BUSINESS · BY FISCAL YEAR', el('span', { class: 'dim', text: 'revenue growth (bars) · margins (lines)' }), [node,
      el('div', { class: 'field-note', text: capAxis
        ? 'Reported annual revenue growth and margins, by this company\'s fiscal year. Missing cost-of-revenue inputs leave gross margin blank; reported history is not a forecast.'
        : 'Totals of the companies\' annual filings: each company\'s own fiscal year, so a year mixes year-ends. Gross margin is blank where most of the revenue has no cost-of-revenue line (banks).' })]));
    queueMicrotask(() => businessChart(node, mine, trimHistory(other?.history), name, benchmark));
  } else {
    business.append(card('THE BUSINESS · BY FISCAL YEAR', null, [gap('No annual filings to total.')]));
  }
  if (historyFold) {
    nodes.push(business);
    historyFold.append(
      el('summary', { text: 'HISTORICAL MULTIPLE · CONTEXT, NOT A TARGET' }),
      el('p', { class: 'note-text', text: 'Past multiples reflect past growth, interest rates, competition and accounting. Below the historical median does not mean undervalued; review the business first.' }), band,
    );
    nodes.push(historyFold);
  } else nodes.push(el('div', { class: 'grid two' }, [band, business]));

  if (other?.valuation?.dates?.length && own.valuation?.price) {
    const fundamentals = { arms: [
      { label: name, basket: own.valuation, outlook: own.outlook },
      { label: benchmark, basket: other.valuation, outlook: other.outlook },
    ] };
    nodes.push(...relativeCards(fundamentals, [name, benchmark], reference, referenceLabel).nodes);
  }
  return nodes;
}

const HISTORY_YEARS = 10;

// One company's FINANCIALS artifact as the history the block draws: by fiscal
// year, in percent, the last ten years. It follows the rules of the Python
// fundamentals_history for a single name. Gross profit is revenue less cost of
// revenue where no gross line is filed; operating profit is pre-tax income where
// no operating line is (a bank). Growth is measured only against the fiscal year
// before, so a missing year stays a gap instead of being bridged.
export function companyHistory(statement) {
  const columns = (statement?.columns || [])
    .map((c, i) => ({ year: c?.fiscal_year, i }))
    .filter((c) => Number.isInteger(c.year))
    .sort((a, b) => a.year - b.year);
  if (!columns.length) return null;
  const values = statement.values || {};
  const at = (field, i) => (present(values[field]?.[i]) ? values[field][i] : null);
  const round1 = (v) => Math.round(v * 10) / 10 || 0;
  const revenue = columns.map(({ i }) => at('revenue', i));
  const gross = columns.map(({ i }, k) => {
    const reported = at('gross_profit', i);
    if (present(reported)) return reported;
    const cost = at('cost_of_revenue', i);
    return present(revenue[k]) && present(cost) ? revenue[k] - cost : null;
  });
  const operating = columns.map(({ i }) => at('ebit', i) ?? at('pretax_income', i));
  const margin = (figures) => figures.map((v, k) => (present(v) && present(revenue[k]) && revenue[k] > 0 ? round1((v / revenue[k]) * 100) : null));
  const growth = revenue.map((r, k) => {
    const before = k > 0 && columns[k - 1].year === columns[k].year - 1 ? revenue[k - 1] : null;
    return present(r) && r > 0 && present(before) && before > 0 ? round1((r / before - 1) * 100) : null;
  });
  const lastYears = (list) => list.slice(-HISTORY_YEARS);
  return {
    years: lastYears(columns.map((c) => c.year)),
    revenue_growth: lastYears(growth),
    gross_margin: lastYears(margin(gross)),
    operating_margin: lastYears(margin(operating)),
  };
}
