// TODAY read live: the board, its headline and the RARE and OVERSOLD signals
// recomputed from intraday quotes, by the build's own rules (panels/today.py).
// Kept apart from the DOM so it can be tested under node.
//
// Each board row carries what a live reading needs from the last close: its
// 60-session sigma, a ladder of past moves by the share of sessions that
// matched them, and the RSI's smoothed gain and loss. A row whose quote did not
// arrive is left off the live board rather than shown at last night's figure.

const finite = (v) => typeof v === 'number' && Number.isFinite(v);

// The build's thresholds, the same numbers as panels/today.py.
export const BOARD_RARE_PCT = 1.0;
export const MOVE_TAIL_PCT = 5.0;
const FLAT_MOVE_PCT = 0.3;
const BREADTH_GAP_PCT = 1.0;
const LEAD_GAP_PCT = 1.0;
const AGAINST_MIN_PCT = 1.0;
const NAMED_SECTORS = 2;
// compute/oversold.py LINES, deepest first.
const LINES = [[20, 'deeply oversold'], [30, 'oversold']];

// The share of past sessions at or beyond `ret` in its direction, read off the
// ladder by straight-line interpolation between its points. Null past the 50%
// point (the build states no share there) or without a ladder; 0 beyond the
// largest move on record.
export function ladderShare(ladder, ret) {
  if (!ladder || !finite(ret) || ret === 0) return null;
  const sign = ret > 0 ? 1 : -1;
  const points = (sign > 0 ? ladder.up : ladder.down) || [];
  if (!points.length) return null;
  const size = sign * ret;
  const at = points.map(([move, share]) => [sign * move, share]);
  if (size < at[0][0]) return null;
  const last = at[at.length - 1];
  if (size > last[0]) return 0;
  for (let i = 1; i < at.length; i += 1) {
    const [m1, s1] = at[i];
    const [m0, s0] = at[i - 1];
    if (size <= m1) return m1 === m0 ? s1 : s0 + ((size - m0) / (m1 - m0)) * (s1 - s0);
  }
  return last[1];
}

// Wilder's RSI with the live price as the next close, from the state at the
// last close; with the run of closes below each line it extends.
export function liveRsi(state, price) {
  if (!state || !finite(price) || !finite(state.close) || !finite(state.gain) || !finite(state.loss)) return null;
  const p = state.period || 6;
  const change = price - state.close;
  const gain = ((p - 1) * state.gain + Math.max(change, 0)) / p;
  const loss = ((p - 1) * state.loss + Math.max(-change, 0)) / p;
  const rsi = loss === 0 ? (gain === 0 ? 50 : 100) : 100 - 100 / (1 + gain / loss);
  const run = (line) => (rsi < line ? (state.below?.[String(line)] || 0) + 1 : 0);
  const hit = LINES.find(([line]) => rsi < line);
  return { rsi, line: hit ? hit[0] : null, verdict: hit ? hit[1] : null, days: hit ? run(hit[0]) : 0, days_shallow: run(30) };
}

// The board as of the quotes: each row with a live move, its sigma multiple,
// its share and its RSI. Null without the S&P 500's quote (the headline reads it first).
export function liveBoard(board, quotes) {
  if (!board?.rows?.length || !quotes) return null;
  const rows = [];
  board.rows.forEach((row) => {
    const quote = quotes.get(row.symbol);
    if (!quote || !finite(quote.change_pct)) return;
    const ret = quote.change_pct;
    const reading = liveRsi(row.rsi_state, quote.price);
    const share = ladderShare(row.ladder, ret);
    rows.push({
      ...row,
      ret_pct: ret,
      z: finite(row.sigma_pct) && row.sigma_pct > 0 ? ret / row.sigma_pct : null,
      share_pct: finite(share) ? share : null,
      rsi6: reading ? reading.rsi : null,
      reading,
      time: quote.time ?? null,
    });
  });
  if (!rows.some((r) => r.symbol === '^GSPC')) return null;
  const vix = quotes.get('^VIX');
  return {
    live: true,
    time: quotes.get('^GSPC').time ?? null,
    rows,
    vix: { value: finite(vix?.price) ? vix.price : null, change: finite(vix?.change) ? vix.change : null },
  };
}

// --- The headline, by the build's template (panels/today.py headline) -------

const plainSigned = (value, suffix = '') => `${Math.round(value * 10) / 10 < 0 ? '−' : '+'}${Math.abs(value).toFixed(1)}${suffix}`;
const named = (row) => `${row.short} ${plainSigned(row.ret_pct, '%')}${finite(row.share_pct) && row.share_pct <= BOARD_RARE_PCT ? ' (rare)' : ''}`;
const and = (items) => (items.length <= 2 ? items.join(' and ') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`);

function marketTitle(bySymbol, sectors) {
  const spx = bySymbol['^GSPC'];
  if (!spx) return null;
  const s = spx.ret_pct;
  const rsp = bySymbol.RSP;
  const gap = rsp ? rsp.ret_pct - s : 0;
  let word;
  if (Math.abs(s) < FLAT_MOVE_PCT) word = 'Flat day';
  else if (s < 0) {
    word = gap >= BREADTH_GAP_PCT && rsp.ret_pct >= 0 ? 'Mega-cap selloff while the average stock rose'
      : gap >= BREADTH_GAP_PCT ? 'Mega-cap selloff'
        : -gap >= BREADTH_GAP_PCT ? 'Broad selloff' : s <= -1 ? 'Selloff' : 'Down day';
  } else {
    word = -gap >= BREADTH_GAP_PCT && rsp.ret_pct <= 0 ? 'Mega-cap rally while the average stock fell'
      : -gap >= BREADTH_GAP_PCT ? 'Narrow rally in the largest names'
        : gap >= BREADTH_GAP_PCT ? 'Broad rally' : s >= 1 ? 'Rally' : 'Up day';
  }
  const ranked = [...sectors].sort((a, b) => a.ret_pct - b.ret_pct);
  if (Math.abs(s) < FLAT_MOVE_PCT) {
    const down = ranked.filter((r) => r.ret_pct <= -AGAINST_MIN_PCT).slice(0, NAMED_SECTORS);
    const up = [...ranked].reverse().filter((r) => r.ret_pct >= AGAINST_MIN_PCT).slice(0, NAMED_SECTORS);
    return [word, ...(up.length ? [`up: ${and(up.map(named))}`] : []), ...(down.length ? [`down: ${and(down.map(named))}`] : [])].join('; ');
  }
  const withIndex = s < 0 ? ranked : [...ranked].reverse();
  const dir = s > 0 ? 1 : -1;
  const lead = withIndex.filter((r) => (r.ret_pct - s) * dir >= LEAD_GAP_PCT).slice(0, NAMED_SECTORS);
  const against = [...withIndex].reverse().filter((r) => r.ret_pct * dir <= -AGAINST_MIN_PCT).slice(0, NAMED_SECTORS);
  let title = lead.length ? `${word}, led by ${and(lead.map(named))}` : word;
  if (against.length) title += `; ${and(against.map(named))} ${s < 0 ? 'rose' : 'fell'}`;
  return title;
}

export function headlineOf(board) {
  const rows = board?.rows || [];
  if (rows.length < 3) return null;
  const bySymbol = Object.fromEntries(rows.map((r) => [r.symbol, r]));
  const sectors = rows.filter((r) => r.group === 'sector');
  const parts = [];
  const indices = ['^GSPC', '^NDX', 'RSP', 'IWM'].filter((s) => bySymbol[s]).map((s) => bySymbol[s]);
  if (indices.length) parts.push(`${indices.map((r) => `${r.short} ${plainSigned(r.ret_pct, '%')}`).join(', ')}.`);
  const rare = sectors.filter((r) => finite(r.share_pct) && r.share_pct <= BOARD_RARE_PCT).sort((a, b) => a.share_pct - b.share_pct);
  if (rare.length) {
    parts.push(`Rare: ${rare.map((r) => `${r.short} ${r.ret_pct > 0 ? 'rose' : 'fell'} this far on ${r.share_pct.toFixed(1)}% of days`).join('; ')}.`);
  }
  const vix = board.vix || {};
  if (finite(vix.value)) parts.push(`VIX ${vix.value.toFixed(1)}${finite(vix.change) ? ` (${plainSigned(vix.change)})` : ''}.`);
  if (!parts.length) return null;
  const spx = bySymbol['^GSPC'];
  const tone = !spx || Math.abs(spx.ret_pct) < FLAT_MOVE_PCT ? 'flat' : spx.ret_pct < 0 ? 'down' : 'up';
  return { title: marketTitle(bySymbol, sectors), text: parts.join(' '), tone };
}

// --- RARE and OVERSOLD from the live board -----------------------------------

const TAIL_DETAIL = 'How rare in its own history, not what comes next, read from today\'s quote against every past session. MOVE CHECK lists what followed past moves this size.';

// The two signal groups the live board replaces, in the build's item shape so the
// SIGNALS card draws them unchanged: one-session tails and the RSI(6) lines.
// `detail` carries the build's own oversold explanation onto the live chips.
export function liveSignals(board, { oversoldDetail = '' } = {}) {
  const rows = board?.rows || [];
  const tails = rows
    .filter((r) => finite(r.share_pct) && r.share_pct <= MOVE_TAIL_PCT)
    .sort((a, b) => a.share_pct - b.share_pct)
    .map((r) => ({
      kind: 'tail', subject: r.label, value: r.ret_pct, unit: '%', link: `#movecheck/${r.symbol}`,
      title: `${r.label} ${r.ret_pct < 0 ? 'down' : 'up'} ${Math.abs(r.ret_pct).toFixed(1)}% so far today: matched or beyond on ${r.share_pct.toFixed(1)}% of past sessions`,
      detail: TAIL_DETAIL, extra: { symbol: r.symbol, horizon: 1, share_pct: r.share_pct },
    }));
  const oversold = rows
    .filter((r) => r.reading?.line !== null && r.reading?.line !== undefined)
    .sort((a, b) => a.reading.rsi - b.reading.rsi)
    .map((r) => ({
      kind: 'oversold', subject: r.label, value: r.reading.rsi, link: `#technicals/${r.symbol}`,
      title: `${r.label} ${r.reading.verdict} on today's quote: RSI(6) ${r.reading.rsi.toFixed(1)}, ${r.reading.days === 1 ? 'first' : `${r.reading.days} in a row`} below ${r.reading.line}`,
      detail: oversoldDetail,
      extra: { symbol: r.symbol, rsi: Math.round(r.reading.rsi * 10) / 10, line: r.reading.line, verdict: r.reading.verdict, days_below_30: r.reading.days_shallow },
    }));
  return { tails, oversold };
}
