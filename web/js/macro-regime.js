// Descriptive monthly map; each coordinate is for the same reference month.
import { el, card, num, pct, DASH, periodSwitch } from './fmt.js';
import { render } from './charts.js';

const finite = (v) => typeof v === 'number' && Number.isFinite(v);
export function regimeName(x, y) {
  if (!finite(x) || !finite(y)) return null;
  if (x === 0 || y === 0) return 'ON THE BOUNDARY';
  return x > 0 ? (y > 0 ? 'REFLATION' : 'GOLDILOCKS') : (y > 0 ? 'STAGFLATION' : 'SLOWDOWN');
}

export function macroSnapshot(overview, regime, gdp, priced) {
  const prints = overview?.prints || [];
  const entries = [...(gdp ? [gdp] : []), ...prints];
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

export function macroRegimeCard(regime) {
  const points = (regime?.points || []).filter((p) => finite(p.growth) && finite(p.inflation_change_pp));
  const latest = points.at(-1);
  if (!latest) return card('GROWTH / INFLATION MAP', null, [el('div', { class: 'gap', text: 'No matching monthly CFNAI and core PCE observations in this build.' })]);
  const x = Math.max(.2, ...points.map((p) => Math.abs(p.growth))) * 1.18;
  const y = Math.max(.1, ...points.map((p) => Math.abs(p.inflation_change_pp))) * 1.18;
  const node = el('div', { class: 'chart', style: 'height:360px', 'aria-label': 'Growth and inflation regime map' });
  const quadrant = (x0, y0, x1, y1, name, color) => [{ name, xAxis: x0, yAxis: y0, itemStyle: { color }, label: { position: x0 < 0 ? (y0 < 0 ? 'insideBottomLeft' : 'insideTopLeft') : (y0 < 0 ? 'insideBottomRight' : 'insideTopRight') } }, { xAxis: x1, yAxis: y1 }];
  requestAnimationFrame(() => render(node, (o, p) => ({
    ...o,
    grid: { ...o.grid, left: 60, right: 38, top: 32, bottom: 56 },
    xAxis: { ...o.xAxis, type: 'value', min: -x, max: x, name: 'CFNAI 3M · above / below trend', nameLocation: 'middle', nameGap: 32, nameTextStyle: { color: p.dim }, axisLabel: { ...o.xAxis.axisLabel, showMinLabel: false, showMaxLabel: false } },
    yAxis: { ...o.yAxis, type: 'value', min: -y, max: y, name: 'Core PCE YoY change · pp / 3M', nameLocation: 'middle', nameGap: 45, nameTextStyle: { color: p.dim } },
    tooltip: { ...o.tooltip, trigger: 'item', formatter: (v) => `${v.data?.month || ''}<br>CFNAI 3M: ${num(v.value?.[0], 3)}<br>Core PCE YoY change: ${num(v.value?.[1], 2)} pp<br>Core PCE YoY: ${pct(v.data?.inflation, 2)}` },
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
      data: points.map((v, i) => ({ value: [v.growth, v.inflation_change_pp], month: v.month, inflation: v.inflation_yoy,
        symbolSize: i === points.length - 1 ? 15 : i === 0 ? 7 : 5,
        itemStyle: { color: p.accent, opacity: .3 + .7 * (i + 1) / points.length,
          borderColor: i === points.length - 1 ? p.text : p.panel, borderWidth: i === points.length - 1 ? 2 : 1 },
        label: { show: i === 0 || i === points.length - 1,
          formatter: `${i === points.length - 1 ? 'LATEST · ' : ''}${v.month}`,
          position: i === points.length - 1 ? 'bottom' : 'left', distance: 10, color: p.text,
          fontWeight: i === points.length - 1 ? 'bold' : 'normal', fontSize: 10 },
      })),
    }],
  })));
  return card('GROWTH / INFLATION MAP · LAST 12 MATCHED MONTHS', null, [el('div', { class: 'macro-trace-key', text: 'FADED → RECENT · arrows show the last 3 monthly moves · outlined dot = latest' }), node,
    el('div', { class: 'note-text', text: `${latest.month} · ${regimeName(latest.growth, latest.inflation_change_pp)} · growth ${num(latest.growth, 3)}, core PCE YoY ${pct(latest.inflation_yoy, 2)}, change ${num(latest.inflation_change_pp, 2)} pp over ${regime.change_months} months.` }),
    el('div', { class: 'note-text', text: 'Above/below historical trend is CFNAI’s zero line; inflation direction is the change in core PCE YoY, not its absolute level. Reference months are paired, not release dates. Revised current-vintage data; descriptive, not a trading signal.' }),
    el('div', { class: 'field-note' }, [el('a', { href: 'https://fred.stlouisfed.org/series/CFNAIMA3', text: 'Chicago Fed CFNAI 3M ↗' }), ' · ', el('a', { href: 'https://fred.stlouisfed.org/series/PCEPILFE', text: 'BEA core PCE via FRED ↗' })]),
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
