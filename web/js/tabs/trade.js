// Trading research for US stocks and index ETFs, overnight to several weeks.
// No account connection or trade execution: the first workflow group is out
// of scope. All inputs here are public artifacts or the existing live proxy.

import { card, DASH, dirClass, el, metaRow, num, pct, periodSwitch, sectionTitle, table, tag } from '../fmt.js';
import { tickerHref } from '../routes.js';
import { ageSeconds, ageText } from '../live-model.js';
import { anchorScorecard, closeLevels, earningsProximity, optionRange, sentimentScorecard, sizePosition, trendScorecard } from '../trade-math.js';

const valid = (v) => typeof v === 'number' && Number.isFinite(v);
const money = (v) => valid(v) ? `$${num(v, 2)}` : DASH;
const field = (label, input) => el('div', { class: 'field' }, [el('label', { text: label }), input]);
const cell = (value, cls = '') => el('td', { class: cls, text: value });
const row = (...values) => el('tr', {}, values.map((v) => v?.nodeType ? v : cell(v)));
const info = (message) => el('div', { class: 'note-text', text: message });

function setups(root, technicals, evidence, ctx) {
  root.append(sectionTitle('PRICE LEVELS & IMPLIED RANGE', 'DAILY PRICE BARS · SNAPSHOT-DATED'));
  const available = technicals?.available || [];
  const ticker = el('input', { value: ctx.arg || (available.includes('SPY') ? 'SPY' : available[0] || ''),
    list: 'trade-tickers', placeholder: 'ticker', size: '12' });
  const list = el('datalist', { id: 'trade-tickers' }, available.map((t) => el('option', { value: t })));
  const host = el('div', {});
  let reference = null;
  const load = async () => {
    const symbol = ticker.value.trim().toUpperCase();
    if (!available.includes(symbol)) {
      host.replaceChildren(info(`${symbol || 'Ticker'} has no baked close history in this build.`));
      return;
    }
    ctx.setArg(symbol);
    try {
      const response = await fetch(`artifacts/tickers/${encodeURIComponent(symbol)}.json`, { cache: 'no-cache' });
      if (!response.ok) throw new Error(`price history HTTP ${response.status}`);
      const payload = await response.json();
      const levels = closeLevels(payload.close, payload.ohlcv, payload.dates);
      reference = { price: levels.close, atr14: levels.atr14, adv20: levels.adv20, symbol };
      const options = evidence?.names?.[symbol]?.options;
      const range = optionRange(options, levels?.close, payload.as_of);
      const levelRows = [
        ['LAST CLOSE', money(levels.close), payload.as_of],
        ['PRIOR CLOSE', money(levels.previous), levels.previous ? pct(100 * (levels.close / levels.previous - 1)) : DASH],
        ['PRIOR 20-SESSION CLOSE LOW / HIGH', levels.twenty ? `${money(levels.twenty.low)} / ${money(levels.twenty.high)}` : DASH,
          levels.twenty ? 'Excludes latest close; not intraday support/resistance' : 'Needs 21 sessions'],
        ['PRIOR 60-SESSION CLOSE LOW / HIGH', levels.sixty ? `${money(levels.sixty.low)} / ${money(levels.sixty.high)}` : DASH,
          levels.sixty ? 'Excludes latest close; not intraday support/resistance' : 'Needs 61 sessions'],
        ['PRIOR 252-SESSION CLOSE LOW / HIGH', levels.year ? `${money(levels.year.low)} / ${money(levels.year.high)}` : DASH,
          levels.year ? 'Excludes latest close; not intraday extremes' : 'Needs 253 sessions'],
        ...[20, 50, 200].map((n) => [`${n}-SESSION SMA / DISTANCE`, valid(levels.moving[n]) ? money(levels.moving[n]) : DASH,
          valid(levels.moving[n]) ? pct(100 * (levels.close / levels.moving[n] - 1), 2) : `Needs ${n} sessions`]),
        ['LATEST OPENING GAP', levels.gap ? pct(levels.gap.pct, 2) : DASH,
          levels.gap ? `${levels.gap.day} · ${levels.gap.filled_intraday ? 'crossed prior close intraday' : 'did not cross prior close intraday'}`
            : 'OHLC companion unavailable'],
        ['14-SESSION ATR', valid(levels.atr14) ? money(levels.atr14) : DASH,
          'Wilder average true range from split-adjusted Yahoo OHLC, not a forecast'],
        ['20-SESSION AVG $ VOLUME', valid(levels.adv20) ? money(levels.adv20) : DASH,
          'Average split-adjusted close × reported daily volume; liquidity proxy'],
      ];
      host.replaceChildren(card(`${symbol} · CLOSE LEVELS`, el('a', { href: tickerHref(symbol), text: 'OPEN TICKER' }), [
        table(['READING', 'LEVEL', 'SOURCE / QUALIFIER'], levelRows.map((r) => row(...r))),
      ]), card('THIS EXPIRY · OPTIONS-IMPLIED RANGE', null, [
        range ? el('div', { class: 'stat-strip' }, [
          el('div', { class: 'stat' }, [el('div', { class: 'stat-label', text: 'LOWER / UPPER' }),
            el('div', { class: 'stat-value', text: `${money(range.lower)} – ${money(range.upper)}` })]),
          el('div', { class: 'stat' }, [el('div', { class: 'stat-label', text: 'ATM STRADDLE' }),
            el('div', { class: 'stat-value', text: `±${num(range.move_pct, 2)}%` })]),
        ]) : info('No same-session usable options snapshot for this ticker. Range is unavailable, not zero.'),
        info(range ? `Snapshot ${range.snapshot_day}; nearest usable expiry ${range.expiry} (${range.days} calendar days). Close ± ATM straddle mid; not a probability band or a price target.`
          : `Options coverage: ${evidence?.options_snapshot || 'no snapshot in this build'}. The trade desk never substitutes historical volatility for option prices.`),
      ]));
    } catch (error) {
      host.replaceChildren(info(`Unable to load ${symbol}: ${error.message}`));
    }
  };
  ticker.addEventListener('keydown', (event) => { if (event.key === 'Enter') load(); });
  root.append(card('SELECT STOCK OR ETF', null, [el('div', { class: 'field-row' }, [field('SYMBOL', ticker),
    el('button', { class: 'action', text: 'LOAD', onclick: load }), list]),
    info('Daily Yahoo price history, current vintage. Intraday support/resistance and live bid–ask are not inferred from daily bars.')]), host);
  load();

  root.append(sectionTitle('POSITION SIZING', 'LOCAL CALCULATION · NO ACCOUNT DATA SAVED'));
  const side = el('select', {}, [el('option', { value: 'long', text: 'LONG' }), el('option', { value: 'short', text: 'SHORT' })]);
  const inputs = [
    ['ACCOUNT EQUITY ($)', 'account'], ['MAX RISK (%)', 'riskPct'], ['ENTRY ($)', 'entry'],
    ['STOP ($)', 'stop'], ['MAX NOTIONAL (% OF EQUITY)', 'maxPct'],
    ['MAX % OF 20D AVG $ VOLUME', 'participationPct'], ['MANUAL SPREAD (BPS)', 'spreadBps'],
  ].map(([label, key]) => [key, field(label, el('input', { type: 'number', min: '0', step: 'any',
    value: key === 'riskPct' || key === 'participationPct' ? '1' : key === 'maxPct' ? '20' : '' }))]);
  const byKey = Object.fromEntries(inputs.map(([key, node]) => [key, node.querySelector('input')]));
  const sizing = el('div', { class: 'note-text' });
  const calculate = () => {
    const result = sizePosition({ ...Object.fromEntries(Object.entries(byKey).map(([key, node]) => [key, node.value])),
      side: side.value, advUsd: reference?.adv20 });
    sizing.textContent = result
      ? `${num(result.shares, 0)} whole shares · notional ${money(result.notional)} · planned stop loss ${money(result.plannedLoss)} `
        + `of ${money(result.riskBudget)} risk budget · capped by ${{ risk: 'stop risk', notional: 'notional limit', liquidity: 'ADV participation' }[result.cappedBy]}`
        + `${valid(result.spreadCost) ? ` · manually entered one-way spread cost ${money(result.spreadCost)}` : ''}.`
      : `Enter equity, risk %, entry and a stop ${side.value === 'long' ? 'below' : 'above'} entry. No order is sent.`;
  };
  Object.values(byKey).forEach((node) => node.addEventListener('input', calculate));
  side.addEventListener('change', calculate);
  calculate();
  const useClose = el('button', { class: 'action', text: 'USE SELECTED CLOSE', onclick: () => {
    if (!reference) return;
    byKey.entry.value = String(reference.price);
    calculate();
  } });
  const useAtr = el('button', { class: 'action', text: 'SET 2× ATR STOP', onclick: () => {
    if (!reference || !valid(reference.atr14)) return;
    const entry = Number(byKey.entry.value) || reference.price;
    byKey.entry.value = String(entry);
    byKey.stop.value = String(Number((entry + (side.value === 'long' ? -2 : 2) * reference.atr14).toFixed(2)));
    calculate();
  } });
  root.append(card('STOCK / ETF · WHOLE SHARES', null, [
    el('div', { class: 'field-row' }, [field('SIDE', side), ...inputs.map(([, node]) => node)]),
    el('div', { class: 'field-row' }, [useClose, useAtr]), sizing,
    info('ADV cap applies only when this build has 20 valid sessions of volume. The free daily feed has no reliable live stock bid–ask; spread is a manual assumption, not a sourced quote. Gap-through-stop, slippage, commissions, borrow fees and FX can make loss exceed this estimate; short losses are uncapped.'),
  ]));
}

function quoteBlock(quotes, kinds, { extendedOnly = false } = {}) {
  let readings = quotes.filter((q) => kinds.includes(q.kind)).map((q) => {
    const isPre = q.kind === 'premarket' && valid(q.pre_price) && valid(q.pre_time)
      && q.pre_time > (q.time || 0) && q.pre_time >= (q.post_time || 0)
      && Date.now() / 1000 - q.pre_time < 12 * 3600;
    const isPost = q.kind === 'premarket' && !isPre && valid(q.post_price) && valid(q.post_time)
      && q.post_time > (q.time || 0) && Date.now() / 1000 - q.post_time < 12 * 3600;
    const price = isPre ? q.pre_price : isPost ? q.post_price : q.price;
    const stamp = isPre ? q.pre_time : isPost ? q.post_time : q.time;
    // During extended hours Yahoo's chartPreviousClose is *two* sessions ago;
    // regularMarketPrice is the just-completed session's close.
    const reference = (isPre || isPost) ? q.price : q.previous_close;
    const change = valid(price) && valid(reference) && reference > 0
      ? 100 * (price / reference - 1) : null;
    return { q, price, stamp, change, extended: isPre || isPost, label: isPre ? ' PRE' : isPost ? ' POST' : '' };
  });
  if (extendedOnly) readings = readings.filter((r) => r.extended);
  if (!readings.length) return info(extendedOnly
    ? 'No current PRE/POST prints in this scan. Regular-session moves are not labelled as premarket movers.'
    : 'No quote answered for this group.');
  if (kinds.includes('premarket')) readings.sort((a, b) => Number(b.extended) - Number(a.extended)
    || Math.abs(b.change || 0) - Math.abs(a.change || 0));
  return table(['MARKET', 'LAST / EXTENDED', 'VS PRIOR CLOSE', 'QUOTE AGE'], readings.map(({ q, price, stamp, change, label }) => row(
    `${q.label}${q.region ? ` · ${q.region}` : ''}`, q.error ? DASH : valid(price) ? num(price, 2) + label : DASH,
    el('td', { class: dirClass(change), text: valid(change) ? pct(change, 2) : DASH }),
    q.error || ageText(ageSeconds(stamp, Date.now())))));
}

function overnight(root) {
  root.append(sectionTitle('OVERNIGHT & PREMARKET', 'LIVE QUOTES · UNOFFICIAL'));
  const status = el('span', { class: 'dim', text: 'Loading…' });
  const host = el('div', {});
  let inflight = false;
  const load = async () => {
    if (inflight || !root.isConnected) return;
    inflight = true;
    try {
      const response = await fetch('api/quotes?scope=trade', { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json();
      const quotes = body.quotes || [];
      host.replaceChildren(card('ES / NQ & ASIA / EUROPE', null, [quoteBlock(quotes, ['overnight'])]),
        card(`US PRE/POST MOVERS · ${quotes.filter((q) => q.kind === 'premarket').length} SYMBOL SCAN`, null, [
          quoteBlock(quotes, ['premarket'], { extendedOnly: true }),
          info('Scan = top 30 current SPX names by issuer weight plus the configured watchlist, with a fallback list on partial builds; not all US stocks. Only valid extended-hours quotes appear and are ranked by absolute move against the last regular close.'),
        ]));
      status.textContent = `Fetched ${body.fetched_at || DASH} · Yahoo chart · prices can be delayed`;
    } catch (error) {
      status.textContent = `Live source unavailable: ${error.message}`;
      host.replaceChildren(info('No overnight quote is inferred from the nightly close.'));
    } finally {
      inflight = false;
      if (root.isConnected) setTimeout(load, 60000);
    }
  };
  root.append(card('SOURCE STATUS', el('button', { class: 'action', text: 'REFRESH', onclick: load }), status), host);
  load();
}

function flows(root, catalysts, evidence) {
  root.append(sectionTitle('CAPITAL & POSITIONING', 'EARNINGS PROXIMITY · SEC FORM 4'));
  if (!catalysts || catalysts.unavailable || !Array.isArray(catalysts.events)) {
    root.append(card('EARNINGS-RELATED BUYBACK BLACKOUT PROXY', null, info('Calendar artifact unavailable; coverage cannot be calculated.')));
  } else {
    const nearby = earningsProximity(catalysts.events, catalysts.as_of || '', 45);
    const weighted = nearby.filter((e) => valid(e.index_weights?.SPX));
    const weight = weighted.reduce((sum, e) => sum + e.index_weights.SPX, 0);
    const daysAway = (day) => Math.round((Date.parse(`${day}T12:00:00Z`) - Date.parse(`${catalysts.as_of}T12:00:00Z`)) / 86400000);
    const imminent = nearby.filter((e) => daysAway(e.date) <= 7);
    const search = el('input', { placeholder: 'Search ticker / company', size: '22' });
    const showAll = el('button', { class: 'action', text: 'SHOW ALL' });
    const count = el('span', { class: 'field-note' });
    const listHost = el('div', {});
    let expanded = false;
    const draw = () => {
      const query = search.value.trim().toUpperCase();
      const matches = nearby.filter((e) => !query || `${e.symbol} ${e.name || ''}`.toUpperCase().includes(query));
      const shown = query || expanded ? matches : matches.slice(0, 30);
      listHost.replaceChildren(table(['EARNINGS DATE', 'DAYS AWAY', 'TICKER', 'SPX WEIGHT', 'CALENDAR STATUS'], shown.map((e) => row(
        e.date, String(daysAway(e.date)), el('td', {}, [el('a', { href: tickerHref(e.symbol), text: e.symbol })]),
        valid(e.index_weights?.SPX) ? `${num(e.index_weights.SPX, 3)}%` : DASH,
        e.certainty_class === 'vendor_calendar' ? 'vendor estimate' : e.certainty_class || DASH))));
      count.textContent = `Showing ${shown.length} of ${matches.length} matching names`;
      showAll.textContent = expanded ? 'SHOW FIRST 30' : 'SHOW ALL';
    };
    search.addEventListener('input', draw);
    showAll.addEventListener('click', () => { expanded = !expanded; draw(); });
    draw();
    root.append(card('EARNINGS PROXIMITY · POSSIBLE BUYBACK WINDOW RISK · NEXT 45 DAYS', null, [
      el('div', { class: 'stat-strip' }, [
        el('div', { class: 'stat' }, [el('div', { class: 'stat-label', text: 'SCHEDULED NAMES' }), el('div', { class: 'stat-value', text: num(nearby.length, 0) })]),
        el('div', { class: 'stat' }, [el('div', { class: 'stat-label', text: 'WITHIN 7 DAYS' }), el('div', { class: 'stat-value', text: num(imminent.length, 0) })]),
        el('div', { class: 'stat' }, [el('div', { class: 'stat-label', text: 'KNOWN SPX WEIGHT' }), el('div', { class: 'stat-value', text: `${num(weight, 2)}%` })]),
      ]),
      el('div', { class: 'field-row' }, [field('FIND', search), showAll, count]), listHost,
      info(`Calendar as of ${catalysts.as_of}. Coverage: ${weighted.length} of ${nearby.length} scheduled names have SPX weights. Earnings proximity is only a watch queue, NOT a verified issuer repurchase blackout: company policy may differ, 10b5-1 plans may continue, and Nasdaq dates may change. Exact start/end and buyback dollars remain unknown.`),
    ]));
  }

  if (!evidence || evidence.unavailable || !Array.isArray(evidence.focus)) {
    root.append(card('INSIDER PURCHASE CLUSTERS', null, info('Form 4 evidence artifact unavailable; no negative inference is possible.')));
    return;
  }
  const focus = evidence?.focus || [];
  const names = evidence?.names || {};
  const clusters = focus.map((symbol) => ({ symbol, cluster: names[symbol]?.insiders?.strict_cluster,
    coverage: names[symbol]?.insiders?.form4_coverage }))
    .filter((r) => r.cluster).sort((a, b) => b.cluster.available.localeCompare(a.cluster.available));
  const complete = focus.filter((symbol) => names[symbol]?.insiders?.form4_coverage?.complete).length;
  root.append(card('INSIDER PURCHASE CLUSTERS · FOCUS NAMES ONLY', null, [
    clusters.length ? table(['TICKER', 'WINDOW', 'OWNERS', 'REPORTED VALUE', 'FILED / SOURCE'], clusters.map((r) => row(
      el('td', {}, [el('a', { href: tickerHref(r.symbol), text: r.symbol })]),
      `${r.cluster.from} → ${r.cluster.to}${r.coverage?.complete ? '' : ' · partial'}`,
      num(r.cluster.count, 0), money(r.cluster.value),
      el('td', {}, [r.cluster.filing_urls?.[0]
        ? el('a', { href: r.cluster.filing_urls[0], target: '_blank', rel: 'noopener noreferrer', text: r.cluster.available })
        : r.cluster.available]))))
      : info('No qualifying cluster in the focus names read this build.'),
    info(`SEC Form 4 research subset: direct acquired P purchases, positive price, no indicated 10b5-1 plan or swap; >=2 distinct owner CIKs within 5 SPX sessions and >=$250k. ${complete}/${focus.length} focus names fully read, not a market-wide scan. Code P can include private purchases; filing date is the earliest observable date, not transaction date. No alpha claim. ${Object.keys(evidence?.failed || {}).length ? `Source gaps: ${Object.keys(evidence.failed).join(', ')}.` : ''}`),
  ]));
  const purchaseNames = focus.filter((symbol) => names[symbol]?.insiders?.strict_purchases?.length);
  if (purchaseNames.length) {
    const picker = el('select', {}, purchaseNames.map((symbol) => el('option', { value: symbol, text: symbol })));
    const details = el('div', {});
    const draw = () => {
      const list = names[picker.value]?.insiders?.strict_purchases || [];
      details.replaceChildren(table(['TRADE DATE', 'FILED', 'OWNER', 'VALUE', 'SEC FILING'], list.map((p) => row(
        p.date, p.filed, p.owner || DASH, money(p.value), p.filing_url
          ? el('td', {}, [el('a', { href: p.filing_url, target: '_blank', rel: 'noopener noreferrer', text: 'OPEN' })]) : DASH))));
    };
    picker.addEventListener('change', draw);
    draw();
    root.append(card('INSPECT STRICT PURCHASES · LAST 90 DAYS', null, [field('FOCUS NAME', picker), details,
      info('This is the underlying subset, not a buy recommendation. A missing name may mean no qualifying filing or incomplete coverage; inspect the coverage count above.') ]));
  }
  root.append(info('Existing short-interest and CTA flip-level work remains on RISK → POSITIONING; no second copy is calculated here.'));
}

function scorecard(root, anchor, positioning, risk) {
  root.append(sectionTitle('SIGNAL SCORECARD', 'DESCRIPTIVE HISTORY · NOT OUT-OF-SAMPLE ALPHA'));
  const history = anchor?.history;
  const rows = anchorScorecard(history);
  const scoreTable = (readings) => table(['STATE AT CLOSE', 'HORIZON', 'SIGNAL / BASE N', 'DIR HIT / BASE', 'MEAN / BASE', 'Δ MEAN VS BASE'], readings.map((r) => row(
    el('td', {}, [tag(r.label, ['RISK-ON', 'LONG', 'EXTREME FEAR'].includes(r.label) ? 'up' : 'down')]), `${r.horizon} sessions`,
    `${num(r.count, 0)}${r.count < 10 ? ' · thin' : ''} / ${num(r.baseline_count, 0)}`,
    r.hit_rate === null ? DASH : `${num(r.hit_rate, 1)}% / ${num(r.baseline_hit_rate, 1)}%`,
    r.mean_pct === null ? DASH : `${pct(r.mean_pct, 2)} / ${pct(r.baseline_pct, 2)}`,
    r.difference_pct === null ? DASH : pct(r.difference_pct, 2))));
  root.append(card('FROZEN V1 ANCHOR · FORWARD SPY RETURN', null, [
    history ? scoreTable(rows) : info('Anchor artifact unavailable; no historical score is inferred.'),
    info(`As of ${anchor?.as_of || DASH}; ${history?.dates?.[0] || DASH} to ${history?.dates?.at(-1) || DASH}. `
      + 'Signal observed at day-end; enter at next close, exit after the stated sessions. Events of the same state do not overlap. '
      + 'Hit means SPY rose after RISK-ON or fell after RISK-OFF. Outcomes are underlying SPY returns, not anchor strategy P&L. Current-vintage Yahoo closes, no fees, no out-of-sample claim.'),
    info('BASE = all eligible sessions in the same signal-history window, sampled in non-overlapping blocks at each horizon. Δ mean is underlying-index signal mean minus baseline; a positive Δ is adverse for bearish states. Different sample timing is not causal uplift. Fewer than 10 outcomes are marked thin.'),
    info('Form 4 cluster, buyback-proxy, option-range and overnight signals have no causal archived panel here; their hit rates are unavailable until snapshots and point-in-time entry rules exist.'),
  ]));
  const sentiment = risk?.sentiment?.history;
  if (sentiment?.dates?.length && history?.dates?.length) root.append(card('FEAR & GREED EXTREMES · FORWARD SPY RETURN', null, [
    scoreTable(sentimentScorecard(sentiment, history)),
    info(`Fear & Greed scores aligned by session date to SPY. Extreme fear ≤25 tested as an up direction; extreme greed ≥75 as down. History ${sentiment.dates[0]} to ${sentiment.dates.at(-1)}; next-close entry, non-overlapping per state. Short sample and current-vintage components: descriptive only, not out-of-sample alpha.`),
  ]));
  for (const trend of positioning?.trend || []) {
    const readings = trendScorecard(trend);
    root.append(card(`${trend.label.toUpperCase()} TREND PROXY · FORWARD INDEX RETURN`, null, [
      readings.length ? scoreTable(readings) : info('Full daily trend history is unavailable; thinned chart points cannot be scored as trading sessions.'),
      info(`Close-only 4-lookback vote, ${trend.scorecard_history?.dates?.[0] || DASH} to ${trend.as_of}. LONG/SHORT requires ≥3 of 4 votes. `
        + 'Hit means index rose after LONG or fell after SHORT. Full daily observations, signal at close, next-close entry and non-overlapping per-state outcomes. Descriptive current-vintage history, not actual CTA holdings or strategy P&L.'),
    ]));
  }
  if (!positioning?.trend?.length) root.append(info('Trend-proxy scorecard unavailable: no positioning history in this build.'));
}

export default function renderTrade(root, payloads, _manifest, ctx) {
  const [technicals, evidence, catalysts, anchor, positioning, risk] = payloads || [];
  root.append(metaRow('TRADE DESK · US STOCKS & INDEX ETFs · OVERNIGHT TO WEEKS', [
    'Public research and sizing arithmetic only. No Futu account, alerts, journal or trade execution.',
    'Live quotes are separate from the nightly artifacts. Blank readings mean source coverage is absent, not zero.',
  ]));
  const tabs = ['SETUPS & SIZE', 'OVERNIGHT', 'CAPITAL & INSIDERS', 'SCORECARD'];
  const host = el('div', {});
  const switcher = periodSwitch(tabs, tabs[0], (selected) => {
    host.replaceChildren();
    if (selected === tabs[0]) setups(host, technicals, evidence, ctx);
    else if (selected === tabs[1]) overnight(host);
    else if (selected === tabs[2]) flows(host, catalysts, evidence);
    else scorecard(host, anchor, positioning, risk);
  });
  root.append(switcher, host);
  setups(host, technicals, evidence, ctx);
}
