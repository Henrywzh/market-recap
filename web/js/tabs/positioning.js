// POSITIONING: who is forced to trade. A rules-based trend-follower proxy on
// each index, with the closes that flip it tomorrow; and FINRA short interest
// for the members, the watchlist and the broad ETFs.

import { el, card, num, metaRow, tag, DASH } from '../fmt.js';
import { render, timeLines } from '../charts.js';
import { rangeSwitch, sliceRange, initialRange } from '../range.js';
import { spark } from '../spark.js';
import { tickerHref } from '../routes.js';

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

// ------------------------------------------------------------ trend followers

function trendCard(t) {
  const node = el('div', { class: 'chart' });
  const dates = t.history.score.dates;
  let range = initialRange(dates, '1Y');
  const draw = () => {
    const s = sliceRange(t.history.score.dates, { values: t.history.score.values }, range);
    const c = sliceRange(t.history.close.dates, { values: t.history.close.values }, range);
    timeLines(node, [
      { name: 'trend score (left)', ...s, color: (p) => p.accent, width: 1.4 },
      { name: `${t.label} (right)`, ...c, axis: 1, color: (p) => p.faint, width: 1 },
    ], {
      left: (v) => v.toFixed(1),
      right: (v) => num(v, 0),
      value: (v, line) => (line.axis === 1 ? num(v, 0) : num(v, 2)),
      markY: [{ y: 0 }],
    });
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

  return card(`${t.label.toUpperCase()} · TREND FOLLOWERS`, rangeSwitch(dates, range, (label) => { range = label; draw(); }), [
    el('div', { class: 'anchor-head' }, [
      el('span', { class: `anchor-value ${STATE_TONE[t.state] === 'up' ? 'up' : STATE_TONE[t.state] === 'down' ? 'down' : ''}`, text: signed(t.score, 2) }),
      tag(t.state || DASH, STATE_TONE[t.state] || 'dim'),
      el('span', { class: 'dim', text: `close ${num(t.close, 0)} · ${t.as_of}` }),
    ]),
    node,
    el('div', { class: 'table-scroll' }, [flips]),
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
  const node = el('div', { class: 'chart' });
  const today = b.dates.indexOf(b.as_of);
  requestAnimationFrame(() => render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 48, bottom: 44 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, valueFormatter: (v) => (present(v) ? `${num(v, 0)}% of S&P 500 weight` : DASH) },
    xAxis: { ...option.xAxis, data: b.dates },
    yAxis: { ...option.yAxis, min: 0, max: 100, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${v}%` } },
    series: [
      {
        name: 'in blackout (report dates known)', type: 'line', showSymbol: false, step: 'end',
        data: b.share_pct.map((v, i) => (i <= today ? v : null)),
        lineStyle: { width: 1.4, color: p.accent }, areaStyle: { color: p.accent, opacity: 0.12 },
        markLine: { silent: true, symbol: 'none', data: [{ xAxis: b.as_of }, { yAxis: 50 }],
          lineStyle: { color: p.faint, type: 'dashed' }, label: { color: p.dim, fontSize: 9, formatter: (m) => (m.value === 50 ? '50%' : 'today') } },
      },
      {
        name: 'ahead (calendar + projected dates)', type: 'line', showSymbol: false, step: 'end',
        data: b.share_pct.map((v, i) => (i >= today ? v : null)),
        lineStyle: { width: 1.4, color: p.blue, type: 'dashed' }, areaStyle: { color: p.blue, opacity: 0.08 },
      },
    ],
  })));
  const tone = b.now_pct >= 50 ? 'down' : b.now_pct >= 25 ? 'warn' : 'up';
  return el('div', {}, [
    el('div', { class: 'stat-strip' }, [
      stat('IN BLACKOUT NOW', [tag(`${num(b.now_pct, 0)}%`, tone)], 'of S&P 500 weight'),
      stat('PEAK AHEAD', b.peak_pct === null ? DASH : `${num(b.peak_pct, 0)}%`, b.peak_date ? `on ${b.peak_date}` : ''),
      stat('NEXT DATES', `${b.scheduled} scheduled`, `${b.projected} projected · ${b.missing} unknown`),
      stat('WINDOW', `−${b.before_days}d → +${b.after_days}d`, 'around each report'),
    ]),
    card('S&P 500 WEIGHT IN AN ESTIMATED BUYBACK BLACKOUT', el('span', { class: 'dim', text: 'a year back, 60 days ahead' }), [node,
      el('div', { class: 'note-text', text: `Companies usually stop discretionary buybacks from a few weeks before earnings until just after them, so the index loses its steadiest buyer when this share is high. Each member counts from ${b.before_days} days before each report to ${b.after_days} days after, weighted by today's S&P 500 weight. Report dates: past releases from the member's own filings, the next one from the earnings calendar, or projected from its usual gap (${b.projected} names). A convention, not any company's policy: 10b5-1 plans can keep buying through a blackout.` })]),
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
    stat('BUYBACK BLACKOUT', present(data.blackout?.now_pct) ? `${num(data.blackout.now_pct, 0)}%` : DASH, 'of S&P 500 weight, estimated',
      data.blackout?.now_pct >= 50 ? 'down' : ''),
    stat('INSIDER CLUSTERS', data.insiders?.clusters ? String(data.insiders.clusters.length) : DASH,
      data.insiders?.coverage ? `${data.insiders.window_days} days · ${data.insiders.coverage.complete ? 'all filings read' : 'filling in'}` : ''),
  ]));

  root.append(el('h2', { class: 'section-title', text: 'TREND FOLLOWERS' }));
  root.append(el('div', { class: 'grid two' }, data.trend.map(trendCard)));
  root.append(el('h2', { class: 'section-title', text: 'SHORT INTEREST' }));
  root.append(shortSection(si));
  root.append(el('h2', { class: 'section-title', text: 'BUYBACK BLACKOUT' }));
  root.append(blackoutSection(data.blackout));
  root.append(el('h2', { class: 'section-title', text: 'INSIDER BUYING' }));
  root.append(insiderSection(data.insiders));
}
