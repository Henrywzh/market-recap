// MOVE CHECK: how extreme one close-to-close move is in a ticker's own history.
// The ticker's close history comes through the shell's artifact loader (ctx),
// and movecheck-model.js does the arithmetic; this file only lays it out.

import { el, card, num, pct, dirClass, sectionTitle, metaRow, notice, gap, DASH } from '../fmt.js';
import { render } from '../charts.js';
import { cleanTicker, resolveTicker } from '../routes.js';
import * as M from '../movecheck-model.js';

const DEFAULT_TICKER = 'QQQ';
const HORIZON_NAMES = { 1: '1D', 5: '5D', 20: '20D' };
const LOOKBACKS = [['ALL', 'ALL'], ['5Y', '5Y'], ['1Y', '1Y']];
const LOOKBACK_NAMES = { ALL: 'ALL HISTORY', '5Y': '5 YEARS', '1Y': '1 YEAR' };
const EPISODE_ROWS = 25;
const VOLATILITY_WINDOW = 20;
const BINS = 40;
const EPISODE_NOTE = 'Description, not a signal: what followed past moves of this size; episodes overlap with '
  + 'the market\'s own regime, and N is small.';
const VIX_MISSING = 'VIX history was not available in this build, so the VIX columns are dashes.';
const VIX_BUCKET_NAMES = ['under 15', '15–20', '20–30', '30 and over'];
const DRAWDOWN_BUCKET_NAMES = ['within 5% of its 1Y high', '5–10% below its 1Y high', '10–20% below its 1Y high', 'over 20% below its 1Y high'];

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

// A signed figure as a reader reads it: −2.1σ, a plus only on a rise.
function signedText(value, suffix = '') {
  if (!isClose(value)) return DASH;
  const sign = value < 0 ? '−' : value > 0 ? '+' : '';
  return `${sign}${num(Math.abs(value), 1)}${suffix}`;
}

// A percentile in words, open at the ends: under 1st and over 99th.
function percentileWord(percentile) {
  return percentile < 1 ? 'under 1st' : percentile > 99 ? 'over 99th' : M.ordinal(percentile);
}

// The VIX level's percentile as the cell's title reads it.
function vixTitle(percentile) {
  if (!isClose(percentile)) return null;
  return `${percentileWord(percentile)} percentile of all VIX closes up to that day`;
}

// Fetches the VIX history for the episode context. It is optional: a failure is null.
async function loadVix(ctx) {
  try {
    const payload = await ctx.loadArtifact('context/vix');
    return Array.isArray(payload?.dates) && Array.isArray(payload?.close) ? payload : null;
  } catch {
    return null;
  }
}

// The stat tile for one lookback: the share of days beyond the move, with the
// count, the percentile, the yearly rate and the last such day beneath it.
function lookbackTile(key, stat) {
  const share = isClose(stat.share) ? `${num(stat.share * 100, 1)}%` : DASH;
  const perYear = isClose(stat.perYear) ? num(stat.perYear, stat.perYear >= 2 ? 0 : 1) : DASH;
  const percentile = !isClose(stat.percentile) ? DASH : percentileWord(stat.percentile);
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: `${LOOKBACK_NAMES[key]} · ${share} OF DAYS` }),
    el('div', { class: 'stat-value', text: share }),
    el('div', {
      class: 'stat-note',
      text: `${num(stat.worse, 0)} of ${num(stat.n, 0)} days · ${percentile} percentile · ${perYear} a year · last ${stat.lastWorse || DASH}`,
    }),
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
    grid: { ...option.grid, top: 26, bottom: 30, left: 36, right: 12, containLabel: true },
    xAxis: { ...option.xAxis, data: labels, boundaryGap: true, axisLabel: { hideOverlap: true, interval: 'auto' } },
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
        label: { color: p.accent, fontSize: 10, position: 'end', formatter: M.signedPct(move) },
      },
    }],
  }));
}

const EPISODE_HEAD = ['START', 'WORST DAY', 'WORST MOVE', 'FROM 1Y HIGH', 'PRIOR 20D', 'VIX', 'VIX CHANGE',
  '+1 SESSION', '+5 SESSIONS', '+20 SESSIONS', 'MAX DRAWDOWN, 20'];
const PCT_FORMAT = { text: (v) => pct(v, 1), cls: dirClass };
const LEVEL_FORMAT = { text: (v) => num(v, 1) };
const POINTS_FORMAT = { text: (v) => signedText(v) };
const SHARE_FORMAT = { text: (v) => `${num(v * 100, 0)}%` };

// A value as a cell, or a dash when it is missing.
function valueCell(value, format, attrs = {}) {
  if (!isClose(value)) return el('td', { text: DASH });
  return el('td', { class: format.cls ? format.cls(value) : null, text: format.text(value), ...attrs });
}

// One episode, or the move itself (emphasised) with dashes for the forward returns.
function episodeLine(row, emphasis = false) {
  return el('tr', { class: emphasis ? 'emphasis' : null }, [
    el('td', { class: 'dim', text: row.start }),
    el('td', { text: row.worstDate }),
    valueCell(row.worst, PCT_FORMAT),
    valueCell(row.fromHigh, PCT_FORMAT),
    valueCell(row.prior20, PCT_FORMAT),
    valueCell(row.vix, LEVEL_FORMAT, { title: vixTitle(row.vixPct) }),
    valueCell(row.vixChange, POINTS_FORMAT),
    ...row.forward.map((v) => valueCell(v, PCT_FORMAT)),
    valueCell(row.drawdown, PCT_FORMAT),
  ]);
}

function wrapTable(thead, rows, foot = null) {
  const parts = [el('thead', {}, [el('tr', {}, thead.map((h) => el('th', { text: h })))]), el('tbody', {}, rows)];
  if (foot) parts.push(foot);
  return el('div', { class: 'table-scroll' }, [el('table', { class: 'data' }, parts)]);
}

// Median of one column over every episode, with the count when some are missing.
function medianCell(values, total, format) {
  const m = M.median(values);
  if (m === null) return el('td', { text: DASH });
  const present = values.filter(isClose).length;
  return el('td', {
    class: format.cls ? format.cls(m) : null,
    text: `${format.text(m)}${present < total ? ` (n ${present})` : ''}`,
  });
}

// The numeric columns, in table order after the dates: the footer takes each one's median.
const MEDIAN_COLUMNS = [
  [(r) => r.worst, PCT_FORMAT],
  [(r) => r.fromHigh, PCT_FORMAT],
  [(r) => r.prior20, PCT_FORMAT],
  [(r) => r.vix, LEVEL_FORMAT],
  [(r) => r.vixChange, POINTS_FORMAT],
  ...M.FORWARD_SESSIONS.map((_, k) => [(r) => r.forward[k], PCT_FORMAT]),
  [(r) => r.drawdown, PCT_FORMAT],
];

function episodesBlock(rows, thisRow) {
  if (!rows.length) {
    return el('div', {}, [
      notice('No day in this window moved this far, so there are no episodes.'),
      wrapTable(EPISODE_HEAD, [episodeLine(thisRow, true)]),
    ]);
  }
  const foot = el('tfoot', {}, [el('tr', { class: 'emphasis' }, [
    el('td', { class: 'dim', text: `MEDIAN · ${rows.length} EPISODES` }),
    el('td', { text: '' }),
    ...MEDIAN_COLUMNS.map(([get, format]) => medianCell(rows.map(get), rows.length, format)),
  ])]);
  const main = wrapTable(EPISODE_HEAD, [episodeLine(thisRow, true), ...rows.slice(0, EPISODE_ROWS).map((r) => episodeLine(r))], foot);
  if (rows.length <= EPISODE_ROWS) return main;
  const older = rows.slice(EPISODE_ROWS);
  return el('div', {}, [
    main,
    el('details', { class: 'method-fold' }, [
      el('summary', { text: `Show ${older.length} older episodes` }),
      wrapTable(EPISODE_HEAD, older.map((r) => episodeLine(r))),
    ]),
  ]);
}

const DIFF_FORMAT = { text: (v) => signedText(v, ' pp'), cls: dirClass };
const GAP_FORMAT = { text: (v) => M.signedPct(v), cls: dirClass };
const STUDY_HEAD = ['', 'N', '+1 MEDIAN', '+1 SHARE UP', '+5 MEDIAN', '+5 SHARE UP', '+20 MEDIAN', '+20 SHARE UP',
  'MAX DRAWDOWN 20, MEDIAN'];

// A figure in the study tables: its value, its interval beneath when it has one, and how many
// episodes it counts when some lacked it.
function figureCell(value, format, { range = null, count = null, total = null } = {}) {
  if (!isClose(value)) return el('td', { text: DASH });
  const note = count !== null && count < total ? ` (n ${count})` : '';
  return el('td', { class: format.cls ? format.cls(value) : null }, [
    `${format.text(value)}${note}`,
    range ? el('div', { class: 'field-note', text: `${format.text(range[0])} to ${format.text(range[1])}` }) : null,
  ]);
}

// The episodes' figures and the all-days baseline over the same lookback, from the model.
function studyOf(rows, dates, close, windowed) {
  const follow = M.followUp(rows);
  const baseline = M.followUp(M.dayRows(dates, close, windowed.map((r) => r.date)));
  return {
    n: rows.length,
    days: windowed.length,
    follow,
    baseline,
    diff: M.compareFollowUp(follow, baseline),
    boot: M.bootstrapFollowUp(rows),
    years: M.episodeYears(rows),
    periods: M.halves(rows, windowed[0].date, windowed[windowed.length - 1].date),
  };
}

// Episodes against every start day in the lookback, beside the episode table: the baseline,
// the difference, the interval under each episode figure, the years covered and the two halves.
function studyBlock({ n, days, follow, baseline, diff, boot, years, periods }) {
  const forwardCells = (stats, total, ranges) => stats.forward.flatMap((f, k) => [
    figureCell(f.median, PCT_FORMAT, { count: f.n, total, range: ranges ? boot.forward[k].median : null }),
    figureCell(f.share, SHARE_FORMAT, { count: f.n, total, range: ranges ? boot.forward[k].share : null }),
  ]);
  const table = wrapTable(STUDY_HEAD, [
    el('tr', { class: 'emphasis' }, [
      el('td', { class: 'dim', text: 'EPISODES' }), el('td', { text: num(n, 0) }),
      ...forwardCells(follow, n, boot !== null),
      figureCell(follow.drawdown.median, PCT_FORMAT, { count: follow.drawdown.n, total: n }),
    ]),
    el('tr', {}, [
      el('td', { class: 'dim', text: 'ALL DAYS (BASELINE)' }), el('td', { text: `${num(days, 0)} days` }),
      ...forwardCells(baseline, days, false),
      figureCell(baseline.drawdown.median, PCT_FORMAT, { count: baseline.drawdown.n, total: days }),
    ]),
    el('tr', {}, [
      el('td', { class: 'dim', text: 'DIFFERENCE' }), el('td', { text: '' }),
      ...diff.forward.flatMap((f) => [figureCell(f.median, DIFF_FORMAT), figureCell(f.share, DIFF_FORMAT)]),
      figureCell(diff.drawdown, DIFF_FORMAT),
    ]),
  ]);

  const intervalNote = n < M.INTERVAL_MIN
    ? `N = ${n} independent episodes: no interval, as there are too few to resample.`
    : `N = ${n} independent episodes. Under each episode figure, its 90% interval: the 5th to 95th percentile over `
      + `${num(M.BOOTSTRAP_RESAMPLES, 0)} resamples of the episodes.${n < M.INTERVAL_WIDE ? ' Under 20 episodes, so the interval is wide.' : ''}`;

  // The lookback's two halves, each read from its own episodes; a half with too few is not read.
  const period = (label, list) => {
    const f = M.followUp(list).forward[2];
    const cells = [el('td', { class: 'dim', text: label }), el('td', { text: num(list.length, 0) })];
    if (list.length < M.SETUP_MIN) {
      cells.push(el('td', { colspan: '2', text: `n = ${list.length}: too few to read` }));
    } else {
      cells.push(figureCell(f.median, PCT_FORMAT, { count: f.n, total: list.length }),
        figureCell(f.share, SHARE_FORMAT, { count: f.n, total: list.length }));
    }
    return el('tr', {}, cells);
  };

  return el('div', {}, [
    el('div', { class: 'card-title', text: 'EPISODES AGAINST ALL DAYS' }),
    table,
    el('div', {
      class: 'field-note',
      text: 'Baseline: every start day in the same lookback, with the same forward returns and drawdown. '
        + 'DIFFERENCE is episodes minus baseline, in percentage points.',
    }),
    el('div', { class: 'field-note', text: intervalNote }),
    years ? el('div', { class: 'field-note', text: `Episodes span ${years.first} to ${years.last}.` }) : null,
    el('div', { class: 'card-title', text: 'CONSISTENCY ACROSS TWO PERIODS' }),
    el('div', {
      class: 'field-note',
      text: `The lookback split at ${periods.middle}: the same history in two halves, a check of consistency, `
        + 'not out-of-sample validation.',
    }),
    wrapTable(['PERIOD', 'EPISODES', '+20 MEDIAN', '+20 SHARE UP'], [
      period(`EARLIER (before ${periods.middle})`, periods.earlier),
      period(`LATER (from ${periods.middle})`, periods.later),
    ]),
  ]);
}

// The overnight-gap figures: the latest session's gap and where it sits, the share beyond 2%,
// the empirical percentiles, and the five largest gaps up and down.
function gapBody({ n, from, to, percentiles, shareLarge, up, down, latest }) {
  const list = (rows, label) => el('div', {}, [
    el('div', { class: 'card-title', text: label }),
    rows.length
      ? wrapTable(['DATE', 'GAP'], rows.map((g) => el('tr', {}, [el('td', { text: g.date }), valueCell(g.gap, GAP_FORMAT)])))
      : el('div', { class: 'field-note', text: 'None in these bars.' }),
  ]);
  return [
    el('div', {
      class: 'field-note',
      text: `Open against the prior close, daily bars ${from} to ${to}: ${num(n, 0)} sessions. Empirical percentiles, no fitted curve.`,
    }),
    el('div', { class: 'stat-strip' }, [
      el('div', { class: 'stat' }, [
        el('div', { class: 'stat-label', text: 'LATEST GAP' }),
        el('div', { class: `stat-value ${dirClass(latest.gap)}`, text: M.signedPct(latest.gap) }),
        el('div', { class: 'stat-note', text: `${latest.date} · ${percentileWord(latest.percentile)} percentile` }),
      ]),
      el('div', { class: 'stat' }, [
        el('div', { class: 'stat-label', text: `SESSIONS OVER ${M.GAP_LARGE}%` }),
        el('div', { class: 'stat-value', text: `${num(shareLarge * 100, 1)}%` }),
        el('div', { class: 'stat-note', text: `gap beyond ${M.GAP_LARGE}% either way` }),
      ]),
    ]),
    wrapTable(percentiles.map(({ p }) => M.ordinal(p).toUpperCase()), [
      el('tr', {}, percentiles.map(({ value }) => valueCell(value, GAP_FORMAT))),
    ]),
    el('div', { class: 'grid two' }, [list(up, 'LARGEST GAPS UP'), list(down, 'LARGEST GAPS DOWN')]),
  ];
}

// Episodes that sit in today's VIX band and drop from the 1Y high, beside all episodes.
function setupsBlock(setups) {
  const bucket = (names, index) => (index === null ? DASH : names[index]);
  const today = `Today: VIX ${bucket(VIX_BUCKET_NAMES, setups.vixBucket)}; `
    + `${bucket(DRAWDOWN_BUCKET_NAMES, setups.drawdownBucket)}.`;
  const line = (label, s) => {
    const cells = [el('td', { class: 'dim', text: label }), el('td', { text: num(s.n, 0) })];
    if (s.n < M.SETUP_MIN) {
      cells.push(el('td', { colspan: '5', text: `n = ${s.n}: too few to read` }));
    } else {
      cells.push(
        valueCell(s.median5, PCT_FORMAT), valueCell(s.positive5, SHARE_FORMAT),
        valueCell(s.median20, PCT_FORMAT), valueCell(s.positive20, SHARE_FORMAT),
        valueCell(s.medianDrawdown, PCT_FORMAT),
      );
    }
    return el('tr', {}, cells);
  };
  return el('div', {}, [
    el('div', { class: 'card-title', text: 'SIMILAR SETUPS' }),
    el('div', { class: 'field-note', text: today }),
    wrapTable(['SETUP', 'EPISODES', '+5 MEDIAN', '+5 SHARE UP', '+20 MEDIAN', '+20 SHARE UP', 'MAX DRAWDOWN 20, MEDIAN'], [
      line('MATCHING TODAY', setups.matched),
      line('ALL EPISODES', setups.all),
    ]),
    el('div', {
      class: 'field-note',
      text: 'Same VIX band and same drop from the 1Y high as today. Share up: the share of episodes whose later return was positive.',
    }),
  ]);
}

export default async function renderMoveCheck(root, data, _manifest, ctx = {}) {
  const tickers = data?.available || [];
  const available = new Set(tickers);
  const vix = await loadVix(ctx);
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
  // The same ticker's other tools, so a move leads straight to its page, its chart and its trade.
  const flowLinks = el('div', { class: 'field-note' });
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
  const distNode = el('div', { class: 'chart movecheck-dist' });
  const distNote = el('div', { class: 'field-note', text: '' });
  const distCard = el('div', { class: 'card' }, [
    el('div', { class: 'card-head' }, [distTitle, lookbackSwitch]),
    distNode,
    distNote,
  ]);

  const vixNote = el('div', { class: 'field-note', text: vix ? '' : VIX_MISSING });
  const episodesHost = el('div', {});
  const setupsHost = el('div', {});
  const episodesCard = card('EPISODES BEYOND THIS MOVE', null, [
    el('div', { class: 'field-note', text: EPISODE_NOTE }),
    vixNote,
    episodesHost,
    setupsHost,
  ]);

  // The gaps depend on the ticker alone, so this card loads once per ticker.
  const gapsHost = el('div', {});
  const gapsCard = card('OVERNIGHT GAPS', null, gapsHost);
  let gapsFor = null;

  const methodCopy = metaRow(
    'Moves: total-return closes, close to close. Gaps: the open against the prior close. Percentiles are empirical.',
    [
      'Returns are over 1, 5 or 20 sessions. A pair with a missing close is skipped. The history includes the move\'s own '
        + 'session, so a day that equals the move counts, and the last day named is an earlier one.',
      'ALL DAYS (BASELINE) takes every start day in the same lookback and reads the same +1, +5 and +20 returns and worst '
        + 'drawdown from each, so an episode\'s figures can be set against any day\'s. DIFFERENCE is episodes minus baseline, '
        + 'in percentage points. Share up is the share of forward returns above zero.',
      'The 90% interval resamples the episodes, the independent events after merging, 2,000 times with a fixed seed, and takes '
        + 'the 5th and 95th percentiles of their median and share up. Fewer than 5 episodes gives no interval. CONSISTENCY ACROSS '
        + 'TWO PERIODS splits the lookback at its middle date; it is the same history in two halves, not a validation.',
      'OVERNIGHT GAPS are each session\'s open against the prior close in the daily bars, since 2020, on the bars\' own basis. '
        + 'Percentiles are read off the data; the latest gap is placed among them.',
      'Percentile is the move\'s mid-rank among the returns in the window: 0 is the lowest, 100 the highest, ties counted half. '
        + 'Per year divides the days beyond the move by the years the window covers.',
      'Episodes merge days beyond the move that come within 5 sessions of each other, and show the worst day in each. Forward '
        + 'returns start at the worst day\'s close. Max drawdown is the lowest close in the 20 sessions after it, against that close, '
        + 'and is a dash when those sessions are not all in the build.',
      'FROM 1Y HIGH is the close the session before the worst day, against the highest close of the 252 sessions ending there '
        + '(a dash when the year is not all in the build). PRIOR 20D is the return over the 20 sessions before that session. '
        + 'VIX is Cboe\'s daily close, since 1990, on the worst day, with its change from the session before; its percentile '
        + 'is against the VIX closes up to that day. SIMILAR SETUPS groups episodes by VIX (under 15, 15–20, 20–30, 30 and over) '
        + 'and by the drop from the 1Y high (within 5%, 5–10%, 10–20%, over 20%), and reads no median from fewer than 5.',
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
      flowLinks,
      datalist,
    ]),
    card('THIS MOVE IN ITS HISTORY', null, [resultBody]),
    distCard,
    episodesCard,
    gapsCard,
    methodCopy,
  );

  // The links for a ticker, or none while no ticker in the build is set.
  function setFlowLinks(symbol) {
    if (!symbol) { flowLinks.replaceChildren(); return; }
    const s = encodeURIComponent(symbol);
    const items = [['TICKER PAGE', `#ticker/${s}`], ['TECHNICALS', `#technicals/${s}`], ['TRADE DESK', `#trade/${s}`]];
    const nodes = [];
    items.forEach(([label, href], index) => {
      if (index) nodes.push(' · ');
      nodes.push(el('a', { href, text: label }));
    });
    flowLinks.replaceChildren(...nodes);
  }

  // The gap card's body: a one-line note when the ticker has no bars, else the figures.
  async function gapNodes(symbol) {
    if (Array.isArray(data?.bars) && !data.bars.includes(symbol)) {
      return [gap(`${symbol} has no daily bars in this build, so there are no overnight gaps.`)];
    }
    let bars;
    try {
      bars = await ctx.loadArtifact(`bars/${encodeURIComponent(symbol)}`);
    } catch (error) {
      return [gap(`${symbol} bars could not be loaded: ${error.message}`)];
    }
    const summary = M.gapSummary(M.overnightGaps(bars));
    return summary ? gapBody(summary) : [gap(`${symbol} has no open and prior close pairs in its bars.`)];
  }

  async function refreshGaps(symbol) {
    if (symbol === gapsFor) return;
    gapsFor = symbol;
    gapsHost.replaceChildren(gap('Loading overnight gaps…'));
    const nodes = await gapNodes(symbol);
    if (gapsFor === symbol) gapsHost.replaceChildren(...nodes);
  }

  // Runs the check for the ticker in the box and the horizon and move as set. A
  // new ticker, or a new horizon, takes the latest move as the box's default.
  async function check({ resetMove = false } = {}) {
    const current = ++run;
    const raw = cleanTicker(tickerInput.value);
    const symbol = raw ? resolveTicker(raw, (t) => available.has(t)) : null;
    if (!symbol) { setFlowLinks(null); status.textContent = 'Enter a ticker, such as QQQ.'; return; }
    if (!available.has(symbol)) { setFlowLinks(null); status.textContent = `${symbol} is not in this build.`; return; }
    setFlowLinks(symbol);
    const gapsDone = refreshGaps(symbol);
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
      setupsHost.replaceChildren();
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
        el('div', { class: `stat-value ${dirClass(sigma)}`, text: signedText(sigma, 'σ') }),
        el('div', { class: 'stat-note', text: `${VOLATILITY_WINDOW}-session window` }),
      ]),
    );

    const windowed = M.lastSessions(series, M.LOOKBACKS[lookback]);
    const hist = M.histogram(windowed.map((r) => r.ret), BINS, { include: [move] });
    distTitle.textContent = `${HORIZON_NAMES[horizon]} RETURNS, ${LOOKBACK_NAMES[lookback]}`;
    distNote.textContent = `${num(windowed.length, 0)} returns in the window. Dashed line: the move. Coloured bars are at or beyond it.`;
    histogramChart(distNode, hist, move);

    const context = (day) => M.contextOn({ dates, close, vix, date: day });
    // The move's own session is THIS MOVE, not a past episode: it has no forward returns yet.
    const rows = M.episodes(windowed, move).filter((ep) => ep.worstDate !== date).reverse().map((ep) => ({
      ...ep,
      ...context(ep.worstDate),
      forward: M.FORWARD_SESSIONS.map((s) => M.forward(dates, close, ep.worstDate, s)),
      drawdown: M.maxDrawdownAfter(dates, close, ep.worstDate, M.DRAWDOWN_SESSIONS),
    }));
    const today = context(date);
    const thisRow = {
      start: 'THIS MOVE', worstDate: date, worst: move, ...today,
      forward: M.FORWARD_SESSIONS.map(() => null), drawdown: null,
    };
    const study = rows.length ? studyOf(rows, dates, close, windowed) : null;
    episodesHost.replaceChildren(episodesBlock(rows, thisRow), ...(study ? [studyBlock(study)] : []));
    setupsHost.replaceChildren(setupsBlock(M.similarSetups(rows, today)));

    status.textContent = `${symbol} · ${num(series.length, 0)} ${HORIZON_NAMES[horizon]} returns to ${date}`;
    await gapsDone;
  }

  const requested = resolveTicker(cleanTicker(ctx.arg) || DEFAULT_TICKER, (t) => available.has(t));
  tickerInput.value = available.has(requested) ? requested : (tickers[0] || DEFAULT_TICKER);
  await check({ resetMove: true });
}
