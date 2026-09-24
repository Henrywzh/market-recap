// EARNINGS (under CATALYSTS): FactSet's Earnings Insight figures, the daily
// bottom-up revision tracker built here, and the reporting season so far.
// Every figure carries its date and how many companies it covers.

import { el, card, table, num, pct, sectionTitle, notice, periodSwitch, DASH } from '../fmt.js';
import { multiLine } from '../charts.js';

const WINDOWS = ['7d', '30d', '60d', '90d'];

function dirCls(value) {
  if (value === null || value === undefined) return 'dim';
  return value > 0 ? 'up' : value < 0 ? 'down' : 'flat';
}

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function link(url, text) {
  return url ? el('a', { href: url, target: '_blank', rel: 'noopener', text }) : el('span', { text });
}

function quarterText(q) {
  const m = /^(\d{4})Q([1-4])$/.exec(q || '');
  return m ? `Q${m[2]} ${m[1]}` : (q || DASH);
}

function factsetCard(f) {
  const body = [];
  const snap = f.snapshot;
  if (snap) {
    const premium = snap.forward_12m_pe && snap.forward_12m_pe_10y_avg
      ? (snap.forward_12m_pe / snap.forward_12m_pe_10y_avg - 1) * 100 : null;
    body.push(el('div', { class: 'earn-sub' }, [
      `SEASON SNAPSHOT · ${quarterText(snap.reference_quarter)} · `,
      link(snap.source_url, `article of ${snap.report_date}`),
    ]));
    body.push(el('div', { class: 'stat-strip' }, [
      stat('EARNINGS GROWTH Y/Y', pct(snap.blended_earnings_growth_yoy, 1), 'blended: actuals + estimates', dirCls(snap.blended_earnings_growth_yoy)),
      stat('REVENUE GROWTH Y/Y', pct(snap.blended_revenue_growth_yoy, 1), 'blended', dirCls(snap.blended_revenue_growth_yoy)),
      stat('EPS BEAT RATE', snap.eps_beat_rate == null ? DASH : `${num(snap.eps_beat_rate, 0)}%`, snap.eps_surprise_pct == null ? '' : `aggregate surprise ${pct(snap.eps_surprise_pct, 1)}`),
      stat('REVENUE BEAT RATE', snap.revenue_beat_rate == null ? DASH : `${num(snap.revenue_beat_rate, 0)}%`, snap.revenue_surprise_pct == null ? '' : `aggregate surprise ${pct(snap.revenue_surprise_pct, 1)}`),
      stat('FORWARD 12M P/E', snap.forward_12m_pe == null ? DASH : `${num(snap.forward_12m_pe, 1)}×`,
        snap.forward_12m_pe_10y_avg == null ? '' : `10-year average ${num(snap.forward_12m_pe_10y_avg, 1)}× (${pct(premium, 0)})`),
    ]));
  }
  const rev = f.revision;
  if (rev) {
    const typical5 = (rev.typical || []).find((t) => t.years === 5);
    body.push(el('div', { class: 'earn-sub' }, [
      `ESTIMATE REVISION · ${quarterText(rev.reference_quarter)}${rev.window ? ` · ${rev.window}` : ''} · `,
      link(rev.source_url, `article of ${rev.report_date}`),
    ]));
    body.push(el('div', { class: 'stat-strip' }, [
      stat('QUARTER BOTTOM-UP EPS', pct(rev.quarterly_eps_revision_pct, 1),
        rev.prior ? `prior note ${pct(rev.prior.quarterly_eps_revision_pct, 1)} (${rev.prior.report_date})` : '', dirCls(rev.quarterly_eps_revision_pct)),
      stat('CALENDAR-YEAR EPS', pct(rev.annual_eps_revision_pct, 1),
        rev.prior && rev.prior.annual_eps_revision_pct != null ? `prior note ${pct(rev.prior.annual_eps_revision_pct, 1)}` : '', dirCls(rev.annual_eps_revision_pct)),
      stat('TYPICAL (5Y AVERAGE)', typical5 ? pct(typical5.value, 1) : DASH, typical5 ? `same window; this quarter ${num(Math.abs(rev.quarterly_eps_revision_pct - typical5.value), 1)} pp ${rev.quarterly_eps_revision_pct >= typical5.value ? 'above' : 'below'} it` : 'not stated in this note'),
      stat('LONGER HISTORY', (rev.typical || []).filter((t) => t.years !== 5).map((t) => `${t.years}y ${pct(t.value, 1)}`).join(' · ') || DASH, 'average revision, same window'),
    ]));
    const named = Object.entries(rev.sectors || {});
    if (named.length) {
      body.push(el('div', { class: 'note-text' }, [
        'Sectors FactSet names: ',
        ...named.flatMap(([s, v], i) => [i ? ' · ' : '', el('span', { class: dirCls(v), text: `${s} ${pct(v, 1)}` })]),
        '. Only the ones the article names; the rest are not published in the text.',
      ]));
    }
  }
  const chartNode = el('div', { class: 'chart short' });
  const history = el('div', { class: 'grid two' }, [
    el('div', {}, [el('div', { class: 'earn-sub', text: 'FORWARD 12M P/E, AS FACTSET PRINTS IT' }), chartNode]),
    el('div', {}, [
      el('div', { class: 'earn-sub', text: 'BY QUARTER (LAST PRINT OF EACH SEASON)' }),
      table(['QUARTER', 'BEAT RATE', 'GROWTH Y/Y', 'EPS REVISION (LAST NOTE)'], (() => {
        const revByQ = new Map((f.revision_history || []).map((r) => [r.quarter, r]));
        const quarters = [...new Set([...(f.season_history || []).map((r) => r.quarter), ...revByQ.keys()])].sort().slice(-8).reverse();
        const seasonByQ = new Map((f.season_history || []).map((r) => [r.quarter, r]));
        return quarters.map((q) => {
          const s = seasonByQ.get(q) || {};
          const r = revByQ.get(q) || {};
          return el('tr', {}, [
            el('td', { text: quarterText(q) }),
            el('td', { text: s.eps_beat_rate == null ? DASH : `${num(s.eps_beat_rate, 0)}%` }),
            // Before a season has a beat rate, FactSet's growth figure is its estimate.
            el('td', { class: dirCls(s.blended_earnings_growth_yoy), text: pct(s.blended_earnings_growth_yoy, 1) + (s.eps_beat_rate == null && s.blended_earnings_growth_yoy != null ? ' expected' : '') }),
            el('td', { class: dirCls(r.quarterly_eps_revision_pct), text: pct(r.quarterly_eps_revision_pct, 1) }),
          ]);
        });
      })()),
    ]),
  ]);
  body.push(history);
  body.push(el('div', { class: 'note-text', text: `${f.articles} FactSet articles ${f.first_date} to ${f.newest_date}; figures read from the article text, not FactSet's data feed. FactSet calendarizes and uses its own consensus.` }));
  const node = card('FACTSET EARNINGS INSIGHT', el('span', { class: 'dim', text: `newest article ${f.newest_date || DASH}` }), body);
  requestAnimationFrame(() => {
    const pe = (f.forward_pe || []).slice(-104);
    if (pe.length) {
      multiLine(chartNode, pe.map((r) => r.date), {
        'Forward 12M P/E': pe.map((r) => r.forward_12m_pe),
        '10-year average': pe.map((r) => r.ten_year_average),
      });
    }
  });
  return node;
}

function trackerCard(t, asOf) {
  const periods = ['quarter', 'year', 'next_year'].filter((k) => t[k]);
  const summary = table(['PERIOD', 'COMPANIES', ...WINDOWS.map((w) => w.toUpperCase()), 'REVISED UP / DOWN (30D)'],
    periods.map((k) => {
      const p = t[k];
      return el('tr', {}, [
        el('td', { text: p.label }),
        el('td', { class: 'dim', text: `${p.companies} of ${t.members}` }),
        ...WINDOWS.map((w) => el('td', { class: dirCls(p.windows[w]?.pct), text: pct(p.windows[w]?.pct, 2) })),
        el('td', { text: `${p.breadth_30d.up} / ${p.breadth_30d.down}` }),
      ]);
    }));
  const sectorHost = el('div');
  const draw = (label) => {
    const p = periods.map((k) => t[k]).find((x) => x.label === label);
    const movers = p.movers_30d || { up: [], down: [] };
    sectorHost.replaceChildren(
      table(['SECTOR', 'COMPANIES', '30D', '90D', 'LARGEST 30D MOVE WITHIN SECTOR'], p.sectors.map((s) => el('tr', {}, [
        el('td', { text: s.sector }),
        el('td', { class: 'dim', text: String(s.companies) }),
        el('td', { class: dirCls(s['30d']), text: pct(s['30d'], 2) }),
        el('td', { class: dirCls(s['90d']), text: pct(s['90d'], 2) }),
        el('td', { class: 'dim', text: s.leader_30d ? `${s.leader_30d.symbol} ${s.leader_30d.pp >= 0 ? '+' : ''}${num(s.leader_30d.pp, 2)} pp of the sector's move` : DASH }),
      ]))),
      el('div', { class: 'note-text' }, [
        `Moved the index most over 30 days (pp of the ${p.label} aggregate): `,
        ...[...movers.up, ...movers.down].flatMap((m, i) => [i ? ' · ' : '', el('span', { class: dirCls(m.pp), text: `${m.symbol} ${m.pp >= 0 ? '+' : ''}${num(m.pp, 2)}` })]),
        p.fiscal_period_ends ? `. Fiscal periods included end ${p.fiscal_period_ends[0]} to ${p.fiscal_period_ends[1]}.` : '.',
      ]),
    );
  };
  const labels = periods.map((k) => t[k].label);
  draw(labels[0]);
  return card('BOTTOM-UP REVISIONS · DAILY', periodSwitch(labels, labels[0], draw), [
    summary,
    sectorHost,
    el('div', { class: 'note-text', text: `Built here on ${asOf} from Yahoo's consensus trend for ${t.with_estimates} of ${t.members} members, weighted by float-adjusted shares. Fiscal periods count toward the calendar period holding most of their months, without pro-rating. The 90-day figure is comparable to, not the same as, FactSet's.` }),
  ]);
}

function seasonCard(s) {
  const reportedShare = s.universe ? (s.reported / s.universe) * 100 : null;
  return card(`REPORTING SEASON · ${s.quarter}`, el('span', { class: 'dim', text: `reports since ${s.first_day}` }), [
    el('div', { class: 'stat-strip' }, [
      stat('REPORTED', `${s.reported} of ${s.universe}`, `${num(reportedShare, 0)}% · ${s.upcoming_next_5_sessions} due in the next 5 sessions`),
      stat('BEAT EPS CONSENSUS', s.beat_share == null ? DASH : `${num(s.beat_share, 0)}%`, `${s.beat} beat · ${s.in_line} in line · ${s.miss} missed`),
      stat('MEDIAN SURPRISE', pct(s.median_surprise_pct, 1), `aggregate ${pct(s.aggregate_surprise_pct, 1)}`, dirCls(s.median_surprise_pct)),
      stat('EPS GROWTH Y/Y', pct(s.growth_yoy_pct, 1), `${s.growth_companies} companies with a year-ago EPS captured before they reported`, dirCls(s.growth_yoy_pct)),
    ]),
    el('div', { class: 'grid two' }, [
      table(['SECTOR', 'REPORTED', 'BEAT'], (s.sectors || []).map((x) => el('tr', {}, [
        el('td', { text: x.sector }),
        el('td', { text: String(x.reported) }),
        el('td', { text: x.with_estimate ? `${x.beat} of ${x.with_estimate}` : DASH }),
      ]))),
      table(['LATEST', 'DATE', 'EPS VS CONSENSUS', 'SURPRISE'], (s.latest || []).slice(0, 12).map((r) => el('tr', {}, [
        el('td', { text: r.symbol }),
        el('td', { class: 'dim', text: r.date }),
        el('td', { text: `${num(r.eps, 2)} vs ${num(r.eps_forecast, 2)}` }),
        el('td', { class: dirCls(r.surprise_pct), text: pct(r.surprise_pct, 1) }),
      ]))),
    ]),
    el('div', { class: 'note-text', text: 'Nasdaq calendar (Zacks consensus and actuals); counts a fiscal quarter toward the calendar quarter it ends in, so off-cycle reporters (quarters ending July/August) start the season early. A beat is an actual strictly above consensus. Growth covers only companies whose year-ago EPS was captured before they reported; it fills in as the season goes.' }),
  ]);
}

export default function renderEarnings(root, data) {
  root.append(sectionTitle('EARNINGS', 'S&P 500 ESTIMATES AND THE REPORTING SEASON'));
  (data.notices || []).forEach((message) => root.append(notice(message)));
  if (data.factset) root.append(factsetCard(data.factset));
  if (data.tracker) root.append(trackerCard(data.tracker, data.as_of));
  if (data.season) root.append(seasonCard(data.season));
  root.append(el('div', { class: 'note-text', text: data.note || '' }));
}
