// What a ratio of two baskets is made of. Each basket's price index is its P/E
// times its earnings (compute/baskets.py), so the ratio of two baskets splits
// exactly into a ratio of multiples and a ratio of earnings: a lead built on
// earnings, or on a re-rating. The cards read a `fundamentals` payload:
//
//   { arms: [{ key, label, basket: { dates, price, pe, earnings, coverage, names, stats },
//              fund_coverage?, note? }, { ...the other arm }],
//     notes?: [...] }
//
// and draw over one lookback window (windows.js), the same one as the page's
// price charts.

import { el, card, num, gap, DASH } from './fmt.js';
import { render } from './charts.js';
import { sliceWindow, alignTo, baseIndex, availableWindows } from './windows.js';

export { sliceWindow };

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits = 1, unit = '%') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${unit}` : DASH);

function chart(height = 230) {
  return el('div', { class: 'chart', style: `height:${height}px` });
}

// Both arms on the first arm's weeks, with the ratios. Weeks either arm lacks
// are blank, not filled.
export function joinArms(fundamentals) {
  const [a, b] = fundamentals.arms;
  const dates = a.basket.dates;
  const pick = (arm, field) => (arm === a ? arm.basket[field] : alignTo(dates, arm.basket.dates, arm.basket[field]));
  const ratio = (x, y) => x.map((v, i) => (present(v) && present(y[i]) && y[i] !== 0 ? v / y[i] : null));
  const priceA = pick(a, 'price'), priceB = pick(b, 'price');
  const peA = pick(a, 'pe'), peB = pick(b, 'pe');
  const earnA = pick(a, 'earnings'), earnB = pick(b, 'earnings');
  return {
    dates,
    priceA, priceB, peA, peB, earnA, earnB,
    priceRatio: ratio(priceA, priceB),
    peRatio: ratio(peA, peB),
    earningsRatio: ratio(earnA, earnB),
  };
}

// The change of each ratio over the window, from its first value in the window
// with all three present to the last: price = multiple x earnings, so
// (1 + price) = (1 + multiple)(1 + earnings).
export function decompose(joined, window) {
  const start = Math.max(0, baseIndex(joined.dates, window));
  const ok = (i) => present(joined.priceRatio[i]) && present(joined.peRatio[i]) && present(joined.earningsRatio[i]);
  let first = -1;
  for (let i = start; i < joined.dates.length; i += 1) if (ok(i)) { first = i; break; }
  let last = -1;
  for (let i = joined.dates.length - 1; i >= start; i -= 1) if (ok(i)) { last = i; break; }
  if (first < 0 || last <= first) return null;
  const change = (series) => (series[last] / series[first] - 1) * 100;
  return {
    from: joined.dates[first], to: joined.dates[last],
    price: change(joined.priceRatio), multiple: change(joined.peRatio), earnings: change(joined.earningsRatio),
  };
}

export function decompositionText(parts, labels) {
  if (!parts) return 'Too few weeks with a P/E for both arms in this window.';
  const lead = parts.price >= 0 ? labels[0] : labels[1];
  const bigger = Math.abs(parts.multiple) > Math.abs(parts.earnings) ? 'the multiple' : 'earnings';
  return `${parts.from} to ${parts.to}: ${labels[0]} ÷ ${labels[1]} ${signed(parts.price)} = multiple ${signed(parts.multiple)} × earnings ${signed(parts.earnings)}. `
    + `${lead} led, and ${bigger} did more of it.`;
}

// The baskets hold today's names backwards. Where an arm's membership changed a
// lot (a style fund reconstituted on valuation each year, an index adding last
// year's winners), today's names did not earn the arm's past, and splitting
// their ratio would explain a history that never happened. So the split is shown
// only over windows where the baskets' price ratio moved within TRACKING_PP of
// the real one (the funds' ratio). `reference` is {dates, ratio}.
export const TRACKING_PP = 5;

function changeOver(dates, values, window) {
  const start = baseIndex(dates, window);
  if (start < 0) return null;
  let first = null;
  for (let i = start; i < values.length; i += 1) if (present(values[i])) { first = values[i]; break; }
  let last = null;
  for (let i = values.length - 1; i >= start; i -= 1) if (present(values[i])) { last = values[i]; break; }
  return present(first) && present(last) && first !== 0 ? (last / first - 1) * 100 : null;
}

export function tracking(joined, reference, window) {
  const basket = changeOver(joined.dates, joined.priceRatio, window);
  const real = changeOver(reference.dates, reference.ratio, window);
  if (!present(basket) || !present(real)) return null;
  return { basket, real, gap: basket - real, ok: Math.abs(basket - real) <= TRACKING_PP };
}

export function trackedWindows(joined, reference) {
  return availableWindows(joined.dates).filter((w) => w !== 'MAX' && tracking(joined, reference, w)?.ok);
}

// --- What moved the ratio, window by window -----------------------------------
// One window's change in the ratio, split into what the multiple did and what
// earnings did, in percentage points that add up to the change: each part's
// share of the log change, so a +9.6% made of multiple -16% and earnings +31%
// reads "re-rating -19 pp, earnings +29 pp".
const ATTRIBUTION_WINDOWS = ['1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', '10Y'];

export function attributionRow(joined, reference, window) {
  const parts = decompose(joined, window);
  if (!parts) return null;
  const track = reference?.dates?.length ? tracking(joined, reference, window) : null;
  const logMultiple = Math.log1p(parts.multiple / 100);
  const logTotal = logMultiple + Math.log1p(parts.earnings / 100);
  const multiple = Math.abs(logTotal) < 1e-9 ? parts.multiple : (parts.price * logMultiple) / logTotal;
  return {
    window, from: parts.from, to: parts.to, total: parts.price, multiple, earnings: parts.price - multiple,
    ok: track ? track.ok : true, real: track ? track.real : null,
  };
}

export function attributionRows(joined, reference) {
  const covered = availableWindows(joined.dates);
  return ATTRIBUTION_WINDOWS.filter((w) => covered.includes(w)).map((w) => attributionRow(joined, reference, w)).filter(Boolean);
}

// --- The P/E premium against its own history ----------------------------------
// A's P/E over B's as a premium in percent, over the longest window (10Y down to
// 1Y) where today's names track the real ratio; with no reference, all of it.
// Null when no window of a year or more tracks: then only today's premium is fair.
const PREMIUM_WINDOWS = ['10Y', '5Y', '3Y', '1Y'];

function quantile(sorted, q) {
  const at = (sorted.length - 1) * q;
  const lo = Math.floor(at);
  const hi = Math.ceil(at);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (at - lo);
}

export function premiumView(joined, reference) {
  const covered = availableWindows(joined.dates);
  const window = reference?.dates?.length
    ? PREMIUM_WINDOWS.find((w) => covered.includes(w) && tracking(joined, reference, w)?.ok)
    : (PREMIUM_WINDOWS.find((w) => covered.includes(w)) || 'MAX');
  const premium = joined.peRatio.map((v) => (present(v) ? (v - 1) * 100 : null));
  const lastIndex = premium.map((v, i) => (present(v) ? i : -1)).filter((i) => i >= 0).pop();
  const now = lastIndex === undefined ? null : premium[lastIndex];
  if (!window) return { window: null, now };
  const cut = sliceWindow(joined.dates, { premium }, window);
  const valid = cut.series.premium.filter(present).sort((x, y) => x - y);
  if (valid.length < 8) return { window: null, now };
  return {
    window, now, dates: cut.dates, premium: cut.series.premium,
    median: quantile(valid, 0.5), p25: quantile(valid, 0.25), p75: quantile(valid, 0.75),
    percentile: present(now) ? (100 * valid.filter((v) => v <= now).length) / valid.length : null,
  };
}

function premiumChart(node, view) {
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, right: 92 },
    tooltip: { ...option.tooltip, valueFormatter: (v) => signed(v, 0) },
    xAxis: { ...option.xAxis, data: view.dates },
    yAxis: {
      ...option.yAxis,
      min: (v) => Math.floor(Math.min(v.min, view.p25, 0) - 2),
      max: (v) => Math.ceil(Math.max(v.max, view.p75, 0) + 2),
      axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${v > 0 ? '+' : ''}${v}%` },
    },
    series: [{
      name: 'P/E premium', type: 'line', data: view.premium, showSymbol: false,
      lineStyle: { width: 1.4, color: p.text }, itemStyle: { color: p.text },
      markArea: { silent: true, itemStyle: { color: p.accent, opacity: 0.12 }, data: [[{ yAxis: view.p25 }, { yAxis: view.p75 }]] },
      markLine: {
        silent: true, symbol: 'none', label: { color: p.dim, fontSize: 10, position: 'end', formatter: (d) => d.name },
        data: [
          { name: `median ${signed(view.median, 0)}`, yAxis: view.median, lineStyle: { color: p.accent, type: 'dashed' } },
          { name: 'even', yAxis: 0, lineStyle: { color: p.faint, type: 'solid' } },
        ],
      },
    }],
  }));
}

function attributionChart(node, rows) {
  // Each window with its total beside it, so no label sits on a bar.
  const labels = rows.map((r) => `${r.window}  ${signed(r.total, 1)}`);
  const value = (r, field) => r[field];
  render(node, (option, p) => ({
    ...option,
    grid: { left: 92, right: 24, top: 10, bottom: 46 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: {
      ...option.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (items) => {
        const r = rows[items[0].dataIndex];
        if (!r.ok) {
          return `<b>${r.window}</b><br>not comparable: today's names ${signed(r.total)}, the real ratio ${signed(r.real)}`;
        }
        return `<b>${r.window}</b> · ${r.from} to ${r.to}<br>ratio ${signed(r.total)}<br>re-rating ${signed(r.multiple, 1, ' pp')}<br>earnings ${signed(r.earnings, 1, ' pp')}`;
      },
    },
    xAxis: {
      type: 'value', axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => `${v}` },
      splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
    },
    yAxis: {
      type: 'category', inverse: true, data: labels, axisTick: { show: false },
      axisLine: { lineStyle: { color: p.border } },
      axisLabel: { color: p.dim, fontSize: 10 },
    },
    series: [
      { name: 'earnings', type: 'bar', stack: 'split', barWidth: 12, data: rows.map((r) => value(r, 'earnings')), itemStyle: { color: p.accent } },
      { name: 're-rating (P/E)', type: 'bar', stack: 'split', barWidth: 12, data: rows.map((r) => value(r, 'multiple')), itemStyle: { color: p.blue } },
      {
        name: 'ratio', type: 'scatter', symbol: 'diamond', symbolSize: 10, data: rows.map((r) => value(r, 'total')),
        itemStyle: { color: p.text },
      },
    ],
  }));
}

function gapCell(a, b, digits, unit) {
  return present(a) && present(b) ? `${signed(a, digits, unit)} vs ${signed(b, digits, unit)}` : DASH;
}

// What the market pays and expects, today, for each arm: forward P/E,
// consensus EPS growth next fiscal year, and TTM revenue growth (arm.outlook).
export function outlookCells(arms, names, view) {
  const [a, b] = arms.map((x) => x.outlook || {});
  const fwdPremium = present(a.forward_pe) && present(b.forward_pe) ? (a.forward_pe / b.forward_pe - 1) * 100 : null;
  return [
    { label: 'FORWARD P/E', value: present(a.forward_pe) && present(b.forward_pe) ? `${num(a.forward_pe, 1)}× vs ${num(b.forward_pe, 1)}×` : DASH,
      note: present(fwdPremium) ? `${names[0]} at a ${num(Math.abs(fwdPremium), 0)}% ${fwdPremium >= 0 ? 'premium' : 'discount'} · next 12 months` : 'consensus too thin' },
    { label: 'TRAILING P/E PREMIUM', value: present(view.now) ? signed(view.now, 0) : DASH,
      note: view.window ? `${num(view.percentile, 0)}th pctl of ${view.window} · median ${signed(view.median, 0)}` : 'too little comparable history to rank' },
    { label: 'EPS GROWTH NEXT FY', value: gapCell(a.eps_growth_next, b.eps_growth_next, 0, '%'), note: 'consensus, the arm\'s total earnings' },
    { label: 'REVENUE GROWTH · TTM', value: gapCell(a.revenue_growth, b.revenue_growth, 0, '%'), note: 'year on year, from filings' },
  ];
}

function stripOf(cells) {
  return el('div', { class: 'stat-strip' }, cells.map((c) => el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: c.label }),
    el('div', { class: 'stat-value', text: c.value }),
    c.note ? el('div', { class: 'stat-note', text: c.note }) : null,
  ].filter(Boolean))));
}

// The valuation block for a pair: a strip of what the market pays and expects
// today, the P/E premium against its own history, and what moved the ratio in
// each window. `labels` names the arms as the page does; `reference` is the
// real ratio {dates, ratio} the rebuilt arms must track (see tracking).
export function valuationSection(fundamentals, labels = null, reference = null, referenceLabel = 'the real ratio') {
  if (!fundamentals || !Array.isArray(fundamentals.arms) || fundamentals.arms.length !== 2
      || !fundamentals.arms.every((a) => a.basket?.dates?.length)) {
    const why = fundamentals?.missing || 'No filings history for both arms.';
    return [card('VALUATION', null, [gap(why)])];
  }
  const names = labels || fundamentals.arms.map((a) => a.label);
  const joined = joinArms(fundamentals);
  const view = premiumView(joined, reference);
  const all = attributionRows(joined, reference);
  // Windows where today's names do not track the real ratio are left off the
  // chart and named under it.
  const rows = all.filter((r) => r.ok);
  const premiumNode = el('div', { class: 'chart', style: 'height:230px' });
  const splitNode = el('div', { class: 'chart', style: `height:${Math.max(170, 34 * rows.length + 60)}px` });
  queueMicrotask(() => {
    if (view.window) premiumChart(premiumNode, view);
    if (rows.length) attributionChart(splitNode, rows);
  });
  const skipped = all.filter((r) => !r.ok).map((r) => r.window);
  return [
    stripOf(outlookCells(fundamentals.arms, names, view)),
    el('div', { class: 'grid two' }, [
      card(`P/E PREMIUM · ${names[0]} OVER ${names[1]}`, el('span', { class: 'dim', text: view.window ? `trailing · ${view.window} · band 25th–75th` : 'today only' }), [
        view.window ? premiumNode : gap(`Today's names do not track ${referenceLabel} over a year or more, so their P/E history would not be the arms' own. Today: ${signed(view.now, 0)}.`),
      ]),
      card(`WHY ${names[0]} ÷ ${names[1]} MOVED`, el('span', { class: 'dim', text: 'percentage points of the ratio\'s change · bars add up to ◆' }), [
        rows.length ? splitNode : gap(all.length ? `In no window do today's names track ${referenceLabel} within ${TRACKING_PP} pp.` : 'Too few weeks with a P/E for both arms.'),
        el('div', { class: 'field-note', text: [
          'Amber: the part earnings did. Blue: the part a change in the P/E did (a re-rating).',
          skipped.length ? `Not shown: in ${skipped.join(', ')} today's names moved the ratio more than ${TRACKING_PP} pp away from ${referenceLabel} (their membership changed, or some names have no filings history), so the split would explain a history that did not happen.` : null,
        ].filter(Boolean).join(' ') }),
      ]),
    ]),
    el('div', { class: 'field-note', text: [
      'Each arm is rebuilt from its names\' filings and split-adjusted closes at today\'s weights: price only, no dividends, today\'s members throughout.',
      ...(fundamentals.notes || []),
      ...fundamentals.arms.map((a) => a.note).filter(Boolean),
    ].join(' ') }),
  ];
}
