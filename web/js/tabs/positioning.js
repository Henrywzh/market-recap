// POSITIONING: who is forced to trade. A rules-based trend-follower proxy on
// each index, with the closes that flip it tomorrow; and FINRA short interest
// for the members, the watchlist and the broad ETFs.

import { el, card, num, metaRow, table, tag, periodSwitch, DASH } from '../fmt.js';
import { render, timeLines } from '../charts.js';
import { rangeSwitch, sliceRange, initialRange, availableRanges } from '../range.js';
import { spark } from '../spark.js';
import { tickerHref } from '../routes.js';
import { availableSeries, notShownNote, putCallReading } from '../put-call-model.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits = 1, suffix = '') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${suffix}` : DASH);
const STATE_TONE = { LONG: 'up', SHORT: 'down', MIXED: 'warn' };

function dollars(v) {
  if (!present(v)) return DASH;
  const a = Math.abs(v);
  if (a >= 1e9) return `$${num(v / 1e9, 1)}bn`;
  if (a >= 1e6) return `$${num(v / 1e6, a >= 1e7 ? 0 : 1)}m`;
  return `$${num(v, 0)}`;
}

function shares(v) {
  if (!present(v)) return DASH;
  return v >= 1e9 ? `${num(v / 1e9, 2)}bn` : v >= 1e6 ? `${num(v / 1e6, 1)}m` : num(v, 0);
}

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}` }, [].concat(value)),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

// Index options only: no substitution by Total P/C, SPY or QQQ.
function putCallSection(data) {
  const series = availableSeries(data?.series);
  const notShown = notShownNote(data?.disabled);
  if (!series.length) {
    return el('div', {}, [
      el('div', { class: 'gap', text: 'Index-specific put/call data was not built for this session.' }),
      notShown ? el('div', { class: 'field-note dim', text: notShown }) : null,
    ]);
  }
  let window = data.default_window;
  let range = availableRanges(series[0].dates, { short: true }).includes('3M') ? '3M' : 'MAX';
  const windows = Object.keys(series[0].windows);
  const chart = el('div', { class: 'chart', 'aria-label': 'Index option put/call volume ratio history' });
  const stats = el('div', { class: 'grid two pc-readings' });
  const draw = () => {
    const readings = series.map((row) => putCallReading(row, window, range));
    stats.replaceChildren(...series.map((row, i) => {
      const reading = readings[i];
      const dated = present(reading.latest) ? `${data.as_of} · ${window}` : `no complete ${window} reading for ${data.as_of}`;
      return el('div', {}, [
        el('div', { class: 'stat-label', text: row.label }),
        el('div', { class: 'stat-value', text: num(reading.latest, 2) }),
        el('div', { class: 'stat-note', text: dated }),
        el('div', { class: 'pc-baseline', text: `Median ${num(reading.median, 2)} · percentile ${present(reading.percentile) ? `${num(reading.percentile, 1)}%` : DASH}` }),
        el('div', { class: 'field-note', text: `${range}: ${reading.observed} / ${reading.expected} daily sessions · ${reading.missing} missing · ${reading.dates[0] || DASH} → ${reading.dates.at(-1) || DASH}` }),
      ]);
    }));
    const drawn = series.map((row, i) => ({ row, reading: readings[i] })).filter(({ reading }) => reading.observations > 0);
    chart.hidden = !drawn.length;
    if (!drawn.length) return;
    // The dashed line marks the range median of the first drawn series, so the chart shows the figure the text states.
    const first = drawn[0].reading;
    timeLines(chart, drawn.map(({ row, reading }, i) => ({
      name: row.label, ...reading, color: (p) => i === 0 ? p.accent : p.blue,
    })), {
      value: (v) => num(v, 3),
      markY: present(first.median) ? [{ y: first.median, label: `median ${num(first.median, 2)}` }] : [],
    });
  };
  requestAnimationFrame(draw);
  return card('INDEX OPTIONS · PUT / CALL VOLUME', periodSwitch(windows, window, (label) => { window = label; draw(); }), [
    el('div', { class: 'pc-controls' }, [el('span', { class: 'dim', text: 'HISTORY RANGE' }), rangeSwitch(series[0].dates, range, (label) => { range = label; draw(); }, { short: true })]),
    stats, chart,
    ...series.map((row) => el('div', { class: 'pc-source' }, [
      el('a', { href: row.source_url, target: '_blank', rel: 'noopener', text: `${row.label} · ${row.source_label}` }),
    ])),
    el('details', { class: 'sx-fold' }, [el('summary', { text: 'Method, coverage & interpretation' }),
      el('div', { class: 'note-text', text: data.method }),
      ...series.map((row) => el('div', { class: 'note-text', text: `${row.label}: ${[row.scope, row.note].filter(Boolean).join(' ')}` })),
      el('div', { class: 'note-text', text: '1D / 1W / 1M above select daily / 5-session / 21-session smoothing. HISTORY RANGE selects the displayed dates; median, percentile and coverage use that range only. YTD ends on the artifact date, not today.' }),
      el('div', { class: 'note-text', text: 'Series from different providers or universes are not automatically comparable: levels and percentiles differ. High P/C is not, by itself, a bullish reversal signal.' }),
      notShown ? el('div', { class: 'note-text dim', text: notShown }) : null,
    ]),
  ]);
}

// ------------------------------------------------------------ trend followers

const SIGMA_MOVES = [-2, -1, 0, 1, 2];

// Dollar text for a range of $bn, one decimal below $10bn.
const bnText = (v) => (Math.abs(v) >= 10 ? num(v, 0) : num(v, 1));

// A signed $bn range: "+$4.8–9.6bn" for buying, "-$32–64bn" for selling.
export function flowText(low, high) {
  if (!present(low) || !present(high)) return DASH;
  const lo = Math.min(Math.abs(low), Math.abs(high));
  const hi = Math.max(Math.abs(low), Math.abs(high));
  if (hi === 0) return '$0bn';
  const sign = (low + high) / 2 >= 0 ? '+' : '-';
  return lo === hi ? `${sign}$${bnText(hi)}bn` : `${sign}$${bnText(lo)}–${bnText(hi)}bn`;
}

// The same range in words: "about $5–10bn of buying".
function flowWords(row) {
  if (!present(row.flow_bn_low) || !present(row.flow_bn_high)) return 'no dollar estimate for this index';
  const lo = Math.min(Math.abs(row.flow_bn_low), Math.abs(row.flow_bn_high));
  const hi = Math.max(Math.abs(row.flow_bn_low), Math.abs(row.flow_bn_high));
  const side = row.position_change >= 0 ? 'buying' : 'selling';
  return lo === hi ? `about $${bnText(hi)}bn of ${side}` : `about $${bnText(lo)}–${bnText(hi)}bn of ${side}`;
}

// The answer to "what does a move do": flat, then a 2-sigma fall and rally, over five sessions.
export function scenarioSentences(t) {
  const rows = t?.model?.scenarios || [];
  const pick = (moveSd) => rows.find((r) => r.sessions === 5 && r.move_sd === moveSd);
  const flat = pick(0);
  const fall = pick(-2);
  const rally = pick(2);
  if (![flat, fall, rally].every((r) => r && present(r.position_change))) return [];
  const verb = (d) => (d > 0 ? 'ADDS' : 'CUTS');
  const pts = (d) => num(Math.abs(d), 0);
  const flatLine = Math.abs(flat.position_change) < 0.5
    ? `If the ${t.label} is flat for 5 sessions, the model HOLDS its position.`
    : `If the ${t.label} is flat for 5 sessions, the model ${verb(flat.position_change)} ${pts(flat.position_change)} pts ${flat.position_change > 0 ? '(calmer volatility)' : '(wilder volatility)'}: ${flowWords(flat)}.`;
  const shockLine = (word, r) => (Math.abs(r.position_change) < 0.5
    ? `A 2σ ${word} over 5 sessions leaves the model's position unchanged.`
    : `A 2σ ${word} over 5 sessions makes the model ${verb(r.position_change)} ${pts(r.position_change)} pts: ${flowWords(r)}.`);
  return [flatLine, shockLine('drop', fall), shockLine('rally', rally)];
}

// Model position on a −100…+100 scale, with the marker and the room to each limit.
function positionBar(pos) {
  const track = el('div', { class: 'pos-bar', 'aria-hidden': 'true' }, [el('div', { class: 'pos-bar-zero' })]);
  if (present(pos)) {
    track.append(el('div', { class: `pos-bar-mark ${pos >= 0 ? 'up' : 'down'}`, style: `left: ${(((pos + 100) / 200) * 100).toFixed(1)}%` }));
  }
  return el('div', { class: 'pos-bar-wrap' }, [
    track,
    el('div', { class: 'pos-bar-scale' }, [el('span', { text: '−100 max short' }), el('span', { text: '0' }), el('span', { text: '+100 max long' })]),
  ]);
}

function modelHead(t) {
  const pos = t.model.position;
  const tone = present(pos) ? (pos > 0 ? 'up' : pos < 0 ? 'down' : '') : 'dim';
  const room = t.model.room || {};
  const roomText = present(room.to_max_long) && present(room.to_max_short)
    ? `room to max long: ${num(room.to_max_long, 0)} pts · to max short: ${num(room.to_max_short, 0)} pts`
    : DASH;
  return el('div', { class: 'trend-model' }, [
    el('div', { class: 'anchor-head' }, [
      el('span', { class: `anchor-value ${tone}`, text: present(pos) ? `${signed(pos, 0, '%')} ${pos >= 0 ? 'of max long' : 'of max short'}` : DASH }),
      tag(t.state || DASH, STATE_TONE[t.state] || 'dim'),
      el('span', { class: 'dim', text: `vote score ${signed(t.score, 2)}` }),
      el('span', { class: 'dim', text: `close ${num(t.close, 0)} · ${t.as_of}` }),
    ]),
    positionBar(pos),
    el('div', { class: 'field-note', text: roomText }),
  ]);
}

// Each move, one and five sessions: the path, the position change and the dollar range.
function flowsTable(t) {
  const pick = (sessions, moveSd) => t.model.scenarios.find((r) => r.sessions === sessions && r.move_sd === moveSd) || {};
  const moveLabel = (m) => (m === 0 ? 'flat' : `${m > 0 ? '+' : '-'}${Math.abs(m)}σ`);
  const tone = (d) => (present(d) ? (d > 0.5 ? 'up' : d < -0.5 ? 'down' : 'dim') : 'dim');
  const cells = (r) => [
    el('td', { text: present(r.move_pct) ? signed(r.move_pct, 1, '%') : DASH }),
    el('td', { class: tone(r.position_change), text: present(r.position_change) ? signed(r.position_change, 0, ' pts') : DASH }),
    el('td', { class: tone(r.position_change), text: flowText(r.flow_bn_low, r.flow_bn_high) }),
  ];
  return el('table', { class: 'data pos-table pos-flows' }, [
    el('thead', {}, [el('tr', {}, ['MOVE', 'PATH 1D', 'POSITION 1D', '$ 1D', 'PATH 5D', 'POSITION 5D', '$ 5D'].map((h) => el('th', { text: h })))]),
    el('tbody', {}, SIGMA_MOVES.map((m) => el('tr', {}, [
      el('td', { text: moveLabel(m) }), ...cells(pick(1, m)), ...cells(pick(5, m)),
    ]))),
  ]);
}

// Two value axes, each with its own bounds; every line names the axis it reads.
function twoAxisChart(node, lines, axes) {
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 56, right: 56, bottom: 52 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, valueFormatter: (x) => (present(x) ? num(x, 1) : DASH) },
    xAxis: { ...option.xAxis, type: 'time', boundaryGap: false },
    yAxis: axes.map((axis, i) => ({
      ...option.yAxis,
      min: axis.min,
      max: axis.max,
      position: i ? 'right' : 'left',
      splitLine: i ? { show: false } : option.yAxis.splitLine,
      axisLabel: { ...option.yAxis.axisLabel, formatter: axis.format },
    })),
    series: lines.map((line) => ({
      name: line.name, type: 'line', yAxisIndex: line.axis === 1 ? 1 : 0,
      data: line.dates.map((d, k) => [d, line.values[k]]),
      showSymbol: false, connectNulls: false,
      itemStyle: { color: line.color(p) },
      lineStyle: { color: line.color(p), width: line.width || 1.4 },
    })),
  }));
}

// The listed trend-following ETF's equity beta against the model position. A check, not a holding.
function checkBlock(check) {
  const title = `CHECK: LISTED TREND ETF (${check?.etf || 'DBMF'}) EQUITY BETA · ${check?.window || 63}-SESSION`;
  if (!check || check.unavailable) {
    return el('div', { class: 'trend-check' }, [
      el('div', { class: 'stat-label', text: title }),
      el('div', { class: 'gap', text: `Not built this session${check?.unavailable ? `: ${check.unavailable}` : ''}.` }),
    ]);
  }
  const node = el('div', { class: 'chart check-chart', 'aria-label': 'Equity beta of a listed trend-following ETF and the S&P 500 model position' });
  requestAnimationFrame(() => twoAxisChart(node, [
    { name: `${check.etf} equity beta (left)`, dates: check.dates, values: check.beta, axis: 0, color: (p) => p.blue, width: 1.4 },
    { name: 'model position (right)', dates: check.dates, values: check.position, axis: 1, color: (p) => p.accent, width: 1.2 },
  ], [{ format: (v) => num(v, 1) }, { min: -100, max: 100, format: (v) => num(v, 0) }]));
  const corrText = (v) => (present(v) ? num(v, 2) : DASH);
  const corr = `corr with the model: levels ${corrText(check.corr_levels)} · quarterly changes ${corrText(check.corr_with_model)}`;
  return el('div', { class: 'trend-check' }, [
    el('div', { class: 'stat-label', text: title }),
    node,
    el('div', { class: 'field-note', text: `beta now ${present(check.beta_now) ? num(check.beta_now, 2) : DASH} as of ${check.as_of || DASH} · ${corr}` }),
  ]);
}

function trendCard(t, check) {
  const dates = t.history.score.dates;
  const title = `${t.label.toUpperCase()} · TREND FOLLOWERS`;
  if (!t.model) return card(title, null, el('div', { class: 'gap', text: 'Model not built this session.' }));
  const node = el('div', { class: 'chart trend-chart' });
  const model = t.model;
  let range = initialRange(model.history.position.dates.length ? model.history.position.dates : dates, '1Y');
  const draw = () => {
    const pos = sliceRange(model.history.position.dates, { values: model.history.position.values }, range);
    const vc = sliceRange(model.history.vol_control.dates, { values: model.history.vol_control.values }, range);
    const close = sliceRange(t.history.close.dates, { values: t.history.close.values }, range);
    twoAxisChart(node, [
      { name: 'model position (left)', ...pos, axis: 0, color: (p) => p.accent, width: 1.4 },
      { name: 'vol-control exposure (left)', ...vc, axis: 0, color: (p) => p.blue, width: 1 },
      { name: `${t.label} (right)`, ...close, axis: 1, color: (p) => p.faint, width: 1 },
    ], [{ min: -100, max: 100, format: (v) => num(v, 0) }, { format: (v) => num(v, 0) }]);
  };
  requestAnimationFrame(draw);

  const flips = el('table', { class: 'data pos-table' }, [
    el('thead', {}, [el('tr', {}, ['LOOKBACK', 'RETURN', 'SIGNAL', 'FLIPS TOMORROW AT', 'DISTANCE'].map((h) => el('th', { text: h })))]),
    el('tbody', {}, [
      ...t.flips.map((f) => el('tr', {}, [
        el('td', { text: f.lookback }),
        el('td', { class: f.return_pct >= 0 ? 'up' : 'down', text: signed(f.return_pct, 1, '%') }),
        el('td', {}, [tag(f.signal > 0 ? 'LONG' : f.signal < 0 ? 'SHORT' : 'FLAT', f.signal > 0 ? 'up' : f.signal < 0 ? 'down' : 'dim')]),
        el('td', { text: `${f.signal > 0 ? 'below' : 'above'} ${num(f.flip_level, 0)}` }),
        el('td', { class: Math.abs(f.distance_pct) < 2 ? 'down' : 'dim', text: signed(f.distance_pct, 1, '%') }),
      ])),
      ...t.averages.map((m) => el('tr', { class: 'dim' }, [
        el('td', { text: `${m.window}-day avg` }),
        el('td', { text: '' }),
        el('td', {}, [tag(m.above ? 'ABOVE' : 'BELOW', m.above ? 'up' : 'down')]),
        el('td', { text: num(m.level, 0) }),
        el('td', { text: signed(m.distance_pct, 1, '%') }),
      ])),
    ]),
  ]);

  const lines = scenarioSentences(t);
  const [low, high] = model.flow_assumption_bn || [];
  return card(title, rangeSwitch(model.history.position.dates.length ? model.history.position.dates : dates, range, (label) => { range = label; draw(); }), [
    modelHead(t),
    lines.length
      ? el('div', { class: 'trend-answer-block' }, lines.map((text) => el('p', { class: 'trend-answer', text })))
      : el('div', { class: 'gap', text: 'No scenario reading for this index.' }),
    el('div', { class: 'table-scroll' }, [flowsTable(t)]),
    node,
    check ? checkBlock(check) : null,
    el('div', { class: 'table-scroll' }, [flips]),
    el('details', { class: 'sx-fold' }, [el('summary', { text: 'Method & limits' }),
      el('div', { class: 'note-text', text: `Model position: a continuous trend strength times a volatility scale. Each lookback's return is measured in its own volatility (the 60-session daily sigma times the square root of its length) and capped at ±1, so a lookback one sigma up is fully long and one near zero is near flat; the strength is their average. Unlike the vote above, crossing a flip level moves it a little, not all at once. The 60-session volatility is scaled to 15% a year, leverage is capped at 2×, and +100 is the maximum long (−100 the maximum short). Vol-control exposure is a long-only book that targets 10% volatility, capped at 1.5×: it buys when volatility falls, whatever the trend.` }),
      el('div', { class: 'note-text', text: `Scenarios step the close by a whole number of daily sigmas per session (sigma from the last 20 daily returns) and recompute both readings at the end. They are arithmetic on the model, not forecasts.` }),
      el('div', { class: 'note-text', text: low && high ? `Dollar figures assume a notional range for trend-following futures at a full model long: $${num(low, 0)}–${num(high, 0)}bn. That range is an assumption, not observed; the page does not show a fund's position.` : 'No dollar estimate: the assumed notional range is not set for this index.' }),
      el('div', { class: 'note-text', text: 'The check: the listed trend-following ETF\'s equity beta is a rolling 63-session regression of its daily returns on SPY, IEF, UUP, GLD and USO, estimated from prices. It is not read from its holdings.' }),
    ]),
  ]);
}

// ------------------------------------------------------------ short interest

function siTable(rows, sparks, { linkNames = true } = {}) {
  return el('div', { class: 'table-scroll' }, [el('table', { class: 'data pos-table' }, [
    el('thead', {}, [el('tr', {}, ['NAME', 'SHORT', 'VALUE', 'CHANGE', 'DAYS TO COVER', '1Y'].map((h) => el('th', { text: h })))]),
    el('tbody', {}, rows.map((r) => el('tr', {}, [
      el('td', { title: r.name || '' }, [linkNames ? el('a', { href: tickerHref(r.ticker), text: r.ticker }) : r.ticker,
        r.name ? el('span', { class: 'sub', text: r.name }) : null]),
      el('td', { text: shares(r.shares_short) }),
      el('td', { text: dollars(r.short_value) }),
      el('td', { class: present(r.change_pct) ? (r.change_pct > 0 ? 'down' : 'up') : 'dim', text: signed(r.change_pct, 1, '%') }),
      el('td', {}, [present(r.days_to_cover)
        ? tag(num(r.days_to_cover, 1), r.days_to_cover >= 7 ? 'down' : r.days_to_cover >= 4 ? 'warn' : 'dim')
        : DASH]),
      el('td', { class: 'pos-spark' }, [spark(sparks?.[r.ticker], { width: 90, height: 20, color: 'var(--text-dim)' })]),
    ]))),
  ])]);
}

function aggregateChart(node, aggregate) {
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 56, right: 48, bottom: 44 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    xAxis: { ...option.xAxis, data: aggregate.map((a) => a.date), boundaryGap: true },
    yAxis: [
      { ...option.yAxis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `$${v}bn` } },
      { ...option.yAxis, position: 'right', splitLine: { show: false }, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${v}d` } },
    ],
    series: [
      { name: 'S&P 500 members short, $bn', type: 'bar', data: aggregate.map((a) => a.short_value_bn), itemStyle: { color: p.accent, opacity: 0.75 }, barMaxWidth: 14 },
      { name: 'median days to cover (right)', type: 'line', yAxisIndex: 1, data: aggregate.map((a) => a.median_days_to_cover), showSymbol: true, symbolSize: 4, lineStyle: { color: p.blue, width: 1.3 }, itemStyle: { color: p.blue } },
    ],
  }));
}

function shortSection(si) {
  if (!si || si.unavailable) {
    return card('SHORT INTEREST', null, el('div', { class: 'gap', text: `Not built this session${si?.unavailable ? `: ${si.unavailable}` : ''}.` }));
  }
  const aggNode = el('div', { class: 'chart short' });
  requestAnimationFrame(() => aggregateChart(aggNode, si.aggregate));
  const wrap = el('div', {}, [
    el('div', { class: 'grid two' }, [
      card('S&P 500 MEMBERS · SHORT INTEREST BY ROUND', el('span', { class: 'dim', text: `${si.rounds.length} rounds · settled ${si.settlement_date}` }), [aggNode]),
      card('ETFs · SHORT INTEREST', el('span', { class: 'dim', text: 'hedges show up here first' }), siTable(si.etfs, si.spark, { linkNames: false })),
    ]),
    el('div', { class: 'grid three pos-lists' }, [
      card('MOST DAYS TO COVER', el('span', { class: 'dim', text: 'shares short ÷ average daily volume' }), siTable(si.most_days_to_cover, si.spark)),
      card('SHORTS ADDED', el('span', { class: 'dim', text: `% change since ${si.previous_settlement_date}` }), siTable(si.biggest_increase, si.spark)),
      card('SHORTS COVERED', el('span', { class: 'dim', text: `% change since ${si.previous_settlement_date}` }), siTable(si.biggest_decrease, si.spark)),
    ]),
  ]);
  if (si.watchlist?.length) wrap.append(card('WATCHLIST · SHORT INTEREST', null, siTable(si.watchlist, si.spark)));
  return wrap;
}

// ------------------------------------------------------------ buyback blackout

function blackoutSection(b) {
  if (!b || b.unavailable) {
    return card('BUYBACK BLACKOUT', null, el('div', { class: 'gap', text: `Not built this session${b?.unavailable ? `: ${b.unavailable}` : ''}.` }));
  }
  const node = el('div', { class: 'chart', 'aria-label': 'Estimated share of current S&P 500 weight in buyback blackout' });
  // Momentum counts only when it was built for this artifact date; otherwise its cells show a dash.
  const momentum = b.momentum?.as_of === b.as_of ? b.momentum : {};
  const key = momentum.default_window || DASH;
  const w = (momentum.windows || []).find((row) => row.key === momentum.default_window);
  const strip = el('div', { class: 'stat-strip blackout-momentum' }, [
    stat('IN BLACKOUT NOW', present(b.now_pct) ? `${num(b.now_pct, 1)}%` : DASH, `% of current weight · as of ${b.as_of}`),
    stat(`PAST ${key} CHANGE`, signed(w?.now_delta_pp, 1, ' pp'), 'change in estimated covered weight'),
    stat(`NEXT ${key} SCHEDULED`, signed(w?.ahead_delta_pp, 1, ' pp'), 'calendar + projected report dates'),
    stat('PEAK AHEAD', present(b.peak_pct) ? `${num(b.peak_pct, 1)}%` : DASH, `on ${b.peak_date || DASH}`),
  ]);
  requestAnimationFrame(() => render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 48, bottom: 64 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, valueFormatter: (x) => (present(x) ? `${num(x, 1)}%` : DASH) },
    xAxis: { ...option.xAxis, data: b.dates },
    yAxis: { ...option.yAxis, min: 0, max: 100, axisLabel: { ...option.yAxis.axisLabel, formatter: (x) => `${num(x, 1)}%` } },
    series: [
      {
        name: 'reconstructed history', type: 'line', showSymbol: false, step: 'end',
        data: (b.share_pct || []).map((x, i) => (b.dates[i] <= b.as_of ? x : null)),
        itemStyle: { color: p.accent },
        lineStyle: { width: 1.4, color: p.accent },
        areaStyle: { color: p.accent, opacity: 0.12 },
        markLine: {
          silent: true, symbol: 'none',
          data: [{ xAxis: b.as_of, label: { formatter: 'artifact date' } }, { yAxis: 50, label: { formatter: '50%', position: 'insideEndTop' } }],
          lineStyle: { color: p.faint, type: 'dashed' }, label: { color: p.dim, fontSize: 9 },
        },
      },
      {
        name: 'ahead · calendar + projected', type: 'line', showSymbol: false, step: 'end',
        data: (b.share_pct || []).map((x, i) => (b.dates[i] >= b.as_of ? x : null)),
        itemStyle: { color: p.blue },
        lineStyle: { width: 1.4, color: p.blue, type: 'dashed' },
      },
    ],
  })));
  return el('div', { class: 'blackout-section' }, [
    card('S&P 500 WEIGHT IN A BUYBACK BLACKOUT · ESTIMATED BY CONVENTION', el('span', { class: 'dim', text: `as of ${b.as_of}` }), [
      strip, node,
      el('div', { class: 'note-text', text: 'A convention, not data: no company publishes its window, and many keep buying through it under 10b5-1 plans.' }),
      el('details', { class: 'sx-fold' }, [el('summary', { text: 'Method & limits' }),
        el('div', { class: 'note-text', text: `A proxy for potentially reduced discretionary repurchase demand, not observed buyback flow or a price forecast. Each member counts from ${b.before_days} calendar days before each report to ${b.after_days} days after, weighted by today's S&P 500 weight. Report dates come from the member's past filings, the next one from the earnings calendar, or a projection from its usual gap (${b.projected} names). A convention, not any company's policy: prearranged 10b5-1 plans may keep buying through a blackout.` }),
        el('div', { class: 'note-text', text: `Windows are calendar days, not trading sessions. Dashed values after ${b.as_of} are schedule scenarios, not observed changes. Report-date coverage is ${present(b.weight_covered_pct) ? `${num(b.weight_covered_pct, 1)}%` : DASH} of current weight: ${b.scheduled} scheduled, ${b.projected} projected, ${b.missing} unknown next dates.` }),
        el('div', { class: 'note-text', text: 'Not point-in-time: current constituents and weights are applied backwards, and historical report-date coverage is not audited per day. Roughly one year is too short for a credible OOS or causal backtest; high blackout is not a sell signal.' }),
      ]),
    ]),
  ]);
}

// ------------------------------------------------------------ insider buying

function insiderSection(ins) {
  if (!ins || ins.unavailable) {
    return card('INSIDER BUYING', null, el('div', { class: 'gap', text: `Not built this session${ins?.unavailable ? `: ${ins.unavailable}` : ''}.` }));
  }
  const cover = ins.coverage || {};
  const recent = ins.largest || [];
  const weeklyNode = el('div', { class: 'chart short' });
  requestAnimationFrame(() => render(weeklyNode, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 56, right: 40, bottom: 44 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    xAxis: { ...option.xAxis, boundaryGap: true, data: ins.weekly.map((w) => w.week) },
    yAxis: [
      { ...option.yAxis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `$${num(v / 1e6, 0)}m` } },
      { ...option.yAxis, position: 'right', splitLine: { show: false }, minInterval: 1 },
    ],
    series: [
      { name: 'strict purchases, $ (week filed)', type: 'bar', barMaxWidth: 14, data: ins.weekly.map((w) => w.value), itemStyle: { color: p.up, opacity: 0.75 } },
      { name: 'companies (right)', type: 'line', yAxisIndex: 1, data: ins.weekly.map((w) => w.companies), showSymbol: true, symbolSize: 4, lineStyle: { color: p.blue, width: 1.2 }, itemStyle: { color: p.blue } },
    ],
  })));
  const link = (url, text) => (url ? el('a', { href: url, target: '_blank', rel: 'noopener noreferrer', text }) : text);
  const clusterRows = (ins.clusters || []).map((c) => el('tr', {}, [
    el('td', {}, [el('a', { href: tickerHref(c.ticker), text: c.ticker }), el('span', { class: 'sub', text: c.name || '' })]),
    el('td', {}, [tag(`${c.count} INSIDERS`, 'up')]),
    el('td', { text: dollars(c.value) }),
    el('td', { class: 'dim', text: `${c.from} → ${c.to}` }),
    el('td', {}, [link(c.filing_urls?.[0], c.available)]),
    el('td', { class: 'dim', text: present(c.spx_weight) ? `${num(c.spx_weight, 2)}%` : '—' }),
  ]));
  const buyRows = recent.map((b) => el('tr', {}, [
    el('td', {}, [el('a', { href: tickerHref(b.ticker), text: b.ticker }), el('span', { class: 'sub', text: b.name || '' })]),
    el('td', { text: b.owner || '—' }),
    el('td', { text: dollars(b.value) }),
    el('td', { class: 'dim', text: b.date }),
    el('td', {}, [link(b.filing_url, b.filed)]),
  ]));
  const companies = new Set(recent.map((b) => b.ticker)).size;
  return el('div', {}, [
    el('div', { class: 'stat-strip' }, [
      stat('CLUSTERS', String((ins.clusters || []).length), `≥2 insiders within 5 sessions · ${ins.window_days} days`, (ins.clusters || []).length ? 'up' : ''),
      stat('LARGEST BUY', recent[0] ? dollars(recent[0].value) : DASH, recent[0] ? `${recent[0].ticker} · ${recent[0].filed}` : ''),
      stat('COMPANIES BUYING', String(companies), 'in the largest-buys list below'),
      stat('COVERAGE', cover.complete ? [tag('COMPLETE', 'up')] : [tag(`${cover.days_complete}/${cover.days} DAYS`, 'warn')],
        `${num(cover.filings_read, 0)} of ${num(cover.filings_expected, 0)} filings · read through ${cover.read_through || DASH}`),
    ]),
    el('div', { class: 'grid two' }, [
      card('INSIDER BUYING BY WEEK', el('span', { class: 'dim', text: `${cover.members} S&P 500 / Nasdaq-100 issuers` }), [weeklyNode]),
      card('CLUSTER BUYS', el('span', { class: 'dim', text: 'newest first' }), clusterRows.length
        ? el('div', { class: 'table-scroll' }, [el('table', { class: 'data pos-table' }, [
          el('thead', {}, [el('tr', {}, ['NAME', 'BUYERS', 'VALUE', 'TRADED', 'FILED', 'SPX WT'].map((h) => el('th', { text: h })))]),
          el('tbody', {}, clusterRows)])])
        : el('div', { class: 'gap', text: 'No cluster in the filings read so far.' })),
    ]),
    card('LARGEST INSIDER PURCHASES · LAST 30 DAYS', null, buyRows.length
      ? el('div', { class: 'table-scroll' }, [el('table', { class: 'data pos-table' }, [
        el('thead', {}, [el('tr', {}, ['NAME', 'INSIDER', 'VALUE', 'TRADED', 'FILED'].map((h) => el('th', { text: h })))]),
        el('tbody', {}, buyRows)])])
      : el('div', { class: 'gap', text: 'No strict purchase filed in the last 30 days among the filings read.' })),
    el('div', { class: 'note-text', text: `Strict Form 4 purchases only: transaction code P, acquired, held directly, a positive price, no 10b5-1 plan, no swap, one reporting owner per filing. Code P can still include a private purchase. Read from EDGAR's daily index for every Form 4 about an index member, newest day first; each build reads at most a fixed number of new filings, so the window fills over a few nights and the coverage figure says how far it has got. Filing date is when the market could first see it. Evidence of conviction, not a validated signal.` }),
  ]);
}

function methodNotes(data) {
  const lb = Object.entries(data.lookbacks || {}).map(([k, n]) => `${k} (${n} sessions)`).join(', ');
  return [
    `Trend followers: a public stand-in for systematic trend books, whose models are private. Each lookback — ${lb} — votes long if the index is above its close that many sessions ago and short if below; the score is the average vote, from −1 (all short) to +1 (all long). LONG or SHORT needs three of four votes to agree. A vote flips tomorrow if tomorrow's close crosses the close it will be compared with, so each flip level is a known price, not a forecast. Levels within 2% are shown in red. The 50/100/200-day averages are the other lines trend rules watch.`,
    'Short interest: FINRA consolidated short interest, reported by member firms as of two settlement dates a month (mid-month and month-end) and published about seven business days later. Days to cover is FINRA\'s own figure: shares short over average daily volume. Short value prices the shares at the settlement-date close. Change is against the previous round. A red CHANGE is shorts added.',
    'Buyback blackout: an estimate from each member\'s report dates and a fixed window around them; insider buying: strict Form 4 purchases from EDGAR. Both are explained under their charts.',
    'None of these readings is a signal on its own. They say where forced buying or selling would come from if price moves: a trend book near its flip level, or a crowded short with many days to cover.',
  ];
}

export default function renderPositioning(root, data) {
  if (!data || data.unavailable) throw new Error(data?.unavailable || 'positioning artifact missing');
  const si = data.short_interest || {};
  root.append(metaRow(`POSITIONING · WHO IS FORCED TO TRADE · AS OF ${data.as_of}`, methodNotes(data)));

  const agg = si.aggregate || [];
  const last = agg[agg.length - 1];
  const prev = agg[agg.length - 2];
  const change = last && prev && present(last.short_value_bn) && present(prev.short_value_bn) ? (last.short_value_bn / prev.short_value_bn - 1) * 100 : null;
  root.append(el('div', { class: 'stat-strip' }, [
    ...data.trend.map((t) => stat(`${t.label.toUpperCase()} TREND`, [tag(t.state || DASH, STATE_TONE[t.state] || 'dim')], `score ${signed(t.score, 2)}`)),
    stat('S&P 500 SHORT VALUE', last ? `$${num(last.short_value_bn, 0)}bn` : DASH, change === null ? '' : `${signed(change, 1, '%')} vs prior round`, change > 0 ? 'down' : change < 0 ? 'up' : ''),
    stat('MEDIAN DAYS TO COVER', last ? num(last.median_days_to_cover, 1) : DASH, last ? `${last.names} members · ${last.date}` : ''),
    stat('BUYBACK BLACKOUT', present(data.blackout?.now_pct) ? `${num(data.blackout.now_pct, 0)}%` : DASH, 'estimated weight · not observed flow'),
    stat('INSIDER CLUSTERS', data.insiders?.clusters ? String(data.insiders.clusters.length) : DASH,
      data.insiders?.coverage ? `${data.insiders.window_days} days · ${data.insiders.coverage.complete ? 'all filings read' : 'filling in'}` : ''),
  ]));

  root.append(el('h2', { class: 'section-title', text: 'INDEX PUT / CALL' }));
  root.append(putCallSection(data.index_put_call));
  root.append(el('h2', { class: 'section-title', text: 'SHORT INTEREST' }));
  root.append(shortSection(si));
  root.append(el('h2', { class: 'section-title', text: 'INSIDER BUYING' }));
  root.append(insiderSection(data.insiders));

  root.append(el('h2', { class: 'section-title', text: 'TREND FOLLOWERS' }));
  root.append(el('div', { class: 'grid two' }, data.trend.map((t) => trendCard(t, t.key === 'SPX' ? data.trend_check : null))));

  root.append(el('h2', { class: 'section-title', text: 'BUYBACK BLACKOUT' }));
  root.append(blackoutSection(data.blackout));
}
