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

from .config import ARTIFACT_DIR, PERIOD_TRADING_DAYS, SESSION_COVERAGE_THRESHOLD, load_config

SEVERITIES = ("error", "warning")


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
        if record.get("status") == "error":
            out.append(Finding("warning", "source", f"{record['source_id']}: {record.get('error')}"))
        if record.get("freshness") == "stale":
            out.append(Finding(
                "warning", "freshness",
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
        + _check_cross_listing(config, panels.get("cross_listing"))
        + _check_flow_attribution(panels.get("heatmaps"))
        + _check_sources(manifest)
    )
    for name, reason in (manifest.get("errors") or {}).items():
        findings.append(Finding("error", "panel", f"{name} failed: {reason}"))

    errors = [f for f in findings if f.severity == "error"]
    return {
        "ok": not errors,
        "errors": len(errors),
        "warnings": len(findings) - len(errors),
        "findings": [f.as_dict() for f in findings],
    }
