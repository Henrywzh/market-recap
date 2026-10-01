// TRADE DESK: entries, exits and size for US stocks and index ETFs held
// overnight to weeks. No account connection or execution. Buyback blackout
// and insider buying live on RISK -> POSITIONING with the other positioning
// reads; this page keeps what a single trade needs.

import { card, DASH, dirClass, el, metaRow, num, pct, periodSwitch, table, tag } from '../fmt.js';
import { render } from '../charts.js';
import { rangeSwitch, sliceRange, initialRange } from '../range.js';
import { tickerHref } from '../routes.js';
import { ageSeconds, ageText } from '../live-model.js';
import { anchorScorecard, closeLevels, optionRange, priceLadder, sentimentScorecard, sizePosition, trendScorecard } from '../trade-math.js';
import { resolveTicker } from '../routes.js';

const valid = (v) => typeof v === 'number' && Number.isFinite(v);
const usd = (v, digits = 2) => (valid(v) ? `$${num(v, digits)}` : DASH);
const field = (label, input) => el('div', { class: 'field' }, [el('label', { text: label }), input]);
const info = (message) => el('div', { class: 'note-text', text: message });
const signed = (v, digits = 2) => (valid(v) ? pct(v, digits) : DASH);

function compactUsd(v) {
  if (!valid(v)) return DASH;
  const a = Math.abs(v);
  if (a >= 1e9) return `$${num(v / 1e9, 1)}bn`;
  if (a >= 1e6) return `$${num(v / 1e6, a >= 1e7 ? 0 : 1)}m`;
  return `$${num(v, 0)}`;
}

function stat(label, value, note = null, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}` }, [].concat(value)),
    note ? el('div', { class: 'stat-note' }, [].concat(note)) : null,
  ]);
}

const KIND_TONE = { range: 'info', average: 'warn', atr: 'dim', implied: 'up' };
const KIND_LABEL = { range: 'RANGE', average: 'AVG', atr: 'ATR', implied: 'OPTIONS' };

// ------------------------------------------------------------ setups & size

function levelChart(node, payload, levels, range, span) {
  const o = payload.ohlcv?.dates?.length ? payload.ohlcv : { dates: payload.dates, close: payload.close };
  const cut = sliceRange(o.dates, { close: o.close }, span);
  // Averages on the traded closes, over the whole companion so the first
  // point shown is already a full window.
  const avg = (n) => o.close.map((_, i) => (i + 1 >= n && o.close.slice(i + 1 - n, i + 1).every(valid)
    ? o.close.slice(i + 1 - n, i + 1).reduce((a, b) => a + b, 0) / n : null)).slice(o.dates.length - cut.dates.length);
  render(node, (option, p) => {
    const lines = [
      ['20D HIGH', levels.twenty?.high, p.blue], ['20D LOW', levels.twenty?.low, p.blue],
      ['52W HIGH', levels.year?.high, p.faint], ['52W LOW', levels.year?.low, p.faint],
    ].filter(([, y]) => valid(y));
    return {
      ...option,
      grid: { ...option.grid, left: 58, right: 70, bottom: 44 },
      legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
      tooltip: { ...option.tooltip, valueFormatter: (v) => (valid(v) ? num(v, 2) : DASH) },
      xAxis: { ...option.xAxis, data: cut.dates },
      yAxis: { ...option.yAxis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => num(v, 0) } },
      series: [
        {
          name: payload.ticker, type: 'line', data: cut.close, showSymbol: false, lineStyle: { width: 1.5, color: p.text },
          markLine: {
            silent: true, symbol: 'none',
            data: lines.map(([label, y, color]) => ({ yAxis: y, lineStyle: { color, type: 'dashed', width: 1 },
              label: { formatter: `${label} ${num(y, 2)}`, color, fontSize: 9, position: 'end' } })),
          },
          markArea: range ? {
            silent: true,
            data: [[{ yAxis: range.lower, itemStyle: { color: p.up, opacity: 0.08 } }, { yAxis: range.upper }]],
          } : undefined,
        },
        { name: '20D avg', type: 'line', data: avg(20), showSymbol: false, lineStyle: { width: 1, color: p.accent } },
        { name: '50D avg', type: 'line', data: avg(50), showSymbol: false, lineStyle: { width: 1, color: p.purple } },
        { name: '200D avg', type: 'line', data: avg(200), showSymbol: false, lineStyle: { width: 1, color: p.down, type: 'dashed' } },
      ],
    };
  });
}

function ladderTable(ladder, close) {
  const above = ladder.filter((r) => r.price > close);
  const below = ladder.filter((r) => r.price <= close);
  const line = (r) => el('tr', {}, [
    el('td', {}, [tag(KIND_LABEL[r.kind], KIND_TONE[r.kind])]),
    el('td', { text: r.label }),
    el('td', { text: num(r.price, 2) }),
    el('td', { class: Math.abs(r.distance_pct) < 1 ? 'down' : 'dim', text: signed(r.distance_pct, 1) }),
  ]);
  return el('div', { class: 'table-scroll' }, [el('table', { class: 'data trade-ladder' }, [
    el('thead', {}, [el('tr', {}, ['', 'LEVEL', 'PRICE', 'DISTANCE'].map((h) => el('th', { text: h })))]),
    el('tbody', {}, [
      ...above.map(line),
      el('tr', { class: 'trade-ladder-now' }, [el('td', {}), el('td', { text: 'LAST CLOSE' }), el('td', { text: num(close, 2) }), el('td', { text: '' })]),
      ...below.map(line),
    ]),
  ])]);
}

function setups(root, technicals, ctx, state) {
  const available = technicals?.available || [];
  const ticker = el('input', { value: ctx.arg || (available.includes('SPY') ? 'SPY' : available[0] || ''),
    list: 'trade-tickers', placeholder: 'ticker', size: '10' });
  const list = el('datalist', { id: 'trade-tickers' }, available.map((t) => el('option', { value: t })));
  const host = el('div', {});
  const evidence = ctx.loadArtifact('evidence').catch(() => null);

  const load = async () => {
    const symbol = resolveTicker(ticker.value.trim().toUpperCase(), (t) => available.includes(t));
    if (!available.includes(symbol)) {
      host.replaceChildren(info(`${symbol || 'Ticker'} has no baked price history in this build.`));
      return;
    }
    ctx.setArg(symbol);
    try {
      const response = await fetch(`artifacts/tickers/${encodeURIComponent(symbol)}.json`, { cache: 'no-cache' });
      if (!response.ok) throw new Error(`price history HTTP ${response.status}`);
      const payload = await response.json();
      const levels = closeLevels(payload.close, payload.ohlcv, payload.dates);
      if (!levels) throw new Error('no closes in the artifact');
      const range = optionRange((await evidence)?.names?.[symbol]?.options, levels.close, payload.as_of);
      state.reference = { price: levels.close, atr14: levels.atr14, adv20: levels.adv20, symbol };
      state.onReference?.();

      const vs = (n) => (valid(levels.moving[n]) ? 100 * (levels.close / levels.moving[n] - 1) : null);
      const trendTag = (n) => (valid(vs(n)) ? tag(`${vs(n) >= 0 ? 'ABOVE' : 'BELOW'} ${n}D`, vs(n) >= 0 ? 'up' : 'down') : DASH);
      const day = valid(levels.previous) ? 100 * (levels.close / levels.previous - 1) : null;
      const gap = levels.gap;
      const strip = el('div', { class: 'stat-strip' }, [
        stat(`${symbol} · ${payload.as_of}`, usd(levels.close), signed(day), dirClass(day)),
        stat('TREND', el('span', { class: 'tag-row' }, [trendTag(50), trendTag(200)]), `${signed(vs(50), 1)} / ${signed(vs(200), 1)} from the averages`),
        stat('ATR 14', usd(levels.atr14), valid(levels.atr14) ? `${num(100 * levels.atr14 / levels.close, 1)}% of price` : 'no OHLC in this build'),
        stat('20D AVG $ VOLUME', compactUsd(levels.adv20), 'traded close × volume'),
        stat('LATEST GAP', gap ? [tag(`${gap.pct >= 0 ? 'UP' : 'DOWN'} ${num(Math.abs(gap.pct), 1)}%`, gap.pct >= 0 ? 'up' : 'down')] : DASH,
          gap ? `${gap.day} · ${gap.filled_intraday ? 'filled intraday' : 'not filled'}` : null),
        stat('OPTIONS-IMPLIED', range ? `±${num(range.move_pct, 1)}%` : DASH,
          range ? `${usd(range.lower)} – ${usd(range.upper)} · ${range.expiry}` : 'no same-day option snapshot'),
      ]);

      const chartNode = el('div', { class: 'chart tall' });
      const dates = payload.ohlcv?.dates?.length ? payload.ohlcv.dates : payload.dates;
      let span = initialRange(dates, '6M');
      const draw = () => levelChart(chartNode, payload, levels, range, span);
      requestAnimationFrame(draw);
      host.replaceChildren(
        strip,
        el('div', { class: 'grid trade-top' }, [
          card(`${symbol} · PRICE, AVERAGES AND LEVELS`, rangeSwitch(dates, span, (label) => { span = label; draw(); }), [
            chartNode,
            info(`Traded (split-adjusted) closes${levels.basis === 'traded' ? '' : ' unavailable: levels fall back to the dividend-adjusted series'}. Dashed: prior 20-session and 52-week closing extremes. ${range ? 'Green band: close ± the nearest expiry\'s ATM straddle.' : ''}`),
          ]),
          card('PRICE LADDER', el('a', { href: tickerHref(symbol), text: 'OPEN TICKER →' }), [
            ladderTable(priceLadder(levels, range), levels.close),
            info('Closing levels, not intraday highs and lows. ±2 ATR is a stop distance, not a forecast. Red distance: within 1%.'),
          ]),
        ]),
      );
    } catch (error) {
      host.replaceChildren(info(`Unable to load ${symbol}: ${error.message}`));
    }
  };
  ticker.addEventListener('keydown', (event) => { if (event.key === 'Enter') load(); });
  root.append(el('div', { class: 'field-row trade-pick' }, [field('STOCK OR ETF', ticker),
    el('button', { class: 'action', text: 'LOAD', onclick: load }), list]), host);
  load();
}

function sizing(root, state) {
  const side = el('select', {}, [el('option', { value: 'long', text: 'LONG' }), el('option', { value: 'short', text: 'SHORT' })]);
  const inputs = [
    ['ACCOUNT ($)', 'account', ''], ['RISK PER TRADE (%)', 'riskPct', '1'], ['ENTRY ($)', 'entry', ''],
    ['STOP ($)', 'stop', ''], ['MAX POSITION (% OF ACCOUNT)', 'maxPct', '20'],
    ['MAX % OF 20D $ VOLUME', 'participationPct', '1'], ['SPREAD ASSUMPTION (BPS)', 'spreadBps', ''],
  ].map(([label, key, value]) => [key, field(label, el('input', { type: 'number', min: '0', step: 'any', value }))]);
  const byKey = Object.fromEntries(inputs.map(([key, node]) => [key, node.querySelector('input')]));
  const out = el('div', {});
  const calculate = () => {
    const r = sizePosition({ ...Object.fromEntries(Object.entries(byKey).map(([key, node]) => [key, node.value])),
      side: side.value, advUsd: state.reference?.adv20 });
    if (!r) {
      out.replaceChildren(info(`Enter the account, risk %, entry and a stop ${side.value === 'long' ? 'below' : 'above'} the entry. Nothing is saved or sent.`));
      return;
    }
    const capped = { risk: ['STOP RISK', 'up'], notional: ['POSITION LIMIT', 'warn'], liquidity: ['VOLUME LIMIT', 'down'] }[r.cappedBy];
    out.replaceChildren(el('div', { class: 'stat-strip' }, [
      stat('SHARES', num(r.shares, 0), `${side.value.toUpperCase()} · whole shares`),
      stat('POSITION', usd(r.notional, 0), valid(Number(byKey.account.value)) && Number(byKey.account.value) > 0
        ? `${num(100 * r.notional / Number(byKey.account.value), 1)}% of account` : null),
      stat('LOSS AT STOP', usd(r.plannedLoss, 0), `budget ${usd(r.riskBudget, 0)} · ${usd(r.perShareRisk)} a share`, 'down'),
      stat('SIZED BY', [tag(capped[0], capped[1])], valid(r.spreadCost) ? `spread cost ${usd(r.spreadCost)} one way` : null),
    ]));
  };
  Object.values(byKey).forEach((node) => node.addEventListener('input', calculate));
  side.addEventListener('change', calculate);
  state.onReference = () => {
    if (!byKey.entry.value && state.reference) byKey.entry.value = String(state.reference.price);
    calculate();
  };
  const useClose = el('button', { class: 'action', text: 'ENTRY = LAST CLOSE', onclick: () => {
    if (!state.reference) return;
    byKey.entry.value = String(state.reference.price);
    calculate();
  } });
  const useAtr = el('button', { class: 'action', text: 'STOP = 2× ATR', onclick: () => {
    if (!state.reference || !valid(state.reference.atr14)) return;
    const entry = Number(byKey.entry.value) || state.reference.price;
    byKey.entry.value = String(entry);
    byKey.stop.value = String(Number((entry + (side.value === 'long' ? -2 : 2) * state.reference.atr14).toFixed(2)));
    calculate();
  } });
  calculate();
  root.append(card('POSITION SIZE', el('span', { class: 'dim', text: 'computed in the browser · nothing saved' }), [
    el('div', { class: 'field-row' }, [field('SIDE', side), ...inputs.map(([, node]) => node)]),
    el('div', { class: 'field-row' }, [useClose, useAtr]),
    out,
    info('Shares = the smallest of: risk budget ÷ distance to stop, the position limit, and the share of 20-day dollar volume. The free feed has no live stock bid–ask, so spread is your assumption. A gap through the stop, slippage, fees and borrow can make the loss larger; a short\'s loss is unbounded.'),
  ]));
}

// ------------------------------------------------------------ overnight

function readings(quotes, kinds) {
  return quotes.filter((q) => kinds.includes(q.kind)).map((q) => {
    const now = Date.now() / 1000;
    const isPre = q.kind === 'premarket' && valid(q.pre_price) && valid(q.pre_time)
      && q.pre_time > (q.time || 0) && q.pre_time >= (q.post_time || 0) && now - q.pre_time < 12 * 3600;
    const isPost = q.kind === 'premarket' && !isPre && valid(q.post_price) && valid(q.post_time)
      && q.post_time > (q.time || 0) && now - q.post_time < 12 * 3600;
    const price = isPre ? q.pre_price : isPost ? q.post_price : q.price;
    const stamp = isPre ? q.pre_time : isPost ? q.post_time : q.time;
    // In extended hours Yahoo's chartPreviousClose is two sessions back; the
    // regular-market price is the session that just closed.
    const reference = (isPre || isPost) ? q.price : q.previous_close;
    const change = valid(price) && valid(reference) && reference > 0 ? 100 * (price / reference - 1) : null;
    return { q, price, stamp, change, session: isPre ? 'PRE' : isPost ? 'POST' : null };
  });
}

function overnight(root) {
  const section = el('div', {});
  const status = el('span', { class: 'dim', text: 'Loading…' });
  const tiles = el('div', {});
  const movers = el('div', {});
  let timer = null;
  let inflight = false;

  const load = async () => {
    if (inflight) return;
    inflight = true;
    try {
      const response = await fetch('api/quotes?scope=trade', { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json();
      const quotes = body.quotes || [];
      const board = readings(quotes, ['overnight']);
      tiles.replaceChildren(board.length ? el('div', { class: 'stat-strip trade-board' }, board.map((r) => stat(
        `${r.q.label.toUpperCase()} · ${r.q.region}`, r.q.error ? DASH : num(r.price, 2),
        [el('span', { class: dirClass(r.change), text: signed(r.change) }), ` · ${r.q.error || ageText(ageSeconds(r.stamp, Date.now()))}`],
      ))) : info('No quote answered for the overnight board.'));
      const extended = readings(quotes, ['premarket']).filter((r) => r.session)
        .sort((a, b) => Math.abs(b.change || 0) - Math.abs(a.change || 0));
      movers.replaceChildren(extended.length ? table(['NAME', 'SESSION', 'PRICE', 'VS LAST CLOSE', 'AGE'], extended.map((r) => el('tr', {}, [
        el('td', {}, [el('a', { href: tickerHref(r.q.symbol), text: r.q.label })]),
        el('td', {}, [tag(r.session, 'info')]),
        el('td', { text: num(r.price, 2) }),
        el('td', { class: dirClass(r.change), text: signed(r.change) }),
        el('td', { class: 'dim', text: ageText(ageSeconds(r.stamp, Date.now())) }),
      ]))) : info('No pre- or post-market prints right now. Regular-session moves are not shown as pre-market movers.'));
      status.textContent = `Fetched ${new Date(body.fetched_at || Date.now()).toLocaleTimeString()} · Yahoo chart, unofficial, can lag · ${quotes.filter((q) => q.kind === 'premarket').length} names scanned`;
    } catch (error) {
      status.textContent = `Live source unavailable: ${error.message}`;
    } finally {
      inflight = false;
    }
  };
  // Poll only while this section is on screen and the tab is visible, as the
  // live strip does; a hidden tab resumes on its next visit.
  const tick = async () => {
    clearTimeout(timer);
    if (!section.isConnected) { document.removeEventListener('visibilitychange', onVisible); return; }
    if (document.hidden) return;
    await load();
    if (section.isConnected) timer = setTimeout(tick, 60000);
  };
  const onVisible = () => { if (!document.hidden) tick(); };
  document.addEventListener('visibilitychange', onVisible);

  section.append(
    card('ES / NQ · ASIA · EUROPE', el('button', { class: 'action', text: 'REFRESH', onclick: tick }), [tiles, el('div', { class: 'stat-note' }, [status])]),
    card('US PRE / POST-MARKET MOVERS', el('span', { class: 'dim', text: 'top 30 S&P 500 weights + watchlist' }), [movers,
      info('Not a whole-market scan. Only prints inside the extended session count, ranked by size of move against the last regular close.')]),
  );
  root.append(section);
  tick();
}

// ------------------------------------------------------------ scorecard

// A state's edge over the base rate, coloured by whether it helps the call:
// for a bearish state a lower forward return is the signal working.
function edgeClass(r) {
  if (!valid(r.difference_pct)) return 'dim';
  return r.difference_pct * r.direction > 0 ? 'up' : 'down';
}

function scoreBlock(title, rows, note) {
  if (!rows.length) return card(title, null, info(note));
  const chartNode = el('div', { class: 'chart short' });
  const labels = [...new Set(rows.map((r) => r.label))];
  const horizons = [...new Set(rows.map((r) => r.horizon))];
  requestAnimationFrame(() => render(chartNode, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 48, bottom: 44 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: (v) => (valid(v) ? pct(v, 2) : DASH) },
    xAxis: { ...option.xAxis, boundaryGap: true, data: horizons.map((h) => `${h} sessions`) },
    yAxis: { ...option.yAxis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${v}%` } },
    series: [
      ...labels.map((label, i) => ({
        name: `after ${label}`, type: 'bar', barMaxWidth: 16,
        itemStyle: { color: i === 0 ? p.up : p.down, opacity: 0.8 },
        data: horizons.map((h) => rows.find((r) => r.label === label && r.horizon === h)?.mean_pct ?? null),
      })),
      { name: 'any day (base)', type: 'bar', barMaxWidth: 16, itemStyle: { color: p.faint },
        data: horizons.map((h) => rows.find((r) => r.horizon === h)?.baseline_pct ?? null) },
    ],
  })));
  const body = rows.map((r) => el('tr', {}, [
    el('td', {}, [tag(r.label, r.direction > 0 ? 'up' : 'down')]),
    el('td', { text: `${r.horizon}` }),
    el('td', { class: r.count < 10 ? 'down' : '', text: `${num(r.count, 0)}${r.count < 10 ? ' · thin' : ''}` }),
    el('td', { text: valid(r.hit_rate) ? `${num(r.hit_rate, 0)}% vs ${num(r.baseline_hit_rate, 0)}%` : DASH }),
    el('td', { text: valid(r.mean_pct) ? `${signed(r.mean_pct)} vs ${signed(r.baseline_pct)}` : DASH }),
    el('td', { class: edgeClass(r), text: signed(r.difference_pct) }),
  ]));
  return card(title, null, [
    el('div', { class: 'grid two trade-score' }, [
      chartNode,
      el('div', { class: 'table-scroll' }, [el('table', { class: 'data' }, [
        el('thead', {}, [el('tr', {}, ['STATE', 'SESSIONS', 'N', 'HIT RATE', 'MEAN RETURN', 'EDGE'].map((h) => el('th', { text: h })))]),
        el('tbody', {}, body),
      ])]),
    ]),
    info(note),
  ]);
}

const withDirection = (rows, bullish) => rows.map((r) => ({ ...r, direction: bullish.includes(r.label) ? 1 : -1 }));

async function scorecard(root, ctx) {
  const [anchor, positioning, risk] = await Promise.all(['anchor', 'positioning', 'risk']
    .map((name) => ctx.loadArtifact(name).catch(() => null)));
  const path = anchor?.full?.dates?.length ? anchor.full : anchor?.history;
  const common = 'Signal read at the close; entry at the next close; same-state windows do not overlap. Hit = the index moved the way the state points. EDGE = mean after the state minus the mean of any day (green = in the state\'s favour). Descriptive, in-sample, current-vintage prices, no costs: not strategy P&L.';
  root.append(scoreBlock('FROZEN V1 ANCHOR → SPY', path ? withDirection(anchorScorecard(path), ['RISK-ON']) : [],
    path ? `RISK-ON = exposure ≥ 75%, RISK-OFF ≤ 25%. ${path.dates[0]} to ${path.dates.at(-1)}. ${common}` : 'Anchor artifact unavailable.'));
  const sentiment = risk?.sentiment?.history;
  if (sentiment?.dates?.length && path?.dates?.length) {
    root.append(scoreBlock('FEAR & GREED EXTREMES → SPY', withDirection(sentimentScorecard(sentiment, path), ['EXTREME FEAR']),
      `Extreme fear ≤ 25 read as bullish, extreme greed ≥ 75 as bearish. ${sentiment.dates[0]} to ${sentiment.dates.at(-1)} only, so samples are small. ${common}`));
  }
  for (const trend of positioning?.trend || []) {
    root.append(scoreBlock(`${trend.label.toUpperCase()} TREND PROXY → INDEX`, withDirection(trendScorecard(trend), ['LONG']),
      `LONG / SHORT = at least three of the four lookback votes agree (RISK → POSITIONING). ${trend.scorecard_history?.dates?.[0] || DASH} to ${trend.as_of}. ${common}`));
  }
  root.append(info('Buyback blackout, insider clusters and the implied range have no archived daily history yet, so they are not scored.'));
}

// ------------------------------------------------------------ page

export default function renderTrade(root, technicals, _manifest, ctx) {
  root.append(metaRow('TRADE DESK · US STOCKS & INDEX ETFs · OVERNIGHT TO WEEKS', [
    'Research and sizing arithmetic only: no account connection, alerts, journal or orders.',
    'Levels come from the nightly build\'s daily bars; the overnight board is live and separate. A blank is missing coverage, never zero.',
    'Buyback blackout and insider buying are on RISK → POSITIONING with short interest and the trend-follower levels.',
  ]));
  const tabs = ['SETUPS & SIZE', 'OVERNIGHT', 'SCORECARD'];
  const host = el('div', {});
  const state = { reference: null, onReference: null };
  const show = (selected) => {
    host.replaceChildren();
    if (selected === tabs[0]) {
      setups(host, technicals, ctx, state);
      sizing(host, state);
    } else if (selected === tabs[1]) overnight(host);
    else scorecard(host, ctx);
  };
  root.append(el('div', { class: 'trade-nav' }, [periodSwitch(tabs, tabs[0], show),
    el('a', { href: '#positioning', class: 'dim', text: 'buyback blackout · insider buying → POSITIONING' })]), host);
  show(tabs[0]);
}
