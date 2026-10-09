// INDICES, intraday: each index's day so far in five-minute closes against
// its previous close, from the quote function's index board. Like the strip,
// it sits above the recap and says it is live; nothing beneath it changes.

import { el, card, num, pct, dirClass, DASH } from './fmt.js';
import { render } from './charts.js';
import { createFeed } from './live-feed.js';

// A series' points as [ms, close], gaps kept as gaps.
export function points(series) {
  if (!series) return [];
  return series.t.map((t, i) => [t * 1000, series.c[i] ?? null]);
}

const REGULAR_SECONDS = 6.5 * 3600;

// 09:30 New York on the day of `t` (epoch seconds), as epoch seconds.
export function newYorkOpen(t) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(t * 1000)).map((p) => [p.type, p.value]));
  const [y, m, d] = [Number(parts.year), Number(parts.month) - 1, Number(parts.day)];
  const offset = Math.round((Date.UTC(y, m, d, Number(parts.hour), Number(parts.minute)) / 1000 - t) / 60) * 60;
  return Date.UTC(y, m, d, 9, 30) / 1000 - offset;
}

// The x axis is the whole session, open to close, whatever has traded so far:
// Yahoo's own regular period when the series falls inside it (early closes
// included), else -- after the close, when Yahoo may already report the next
// session -- 09:30 to 16:00 New York on the series' own day. [startMs, endMs].
export function sessionWindow(session, series) {
  const first = series?.t?.[0];
  if (!Number.isFinite(first)) return null;
  if (session && Number.isFinite(session.start) && Number.isFinite(session.end)
      && first >= session.start && first < session.end) {
    return [session.start * 1000, session.end * 1000];
  }
  const open = newYorkOpen(first);
  return [open * 1000, (open + REGULAR_SECONDS) * 1000];
}

// The y range always holds the previous close, so the dashed line is on the
// chart and the day reads as above or below it at a glance.
export function valueRange(series, previousClose) {
  const values = (series?.c || []).filter(Number.isFinite);
  if (Number.isFinite(previousClose)) values.push(previousClose);
  if (!values.length) return null;
  const low = Math.min(...values);
  const high = Math.max(...values);
  const pad = (high - low || Math.abs(high) * 0.001 || 1) * 0.06;
  return [low - pad, high + pad];
}

function chart(node, quote, session) {
  const span = sessionWindow(session, quote.series);
  const range = valueRange(quote.series, quote.previous_close);
  render(node, (option, p) => {
    const up = (quote.change ?? 0) >= 0;
    return {
      ...option,
      grid: { left: 52, right: 12, top: 10, bottom: 22 },
      tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: (v) => (v === null || v === undefined ? DASH : num(v)) },
      xAxis: { ...option.xAxis, type: 'time', boundaryGap: false,
        min: span ? span[0] : undefined, max: span ? span[1] : undefined,
        axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => new Date(v).toLocaleTimeString('en-US',
          { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York' }) } },
      yAxis: { ...option.yAxis, scale: true, min: range ? range[0] : undefined, max: range ? range[1] : undefined,
        // The padded range's own ends are not round numbers: only the ticks between them are labelled.
        axisLabel: { ...option.yAxis?.axisLabel, showMinLabel: false, showMaxLabel: false,
          formatter: (v) => num(v, Math.abs(v) >= 1000 ? 0 : 2) } },
      series: [{
        type: 'line', showSymbol: false, data: points(quote.series), connectNulls: false,
        lineStyle: { color: up ? p.up : p.down, width: 1.4 },
        markLine: quote.previous_close === null || quote.previous_close === undefined ? undefined : {
          silent: true, symbol: 'none', data: [{ yAxis: quote.previous_close, name: 'prev close' }],
          lineStyle: { color: p.faint, type: 'dashed' },
          label: { position: 'insideStartTop', color: p.dim, fontSize: 9, formatter: `prev close ${num(quote.previous_close)}` },
        },
      }],
    };
  });
}

export function mountIndexCharts() {
  const grid = el('div', { class: 'grid two live-index-grid' });
  const holder = el('div', {});
  const feed = createFeed('api/quotes?board=indices', {
    node: holder,
    onData: (body) => {
      grid.replaceChildren(...body.quotes.map((q) => {
        const node = el('div', { class: 'chart short' });
        const head = el('div', { class: 'live-index-head' }, [
          el('span', { class: 'stat-label', text: q.label }),
          el('span', { class: 'stat-value', text: q.price === null || q.price === undefined ? DASH : num(q.price) }),
          el('span', { class: dirClass(q.change_pct), text: q.error ? q.error : `${q.change >= 0 ? '+' : ''}${num(q.change)} (${pct(q.change_pct)})` }),
        ]);
        if (!q.error) requestAnimationFrame(() => chart(node, q, body.session));
        return el('div', { class: 'live-index' }, [head, q.error ? null : node]);
      }));
    },
  });
  holder.append(card('INTRADAY · LIVE', feed.controls, [
    grid,
    el('div', { class: 'note-text', text: 'Five-minute closes so far today against the previous close (dashed), Yahoo, unofficial; '
      + 'refreshed every few minutes while the session is open. The recap below is the build\'s close.' }),
  ]));
  return holder;
}
