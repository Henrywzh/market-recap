// JOURNAL: every decision with its reason, reviewed against what happened.
// Names on their return against the index over the horizon; overrides of the
// systematic anchor on the return they added or cost. Hit rates only count
// decisions whose horizon has passed.

import { el, card, num, pct, metaRow, DASH } from '../fmt.js';
import { render } from '../charts.js';
import { tickerHref } from '../routes.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const rate = (r) => (r && present(r.hit_rate) ? `${Math.round(r.hit_rate * 100)}%` : DASH);

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function outcomeChart(node, decisions) {
  const judged = decisions.filter((d) => d.review.matured && (present(d.review.excess_pct) || present(d.review.value_bp)));
  render(node, (option, p) => ({
    ...option,
    grid: { left: 60, right: 16, top: 12, bottom: 30 },
    tooltip: { ...option.tooltip, trigger: 'item', axisPointer: undefined,
      formatter: (q) => { const d = judged[q.dataIndex]; return `<b>${d.ticker}</b> ${d.action} · ${d.date}<br>${d.action === 'override' ? `${num(d.review.value_bp, 0)}bp vs anchor` : `${pct(d.review.excess_pct, 1)} vs index`} · ${d.review.right ? 'right' : 'wrong'}`; } },
    xAxis: { ...option.xAxis, boundaryGap: true, data: judged.map((d) => `${d.ticker} ${d.date.slice(2)}`) },
    yAxis: { ...option.yAxis, axisLabel: { color: p.dim, fontSize: 10, formatter: (v) => `${v}` } },
    series: [{
      type: 'bar', barMaxWidth: 18,
      data: judged.map((d) => ({
        value: d.action === 'override' ? d.review.value_bp / 100 : d.review.excess_pct,
        itemStyle: { color: d.review.right ? p.up : p.down },
      })),
      markLine: { silent: true, symbol: 'none', data: [{ yAxis: 0 }], lineStyle: { color: p.faint }, label: { show: false } },
    }],
  }));
  return judged.length;
}

function decisionRow(d) {
  const r = d.review;
  const outcome = r.matured
    ? el('span', { class: r.right === true ? 'up' : r.right === false ? 'down' : 'dim', text: r.right === true ? 'RIGHT' : r.right === false ? 'WRONG' : 'NO PRICES' })
    : el('span', { class: 'dim', text: `OPEN → ${r.horizon_end}` });
  const measure = d.action === 'override'
    ? `${num(r.exposure * 100, 0)}% vs anchor ${present(r.anchor_exposure) ? `${num(r.anchor_exposure * 100, 0)}%` : DASH} · ${present(r.value_bp) ? `${r.value_bp > 0 ? '+' : ''}${num(r.value_bp, 0)}bp` : DASH}`
    : `${pct(r.return_pct, 1)} · index ${pct(r.index_pct, 1)} · ${present(r.excess_pct) ? `${r.excess_pct > 0 ? '+' : ''}${num(r.excess_pct, 1)} pp` : DASH}`;
  return el('tr', {}, [
    el('td', { text: d.date }),
    el('td', {}, [d.ticker === 'SPX' ? el('span', { text: 'SPX' }) : el('a', { href: tickerHref(d.ticker), text: d.ticker })]),
    el('td', { class: 'journal-action', text: d.action.toUpperCase() }),
    el('td', { class: 'wrap-cell', text: d.reason || '' }),
    el('td', { text: `${r.horizon_days}d` }),
    el('td', { text: measure }),
    el('td', {}, [outcome]),
  ]);
}

function checkpointList(points) {
  if (!points.length) return el('div', { class: 'dim', text: 'No checkpoint ahead or due.' });
  return el('div', {}, points.map((c) => el('div', { class: `brief-event${c.due ? ' journal-due' : ''}` }, [
    el('span', { class: 'brief-event-when dim', text: `${c.date}${c.due ? ' · DUE' : ''}` }),
    el('span', { class: 'brief-event-title' }, [c.ticker === 'SPX' ? 'SPX' : el('a', { href: tickerHref(c.ticker), text: c.ticker }), ` ${c.text}`]),
    el('span', { class: 'brief-event-figure dim', text: `${c.action} ${c.decision_date}` }),
  ])));
}

function howTo(data) {
  return [
    `The log is ${data.source}: one [[decision]] per decision -- date, ticker (omit for an override), action (enter, add, trim, exit, pass or override), reason, horizon_days, exposure (overrides), checkpoints. Write it when the decision is made and never edit it; a change of mind is a new entry.`,
    'Review: an entry or add is right if the name beat the index over its horizon; a trim, exit or pass is right if it did not. An override is right if holding its exposure instead of the systematic anchor\'s added return: the daily difference in exposure times the index return, summed over the horizon. Until the horizon passes a decision is open and only its return so far is shown.',
    'Holdings are not connected yet: the log records decisions, not positions.',
  ];
}

export default function renderJournal(root, data) {
  const s = data.summary;
  root.append(metaRow(`JOURNAL · ${s.decisions} DECISIONS · ${s.open} OPEN · AS OF ${data.as_of}`, howTo(data)));
  if (data.example) root.append(el('div', { class: 'notice', text: `EXAMPLE LOG (${data.source}): these entries illustrate the page and are not decisions anyone made. The published build reads config/journal.toml.` }));
  (data.problems || []).forEach((p) => root.append(el('div', { class: 'gap', text: p })));
  root.append(el('div', { class: 'stat-strip' }, [
    stat('DECISIONS', String(s.decisions), `${s.matured} past their horizon · ${s.open} open`),
    stat('NAMES · HIT RATE', rate(s.names), `${s.names.right} of ${s.names.judged} judged · mean ${s.mean_matured_excess_pct !== null ? `${s.mean_matured_excess_pct > 0 ? '+' : ''}${num(s.mean_matured_excess_pct, 1)} pp` : DASH} vs index`),
    stat('OVERRIDES · HIT RATE', rate(s.overrides), `${s.overrides.right} of ${s.overrides.judged} judged · ${s.overrides.value_bp > 0 ? '+' : ''}${num(s.overrides.value_bp, 0)}bp vs anchor`),
    stat('BY ACTION', Object.keys(s.by_action).length ? '' : DASH,
      Object.entries(s.by_action).map(([a, r]) => `${a} ${rate(r)} (${r.judged})`).join(' · ') || 'nothing judged yet'),
  ]));
  if (!data.decisions.length) {
    root.append(card('NO DECISIONS LOGGED YET', null, el('div', { class: 'dim', text: `Add the first [[decision]] to ${data.source}; the format is in the file's header and under METHOD above.` })));
    return;
  }
  const chartNode = el('div', { class: 'chart short' });
  root.append(el('div', { class: 'grid two journal-top' }, [
    card('OUTCOMES · PAST THEIR HORIZON', el('span', { class: 'dim', text: 'names: pp vs index · overrides: pp vs anchor' }), [chartNode]),
    card('CHECKPOINTS', el('span', { class: 'dim', text: 'ahead, and due within two weeks' }), [checkpointList(data.open_checkpoints)]),
  ]));
  requestAnimationFrame(() => { if (!outcomeChart(chartNode, data.decisions)) chartNode.replaceChildren(el('div', { class: 'dim', text: 'No decision has reached its horizon yet.' })); });
  root.append(card('DECISIONS', null, el('div', { class: 'table-scroll' }, [
    el('table', { class: 'data journal-table' }, [
      el('thead', {}, [el('tr', {}, ['DATE', 'NAME', 'ACTION', 'REASON', 'HORIZON', 'SINCE / OVER HORIZON', 'OUTCOME'].map((h) => el('th', { text: h })))]),
      el('tbody', {}, data.decisions.map(decisionRow)),
    ]),
  ])));
}
