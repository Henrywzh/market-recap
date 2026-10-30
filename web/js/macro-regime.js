// Descriptive monthly map; each coordinate is for the same reference month.
import { el, card, num, pct, DASH, periodSwitch, table } from './fmt.js';
import { render } from './charts.js';

const finite = (v) => typeof v === 'number' && Number.isFinite(v);
export function regimeName(x, y) {
  if (!finite(x) || !finite(y)) return null;
  if (x === 0 || y === 0) return 'ON THE BOUNDARY';
  return x > 0 ? (y > 0 ? 'REFLATION' : 'GOLDILOCKS') : (y > 0 ? 'STAGFLATION' : 'SLOWDOWN');
}

export function macroSnapshot(overview, regime, gdp, priced, gdpnow = null) {
  const prints = overview?.prints || [];
  const entries = [...(gdp ? [gdp] : []), ...(gdpnow ? [gdpnow] : []), ...prints];
  if (regime?.latest) entries.push({ label: 'Chicago Fed activity · matched month', value: regime.latest.growth,
    unit: 'index', period: regime.latest.month });
  const upper = (priced?.anchors || []).find((row) => row.key === 'DFEDTARU');
  if (upper) entries.push({ label: 'Fed target upper', value: upper.value, unit: '%', period: upper.date });
  const tiles = entries.map((p) => el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: p.label }),
    el('div', { class: 'stat-value', text: finite(p.value) ? `${num(p.value, p.unit?.startsWith('k') ? 0 : 2)} ${p.unit || ''}` : DASH }),
    el('div', { class: 'stat-note', text: `${p.period || 'date unavailable'}${finite(p.prior) ? ` · prior ${num(p.prior, 2)}` : ''}` }),
  ]));
  return card('MACRO SNAPSHOT', null, tiles.length ? [el('div', { class: 'stat-strip' }, tiles),
    el('div', { class: 'note-text', text: `Sources: OVERVIEW (${overview?.as_of || 'date unavailable'}), FRED/BEA and PRICED PATH. Each tile shows its reference period; GDPNow is a nowcast.` })]
    : [el('div', { class: 'gap', text: 'Macro snapshot unavailable in this build.' })]);
}

const OFFICIAL = 'OFFICIAL · REVISED';
const REALTIME = 'REAL-TIME · AS KNOWN THEN';

// Both views on one footing: official points are the revised monthly figures with
// the nowcast past them; real-time points are each month as read at the time.
export function regimeViews(regime, now, realtime) {
  const ok = (p) => finite(p.growth) && finite(p.inflation_change_pp);
  const official = (regime?.points || []).filter(ok);
  const officialNow = (now?.points || []).filter(ok);
  const rt = (realtime?.points || []).filter(ok);
  return {
    official: { points: official, now: officialNow },
    realtime: { points: rt.filter((p) => p.source !== 'ledger'), now: rt.filter((p) => p.source === 'ledger') },
  };
}

// Months both views cover, and how many land in the same quadrant.
export function regimeAgreement(views) {
  const real = new Map([...views.realtime.points, ...views.realtime.now].map((p) => [p.month, regimeName(p.growth, p.inflation_change_pp)]));
  const both = views.official.points.filter((p) => real.has(p.month));
  return { months: both.length, same: both.filter((p) => regimeName(p.growth, p.inflation_change_pp) === real.get(p.month)).length };
}

function drawRegimeMap(node, points, nowPoints, mode) {
  const latest = points.at(-1);
  const all = [...points, ...nowPoints];
  const x = Math.max(.2, ...all.map((p) => Math.abs(p.growth))) * 1.18;
  const y = Math.max(.1, ...all.map((p) => Math.abs(p.inflation_change_pp))) * 1.18;
  const quadrant = (x0, y0, x1, y1, name, color) => [{ name, xAxis: x0, yAxis: y0, itemStyle: { color }, label: { position: x0 < 0 ? (y0 < 0 ? 'insideBottomLeft' : 'insideTopLeft') : (y0 < 0 ? 'insideBottomRight' : 'insideTopRight') } }, { xAxis: x1, yAxis: y1 }];
  const pointTip = (d) => (mode === REALTIME
    ? `${d.month} · as known ${d.known || DASH}${d.source === 'ledger' ? ' · nowcast, still moving' : ''}<br>Growth: ${num(d.growth, 3)} (${d.basis === 'ads_raw' ? 'ADS, raw' : 'ADS mapped to CFNAI'})<br>Core PCE YoY change: ${num(d.inflation_change_pp, 2)} pp<br>${regimeName(d.growth, d.inflation_change_pp)}`
    : `${d.month}<br>CFNAI 3M: ${num(d.growth, 3)}<br>Core PCE YoY change: ${num(d.inflation_change_pp, 2)} pp<br>Core PCE YoY: ${pct(d.inflation_yoy, 2)}`);
  requestAnimationFrame(() => render(node, (o, p) => ({
    ...o,
    grid: { ...o.grid, left: 60, right: 38, top: 32, bottom: 56 },
    xAxis: { ...o.xAxis, type: 'value', min: -x, max: x, name: mode === REALTIME ? 'Growth as known · ADS on the CFNAI scale' : 'CFNAI 3M · above / below trend', nameLocation: 'middle', nameGap: 32, nameTextStyle: { color: p.dim }, axisLabel: { ...o.xAxis.axisLabel, showMinLabel: false, showMaxLabel: false } },
    yAxis: { ...o.yAxis, type: 'value', min: -y, max: y, name: 'Core PCE YoY change · pp / 3M', nameLocation: 'middle', nameGap: 45, nameTextStyle: { color: p.dim }, axisLabel: { ...o.yAxis.axisLabel, showMinLabel: false, showMaxLabel: false, formatter: (v) => num(v, 2) } },
    tooltip: { ...o.tooltip, trigger: 'item', formatter: (v) => (v.data?.now && mode === OFFICIAL ? nowTooltip(v.data.now) : pointTip(v.data?.point || {})) },
    series: [{ type: 'scatter', data: [], silent: true,
      markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: p.faint, width: 1 }, data: [{ xAxis: 0 }, { yAxis: 0 }] },
      markArea: { silent: true, label: { show: true, color: p.dim, fontSize: 10 }, data: [
        quadrant(-x, 0, 0, y, 'STAGFLATION', 'rgba(197,60,60,.12)'),
        quadrant(0, 0, x, y, 'REFLATION', 'rgba(213,146,46,.10)'),
        quadrant(-x, -y, 0, 0, 'SLOWDOWN', 'rgba(65,105,160,.12)'),
        quadrant(0, -y, x, 0, 'GOLDILOCKS', 'rgba(39,154,113,.12)'),
      ] },
    }, ...points.slice(1).flatMap((v, i) => {
      const prev = points[i];
      // Do not connect across a missing reference month.
      const monthIndex = (m) => Number(m.slice(0, 4)) * 12 + Number(m.slice(5, 7));
      if (monthIndex(v.month) - monthIndex(prev.month) !== 1) return [];
      const recent = i >= points.length - 4;
      return [{ type: 'line', silent: true, symbol: 'none', z: 3,
        data: [[prev.growth, prev.inflation_change_pp], [v.growth, v.inflation_change_pp]],
        lineStyle: { color: p.accent, width: recent ? 2.5 : 1.5, opacity: .18 + .8 * (i + 1) / points.length },
        ...(recent && (v.growth !== prev.growth || v.inflation_change_pp !== prev.inflation_change_pp) ? {
          markLine: { silent: true, symbol: ['none', 'arrow'], symbolSize: 7,
            label: { show: false }, lineStyle: { color: p.accent, width: 2, type: 'solid' },
            data: [[{ coord: [prev.growth, prev.inflation_change_pp] }, { coord: [v.growth, v.inflation_change_pp] }]] },
        } : {}),
      }];
    }), { type: 'scatter', z: 5, symbol: 'circle',
      data: points.map((v, i) => ({ value: [v.growth, v.inflation_change_pp], point: v,
        symbolSize: i === points.length - 1 ? 15 : i === 0 ? 7 : 5,
        itemStyle: { color: p.accent, opacity: .3 + .7 * (i + 1) / points.length,
          borderColor: i === points.length - 1 ? p.text : p.panel, borderWidth: i === points.length - 1 ? 2 : 1 },
        label: { show: i === 0 || i === points.length - 1,
          formatter: `${i === points.length - 1 ? (mode === REALTIME ? 'MONTH-END READ · ' : 'LATEST · ') : ''}${v.month}`,
          position: i === points.length - 1 ? 'bottom' : 'left', distance: 10, color: p.text,
          fontWeight: i === points.length - 1 ? 'bold' : 'normal', fontSize: 10 },
      })),
    }, ...(nowPoints.length && latest ? [{ type: 'line', silent: true, symbol: 'none', z: 4,
      data: [[latest.growth, latest.inflation_change_pp], ...nowPoints.map((v) => [v.growth, v.inflation_change_pp])],
      lineStyle: { color: p.text, width: 1.5, type: 'dashed', opacity: .8 } },
    { type: 'scatter', z: 6, symbol: 'emptyCircle', symbolSize: 14,
      data: nowPoints.map((v, i) => ({ value: [v.growth, v.inflation_change_pp], now: v, point: v,
        itemStyle: { color: p.panel, borderColor: p.text, borderWidth: 2 },
        label: { show: i === nowPoints.length - 1, formatter: `NOW · ${v.month}`, position: 'top', distance: 8,
          color: p.text, fontWeight: 'bold', fontSize: 10 } })) }] : [])],
  })));
}

// opts.title: the card title; opts.compact: leave out the method fold and source links.
export function macroRegimeCard(regime, now = null, realtime = null, opts = {}) {
  const views = regimeViews(regime, now, realtime);
  const latest = views.official.points.at(-1);
  const title = opts.title || 'GROWTH / INFLATION MAP · LAST 12 MATCHED MONTHS';
  if (!latest) return card(title, null, [el('div', { class: 'gap', text: 'No matching monthly CFNAI and core PCE observations in this build.' })]);
  const hasRealtime = views.realtime.points.length > 0;
  const node = el('div', { class: 'chart', style: 'height:360px', 'aria-label': 'Growth and inflation regime map' });
  const key = el('div', { class: 'macro-trace-key' });
  const notes = el('div', {});
  const agree = regimeAgreement(views);
  const nowLast = views.official.now.at(-1);
  const officialFor = (month) => { const o = views.official.points.find((q) => q.month === month); return o ? regimeName(o.growth, o.inflation_change_pp) : null; };
  const draw = (mode) => {
    const view = mode === REALTIME ? views.realtime : views.official;
    drawRegimeMap(node, view.points, view.now, mode);
    if (mode === REALTIME) {
      const last = view.points.at(-1); const live = view.now.at(-1);
      key.textContent = `FADED → RECENT · each month as read the first business day after it, before revisions · outlined dot = latest month-end read${live ? ' · dashed ring = this month so far' : ''}`;
      notes.replaceChildren(
        live ? el('div', { class: 'note-text' }, [el('strong', { text: `NOW · ${live.month} · ${regimeName(live.growth, live.inflation_change_pp)}` }), ` · read ${live.known}, still moving until the month ends.`]) : null,
        last ? el('div', { class: 'note-text' }, [el('strong', { text: `${last.month} · ${regimeName(last.growth, last.inflation_change_pp)}` }),
          ` as read on ${last.known}${officialFor(last.month) ? ` · official (revised) data now say ${officialFor(last.month)}` : ''}.`]) : null,
        agree.months ? el('div', { class: 'note-text', text: `Official and real-time agree on ${agree.months ? `${agree.same} of ${agree.months}` : DASH} months shown. The gap is revisions and the nowcast's error: real-time is what a reader could have known, official is what later data says happened.` }) : null,
        el('div', { class: 'note-text', text: 'Growth: the Philadelphia Fed ADS index\'s 3-month average on that day, mapped onto CFNAI-MA3 by a fit on CFNAI already published then (raw ADS before 2016). Inflation: the Cleveland Fed core PCE YoY nowcast minus the official YoY three months earlier, as published then. config/regime_quadrant_history.json, then this page\'s nowcast ledger.' }));
    } else {
      key.textContent = `FADED → RECENT · arrows show the last 3 monthly moves · outlined dot = latest official${nowLast ? ' · dashed ring = NOW (nowcast)' : ''}`;
      notes.replaceChildren(
        nowLast ? el('div', { class: 'note-text' }, [el('strong', { text: `NOW · ${nowLast.month} · ${regimeName(nowLast.growth, nowLast.inflation_change_pp)}` }),
          ` · growth ${num(nowLast.growth, 3)} (${nowLast.growth_source === 'ads' ? `ADS through ${now.ads_through}, mapped to CFNAI` : 'official CFNAI'}), core PCE YoY ${pct(nowLast.inflation_yoy, 2)} (${nowLast.inflation_source === 'cleveland' ? `Cleveland Fed nowcast, ${nowLast.inflation_asof}` : 'official'}), change ${num(nowLast.inflation_change_pp, 2)} pp. A real-time estimate, not a print; it moves until the official month arrives.`]) : null,
        el('div', { class: 'note-text', text: `${latest.month} · ${regimeName(latest.growth, latest.inflation_change_pp)} · growth ${num(latest.growth, 3)}, core PCE YoY ${pct(latest.inflation_yoy, 2)}, change ${num(latest.inflation_change_pp, 2)} pp over ${regime.change_months} months.` }),
        el('div', { class: 'note-text', text: 'Above/below historical trend is CFNAI’s zero line; inflation direction is the change in core PCE YoY, not its absolute level. Reference months are paired, not release dates. Revised current-vintage data; descriptive, not a trading signal.' }));
    }
  };
  const tools = hasRealtime ? periodSwitch([OFFICIAL, REALTIME], OFFICIAL, draw) : null;
  draw(OFFICIAL);
  return card(title, tools, [key, node, notes,
    opts.compact ? (opts.link || null) : el('div', { class: 'field-note' }, [el('a', { href: 'https://fred.stlouisfed.org/series/CFNAIMA3', text: 'Chicago Fed CFNAI 3M ↗' }), ' · ', el('a', { href: 'https://fred.stlouisfed.org/series/PCEPILFE', text: 'BEA core PCE via FRED ↗' }),
      ...(now?.sources ? [' · ', el('a', { href: now.sources.cleveland, text: 'Federal Reserve Bank of Cleveland inflation nowcasting ↗' }), ' · ', el('a', { href: now.sources.ads, text: 'Federal Reserve Bank of Philadelphia ADS index ↗' })] : [])]),
    !opts.compact && now ? nowcastFold(now) : null,
  ]);
}

function nowTooltip(v) {
  return `NOW · ${v.month} · nowcast<br>Growth: ${num(v.growth, 3)} ${v.growth_source === 'ads' ? `(ADS 3M ${num(v.ads_3m, 3)}, ${v.ads_days} days of ${v.month}, mapped to CFNAI)` : '(official CFNAI)'}`
    + `<br>Core PCE YoY: ${pct(v.inflation_yoy, 2)} ${v.inflation_source === 'cleveland' ? `(Cleveland nowcast, ${v.inflation_asof})` : '(official)'}`
    + `<br>3M change: ${num(v.inflation_change_pp, 2)} pp`;
}

const share = (v) => (finite(v) ? `${num(v * 100, 1)}%` : DASH);
const cells = (values) => el('tr', {}, values.map((v) => el('td', { class: 'wrap-cell', text: v ?? DASH })));

// The nowcast's own record on this page (one row per month, its last reading
// before the official month), then the archived real-time comparison that chose it.
export function nowcastLedgerRows(ledger) {
  const byMonth = new Map();
  for (const row of ledger || []) byMonth.set(row.month, row);       // ledger is date-ordered: the last row wins
  return [...byMonth.values()].reverse();
}

function nowcastFold(now) {
  const months = nowcastLedgerRows(now.ledger);
  const scored = months.filter((r) => r.actual_quadrant);
  const hits = scored.filter((r) => r.quadrant === r.actual_quadrant).length;
  const ev = now.evaluation;
  const evalTable = (block, headers, row) => (block?.rows?.length ? [el('div', { class: 'card-title', text: block.target }),
    table(headers, block.rows.map((r) => cells(row(r))))] : []);
  const cal = now.calibration;
  return el('details', { class: 'method-fold' }, [
    el('summary', { text: 'ⓘ NOWCAST · METHOD & TRACK RECORD' }),
    el('div', { class: 'method-copy', text: `Growth: ADS 3-month average (Philadelphia Fed, through ${now.ads_through || DASH}) mapped onto CFNAI-MA3`
      + (cal ? ` by ${num(cal.intercept, 3)} + ${num(cal.slope, 3)} × ADS (${cal.months} months ${cal.from}–${cal.to}, ex-2020/21, r ${num(cal.corr, 2)})` : '')
      + `. Inflation: Cleveland Fed core PCE YoY nowcast (through ${now.cleveland_through || DASH}); its change is against the official print three months earlier. Where an official month exists it replaces the nowcast on that axis.` }),
    el('div', { class: 'card-title', text: `THIS PAGE'S RECORD · ${scored.length ? `${hits} of ${scored.length} quadrants right` : 'no month scored yet'}` }),
    months.length ? table(['MONTH', 'LAST READ', 'NOWCAST', 'OFFICIAL (FIRST SEEN)', 'RIGHT?'], months.slice(0, 12).map((r) => cells([
      r.month, r.date, `${r.quadrant || DASH} · ${num(r.growth, 2)}, ${num(r.inflation_change_pp, 2)} pp`,
      r.actual_quadrant || 'pending', r.actual_quadrant ? (r.actual_quadrant === r.quadrant ? 'YES' : 'NO') : DASH])))
      : el('div', { class: 'gap', text: 'The ledger starts with this build.' }),
    ...(ev ? [
      el('div', { class: 'card-title', text: `ARCHIVED REAL-TIME COMPARISON · ${ev.as_of}` }),
      el('div', { class: 'method-copy', text: ev.method }),
      ...evalTable(ev.inflation_direction, ['CANDIDATE', 'N', 'MAE PP', 'DIRECTION', 'WHEN > 0.1PP'],
        (r) => [r.candidate, String(r.n), num(r.mae, 3), share(r.sign_hit), share(r.sign_hit_clear)]),
      ...evalTable(ev.growth, ['CANDIDATE', 'N', 'FROM', 'CORR', 'SIGN', 'WHEN CLEAR'],
        (r) => [r.candidate, String(r.n), r.from, num(r.corr, 2), share(r.sign_hit), share(r.sign_hit_clear)]),
      ...evalTable(ev.quadrant, ['CANDIDATE', 'QUADRANT RIGHT'], (r) => [r.candidate, share(r.hit)]),
      ...evalTable(ev.gdp, ['CANDIDATE', 'N', 'MAE PP', 'CORR', 'ABOVE / BELOW TREND'],
        (r) => [r.candidate, String(r.n), num(r.mae_pp, 2), num(r.corr, 2), share(r.above_trend_hit)]),
      el('div', { class: 'method-copy', text: ev.market }),
      el('div', { class: 'method-copy', text: ev.decision }),
    ] : []),
  ]);
}

// Source importance is retained, including its measured/judged provenance.
// ``days`` keeps events within that many calendar days of the snapshot.
export function macroCalendarEvents(catalysts, majorOnly = false, days = null) {
  const end = days === null || !catalysts?.as_of ? null
    : new Date(Date.parse(`${catalysts.as_of}T00:00:00Z`) + days * 864e5).toISOString().slice(0, 10);
  return (catalysts?.events || []).filter((e) => e.lane === 'macro'
    && ['macro_data', 'monetary_policy'].includes(e.category) && e.date >= catalysts.as_of
    && (end === null || e.date <= end)
    && (!majorOnly || ['high', 'medium'].includes(e.importance)))
    .sort((a, b) => a.date.localeCompare(b.date) || (a.time || '99:99').localeCompare(b.time || '99:99')
      || a.title.localeCompare(b.title));
}

const AGENDA_DAYS = 14;
const MAJOR = 'HIGH + MEDIUM';
const level = (e) => (['high', 'medium', 'low'].includes(e.importance) ? e.importance : 'unknown');
const dayLabel = (date) => new Date(`${date}T12:00:00Z`).toLocaleDateString('en-US', { weekday: 'short', day: 'numeric', timeZone: 'UTC' });

// One line per release: day (first of its day only), time, name (cut with its
// full text on hover), reference period, importance. The row carries the colour.
function agendaRow(e, date) {
  const lv = level(e);
  return el('div', { class: `macro-agenda-event importance-${lv}` }, [
    el('span', { class: 'macro-agenda-day', text: date ? dayLabel(e.date) : '' }),
    el('span', { class: 'macro-agenda-time', text: e.time || 'TBD' }),
    el('a', { class: 'macro-agenda-name', href: e.source_url || '#catalysts', text: e.title,
      title: [e.title, e.reference_period].filter(Boolean).join(' · ') }),
    el('span', { class: 'macro-agenda-period', text: e.reference_period || '' }),
    el('span', { class: 'macro-importance', text: lv === 'unknown' ? '?' : lv.slice(0, 3).toUpperCase(),
      title: e.importance_basis?.text || 'Importance unavailable in source' }),
  ]);
}

export function upcomingMacro(catalysts) {
  const host = el('div', { class: 'macro-agenda' });
  const draw = (filter) => {
    const all = macroCalendarEvents(catalysts, false, AGENDA_DAYS);
    host.replaceChildren();
    if (!all.length) { host.append(el('div', { class: 'gap', text: 'No macro releases in the next two weeks of this calendar snapshot.' })); return; }
    const days = [...new Set(all.map((e) => e.date))];
    for (const date of days) {
      const today = all.filter((e) => e.date === date);
      const shown = filter === MAJOR ? today.filter((e) => ['high', 'medium'].includes(e.importance)) : today;
      const folded = today.filter((e) => !shown.includes(e));
      shown.forEach((e, i) => host.append(agendaRow(e, i === 0)));
      if (folded.length) {
        // Low-importance releases stay one click away, under the day they belong to.
        const fold = el('details', { class: 'macro-agenda-more' }, [
          el('summary', {}, [el('span', { class: 'macro-agenda-day', text: shown.length ? '' : dayLabel(date) }),
            el('span', { text: `+${folded.length} low` })]),
          ...folded.map((e) => agendaRow(e, false)),
        ]);
        host.append(fold);
      }
    }
  };
  draw(MAJOR);
  const info = el('span', { class: 'rc-info', text: 'ⓘ', title: `Calendar snapshot ${catalysts?.as_of || 'unavailable'}, next ${AGENDA_DAYS} days, times New York. Red = high attention, amber = medium, grey = low; not a market direction forecast. Importance comes from the calendar's measured release-day moves or editorial judgement (hover a badge for its basis). Dates may change; this is not a live calendar.` });
  return card('UPCOMING MACRO & POLICY', el('div', { class: 'tag-row' }, [periodSwitch([MAJOR, 'ALL'], MAJOR, draw), info,
    el('a', { href: '#catalysts', text: 'FULL CALENDAR →' })]), [host]);
}
