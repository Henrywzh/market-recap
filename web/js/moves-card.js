// A session's move in the stock's own terms (MOVES artifact): its return in
// units of its own volatility, split into what the market and its sector
// explain and its own part; the overnight gap against the session; volume;
// and the range its own history implies for the next sessions.

import { el, card, table, num, tag, periodSwitch, DASH } from './fmt.js';
import { tickerHref } from './routes.js';

const valid = (v) => typeof v === 'number' && Number.isFinite(v);
const signed = (v, digits = 2, suffix = '%') => (valid(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${suffix}` : DASH);
const sigma = (v) => signed(v, 1, 'σ');
const tone = (v) => (!valid(v) ? 'dim' : v > 0 ? 'up' : v < 0 ? 'down' : 'dim');

// Market, sector and own parts as bars on one scale, so the reader sees which
// of the three made the move.
export function partRows(row) {
  const parts = [['Market', row.market_pct, row.beta_market], ['Sector', row.sector_pct, row.beta_sector], ['Own', row.own_pct, null]];
  const scale = Math.max(...parts.map(([, v]) => (valid(v) ? Math.abs(v) : 0)), 0.01);
  return parts.map(([label, value, beta]) => ({
    label, value, beta, width: valid(value) ? Math.round((100 * Math.abs(value)) / scale) : 0, negative: valid(value) && value < 0,
  }));
}

// The bands carry quantiles; the 90% and 68% ranges are their outer pairs.
export function rangeText(range) {
  const at = (q) => range?.bands?.find((b) => Math.abs(b.q - q) < 1e-9);
  const lo90 = at(0.05), hi90 = at(0.95), lo68 = at(0.16), hi68 = at(0.84);
  if (!lo90 || !hi90) return null;
  return {
    wide: `${signed(lo90.pct, 1)} to ${signed(hi90.pct, 1)}`,
    widePrices: `$${num(lo90.price, 2)} – $${num(hi90.price, 2)}`,
    narrow: lo68 && hi68 ? `${signed(lo68.pct, 1)} to ${signed(hi68.pct, 1)}` : null,
  };
}

export function unusualRows(data, direction = 'ALL') {
  const threshold = data?.settings?.threshold_sigma ?? 2;
  return (data?.rows || [])
    .filter((r) => valid(r.z_own) && Math.abs(r.z_own) >= threshold)
    .filter((r) => direction === 'ALL' || (direction === 'DOWN' ? r.z_own < 0 : r.z_own > 0))
    .sort((a, b) => Math.abs(b.z_own) - Math.abs(a.z_own));
}

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    el('div', { class: 'stat-note', text: note }),
  ]);
}

export function moveCard(row, data) {
  if (!row) return null;
  const settings = data.settings || {};
  const range = rangeText(row.range);
  const bars = el('div', { class: 'move-parts' }, partRows(row).map((p) => el('div', { class: 'move-part' }, [
    el('span', { class: 'move-part-label', text: p.label }),
    el('span', { class: 'move-part-track' }, [el('span', { class: `move-part-fill ${p.negative ? 'down' : 'up'}`, style: `width:${p.width}%` })]),
    el('span', { class: `move-part-value ${tone(p.value)}`, text: signed(p.value) }),
    el('span', { class: 'dim move-part-beta', text: valid(p.beta) ? `β ${num(p.beta, 2)}` : '' }),
  ])));
  return card(`LAST SESSION IN ITS OWN TERMS · ${data.as_of}`, row.reported ? tag('REPORTED', 'info') : null, [
    el('div', { class: 'stat-strip' }, [
      stat('RETURN', signed(row.ret_pct), `${sigma(row.z)} of its ${settings.vol_sessions}-session σ (${num(row.sigma_pct, 2)}%)`, tone(row.ret_pct)),
      stat('OWN PART', signed(row.own_pct), `${sigma(row.z_own)} after market and sector`, tone(row.own_pct)),
      stat('GAP / SESSION', `${signed(row.gap_pct, 1)} / ${signed(row.intraday_pct, 1)}`, 'close→open / open→close'),
      stat('VOLUME', valid(row.volume_ratio) ? `${num(row.volume_ratio, 1)}×` : DASH, `of its ${settings.volume_sessions}-session median`),
      stat(`NEXT ${settings.range_sessions} SESSIONS`, range ? range.wide : DASH, range ? `90% of its own history · ${range.widePrices}` : 'too little history'),
    ]),
    bars,
    el('details', { class: 'sx-fold' }, [el('summary', { text: 'Method & caveats' }),
      el('div', { class: 'note-text', text: data.note }),
      range?.narrow ? el('div', { class: 'note-text', text: `68% range: ${range.narrow}. Ranges are the stock's own past ${settings.range_sessions}-session moves scaled to today's volatility, with the past average removed: a spread of outcomes, not a direction.` }) : null,
    ]),
  ]);
}

export function unusualCard(data, { limit = 20 } = {}) {
  if (!data?.rows?.length) return null;
  let direction = 'ALL';
  const host = el('div', {});
  const draw = () => {
    const rows = unusualRows(data, direction);
    const line = (r) => el('tr', {}, [
      el('td', {}, [el('a', { href: tickerHref(r.ticker), text: r.ticker }), el('span', { class: 'sub', text: r.name })]),
      el('td', { class: 'dim', text: r.sector || DASH }),
      el('td', { class: tone(r.ret_pct), text: signed(r.ret_pct) }),
      el('td', { text: sigma(r.z) }),
      el('td', { class: tone(r.market_pct), text: signed(r.market_pct) }),
      el('td', { class: tone(r.sector_pct), text: signed(r.sector_pct) }),
      el('td', { class: tone(r.own_pct), text: signed(r.own_pct) }),
      el('td', { class: tone(r.z_own), text: sigma(r.z_own) }),
      el('td', { text: `${signed(r.gap_pct, 1)} / ${signed(r.intraday_pct, 1)}` }),
      el('td', { text: valid(r.volume_ratio) ? `${num(r.volume_ratio, 1)}×` : DASH }),
      el('td', {}, [r.reported ? tag('REPORTED', 'info') : el('span', { class: 'dim', text: r.reported === false ? 'no' : DASH })]),
      el('td', { class: 'dim', text: r.above_200d === null || r.above_200d === undefined ? DASH : r.above_200d ? 'above' : 'below' }),
    ]);
    const head = ['NAME', 'SECTOR', 'RETURN', 'σ', 'MARKET', 'SECTOR', 'OWN', 'OWN σ', 'GAP / SESSION', 'VOL', 'REPORTED', '200D'];
    host.replaceChildren(
      rows.length ? table(head, rows.slice(0, limit).map(line)) : el('div', { class: 'gap', text: 'No name moved that far on its own this session.' }),
      rows.length > limit ? el('details', { class: 'sx-fold' }, [el('summary', { text: `${rows.length - limit} more` }), table(head, rows.slice(limit).map(line))]) : null,
    );
  };
  draw();
  const threshold = data.settings?.threshold_sigma ?? 2;
  const counts = { DOWN: unusualRows(data, 'DOWN').length, UP: unusualRows(data, 'UP').length };
  const labels = ['ALL', `DOWN ${counts.DOWN}`, `UP ${counts.UP}`];
  const buttons = periodSwitch(labels, labels[0], (label) => { direction = label.split(' ')[0]; draw(); });
  return card(`UNUSUAL MOVES · OWN PART BEYOND ±${threshold}σ · ${data.as_of}`, buttons, [
    el('div', { class: 'field-note', text: `Own part: what is left after each stock's market (${data.market?.symbol}) and sector-fund betas. ${data.market?.symbol} ${signed(data.market?.ret_pct)} this session (${sigma(data.market?.z)}). Daily returns have fat tails, so more names cross ±${threshold}σ than a normal curve would suggest.` }),
    host,
    el('details', { class: 'sx-fold' }, [el('summary', { text: 'Method & caveats' }), el('div', { class: 'note-text', text: data.note })]),
  ]);
}
