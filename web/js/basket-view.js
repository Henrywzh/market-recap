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
import { multiLine } from './charts.js';
import { sliceWindow, alignTo, baseIndex, availableWindows } from './windows.js';

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

function armText(arm) {
  const st = arm.basket.stats;
  const cover = present(arm.fund_coverage) ? ` · ${num(arm.fund_coverage * 100, 0)}% of the fund` : '';
  if (!st) return `${arm.label}: ${arm.basket.names} names${cover} · too little history to rank`;
  return `${arm.label}: ${num(st.current, 1)}× · ${num(st.percentile, 0)}th pctl of ${st.weeks} weeks · median ${num(st.median, 1)}× · ${arm.basket.names} names${cover}`;
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

function untrackedCard(fundamentals, window, names, track, joined, reference, referenceLabel) {
  const good = trackedWindows(joined, reference);
  const now = fundamentals.arms.map((a) => {
    const st = a.basket.stats;
    return st && present(st.current) ? `${a.label} ${num(st.current, 1)}×` : null;
  }).filter(Boolean).join(' · ');
  return [card(`WHAT MOVED ${names[0]} ÷ ${names[1]} · ${window}`, el('span', { class: 'dim', text: `not shown for ${window}` }), [
    el('div', { class: 'sc-fomc-line', text: `Over ${window}, the rebuilt arms (today's names with a filings history) moved the ratio ${signed(track.basket)}; ${referenceLabel} moved it ${signed(track.real)}. `
      + 'The rebuilt arms differ too much from the real ones here (their membership changed since, or some names have no filings history), so splitting their ratio into multiple and earnings would explain a history that did not happen.' }),
    el('div', { class: 'field-note', text: good.length
      ? `Shown where the two agree within ${TRACKING_PP} pp: ${good.join(', ')}.`
      : `No window here has the two within ${TRACKING_PP} pp.` }),
    now ? el('div', { class: 'field-note', text: `Trailing P/E today: ${now}.` }) : null,
  ].filter(Boolean))];
}

// The three cards for one window. `labels` names the arms as the page does.
export function fundamentalCards(fundamentals, window, labels = null, reference = null, referenceLabel = 'the funds') {
  if (!fundamentals || !Array.isArray(fundamentals.arms) || fundamentals.arms.length !== 2
      || !fundamentals.arms.every((a) => a.basket?.dates?.length)) {
    const why = fundamentals?.missing || 'No filings history for both arms.';
    return [card('VALUATION AND EARNINGS', null, [gap(why)])];
  }
  const names = labels || fundamentals.arms.map((a) => a.label);
  const joined = joinArms(fundamentals);
  const track = reference?.dates?.length ? tracking(joined, reference, window) : null;
  if (track && !track.ok) return untrackedCard(fundamentals, window, names, track, joined, reference, referenceLabel);
  const peNode = chart();
  const earnNode = chart();
  const splitNode = chart();
  const cut = sliceWindow(joined.dates, {
    peA: joined.peA, peB: joined.peB, earnA: joined.earnA, earnB: joined.earnB,
    price: joined.priceRatio, multiple: joined.peRatio, earnings: joined.earningsRatio,
  }, window, { earnA: 'index', earnB: 'index', price: 'ratio', multiple: 'ratio', earnings: 'ratio' });
  queueMicrotask(() => {
    multiLine(peNode, cut.dates, { [`${names[0]} P/E`]: cut.series.peA, [`${names[1]} P/E`]: cut.series.peB });
    multiLine(earnNode, cut.dates, { [`${names[0]} earnings`]: cut.series.earnA, [`${names[1]} earnings`]: cut.series.earnB });
    multiLine(splitNode, cut.dates, {
      [`price ratio`]: cut.series.price, [`P/E ratio`]: cut.series.multiple, [`earnings ratio`]: cut.series.earnings,
    });
  });
  const parts = decompose(joined, window);
  return [
    card(`WHAT MOVED ${names[0]} ÷ ${names[1]} · ${window}`, el('span', { class: 'dim', text: '=1 at the window\'s start · price ratio = P/E ratio × earnings ratio' }), [
      splitNode,
      el('div', { class: 'sc-fomc-line', text: decompositionText(parts, names) }),
    ]),
    el('div', { class: 'grid two' }, [
      card(`TRAILING P/E · EACH ARM · ${window}`, null, [peNode,
        ...fundamentals.arms.map((a) => el('div', { class: 'field-note', text: armText(a) }))]),
      card(`EARNINGS · EACH ARM · ${window}`, el('span', { class: 'dim', text: '=100 at the window\'s start' }), [earnNode,
        el('div', { class: 'field-note', text: 'Trailing twelve-month earnings the arm\'s price index stands for (price ÷ P/E), losses included. A week whose arm has too little filings coverage or a total loss is blank.' })]),
    ]),
    el('div', { class: 'field-note', text: [
      'Each arm here is rebuilt from its names\' filings and split-adjusted closes, held at today\'s weights (a fund at its holding weights, an index at market caps, an equal-weight arm in equal value): price only, no dividends, today\'s members throughout. So its price ratio can differ a little from the fund\'s above.',
      ...(fundamentals.notes || []),
      ...fundamentals.arms.map((a) => a.note).filter(Boolean),
    ].join(' ') }),
  ];
}
