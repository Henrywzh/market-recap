"""Descriptive own-asset pressure and fixed-roster sector participation.

No fitted scores, signal probabilities, forward returns or market forecasts.
All histories stop at the artifact session; a missing roster member stays unknown.
"""
from __future__ import annotations

from datetime import date, timedelta
import statistics
import numpy as np
import pandas as pd

from ..compute.blackout import calendar_momentum
from ..config import PERIOD_TRADING_DAYS, TRADING_DAYS_PER_YEAR


# Share of the price columns a date needs to count as a session.
SESSION_COVERAGE = 0.5


def _number(value):
    return round(float(value), 4) if pd.notna(value) and np.isfinite(value) else None


def _history(frame: pd.DataFrame, sessions: int) -> dict:
    frame = frame.tail(sessions)
    return {"dates": [d.strftime("%Y-%m-%d") for d in frame.index],
            **{c: [_number(v) for v in frame[c]] for c in frame}}


def _series_percentile(series: pd.Series, window: int | None = None) -> float | None:
    clean = series.dropna()
    if window is not None:
        clean = clean.tail(window)
    if len(clean) < 10:
        return None
    return _number(clean.rank(pct=True).iloc[-1] * 100.0)


def assemble_liquidity(
    *,
    as_of: str,
    raw_prices: pd.DataFrame | None = None,
    volumes: pd.DataFrame | None = None,
    spx_constituents: list[dict] | None = None,
    catalysts: dict | None = None,
    evidence: dict | None = None,
    positioning: dict | None = None,
    risk_tiles: dict[str, dict] | None = None,
    history_sessions: int = 504,
) -> dict:
    out: dict = {"as_of": as_of}
    week = PERIOD_TRADING_DAYS["1W"]
    year = PERIOD_TRADING_DAYS["1Y"]

    # 1 & 2. Market Depth (Amihud Illiquidity 20D) & Top-10 Dollar Volume Share (20D)
    if raw_prices is not None and volumes is not None and not raw_prices.empty and not volumes.empty:
        p = raw_prices.copy().sort_index()
        v = volumes.copy().sort_index()
        p.index = pd.to_datetime(p.index)
        v.index = pd.to_datetime(v.index)
        p = p.loc[p.index <= pd.Timestamp(as_of)]
        v = v.loc[v.index <= pd.Timestamp(as_of)].reindex(p.index)
        # Members only, never every column: an index or a fund's volume would swamp the sums.
        tickers = [r["ticker"] for r in spx_constituents or [] if r.get("ticker") in p.columns and r.get("ticker") in v.columns]
        if tickers:
            p_sub = p[tickers].apply(pd.to_numeric, errors="coerce")
            v_sub = v[tickers].apply(pd.to_numeric, errors="coerce")
            dvol_bn = (p_sub * v_sub) / 1e9
            ret_pct = p_sub.pct_change().abs() * 100.0
            amihud_daily = (ret_pct / dvol_bn.where(dvol_bn > 0.01)).median(axis=1)
            amihud_20d = amihud_daily.rolling(20).mean()

            arr = np.nan_to_num(dvol_bn.to_numpy(), nan=0.0)
            k = min(10, arr.shape[1])
            top10_sum = np.partition(arr, -k, axis=1)[:, -k:].sum(axis=1)
            tot_sum = arr.sum(axis=1)
            top10_share = pd.Series(np.where(tot_sum > 0, top10_sum / tot_sum * 100.0, np.nan), index=dvol_bn.index)
            top10_20d = top10_share.rolling(20).mean()
            tot_dvol_20d = pd.Series(tot_sum, index=dvol_bn.index).rolling(20).mean()

            hist_df = pd.DataFrame({
                "amihud_20d": amihud_20d,
                "top10_share_20d": top10_20d,
                "total_dvol_bn_20d": tot_dvol_20d,
            }).dropna(how="all")
            out["amihud"] = {
                "date": hist_df.index[-1].strftime("%Y-%m-%d") if len(hist_df) else None,
                "value": _number(amihud_20d.iloc[-1]) if len(amihud_20d) else None,
                "change_1w": _number(amihud_20d.diff(week).iloc[-1]) if len(amihud_20d) > week else None,
                "pct_1y": _series_percentile(amihud_20d, year),
                "pct_10y": _series_percentile(amihud_20d),
                "unit": "% / $1B",
                "note": "20-session average of median S&P 500 |daily % return| per $1B traded. Higher means more absolute return per traded dollar; not measured order-book depth or causal price impact.",
            }
            out["concentration"] = {
                "date": hist_df.index[-1].strftime("%Y-%m-%d") if len(hist_df) else None,
                "value": _number(top10_20d.iloc[-1]) if len(top10_20d) else None,
                "change_1w": _number(top10_20d.diff(week).iloc[-1]) if len(top10_20d) > week else None,
                "pct_1y": _series_percentile(top10_20d, year),
                "pct_10y": _series_percentile(top10_20d),
                "total_dvol_bn_20d": _number(tot_dvol_20d.iloc[-1]) if len(tot_dvol_20d) else None,
                "unit": "%",
                "note": "20-session share of S&P 500 dollar volume traded in the 10 busiest names each day.",
            }
            out["micro_history"] = _history(hist_df, history_sessions)

    # 3. Buyback Blackout Window
    blackout_data = None
    if spx_constituents and (catalysts or evidence):
        as_of_dt = date.fromisoformat(as_of)
        before, after, back, ahead = 30, 2, 365, 60
        windows, scheduled, projected, missing, total = [], 0, 0, 0, 0.0
        for r in spx_constituents:
            w = float(r.get("weight") or 0.0)
            total += w
            sym = r.get("ticker")
            past = [date.fromisoformat(rx["date"][:10]) for rx in ((evidence or {}).get("names", {}).get(sym, {}).get("reactions") or []) if rx.get("date")]
            upcoming = [date.fromisoformat(ev_item["date"]) for ev_item in ((catalysts or {}).get("events") or [])
                        if ev_item.get("event_type") == "earnings" and ev_item.get("symbol") == sym and ev_item.get("date")]
            dates = sorted(set(past + upcoming))
            if not dates:
                missing += 1
                continue
            if upcoming:
                scheduled += 1
            elif len(dates) >= 2:
                gap_days = statistics.median((b - a).days for a, b in zip(dates, dates[1:]))
                nxt = dates[-1] + timedelta(days=int(min(max(gap_days, 80), 100)))
                while nxt < as_of_dt:
                    nxt += timedelta(days=int(min(max(gap_days, 80), 100)))
                dates.append(nxt)
                projected += 1
            windows.append((w, [(d - timedelta(days=before), d + timedelta(days=after)) for d in dates]))
        if total > 0 and windows:
            days = [as_of_dt + timedelta(days=n) for n in range(-back, ahead + 1)]
            share = [round(100.0 * sum(w for w, spans in windows if any(a <= day <= b for a, b in spans)) / total, 1) for day in days]
            s = pd.Series(share, index=pd.to_datetime(days))
            future = s[s.index > pd.Timestamp(as_of_dt)]
            peak_day = future.idxmax() if future.notna().any() else None
            mom = calendar_momentum([d.isoformat() for d in days], share, as_of, [1, 7])
            w7 = next((w for w in mom.get("windows", []) if w.get("key") == "7D"), {})
            blackout_data = {
                "as_of": as_of,
                "now_pct": _number(s.loc[pd.Timestamp(as_of_dt)]),
                "change_7d_pp": _number(w7.get("now_delta_pp")),
                "ahead_7d_pp": _number(w7.get("ahead_delta_pp")),
                "velocity_7d": _number(w7.get("now_velocity_pp_per_day")),
                "peak_pct": _number(future.max()) if peak_day is not None else None,
                "peak_date": peak_day.strftime("%Y-%m-%d") if peak_day is not None else None,
                "scheduled": scheduled,
                "projected": projected,
                "dates": [d.isoformat() for d in days],
                "share_pct": share,
                "note": "Estimated S&P 500 weight in earnings blackout (30 calendar days before report through 2 days after). Calendar estimate, not observed buyback flows; actual policies and trading plans differ.",
            }
    if blackout_data is None and positioning and positioning.get("blackout"):
        b = positioning["blackout"]
        w7 = next((w for w in b.get("momentum", {}).get("windows", []) if w.get("key") == "7D"), {})
        blackout_data = {
            "as_of": b.get("as_of"),
            "now_pct": _number(b.get("now_pct")),
            "change_7d_pp": _number(w7.get("now_delta_pp")),
            "ahead_7d_pp": _number(w7.get("ahead_delta_pp")),
            "velocity_7d": _number(w7.get("now_velocity_pp_per_day")),
            "peak_pct": _number(b.get("peak_pct")),
            "peak_date": b.get("peak_date"),
            "scheduled": b.get("scheduled"),
            "projected": b.get("projected"),
            "dates": b.get("dates", []),
            "share_pct": b.get("share_pct", []),
            "note": "Estimated S&P 500 weight in earnings blackout (30 calendar days before report through 2 days after).",
        }
    out["blackout"] = blackout_data

    # 4. Hedge Fund Futures Positioning (CFTC Leveraged Funds ES & NQ)
    if risk_tiles:
        es = risk_tiles.get("cftc_es")
        nq = risk_tiles.get("cftc_nq")
        out["hedge_funds"] = {
            "es": {
                "label": "S&P 500 Futures (ES)",
                "date": es.get("date") if es else None,
                "value": _number(es.get("value")) if es else None,
                "change_1w": _number(es.get("change_1w")) if es else None,
                "pct_1y": _number(es.get("pct_1y")) if es else None,
                "pct_long": _number(es.get("pct_long")) if es else None,
                "history": es.get("history") if es else None,
            },
            "nq": {
                "label": "Nasdaq-100 Futures (NQ)",
                "date": nq.get("date") if nq else None,
                "value": _number(nq.get("value")) if nq else None,
                "change_1w": _number(nq.get("change_1w")) if nq else None,
                "pct_1y": _number(nq.get("pct_1y")) if nq else None,
                "pct_long": _number(nq.get("pct_long")) if nq else None,
                "history": nq.get("history") if nq else None,
            },
            "note": "CFTC Traders in Financial Futures: leveraged-money net position as % of open interest (weekly).",
        }

    # 5. Aggregate Short Interest & Insider Buying
    if positioning:
        si = positioning.get("short_interest") or {}
        agg = si.get("aggregate") or []
        last_si = agg[-1] if agg else {}
        prev_si = agg[-2] if len(agg) >= 2 else {}
        ins = positioning.get("insiders") or {}
        weekly_ins = ins.get("weekly") or []
        out["shorts_insiders"] = {
            "settlement_date": si.get("settlement_date") or last_si.get("date"),
            "short_value_bn": _number(last_si.get("short_value_bn")),
            "short_value_change_bn": _number(last_si.get("short_value_bn") - prev_si.get("short_value_bn"))
            if last_si.get("short_value_bn") is not None and prev_si.get("short_value_bn") is not None else None,
            "median_days_to_cover": _number(last_si.get("median_days_to_cover")),
            "dtc_change": _number(last_si.get("median_days_to_cover") - prev_si.get("median_days_to_cover"))
            if last_si.get("median_days_to_cover") is not None and prev_si.get("median_days_to_cover") is not None else None,
            "rounds": agg,
            "insider_window_days": ins.get("window_days", 90),
            "insider_clusters": len(ins.get("clusters") or []),
            "insider_weekly": weekly_ins,
            "insider_read_through": (ins.get("coverage") or {}).get("read_through"),
            "note": "FINRA twice-monthly consolidated S&P 500 short interest (median days to cover & total short value) alongside strict SEC Form 4 open-market insider purchase clusters.",
        }
    return out


def assemble_fed_model(
    *,
    as_of: str,
    valuation_aggregates: dict | None,
    dgs10: pd.Series | None,
    dfii10: pd.Series | None,
    baa10y: pd.Series | None,
) -> dict | None:
    if not valuation_aggregates or not valuation_aggregates.get("dates") or not valuation_aggregates.get("series"):
        return None
    raw_dates = [d for d in valuation_aggregates["dates"] if d <= as_of]
    if not raw_dates:
        return None
    cut = len(raw_dates)
    idx = pd.to_datetime(raw_dates)

    def _align(s: pd.Series | None) -> pd.Series:
        if s is None or s.empty:
            return pd.Series(np.nan, index=idx, dtype=float)
        clean = pd.to_numeric(s, errors="coerce").dropna().sort_index()
        clean.index = pd.to_datetime(clean.index)
        clean = clean.loc[clean.index <= pd.Timestamp(as_of)]
        return clean.reindex(idx.union(clean.index)).sort_index().ffill().reindex(idx)

    y10 = _align(dgs10)
    r10 = _align(dfii10)
    baa_spread = _align(baa10y)
    baa_yield = y10 + baa_spread

    indices = []
    for entry in valuation_aggregates.get("series", []):
        if entry.get("key") not in ("SPX", "NDX"):
            continue
        pe_op = pd.Series((entry.get("pe") or [])[:cut], index=idx, dtype=float)
        pe_rep = pd.Series((entry.get("pe_reported") or [])[:cut], index=idx, dtype=float)
        ey_op = 100.0 / pe_op.where(pe_op > 0)
        ey_rep = 100.0 / pe_rep.where(pe_rep > 0)

        fwd_pe = _number((entry.get("forward_now") or {}).get("pe"))
        fwd_ey = _number(100.0 / fwd_pe) if fwd_pe and fwd_pe > 0 else None
        y10_now = _number(y10.iloc[-1])
        r10_now = _number(r10.iloc[-1])
        baa_now = _number(baa_yield.iloc[-1])

        def _basis_payload(pe_s: pd.Series, ey_s: pd.Series, name: str) -> dict:
            sp_10y = ey_s - y10
            sp_real = ey_s - r10
            sp_baa = ey_s - baa_yield
            return {
                "basis": name,
                "pe": _number(pe_s.iloc[-1]),
                "pe_pct_10y": _series_percentile(pe_s),
                "earnings_yield_pct": _number(ey_s.iloc[-1]),
                "ey_pct_10y": _series_percentile(ey_s),
                "spread_10y_pct": _number(sp_10y.iloc[-1]),
                "spread_10y_percentile": _series_percentile(sp_10y),
                "spread_real10y_pct": _number(sp_real.iloc[-1]),
                "spread_real10y_percentile": _series_percentile(sp_real),
                "spread_baa_pct": _number(sp_baa.iloc[-1]),
                "spread_baa_percentile": _series_percentile(sp_baa),
                "history": {
                    "pe": [_number(v) for v in pe_s],
                    "earnings_yield_pct": [_number(v) for v in ey_s],
                    "spread_10y_pct": [_number(v) for v in sp_10y],
                    "spread_real10y_pct": [_number(v) for v in sp_real],
                    "spread_baa_pct": [_number(v) for v in sp_baa],
                },
            }

        indices.append({
            "key": entry["key"],
            "label": entry.get("label", entry["key"]),
            "companies": entry.get("companies"),
            "forward": {
                "pe": fwd_pe,
                "earnings_yield_pct": fwd_ey,
                "spread_10y_pct": _number(fwd_ey - y10_now) if fwd_ey is not None and y10_now is not None else None,
                "spread_real10y_pct": _number(fwd_ey - r10_now) if fwd_ey is not None and r10_now is not None else None,
                "spread_baa_pct": _number(fwd_ey - baa_now) if fwd_ey is not None and baa_now is not None else None,
            },
            "operating": _basis_payload(pe_op, ey_op, "operating"),
            "reported": _basis_payload(pe_rep, ey_rep, "reported"),
        })

    return {
        "as_of": raw_dates[-1],
        "dates": raw_dates,
        "rates": {
            "dgs10_pct": _number(y10.iloc[-1]),
            "real_10y_pct": _number(r10.iloc[-1]),
            "baa_yield_pct": _number(baa_yield.iloc[-1]),
            "history": {
                "dgs10_pct": [_number(v) for v in y10],
                "real_10y_pct": [_number(v) for v in r10],
                "baa_yield_pct": [_number(v) for v in baa_yield],
            },
        },
        "indices": indices,
        "note": "Point-in-time trailing 10-year weekly P/E inverted into Earnings Yield (1/PE), compared against 10Y nominal Treasury (DGS10), 10Y TIPS real yield (DFII10), and Moody's BAA corporate yield. Operating strips below-the-line equity gains; Reported uses GAAP diluted EPS.",
    }


def assemble(closes: pd.DataFrame, *, as_of: str, cfg: dict, sector_roster: list[str], constituents: list[str] | None = None, universe_label: str = "Primary index") -> dict:
    high_window = PERIOD_TRADING_DAYS[cfg["high_period"]]
    vol_window = PERIOD_TRADING_DAYS[cfg["volatility_period"]]
    month = PERIOD_TRADING_DAYS[cfg["scale_period"]]
    keep = PERIOD_TRADING_DAYS[cfg["history_period"]]
    week = PERIOD_TRADING_DAYS["1W"]
    windows = cfg["ma_sessions"]
    rv_window = cfg["realized_vol_sessions"]
    prices = closes.copy().sort_index()
    prices.index = pd.to_datetime(prices.index)
    prices = prices.loc[prices.index <= pd.Timestamp(as_of)]
    prices = prices.loc[~prices.index.duplicated(keep="last")]
    prices = prices.loc[:, ~prices.columns.duplicated()]
    prices = prices.apply(pd.to_numeric, errors="coerce").where(lambda f: np.isfinite(f) & (f > 0))
    # A date most series have no close on is not a session (a holiday one source
    # still dated): kept, it would put a gap in every window it falls in and blank
    # each 50- and 200-session average. A missing close on a real session stays a gap.
    if len(prices.columns):
        prices = prices.loc[prices.notna().mean(axis=1) >= SESSION_COVERAGE]
    assets = []
    for spec in cfg["assets"]:
        price = prices.get(spec["symbol"], pd.Series(dtype=float))
        # Preserve gaps on the asset's calendar; do not bridge an internal missing close.
        price = price.loc[price.first_valid_index():price.last_valid_index()] if price.notna().any() else price
        frame = pd.DataFrame({"close": price})
        returns = np.log(price / price.shift(1))
        sigma = returns.rolling(vol_window).std().shift(1) * np.sqrt(month)
        dd = (price / price.rolling(high_window).max() - 1) * 100
        frame["drawdown_pct"] = dd
        frame["drawdown_sigma"] = -dd / (100 * sigma.where(sigma > 0))
        frame["monthly_sigma_pct"] = sigma * 100
        rv = returns.rolling(rv_window).std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
        frame["realized_vol_pct"] = rv
        frame["vol_percentile"] = rv.rolling(vol_window).rank(pct=True) * 100
        for window in windows:
            frame[f"ma{window}"] = price.rolling(window).mean()
            frame[f"distance_ma{window}_pct"] = (price / frame[f"ma{window}"] - 1) * 100
        last = frame.iloc[-1] if len(frame) else pd.Series(dtype=float)
        date = frame.index[-1].strftime("%Y-%m-%d") if len(frame) else None
        assets.append({**spec, "date": date, "stale": date != as_of,
                       "latest": {c: _number(last.get(c)) for c in frame},
                       "history": _history(frame, keep)})

    roster = list(dict.fromkeys(sector_roster))
    sector_prices = prices.reindex(columns=roster)
    breadth = pd.DataFrame(index=prices.index)
    members = []
    for window in windows:
        ma = sector_prices.rolling(window).mean()
        valid = sector_prices.notna() & ma.notna()
        above = sector_prices.gt(ma)
        breadth[f"above_{window}d_pct"] = (above.sum(axis=1) / len(roster) * 100).where(valid.all(axis=1)) if roster else np.nan
        breadth[f"change_{window}d_pp"] = breadth[f"above_{window}d_pct"].diff(week)
    last = breadth.iloc[-1] if len(breadth) else pd.Series(dtype=float)
    for symbol in roster:
        states = {}
        for window in windows:
            price = sector_prices[symbol]
            ma = price.rolling(window).mean()
            states[str(window)] = bool(price.iloc[-1] > ma.iloc[-1]) if len(price) and pd.notna(price.iloc[-1]) and pd.notna(ma.iloc[-1]) else None
        members.append({"symbol": symbol, "above": states})
    member_roster = list(dict.fromkeys(constituents or []))
    constituent_breadth = None
    if member_roster:
        member_prices = prices.reindex(columns=member_roster)
        history = pd.DataFrame(index=prices.index)
        for window in windows:
            ma = member_prices.rolling(window).mean()
            valid = member_prices.notna() & ma.notna()
            eligible = valid.sum(axis=1)
            above_count = (member_prices.gt(ma) & valid).sum(axis=1)
            history[f"eligible_{window}d"] = eligible
            history[f"above_{window}d_count"] = above_count
            history[f"above_{window}d_pct"] = above_count.div(eligible.where(eligible > 0)) * 100
            history[f"change_{window}d_pp"] = history[f"above_{window}d_pct"].diff(week)
        latest = history.iloc[-1] if len(history) else pd.Series(dtype=float)
        constituent_breadth = {
            "label": universe_label, "date": as_of, "roster": member_roster, "members": [],
            "latest": {c: _number(latest.get(c)) for c in history},
            "history": _history(history, keep),
            "note": "Equal-count breadth among members with a valid close and full moving-average window; coverage shown separately. Historical reconstruction uses the current roster, not historical index membership (survivorship bias). Adjusted closes; not a bottom signal.",
        }
    return {"as_of": as_of, "high_sessions": high_window, "volatility_sessions": vol_window,
            "scale_sessions": month, "realized_vol_sessions": rv_window, "ma_sessions": windows,
            "drawdown_references": cfg["drawdown_references"], "assets": assets,
            "constituent_breadth": constituent_breadth,
            "breadth": {"date": breadth.index[-1].strftime("%Y-%m-%d") if len(breadth) else None,
                        "roster": roster, "members": members,
                        "latest": {c: _number(last.get(c)) for c in breadth},
                        "history": _history(breadth, keep),
                        "note": f"Fixed {len(roster)}-sector ETF proxy shared across assets; not index constituent breadth. Omits communication services and real estate. Missing input leaves the full-roster percentage unknown."}}
