// MOVE CHECK: how extreme one close-to-close move is in a ticker's own history.
// The ticker's close history comes through the shell's artifact loader (ctx),
// and movecheck-model.js does the arithmetic; this file only lays it out.

import { el, card, num, pct, dirClass, sectionTitle, metaRow, notice, DASH } from '../fmt.js';
import { render } from '../charts.js';
import { cleanTicker, resolveTicker } from '../routes.js';
import * as M from '../movecheck-model.js';

const DEFAULT_TICKER = 'QQQ';
const HORIZON_NAMES = { 1: '1D', 5: '5D', 20: '20D' };
const LOOKBACKS = [['ALL', 'ALL'], ['5Y', '5Y'], ['1Y', '1Y']];
const LOOKBACK_NAMES = { ALL: 'ALL HISTORY', '5Y': '5 YEARS', '1Y': '1 YEAR' };
const EPISODE_ROWS = 25;
const FORWARD_SESSIONS = [1, 5, 20];
const DRAWDOWN_SESSIONS = 20;
const VOLATILITY_WINDOW = 20;
const BINS = 40;
const EPISODE_NOTE = 'Description, not a signal: what followed past moves of this size; episodes overlap with '
  + 'the market\'s own regime, and N is small.';

const isClose = (value) => typeof value === 'number' && Number.isFinite(value);

// A row of exclusive buttons in the period-switch style; onPick gets the key.
function switchOf(options, active, onPick) {
  const keys = options.map(([key]) => key);
  const buttons = options.map(([key, label]) => el('button', {
    type: 'button', text: label, onclick: () => { wrap.setActive(key); onPick(key); },
  }));
  const wrap = el('div', { class: 'period-switch' }, buttons);
  wrap.setActive = (key) => buttons.forEach((b, i) => b.setAttribute('aria-pressed', String(keys[i] === key)));
  wrap.setActive(active);
  return wrap;
}

// Sigma as a reader reads it: −2.1σ, a plus only on a rise.
function sigmaText(value) {
  if (!isClose(value)) return DASH;
  const sign = value < 0 ? '−' : value > 0 ? '+' : '';
  return `${sign}${num(Math.abs(value), 1)}σ`;
}

// The stat tile for one lookback: the share of days beyond the move, with the
// percentile, the yearly rate and the last such day beneath it.
function lookbackTile(key, stat) {
  const share = isClose(stat.share) ? `${num(stat.share * 100, 1)}%` : DASH;
  const perYear = isClose(stat.perYear) ? num(stat.perYear, stat.perYear >= 2 ? 0 : 1) : DASH;
  const percentile = !isClose(stat.percentile) ? DASH
    : stat.percentile < 1 ? 'under 1st' : stat.percentile > 99 ? 'over 99th' : M.ordinal(stat.percentile);
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: `${LOOKBACK_NAMES[key]} · ${stat.worse} OF ${num(stat.n, 0)} DAYS` }),
    el('div', { class: 'stat-value', text: share }),
    el('div', { class: 'stat-note', text: `${percentile} percentile · ${perYear} a year · last ${stat.lastWorse || DASH}` }),
  ]);
}

// The move's own distribution: returns in bins, the tail beyond the move in
// the move's colour, and a dashed line at the move.
function histogramChart(node, { edges, counts }, move) {
  const down = move < 0;
  const moveBin = M.binIndex(edges, move);
  const labels = counts.map((_, k) => `${num((edges[k] + edges[k + 1]) / 2, 1)}%`);
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, top: 10, bottom: 24 },
    xAxis: { ...option.xAxis, data: labels, boundaryGap: true },
    yAxis: { ...option.yAxis, min: 0, scale: false },
    series: [{
      name: 'Returns', type: 'bar', barCategoryGap: '20%',
      data: counts.map((count, k) => {
        const beyond = down ? edges[k] <= move : edges[k + 1] >= move;
        return { value: count, itemStyle: { color: beyond ? (down ? p.down : p.up) : p.faint } };
      }),
      markLine: {
        silent: true, symbol: 'none', data: moveBin === null ? [] : [{ xAxis: moveBin }],
        lineStyle: { color: p.accent, type: 'dashed', width: 1 },
        label: { color: p.accent, fontSize: 10, formatter: M.signedPct(move) },
      },
    }],
  }));
}

const EPISODE_HEAD = ['START', 'WORST DAY', 'WORST MOVE', '+1 SESSION', '+5 SESSIONS', '+20 SESSIONS', 'MAX DRAWDOWN, 20'];

function episodeLine(row) {
  return el('tr', {}, [
    el('td', { class: 'dim', text: row.start }),
    el('td', { text: row.worstDate }),
    el('td', { class: dirClass(row.worst), text: pct(row.worst, 1) }),
    ...row.forward.map((v) => el('td', { class: dirClass(v), text: v === null ? DASH : pct(v, 1) })),
    el('td', { class: dirClass(row.drawdown), text: row.drawdown === null ? DASH : pct(row.drawdown, 1) }),
  ]);
}

function wrapTable(thead, rows, foot = null) {
  const parts = [el('thead', {}, [el('tr', {}, thead.map((h) => el('th', { text: h })))]), el('tbody', {}, rows)];
  if (foot) parts.push(foot);
  return el('div', { class: 'table-scroll' }, [el('table', { class: 'data' }, parts)]);
}

// Median of each numeric column over every episode, with the count when some are missing.
function medianCell(values, total) {
  const m = M.median(values);
  if (m === null) return el('td', { text: DASH });
  const present = values.filter(isClose).length;
  return el('td', { class: dirClass(m), text: `${pct(m, 1)}${present < total ? ` (n ${present})` : ''}` });
}

function episodesBlock(rows) {
  if (!rows.length) return notice('No day in this window moved this far, so there are no episodes.');
  const columns = [
    rows.map((r) => r.worst),
    ...FORWARD_SESSIONS.map((_, k) => rows.map((r) => r.forward[k])),
    rows.map((r) => r.drawdown),
  ];
  const foot = el('tfoot', {}, [el('tr', { class: 'emphasis' }, [
    el('td', { class: 'dim', text: `MEDIAN · ${rows.length} EPISODES` }),
    el('td', { text: '' }),
    ...columns.map((values) => medianCell(values, rows.length)),
  ])]);
  const main = wrapTable(EPISODE_HEAD, rows.slice(0, EPISODE_ROWS).map(episodeLine), foot);
  if (rows.length <= EPISODE_ROWS) return main;
  const older = rows.slice(EPISODE_ROWS);
  return el('div', {}, [
    main,
    el('details', { class: 'method-fold' }, [
      el('summary', { text: `Show ${older.length} older episodes` }),
      wrapTable(EPISODE_HEAD, older.map(episodeLine)),
    ]),
  ]);
}

export default async function renderMoveCheck(root, data, _manifest, ctx = {}) {
  const tickers = data?.available || [];
  const available = new Set(tickers);
  root.append(sectionTitle('MOVE CHECK', 'HOW EXTREME IS THIS MOVE IN ITS OWN HISTORY'));

  let horizon = 1;
  let lookback = 'ALL';
  let shown = null;
  // The latest move as the box shows it, with its exact value: an untouched box
  // checks the true move, so a day that equals it counts.
  let prefill = { text: '', value: null };
  let run = 0;

  const tickerInput = el('input', { value: '', size: '8', list: 'movecheck-list', autocomplete: 'off', 'aria-label': 'Ticker' });
  const datalist = el('datalist', { id: 'movecheck-list' }, tickers.map((t) => el('option', { value: t })));
  const moveInput = el('input', { type: 'number', step: 'any', size: '8', 'aria-label': 'Move in percent' });
  const status = el('span', { class: 'field-note', text: '' });
  const horizonSwitch = switchOf(M.HORIZONS.map((h) => [h, HORIZON_NAMES[h]]), horizon, (h) => {
    horizon = h;
    check({ resetMove: true });
  });
  const checkButton = el('button', { class: 'action', text: 'CHECK', onclick: () => check() });
  for (const input of [tickerInput, moveInput]) {
    input.addEventListener('keydown', (event) => { if (event.key === 'Enter') check(); });
  }

  const headline = el('div', { class: 'move-headline' });
  const statHost = el('div', { class: 'stat-strip' });
  const resultBody = el('div', {}, [headline, statHost]);

  const lookbackSwitch = switchOf(LOOKBACKS, lookback, (key) => { lookback = key; check(); });
  const distTitle = el('span', { class: 'card-title', text: '' });
  const distNode = el('div', { class: 'chart short' });
  const distNote = el('div', { class: 'field-note', text: '' });
  const distCard = el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [distTitle, lookbackSwitch]),
    distNode,
    distNote,
  ]);

  const episodesHost = el('div', {});
  const episodesCard = card('EPISODES BEYOND THIS MOVE', null, [
    el('div', { class: 'field-note', text: EPISODE_NOTE }),
    episodesHost,
  ]);

  const methodCopy = metaRow(
    'Total-return closes, close to close. Percentile is empirical.',
    [
      'Returns are over 1, 5 or 20 sessions. A pair with a missing close is skipped. The history includes the move\'s own '
        + 'session, so a day that equals the move counts, and the last day named is an earlier one.',
      'Percentile is the move\'s mid-rank among the returns in the window: 0 is the lowest, 100 the highest, ties counted half. '
        + 'Per year divides the days beyond the move by the years the window covers.',
      'Episodes merge days beyond the move that come within 5 sessions of each other, and show the worst day in each. Forward '
        + 'returns start at the worst day\'s close. Max drawdown is the lowest close in the 20 sessions after it, against that close, '
        + 'and is a dash when those sessions are not all in the build.',
      '5- and 20-session returns overlap, so their counts are of overlapping windows, not independent episodes. In today\'s '
        + 'volatility, the move is divided by the stdev of the 20 daily returns before it, scaled by the square root of the horizon.',
    ],
  );

  root.append(
    el('div', { class: 'card' }, [
      el('div', { class: 'card-head' }, [el('span', { class: 'card-title', text: 'CHECK A MOVE' })]),
      el('div', { class: 'field-row' }, [
        el('div', { class: 'field' }, [el('label', { text: 'TICKER' }), tickerInput]),
        el('div', { class: 'field' }, [el('label', { text: 'HORIZON' }), horizonSwitch]),
        el('div', { class: 'field' }, [el('label', { text: 'MOVE %' }), moveInput]),
        checkButton,
        status,
      ]),
      datalist,
    ]),
    card('THIS MOVE IN ITS HISTORY', null, [resultBody]),
    distCard,
    episodesCard,
    methodCopy,
  );

  // Runs the check for the ticker in the box and the horizon and move as set. A
  // new ticker, or a new horizon, takes the latest move as the box's default.
  async function check({ resetMove = false } = {}) {
    const current = ++run;
    const raw = cleanTicker(tickerInput.value);
    const symbol = raw ? resolveTicker(raw, (t) => available.has(t)) : null;
    if (!symbol) { status.textContent = 'Enter a ticker, such as QQQ.'; return; }
    if (!available.has(symbol)) { status.textContent = `${symbol} is not in this build.`; return; }
    status.textContent = `Loading ${symbol}…`;

    let payload;
    try {
      payload = await ctx.loadArtifact(`tickers/${symbol}`);
    } catch (error) {
      if (current === run) status.textContent = `${symbol} could not be loaded: ${error.message}`;
      return;
    }
    if (current !== run) return;
    ctx.setArg?.(symbol);

    const dates = payload?.dates;
    const close = payload?.close;
    if (!Array.isArray(dates) || !Array.isArray(close)) {
      status.textContent = `${symbol} has no close history in this build.`;
      return;
    }

    const series = M.returns(dates, close, horizon);
    const daily = M.returns(dates, close, 1);
    if (!series.length) {
      const closes = close.filter(isClose).length;
      status.textContent = `Not enough history for ${symbol} at ${HORIZON_NAMES[horizon]}: needs ${horizon + 1} sessions with closes, has ${closes}.`;
      headline.textContent = '';
      statHost.replaceChildren();
      distNode.replaceChildren();
      episodesHost.replaceChildren();
      return;
    }

    const latest = series[series.length - 1];
    if (resetMove || symbol !== shown) {
      const text = String(Math.round(latest.ret * 100) / 100);
      moveInput.value = text;
      prefill = { text, value: latest.ret };
      shown = symbol;
    }
    const typed = moveInput.value.trim();
    const move = typed === prefill.text && prefill.value !== null ? prefill.value : (typed === '' ? NaN : Number(typed));
    if (!Number.isFinite(move)) {
      status.textContent = 'Type a move in percent, such as -3.';
      return;
    }

    const date = latest.date;
    const stats = Object.fromEntries(LOOKBACKS.map(([key]) => [
      key, M.checkMove(series, move, { lookbackSessions: M.LOOKBACKS[key], date }),
    ]));
    const sigma = M.sigmaOf(daily, move, VOLATILITY_WINDOW, horizon);

    headline.textContent = M.moveSentence({ ticker: symbol, horizon, move, date, all: stats.ALL });
    statHost.replaceChildren(
      ...LOOKBACKS.map(([key]) => lookbackTile(key, stats[key])),
      el('div', { class: 'stat' }, [
        el('div', { class: 'stat-label', text: 'IN TODAY\'S VOLATILITY' }),
        el('div', { class: `stat-value ${dirClass(sigma)}`, text: sigmaText(sigma) }),
        el('div', { class: 'stat-note', text: `${VOLATILITY_WINDOW}-session window` }),
      ]),
    );

    const windowed = M.lastSessions(series, M.LOOKBACKS[lookback]);
    const hist = M.histogram(windowed.map((r) => r.ret), BINS, { include: [move] });
    distTitle.textContent = `${HORIZON_NAMES[horizon]} RETURNS, ${LOOKBACK_NAMES[lookback]}`;
    distNote.textContent = `${num(windowed.length, 0)} returns in the window. Dashed line: the move. Coloured bars are at or beyond it.`;
    histogramChart(distNode, hist, move);

    const rows = M.episodes(windowed, move).reverse().map((ep) => ({
      ...ep,
      forward: FORWARD_SESSIONS.map((s) => M.forward(dates, close, ep.worstDate, s)),
      drawdown: M.maxDrawdownAfter(dates, close, ep.worstDate, DRAWDOWN_SESSIONS),
    }));
    episodesHost.replaceChildren(episodesBlock(rows));

    status.textContent = `${symbol} · ${num(series.length, 0)} ${HORIZON_NAMES[horizon]} returns to ${date}`;
  }

  const requested = resolveTicker(cleanTicker(ctx.arg) || DEFAULT_TICKER, (t) => available.has(t));
  tickerInput.value = available.has(requested) ? requested : (tickers[0] || DEFAULT_TICKER);
  await check({ resetMove: true });
}
