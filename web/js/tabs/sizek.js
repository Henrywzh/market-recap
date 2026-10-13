// SIZE K: one arm of a pair against the other. Size pairs (the cap-weighted
// arm against the equal-weight or smaller one, of much the same market) and
// style pairs (value against growth, staples or low volatility against the
// market). Each view names its arms (big_arm / small_arm, default LARGE / SMALL).
// The page reads in three charts: the ratio of the arms' prices with where it
// sits in its own history, then the valuation section (forward P/E and growth,
// the P/E premium against its own history, and what moved the ratio in each
// window). Each arm's path, the rolling one-year gap and the returns tables sit
// in a DETAIL fold, closed. One window switch cuts the ratio and the folded
// charts to the same lookback, and the reader's choice is kept between pairs.
// The stat strip is full-history. The page shows the divergence; it does not
// say which arm is right.

import { el, card, table, num, pct, dirClass, metaRow, sectionTitle, periodSwitch, gap, DASH } from '../fmt.js';
import { areaLine, multiLine, zeroLine } from '../charts.js';
import { valuationSection } from '../basket-view.js';
import { pickWindow, windowSwitch } from '../windows.js';
import { percentileView, multipleText, spreadRows } from '../kshape-model.js';
import { leadText, extremesText, yearRows, yearsWon, wonText, readWindow, writeWindow, priceSeries, gapSeries, fundamentalsOf, detailFold } from '../sizek-model.js';

// One memory per tab, so the reader's window survives switching pairs and
// reloads. The default is five years: long enough to show a regime, short
// enough that the last year is still legible.
const WINDOW_KEY = 'mr-window-sizek';
const DEFAULT_WINDOW = '5Y';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits, unit = '') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${unit}` : DASH);

function stat(label, value, note) {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: 'stat-value', text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function chart(height = 230) {
  return el('div', { class: 'chart', style: `height:${height}px` });
}

// The arm names for a view, as the page prints them.
function arms(v) {
  return { big: v.big_arm || 'LARGE', small: v.small_arm || 'SMALL' };
}

// Full-history figures: the strip says "of its own weeks", so it does not move
// with the window.
function strip(v) {
  const p = v.price, g = v.gap, b = v.big_name, sm = v.small_name, a = arms(v);
  const pp = p ? percentileView(p.ratio_percentile) : null;
  const gp = g ? percentileView(g.percentile) : null;
  return el('div', { class: 'stat-strip' }, [
    stat(`RATIO · ${b} ÷ ${sm}`, p ? multipleText(p.ratio_now) : DASH, p ? `since ${p.since} (=1.00) · ${pp.text}` : 'a series has no prices'),
    stat('FROM THE RATIO\'S HIGH', p && p.extremes ? signed(p.extremes.from_high_pct, 1, '%') : DASH, p && p.extremes ? `high ${num(p.extremes.high, 2)}× on ${p.extremes.high_date}` : null),
    stat(`${b} LESS ${sm}, ${g ? g.window : '1Y'}`, g ? signed(g.now, 1, ' pp') : DASH, g ? `${gp.text} of its own weeks` : 'too little history'),
    stat(`CALENDAR YEARS ${a.big} WON`, wonText(yearsWon(v.years)), 'complete years only'),
  ]);
}

function windowBar(dates, window, onPick) {
  return el('div', { class: 'pair-window' }, [
    el('span', { class: 'pair-window-label', text: 'WINDOW' }),
    windowSwitch(dates, window, onPick),
  ]);
}

// The one chart in the main flow: the ratio over the window, rebased to 1 at
// its start, with where the ratio sits in its own full history.
function ratioCard(v, win) {
  const p = v.price;
  const ratio = priceSeries(p, win);
  const node = chart();
  queueMicrotask(() => areaLine(node, ratio.dates, ratio.series.ratio));
  return card(`RATIO · ${v.big_name} ÷ ${v.small_name} · ${win}`,
    el('span', { class: 'dim', text: `=1.00 at the window's start · ${percentileView(p.ratio_percentile).text} of its own weeks` }), [
      node,
      p.extremes ? el('div', { class: 'field-note', text: extremesText(p.extremes) }) : null,
    ]);
}

// The folded charts, all cut to the window: each arm's path and the rolling
// gap with its lead. Their paints are queued, not drawn, because the fold is
// closed until the reader opens it.
function detailCharts(v, win, paints) {
  const a = arms(v);
  const armsCut = priceSeries(v.price, win);
  const armsNode = chart();
  paints.push(() => multiLine(armsNode, armsCut.dates, {
    [`${a.big} · ${v.big_name}`]: armsCut.series.big,
    [`${a.small} · ${v.small_name}`]: armsCut.series.small,
  }));
  const out = [card(`EACH ARM · =100 AT THE WINDOW'S START · ${win}`, null, [armsNode])];
  if (v.gap) {
    const node = chart(200);
    const cut = gapSeries(v.gap, win);
    paints.push(() => zeroLine(node, cut.dates, cut.series.gap));
    out.push(card(`${v.big_name} LESS ${v.small_name} · RETURN OVER ${v.gap.window}, PERCENTAGE POINTS · ${win}`, el('span', { class: 'dim', text: `${v.gap.windows} windows from ${v.gap.first}` }), [node,
      el('div', { class: 'sc-fomc-line', text: leadText(v.gap, v.big_name, v.small_name) }),
      el('div', { class: 'field-note', text: 'Rolling windows overlap: neighbouring points share most of their days, so the number of times the lead changed hands is far smaller than the number of points.' })]));
  }
  return out;
}

// The tables are readings of whole periods, not dated charts: they stay full.
function tables(v) {
  const a = arms(v);
  const spreadBody = spreadRows(v.price.spreads).map((r) => el('tr', {}, [
    el('td', { text: r.period }), el('td', { class: dirClass(r.top), text: pct(r.top, 1) }), el('td', { class: dirClass(r.bottom), text: pct(r.bottom, 1) }),
    el('td', { class: r.tone === 'dim' ? 'dim' : r.tone, text: signed(r.spread, 1, ' pp') }),
  ]));
  const yearBody = yearRows(v.years).map((r) => el('tr', {}, [
    el('td', { text: r.label }), el('td', { class: dirClass(r.big), text: pct(r.big, 1) }), el('td', { class: dirClass(r.small), text: pct(r.small, 1) }),
    el('td', { class: r.tone === 'dim' ? 'dim' : r.tone, text: signed(r.gap, 1, ' pp') }),
  ]));
  return [el('div', { class: 'grid two' }, [
    card('RETURNS BY WINDOW', null, [table(['WINDOW', `${a.big} · ${v.big_name}`, `${a.small} · ${v.small_name}`, `${a.big} − ${a.small}`], spreadBody),
      el('div', { class: 'field-note', text: 'A window longer than the common history is absent, not shortened.' })]),
    card('RETURNS BY CALENDAR YEAR', null, [table(['YEAR', `${a.big} · ${v.big_name}`, `${a.small} · ${v.small_name}`, `${a.big} − ${a.small}`], yearBody),
      el('div', { class: 'field-note', text: 'The first year starts at the first close both were priced; the current year is to date.' })]),
  ])];
}

export default function renderSizek(root, data, _manifest, ctx = {}) {
  if (!data || data.unavailable || !Array.isArray(data.views)) {
    root.append(gap('No size-K measurements in this build.'));
    return;
  }
  root.append(sectionTitle('SIZE & STYLE', 'ONE ARM AGAINST ANOTHER'));
  root.append(metaRow(`AS OF ${data.as_of} · PRICES THROUGH ${data.inputs.prices_through}${data.inputs.no_prices.length ? ` · NO PRICES: ${data.inputs.no_prices.join(', ')}` : ''}`, data.notes));
  const wanted = String(ctx.arg || '').toLowerCase();
  const keys = data.views.map((v) => v.key);
  const first = keys.includes(wanted) ? wanted : keys[0];
  const host = el('div', {});
  const byLabel = Object.fromEntries(data.views.map((v) => [v.label, v.key]));
  let lookback = readWindow(WINDOW_KEY, DEFAULT_WINDOW);
  const foldState = { open: false };

  // Redraws the pair. A pair shorter than the remembered window shows its
  // longest covered window instead, and the remembered choice is kept.
  const draw = (key) => {
    const v = data.views.find((x) => x.key === key) || data.views[0];
    if (!v.price) {
      host.replaceChildren(card(v.label, null, [gap(`No prices for ${(v.no_prices || []).join(', ') || 'this pair'}.`)]));
      return;
    }
    const win = pickWindow(v.price.dates, lookback);
    const a = arms(v);
    const paints = [];
    const folded = [...detailCharts(v, win, paints), ...tables(v)];
    const fold = detailFold(foldState, () => paints.forEach((paint) => paint()), folded);
    // replaceChildren turns a null child into the text "null", so absent parts are filtered out.
    host.replaceChildren(...[
      strip(v),
      v.note ? el('div', { class: 'note-text', text: v.note }) : null,
      windowBar(v.price.dates, win, (next) => {
        lookback = next;
        writeWindow(WINDOW_KEY, next);
        draw(v.key);
      }),
      ratioCard(v, win),
      ...valuationSection(fundamentalsOf(v), [a.big, a.small], { dates: v.price.dates, ratio: v.price.ratio }, `${v.big_name} ÷ ${v.small_name}`),
      fold,
    ].filter(Boolean));
  };

  root.append(periodSwitch(data.views.map((v) => v.label), data.views.find((v) => v.key === first).label, (label) => {
    ctx.setArg?.(byLabel[label]);
    draw(byLabel[label]);
  }));
  root.append(host);
  draw(first);
}
