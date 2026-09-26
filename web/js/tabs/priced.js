// PRICED PATH: what the rates and event markets expect, and how that moved.
// Futures-implied meeting probabilities beside Kalshi and Polymarket, the
// longer SOFR path, and the release distributions -- as series, not tied to
// how far away an event is.

import { el, card, num, metaRow, DASH } from '../fmt.js';
import { render } from '../charts.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const bp = (v, digits = 1) => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}bp` : DASH);
const pctOf = (v) => (present(v) ? `${Math.round(v * 100)}%` : DASH);
const shortDate = (iso) => (iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit', timeZone: 'UTC' }).toUpperCase() : DASH);

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function stats(data) {
  const next = data.meetings[0];
  const byYearEnd = [...data.meetings].reverse().find((m) => m.date.slice(0, 4) === (next?.date || '').slice(0, 4));
  const last = data.meetings[data.meetings.length - 1];
  const trace = data.next_meeting_trace || [];
  const same = trace.filter((t) => t.meeting === next?.date);
  const dayAgo = same.length > 1 ? same[same.length - 2].change_bp : null;
  const out = [];
  if (next) {
    const s = next.step;
    const verb = s.direction === 'hold' ? 'HOLD' : `${s.direction.toUpperCase()} 25`;
    out.push(stat(`NEXT FOMC · ${shortDate(next.date)}`, bp(next.change_bp),
      `P(${verb}) ${pctOf(s.whole_steps ? 1 : s.p_next_step)} futures · Kalshi ${pctOf(next.kalshi?.p_hike)} hike · Poly ${pctOf(next.polymarket?.value)}`,
      next.change_bp > 0 ? 'down' : next.change_bp < 0 ? 'up' : ''));
    out.push(stat('NEXT MEETING · CHANGE', `${bp(present(dayAgo) ? next.change_bp - dayAgo : null)} 1D`,
      `${bp(next.change_1w_bp)} over 1W · ${bp(next.change_1m_bp)} over 1M`));
  }
  if (byYearEnd) out.push(stat(`PRICED BY ${shortDate(byYearEnd.date)}`, bp(byYearEnd.cumulative_bp, 0),
    `${num(byYearEnd.cumulative_bp / 25, 1)} moves of 25bp from ${num(data.target.lower, 2)}–${num(data.target.upper, 2)}`));
  if (last) out.push(stat(`PRICED BY ${shortDate(last.date)}`, bp(last.cumulative_bp, 0), `expected EFFR ${num(last.post, 2)}%`));
  const disagree = data.meetings.filter((m) => m.disagree);
  out.push(stat('FUTURES VS KALSHI', disagree.length ? `${disagree.length} apart` : 'in line',
    disagree.length ? disagree.map((m) => shortDate(m.date)).join(' · ') : `no meeting differs by > ${data.disagreement_bp}bp`,
    disagree.length ? 'down' : ''));
  return el('div', { class: 'stat-strip' }, out);
}

function pathChart(node, data) {
  const labels = { today: 'today', '1 week ago': '1 week ago', '1 month ago': '1 month ago' };
  render(node, (option, p) => {
    const tones = { today: p.text, '1 week ago': p.accent, '1 month ago': p.faint };
    const series = Object.entries(data.paths).map(([label, path]) => ({
      name: `fed funds · ${labels[label]}`, type: 'line', step: 'end', symbolSize: 4,
      data: path.points.map((pt) => [pt.date, pt.post]),
      lineStyle: { width: label === 'today' ? 2 : 1, color: tones[label], type: label === '1 month ago' ? 'dashed' : 'solid' },
      itemStyle: { color: tones[label] },
    }));
    const quarterMid = (q) => { const [y, m] = q.split('-').map(Number); return new Date(Date.UTC(y, m - 1, 15)).toISOString().slice(0, 10); };
    const sofrToday = data.sofr?.today?.points || [];
    if (sofrToday.length) {
      series.push({
        name: 'SOFR 3M futures · today', type: 'line', symbol: 'rect', symbolSize: 6,
        data: sofrToday.map((pt) => [quarterMid(pt.quarter), pt.rate]),
        lineStyle: { width: 1, color: p.blue, type: 'dotted' }, itemStyle: { color: p.blue },
      });
    }
    const t = data.target;
    return {
      ...option,
      grid: { ...option.grid, top: 36, left: 48, right: 16 },
      legend: { top: 0, textStyle: { color: p.dim, fontSize: 10 }, itemWidth: 12, itemHeight: 2 },
      tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: (v) => (present(v) ? `${num(v, 3)}%` : DASH) },
      xAxis: { ...option.xAxis, type: 'time', boundaryGap: false },
      yAxis: { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => `${num(v, 2)}%` } },
      series: series.concat(present(t.lower) ? [{
        name: 'target range now', type: 'line', data: [], silent: true,
        markArea: { silent: true, itemStyle: { color: 'rgba(96,165,250,0.08)' }, data: [[{ yAxis: t.lower }, { yAxis: t.upper }]] },
      }] : []),
    };
  });
}

function traceChart(node, data) {
  const next = data.meetings[0];
  const rows = (data.next_meeting_trace || []);
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, top: 14, left: 48 },
    tooltip: { ...option.tooltip, valueFormatter: (v) => bp(v) },
    xAxis: { ...option.xAxis, data: rows.map((r) => r.date) },
    yAxis: { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => `${v}bp` } },
    series: [{
      name: 'priced at the next meeting', type: 'line', showSymbol: false, data: rows.map((r) => r.change_bp),
      lineStyle: { width: 1.4, color: p.text },
      markLine: { silent: true, symbol: 'none', data: [{ yAxis: 25 }, { yAxis: 0 }, { yAxis: -25 }],
        lineStyle: { color: p.faint, type: 'dashed' }, label: { color: p.faint, fontSize: 9, formatter: (q) => `${q.value > 0 ? '+' : ''}${q.value}bp` } },
      markPoint: next?.kalshi ? { symbol: 'diamond', symbolSize: 9, itemStyle: { color: p.accent },
        data: [{ coord: [rows.length - 1, next.kalshi.expected_bp], name: 'Kalshi' }],
        label: { show: true, position: 'left', color: p.accent, fontSize: 9, formatter: 'Kalshi' } } : undefined,
    }],
  }));
}

function probabilityBar(p, direction) {
  const width = present(p) ? Math.round(Math.min(1, p) * 100) : 0;
  return el('span', { class: 'pp-bar' }, [el('span', { class: `pp-fill ${direction}`, style: `width:${width}%` })]);
}

function meetingTable(data) {
  const head = ['MEETING', 'FUTURES', 'P(MOVE)', 'TWO NEAREST RANGES AFTER', 'KALSHI', 'POLY P(HIKE)', '1W Δ', '1M Δ'];
  const rows = data.meetings.map((m) => {
    const s = m.step;
    const pMove = s.whole_steps ? 1 : s.p_next_step;
    return el('tr', { class: m.disagree ? 'pp-disagree' : '', title: m.source || '' }, [
      el('td', {}, [shortDate(m.date), m.source && m.source.startsWith('Kalshi') ? el('span', { class: 'dim', text: ' *' }) : null]),
      el('td', { class: m.change_bp > 0 ? 'down' : m.change_bp < 0 ? 'up' : '', text: bp(m.change_bp) }),
      el('td', {}, [probabilityBar(pMove, s.direction), ` ${pctOf(pMove)} ${s.direction === 'hold' ? '' : s.direction}`]),
      el('td', { class: 'dim', text: m.ranges.map((r) => `${r.range} ${pctOf(r.probability)}`).join(' · ') }),
      el('td', { text: m.kalshi ? `${bp(m.kalshi.expected_bp)} · hike ${pctOf(m.kalshi.p_hike)}` : DASH }),
      el('td', { text: pctOf(m.polymarket?.value) }),
      el('td', { class: 'dim', text: bp(m.change_1w_bp) }),
      el('td', { class: 'dim', text: bp(m.change_1m_bp) }),
    ]);
  });
  return el('div', { class: 'table-scroll' }, [
    el('table', { class: 'data pp-table' }, [el('thead', {}, [el('tr', {}, head.map((h) => el('th', { text: h })))]), el('tbody', {}, rows)]),
    el('div', { class: 'field-note', text: `* date from Kalshi's contract; the Fed has not listed the meeting yet. A red row: Kalshi's expected change differs from the futures' by more than ${data.disagreement_bp}bp.` }),
  ]);
}

function releases(data) {
  const items = data.releases || [];
  if (!items.length) return el('div', { class: 'dim', text: 'No open Kalshi ladder in the configured series.' });
  const fmt = (v, unit) => (present(v) ? `${num(v, unit === 'k' ? 0 : 2)}${unit === '%' ? '%' : unit === 'k' ? 'k' : ''}` : DASH);
  return el('div', { class: 'pp-releases' }, items.map((r) => {
    const lo = r.low, hi = r.high, mid = r.value;
    const span = present(lo) && present(hi) && hi > lo ? hi - lo : null;
    const pos = span ? Math.max(0, Math.min(100, ((mid - lo) / span) * 100)) : 50;
    return el('div', { class: 'pp-release' }, [
      el('div', { class: 'pp-release-head' }, [el('span', { text: r.label }), el('span', { class: 'dim', text: shortDate(r.release) })]),
      el('div', { class: 'pp-release-value', text: fmt(mid, r.unit) }),
      el('div', { class: 'pp-range' }, [
        el('span', { class: 'pp-range-band' }),
        el('span', { class: 'pp-range-mid', style: `left:${pos}%` }),
      ]),
      el('div', { class: 'pp-release-foot dim', text: `10–90%: ${fmt(lo, r.unit)} – ${fmt(hi, r.unit)} · OI ${present(r.open_interest) ? num(r.open_interest, 0) : DASH}` }),
    ]);
  }));
}

function anchors(data) {
  return el('div', { class: 'stat-strip pp-anchors' }, (data.anchors || []).filter((a) => !['DFEDTARL', 'DFEDTARU'].includes(a.key)).map((a) =>
    stat(a.label.toUpperCase(), `${num(a.value, 2)}%`,
      a.key === 'GDPNOW' ? `quarter of ${a.date}` : `${bp(present(a.change_1w) ? a.change_1w * 100 : null, 0)} 1W · ${bp(present(a.change_1m) ? a.change_1m * 100 : null, 0)} 1M`)));
}

function methodNotes(data) {
  return [
    'Policy path: fed funds futures settle on the month\'s average effective rate (100 − price). In a meeting month, R = (d·pre + (N−d)·post)/N; each meeting\'s pre-meeting rate is the previous one\'s post-meeting rate, starting from today\'s effective rate, and when the next month has no meeting its contract gives the post-meeting rate directly. This is the arithmetic behind CME FedWatch.',
    'P(move) reads a meeting\'s expected change in steps of 25bp: +15bp is a 62% chance of one hike. The "two nearest ranges" are the target ranges either side of the cumulative change, weighted by how close it is to each -- not CME\'s full probability tree.',
    `Kalshi: each meeting's outcome prices (mid when the spread is ≤ 10¢, else the last trade); ">25bp" counts as 50bp in the expected change. Polymarket: the probability of a hike at that meeting. A meeting is flagged when Kalshi's expected change and the futures' differ by more than ${data.disagreement_bp}bp; the two are shown, never averaged.`,
    'Yahoo\'s fed funds futures are delayed and read at the close; the week-ago and month-ago paths are rebuilt from each contract\'s history. SOFR futures have no history on Yahoo, so their week-ago and month-ago paths come from the snapshot branch once it has recorded that far back.',
    'Release distributions: every open Kalshi ladder in the configured series, with its median and 10th–90th percentiles interpolated from the strike ladder -- whatever the release date. Anchors are FRED\'s current-vintage series.',
  ];
}

export default function renderPriced(root, data) {
  const t = data.target || {};
  root.append(metaRow(`PRICED PATH · TARGET ${num(t.lower, 2)}–${num(t.upper, 2)}% · EFFR ${num(t.effr, 2)}% · AS OF ${data.as_of}`, methodNotes(data)));
  root.append(stats(data));
  const pathNode = el('div', { class: 'chart tall' });
  const traceNode = el('div', { class: 'chart tall' });
  const sofrNote = data.sofr?.['1 week ago'] ? '' : ' · SOFR history: not recorded yet';
  root.append(el('div', { class: 'grid two pp-top' }, [
    card('POLICY PATH', el('span', { class: 'dim', text: `expected rate after each meeting · today, 1W and 1M ago${sofrNote}` }), [pathNode]),
    card(`NEXT MEETING THROUGH TIME · ${shortDate(data.meetings[0]?.date)}`, el('span', { class: 'dim', text: 'change priced at the meeting that was next' }), [traceNode]),
  ]));
  root.append(card('BY MEETING · FUTURES VS KALSHI VS POLYMARKET', null, [meetingTable(data)]));
  root.append(card('RELEASE DISTRIBUTIONS · KALSHI', el('span', { class: 'dim', text: 'median and 10th–90th percentile' }), [releases(data)]));
  root.append(card('ANCHORS', el('span', { class: 'dim', text: 'FRED' }), [anchors(data)]));
  requestAnimationFrame(() => { pathChart(pathNode, data); traceChart(traceNode, data); });
}
