import { el, card, table, num, pct, dirClass, periodSwitch, sectionTitle, DASH } from '../fmt.js';
import { areaLine, zeroLine, multiLine } from '../charts.js';

function quoteStat(quote) {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: quote.ticker }),
    el('div', { class: 'stat-value', text: `$${num(quote.price)}` }),
    el('div', { class: `stat-note ${dirClass(quote.change_pct)}` }, [
      `${quote.change >= 0 ? '+' : ''}${num(quote.change)} (${pct(quote.change_pct)})`,
    ]),
  ]);
}

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

export default function renderMarkets(root, data) {
  // Indices are read in the order the contract declares them, so adding one is
  // a config change here too -- nothing on this tab names an index.
  const order = data.index_order || Object.keys(data.indices || {});
  const blocks = order.map((key) => data.indices[key]).filter(Boolean);

  root.append(el('div', { class: 'stat-strip' }, [
    ...data.quotes.map(quoteStat),
    ...blocks.map((block) => drawdownStat({ label: block.key, ...block.drawdown })),
    ...blocks.map((block) => adStat(block.key, block.advance_decline)),
  ]));

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
