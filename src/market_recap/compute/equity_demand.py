"""Assemble the four-part equity demand pipeline and multi-layer hedge-fund monitor.

1. Investor sector demand: Households, Mutual funds, Pensions (private + federal +
   state/local), and Foreign investors from Fed Financial Accounts Z.1 (F51.1.t, FU NSA).
2. Foreign demand bridge & high-frequency supplement: Quarterly Fed corporate equities
   bridged to BEA broad equity+fund shares and monthly Treasury TIC (slt_table1.txt).
3. Corporate actual cash repurchases & authorizations: Deduplicated by CIK across SPX
   and NDX, with TTM vs 4-quarter reconciliation, buyback yield, YoY acceleration,
   execution regime (active / paused / resumed / zero), entity-level remaining
   authorizations, and dimensional inline-XBRL program disclosures.
4. Multi-layer hedge-fund flow & positioning monitor: OFR Form PF cash equities vs
   equity derivatives & prime-broker borrowing, SEC 13F constant-price share changes,
   and CFTC weekly index futures beta-hedge positioning.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import CACHE_DIR
from ..sources import equity_demand as ED_SRC
from ..sources import ofr
from ..util import clean_float, to_iso_date
from . import buybacks as BB
from . import hf_leverage as HFL


def _quarter_str(period: pd.Period) -> str:
    return f"{period.year}Q{period.quarter}"


def _quarter_end_iso(period: pd.Period) -> str:
    return period.end_time.date().isoformat()


def _series_summary(series: pd.Series, digits: int = 2) -> dict:
    clean = series.dropna()
    if clean.empty:
        return {"latest_quarter": None, "latest_bn": None, "prior_q_bn": None, "qoq_bn": None,
                "ytd_bn": None, "ttm_4q_bn": None, "prior_ttm_4q_bn": None}
    last_p = clean.index[-1]
    last_v = float(clean.iloc[-1])
    prev_v = float(clean.iloc[-2]) if len(clean) >= 2 else None
    ytd_slice = clean[clean.index.year == last_p.year]
    ttm_4q = float(clean.iloc[-4:].sum()) if len(clean) >= 4 else None
    prior_4q = float(clean.iloc[-8:-4].sum()) if len(clean) >= 8 else None
    return {
        "latest_quarter": _quarter_str(last_p),
        "latest_quarter_end": _quarter_end_iso(last_p),
        "latest_bn": clean_float(last_v, digits),
        "prior_q_bn": clean_float(prev_v, digits) if prev_v is not None else None,
        "qoq_bn": clean_float(last_v - prev_v, digits) if prev_v is not None else None,
        "ytd_quarters": int(len(ytd_slice)),
        "ytd_bn": clean_float(float(ytd_slice.sum()), digits),
        "ttm_4q_bn": clean_float(ttm_4q, digits) if ttm_4q is not None else None,
        "prior_ttm_4q_bn": clean_float(prior_4q, digits) if prior_4q is not None else None,
        "ttm_change_bn": clean_float(ttm_4q - prior_4q, digits) if ttm_4q is not None and prior_4q is not None else None,
    }


def _read_fred_cached_or_none(series_id: str) -> pd.DataFrame | None:
    path = CACHE_DIR / f"fred/{series_id}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "observation_date" not in df or series_id not in df:
        return None
    df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
    return df.dropna(subset=[series_id])


def build_sector_and_foreign_demand(cfg: dict, *, offline: bool = False) -> dict:
    z1_text, z1_meta = ED_SRC.download(
        "z1_f51_1_t_tu",
        cfg["z1_zip_url"],
        offline=offline,
        zip_member=cfg["z1_member"],
    )
    q_df = ED_SRC.quarterly_table(z1_text, first_quarter=cfg["z1_first_quarter"])
    sc = cfg["z1_series"]

    # Verify accounting identities across all quarters since 1952Q1
    cols = q_df.columns.tolist()
    total = q_df[sc["total"]]
    holder_cols = cols[17:]
    holder_sum = q_df[holder_cols].sum(axis=1, min_count=len(holder_cols))
    issuer_sum = q_df[[sc["nfc_net_issuance"], sc["financial_net_issuance"], sc["foreign_net_issuance"]]].sum(axis=1, min_count=3)
    fin_detail_sum = q_df[cols[3:15]].sum(axis=1, min_count=12)

    holder_res_max = float((holder_sum - total).abs().max())
    issuer_res_max = float((issuer_sum - total).abs().max())
    fin_res_max = float((fin_detail_sum - q_df[sc["financial_net_issuance"]]).abs().max())

    pensions_total = q_df[[sc["pension_private"], sc["pension_federal"], sc["pension_state_local"]]].sum(axis=1, min_count=3)
    nfc_net_retirement = -q_df[sc["nfc_net_issuance"]]

    groups_spec = [
        ("households", "Households & nonprofits (residual)", q_df[sc["households"]],
         "Fed FU153064105.Q: includes nonprofit organizations and residual estimation; not pure retail broker flow."),
        ("mutual_funds", "Mutual funds (portfolio equity trades)", q_df[sc["mutual_funds"]],
         "Fed FU653064100.Q: net equity purchases by mutual funds, distinct from investor subscriptions/redemptions."),
        ("pensions", "Pension funds (private + federal + state/local)", pensions_total,
         "Sum of private (FU573064105.Q), federal (FU343064105.Q), and state/local (FU223064145.Q) retirement funds."),
        ("foreign", "Foreign investors (Rest of World, ex-funds)", q_df[sc["foreign_equities"]],
         "Fed FU263064105.Q: foreign net purchases of corporate equities (excludes investment fund shares)."),
        ("etfs", "Exchange-traded funds (Z.1 holder line)", q_df[sc["etfs"]],
         "Fed FU563064100.Q: shown for Z.1 holder accounting completeness."),
    ]

    pension_sub = [
        ("pension_private", "Private pension funds", q_df[sc["pension_private"]]),
        ("pension_federal", "Federal retirement funds", q_df[sc["pension_federal"]]),
        ("pension_state_local", "State & local retirement funds", q_df[sc["pension_state_local"]]),
    ]

    chart_n = int(cfg.get("z1_chart_quarters", 40))
    tail = q_df.index[-chart_n:]
    q_labels = [_quarter_str(p) for p in tail]
    q_dates = [_quarter_end_iso(p) for p in tail]

    tic_text, tic_meta = ED_SRC.download("tic_slt_table1", cfg["tic_url"], offline=offline)
    tic_df = ED_SRC.tic_monthly(tic_text, country_code=cfg["tic_country_code"], field=cfg["tic_field"])
    tic_df["quarter"] = pd.PeriodIndex(tic_df["date"], freq="M").asfreq("Q")
    tic_q = tic_df.groupby("quarter")["value_bn"].agg(["sum", "count"]).reset_index()
    tic_q = tic_q[tic_q["count"].eq(3)].copy()

    fed_q = pd.DataFrame({"quarter": q_df.index, "fed_ex_funds_bn": q_df[sc["foreign_equities"]].values})
    bridge_df = fed_q.merge(tic_q, on="quarter").rename(columns={"sum": "tic_broad_bn"})
    bridge_df["raw_diff_bn"] = bridge_df["fed_ex_funds_bn"] - bridge_df["tic_broad_bn"]

    broad_fred = _read_fred_cached_or_none(sc["fred_foreign_broad"])
    funds_fred = _read_fred_cached_or_none(sc["fred_foreign_funds"])
    if broad_fred is not None and funds_fred is not None:
        bf = broad_fred.merge(funds_fred, on="observation_date")
        bf["quarter"] = pd.PeriodIndex(bf["observation_date"], freq="Q")
        bf["bea_broad_bn"] = bf[sc["fred_foreign_broad"]] / 1000.0
        bf["fund_shares_bn"] = bf[sc["fred_foreign_funds"]] / 1000.0
        bridge_df = bridge_df.merge(bf[["quarter", "bea_broad_bn", "fund_shares_bn"]], on="quarter", how="left")
        bridge_df["scope_aligned_diff_bn"] = bridge_df["bea_broad_bn"] - bridge_df["tic_broad_bn"]
        bridge_df["identity_residual_bn"] = (
            bridge_df["bea_broad_bn"] - bridge_df["fund_shares_bn"] - bridge_df["fed_ex_funds_bn"]
        )

    tic_latest = tic_df.iloc[-1] if not tic_df.empty else None
    tic_3m = float(tic_df["value_bn"].iloc[-3:].sum()) if len(tic_df) >= 3 else None
    tic_12m = float(tic_df["value_bn"].iloc[-12:].sum()) if len(tic_df) >= 12 else None

    return {
        "z1": {
            "source_url": cfg["z1_table_url"],
            "fetched_at": z1_meta["fetched_at"],
            "sha256": z1_meta["sha256"],
            "released": cfg["z1_latest_release"],
            "next_release": cfg["z1_next_release"],
            "basis": "FU (unadjusted quarterly transactions, $bn)",
            "quarters_count": int(len(q_df)),
            "first_quarter": _quarter_str(q_df.index[0]),
            "latest_quarter": _quarter_str(q_df.index[-1]),
            "latest_quarter_end": _quarter_end_iso(q_df.index[-1]),
            "reconciliation": {
                "all_quarters_checked": int(len(q_df)),
                "holder_identity_max_residual_bn": clean_float(holder_res_max, 4),
                "issuer_identity_max_residual_bn": clean_float(issuer_res_max, 4),
                "financial_subsector_max_residual_bn": clean_float(fin_res_max, 4),
                "passed": bool(holder_res_max <= 0.012 and issuer_res_max <= 0.002 and fin_res_max <= 0.007),
            },
            "groups": [
                {"key": k, "label": label, "note": note, **_series_summary(s)}
                for k, label, s, note in groups_spec
            ],
            "pension_components": [
                {"key": k, "label": label, **_series_summary(s)}
                for k, label, s in pension_sub
            ],
            "corporate_net_retirement_broad": {
                "key": "nfc_net_retirement_broad",
                "label": "Nonfinancial corporate net retirement (-FU103164105.Q, broad)",
                "note": "Includes closely held equities and M&A retirements; broader than S&P 500 / listed cash buybacks.",
                **_series_summary(nfc_net_retirement),
            },
            "history": {
                "quarters": q_labels,
                "dates": q_dates,
                "households": [clean_float(v, 2) for v in q_df[sc["households"]].reindex(tail)],
                "mutual_funds": [clean_float(v, 2) for v in q_df[sc["mutual_funds"]].reindex(tail)],
                "pensions": [clean_float(v, 2) for v in pensions_total.reindex(tail)],
                "foreign": [clean_float(v, 2) for v in q_df[sc["foreign_equities"]].reindex(tail)],
                "etfs": [clean_float(v, 2) for v in q_df[sc["etfs"]].reindex(tail)],
                "nfc_net_retirement_broad": [clean_float(v, 2) for v in nfc_net_retirement.reindex(tail)],
            },
        },
        "foreign": {
            "tic_source_url": cfg["tic_url"],
            "tic_fetched_at": tic_meta["fetched_at"],
            "tic_sha256": tic_meta["sha256"],
            "tic_months_count": int(len(tic_df)),
            "tic_first_month": str(tic_df["date"].iloc[0]) if not tic_df.empty else None,
            "tic_latest_month": str(tic_latest["date"]) if tic_latest is not None else None,
            "tic_latest_bn": clean_float(tic_latest["value_bn"], 2) if tic_latest is not None else None,
            "tic_3m_sum_bn": clean_float(tic_3m, 2) if tic_3m is not None else None,
            "tic_12m_sum_bn": clean_float(tic_12m, 2) if tic_12m is not None else None,
            "tic_monthly": {
                "dates": [f"{m}-01" for m in tic_df["date"].tolist()],
                "months": tic_df["date"].tolist(),
                "values_bn": [clean_float(v, 2) for v in tic_df["value_bn"]],
            },
            "scope_bridge": {
                "matched_quarters": int(len(bridge_df)),
                "raw_mean_abs_diff_bn": clean_float(float(bridge_df["raw_diff_bn"].abs().mean()), 3)
                if not bridge_df.empty else None,
                "scope_aligned_mean_abs_diff_bn": clean_float(float(bridge_df["scope_aligned_diff_bn"].abs().mean()), 3)
                if "scope_aligned_diff_bn" in bridge_df else None,
                "rows": [
                    {
                        "quarter": _quarter_str(r.quarter),
                        "date": _quarter_end_iso(r.quarter),
                        "tic_broad_bn": clean_float(r.tic_broad_bn, 2),
                        "bea_broad_bn": clean_float(getattr(r, "bea_broad_bn", None), 2),
                        "fund_shares_bn": clean_float(getattr(r, "fund_shares_bn", None), 2),
                        "fed_ex_funds_bn": clean_float(r.fed_ex_funds_bn, 2),
                        "scope_aligned_diff_bn": clean_float(getattr(r, "scope_aligned_diff_bn", None), 2),
                    }
                    for r in bridge_df.itertuples()
                ],
                "note": (
                    "Fed Z.1 FU263064105.Q equals broad foreign equity+fund shares (FU263064003.Q) minus foreign "
                    "investment fund shares (FU263081205.Q). Monthly Treasury TIC (slt_table1.txt) measures broad "
                    "foreign net purchases (including fund shares) and is never concatenated onto the ex-fund series."
                ),
            },
        },
    }


def build_hedge_fund_monitor(
    *,
    cfg: dict,
    flows_artifact: dict | None = None,
    risk_tiles: dict[str, dict] | None = None,
) -> dict:
    """Three-layer hedge-fund exposure and positioning monitor:
    1. OFR Form PF quarterly cash equities vs equity derivatives + prime brokerage borrowing
    2. SEC 13F quarterly constant-price share changes across curated L/S funds
    3. CFTC TFF weekly leveraged-money index futures
    """
    out: dict = {}
    om = cfg["ofr_series"]
    try:
        dataset = ofr.fetch_dataset(use_cache=True)
        le_sec = HFL.points(dataset, om["le_sec"]) / 1e9
        se_sec = HFL.points(dataset, om["se_sec"]) / 1e9
        le_der = HFL.points(dataset, om["le_deriv"]) / 1e9
        se_der = HFL.points(dataset, om["se_deriv"]) / 1e9
        pb_bor = HFL.points(dataset, om["pb_borrow"]) / 1e9
        eq_bor = HFL.points(dataset, om["eq_borrow"]) / 1e9
        eq_nav = HFL.points(dataset, om["eq_nav"]) / 1e9
        eq_ret = HFL.points(dataset, om["eq_ret"])
        eq_cash = HFL.points(dataset, om["eq_cash_ratio"])

        df = pd.DataFrame({
            "long_cash_eq_bn": le_sec,
            "short_cash_eq_bn": se_sec,
            "net_cash_eq_bn": le_sec - se_sec,
            "long_deriv_eq_bn": le_der,
            "short_deriv_eq_bn": se_der,
            "net_deriv_eq_bn": le_der - se_der,
            "prime_broker_borrowing_bn": pb_bor,
            "equity_strategy_borrowing_bn": eq_bor,
            "equity_strategy_nav_bn": eq_nav,
            "equity_strategy_net_return_pct": eq_ret,
            "equity_strategy_cash_ratio_pct": eq_cash,
        }).dropna(how="all").sort_index()

        # Aggregated NAV/weighted returns are not a fixed fund cohort. Changes
        # in reporters and return weights prevent identifying investor cash flows.

        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else pd.Series(dtype=float)
        yago = df.iloc[-5] if len(df) >= 5 else pd.Series(dtype=float)
        latest_date = to_iso_date(df.index[-1])

        out["form_pf"] = {
            "latest_period": latest_date,
            "quarters": int(len(df)),
            "cash_equities": {
                "long_bn": clean_float(last["long_cash_eq_bn"], 1),
                "short_bn": clean_float(last["short_cash_eq_bn"], 1),
                "net_bn": clean_float(last["net_cash_eq_bn"], 1),
                "net_qoq_bn": clean_float(last["net_cash_eq_bn"] - prev.get("net_cash_eq_bn", np.nan), 1),
                "net_yoy_bn": clean_float(last["net_cash_eq_bn"] - yago.get("net_cash_eq_bn", np.nan), 1),
            },
            "equity_derivatives": {
                "long_bn": clean_float(last["long_deriv_eq_bn"], 1),
                "short_bn": clean_float(last["short_deriv_eq_bn"], 1),
                "net_bn": clean_float(last["net_deriv_eq_bn"], 1),
                "net_qoq_bn": clean_float(last["net_deriv_eq_bn"] - prev.get("net_deriv_eq_bn", np.nan), 1),
                "net_yoy_bn": clean_float(last["net_deriv_eq_bn"] - yago.get("net_deriv_eq_bn", np.nan), 1),
            },
            "financing": {
                "prime_broker_borrowing_bn": clean_float(last["prime_broker_borrowing_bn"], 1),
                "pb_qoq_bn": clean_float(last["prime_broker_borrowing_bn"] - prev.get("prime_broker_borrowing_bn", np.nan), 1),
                "pb_yoy_bn": clean_float(last["prime_broker_borrowing_bn"] - yago.get("prime_broker_borrowing_bn", np.nan), 1),
                "equity_strategy_borrowing_bn": clean_float(last["equity_strategy_borrowing_bn"], 1),
                "eq_borrow_qoq_bn": clean_float(last["equity_strategy_borrowing_bn"] - prev.get("equity_strategy_borrowing_bn", np.nan), 1),
                "unencumbered_cash_pct_nav": clean_float(last["equity_strategy_cash_ratio_pct"], 1),
                "cash_ratio_qoq_pp": clean_float(last["equity_strategy_cash_ratio_pct"] - prev.get("equity_strategy_cash_ratio_pct", np.nan), 1),
                "equity_strategy_nav_bn": clean_float(last["equity_strategy_nav_bn"], 1),
                "implied_capital_flow_bn": None,
                "capital_flow_status": "withheld: aggregate NAV and weighted returns do not identify subscriptions/redemptions",
            },
            "history": {
                "dates": [to_iso_date(d) for d in df.index],
                "net_cash_eq_bn": [clean_float(v, 1) for v in df["net_cash_eq_bn"]],
                "net_deriv_eq_bn": [clean_float(v, 1) for v in df["net_deriv_eq_bn"]],
                "prime_broker_borrowing_bn": [clean_float(v, 1) for v in df["prime_broker_borrowing_bn"]],
                "equity_strategy_borrowing_bn": [clean_float(v, 1) for v in df["equity_strategy_borrowing_bn"]],
            },
            "note": (
                "OFR Form PF aggregates describe securities/derivative exposures and borrowing, not cash trades. "
                "Derivatives include many instruments and purposes; an aggregate net short does not establish index hedging. "
                "Reporting cohorts may change. Subscriptions/redemptions are not identified from aggregate NAV and weighted returns."
            ),
        }
    except Exception as exc:
        out["form_pf"] = {"unavailable": str(exc)[:180]}

    hf13f = (flows_artifact or {}).get("hf_13f") or {}
    if hf13f and not hf13f.get("unavailable"):
        moves = hf13f.get("moves") or {}
        adds = moves.get("adds") or []
        cuts = moves.get("cuts") or []
        out["sec_13f"] = {
            "period": hf13f.get("period"),
            "period_label": hf13f.get("period_label"),
            "n_funds": hf13f.get("n_funds"),
            "common_funds": moves.get("common_funds"),
            "total_long_value_bn": hf13f.get("total_value_bn"),
            "concentration_top10_pct": clean_float(hf13f.get("concentration_top10_pct"), 1),
            "options_put_value_bn": (hf13f.get("options") or {}).get("put_value_bn"),
            "options_call_value_bn": (hf13f.get("options") or {}).get("call_value_bn"),
            "top_adds": [
                {"ticker": r["ticker"], "d_holders": r["d_holders"], "d_value_bn": clean_float(r["d_value"] / 1e9, 2)}
                for r in adds[:5]
            ],
            "top_cuts": [
                {"ticker": r["ticker"], "d_holders": r["d_holders"], "d_value_bn": clean_float(r["d_value"] / 1e9, 2)}
                for r in cuts[:5]
            ],
            "sector_tilt": (hf13f.get("sector_tilt") or [])[:6],
        }

    if risk_tiles:
        es = risk_tiles.get("cftc_es") or {}
        nq = risk_tiles.get("cftc_nq") or {}
        out["cftc_futures"] = {
            "date": es.get("date") or nq.get("date"),
            "es_pct_oi": clean_float(es.get("value"), 1),
            "es_change_1w": clean_float(es.get("change_1w"), 1),
            "nq_pct_oi": clean_float(nq.get("value"), 1),
            "nq_change_1w": clean_float(nq.get("change_1w"), 1),
            "note": "Weekly CFTC TFF leveraged-fund net futures (% of OI). Directional trades, hedges and basis positions cannot be distinguished here.",
        }

    return out


def assemble_demand_pipeline(
    *,
    as_of: str,
    cfg: dict,
    heatmaps: dict | None = None,
    valuation: dict | None = None,
    flows_artifact: dict | None = None,
    risk_tiles: dict[str, dict] | None = None,
    offline: bool = False,
    prices: pd.DataFrame | None = None,
    volumes: pd.DataFrame | None = None,
) -> dict:
    macro_and_foreign = build_sector_and_foreign_demand(cfg, offline=offline)
    hm = heatmaps or {}
    val = valuation or {}
    baskets: dict[str, list[dict]] = {}
    indices = cfg.get("indices") or []
    if hm.get("constituents") and indices:
        baskets[indices[0]] = hm["constituents"]
    for m in hm.get("index_maps") or []:
        if m.get("key") in indices and m.get("constituents"):
            baskets[m["key"]] = m["constituents"]

    buybacks_payload = BB.build_index_buybacks(
        cutoff=as_of,
        baskets=baskets,
        valuation_rows=val.get("rows") or [],
        remaining_tags=list(cfg["remaining_tags"]),
        authorized_tags=list(cfg["authorized_tags"]),
        tolerance_usd=float(cfg.get("reconciliation_tolerance_usd", 1_000_000.0)),
        prices=prices, volumes=volumes,
    ) if baskets else None

    hf_monitor = build_hedge_fund_monitor(
        cfg=cfg,
        flows_artifact=flows_artifact,
        risk_tiles=risk_tiles,
    )

    return {
        "as_of": as_of,
        "z1": macro_and_foreign["z1"],
        "foreign": macro_and_foreign["foreign"],
        "buybacks": buybacks_payload,
        "hedge_fund_monitor": hf_monitor,
    }
