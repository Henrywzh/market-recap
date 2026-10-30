"""MACRO tab: commodity proxies and the last twelve inflation releases."""

from __future__ import annotations

import json
import os

import pandas as pd

from ..config import ARTIFACT_DIR, NOWCAST_EVALUATION_PATH, REGIME_QUADRANT_HISTORY_PATH
from ..compute import inflation_releases, macro_regime
from ..compute import periods as P
from ..compute import returns as R
from ..sources import fred, yahoo, inflation_state, nowcast as nowcast_source
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, history_payload, to_iso_date
from . import cpi, ppi


def _restore_release_history(ctx, config: dict) -> dict:
    """The previous release ledgers, or {} (no carried history) when they cannot be read.

    A failed MACRO build publishes no macro.json, so a restore that raised
    would fail every later build too, and commodities and PCE would go down
    with CPI/PPI history. The failure is logged instead and the ledgers start
    again from this build's observation.
    """
    base_url = (config['macro']['release_ledger']['published_base_url']
                if os.environ.get('INFLATION_PUBLISHED_STATE') == '1' else None)
    try:
        return inflation_state.load_previous(ARTIFACT_DIR / 'macro.json', published_base_url=base_url)
    except Exception as exc:
        # Named cpi_* so validate.py's optional (cpi|ppi)_fred_* pattern covers it.
        ctx.log.add(SourceRecord('cpi_fred_release_state', 'Inflation release history restore',
                                 base_url or str(ARTIFACT_DIR / 'macro.json'), status='partial',
                                 error=str(exc)[:ERROR_DETAIL_CHARS], policy='monthly_release'))
        return {}


def build(ctx) -> dict:
    config = ctx.config
    previous = _restore_release_history(ctx, config)
    releases = int(config["macro"]["releases"])
    history_years = int(config["macro"].get("history_years", 10))
    periods = list(config["periods"]["commodities"])
    history = config["periods"]["commodity_history"]

    # --- Commodities: Yahoo front-month futures and ETF proxies ------------
    symbols = dict(config["macro"]["commodities"])
    closes = yahoo.fetch_closes(symbols.values(), period=history)
    ctx.log.add(
        SourceRecord(
            "yahoo_commodities",
            "Commodity futures / ETF proxies",
            "https://finance.yahoo.com",
            to_iso_date(closes.index[-1]) if not closes.empty else None,
            rows=int(closes.shape[1]),
            status="ok" if closes.shape[1] == len(symbols) else "partial",
        )
    )

    commodity_rows = []
    for label, symbol in symbols.items():
        if symbol not in closes.columns:
            commodity_rows.append({"label": label, "symbol": symbol, "price": None, "status": "unavailable"})
            continue
        # Each instrument on its own trading days: futures, FX and ETFs keep
        # different holidays, and a shared union calendar would blank them.
        series = closes[symbol].dropna()
        row = {
            "label": label,
            "symbol": symbol,
            "price": clean_float(series.iloc[-1], 2),
            "status": "ok",
        }
        row |= {k: clean_float(v, 2) for k, v in R.period_returns(series, periods).items()}
        row["history"] = history_payload(series, years=history_years, digits=2)
        commodity_rows.append(row)

    # --- Inflation: the last twelve monthly prints -------------------------
    # Displayed as the publisher's own transform (YoY, MoM or a level), never
    # silently converted between them.
    collected: dict[str, pd.Series] = {}
    inflation_rows = []
    for spec in config["macro"]["inflation"]:
        try:
            frame, url = fred.fetch_series(spec["series_id"])
        except Exception as exc:
            ctx.log.add(
                SourceRecord(
                    f"fred_{spec['series_id'].lower()}", spec["label"],
                    f"https://fred.stlouisfed.org/series/{spec['series_id']}",
                    status="error", error=str(exc)[:ERROR_DETAIL_CHARS], policy="monthly_release",
                )
            )
            inflation_rows.append(
                {"label": spec["label"], "unit": spec["unit"],
                 "series_id": spec["series_id"], "values": [], "status": "unavailable"}
            )
            continue

        series = frame.set_index("date")["value"].sort_index()
        display = spec["display"]
        # By date: a month the agency never published leaves the changes that
        # span it blank instead of comparing across two periods.
        transformed = P.transform(series, display if display in ("yoy", "mom") else "level")
        collected[spec["series_id"]] = transformed.dropna()

        ctx.log.add(
            SourceRecord(
                f"fred_{spec['series_id'].lower()}", spec["label"], url,
                to_iso_date(series.index[-1]), rows=len(series), policy="monthly_release",
            )
        )
        inflation_rows.append(
            {"label": spec["label"], "unit": spec["unit"],
             "series_id": spec["series_id"], "status": "ok"}
        )

    # Lay every series on one month axis rather than taking each one's own last
    # twelve values and labelling them with the first series' months. These
    # publishers do not share a release lag -- the Dallas Fed's trimmed-mean
    # series can run a month behind BEA's -- and a row shifted one column
    # against its own header is wrong in a way nothing on the page would show.
    months: list[str] = []
    if collected:
        axis = sorted({stamp for series in collected.values() for stamp in series.index})
        axis = axis[-releases:]
        months = [stamp.strftime("%Y-%m") for stamp in axis]
        for row in inflation_rows:
            series = collected.get(row["series_id"])
            if series is None:
                row["values"] = []
                continue
            aligned = series.reindex(axis)
            row["values"] = [clean_float(v, 2) for v in aligned.to_numpy()]
            # Monthly already: nothing to thin, so the daily window covers it all.
            row["history"] = history_payload(series, years=history_years, digits=2, daily_days=366 * history_years)
            # A series that has not printed the latest month says so, instead
            # of borrowing the month above it.
            row["latest_month"] = series.index[-1].strftime("%Y-%m") if len(series) else None

    regime_cfg = config['macro']['regime']
    growth_id = regime_cfg['growth_series']
    regime = {'points': [], 'latest': None}
    growth = pd.Series(dtype=float)
    try:
        frame, url = fred.fetch_series(growth_id)
        growth = frame.set_index('date')['value'].sort_index()
        regime = macro_regime.build(growth, collected.get(regime_cfg['inflation_series'], pd.Series(dtype=float)),
                                    months=int(regime_cfg['path_months']), change_months=int(regime_cfg['change_months']))
        ctx.log.add(SourceRecord('fred_macro_regime', 'Chicago Fed activity index', url,
                                 to_iso_date(growth.index[-1]) if not growth.empty else None,
                                 rows=len(growth), status='ok' if regime['points'] else 'partial', policy='monthly_release'))
    except Exception as exc:
        ctx.log.add(SourceRecord('fred_macro_regime', 'Chicago Fed activity index',
                                 f'https://fred.stlouisfed.org/series/{growth_id}', status='partial',
                                 error=str(exc)[:ERROR_DETAIL_CHARS], policy='monthly_release'))
    regime.update({'growth_series': growth_id, 'inflation_series': regime_cfg['inflation_series'],
                   'change_months': int(regime_cfg['change_months'])})
    gdp = None
    try:
        gdp_frame, url = fred.fetch_series(regime_cfg['gdp_series'])
        values = gdp_frame.set_index('date')['value'].dropna().sort_index()
        if not values.empty:
            gdp = {'label': 'Real GDP growth · annualized', 'value': clean_float(values.iloc[-1], 2),
                   'prior': clean_float(values.iloc[-2], 2) if len(values) > 1 else None,
                   'period': to_iso_date(values.index[-1]), 'unit': '% SAAR'}
        ctx.log.add(SourceRecord('fred_macro_regime_gdp', 'Real GDP growth', url,
                                 to_iso_date(values.index[-1]) if not values.empty else None,
                                 rows=len(values), status='ok' if gdp else 'partial', policy='quarterly_release'))
    except Exception as exc:
        ctx.log.add(SourceRecord('fred_macro_regime_gdp', 'Real GDP growth',
                                 f"https://fred.stlouisfed.org/series/{regime_cfg['gdp_series']}",
                                 status='partial', error=str(exc)[:ERROR_DETAIL_CHARS], policy='quarterly_release'))

    regime_nowcast = _regime_nowcast(ctx, regime, growth, collected.get(regime_cfg['inflation_series'], pd.Series(dtype=float)),
                                     regime_cfg, previous.get('regime_nowcast') or {},
                                     to_iso_date(closes.index[-1]) if not closes.empty else None)

    # The same map as known at the time: archived month-end reads, then the ledger.
    try:
        history = json.loads(REGIME_QUADRANT_HISTORY_PATH.read_text())['rows']
    except (OSError, ValueError, KeyError):
        history = []
    first = (regime.get('points') or [{}])[0].get('month')
    regime_realtime = {'points': macro_regime.realtime_points(history, regime_nowcast.get('ledger') or [], first)}

    return inflation_releases.attach({
        "as_of": to_iso_date(closes.index[-1]) if not closes.empty else None,
        "commodities": {"periods": periods, "rows": commodity_rows},
        "inflation": {"months": months, "releases": releases, "rows": inflation_rows},
        "regime": regime,
        "regime_gdp": gdp,
        "regime_nowcast": regime_nowcast,
        "regime_realtime": regime_realtime,
        "cpi": cpi.build(ctx),
        "ppi": ppi.build(ctx),
        "note": (
            "Commodity prices are Yahoo front-month futures or ETF proxies, not LBMA/EIA spot "
            "prints. Inflation figures are the current FRED vintage: they reflect revisions "
            "published since the original release, so they are a release table, not a "
            "point-in-time record of what was known on the day. Every row is laid on one shared "
            "month axis, so a series its publisher has not updated yet shows a blank in the last "
            "column rather than being shifted a month to fill it."
        ),
    }, previous)


def _regime_nowcast(ctx, regime: dict, growth: pd.Series, core_yoy: pd.Series, cfg: dict, previous: dict,
                    as_of: str | None) -> dict:
    """The map's NOW point, GDPNow, the carried daily ledger and the archived evaluation."""
    cleveland, ads = pd.DataFrame(), pd.Series(dtype=float)
    try:
        cleveland = nowcast_source.core_pce_nowcasts()
        ctx.log.add(SourceRecord('nowcast_cleveland', 'Cleveland Fed core PCE nowcast', nowcast_source.CLEVELAND_PAGE,
                                 to_iso_date(cleveland['asof'].max()) if not cleveland.empty else None, rows=len(cleveland),
                                 status='ok' if not cleveland.empty else 'partial', policy='nowcast'))
    except Exception as exc:
        ctx.log.add(SourceRecord('nowcast_cleveland', 'Cleveland Fed core PCE nowcast', nowcast_source.CLEVELAND_PAGE,
                                 status='partial', error=str(exc)[:ERROR_DETAIL_CHARS], policy='nowcast'))
    try:
        ads = nowcast_source.ads_daily()
        ctx.log.add(SourceRecord('nowcast_ads', 'Philadelphia Fed ADS index', nowcast_source.ADS_PAGE,
                                 to_iso_date(ads.index.max()) if not ads.empty else None, rows=len(ads),
                                 status='ok' if not ads.empty else 'partial', policy='nowcast'))
    except Exception as exc:
        ctx.log.add(SourceRecord('nowcast_ads', 'Philadelphia Fed ADS index', nowcast_source.ADS_PAGE,
                                 status='partial', error=str(exc)[:ERROR_DETAIL_CHARS], policy='nowcast'))
    result = macro_regime.nowcast(regime, growth, core_yoy, cleveland, ads, change_months=int(cfg['change_months']))
    gdpnow = None
    try:
        frame, url = fred.fetch_series(cfg['gdpnow_series'])
        values = frame.set_index('date')['value'].dropna().sort_index()
        if not values.empty:
            gdpnow = {'label': 'GDPNow · current quarter', 'value': clean_float(values.iloc[-1], 2),
                      'period': to_iso_date(values.index[-1]), 'unit': '% SAAR'}
        ctx.log.add(SourceRecord('fred_macro_regime_gdpnow', 'Atlanta Fed GDPNow', url,
                                 to_iso_date(values.index[-1]) if not values.empty else None, rows=len(values),
                                 status='ok' if gdpnow else 'partial', policy='quarterly_release'))
    except Exception as exc:
        ctx.log.add(SourceRecord('fred_macro_regime_gdpnow', 'Atlanta Fed GDPNow',
                                 f"https://fred.stlouisfed.org/series/{cfg['gdpnow_series']}", status='partial',
                                 error=str(exc)[:ERROR_DETAIL_CHARS], policy='quarterly_release'))
    result['gdpnow'] = gdpnow
    result['ledger'] = macro_regime.update_ledger(previous.get('ledger') or [], result, regime, as_of)
    try:
        result['evaluation'] = json.loads(NOWCAST_EVALUATION_PATH.read_text())
    except (OSError, ValueError):
        result['evaluation'] = None
    result['sources'] = {'cleveland': nowcast_source.CLEVELAND_PAGE, 'ads': nowcast_source.ADS_PAGE,
                         'gdpnow': f"https://fred.stlouisfed.org/series/{cfg['gdpnow_series']}"}
    return result
