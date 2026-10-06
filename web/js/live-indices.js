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

function chart(node, quote) {
  render(node, (option, p) => {
    const up = (quote.change ?? 0) >= 0;
    return {
      ...option,
      grid: { left: 52, right: 12, top: 10, bottom: 22 },
      tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: (v) => (v === null || v === undefined ? DASH : num(v)) },
      xAxis: { ...option.xAxis, type: 'time', boundaryGap: false,
        axisLabel: { color: p.dim, fontSize: 9, formatter: (v) => new Date(v).toLocaleTimeString('en-US',
          { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York' }) } },
      yAxis: { ...option.yAxis, scale: true },
      series: [{
        type: 'line', showSymbol: false, data: points(quote.series), connectNulls: false,
        lineStyle: { color: up ? p.up : p.down, width: 1.4 },
        markLine: quote.previous_close === null || quote.previous_close === undefined ? undefined : {
          silent: true, symbol: 'none', data: [{ yAxis: quote.previous_close, name: 'prev close' }],
          lineStyle: { color: p.faint, type: 'dashed' }, label: { color: p.dim, fontSize: 9, formatter: 'prev close' },
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
        if (!q.error) requestAnimationFrame(() => chart(node, q));
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
