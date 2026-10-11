import { el, card, table, tag, num, pct, dirClass, periodSwitch, sectionTitle, notice, DASH } from '../fmt.js';
import { areaLine, zeroLine, multiLine } from '../charts.js';
import { mountLive } from '../live.js';
import { mountIndexCharts } from '../live-indices.js';
import { spark } from '../spark.js';
import { readingText, readingNote, outcomeCell, stateSummary, daysNow, sectorFlag } from '../market-state-model.js';

function drawdownStat(entry) {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: `${entry.label} DRAWDOWN` }),
    el('div', { class: `stat-value ${dirClass(entry.drawdown_pct)}`, text: pct(entry.drawdown_pct) }),
    el('div', { class: 'stat-note' }, [
      `${entry.trading_days_since_high ?? DASH} TRADING DAYS (HIGH ${entry.high_date ?? DASH})`,
    ]),
  ]);
}

function adStat(label, ad) {
  if (!ad) return null;
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: `${label} ADV / DEC` }),
    el('div', { class: 'stat-value' }, [
      el('span', { class: 'up', text: ad.advancers }),
      ' / ',
      el('span', { class: 'down', text: ad.decliners }),
      ' / ',
      el('span', { class: 'dim', text: ad.unchanged }),
    ]),
    el('div', { class: 'stat-note', text: `RATIO ${ad.ratio ?? DASH}` }),
  ]);
}

function moverTable(title, rows) {
  const body = rows.map((row) => el('tr', {}, [
    el('td', { class: 'wrap-cell' }, [
      el('span', { text: row.ticker }),
      el('span', { class: 'sub', text: row.name }),
    ]),
    el('td', { class: 'wrap-cell dim', text: row.sector }),
    el('td', { class: 'wrap-cell dim', text: row.sub_sector }),
    el('td', { text: num(row.price) }),
    el('td', { class: dirClass(row.change_pct), text: pct(row.change_pct) }),
  ]));
  return card(title, null, table(['TICKER', 'SECTOR', 'SUB-SECTOR', 'PRICE', '% CHG'], body));
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
    el('div', { class: 'stat-note', text: readingNote(r) || (r.unit === 'pp' ? `OVER ${state.settings.relative_period}` : r.key === 'spy_drawdown' ? `FROM ${state.settings.high_period} HIGH` : '') }),
  ])));

  const funds = el('div', { class: 'ms-funds' }, state.sectors.map((row) => {
    const flag = sectorFlag(row);
    return el('span', { class: `ms-fund ${flag.tone}`, title: `${row.sector}: ${row.above_50 === null ? DASH : row.above_50 ? 'above' : 'below'} its ${state.settings.short_ma}-day line` }, [
      el('b', { text: row.etf }), ` ${flag.text}`,
    ]);
  }));

  const summary = stateSummary(state.states, state.settings.drawdown_floor_pct);
  const total = state.states.length;
  const sentence = summary.holding.length
    ? `${summary.holding.length} of ${total} states hold today. ${summary.detected.length
      ? `After such days a difference is detected for ${summary.detected.map((d) => `${d.label} (${d.parts.join(', ')})`).join('; ')}. `
      : 'None of them has a detected difference in what followed. '}${summary.undetected.length
      ? `No difference is detected for the other ${summary.undetected.length}: ${summary.undetected.map((d) => d.label).join(', ')}.` : ''}`
    : 'No state holds today.';

  const unit = { ret: 'pp', worst_dd: 'pp', hit: '%' };
  const rows = state.states.map((st) => {
    const cells = ['ret', 'worst_dd', 'hit'].map((key) => {
      const c = outcomeCell(key, st.outcomes?.[key], unit[key]);
      return el('td', { class: c.tone === 'dim' ? 'dim' : c.tone, title: c.title, text: c.text });
    });
    const now = daysNow(st);
    return el('tr', { class: st.active_now ? 'ms-active' : '' }, [
      el('td', {}, [el('span', { class: 'ms-name', text: st.label }), el('span', { class: 'sub', text: st.rule })]),
      el('td', {}, now ? [tag(now, 'info')] : [el('span', { class: 'dim', text: DASH })]),
      el('td', { class: st.status === 'ok' ? '' : 'dim', title: `${st.days} scored days in ${st.episodes} separate episodes, ${st.first || DASH} to ${st.last || DASH}`, text: `${st.days} / ${st.episodes}` }),
      ...cells,
    ]);
  });
  return [
    sectionTitle('MARKET STATE', `BREADTH AND STRESS FROM FUND PRICES · THROUGH ${state.inputs.prices_through}`),
    strip,
    funds,
    el('div', { class: 'field-note ms-sentence', text: sentence }),
    card(`WHAT THE MARKET DID NEXT · ${horizon} AFTER A DAY IN THE STATE, LESS THE OTHER DAYS · 95% RANGE`, null, [
      table(['STATE', 'NOW', 'DAYS / EPISODES', `${horizon} RETURN, PP`, 'WORST FALL, PP', `${state.settings.drawdown_floor_pct}%+ FALL CHANCE, PP`], rows),
      el('div', { class: 'field-note', text: `Scored over ${state.inputs.scored_days} sessions from ${state.settings.history_start} to ${state.inputs.scored_through}. ${state.notes.join(' ')}` }),
    ]),
  ];
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
  root.append(mountLive());
  root.append(mountIndexCharts());

  root.append(el('div', { class: 'stat-strip' }, [
    // The ETFs' closes are not repeated here: the live strip above carries
    // the cash indices they track.
    ...blocks.map((block) => drawdownStat({ label: block.key, ...block.drawdown })),
    ...blocks.map((block) => adStat(block.key, block.advance_decline)),
  ]));

  // How narrow or stressed the market is; built on its own, so a failure of
  // that panel leaves a named gap here and nothing else on the page.
  if (ctx.loadArtifact) {
    const stateHost = el('div', {});
    root.append(stateHost);
    mountMarketState(stateHost, ctx);
  }

  // One section per index, rendered by the same function so the two read
  // identically and a reader can compare them without re-learning the layout.
  const drawCallbacks = [];

  function indexSection(key, block) {
    root.append(sectionTitle(block.label, `(${key}) · ${block.members} MEMBERS`));

    const priceNode = el('div', { class: 'chart' });
    const pricePeriods = Object.keys(block.price_chart);
    const priceDefault = pricePeriods.includes('1Y') ? '1Y' : pricePeriods[pricePeriods.length - 1];
    const drawPrice = (period) => {
      const series = block.price_chart[period];
      if (series) areaLine(priceNode, series.dates, series.values);
    };

    const breadthNode = el('div', { class: 'chart' });
    const breadthPeriods = Object.keys(block.breadth_chart);
    const breadthDefault = breadthPeriods.includes('6M') ? '6M' : breadthPeriods[0];
    const drawBreadth = (period) => {
      const series = block.breadth_chart[period];
      if (series) zeroLine(breadthNode, series.dates, series.values);
    };

    root.append(el('div', { class: 'grid two' }, [
      card(`${key} — PRICE`, periodSwitch(pricePeriods, priceDefault, drawPrice), priceNode),
      card(`${key} — NET BREADTH %`, periodSwitch(breadthPeriods, breadthDefault, drawBreadth), breadthNode),
    ]));

    root.append(el('div', { class: 'grid two' }, [
      moverTable(`TOP ${block.gainers.length} GAINERS — ${key}`, block.gainers),
      moverTable(`TOP ${block.losers.length} LOSERS — ${key}`, block.losers),
    ]));

    drawCallbacks.push(() => { drawPrice(priceDefault); drawBreadth(breadthDefault); });
  }

  blocks.forEach((block) => indexSection(block.key, block));

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

  drawCallbacks.forEach((fn) => fn());
  drawRebased(rebasedDefault);
}
