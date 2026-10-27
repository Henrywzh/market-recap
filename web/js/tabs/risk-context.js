// Descriptive pressure by asset. Context families never become independent votes.
import { el, card, num, tag, gap, DASH } from '../fmt.js';
import { render } from '../charts.js';
import { rangeSwitch, sliceRange, initialRange } from '../risk-range.js';

const finite = Number.isFinite;
const value = (v, suffix = '', digits = 1) => finite(v) ? `${num(v, digits)}${suffix}` : DASH;
const signed = (v, suffix = '') => finite(v) ? `${v > 0 ? '+' : ''}${num(v, 1)}${suffix}` : DASH;
function ord(n) {
  if (!finite(n)) return DASH;
  const r = Math.round(n);
  const t = r % 100;
  return `${r}${t >= 11 && t <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[r % 10] || 'th')}`;
}

function quantile(arr, q) {
  const clean = (arr || []).filter(finite).slice().sort((a, b) => a - b);
  if (!clean.length) return null;
  const pos = (clean.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  return clean[base + 1] !== undefined ? clean[base] + rest * (clean[base + 1] - clean[base]) : clean[base];
}

export function pressureTone(asset, references) {
  const v = asset?.latest?.drawdown_sigma;
  if (asset?.stale || !finite(v)) return 'unknown';
  return v >= references[1] ? 'stress' : v >= references[0] ? 'watch' : 'normal';
}

// Bar colour lines for participation: a reading convention, not a forecast.
export const BREADTH_LINES = { healthy: 60, mixed: 40 };

// The bar's tone from its own percentage: healthy at or above 60, mixed from 40,
// weak below 40. Null when there is no reading.
export function breadthTone(pct) {
  if (!finite(pct)) return null;
  if (pct >= BREADTH_LINES.healthy) return 'healthy';
  if (pct >= BREADTH_LINES.mixed) return 'mixed';
  return 'weak';
}

const BAR_TIP = `Bar colour: ≥${BREADTH_LINES.healthy}% healthy, ${BREADTH_LINES.mixed}–${BREADTH_LINES.healthy}% mixed, <${BREADTH_LINES.mixed}% weak — a reading convention, not a forecast.`;

// A card whose title carries an ⓘ tooltip; card() takes only a plain title.
function tippedCard(title, tip, right, body) {
  const head = el('div', { class: 'card-head' }, [el('span', { class: 'card-title' }, [title, ' ', infoMark(tip)])]);
  if (right) head.append(right);
  return el('div', { class: 'card' }, [head, ...[].concat(body)]);
}

// A method caveat beside a metric's label: a small ⓘ whose tooltip carries the
// words, so the card's visible lines stay numbers and dates.
function infoMark(text) {
  return el('span', { class: 'rc-info', role: 'img', title: text, 'aria-label': text, text: 'ⓘ' });
}

function drawAsset(node, asset, context, range, mode) {
  const h = sliceRange(asset.history.dates, asset.history, range);
  if (!h.dates.length) { node.replaceChildren(gap('No close history for this asset.')); return; }
  const ref1 = context.drawdown_references[0];
  const ref2 = context.drawdown_references[1];
  render(node, (option, p) => ({
    ...option,
    grid: { left: 54, right: 22, top: 20, bottom: 28 },
    legend: mode === 'price' ? { top: 0, textStyle: { color: p.dim, fontSize: 10 } } : undefined,
    visualMap: mode === 'pressure' ? {
      show: false,
      dimension: 1,
      pieces: [
        { gte: -0.5, lte: 0.1, color: p.up },
        { gt: -ref1, lt: -0.5, color: p.text },
        { gt: -ref2, lte: -ref1, color: p.accent },
        { lte: -ref2, color: p.down },
      ],
    } : undefined,
    xAxis: { ...option.xAxis, data: h.dates },
    yAxis: { ...option.yAxis, max: mode === 'pressure' ? 0 : undefined,
      axisLabel: { color: p.dim, formatter: (v) => mode === 'pressure' ? `${num(v, 1)}σ` : num(v, 0) } },
    tooltip: { ...option.tooltip, valueFormatter: (v) => value(v, mode === 'pressure' ? 'σ' : '', 2) },
    series: mode === 'pressure' ? [{
      name: 'Drawdown / prior monthly volatility', type: 'line', showSymbol: false,
      data: h.drawdown_sigma.map((v) => finite(v) ? -v : null),
      lineStyle: { width: 1.9 },
      areaStyle: { opacity: 0.10 },
      markArea: {
        silent: true,
        data: [
          [{ yAxis: 0, itemStyle: { color: p.up, opacity: 0.05 } }, { yAxis: -0.5 }],
          [{ yAxis: -ref1, itemStyle: { color: p.accent, opacity: 0.06 } }, { yAxis: -ref2 }],
          [{ yAxis: -ref2, itemStyle: { color: p.down, opacity: 0.11 } }, { yAxis: -4.0 }],
        ],
      },
      markLine: { symbol: 'none', silent: true,
        data: [
          { yAxis: -ref1, lineStyle: { color: p.accent, type: 'dashed' }, label: { show: true, formatter: `watch -${ref1}σ`, color: p.accent, fontSize: 9, position: 'insideEndTop' } },
          { yAxis: -ref2, lineStyle: { color: p.down, type: 'dashed' }, label: { show: true, formatter: `stress -${ref2}σ`, color: p.down, fontSize: 9, position: 'insideEndTop' } },
        ] },
    }] : [
      { name: asset.short, type: 'line', data: h.close, showSymbol: false, lineStyle: { width: 1.8, color: p.text } },
      ...context.ma_sessions.filter((w) => w !== 50).map((w, i) => ({
        name: `${w}D average`, type: 'line', data: h[`ma${w}`], showSymbol: false,
        lineStyle: { width: 1, color: i ? p.blue : p.accent, type: 'dashed' },
      })),
    ],
  }));
}

function participation(context, constituent = false, onSwitch = null) {
  const breadth = constituent ? context.constituent_breadth : context.breadth;
  if (!breadth) return null;
  const counts = breadth.roster.length;
  const main = el('div', { class: 'rc-breadth-bars' });
  const row = (window) => {
    const v = breadth.latest[`above_${window}d_pct`];
    const delta = breadth.latest[`change_${window}d_pp`];
    return el('div', { class: 'rc-breadth-row' }, [
      el('div', { class: 'rc-breadth-label' }, [
        el('strong', { text: `${window}D` }),
        el('span', { class: 'dim', text: window === 20 ? 'Short-term participation' : window === 200 ? 'Long-term participation' : 'Intermediate participation' }),
      ]),
      el('div', { class: `rc-track ${finite(v) ? (v < 50 ? 'below' : 'above') : ''}`, role: 'img', 'aria-label': `${window} day breadth: ${value(v, '%')}` }, [
        finite(v) ? el('span', { class: `rc-fill ${breadthTone(v)}`, style: `width:${Math.max(0, Math.min(100, v))}%` }) : null,
      ]),
      el('span', { class: 'rc-breadth-count' }, [
        el('strong', { class: `rc-breadth-pct ${breadthTone(v) || ''}`, text: value(v, '%', 0) }),
        el('span', { class: 'rc-note', text: finite(v) ? `${Math.round(breadth.latest[`above_${window}d_count`] ?? v * counts / 100)} / ${Math.round(breadth.latest[`eligible_${window}d`] ?? counts)}` : DASH }),
      ]),
      el('span', { class: `rc-note ${finite(delta) ? (delta < 0 ? 'down' : delta > 0 ? 'up' : '') : ''}`, text: `${signed(delta, ' pp')} / 1W${constituent ? ` · coverage ${breadth.latest[`eligible_${window}d`] ?? 0}/${counts}` : ''}` }),
    ]);
  };
  main.append(row(20), row(200));
  const chart = el('div', { class: 'chart rc-breadth-chart' });
  let range = initialRange(breadth.history.dates, '6M');
  let include50 = false;
  const draw = () => {
    const h = sliceRange(breadth.history.dates, breadth.history, range);
    render(chart, (option, p) => ({
      ...option, grid: { left: 40, right: 16, top: 8, bottom: 25 },
      xAxis: { ...option.xAxis, data: h.dates },
      yAxis: { ...option.yAxis, min: 0, max: 100, interval: 50,
        axisLabel: { color: p.dim, formatter: '{value}%' } },
      tooltip: { ...option.tooltip, valueFormatter: (v) => value(v, '%', 0) },
      series: [20, ...(include50 ? [50] : []), 200].map((w, idx) => ({
        name: `${w}D participation`, type: 'line', data: h[`above_${w}d_pct`], step: 'end', showSymbol: false,
        // Neutral colours; style tells 20D (solid) from 200D (dashed) apart.
        lineStyle: w === 20 ? { width: 1.8, color: p.text, type: 'solid' }
          : w === 200 ? { width: 1.6, color: p.dim, type: 'dashed' }
            : { width: 1, color: p.faint, type: 'dashed' },
        markArea: idx === 0 ? {
          silent: true,
          data: [
            [{ yAxis: 70, itemStyle: { color: p.up, opacity: 0.05 } }, { yAxis: 100 }],
            [{ yAxis: 0, itemStyle: { color: p.down, opacity: 0.08 } }, { yAxis: 50 }],
          ],
        } : undefined,
        markLine: idx === 0 ? {
          silent: true, symbol: 'none',
          data: [{ yAxis: 50, lineStyle: { color: p.dim, type: 'dashed', opacity: 0.8 }, label: { show: true, formatter: '50%', color: p.dim, fontSize: 9, position: 'insideEndTop' } }],
        } : undefined,
      })),
    }));
  };
  const more = el('details', { class: 'rc-method' }, [el('summary', { text: constituent ? '50D detail' : '50D & sector-by-sector detail' }), row(50)]);
  more.append(el('div', { class: 'rc-sector-grid' }, breadth.members.map((m) => el('div', { class: 'rc-sector' }, [
    el('strong', { text: m.symbol }),
    ...context.ma_sessions.map((w) => {
      const v = m.above[String(w)];
      return el('span', { class: `rc-sector-state ${v === null ? 'unknown' : v ? 'above' : 'below'}`,
        title: `${m.symbol}: ${v === null ? 'unknown' : v ? 'above' : 'below'} its ${w}D average`,
        text: `${w}D ${v === null ? DASH : v ? '↑' : '↓'}` });
    }),
  ]))));
  requestAnimationFrame(draw);
  return tippedCard(constituent ? `${breadth.label.toUpperCase()} · CONSTITUENT BREADTH` : 'INDUSTRY PARTICIPATION', BAR_TIP, tag(constituent ? 'EQUAL COUNT · CURRENT ROSTER' : 'SHARED CONTEXT', 'dim'), [
    onSwitch ? el('div', { class: 'period-switch', role: 'group', 'aria-label': 'Breadth universe' }, [
      el('button', { type: 'button', text: 'S&P 500 STOCKS', 'aria-pressed': String(constituent), onclick: () => onSwitch(true) }),
      el('button', { type: 'button', text: 'SECTOR ETFs', 'aria-pressed': String(!constituent), onclick: () => onSwitch(false) }),
    ]) : null,
    main,
    el('div', { class: 'rc-chart-tools' }, [
      el('span', { class: 'rc-chart-key' }, [
        el('span', { class: 'rc-key-short', text: '━━ 20D solid' }), ' · ',
        el('span', { class: 'rc-key-long', text: '╍╍ 200D dashed' }),
      ]),
      el('label', { class: 'rc-note' }, [el('input', { type: 'checkbox', onchange: (e) => { include50 = e.target.checked; draw(); } }), ' Show 50D']),
      rangeSwitch(breadth.history.dates, range, (r) => { range = r; draw(); }),
    ]),
    chart, more,
    el('details', { class: 'rc-method' }, [el('summary', { text: 'Breadth · notes & coverage' }), el('p', { class: 'rc-note', text: `${constituent ? `Share of ${counts} current members above their own average; coverage is shown by window.` : `${counts} sector ETFs above their own average.`} ${breadth.note} As of ${breadth.date || DASH}. Low short-term participation alone does not establish that a pullback is ending.` })]),
  ]);
}

function liquiditySection(liq) {
  if (!liq) return null;
  const amihud = liq.amihud || {};
  const conc = liq.concentration || {};
  const bo = liq.blackout || {};
  const hf = liq.hedge_funds || {};
  const si = liq.shorts_insiders || {};
  const tiles = [
    {
      key: 'amihud',
      label: 'ILLIQUIDITY PROXY · AMIHUD 20D',
      info: 'Daily return / turnover proxy; not measured order-book depth',
      badge: 'LOWER = BETTER',
      badgeTone: 'dim',
      val: value(amihud.value, ' %/$1B', 2),
      tone: finite(amihud.pct_1y) && amihud.pct_1y >= 80 ? 'stress' : finite(amihud.pct_1y) && amihud.pct_1y <= 35 ? 'good' : '',
      sub: `1Y ${ord(amihud.pct_1y)} · 10Y ${ord(amihud.pct_10y)} · 1W ${signed(amihud.change_1w)}`,
    },
    {
      key: 'concentration',
      label: 'TOP 10 $ VOLUME SHARE',
      badge: 'LOWER = BROADER',
      badgeTone: 'dim',
      val: value(conc.value, '%', 1),
      tone: finite(conc.pct_1y) && conc.pct_1y >= 80 ? 'stress' : finite(conc.pct_1y) && conc.pct_1y <= 35 ? 'good' : '',
      sub: `1Y ${ord(conc.pct_1y)} · 10Y ${ord(conc.pct_10y)} · 1W ${signed(conc.change_1w, ' pp')}`,
      foot: `$${value(conc.total_dvol_bn_20d, 'B', 0)}/day · High = crowded in top 10`,
    },
    {
      key: 'blackout',
      label: 'BUYBACK BLACKOUT SHARE',
      // A calendar estimate, not a risk reading: neutral colour throughout.
      info: 'Estimated earnings window; does not measure actual buybacks',
      badge: 'ESTIMATED WINDOW',
      badgeTone: 'dim',
      val: value(bo.now_pct, '%', 1),
      tone: '',
      sub: `7D ${signed(bo.change_7d_pp, ' pp')} · next 7D ${signed(bo.ahead_7d_pp, ' pp')}`,
    },
    {
      key: 'hedge_funds',
      label: 'CFTC LEVERAGED FUNDS · ES / NQ',
      badge: 'POSITIONING CONTEXT',
      badgeTone: (finite(hf.nq?.pct_1y) && hf.nq.pct_1y >= 85) ? 'warn' : 'dim',
      val: `${signed(hf.es?.value, '%')} / ${signed(hf.nq?.value, '%')}`,
      tone: '',
      sub: `ES 1Y ${ord(hf.es?.pct_1y)} · NQ 1Y ${ord(hf.nq?.pct_1y)}`,
      info: 'Futures only; may include hedges / basis trades.',
      foot: `ES = S&P 500 · NQ = Nasdaq-100 · ${hf.es?.date || DASH}`,
    },
    {
      key: 'shorts_insiders',
      label: 'SHORT INTEREST & INSIDERS',
      badge: 'DATED POSITIONING',
      badgeTone: 'dim',
      val: `${value(si.median_days_to_cover, 'd DTC', 2)}`,
      tone: '',
      sub: `Short $${value(si.short_value_bn, 'B', 0)} (${signed(si.short_value_change_bn, 'B')}) · ${si.insider_clusters ?? DASH} clusters (insiders through ${si.insider_read_through || DASH})`,
      info: 'No direction signal.',
      foot: `FINRA ${si.settlement_date || DASH} · DTC = short shares / average daily volume`,
    },
  ];

  let picked = 'blackout';
  const grid = el('div', { class: 'rc-liq-grid' });
  const chartTitle = el('span', { class: 'rc-chart-key' });
  const chartNote = el('p', { class: 'rc-note' });
  const chartNode = el('div', { class: 'chart rc-breadth-chart' });

  const draw = () => {
    grid.replaceChildren(...[...tiles].sort((a, b) => Number(b.key === 'blackout') - Number(a.key === 'blackout')).map((t) => el('button', {
      type: 'button',
      class: `rc-asset ${t.tone}`,
      'aria-pressed': String(t.key === picked),
      onclick: () => { picked = t.key; draw(); },
    }, [
      el('span', { class: 'rc-asset-head' }, [
        el('span', { class: 'rc-label-row' }, [el('span', { class: 'rc-eyebrow', text: t.label }), t.info ? infoMark(t.info) : null]),
        tag(t.badge, t.badgeTone),
      ]),
      el('strong', { class: 'rc-asset-dd', text: t.val }),
      el('span', { class: 'rc-note', text: t.sub }),
      t.foot ? el('span', { class: 'rc-note', text: t.foot }) : null,
    ])));

    if (picked === 'amihud' || picked === 'concentration') {
      const full = liq.micro_history || { dates: [] };
      const mh = sliceRange(full.dates, full);
      const isAmihud = picked === 'amihud';
      const seriesData = isAmihud ? mh.amihud_20d : mh.top10_share_20d;
      const qLow = quantile(seriesData, 0.30);
      const qHigh = quantile(seriesData, 0.80);
      chartTitle.textContent = isAmihud
        ? 'AMIHUD ILLIQUIDITY · LOW / HIGH DAILY ILLIQUIDITY PROXY · DISPLAY-HISTORY PERCENTILES'
        : 'TOP 10 $ VOLUME SHARE · GREEN = BROAD TRADING (≤30TH PCT) · RED = CROWDED IN MEGA-CAPS (≥80TH PCT)';
      chartNote.textContent = isAmihud ? amihud.note : conc.note;
      render(chartNode, (option, p) => ({
        ...option, grid: { left: 48, right: 18, top: 14, bottom: 26 },
        visualMap: finite(qLow) && finite(qHigh) ? {
          show: false,
          dimension: 1,
          pieces: [
            { lte: qLow, color: p.up },
            { gt: qLow, lt: qHigh, color: p.text },
            { gte: qHigh, color: p.down },
          ],
        } : undefined,
        xAxis: { ...option.xAxis, data: mh.dates },
        yAxis: { ...option.yAxis, axisLabel: { color: p.dim, formatter: (v) => isAmihud ? `${num(v, 1)}%` : `${num(v, 0)}%` } },
        series: [{
          name: isAmihud ? 'Amihud 20D' : 'Top 10 share', type: 'line', showSymbol: false,
          data: seriesData, lineStyle: { width: 1.9 },
          areaStyle: { opacity: 0.08 },
          markArea: finite(qLow) && finite(qHigh) ? {
            silent: true,
            data: [
              [{ yAxis: 0, itemStyle: { color: p.up, opacity: 0.05 } }, { yAxis: qLow }],
              [{ yAxis: qHigh, itemStyle: { color: p.down, opacity: 0.09 } }, { yAxis: Math.max(...seriesData.filter(finite)) * 1.05 }],
            ],
          } : undefined,
          markLine: finite(qLow) && finite(qHigh) ? {
            silent: true, symbol: 'none',
            data: [
              { yAxis: qLow, lineStyle: { color: p.up, type: 'dashed', opacity: 0.6 }, label: { show: true, formatter: `abundant ${num(qLow, isAmihud ? 2 : 1)}%`, color: p.up, fontSize: 9, position: 'insideEndTop' } },
              { yAxis: qHigh, lineStyle: { color: p.down, type: 'dashed', opacity: 0.7 }, label: { show: true, formatter: `stressed ${num(qHigh, isAmihud ? 2 : 1)}%`, color: p.down, fontSize: 9, position: 'insideEndTop' } },
            ],
          } : undefined,
        }],
      }));
    } else if (picked === 'blackout') {
      const bh = sliceRange(bo.dates || [], { shares: bo.share_pct || [] }, null, { future: true });
      const dates = bh.dates;
      const shares = bh.shares;
      const asOf = bo.as_of;
      const past = shares.map((v, i) => dates[i] <= asOf ? v : null);
      const ahead = shares.map((v, i) => dates[i] >= asOf ? v : null);
      chartTitle.textContent = `BUYBACK BLACKOUT · ESTIMATED SHARE · COLOR BANDS ARE DESCRIPTIVE · DASHED = NEXT 60D`;
      chartNote.textContent = bo.note || '';
      render(chartNode, (option, p) => ({
        ...option, grid: { left: 46, right: 18, top: 14, bottom: 26 },
        visualMap: {
          show: false,
          dimension: 1,
          seriesIndex: 0,
          pieces: [
            { lte: 25, color: p.up },
            { gt: 25, lt: 50, color: p.accent },
            { gte: 50, color: p.down },
          ],
        },
        xAxis: { ...option.xAxis, data: dates },
        yAxis: { ...option.yAxis, min: 0, max: 100, axisLabel: { color: p.dim, formatter: '{value}%' } },
        series: [
          {
            name: 'Estimated blackout %', type: 'line', data: past, showSymbol: false,
            lineStyle: { width: 1.9 }, areaStyle: { opacity: 0.10 },
            markArea: {
              silent: true,
              data: [
                [{ yAxis: 0, itemStyle: { color: p.up, opacity: 0.05 } }, { yAxis: 25 }],
                [{ yAxis: 50, itemStyle: { color: p.down, opacity: 0.09 } }, { yAxis: 100 }],
              ],
            },
            markLine: {
              silent: true, symbol: 'none',
              data: [
                { yAxis: 25, lineStyle: { color: p.up, type: 'dashed', opacity: 0.6 }, label: { show: true, formatter: '25% reference', color: p.up, fontSize: 9, position: 'insideEndTop' } },
                { yAxis: 50, lineStyle: { color: p.down, type: 'dashed', opacity: 0.7 }, label: { show: true, formatter: '50% reference', color: p.down, fontSize: 9, position: 'insideEndTop' } },
              ],
            },
          },
          { name: 'Scheduled / projected %', type: 'line', data: ahead, showSymbol: false, lineStyle: { width: 1.6, color: p.text, type: 'dashed' } },
        ],
      }));
    } else if (picked === 'hedge_funds') {
      const raw = hf.es?.history || { dates: [], values: [] };
      const esH = sliceRange(raw.dates, raw);
      const nqMap = new Map((hf.nq?.history?.dates || []).map((d, i) => [d, hf.nq.history.values[i]]));
      chartTitle.textContent = 'CFTC · (LONG − SHORT) / OPEN INTEREST · ES: S&P 500 · NQ: NASDAQ-100';
      chartNote.textContent = hf.note || '';
      render(chartNode, (option, p) => ({
        ...option, grid: { left: 46, right: 18, top: 20, bottom: 26 },
        legend: { top: 0, textStyle: { color: p.dim, fontSize: 10 } },
        xAxis: { ...option.xAxis, data: esH.dates },
        yAxis: { ...option.yAxis, axisLabel: { color: p.dim, formatter: (v) => `${num(v, 0)}%` } },
        series: [
          {
            name: 'S&P 500 (ES)', type: 'line', data: esH.values, showSymbol: false, lineStyle: { width: 1.7, color: p.accent },
            markLine: { silent: true, symbol: 'none', data: [{ yAxis: 0, lineStyle: { color: p.faint, type: 'dashed' }, label: { show: false } }] },
          },
          { name: 'Nasdaq-100 (NQ)', type: 'line', data: esH.dates.map((d) => nqMap.get(d) ?? null), showSymbol: false, lineStyle: { width: 1.6, color: p.blue } },
        ],
      }));
    } else {
      const rounds = sliceRange((si.rounds || []).map((r) => r.date), { rows: si.rounds || [] }).rows;
      const dtc = rounds.map((r) => r.median_days_to_cover);
      chartTitle.textContent = 'SHORT INTEREST · MEDIAN DAYS TO COVER & TOTAL SHORT VALUE · NOT A BUY / SELL SIGNAL';
      chartNote.textContent = `${si.note || ''} Insider coverage ends ${si.insider_read_through || DASH}; not current buying. A higher DTC can reflect more shorts or lower trading volume, and does not guarantee a squeeze. Short-value changes also reflect stock-price changes.`;
      render(chartNode, (option, p) => ({
        ...option, grid: { left: 46, right: 52, top: 20, bottom: 26 },
        legend: { top: 0, textStyle: { color: p.dim, fontSize: 10 } },
        xAxis: { ...option.xAxis, data: rounds.map((r) => r.date) },
        yAxis: [
          { ...option.yAxis, axisLabel: { color: p.dim, formatter: (v) => `${num(v, 1)}d` } },
          { ...option.yAxis, position: 'right', splitLine: { show: false }, axisLabel: { color: p.dim, formatter: (v) => `$${num(v, 0)}B` } },
        ],
        series: [
          {
            name: 'Median days to cover', type: 'line', yAxisIndex: 0, data: dtc, showSymbol: true, symbolSize: 4, lineStyle: { width: 1.9 },
          },
          { name: 'Total short value ($B)', type: 'line', yAxisIndex: 1, data: rounds.map((r) => r.short_value_bn), showSymbol: false, lineStyle: { width: 1.4, color: p.blue, type: 'dashed' } },
        ],
      }));
    }
  };
  requestAnimationFrame(draw);
  return card('EQUITIES LIQUIDITY & POSITIONING', tag('MICROSTRUCTURE · BUYBACKS · POSITIONING', 'dim'), [
    el('p', { class: 'rc-intro', text: 'Equities-only liquidity and positioning (excluding ETF flows): daily illiquidity proxy, volume concentration, estimated buyback window, leveraged-fund futures and short interest. These describe different channels; positioning has no simple good/bad direction. Click any card to inspect its history.' }),
    grid,
    el('div', { class: 'rc-chart-tools' }, [chartTitle, rangeSwitch([], null, draw)]),
    chartNode,
    chartNote,
  ]);
}

export default function assetContext(context) {
  if (!context?.assets?.length) return gap('Asset context was not built for this session.');
  const holder = el('div', { class: 'risk-context' });
  const menu = el('div', { class: 'rc-assets', role: 'group', 'aria-label': 'Select risk asset' });
  const stats = el('div', { class: 'rc-ma-row' });
  const explanation = el('p', { class: 'rc-reading' });
  const title = el('strong', { class: 'rc-selected-label' });
  const date = el('span', { class: 'rc-note' });
  const chart = el('div', { class: 'chart rc-asset-chart' });
  const modes = el('div', { class: 'period-switch', role: 'group', 'aria-label': 'Asset chart mode' });
  const ranges = el('div');
  let selected = context.assets[0];
  let mode = 'pressure';
  let range = initialRange(selected.history.dates, '1Y');
  const draw = () => drawAsset(chart, selected, context, range, mode);
  const buttons = context.assets.map((a) => {
    const tone = pressureTone(a, context.drawdown_references);
    return el('button', { type: 'button', class: `rc-asset ${tone}`, 'aria-label': `Select ${a.short}`,
      onclick: () => { selected = a; update(); } }, [
      el('span', { class: 'rc-asset-head' }, [el('strong', { text: a.short }), el('span', { class: 'rc-note', text: a.stale ? 'DATED INPUT' : a.date })]),
      el('span', { class: 'rc-asset-dd', text: value(a.latest.drawdown_pct, '%') }),
      el('span', { class: 'rc-note', text: `${value(a.latest.drawdown_sigma, 'σ')} from ${context.high_sessions}D high` }),
    ]);
  });
  const update = () => {
    buttons.forEach((b, i) => b.setAttribute('aria-pressed', String(context.assets[i].key === selected.key)));
    const l = selected.latest;
    const tone = pressureTone(selected, context.drawdown_references);
    title.textContent = selected.label;
    date.textContent = `${selected.date || 'No close'} · ${selected.basis}${selected.stale ? ' · behind this artifact session' : ''}`;
    stats.replaceChildren(...context.ma_sessions.map((w) => {
      const v = l[`distance_ma${w}_pct`];
      return el('span', { class: `rc-ma ${finite(v) ? v >= 0 ? 'above' : 'below' : 'unknown'}`,
        text: `${w}D average ${signed(v, '%')}` });
    }));
    explanation.className = `rc-reading ${tone}`;
    explanation.textContent = finite(l.drawdown_sigma)
      ? `${selected.short} is ${value(-l.drawdown_pct, '%')} below its local closing high, or ${value(l.drawdown_sigma, ' monthly σ')}. Compare constituent breadth and the context below to see whether weakness is shared across channels. This reading does not locate a bottom.`
      : `${selected.short} does not have enough dated input for a volatility-scaled reading.`;
    ranges.replaceChildren(rangeSwitch(selected.history.dates, range, (r) => { range = r; draw(); }));
    requestAnimationFrame(draw);
  };
  [['pressure', 'Drawdown in σ'], ['price', 'Close + averages']].forEach(([key, label]) => {
    modes.append(el('button', { type: 'button', 'aria-pressed': String(key === mode), text: label, onclick: () => {
      mode = key; [...modes.children].forEach((b) => b.setAttribute('aria-pressed', String(b.textContent === label))); draw();
    } }));
  });
  menu.append(...buttons);
  const sideBySide = el('div', { class: 'rc-overview-grid' });
  sideBySide.append(card('ASSET PRESSURE', tag('OBSERVED · NOT A FORECAST', 'dim'), [
    menu, el('div', { class: 'rc-selected' }, [title, date]), stats,
    el('div', { class: 'rc-chart-tools' }, [modes, ranges]), chart,
    el('details', { class: 'rc-method' }, [el('summary', { text: 'Drawdown · notes & method' }), explanation, el('p', { class: 'rc-note', text: `σ is a volatility unit, not a score or loss probability. Prior ${context.volatility_sessions} sessions of daily log returns × √${context.scale_sessions}; today’s return is excluded from that scale. Amber ≥${context.drawdown_references[0]}σ; red ≥${context.drawdown_references[1]}σ. These are descriptive reference lines. Price down means pressure for IEF too.` })]),
  ]));
  const breadthSlot = el('div', { class: 'rc-breadth-slot' });
  const chooseBreadth = (constituent) => { const panel = participation(context, constituent, chooseBreadth); if (panel) breadthSlot.replaceChildren(panel); };
  if (context.constituent_breadth) { chooseBreadth(true); sideBySide.append(breadthSlot); }
  holder.append(sideBySide);
  const liquidity = liquiditySection(context.liquidity);
  if (liquidity) holder.append(liquidity);
  // The stocks-vs-bonds card is rendered by the risk page, after this context.
  update();
  return holder;
}
