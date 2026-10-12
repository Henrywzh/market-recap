// SIZE K: one arm of a pair against the other. Size pairs (the cap-weighted
// arm against the equal-weight or smaller one, of much the same market) and
// style pairs (value against growth, staples or low volatility against the
// market). Each view names its arms (big_arm / small_arm, default LARGE / SMALL).
// The ratio of their prices with where it sits in its own history, each arm's
// path, the rolling one-year gap, returns by window and each calendar year. The
// page shows the divergence; it does not say which arm is right, and it carries
// no valuation for the arms (see the notes).

import { el, card, table, num, pct, dirClass, metaRow, sectionTitle, periodSwitch, gap, DASH } from '../fmt.js';
import { areaLine, multiLine, zeroLine } from '../charts.js';
import { percentileView, multipleText, spreadRows } from '../kshape-model.js';
import { leadText, extremesText, yearRows, yearsWon, wonText } from '../sizek-model.js';

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

function render(data, host, key) {
  const v = data.views.find((x) => x.key === key) || data.views[0];
  const p = v.price, a = arms(v);
  if (!p) {
    host.replaceChildren(card(v.label, null, [gap(`No prices for ${(v.no_prices || []).join(', ') || 'this pair'}.`)]));
    return;
  }
  const ratioNode = chart();
  const armsNode = chart();
  const ratioCard = card(`RATIO · ${v.big_name} ÷ ${v.small_name} · SINCE ${p.since}`, el('span', { class: 'dim', text: `${p.sessions} sessions through ${p.through} · ${percentileView(p.ratio_percentile).text} of its own weeks` }), [
    ratioNode, p.extremes ? el('div', { class: 'field-note', text: extremesText(p.extremes) }) : null]);
  const armsCard = card('EACH ARM · =100 WHEN BOTH FIRST TRADED', null, [armsNode]);
  queueMicrotask(() => {
    areaLine(ratioNode, p.dates, p.ratio);
    multiLine(armsNode, p.dates, { [`${a.big} · ${v.big_name}`]: p.big, [`${a.small} · ${v.small_name}`]: p.small });
  });

  const cards = [el('div', { class: 'grid two' }, [ratioCard, armsCard])];
  if (v.gap) {
    const node = chart(200);
    queueMicrotask(() => zeroLine(node, v.gap.dates, v.gap.gap));
    cards.push(card(`${v.big_name} LESS ${v.small_name} · RETURN OVER ${v.gap.window}, PERCENTAGE POINTS`, el('span', { class: 'dim', text: `${v.gap.windows} windows from ${v.gap.first}` }), [node,
      el('div', { class: 'sc-fomc-line', text: leadText(v.gap, v.big_name, v.small_name) }),
      el('div', { class: 'field-note', text: 'Rolling windows overlap: neighbouring points share most of their days, so the number of times the lead changed hands is far smaller than the number of points.' })]));
  }

  const spreadBody = spreadRows(p.spreads).map((r) => el('tr', {}, [
    el('td', { text: r.period }), el('td', { class: dirClass(r.top), text: pct(r.top, 1) }), el('td', { class: dirClass(r.bottom), text: pct(r.bottom, 1) }),
    el('td', { class: r.tone === 'dim' ? 'dim' : r.tone, text: signed(r.spread, 1, ' pp') }),
  ]));
  const yearBody = yearRows(v.years).map((r) => el('tr', {}, [
    el('td', { text: r.label }), el('td', { class: dirClass(r.big), text: pct(r.big, 1) }), el('td', { class: dirClass(r.small), text: pct(r.small, 1) }),
    el('td', { class: r.tone === 'dim' ? 'dim' : r.tone, text: signed(r.gap, 1, ' pp') }),
  ]));
  cards.push(el('div', { class: 'grid two' }, [
    card('RETURNS BY WINDOW', null, [table(['WINDOW', `${a.big} · ${v.big_name}`, `${a.small} · ${v.small_name}`, `${a.big} − ${a.small}`], spreadBody),
      el('div', { class: 'field-note', text: 'A window longer than the common history is absent, not shortened.' })]),
    card('RETURNS BY CALENDAR YEAR', null, [table(['YEAR', `${a.big} · ${v.big_name}`, `${a.small} · ${v.small_name}`, `${a.big} − ${a.small}`], yearBody),
      el('div', { class: 'field-note', text: 'The first year starts at the first close both were priced; the current year is to date.' })]),
  ]));
  host.replaceChildren(strip(v), v.note ? el('div', { class: 'note-text', text: v.note }) : null, ...cards);
}

export default function renderSizek(root, data, _manifest, ctx = {}) {
  if (!data || data.unavailable || !Array.isArray(data.views)) {
    root.append(gap('No size-K measurements in this build.'));
    return;
  }
  root.append(sectionTitle('SIZE K', 'SIZE AND STYLE: ONE ARM AGAINST ANOTHER'));
  root.append(metaRow(`AS OF ${data.as_of} · PRICES THROUGH ${data.inputs.prices_through}${data.inputs.no_prices.length ? ` · NO PRICES: ${data.inputs.no_prices.join(', ')}` : ''}`, data.notes));
  const wanted = String(ctx.arg || '').toLowerCase();
  const keys = data.views.map((v) => v.key);
  const first = keys.includes(wanted) ? wanted : keys[0];
  const host = el('div', {});
  const byLabel = Object.fromEntries(data.views.map((v) => [v.label, v.key]));
  root.append(periodSwitch(data.views.map((v) => v.label), data.views.find((v) => v.key === first).label, (label) => {
    ctx.setArg?.(byLabel[label]);
    render(data, host, byLabel[label]);
  }));
  root.append(host);
  render(data, host, first);
}
