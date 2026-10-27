// RISK: STRESS COUNT. Nine yes/no conditions in five groups, counted. Each vote's
// reading and line are shown, an unknown vote reads "no reading" and never counts
// as off, and the card says in its own words that it describes the market, not
// where it goes next.

import { el, card, num, tag, gap, DASH } from '../fmt.js';
import { render } from '../charts.js';
import { rangeSwitch, sliceRange, initialRange } from '../risk-range.js';
import * as M from '../stress-model.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);

function voteNode(vote) {
  const state = M.voteState(vote);
  const mark = state === 'on' ? '●' : state === 'off' ? '○' : DASH;
  const stamp = vote.frequency === 'weekly' && vote.as_of ? ` · week of ${vote.as_of}` : '';
  return el('li', { class: `stress-vote ${state}` }, [
    el('span', { class: 'stress-mark', text: mark }),
    el('span', { class: 'stress-vote-body' }, [
      el('span', { class: 'stress-vote-label', text: vote.label }),
      el('span', { class: 'dim stress-vote-reading', text: `${M.voteReading(vote)}${stamp}` }),
    ]),
  ]);
}

function groupNode(group) {
  const tone = M.groupTone(group);
  return el('div', { class: `stress-group ${tone}` }, [
    el('div', { class: 'stress-group-head' }, [
      el('span', { class: 'stress-group-label', text: group.label }),
      tag(M.groupText(group), tone),
    ]),
    el('ul', { class: 'stress-votes' }, group.votes.map(voteNode)),
  ]);
}

function historyChart(node, stress, range) {
  const h = sliceRange(stress.history.dates, { raw: stress.history.raw }, range);
  render(node, (option, p) => ({
    ...option,
    grid: { left: 30, right: 12, top: 8, bottom: 22 },
    tooltip: { ...option.tooltip, trigger: 'axis' },
    xAxis: { ...option.xAxis, data: h.dates },
    yAxis: { ...option.yAxis, min: 0, max: stress.total, interval: 1, axisLabel: { color: p.dim, fontSize: 9 } },
    series: [{
      name: 'votes on', type: 'line', step: 'end', data: h.raw, showSymbol: false, lineStyle: { width: 1.3, color: p.text },
      markLine: stress.reference ? { silent: true, symbol: 'none', data: [{ yAxis: stress.reference }],
        lineStyle: { color: p.faint, type: 'dashed' }, label: { show: false } } : undefined,
    }],
  }));
}

export default function stressCard(stress) {
  const head = el('span', { class: 'dim', text: 'a count of conditions · not a forecast' });
  if (!stress || !stress.groups?.length) {
    return gap(`STRESS COUNT · not computed this session${stress?.error ? `: ${stress.error}` : ''}.`);
  }
  const reference = M.referenceText(stress);
  const change = M.changeText(stress);
  const stale = M.staleInputs(stress);
  const started = M.firstKnown(stress.history);
  const chartNode = el('div', { class: 'chart short' });
  let range = initialRange(stress.history.dates, '1Y');
  requestAnimationFrame(() => historyChart(chartNode, stress, range));
  const missing = stress.missing_sectors?.length ? `Sector funds missing this build: ${stress.missing_sectors.join(', ')}. ` : '';
  return card('STRESS COUNT', head, [
    el('div', { class: 'anchor-head' }, [
      el('span', { class: 'anchor-value', text: M.countText(stress) }),
      reference ? tag(reference, present(stress.raw) && stress.raw >= stress.reference ? 'warn' : 'dim') : null,
      el('span', { class: 'dim', text: [change, `as of ${stress.as_of}`].filter(Boolean).join(' · ') }),
    ]),
    el('div', { class: 'chart-head' }, [
      el('span', { class: 'dim', text: `VOTES ON, DAILY${started ? ` · counted from ${started}` : ''} · dashed: reference line` }),
      rangeSwitch(stress.history.dates, range, (label) => { range = label; historyChart(chartNode, stress, range); }),
    ]),
    chartNode,
    el('div', { class: 'stress-groups' }, stress.groups.map(groupNode)),
    el('p', { class: 'dim stress-note', text: `${stress.note ?? ''} ${missing}${stale.length ? `Older than ten days: ${stale.map((s) => `${s.label} (${s.as_of})`).join('; ')}. ` : ''}Votes and lines are fixed in config; ${num(stress.total, 0)} votes in ${stress.groups.length} groups.` }),
  ]);
}
