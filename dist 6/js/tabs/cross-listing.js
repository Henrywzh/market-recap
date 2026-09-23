import { el, card, table, num, pct, dirClass, sectionTitle, notice, DASH } from '../fmt.js';
import { render, SERIES_COLORS } from '../charts.js';

function stat(label, value, note, cls) {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls || ''}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

function diagnosticsTable(pair) {
  const d = pair.diagnostics;
  const rows = [
    ['Sessions', d.sessions, `since ${pair.first_session}`],
    ['Level dispersion', `${num(d.level_sd_pp)} pp`, 'standard deviation of the premium itself'],
    ['Daily change dispersion', `${num(d.daily_change_sd_pp)} pp`,
      'larger than the level dispersion means day-to-day noise, not a moving dislocation'],
    ['Autocorrelation (1 day)', num(d.autocorr_1d, 3),
      'a real dislocation persists; near zero or negative points at a session gap'],
    ['corr(Δpremium, US leg return)', num(d.corr_change_vs_us_leg, 3), 'how much of the move is just the US line'],
    ['corr(Δpremium, home leg return)', num(d.corr_change_vs_home_leg, 3), 'the mirror image, from the stale leg'],
  ];
  return table(['DIAGNOSTIC', 'VALUE', 'WHAT IT SAYS'], rows.map(([a, b, c]) => el('tr', {}, [
    el('td', { text: a }),
    el('td', { text: b === null || b === undefined ? DASH : String(b) }),
    el('td', { class: 'wrap-cell dim', text: c }),
  ])));
}

function overnightTable(pair) {
  const d = pair.diagnostics;
  const lead = d.corr_us_today_vs_home_next;
  const same = d.corr_us_today_vs_home_today;
  const leads = lead !== null && same !== null && lead > same;
  return [
    table(['MEASURE', 'CORRELATION'], [
      el('tr', { class: leads ? 'emphasis' : '' }, [
        el('td', { text: `${pair.us_ticker} return today vs ${pair.home_ticker} return NEXT session` }),
        el('td', { class: dirClass(lead), text: num(lead, 3) }),
      ]),
      el('tr', {}, [
        el('td', { text: `${pair.us_ticker} return today vs ${pair.home_ticker} return same date` }),
        el('td', { class: dirClass(same), text: num(same, 3) }),
      ]),
    ]),
    el('div', { class: 'note-text' }, [
      leads
        ? `The cross-session correlation is the higher of the two, which is what the ${pair.home_close_lead_hours}-hour `
          + `gap implies: ${pair.home_market} has already closed when New York trades, so today's US `
          + `session is information the home market prices tomorrow. Read the pair that way rather than as an arbitrage.`
        : 'The two correlations do not separate here, so this pair shows no clear lead-lag relationship.',
    ]),
  ];
}

export default function renderCrossListing(root, data) {
  root.append(sectionTitle('CROSS-LISTING', 'ONE COMPANY, TWO LISTINGS'));
  root.append(notice(data.note));

  if (!data.pairs.length) {
    root.append(el('div', { class: 'gap', text: 'No cross-listing pairs resolved in this build.' }));
    return;
  }

  data.pairs.forEach((pair) => {
    const l = pair.latest;
    root.append(sectionTitle(pair.label, `${pair.us_ticker} vs ${pair.home_ticker} · ${pair.home_market}`));

    root.append(el('div', { class: 'stat-strip' }, [
      stat('PREMIUM TO HOME LINE', pct(l.premium_pct), `${l.percentile}th percentile of its own history`, dirClass(l.premium_pct)),
      stat(`${pair.us_ticker} CLOSE`, `$${num(l.us_price)}`, pair.as_of),
      stat('HOME LINE IN USD', `$${num(l.home_usd_equivalent)}`, `${num(l.home_price, 0)} at ${num(l.fx)} ${pair.fx_note}`),
      stat('MEAN SINCE LISTING', pct(l.mean_pct), `${pair.diagnostics.sessions} sessions`),
      stat('DEPOSITARY RATIO', pair.ratio_text, 'from the issuer filing'),
    ]));

    // The ratio is the one input that can silently zero the whole panel, so
    // its provenance is on the page, not buried in a tooltip.
    root.append(card('RATIO PROVENANCE', null, [
      el('div', { class: 'note-text', text: pair.ratio_source || 'not recorded' }),
      pair.ratio_url ? el('div', { class: 'note-text' }, [
        el('a', { href: pair.ratio_url, target: '_blank', rel: 'noopener noreferrer', text: pair.ratio_url }),
      ]) : null,
    ]));

    const premiumNode = el('div', { class: 'chart' });
    const legsNode = el('div', { class: 'chart short' });
    root.append(card('PREMIUM TO HOME LINE (%)', null, premiumNode));
    root.append(card(`${pair.us_ticker} VS HOME LINE, BOTH IN USD PER US SHARE`, null, legsNode));

    render(premiumNode, (option, p) => ({
      ...option,
      xAxis: { ...option.xAxis, data: pair.series.dates },
      yAxis: { ...option.yAxis, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${v.toFixed(0)}%` } },
      series: [{
        type: 'line', data: pair.series.premium_pct, showSymbol: false,
        lineStyle: { width: 1.3, color: p.accent },
        markLine: {
          silent: true, symbol: 'none',
          data: [{ yAxis: 0 }, { yAxis: pair.latest.mean_pct, lineStyle: { color: p.dim } }],
          lineStyle: { color: p.faint, type: 'dashed' },
          label: { show: false },
        },
      }],
    }));

    render(legsNode, (option, p) => ({
      ...option,
      grid: { ...option.grid, bottom: 44 },
      legend: { bottom: 0, textStyle: { color: p.dim, fontSize: 10 }, icon: 'rect', itemWidth: 9, itemHeight: 9 },
      xAxis: { ...option.xAxis, data: pair.series.dates },
      series: [
        { name: pair.us_ticker, type: 'line', data: pair.series.us, showSymbol: false,
          lineStyle: { width: 1.2, color: SERIES_COLORS[0] } },
        { name: `${pair.home_ticker} in USD`, type: 'line', data: pair.series.home_usd_equivalent, showSymbol: false,
          lineStyle: { width: 1.2, color: SERIES_COLORS[1] } },
      ],
    }));

    const verdictBox = pair.verdict.daily_change_usable
      ? el('div', { class: 'notice', text: pair.verdict.statement })
      : el('div', { class: 'gap', text: pair.verdict.statement });

    root.append(el('div', { class: 'grid two' }, [
      card('IS THIS SERIES MEASURING ANYTHING?', null, [verdictBox, diagnosticsTable(pair)]),
      card('WHAT THE SESSION GAP MAKES USABLE', null, overnightTable(pair)),
    ]));
  });
}
