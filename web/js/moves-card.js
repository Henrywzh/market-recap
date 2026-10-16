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

// "What shocks like this did next" (research v1/v2): the frozen table's rows a
// shock belongs to, the whole direction first. A row matches when every tag it
// names holds exactly; an unknown (null) tag matches nothing, never a guess.
export function stateRows(row, states) {
  if (!row?.direction || !row.tags || !states?.rows) return [];
  const mine = states.rows.filter((r) => r.direction === row.direction);
  const holds = (r) => Object.entries(r.match || {}).every(([key, want]) => row.tags[key] === want);
  return [...mine.filter((r) => !Object.keys(r.match || {}).length), ...mine.filter((r) => Object.keys(r.match || {}).length && holds(r))];
}

// Mean / median in basis points (the table stores fractions of price).
export const bpPair = (s) => (s && valid(s.mean) ? `${signed(s.mean * 1e4, 0, '')} / ${signed(s.median * 1e4, 0, '')}` : DASH);

export function statesTable(row, states) {
  const rows = stateRows(row, states);
  if (!rows.length) return null;
  const cut = (r) => r.stats?.h5 || {};
  const line = (r) => el('tr', {}, [
    el('td', { text: r.label }),
    ...['h1', 'h5', 'h20'].map((h) => el('td', { text: bpPair(r.stats?.[h]) })),
    el('td', { text: valid(cut(r).positive_share) ? `${num(100 * cut(r).positive_share, 0)}%` : DASH }),
    el('td', { text: valid(cut(r).n) ? num(cut(r).n, 0) : DASH }),
    el('td', { class: 'dim', text: valid(cut(r).lo) ? `${signed(cut(r).lo * 1e4, 0, '')} to ${signed(cut(r).hi * 1e4, 0, '')}` : DASH }),
  ]);
  const head = ['SHOCKS THAT WERE', '1D · MEAN / MEDIAN', '5D', '20D', '5D UP', 'N', '5D 95% INTERVAL'];
  return el('div', { class: 'move-states', style: 'margin-top:14px' }, [
    el('div', { class: 'stat-label', text: 'WHAT SHOCKS LIKE THIS DID NEXT · OWN PART, FROM THE NEXT OPEN (bp)' }),
    table(head, rows.map(line)),
    el('div', { class: 'field-note', text: `History since ${(states.since || '').slice(0, 4) || '2015'} for S&P 500 members; descriptive, not a forecast.` }),
  ]);
}

// The range cell's note: the band's basis, and the factor that scaled it for a shock.
export function rangeNote(row, range) {
  const base = `90% of its own history · ${range.widePrices}`;
  return valid(row.range_factor) && row.range_factor !== 1 ? `${base} · ×${num(row.range_factor, 2)}, ${row.range_reason}` : base;
}

export function moveCard(row, data) {
  if (!row) return null;
  const settings = data.settings || {};
  const range = rangeText(row.range);
  const rawRange = row.range_raw && row.range_factor !== 1 ? rangeText(row.range_raw) : null;
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
      stat(`NEXT ${settings.range_sessions} SESSIONS`, range ? range.wide : DASH, range ? rangeNote(row, range) : 'too little history'),
    ]),
    bars,
    statesTable(row, data.move_states),
    el('details', { class: 'sx-fold' }, [el('summary', { text: 'Method & caveats' }),
      el('div', { class: 'note-text', text: data.note }),
      rawRange ? el('div', { class: 'note-text', text: `Before the calibration: ${rawRange.wide}.` }) : null,
      range?.narrow ? el('div', { class: 'note-text', text: `68% range: ${range.narrow}. Ranges are the stock's own past ${settings.range_sessions}-session moves scaled to today's volatility, with the past average removed: a spread of outcomes, not a direction.` }) : null,
    ]),
  ]);
}

// A technology-only sell-off (research v6): one sentence of what followed such
// days, from the constants the panel carries. Basis points, own part against
// the rest of the sector, from the next open; descriptive.
export function selloffHistoryText(h) {
  if (!h || !h.five_day) return null;
  const bp = (v) => signed(v, 0, '');
  const span = (d) => `${bp(d.bp)} bp [${bp(d.lo)}, ${bp(d.hi)}]`;
  const list = (items) => (items || []).map((i) => `${i.label} (${bp(i.bp)})`).join(', ');
  const parts = [
    `On ${h.days} such days since ${(h.since || '').slice(0, 4)} the hardest-hit technology names ended the next 5 sessions ${span(h.five_day)} ahead of the rest of the sector`
      + (h.twenty_day ? ` and the next 20 ${span(h.twenty_day)}` : ''),
    h.strongest?.length ? `most in ${list(h.strongest)}` : null,
    h.absent?.length ? `none in ${list(h.absent)}` : null,
  ];
  return `${parts.filter(Boolean).join('; ')}.`;
}

// Names that fit the profile first, the hardest-hit first within each group.
export function selloffOrder(losers) {
  return [...(losers || [])].sort((a, b) => (Number(b.fits_profile) - Number(a.fits_profile)) || (a.ret_pct - b.ret_pct));
}

// A tag when it holds, plain dim words when it does not, a dash when unknown.
const flag = (on, yes, no) => (on === null || on === undefined ? el('span', { class: 'dim', text: DASH })
  : on ? tag(yes, 'info') : el('span', { class: 'dim', text: no }));

// Only on a technology-only sell-off session; nothing otherwise.
export function selloffBanner(data) {
  const s = data?.sector_selloff;
  if (!s?.active || !s.losers?.length) return null;
  const line = (r) => el('tr', {}, [
    el('td', {}, [el('a', { href: tickerHref(r.ticker), text: r.ticker }), el('span', { class: 'sub', text: r.name })]),
    el('td', { class: 'dim', text: r.sub_sector || DASH }),
    el('td', { class: tone(r.ret_pct), text: signed(r.ret_pct) }),
    el('td', { text: valid(r.beta_sector) ? num(r.beta_sector, 2) : DASH }),
    el('td', {}, [el('span', { class: 'tag-row' }, [
      flag(r.high_beta, 'HIGH β', 'lower β'), flag(r.session_led, 'SESSION-LED', 'gap-led'), flag(r.reported, 'REPORTED', 'no report')])]),
    el('td', {}, [r.fits_profile ? tag('FITS PROFILE', 'warn') : null]),
  ]);
  const head = ['NAME', 'SUB-INDUSTRY', 'RETURN', 'SECTOR β', 'TAGS', ''];
  const beta = valid(s.beta_median) ? ` (above ${num(s.beta_median, 2)}, the median of the sector's ${s.members} names)` : '';
  return card(`TECHNOLOGY-ONLY SELL-OFF · ${s.fund} ${sigma(s.z)} beyond ${s.market}`, null, [
    el('div', { class: 'field-note', text: selloffHistoryText(s.history) }),
    table(head, selloffOrder(s.losers).map(line)),
    el('div', { class: 'field-note', text: `The sector's hardest-hit fifth by return this session. Fits the profile: high sector beta${beta}, a fall made during the session rather than at the open, and no report.` }),
    el('div', { class: 'dim', text: s.history?.days ? `${s.history.days} such days since ${(s.history.since || '').slice(0, 4)}; history, not a forecast.` : 'History, not a forecast.' }),
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
