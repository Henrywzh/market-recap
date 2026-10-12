// K-SHAPE: a high-income leg against a low-income leg, within an industry.
// For each pair: the ratio of the legs' prices, of their trailing P/Es and the
// growth of their earnings, each with where today's value sits in its own
// history, and a table of who is in which leg. The legs are a judgment, set in
// the config. The page shows the divergence and what has been paid for it; it
// does not say which leg is right.

import { el, card, table, num, pct, dirClass, metaRow, sectionTitle, periodSwitch, gap, DASH } from '../fmt.js';
import { areaLine, multiLine } from '../charts.js';
import { tickerHref } from '../routes.js';
import { percentileView, multipleText, premiumView, spreadRows, nameRow, peRangeText, ordinal } from '../kshape-model.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits, unit = '') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${unit}` : DASH);

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function strip(v) {
  const price = v.price, pe = v.pe, now = v.now || {};
  const pp = price ? percentileView(price.ratio_percentile) : null;
  const pep = pe ? percentileView(pe.ratio_percentile) : null;
  return el('div', { class: 'stat-strip' }, [
    stat('PRICE RATIO · TOP ÷ BOTTOM', price ? multipleText(price.ratio_now) : DASH,
      price ? `since ${price.since} (=1.00) · ${pp.text}` : 'a leg has no prices'),
    stat('TRAILING P/E RATIO', pe ? multipleText(pe.now.ratio) : DASH,
      pe ? `${num(pe.now.top, 1)}× vs ${num(pe.now.bottom, 1)}× · ${pep.text} · median ${multipleText(pe.ratio_median)}` : 'no filings history for both legs'),
    stat('FORWARD P/E RATIO', multipleText(now.pe_forward_ratio),
      present(now.pe_forward_top) && present(now.pe_forward_bottom) ? `${num(now.pe_forward_top, 1)}× vs ${num(now.pe_forward_bottom, 1)}× (medians, today)` : 'a leg has no forward multiple'),
    stat('EPS GROWTH, THIS FISCAL YEAR', present(now.eps_growth_this_year_top) ? `${signed(now.eps_growth_this_year_top, 0, '%')} vs ${signed(now.eps_growth_this_year_bottom, 0, '%')}` : DASH, 'consensus, top vs bottom (medians)'),
  ]);
}

function chart(height = 230) {
  return el('div', { class: 'chart', style: `height:${height}px` });
}

function priceCards(v) {
  const p = v.price;
  if (!p) return [card('PRICE', null, [gap('A leg has no prices.')])];
  const ratioNode = chart();
  const legsNode = chart();
  const card1 = card(`PRICE RATIO · TOP ÷ BOTTOM · SINCE ${p.since}`, el('span', { class: 'dim', text: `${p.sessions} sessions · ${percentileView(p.ratio_percentile).text} of its own weeks` }), [ratioNode]);
  const card2 = card('EACH LEG, EQUAL WEIGHT · =100 WHEN BOTH FIRST TRADED', null, [legsNode]);
  queueMicrotask(() => {
    areaLine(ratioNode, p.dates, p.ratio);
    multiLine(legsNode, p.dates, { [`TOP · ${v.top.join(', ')}`]: p.top, [`BOTTOM · ${v.bottom.join(', ')}`]: p.bottom });
  });
  const rows = spreadRows(p.spreads).map((r) => el('tr', {}, [
    el('td', { text: r.period }), el('td', { class: dirClass(r.top), text: pct(r.top, 1) }), el('td', { class: dirClass(r.bottom), text: pct(r.bottom, 1) }),
    el('td', { class: r.tone === 'dim' ? 'dim' : r.tone, text: signed(r.spread, 1, ' pp') }),
  ]));
  const card3 = card('RETURNS · TOP LEG AGAINST BOTTOM LEG', null, [table(['WINDOW', 'TOP', 'BOTTOM', 'TOP − BOTTOM'], rows),
    el('div', { class: 'field-note', text: 'A window longer than both legs\' common history is absent, not shortened.' })]);
  return [el('div', { class: 'grid two' }, [card1, card2]), card3];
}

function peCard(v, settings) {
  const pe = v.pe;
  if (!pe) return card('TRAILING P/E', null, [gap('No P/E history for both legs: a name outside the valuation universe has prices only, and a build without VALUATION shows none.')]);
  const legsNode = chart();
  const ratioNode = chart();
  queueMicrotask(() => {
    multiLine(legsNode, pe.dates, { [`TOP · ${pe.covered.top.join(', ')}`]: pe.top, [`BOTTOM · ${pe.covered.bottom.join(', ')}`]: pe.bottom });
    areaLine(ratioNode, pe.dates, pe.ratio);
  });
  const missing = [...v.top, ...v.bottom].filter((t) => ![...pe.covered.top, ...pe.covered.bottom].includes(t));
  return card('TRAILING P/E · MEDIAN OF EACH LEG, AND THEIR RATIO', el('span', { class: 'dim', text: peRangeText(pe) }), [
    el('div', { class: 'grid two' }, [legsNode, ratioNode]),
    el('div', { class: 'field-note', text: `Only weeks where at least ${Math.round(settings.pe_min_share * 100)}% of the names with a history had a meaningful trailing P/E (positive, at most ${settings.pe_cap}×): loss-making years are blank, not zero.${missing.length ? ` No filings history for ${missing.join(', ')}.` : ''}` }),
  ]);
}

function epsCard(v) {
  const e = v.eps;
  if (!e) return null;
  const node = chart(210);
  queueMicrotask(() => multiLine(node, e.dates, { 'TOP · median EPS growth, y/y %': e.top, 'BOTTOM · median EPS growth, y/y %': e.bottom }));
  return card('EARNINGS · TRAILING 12-MONTH EPS, YEAR-ON-YEAR GROWTH · MEDIAN OF EACH LEG', el('span', { class: 'dim', text: `to ${e.latest}` }), [node,
    el('div', { class: 'field-note', text: 'Growth is drawn where the year-earlier EPS was positive and the change is within ±150%; a leg-quarter with none is blank.' })]);
}

function namesCard(v) {
  const rows = (v.names || []).map(nameRow).map((r) => el('tr', { class: r.leg === 'top' ? 'ks-top' : '' }, [
    el('td', {}, [el('a', { href: tickerHref(r.ticker), text: r.ticker })]),
    el('td', { class: 'dim', text: r.leg.toUpperCase() }),
    el('td', { title: r.peTitle, class: r.pe === DASH ? 'dim' : '', text: r.pe }),
    el('td', { class: 'dim', title: 'where its trailing P/E sits in its own ten years (the valuation tab)', text: r.percentile }),
    el('td', { text: r.growth }), el('td', { class: r.revenue === DASH ? 'dim' : '', text: r.revenue }),
    el('td', { class: dirClass(r.ret3m), text: pct(r.ret3m, 1) }), el('td', { class: dirClass(r.ret1y), text: pct(r.ret1y, 1) }),
    el('td', { class: 'dim', text: r.since && r.since > '2016-01-01' ? `from ${r.since}` : '' }),
  ]));
  const prem = premiumView(v.now);
  return card('WHO IS IN EACH LEG', el('span', { class: 'dim', text: 'forward P/E · consensus EPS growth this fiscal year · revenue growth y/y (filings)' }), [
    v.note ? el('div', { class: 'note-text', text: v.note }) : null,
    table(['NAME', 'LEG', 'FWD P/E', 'P/E PCTILE', 'EPS G THIS YR %', 'REV G %', '3M', '1Y', ''], rows),
    el('div', { class: 'sc-fomc-line', text: prem.text }),
    el('div', { class: 'field-note', text: 'Forward P/E is the valuation tab\'s next-twelve-months figure; a name outside it (listed 2024, or not in an index) uses the same blend from the consensus alone. Revenue growth is the trailing twelve months from filings, so a merger (Capital One and Discover) shows in it.' }),
  ]);
}

function render(root, data, host, key) {
  const v = data.views.find((x) => x.key === key) || data.views[0];
  host.replaceChildren(strip(v), ...priceCards(v), peCard(v, data.settings), epsCard(v), namesCard(v));
}

export default function renderKshape(root, data, _manifest, ctx = {}) {
  if (!data || data.unavailable || !Array.isArray(data.views)) {
    root.append(gap('No K-shape measurements in this build.'));
    return;
  }
  root.append(sectionTitle('K-SHAPE', 'HIGH-INCOME AGAINST LOW-INCOME, WITHIN AN INDUSTRY'));
  root.append(metaRow(`AS OF ${data.as_of} · PRICES THROUGH ${data.inputs.prices_through}${data.inputs.valuation_built ? '' : ' · NO VALUATION IN THIS BUILD: P/E AND EPS HISTORY ABSENT'}`, data.notes));
  const wanted = String(ctx.arg || '').toLowerCase();
  const keys = data.views.map((v) => v.key);
  const first = keys.includes(wanted) ? wanted : keys[0];
  const host = el('div', {});
  const labels = data.views.map((v) => v.label);
  const byLabel = Object.fromEntries(data.views.map((v) => [v.label, v.key]));
  root.append(periodSwitch(labels, data.views.find((v) => v.key === first).label, (label) => {
    ctx.setArg?.(byLabel[label]);
    render(root, data, host, byLabel[label]);
  }));
  root.append(host);
  render(root, data, host, first);
}
