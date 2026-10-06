import { el, card, table, num, bps, sectionTitle, DASH } from '../fmt.js';
import { render, timeLines, SERIES_COLORS } from '../charts.js';
import { rangeSwitch, sliceRange, initialRange } from '../range.js';
import { createManualFeed } from '../live-feed.js';

const ok = (v) => typeof v === 'number' && Number.isFinite(v);

// A spread row ("10Y - 2Y") from live yields by tenor: its level and today's
// change, both in bp. Null where either leg has no live quote.
export function liveSpread(label, byTenor) {
  const [long, shortLeg] = String(label).split('-').map((x) => x.trim());
  const a = byTenor.get(long);
  const b = byTenor.get(shortLeg);
  if (!a || !b || !ok(a.price) || !ok(b.price)) return null;
  return {
    bps: Math.round((a.price - b.price) * 1000) / 10,
    change_bp: ok(a.change_bp) && ok(b.change_bp) ? Math.round((a.change_bp - b.change_bp) * 10) / 10 : null,
  };
}

// ET clock of the newest live quote, for the curve's legend.
function clockOf(quotes) {
  const newest = Math.max(...quotes.map((q) => q.time).filter(ok));
  if (!Number.isFinite(newest)) return '';
  return new Date(newest * 1000).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York' });
}

// A rising yield is a falling bond price and tighter money: red, as on
// OVERVIEW. Spreads are shape, not direction, so they stay grey.
function yieldClass(change) {
  if (change === null || change === undefined || change === 0) return 'dim';
  return change > 0 ? 'down' : 'up';
}

function historyCard(history) {
  const series = history?.series || {};
  const spreadName = history?.spread;
  const names = Object.keys(series).filter((n) => n !== spreadName);
  if (!names.length) return null;
  const longest = names.map((n) => series[n].dates).reduce((a, b) => (b.length > a.length ? b : a), []);
  let range = initialRange(longest, '1Y');
  const node = el('div', { class: 'chart' });
  const spreadNode = el('div', { class: 'chart short' });
  const cut = (name) => sliceRange(series[name].dates, { values: series[name].values }, range);
  const draw = () => {
    timeLines(node, names.map((name) => ({ name, ...cut(name) })), {
      left: (v) => `${v.toFixed(1)}%`,
      value: (v) => `${num(v, 2)}%`,
    });
    // The spread under the levels, on its own axis: below zero is an inverted curve.
    if (series[spreadName]) {
      const s = cut(spreadName);
      timeLines(spreadNode, [{ name: spreadName, ...s, color: (p) => p.accent }], {
        left: (v) => `${v.toFixed(0)}bp`,
        value: (v) => `${num(v, 0)}bp`,
        markY: [{ y: 0, label: 'inverted below' }],
      });
    }
  };
  requestAnimationFrame(draw);
  return card('YIELDS OVER TIME', rangeSwitch(longest, range, (label) => { range = label; draw(); }), [
    node,
    series[spreadName] ? el('div', { class: 'chart-head' }, [el('span', { class: 'dim', text: `${spreadName} SPREAD · BP` })]) : null,
    series[spreadName] ? spreadNode : null,
    el('div', { class: 'note-text', text: `FRED constant-maturity yields (Treasury's own series), ${history.years} years: daily for the last year, each week's last print before that. FRED posts a day after Treasury, so the last point can trail the table above by a session.` }),
  ]);
}

export default function renderFixedIncome(root, data) {
  root.append(sectionTitle('U.S. TREASURIES', '(FIXED INCOME)'));

  const chartNode = el('div', { class: 'chart tall' });
  const curveCard = card(
    'YIELD CURVE — LATEST VS. 1 WEEK, 1 MONTH AGO AND START OF YEAR',
    null,
    [chartNode, el('div', { class: 'note-text', text: data.note })],
  );
  // The curve's shape beside its history: where each tenor sits today, and
  // how it got there.
  const history = historyCard(data.history);
  root.append(history ? el('div', { class: 'grid two' }, [curveCard, history]) : curveCard);

  // CNBC's live curve joins the chart and the table only after REFRESH.
  let live = null;
  const drawCurve = () => render(chartNode, (option, p) => ({
    ...option,
    grid: { ...option.grid, bottom: 52, left: 56 },
    legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
    tooltip: { ...option.tooltip, valueFormatter: (v) => (v === null ? DASH : `${v.toFixed(2)}%`) },
    xAxis: { ...option.xAxis, data: data.tenors, boundaryGap: false },
    yAxis: { ...option.yAxis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${v.toFixed(2)}%` } },
    series: [...data.curves.map((curve, index) => ({
      name: `${curve.label} (${curve.date})`,
      type: 'line',
      data: curve.values,
      showSymbol: true,
      symbolSize: 5,
      // The latest curve is the subject of the panel; the comparisons are
      // context, so they are thinner and cooler.
      lineStyle: { width: index === 0 ? 1.8 : 1.1, color: SERIES_COLORS[index % SERIES_COLORS.length] },
      itemStyle: { color: SERIES_COLORS[index % SERIES_COLORS.length] },
    })), ...(live ? [{
      name: `Live, CNBC (${live.clock} ET)`,
      type: 'line',
      data: data.tenors.map((t) => live.byTenor.get(t)?.price ?? null),
      showSymbol: true,
      symbolSize: 4,
      lineStyle: { width: 1.4, type: 'dashed', color: p.text },
      itemStyle: { color: p.text },
    }] : [])],
  }));
  requestAnimationFrame(drawCurve);

  // Change columns come from the artifact, which took them from the contract:
  // "1W" on this tab is seven calendar days because the curve is published on
  // a calendar schedule, and it says so in the note rather than silently
  // meaning something different from "1W" on the equity tabs.
  const cols = data.change_columns;
  const liveCells = (yieldText, change, cls) => (live ? [
    el('td', { class: 'live-cell', text: yieldText }),
    el('td', { class: `live-cell ${cls}`, text: ok(change) ? bps(change) : DASH }),
  ] : []);
  const buildRows = () => {
    const rows = data.rows.map((row) => {
      const q = live?.byTenor.get(row.tenor);
      return el('tr', {}, [
        el('td', { text: row.tenor }),
        el('td', { text: row.yield_pct === null ? DASH : `${num(row.yield_pct)}%` }),
        ...liveCells(q && ok(q.price) ? `${num(q.price, 3)}%` : DASH, q?.change_bp, yieldClass(q?.change_bp)),
        ...cols.map((c) => el('td', { class: yieldClass(row[c]), text: bps(row[c]) })),
      ]);
    });
    data.spreads.forEach((spread) => {
      const s = live ? liveSpread(spread.label, live.byTenor) : null;
      rows.push(el('tr', { class: 'emphasis' }, [
        el('td', { text: spread.label }),
        el('td', { text: spread.bps === null ? DASH : `${bps(spread.bps)} bps` }),
        ...liveCells(s ? `${bps(s.bps)} bps` : DASH, s?.change_bp, 'dim'),
        ...cols.map((c) => el('td', { class: 'dim', text: bps(spread[c]) })),
      ]));
    });
    return rows;
  };
  const tableHost = el('div');
  const liveNote = el('div', { class: 'note-text' });
  const drawTable = () => tableHost.replaceChildren(table(
    ['MATURITY', 'YIELD', ...(live ? ['LIVE', 'TODAY (BPS)'] : []), ...cols.map((c) => `${c} (BPS)`)], buildRows()));
  const feed = createManualFeed(['api/quotes?board=yields'], {
    onData: ([body]) => {
      live = { byTenor: new Map(body.quotes.map((q) => [q.label, q])), clock: clockOf(body.quotes) };
      liveNote.textContent = 'LIVE: CNBC\'s on-the-run market yields, about 15 seconds behind, as of '
        + `${live.clock || DASH} ET; TODAY is CNBC's change since its previous close. YIELD and the change columns are Treasury's `
        + 'published par curve, a fitted curve on a bond-equivalent basis: the two differ by a few bp on coupons and by ten or so on bills '
        + 'on the same day without anything moving, so compare TODAY with TODAY, not LIVE with YIELD.';
      drawTable();
      drawCurve();
    },
  });
  drawTable();

  root.append(card('TREASURY YIELDS — LEVEL & CHANGE (BPS)',
    el('div', { class: 'live-controls' }, [el('span', { class: 'dim', text: 'red = yield up' }), feed.controls]),
    [tableHost, liveNote]));

  const auctions = data.auctions;
  if (auctions?.groups?.length) {
    const auctionRows = auctions.groups.map((row) => el('tr', {}, [
      el('td', { text: `${row.original_term} ${row.type}` }),
      el('td', { text: row.reopening === 'Yes' ? 'Reopening' : 'New' }),
      el('td', { text: row.latest_date }),
      el('td', { text: row.high_yield == null ? DASH : `${num(row.high_yield, 3)}%` }),
      el('td', { class: yieldClass(row.high_yield_change_bps), text: bps(row.high_yield_change_bps) }),
      el('td', { text: row.bid_to_cover == null ? DASH : num(row.bid_to_cover, 2) }),
      el('td', { class: 'dim', text: row.bid_to_cover_change == null ? DASH : num(row.bid_to_cover_change, 2) }),
      el('td', { text: row.indirect_share_pct == null ? DASH : `${num(row.indirect_share_pct, 1)}%` }),
      el('td', { text: row.direct_share_pct == null ? DASH : `${num(row.direct_share_pct, 1)}%` }),
      el('td', { text: row.dealer_share_pct == null ? DASH : `${num(row.dealer_share_pct, 1)}%` }),
    ]));
    root.append(card(
      'RECENT COUPON AUCTIONS',
      el('span', { class: 'dim', text: `${auctions.coverage?.start || DASH} to ${auctions.coverage?.end || DASH}` }),
      [
        table(['ISSUE', 'KIND', 'AUCTION', 'HIGH YIELD', 'VS PRIOR', 'BID/COVER', 'CHANGE', 'INDIRECT', 'DIRECT', 'DEALER'], auctionRows),
        el('div', { class: 'note-text', text: 'Each row is the latest completed auction within its original maturity, type and reopening group. Change is against the previous auction in that same group, not against a different tenor. Indirect bidders are not the same as foreign buyers. Tail is unavailable without a pre-auction when-issued yield.' }),
      ],
    ));
  } else if (auctions?.status === 'missing') {
    root.append(el('div', { class: 'gap', text: 'Treasury auction results are not in the local snapshot yet.' }));
  }
}
