"""Check the built artifacts against the contract that produced them.

A build that "succeeds" is not the same as a build that is publishable. Every
failure this module reports is one that has actually reached the page at least
once during development: a tab dated to a session that had not closed, a
period column whose window nothing had fetched history for, a preset naming a
ticker no panel priced, a flow series attributed to the wrong issuer.

It runs as part of the build, so the answer to "is this page safe to serve"
comes from the build itself rather than from someone opening every tab.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .config import ARTIFACT_DIR, PERIOD_TRADING_DAYS, SESSION_COVERAGE_THRESHOLD, load_config

# error: not publishable. warning: publishable, but --strict refuses it.
# notice: a gap in an optional feed, shown on its own tab; never blocks.
SEVERITIES = ("error", "warning", "notice")

# Feeds whose failure leaves a gap on one tab rather than a wrong number on
# the page: the catalyst calendars and the ETF look-through holdings. Unofficial
# endpoints among them fail for reasons of their own, and one of them being
# down must not hold back the prices every other tab needs.
OPTIONAL_SOURCES = re.compile(r"^(catalysts_\w+|(ssga|ishares|vanguard|invesco)_xray_holdings|yahoo_estimates(_quarter)?|factset_insight|earnings_season_nasdaq"
                              # THEMES' industry data: each is one card's content, never the page's.
                              r"|sec_capex|sec_releases|mops_revenue|korea_customs|motie_trade|adata_market_watch|pcpartpicker|altdata_\w+)$")


@dataclass(frozen=True)
class Finding:
    severity: str
    check: str
    detail: str

    def as_dict(self) -> dict:
        return {"severity": self.severity, "check": self.check, "detail": self.detail}


def _load(name: str) -> dict | None:
    path = ARTIFACT_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _check_period_labels(config: dict) -> list[Finding]:
    """Every window a table offers has to be a window this codebase defines."""
    out = []
    for table, labels in config["periods"].items():
        if not isinstance(labels, list):
            continue
        for label in labels:
            if label not in PERIOD_TRADING_DAYS:
                out.append(Finding("error", "period_label", f"{table} offers unknown window {label!r}"))
    return out


def _check_as_of(manifest: dict, panels: dict[str, dict]) -> list[Finding]:
    """Every tab must describe the same session.

    The cross-listing tab fetched its own prices once and could date itself a
    day ahead of the rest of the page. One page showing two "todays" is worse
    than one showing yesterday.
    """
    out = []
    reference = manifest.get("as_of")
    for name, payload in panels.items():
        as_of = payload.get("as_of")
        if as_of is None or reference is None:
            continue
        # The published curve and the monthly releases legitimately lag: they
        # are dated by their publisher, not by the equity session.
        if name in {"fixed_income", "macro"}:
            continue
        # A carried MONITOR ledger keeps the session it last observed; the
        # carry itself is reported by _check_monitor_carried.
        if name == "monitor" and manifest.get("monitor_carried"):
            continue
        if as_of != reference:
            out.append(Finding("error", "as_of", f"{name} is dated {as_of}, manifest says {reference}"))
    return out


def _check_coverage(manifest: dict) -> list[Finding]:
    out = []
    for index in manifest.get("indices", []):
        members, priced = index.get("members", 0), index.get("priced", 0)
        if not members:
            out.append(Finding("error", "coverage", f"{index['key']} has no members"))
            continue
        ratio = priced / members
        if ratio < 0.95:
            out.append(Finding(
                "error", "coverage",
                f"{index['key']}: only {priced} of {members} members priced ({ratio:.0%})",
            ))
        elif priced < members:
            out.append(Finding(
                "warning", "coverage",
                f"{index['key']}: {members - priced} of {members} members unpriced",
            ))
    return out


def _check_latest_session(markets: dict | None) -> list[Finding]:
    """The page's session must have a measurable change, not just a price.

    Coverage counts members with *a* price; a session whose previous day is
    missing at the source (Yahoo once served a whole session as NaN) prices
    every member and measures none of them. Without this check that page
    deploys with blank 1D columns, zero advancers and zero decliners.
    """
    if not markets:
        return []
    out = []
    for key, block in (markets.get("indices") or {}).items():
        ad = block.get("advance_decline") or {}
        measured = sum(ad.get(k) or 0 for k in ("advancers", "decliners", "unchanged"))
        members = block.get("members") or 0
        if members and measured < SESSION_COVERAGE_THRESHOLD * members:
            out.append(Finding(
                "error", "latest_session",
                f"{key}: only {measured} of {members} members have a 1D change on "
                f"{markets.get('as_of')}; the prior session is missing at the source",
            ))
    index_row = (markets.get("sector_table") or {}).get("index") or {}
    if index_row and index_row.get("1D") is None:
        out.append(Finding("error", "latest_session", "the index row of the sector table has no 1D return"))
    return out


def _check_financials(payload: dict | None) -> list[Finding]:
    """Most members must have statements. A handful of IFRS filers and
    brand-new registrants are expected and listed on the page; losing a
    large share at once means the extraction broke, not the filers."""
    if payload is None:
        return []
    universe, extracted = payload.get("universe") or 0, len(payload.get("available") or [])
    if not extracted:
        return [Finding("error", "financials", "no company's statements were extracted")]
    if extracted < SESSION_COVERAGE_THRESHOLD * universe:
        return [Finding("warning", "financials", f"statements for only {extracted} of {universe} members")]
    return []


# Share of valued companies allowed to fail the SPY-weight check or lack a
# market cap before the build is warned. One or two are a filer's own quirk
# and are named on the page; more means the share-count logic broke.
VALUATION_TOLERATED_SHARE = 0.05


def _check_valuation(payload: dict | None) -> list[Finding]:
    if payload is None:
        return []
    rows = payload.get("rows") or []
    if not rows:
        return [Finding("error", "valuation", "no company was valued")]
    out = []
    check = payload.get("weight_check") or {}
    flagged, checked = len(check.get("flagged") or []), check.get("checked") or 0
    if checked and flagged > VALUATION_TOLERATED_SHARE * checked:
        out.append(Finding("warning", "valuation", f"{flagged} of {checked} share counts disagree with SPY weights"))
    history = payload.get("pe_history") or {}
    disagree, with_history = len(history.get("disagree") or []), history.get("companies") or 0
    if with_history and disagree > VALUATION_TOLERATED_SHARE * with_history:
        out.append(Finding("warning", "valuation",
                           f"the two P/E calculations disagree for {disagree} of {with_history} companies"))
    missing = len(payload.get("without_market_cap") or [])
    if missing > VALUATION_TOLERATED_SHARE * len(rows):
        out.append(Finding("warning", "valuation", f"{missing} of {len(rows)} companies have no market cap"))
    return out


def _check_catalysts(payload: dict | None) -> list[Finding]:
    """A calendar with a source missing reads as a quiet week; say so."""
    if payload is None:
        return []
    out = [Finding("notice", "catalysts", f"{source} not fetched: {why}")
           for source, why in (payload.get("failed_sources") or {}).items()]
    out += [Finding("notice", "catalysts", f"expected release not in its calendar: {m}")
            for m in payload.get("expected_missing") or []]
    if not payload.get("events"):
        out.append(Finding("error", "catalysts", "no upcoming event at all"))
    return out


# The one finding a deploy may go ahead with: the rest of the page is sound
# and only MONITOR is yesterday's, republished unchanged (build._carry_monitor).
CARRIED_CATEGORY = "monitor_carried"


def _check_monitor_carried(manifest: dict) -> list[Finding]:
    carried = manifest.get("monitor_carried")
    if not carried:
        return []
    return [Finding(
        "warning", CARRIED_CATEGORY,
        f"MONITOR was not rebuilt for {manifest.get('as_of')} ({carried.get('reason')}); the published "
        f"ledger observed to {carried.get('as_of')} is republished unchanged, not updated since {carried.get('since')}",
    )]


def _check_monitor(payload: dict | None) -> list[Finding]:
    if payload is None:
        return []
    from .sources.monitor_state import validate_previous

    try:
        validate_previous(payload)
    except (ValueError, TypeError, KeyError) as exc:
        return [Finding("error", "monitor", f"invalid observation ledger: {exc}")]
    rows = [row for row in payload["rows"] if row["in_universe"]]
    if not rows or len(rows) != payload["universe"]["members"]:
        return [Finding("error", "monitor", "monitor rows do not match the declared universe")]
    missing = sum(row.get("drawdown_pct") is None for row in rows)
    if missing == len(rows):
        return [Finding("error", "monitor", "no member has a measurable drawdown")]
    return ([Finding("notice", "monitor", f"{missing} members have unknown drawdown; see row data gaps")]
            if missing else [])


# An equity fund's listed-equity lines should be nearly the whole fund; much
# less means the parser dropped lines, more means a percent read as a fraction.
XRAY_EQUITY_WEIGHT_RANGE = (0.85, 1.02)


def _check_xray(config: dict, payload: dict | None) -> list[Finding]:
    if payload is None:
        return []
    out = []
    listed = {f["ticker"]: f for f in payload.get("funds") or []}
    for ticker, spec in (config.get("etf_xray", {}).get("holdings") or {}).items():
        fund = listed.get(ticker)
        if fund is None:
            out.append(Finding("error", "xray", f"{ticker} is configured but not listed"))
        elif not spec.startswith("none") and fund.get("status") != "ok":
            out.append(Finding("notice", "xray", f"{ticker}: holdings not fetched ({fund.get('reason')})"))
        elif fund.get("kind") == "equity":
            low, high = XRAY_EQUITY_WEIGHT_RANGE
            if not low <= (fund.get("equity_weight") or 0) <= high:
                out.append(Finding("error", "xray", f"{ticker}: equity lines sum to {fund.get('equity_weight')} of the fund"))
    return out


def _check_presets(config: dict, technicals: dict | None) -> list[Finding]:
    """A relative-strength preset whose legs were never baked renders empty."""
    if not technicals:
        return []
    available = set(technicals.get("available") or [])
    out = []
    for preset in config["technicals"]["presets"]:
        missing = [
            leg.strip().upper()
            for leg in str(preset).split("/")
            if leg.strip() and leg.strip().upper() not in available
        ]
        if missing:
            out.append(Finding(
                "error", "preset", f"preset {preset} names unbaked ticker(s): {', '.join(missing)}"
            ))
    return out


def _check_cross_listing(config: dict, payload: dict | None) -> list[Finding]:
    """The depositary ratio is the one input that fails silently when wrong.

    Reverse-engineered from prices it forces the premium to zero and draws a
    flat line that looks exactly like data, so a pair without a cited source is
    a build error rather than a cosmetic omission.
    """
    out = []
    for spec in config.get("cross_listing") or []:
        if not spec.get("ratio_source") or not spec.get("ratio_url"):
            out.append(Finding(
                "error", "ratio_provenance",
                f"{spec.get('us_ticker')}: ratio has no cited filing; a ratio without a source "
                "cannot be checked and must not be published",
            ))
    if payload:
        for pair in payload.get("pairs", []):
            if not pair.get("diagnostics", {}).get("sessions"):
                out.append(Finding(
                    "warning", "cross_listing", f"{pair.get('us_ticker')}: no diagnostics computed"
                ))
    return out


def _check_flow_attribution(heatmaps: dict | None) -> list[Finding]:
    """A fund counted under a provider that did not supply it."""
    if not heatmaps:
        return []
    out = []
    published = set(heatmaps.get("flow_coverage", {}).get("published") or [])
    attributed = {t for tickers in (heatmaps.get("flow_sources") or {}).values() for t in tickers}
    for ticker in sorted(published - attributed):
        out.append(Finding("error", "flow_attribution", f"{ticker} has flow but no named provider"))
    for ticker in sorted(attributed - published):
        out.append(Finding("error", "flow_attribution", f"{ticker} attributed to a provider but has no flow"))
    return out


def _check_sources(manifest: dict) -> list[Finding]:
    out = []
    for record in manifest.get("sources", []):
        severity = "notice" if OPTIONAL_SOURCES.match(record["source_id"]) else "warning"
        if record.get("status") == "error":
            out.append(Finding(severity, "source", f"{record['source_id']}: {record.get('error')}"))
        if record.get("freshness") == "stale":
            out.append(Finding(
                severity, "freshness",
                f"{record['source_id']} observed {record.get('observed_date')} is past its "
                f"{record.get('policy')} window",
            ))
    return out


def run() -> dict:
    """Validate the artifacts on disk. Returns a report, never raises."""
    config = load_config()
    manifest = _load("manifest")
    if manifest is None:
        return {"ok": False, "findings": [Finding("error", "manifest", "no manifest written").as_dict()]}

    panels = {name: payload for name in manifest.get("panels", []) if (payload := _load(name))}

    findings = (
        _check_period_labels(config)
        + _check_as_of(manifest, panels)
        + _check_coverage(manifest)
        + _check_latest_session(panels.get("markets"))
        + _check_presets(config, panels.get("technicals"))
        + _check_financials(panels.get("financials"))
        + _check_valuation(panels.get("valuation"))
        + _check_xray(config, panels.get("xray"))
        + _check_catalysts(panels.get("catalysts"))
        # A carried ledger is the live one verbatim; checking it against this
        # code is what may have failed, and would block the rest of the page.
        + (_check_monitor(panels.get("monitor")) if not manifest.get("monitor_carried") else [])
        + _check_monitor_carried(manifest)
        + _check_cross_listing(config, panels.get("cross_listing"))
        + _check_flow_attribution(panels.get("heatmaps"))
        + _check_sources(manifest)
    )
    for name, reason in (manifest.get("errors") or {}).items():
        findings.append(Finding("error", "panel", f"{name} failed: {reason}"))

    count = {severity: sum(f.severity == severity for f in findings) for severity in SEVERITIES}
    blocking = [f for f in findings if f.severity in ("error", "warning") and f.check != CARRIED_CATEGORY]
    return {
        "ok": not count["error"],
        "errors": count["error"],
        "warnings": count["warning"],
        "notices": count["notice"],
        # Whether the unattended run may publish this build even though it
        # fails --strict: true only when the carried MONITOR is the sole reason.
        "deployable": not blocking,
        "findings": [f.as_dict() for f in findings],
    }
