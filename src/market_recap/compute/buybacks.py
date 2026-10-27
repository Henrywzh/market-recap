"""Cash execution and plan balances. Never infer cash purchases from authority."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
import os
from pathlib import Path
import re

import pandas as pd
from bs4 import BeautifulSoup

from ..config import CACHE_DIR
from ..sources import sec, xbrl_instance
from ..util import clean_float


def _one_year_ago(day_str: str, candidates: list[str], tolerance_days: int = 20) -> str | None:
    target = date.fromisoformat(day_str[:10]) - timedelta(days=365)
    best = min(candidates, key=lambda d: abs((date.fromisoformat(d[:10]) - target).days), default=None)
    if best is None or abs((date.fromisoformat(best[:10]) - target).days) > tolerance_days:
        return None
    return best


def quarter_at(periods: dict, end: str) -> dict | None:
    spans = [(key, entry, (date.fromisoformat(end) - date.fromisoformat(key[0])).days + 1)
             for key, entry in periods.items() if key[0] and key[1] == end]
    direct = [p for p in spans if 70 <= p[2] <= 110]
    if direct:
        key, entry, _ = min(direct, key=lambda p: abs(p[2] - 91))
        return {"start": key[0], "end": end, "value": entry["value"], "method": "direct",
                "parts": [{"start": key[0], "end": end, "sign": 1, **entry}]}
    ytd = [p for p in spans if 111 <= p[2] <= 380]
    if not ytd:
        return None
    key, entry, _ = max(ytd, key=lambda p: p[2])
    priors = [(k, v) for k, v in periods.items() if k[0] == key[0] and k[1] < end
              and 70 <= (date.fromisoformat(end) - date.fromisoformat(k[1])).days <= 110]
    if not priors:
        return None
    prev_key, prev = max(priors, key=lambda p: p[0][1])
    return {"start": (date.fromisoformat(prev_key[1]) + timedelta(days=1)).isoformat(), "end": end,
            "value": entry["value"] - prev["value"], "method": "same_fiscal_start_difference",
            "parts": [{"start": key[0], "end": end, "sign": 1, **entry},
                      {"start": prev_key[0], "end": prev_key[1], "sign": -1, **prev}]}


def cash_execution(facts: dict, recent: dict, cutoff: str, *, tolerance_usd: float) -> dict:
    periods = sec._period_values(facts, sec.ITEMS_BY_KEY["buybacks"], (), filed_by=cutoff)
    periods = {k: v for k, v in periods.items() if k[1] <= cutoff}
    reports = [rd for form, fd, rd in zip(recent.get("form", []), recent.get("filingDate", []), recent.get("reportDate", []))
               if form in sec.STATEMENT_FORMS and fd <= cutoff and rd and rd <= cutoff]
    end = max(reports, default=None)
    if not end:
        return {"status": "no_report_anchor", "ttm_usd": None, "quarter_usd": None, "history": []}
    ends = sorted({k[1] for k in periods if k[1] <= end})
    # Reconcile only four recent consecutive quarters, not every historic XBRL span.
    quarters = [q for e in ends if (q := quarter_at(periods, e)) is not None]
    ttm, _ = sec.trailing_value(periods, end)
    q = quarter_at(periods, end)
    prior_end = _one_year_ago(end, ends)
    prior_ttm = sec.trailing_value(periods, prior_end)[0] if prior_end else None
    prior_q = quarter_at(periods, prior_end) if prior_end else None
    last = quarters[-4:]
    continuous = (len(last) == 4 and last[-1]["end"] == end
                  and all((date.fromisoformat(b["start"]) - date.fromisoformat(a["end"])).days == 1
                          for a, b in zip(last, last[1:]))
                  and 350 <= sum((date.fromisoformat(x["end"]) - date.fromisoformat(x["start"])).days + 1 for x in last) <= 380)
    residual = sum(x["value"] for x in last) - ttm if continuous and ttm is not None else None
    status = "available" if ttm is not None else "missing_ttm_at_latest_report"
    if ttm is not None and (ttm < 0 or (q and q["value"] < 0)):
        status = "negative_cash_needs_review"
    if residual is not None and abs(residual) > tolerance_usd:
        status = "quarter_ttm_reconciliation_exception"
    q_val = (q["value"] if q and q["value"] >= 0 and status not in
             {"negative_cash_needs_review", "quarter_ttm_reconciliation_exception"} else None)
    ttm_val = ttm if status == "available" else None
    prior_q_val = prior_q["value"] if prior_q and prior_q["value"] >= 0 else None
    prior_ttm_val = prior_ttm if prior_ttm is not None and prior_ttm >= 0 else None
    q_accel_pct = (clean_float((q_val / prior_q_val - 1.0) * 100.0, 1)
                   if q_val is not None and prior_q_val is not None and prior_q_val > 0 else None)
    ttm_accel_pct = (clean_float((ttm_val / prior_ttm_val - 1.0) * 100.0, 1)
                     if ttm_val is not None and prior_ttm_val is not None and prior_ttm_val > 0 else None)
    if status == "quarter_ttm_reconciliation_exception":
        regime = "reconciliation_exception"
    elif q_val is not None and q_val > 0 and prior_q_val == 0:
        regime = "positive_vs_zero_year_ago"
    elif q_val is not None and q_val > 0:
        regime = "active"
    elif q_val == 0 and ((ttm_val is not None and ttm_val > 0) or (prior_q_val is not None and prior_q_val > 0)):
        regime = "zero_with_prior_execution"
    elif q_val == 0:
        regime = "zero"
    else:
        regime = "missing"
    parts = sec.trailing_parts(periods, end)
    return {"status": status, "report_end": end, "latest_payment_end": max(ends, default=None),
            "ttm_usd": ttm_val,
            "quarter_usd": q_val,
            "quarter_method": q["method"] if q else None,
            "prior_year_end": prior_end,
            "prior_quarter_usd": prior_q_val,
            "prior_ttm_usd": prior_ttm_val,
            "quarter_yoy_pct": q_accel_pct,
            "ttm_yoy_pct": ttm_accel_pct,
            "regime": regime,
            "reported_ttm_candidate_usd": ttm, "reconciliation_residual_usd": clean_float(residual),
            "ttm_parts": [{"sign": sign, **entry} for entry, sign in parts] if parts else None,
            "history": quarters}


def plan_facts(html: str, *, filed: str, cutoff: str, source: str, allowed_tags: list[str]) -> list[dict]:
    """Only USD instant facts with zero or repurchase-program dimensions.

    Identical disclosures collapse; conflicts remain unavailable. Totals and
    constituent programs are never summed here. Monetary duration approvals
    are not remaining-capacity stocks and are intentionally excluded.
    """
    soup = BeautifulSoup(html, "lxml")
    contexts = {t.get("id"): t for t in soup.find_all(lambda t: t.name and t.name.lower().endswith(":context"))}
    units = {t.get("id"): t for t in soup.find_all(lambda t: t.name and t.name.lower().endswith(":unit"))}
    wanted = {t.lower() for t in allowed_tags}
    picked: dict[tuple, dict] = {}
    if filed > cutoff:
        return []
    for element in soup.find_all(lambda t: t.name and t.name.lower().endswith(":nonfraction")):
        tag = element.get("name", "").split(":")[-1]
        if tag.lower() not in wanted or element.get("xsi:nil") in {"true", "1"}:
            continue
        context, unit = contexts.get(element.get("contextref")), units.get(element.get("unitref"))
        if context is None or unit is None:
            continue
        measure = unit.find(lambda t: t.name and t.name.lower().endswith(":measure"))
        instant = context.find(lambda t: t.name and t.name.lower().endswith(":instant"))
        if not measure or measure.get_text(strip=True).split(":")[-1] != "USD" or instant is None:
            continue
        end = instant.get_text(strip=True)
        if end > cutoff:
            continue
        members = sorted((m.get("dimension", ""), m.get_text(strip=True)) for m in
                         context.find_all(lambda t: t.name and t.name.lower().endswith(":explicitmember")))
        if context.find(lambda t: t.name and t.name.lower().endswith(":typedmember")):
            continue
        if any("repurchaseprogram" not in axis.lower() for axis, _ in members):
            continue
        try:
            text = re.sub(r"[\s,$]", "", element.get_text())
            amount = Decimal(text) * Decimal(10) ** int(element.get("scale", "0"))
            if element.get("sign") == "-":
                amount = -amount
            value = float(amount)
            if not amount.is_finite() or value < 0 or clean_float(value) is None:
                continue
        except (InvalidOperation, ValueError, OverflowError):
            continue
        kind = "remaining" if "remaining" in tag.lower() else "authorized_total"
        key = (kind, end, tuple(members))
        row = {"kind": kind, "period_end": end, "program_dimensions": members, "amount_usd": value,
               "filed": filed, "source": source, "tag": tag, "status": "observed", "occurrences": 1}
        if key not in picked:
            picked[key] = row
        else:
            old = picked[key]
            old["occurrences"] += 1
            if old["amount_usd"] != value:
                old["status"], old["amount_usd"] = "conflicting_facts", None
    return list(picked.values())


def latest_capacity(rows: list[dict], report_end: str) -> dict:
    rows = [r for r in rows if r["kind"] == "remaining" and r["period_end"] == report_end]
    totals = [r for r in rows if not r["program_dimensions"]]
    if len(totals) == 1 and totals[0]["status"] == "observed":
        return {"remaining_usd": totals[0]["amount_usd"], "status": "reported_entity_total"}
    # Without a verified exhaustive plan list, even one dimension could be just
    # one of several programs. Expose observations, withhold the issuer total.
    return {"remaining_usd": None, "status": "program_observations_only" if rows else "not_tagged_or_not_parsed"}


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


def _load_cached_issuer(cik: int) -> tuple[dict | None, dict, list[int], dict[str, tuple[int, int]]]:
    reads: dict[str, tuple[int, int]] = {}
    p = CACHE_DIR / f"sec/facts/CIK{cik:010d}.json.gz"
    if not p.exists():
        return None, {}, [], reads
    if (st := _stamp(p)) is not None:
        reads[str(p)] = st
    facts = json.loads(gzip.decompress(p.read_bytes()))
    sources = [cik]
    if not sec._has_annual_facts(facts):
        name = str(facts.get("entityName") or "").strip().lower()
        for cand in sec._predecessor_ciks(facts, cik):
            cp = CACHE_DIR / f"sec/facts/CIK{cand:010d}.json.gz"
            if cp.exists():
                if (cst := _stamp(cp)) is not None:
                    reads[str(cp)] = cst
                older = json.loads(gzip.decompress(cp.read_bytes()))
                if name and str(older.get("entityName") or "").strip().lower() == name:
                    facts = sec._merge(facts, older)
                    sources.append(cand)
                    break
    subp = CACHE_DIR / f"sec/submissions/CIK{cik:010d}.json.gz"
    recent = {}
    if subp.exists():
        if (sst := _stamp(subp)) is not None:
            reads[str(subp)] = sst
        recent = json.loads(gzip.decompress(subp.read_bytes())).get("filings", {}).get("recent", {})
    newest = sec._newest_filed(facts)
    for filing in sec._statement_filings(recent):
        if filing.filed > newest and not sec._carries(facts, filing.accession):
            folder = filing.accession.replace("-", "")
            inst = CACHE_DIR / f"sec/instance/{folder}.json.gz"
            if inst.exists():
                if (ist := _stamp(inst)) is not None:
                    reads[str(inst)] = ist
                extra = json.loads(gzip.decompress(inst.read_bytes()))
                if extra.get("us-gaap"):
                    facts = xbrl_instance.merge_into(facts, extra)
    return facts, recent, sources, reads


def _extract_authorization_facts(
    facts: dict,
    report_end: str | None,
    cutoff: str,
    remaining_tags: list[str],
    authorized_tags: list[str],
) -> dict:
    rem_item = sec.LineItem("rem_auth", "Remaining repurchase authorization", tuple(remaining_tags), "balance")
    rem_periods = sec._period_values(facts, rem_item, (), filed_by=cutoff)
    rem_periods = {k: v for k, v in rem_periods.items() if k[1] <= cutoff and v.get("value") is not None and v["value"] >= 0}
    at_report = rem_periods.get((None, report_end)) if report_end else None
    latest_rem_end = max((k[1] for k in rem_periods), default=None)
    latest_rem = rem_periods.get((None, latest_rem_end)) if latest_rem_end else None

    gaap = facts.get("facts", {}).get("us-gaap", {})
    auth_rows = []
    for priority, tag in enumerate(authorized_tags):
        for row in gaap.get(tag, {}).get("units", {}).get("USD", []):
            filed = row.get("filed") or ""
            end = row.get("end")
            val = row.get("val")
            if row.get("form") not in sec.QUARTERLY_FORMS or not end or end > cutoff or not filed or filed > cutoff or val is None or val < 0:
                continue
            auth_rows.append((end, filed, -priority, float(val), tag))
    auth_rows.sort()
    latest_auth = auth_rows[-1] if auth_rows else None
    return {
        "remaining_at_report_usd": float(at_report["value"]) if at_report else None,
        "remaining_at_report_filed": at_report["filed"] if at_report else None,
        "latest_remaining_end": latest_rem_end,
        "latest_remaining_usd": float(latest_rem["value"]) if latest_rem else None,
        "latest_authorized_end": latest_auth[0] if latest_auth else None,
        "latest_authorized_filed": latest_auth[1] if latest_auth else None,
        "latest_authorized_usd": latest_auth[3] if latest_auth else None,
    }


def build_index_buybacks(
    *,
    cutoff: str,
    baskets: dict[str, list[dict]],
    valuation_rows: list[dict],
    remaining_tags: list[str],
    authorized_tags: list[str],
    tolerance_usd: float = 1_000_000.0,
    prices: pd.DataFrame | None = None,
    volumes: pd.DataFrame | None = None,
) -> dict:
    """Build deduplicated SPX and NDX cash repurchase & authorization summaries."""
    code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
    cache_path = CACHE_DIR / "equity_demand" / "buybacks_issuer_cache.json"
    cached_store: dict = {}
    if cache_path.exists():
        try:
            raw_cache = json.loads(cache_path.read_text())
            if raw_cache.get("code_hash") == code_hash and raw_cache.get("cutoff") == cutoff:
                cached_store = raw_cache.get("issuers", {})
        except Exception:
            cached_store = {}

    cik_by_ticker = {r["ticker"]: int(r["cik"]) for r in valuation_rows if r.get("ticker") and r.get("cik")}
    mcap_by_cik: dict[int, float] = {}
    name_by_cik: dict[int, str] = {}
    sector_by_cik: dict[int, str] = {}
    for r in valuation_rows:
        if r.get("cik"):
            c = int(r["cik"])
            if r.get("market_cap") and c not in mcap_by_cik:
                mcap_by_cik[c] = float(r["market_cap"])
            if r.get("name") and c not in name_by_cik:
                name_by_cik[c] = str(r["name"])
            if r.get("sector") and c not in sector_by_cik:
                sector_by_cik[c] = str(r["sector"])

    ref_path = CACHE_DIR / "sec/company_tickers.json"
    if ref_path.exists():
        for x in json.loads(ref_path.read_text()).values():
            t = x["ticker"]
            cik_by_ticker.setdefault(t, int(x["cik_str"]))
            cik_by_ticker.setdefault(t.replace(".", "-"), int(x["cik_str"]))

    needed_ciks = sorted({
        cik_by_ticker[r["ticker"]]
        for roster in baskets.values()
        for r in roster
        if r.get("ticker") in cik_by_ticker
    })

    def eval_cik(cik: int) -> tuple[int, dict]:
        key = str(cik)
        prev = cached_store.get(key)
        if prev and prev.get("reads"):
            if all(_stamp(Path(p)) == tuple(st) for p, st in prev["reads"].items()):
                return cik, prev["data"]
        facts, recent, sources, reads = _load_cached_issuer(cik)
        if facts is None:
            data = {"cik": cik, "status": "no_cached_facts", "regime": "missing",
                    "ttm_usd": None, "quarter_usd": None, "history": []}
            return cik, data
        ce = cash_execution(facts, recent, cutoff, tolerance_usd=tolerance_usd)
        auth = _extract_authorization_facts(facts, ce.get("report_end"), cutoff, remaining_tags, authorized_tags)
        ce["history"] = [
            {"start": q["start"], "end": q["end"], "value": q["value"], "method": q["method"]}
            for q in (ce.get("history") or [])
            if (date.fromisoformat(q["end"]) - date.fromisoformat(q["start"])).days in range(69, 110)
        ]
        if ce.get("status") == "quarter_ttm_reconciliation_exception":
            ce["history"] = [q for q in ce["history"] if q["end"] != ce["report_end"]]
        ce.pop("ttm_parts", None)
        data = {"cik": cik, "source_ciks": sources, **ce, **auth}
        cached_store[key] = {"reads": {k: list(v) for k, v in reads.items()}, "data": data}
        return cik, data

    with ThreadPoolExecutor(8) as pool:
        issuer_map = dict(pool.map(eval_cik, needed_ciks))

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"code_hash": code_hash, "cutoff": cutoff, "issuers": cached_store}))
    except OSError:
        pass

    indices_out = {}
    for group, roster in baskets.items():
        seen: set[int] = set()
        rows = []
        for r in roster:
            sym = r.get("ticker")
            cik = cik_by_ticker.get(sym)
            if not cik or cik in seen:
                continue
            seen.add(cik)
            lines = [x["ticker"] for x in roster if cik_by_ticker.get(x.get("ticker")) == cik]
            weight_pct = sum(float(x.get("weight") or 0.0) for x in roster if cik_by_ticker.get(x.get("ticker")) == cik)
            info = issuer_map.get(cik, {})
            mcap = mcap_by_cik.get(cik)
            ttm_usd = info.get("ttm_usd")
            q_usd = info.get("quarter_usd")
            rem_usd = info.get("remaining_at_report_usd")
            yield_pct = clean_float(ttm_usd / mcap * 100.0, 2) if ttm_usd is not None and mcap and mcap > 0 else None
            rem_pct_mcap = clean_float(rem_usd / mcap * 100.0, 2) if rem_usd is not None and mcap and mcap > 0 else None
            rows.append({
                "ticker": sym,
                "tickers": lines,
                "name": name_by_cik.get(cik) or r.get("name") or sym,
                "sector": sector_by_cik.get(cik) or r.get("sector"),
                "cik": cik,
                "weight_pct": clean_float(weight_pct, 4),
                "market_cap_bn": clean_float(mcap / 1e9, 2) if mcap else None,
                "report_end": info.get("report_end"),
                "status": info.get("status"),
                "regime": info.get("regime"),
                "quarter_bn": clean_float(q_usd / 1e9, 3) if q_usd is not None else None,
                "quarter_method": info.get("quarter_method"),
                "prior_quarter_bn": clean_float(info["prior_quarter_usd"] / 1e9, 3) if info.get("prior_quarter_usd") is not None else None,
                "quarter_yoy_pct": info.get("quarter_yoy_pct"),
                "ttm_bn": clean_float(ttm_usd / 1e9, 3) if ttm_usd is not None else None,
                "prior_ttm_bn": clean_float(info["prior_ttm_usd"] / 1e9, 3) if info.get("prior_ttm_usd") is not None else None,
                "ttm_yoy_pct": info.get("ttm_yoy_pct"),
                "buyback_yield_pct": yield_pct,
                "reconciliation_residual_m": clean_float((info.get("reconciliation_residual_usd") or 0.0) / 1e6, 2)
                if info.get("reconciliation_residual_usd") is not None else None,
                "remaining_at_report_bn": clean_float(rem_usd / 1e9, 3) if rem_usd is not None else None,
                "remaining_pct_mcap": rem_pct_mcap,
                "latest_remaining_end": info.get("latest_remaining_end"),
                "latest_remaining_bn": clean_float(info["latest_remaining_usd"] / 1e9, 3) if info.get("latest_remaining_usd") is not None else None,
                "latest_authorized_end": info.get("latest_authorized_end"),
                "latest_authorized_bn": clean_float(info["latest_authorized_usd"] / 1e9, 3) if info.get("latest_authorized_usd") is not None else None,
            })

        ttm_rows = [x for x in rows if x["ttm_bn"] is not None]
        q_rows = [x for x in rows if x["quarter_bn"] is not None]
        rem_rows = [x for x in rows if x["remaining_at_report_bn"] is not None]
        rem_any_rows = [x for x in rows if x["latest_remaining_bn"] is not None]
        regimes = {}
        for x in rows:
            reg = x["regime"] or "missing"
            regimes[reg] = regimes.get(reg, 0) + 1

        top_ttm = sorted(ttm_rows, key=lambda x: x["ttm_bn"], reverse=True)[:15]
        paused_notable = sorted(
            [x for x in rows if x["regime"] == "zero_with_prior_execution"],
            key=lambda x: (x["ttm_bn"] or 0.0, x["weight_pct"] or 0.0),
            reverse=True,
        )[:8]
        top_remaining = sorted(rem_rows, key=lambda x: x["remaining_at_report_bn"], reverse=True)[:12]
        exceptions = [x for x in rows if x["status"] == "quarter_ttm_reconciliation_exception"]

        indices_out[group] = {
            "index": group,
            "security_lines": len(roster),
            "unique_issuers": len(rows),
            "ttm_covered_issuers": len(ttm_rows),
            "ttm_weight_coverage_pct": clean_float(sum(x["weight_pct"] or 0.0 for x in ttm_rows), 2),
            "covered_ttm_sum_bn": clean_float(sum(x["ttm_bn"] for x in ttm_rows), 2),
            "quarter_covered_issuers": len(q_rows),
            "quarter_weight_coverage_pct": clean_float(sum(x["weight_pct"] or 0.0 for x in q_rows), 2),
            "covered_quarter_sum_bn": clean_float(sum(x["quarter_bn"] for x in q_rows), 2),
            "remaining_at_report_issuers": len(rem_rows),
            "remaining_at_report_weight_pct": clean_float(sum(x["weight_pct"] or 0.0 for x in rem_rows), 2),
            "covered_remaining_at_report_bn": clean_float(sum(x["remaining_at_report_bn"] for x in rem_rows), 2),
            "remaining_any_period_issuers": len(rem_any_rows),
            "regimes": regimes,
            "reconciliation_exceptions": exceptions,
            "top_ttm_buyers": top_ttm,
            "notable_paused": paused_notable,
            "top_entity_remaining": top_remaining,
            "history": aggregate_history(
                attach_turnover({cik: issuer_map[cik].get("history", []) for cik in seen if cik in issuer_map},
                                {row["cik"]: row["tickers"] for row in rows}, prices, volumes),
                cutoff=cutoff, issuer_count=len(rows),
            ),
        }

    return {
        "as_of": cutoff,
        "indices": indices_out,
        "note": (
            "Deduplicated by issuer CIK before summing. Cash repurchases use US-GAAP PaymentsForRepurchaseOfCommonStock "
            "(standalone fiscal quarter or same-fiscal-start YTD difference; TTM reconciled against four consecutive quarters "
            "within $1M). Missing disclosures remain missing, never zero. Covered totals are partial sums over issuers with reported values, "
            "not complete index totals. Remaining authorizations combine entity-level non-dimensional balances at report_end and may miss issuer-specific or dimensional program disclosures."
        ),
    }


def attach_turnover(issuer_quarters, tickers_by_cik, prices, volumes):
    """Add close × volume over each issuer's fiscal quarter, with session coverage.

    Both series must cover the interval; missing observations never become zero.
    This is a traded-value proxy, not cash flow or exact transaction notional.
    """
    if prices is None or volumes is None or prices.empty or volumes.empty:
        return issuer_quarters
    p, v = prices.copy().sort_index(), volumes.copy().sort_index()
    p.index, v.index = pd.to_datetime(p.index), pd.to_datetime(v.index)
    v = v.reindex(p.index)
    out = {}
    for cik, quarters in issuer_quarters.items():
        names = tickers_by_cik.get(cik, [])
        good_names = bool(names) and all(n in p.columns and n in v.columns for n in names)
        out[cik] = []
        for row in quarters:
            item = dict(row)
            start, end = pd.Timestamp(row['start']), pd.Timestamp(row['end'])
            calendar = p.index[(p.index >= start) & (p.index <= end)]
            complete_edges = len(calendar) and (calendar[0] - start).days <= 7 and (end - calendar[-1]).days <= 7
            if good_names and complete_edges:
                pp, vv = p.loc[calendar, names], v.loc[calendar, names]
                valid = pp.notna() & vv.notna() & (pp > 0) & (vv >= 0)
                if (valid.sum(axis=0) / len(calendar) >= 0.9).all():
                    item['turnover_usd'] = float((pp * vv).where(valid).sum().sum())
            out[cik].append(item)
    return out


def aggregate_history(issuer_quarters: dict[int, list[dict]], *, cutoff: str, issuer_count: int) -> dict:
    """Fiscal quarters grouped by calendar period of end date; no daily interpolation.

    A calendar year total needs four contiguous quarters for that issuer. TTM
    needs four contiguous calendar buckets and contiguous fiscal intervals.
    The roster is today's roster throughout; missing issuers never become zero.
    """
    quarter_map: dict[int, dict[pd.Period, dict]] = {}
    for cik, rows in issuer_quarters.items():
        buckets: dict[pd.Period, list] = {}
        for row in rows:
            if row['end'] > cutoff or clean_float(row.get('value')) is None or row['value'] < 0:
                continue
            buckets.setdefault(pd.Period(row['end'], freq='Q'), []).append(row)
        # Multiple fiscal quarters ending in one calendar quarter are ambiguous;
        # exclude that issuer/period rather than silently choosing or doubling it.
        quarter_map[cik] = {p: rs[0] for p, rs in buckets.items() if len(rs) == 1}
    periods = sorted({p for rows in quarter_map.values() for p in rows})
    if not periods:
        return {'quarterly': [], 'ttm': [], 'annual': [], 'roster_basis': 'current_roster'}
    periods = pd.period_range(periods[0], pd.Period(cutoff, freq='Q'), freq='Q')

    def total(label, rows, complete):
        vals = [r['value'] for r in rows]
        return {'period': str(label), 'date': label.end_time.date().isoformat(),
                'covered_sum_bn': clean_float(sum(vals) / 1e9, 3) if vals else None,
                'covered_issuers': len(vals), 'total_issuers': issuer_count,
                'coverage_pct': clean_float(len(vals) / issuer_count * 100, 1) if issuer_count else None,
                'period_ended': complete}

    def consecutive(rows):
        return (len(rows) == 4 and all((date.fromisoformat(b['start']) - date.fromisoformat(a['end'])).days == 1
                                      for a, b in zip(rows, rows[1:])))

    qs, ttms, annual = [], [], []
    series: dict[str, dict] = {"quarterly": {}, "ttm": {}, "annual": {}}
    for period in periods:
        series["quarterly"][period] = {cik: rows[period]["value"] for cik, rows in quarter_map.items() if period in rows}
        vals = {}
        for cik, rows in quarter_map.items():
            window = [rows[p] for p in pd.period_range(period - 3, period, freq="Q") if p in rows]
            if consecutive(window):
                vals[cik] = sum(r["value"] for r in window)
        series["ttm"][period] = vals
    for year in range(periods[0].year, periods[-1].year + 1):
        period = pd.Period(str(year), freq="Y")
        vals = {}
        for cik, rows in quarter_map.items():
            window = [rows[p] for p in pd.period_range(f"{year}Q1", f"{year}Q4", freq="Q") if p in rows]
            if consecutive(window):
                vals[cik] = sum(r["value"] for r in window)
        series["annual"][period] = vals

    def result(period, values, prev):
        row = total(period, [{"value": value} for value in values.values()],
                    period.end_time.date().isoformat() <= cutoff)
        common = values.keys() & prev.keys()
        current_sum = sum(values[cik] for cik in common)
        prior_sum = sum(prev[cik] for cik in common)
        row["matched_yoy"] = {
            "issuers": len(common),
            "current_bn": clean_float(current_sum / 1e9, 3) if common else None,
            "prior_bn": clean_float(prior_sum / 1e9, 3) if common else None,
            "change_bn": clean_float((current_sum - prior_sum) / 1e9, 3) if common else None,
            "change_pct": clean_float((current_sum / prior_sum - 1) * 100, 1) if common and prior_sum > 0 else None,
        }
        return row

    for key, destination in (("quarterly", qs), ("ttm", ttms), ("annual", annual)):
        for period, values in series[key].items():
            destination.append(result(period, values, series[key].get(period - (1 if key == "annual" else 4), {})))
    for result_row, period in zip(qs, periods):
        matched = [rows[period] for rows in quarter_map.values()
                   if period in rows and rows[period].get('turnover_usd') is not None and rows[period]['turnover_usd'] > 0]
        spent = sum(r['value'] for r in matched)
        traded = sum(r['turnover_usd'] for r in matched)
        result_row['trading_value_comparison'] = {
            'issuers': len(matched), 'buyback_bn': clean_float(spent / 1e9, 3) if matched else None,
            'traded_value_bn': clean_float(traded / 1e9, 3) if matched else None,
            'ratio_pct': clean_float(spent / traded * 100, 3) if matched and traded > 0 else None,
        }
    return {'quarterly': qs, 'ttm': ttms, 'annual': annual, 'roster_basis': 'current_roster',
            'aggregation_basis': 'Fiscal quarters grouped by calendar quarter of fiscal end; not exact calendar-day cash flows.',
            'note': 'Covered issuer sums, unweighted and deduplicated by CIK. Coverage changes by period. Current-roster history contains survivorship bias. Unfinished/recent periods are incomplete; missing stays null. No monthly/daily execution is estimated.'}
