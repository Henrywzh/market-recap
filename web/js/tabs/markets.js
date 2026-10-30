import { el, card, table, tag, num, pct, dirClass, periodSwitch, sectionTitle, notice, DASH } from '../fmt.js';
import { multiLine, disposeWithin } from '../charts.js';
import { mountLive } from '../live.js';
import { mountIndexCharts } from '../live-indices.js';
import { spark } from '../spark.js';
import { readingText, readingNote, outcomeCell, stateSummary, daysNow, sectorFlag, statePresentation } from '../market-state-model.js';
import { performanceCard, volatilityLine } from '../session-cards.js';
import { indexHistory } from '../index-history.js';

// One row per index: how far it sits below its high, and how many members rose.
// Side by side, so the indices compare before one is opened below.
function indexComparison(blocks) {
  const rows = blocks.map((block) => {
    const drawdown = block.drawdown || {};
    const ad = block.advance_decline;
    return el('tr', {}, [
      el('td', {}, [el('span', { text: block.key }), el('span', { class: 'sub', text: block.label })]),
      el('td', {}, [
        el('span', { class: dirClass(drawdown.drawdown_pct), text: pct(drawdown.drawdown_pct) }),
        el('span', { class: 'sub', text: `${drawdown.trading_days_since_high ?? DASH} TRADING DAYS · HIGH ${drawdown.high_date ?? DASH}` }),
      ]),
      el('td', {}, ad ? [
        el('span', { class: 'up', text: ad.advancers }),
        ' / ',
        el('span', { class: 'down', text: ad.decliners }),
        ' / ',
        el('span', { class: 'dim', text: ad.unchanged }),
      ] : [el('span', { class: 'dim', text: DASH })]),
      el('td', { text: ad?.ratio ?? DASH }),
    ]);
  });
  return table(['INDEX', 'DRAWDOWN FROM HIGH', 'ADV / DEC / UNCH', 'RATIO'], rows, { class: 'index-compare' });
}

function sectorTable(data) {
  // Columns come from the artifact, which got them from the contract. A list
  // spelled out here would silently stop matching the day someone changed it.
  const cols = data.periods;
  const makeRow = (row, emphasis) => el('tr', { class: emphasis ? 'emphasis' : '' }, [
    el('td', { text: row.sector }),
    el('td', { class: 'dim', text: row.etf || DASH }),
    el('td', { text: num(row.weight_pct) }),
    el('td', { class: dirClass(row.contribution_1d), text: row.contribution_1d === null ? DASH : num(row.contribution_1d, 3) }),
    ...cols.map((c) => el('td', { class: dirClass(row[c]), text: pct(row[c]) })),
  ]);
  const rows = [makeRow(data.index, true), ...data.rows.map((r) => makeRow(r, false))];
  return card(
    'SECTOR PERFORMANCE / WEIGHT / CONTRIBUTION (1D)',
    null,
    [
      table(['SECTOR', 'ETF', 'WEIGHT%', 'CONTRIB 1D', ...cols], rows),
      el('div', { class: 'note-text' }, [
        `Contribution is the sector's ${data.source} multiplied by its cap-weighted 1D return, `,
        'so the sector rows sum to the index row. Returns are computed from constituents, not from the ETF wrapper.',
      ]),
    ],
  );
}

function breadthTable(data) {
  const cols = data.windows.map((w) => `>${w}D`);
  const rows = data.rows.map((row) => el('tr', {}, [
    el('td', { text: row.sector }),
    el('td', { class: 'dim', text: row.n }),
    ...cols.map((c) => el('td', { class: row[c] >= 50 ? 'up' : 'down', text: row[c] === null ? DASH : num(row[c], 1) })),
  ]));
  return card('MARKET BREADTH BY SECTOR — % OF STOCKS ABOVE MOVING AVERAGE', null,
    table(['SECTOR', 'N', ...cols], rows));
}

function slopeTable(data) {
  const cols = data.windows.map((w) => `${w}D`);
  const window = data.trend_window;
  const rows = data.rows.map((row) => el('tr', {}, [
    el('td', { text: row.sector }),
    el('td', { class: 'dim', text: row.etf }),
    ...cols.map((c) => el('td', { class: dirClass(row[c]), text: pct(row[c]) })),
  ]));
  return card(`${window}-DAY MOVING AVERAGE SLOPE BY SECTOR (% CHANGE IN SMA${window} OVER WINDOW)`, null,
    table(['SECTOR', 'ETF', ...cols], rows));
}

// A session Yahoo dropped or got wrong, rebuilt from other publishers: said at
// the top of the page, because every figure below it depends on that session.
function filledNotice(manifest) {
  const filled = Object.entries((manifest && manifest.filled_sessions) || {});
  if (!filled.length) return null;
  const days = [...new Set(filled.map(([key]) => key.split(' ')[0]))].join(', ');
  const count = (source) => filled.reduce((n, [, r]) => n + (r[source] || 0), 0);
  const unfilled = filled.flatMap(([, r]) => r.unfilled_symbols || []);
  const why = [...new Set(filled.map(([, r]) => r.reason))].join('; ');
  return notice(
    `${days}: ${why}. Rebuilt from iShares IVV holdings (${count('ishares')} closes), Nasdaq (${count('nasdaq')}) `
    + `and FRED (${count('fred')})${unfilled.length ? `; still missing: ${unfilled.join(', ')}` : ''}.`,
  );
}

// A spin-off the price feed does not adjust for, adjusted by the build: said at
// the top, because a returns table that read it as a loss would be wrong, and a
// table that quietly corrected it would be unexplained.
function actionsNotice(manifest) {
  const actions = (manifest && manifest.corporate_actions) || [];
  if (!actions.length) return null;
  return notice(actions.map((a) => (a.factor === null
    ? `${a.ticker}: the ${a.kind} on ${a.ex_date} could not be adjusted, so its history before that date is blank.`
    : `${a.ticker}: prices before ${a.ex_date} are adjusted (x${a.factor.toFixed(4)}) for the ${a.kind} of ${a.distributed}, `
      + `${a.ratio} share per share held; the feed does not adjust for spin-offs.`)).join(' '));
}

// --- market state --------------------------------------------------------------

function marketStateSection(state) {
  const horizon = state.settings.horizon_period;
  const strip = el('div', { class: 'stat-strip ms-strip' }, state.readings.map((r) => el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: r.label }),
    el('div', { class: 'stat-value', text: readingText(r) }),
    el('div', { class: 'ms-spark' }, [spark(r.spark, { width: 120, height: 22 })]),
    el('div', { class: 'stat-note', text: readingNote(r) || (['rsp_spy', 'iwm_spy'].includes(r.key) ? `PRICE RATIO CHANGE OVER ${state.settings.relative_period}` : r.key === 'spy_drawdown' ? `FROM ${state.settings.high_period} HIGH` : '') }),
  ])));

  const funds = el('div', { class: 'ms-funds' }, state.sectors.map((row) => {
    const flag = sectorFlag(row);
    return el('span', { class: `ms-fund ${flag.tone}`, title: `${row.sector}: ${row.above_200 === null ? DASH : row.above_200 ? 'above' : 'below'} its ${state.settings.long_ma}-day line` }, [
      el('b', { text: row.etf }), ` ${flag.text}`,
    ]);
  }));

  const summary = stateSummary(state.states, state.settings.drawdown_floor_pct);
  const total = state.states.length;
  const riskCount = state.states.filter((st) => statePresentation(st).level === 'risk').length;
  const sentence = `${summary.holding.length} / ${total} active · ${riskCount} caution.${summary.holding.length ? ' Click a condition for the full comparison.' : ''}`;
  let history;
  const board = el('div', { class: 'ms-active-list', 'aria-label': 'Active market conditions' }, state.states.filter((st) => st.active_now).map((st) => {
    const view = statePresentation(st);
    return el('button', { type: 'button', class: `ms-chip ms-chip-${view.tone}`, 'data-state-key': st.key, 'data-risk-level': view.level,
      title: `${st.rule}. ${view.reason}`, 'aria-expanded': 'false', onclick: () => {
        history.open = !history.open;
        // Opening it from a chip far up the page would otherwise leave the table out of sight.
        if (history.open) history.scrollIntoView({ block: 'start', behavior: 'smooth' });
      } }, [
      el('span', { class: 'ms-chip-heading' }, [
        el('span', { class: 'ms-chip-name', text: st.label }),
        el('span', { class: 'ms-chip-meta' }, [
          el('span', { class: 'ms-chip-status', text: view.label }),
          el('span', { class: 'dim', text: `${st.days_now} D` }),
        ]),
      ]),
      el('span', { class: 'ms-chip-rule', text: st.rule }),
    ]);
  }));

  const unit = { ret: 'pp', worst_dd: 'pp', hit: '%' };
  const rows = state.states.map((st) => {
    const cells = ['ret', 'worst_dd', 'hit'].map((key) => {
      const c = outcomeCell(key, st.outcomes?.[key], unit[key]);
      const outcome = st.outcomes?.[key];
      return el('td', { class: c.tone === 'dim' ? 'dim' : c.tone, title: c.title }, [
        el('span', { text: c.text }),
        el('span', { class: 'sub', text: `State ${num(outcome?.inside, 1)}% · other ${num(outcome?.outside, 1)}%` }),
      ]);
    });
    const now = daysNow(st);
    const view = statePresentation(st);
    return el('tr', { class: st.active_now ? `ms-active ms-row-${view.tone}` : '' }, [
      el('td', {}, [el('span', { class: 'ms-name', text: st.label }), el('span', { class: 'sub', text: st.rule }), el('span', { class: 'sub', text: `${view.label}: ${view.reason}` })]),
      el('td', {}, now ? [tag(now, view.tone)] : [el('span', { class: 'dim', text: DASH })]),
      el('td', { class: st.status === 'ok' ? '' : 'dim', title: `${st.days} scored days in ${st.episodes} separate episodes, ${st.first || DASH} to ${st.last || DASH}`, text: `${st.days} / ${st.episodes}` }),
      ...cells,
    ]);
  });
  history = el('details', { class: 'sx-fold ms-history' }, [el('summary', { text: `Historical context · next ${horizon} outcomes & uncertainty` }), card(`WHAT THE MARKET DID NEXT · ${horizon} AFTER A DAY IN THE STATE, LESS THE OTHER DAYS · 95% RANGE`, null, [
    el('div', { class: 'field-note ms-legend', text: 'CAUTION: active condition with an adverse historical difference whose 95% interval excludes zero. ACTIVE: holds today, without that evidence or with too little history. Inactive conditions are grey, not an all-clear. Historical associations, not forecasts or entry signals; intervals are not corrected for multiple tests.' }),
    table(['STATE', 'NOW', 'DAYS / EPISODES', `${horizon} RETURN, PP`, 'WORST FALL, PP', `${state.settings.drawdown_floor_pct}%+ FALL CHANCE, PP`], rows),
    el('div', { class: 'note-text', text: 'Outcome columns are differences in percentage points, not absolute returns or probabilities: +10 pp in fall chance means 10 points more often than on other days. Brackets are 95% intervals for that difference. Days overlap; episodes are the much smaller effective history. A stronger subsequent rebound can coexist with a deeper interim fall. Not an out-of-sample strategy test.' }),
    el('div', { class: 'field-note', text: `Scored over ${state.inputs.scored_days} sessions from ${state.settings.history_start} to ${state.inputs.scored_through}. ${state.notes.join(' ')}` }),
  ])]);
  history.addEventListener('toggle', () => board.querySelectorAll('button').forEach((button) => button.setAttribute('aria-expanded', String(history.open))));
  return [
    sectionTitle('MARKET STATE', `BREADTH AND STRESS FROM FUND PRICES · THROUGH ${state.inputs.prices_through}`),
    strip,
    funds,
    el('div', { class: 'field-note ms-sentence', text: sentence }),
    board,
    el('div', { class: 'field-note ms-definitions', text: 'RSP / SPY: equal-weight / cap-weight S&P 500. IWM / SPY: small caps / S&P 500. Ratio change is %, not a return gap in pp. 200D: 200-session moving average. Market high: highest close in the stated window. D beside a state: consecutive trading days active.' }),
    history,
  ];
}

// --- performance ---------------------------------------------------------------
// SPY, QQQ, IWM and RSP rebased, and the bond-vs-equity volatility reading, from
// overview.json, loaded here so a failed read leaves one named gap.

async function mountPerformance(host, ctx) {
  try {
    const overview = await ctx.loadArtifact('overview');
    if (!overview || overview.unavailable) throw new Error('no session figures in this build');
    host.replaceChildren(...[performanceCard(overview.performance, overview.equal_vs_cap), volatilityLine(overview.vol)].filter(Boolean));
  } catch (error) {
    host.replaceChildren(el('div', { class: 'gap', text: `Performance is unavailable: ${error.message}.` }));
  }
}

async function mountMarketState(host, ctx) {
  try {
    const state = await ctx.loadArtifact('market_state');
    if (!state || state.unavailable || !Array.isArray(state.states)) throw new Error('no market-state measurements in this build');
    host.replaceChildren(...marketStateSection(state));
  } catch (error) {
    host.replaceChildren(sectionTitle('MARKET STATE', 'BREADTH AND STRESS'), el('div', { class: 'gap', text: `Market state is unavailable: ${error.message}.` }));
  }
}

export default function renderMarkets(root, data, manifest, ctx = {}) {
  // Indices are read in the order the contract declares them, so adding one is
  // a config change here too -- nothing on this tab names an index.
  const order = data.index_order || Object.keys(data.indices || {});
  const blocks = order.map((key) => data.indices[key]).filter(Boolean);
  const filled = filledNotice(manifest);
  if (filled) root.append(filled);
  const actions = actionsNotice(manifest);
  if (actions) root.append(actions);
  // The night's session is cross-checked against Nasdaq's closes; when too few
  // came back to judge, the page says it was not, rather than implying it was.
  const latest = manifest && manifest.session_check && manifest.session_check.latest;
  if (latest && latest.verified === false) {
    root.append(notice(`${latest.date}: not yet cross-checked against published closes `
      + `(${latest.names} of the largest members answered). Yahoo's closes are shown as served.`));
  }

  // Intraday prices first, the recap's closes beneath: the live strip is
  // labelled as such and nothing below it changes during the session.
  root.append(mountLive({ asOf: data.as_of }));
  root.append(mountIndexCharts());

  // How narrow or stressed the market is; built on its own, so a failure of
  // that panel leaves a named gap here and nothing else on the page.
  if (ctx.loadArtifact) {
    const stateHost = el('div', {});
    root.append(stateHost);
    mountMarketState(stateHost, ctx);
  }

  // One section per index, rendered by the same function so the two read
  // identically and a reader can compare them without re-learning the layout.
  const indexHost = el('div', { class: 'index-history' });
  const labels = blocks.map((b) => b.label);
  const drawIndex = (label) => {
    const block = blocks.find((b) => b.label === label);
    if (!block) return;
    disposeWithin(indexHost);
    indexSection(block.key, block);
  };
  root.append(card('INDEX COMPARISON', null, indexComparison(blocks)));
  root.append(card('INDEX HISTORY · SELECT A UNIVERSE', periodSwitch(labels, labels[0], drawIndex), indexHost));
  if (ctx.loadArtifact) {
    const performanceHost = el('div', { class: 'session-cards' });
    root.append(performanceHost);
    mountPerformance(performanceHost, ctx);
  }

  // Price, members above their averages with the day's up / down, what moved it
  // and the movers: the same layout as EUROPE's (index-history.js).
  function indexSection(key, block) {
    indexHistory(indexHost, { ...block, key, history: block.breadth_history, date: data.as_of });
  }

  drawIndex(labels[0]);

  // --- Watchlist ---------------------------------------------------------
  const watch = data.watchlist;
  if (watch && watch.rows.length) {
    root.append(sectionTitle('WATCHLIST', 'NAMES NO TRACKED INDEX HOLDS'));
    const rows = watch.rows.map((row) => {
      if (row.status !== 'ok') {
        return el('tr', {}, [
          el('td', {}, [el('span', { text: row.ticker }), el('span', { class: 'sub', text: row.label })]),
          el('td', { class: 'dim', text: DASH }),
          el('td', { class: 'dim', text: 'no price data' }),
          ...watch.periods.map(() => el('td', { class: 'dim', text: DASH })),
          el('td', { class: 'dim', text: DASH }),
        ]);
      }
      return el('tr', {}, [
        el('td', { class: 'wrap-cell' }, [
          el('span', { text: row.ticker }),
          el('span', { class: 'sub', text: row.label }),
        ]),
        el('td', { class: 'wrap-cell dim', text: row.sub_sector || DASH }),
        el('td', { text: num(row.price) }),
        ...watch.periods.map((p) => el('td', { class: dirClass(row[p]), text: pct(row[p]) })),
        el('td', { class: 'dim', text: row.sessions }),
      ]);
    });
    const notes = watch.rows.filter((r) => r.note).map((r) => `${r.ticker}: ${r.note}`);
    root.append(card('WATCHLIST — PRICE & RETURN', null, [
      table(['TICKER', 'SUB-SECTOR', 'PRICE', ...watch.periods, 'SESSIONS'], rows),
      el('div', { class: 'note-text', text: watch.note }),
      ...notes.map((n) => el('div', { class: 'note-text', text: n })),
    ]));
  }

  // --- Sector table beside the rebased chart -------------------------------
  const rebasedNode = el('div', { class: 'chart tall' });
  const rebasedPeriods = Object.keys(data.sector_rebased);
  const rebasedDefault = rebasedPeriods.includes('1Y') ? '1Y' : rebasedPeriods[rebasedPeriods.length - 1];
  const drawRebased = (period) => {
    const payload = data.sector_rebased[period];
    if (payload) multiLine(rebasedNode, payload.dates, payload.series);
  };

  root.append(el('div', { class: 'grid two' }, [
    sectorTable(data.sector_table),
    card('SECTORS REBASED TO 100', periodSwitch(rebasedPeriods, rebasedDefault, drawRebased), rebasedNode),
  ]));

  root.append(el('div', { class: 'grid two' }, [
    breadthTable(data.breadth_by_sector),
    slopeTable(data.sma_slope_by_sector),
  ]));

  // Any index whose members are labelled from two taxonomies says so, rather
  // than only the one that happened to need it when this was written.
  blocks.forEach((block) => {
    const mixed = block.classification || {};
    if (!mixed.yahoo_mapped_to_gics) return;
    root.append(el('div', { class: 'note-text' }, [
      `${mixed.wikipedia_gics || 0} ${block.label} members carry GICS labels from the S&P 500 list; `,
      `${mixed.yahoo_mapped_to_gics} sit outside it (foreign issuers and recent listings) and are `,
      'labelled from Yahoo\'s taxonomy mapped onto the same GICS sector names. Sub-industry wording '
      + 'therefore differs between the two groups.',
    ]));
  });

  drawRebased(rebasedDefault);
}
