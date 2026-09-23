"""The contract itself, and the guards that keep a build from publishing a lie.

Every test here corresponds to something that reached the page at least once:
a period column nothing had defined, a session that had not closed, a row laid
under the wrong month, a preset naming a ticker no panel priced.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap import cache, config, context, validate
from market_recap.sources.http import FetchError


# --- The contract ----------------------------------------------------------

def test_every_window_a_table_offers_is_a_window_we_define():
    """A table offering "6M" needs PERIOD_TRADING_DAYS to say what 6M means."""
    settings = config.load_config()["periods"]
    for table, labels in settings.items():
        if isinstance(labels, list):
            for label in labels:
                assert label in config.PERIOD_TRADING_DAYS, f"{table} offers undefined {label}"


def test_period_sessions_rejects_an_unknown_label():
    """Returning None for a typo would silently be read as "YTD"."""
    assert config.period_sessions("1M") == 21
    assert config.period_sessions("YTD") is None
    with pytest.raises(KeyError):
        config.period_sessions("1Q")


def test_year_windows_are_multiples_of_one_trading_year():
    assert config.PERIOD_TRADING_DAYS["1Y"] == config.TRADING_DAYS_PER_YEAR
    assert config.PERIOD_TRADING_DAYS["5Y"] == config.TRADING_DAYS_PER_YEAR * 5
    assert config.CHART_SESSIONS == config.PERIOD_TRADING_DAYS["2Y"]


def test_every_index_declares_what_it_needs_and_exactly_one_is_primary():
    specs = [context.IndexSpec.from_config(s) for s in config.load_config()["universe"]["indices"]]
    assert specs, "the page must cover at least one index"
    assert sum(1 for s in specs if s.primary) == 1
    assert len({s.key for s in specs}) == len(specs)


def test_a_cross_listing_ratio_always_cites_its_filing():
    """A ratio reverse-engineered from prices forces the premium to zero and
    draws a flat line that looks exactly like data. The source is the check."""
    for spec in config.load_config().get("cross_listing") or []:
        assert spec.get("ratio_source"), f"{spec['us_ticker']} ratio has no cited filing"
        assert str(spec.get("ratio_url", "")).startswith("http")


# --- The completed-session guard ------------------------------------------

def test_an_unfinished_session_is_dropped_from_the_panel():
    """The provider serves an intraday bar for whatever it refreshed most
    recently while hundreds of cached symbols still end on the prior close."""
    index = pd.bdate_range("2024-01-01", periods=4)
    frame = pd.DataFrame(
        {f"S{i}": [1.0, 2.0, 3.0, (4.0 if i < 2 else None)] for i in range(20)}, index=index
    )
    trimmed = context.completed_sessions(frame)
    assert trimmed.index[-1] == index[-2]


def test_a_fully_priced_session_is_kept():
    index = pd.bdate_range("2024-01-01", periods=3)
    frame = pd.DataFrame({f"S{i}": [1.0, 2.0, 3.0] for i in range(20)}, index=index)
    assert context.completed_sessions(frame).index[-1] == index[-1]


# --- Cache ------------------------------------------------------------------

def test_cache_kinds_are_named_not_guessed():
    assert cache.ttl("filings") == config.CACHE_TTL["filings"]
    with pytest.raises(KeyError):
        cache.ttl("filing")  # a typo must not silently mean "one week"


def test_a_404_is_remembered_and_a_500_is_not(tmp_path, monkeypatch):
    """Whether an issuer publishes a file is a property of the fund. Whether
    its server is up today is not, and caching that would drop a live feed."""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)

    calls = {"n": 0}

    def missing():
        calls["n"] += 1
        raise FetchError("gone", not_found=True)

    for _ in range(3):
        with pytest.raises(FetchError):
            cache.fetch_bytes("t", "a", missing, kind="daily_file", remember_missing=True)
    assert calls["n"] == 1, "a 404 should be probed once, not once per build"

    def flaky():
        calls["n"] += 1
        raise FetchError("server error")

    for _ in range(2):
        with pytest.raises(FetchError):
            cache.fetch_bytes("t", "b", flaky, kind="daily_file", remember_missing=True)
    assert calls["n"] == 3, "a transient failure must be retried on the next build"


def test_prune_removes_expired_entries_only(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    fresh = tmp_path / "ns" / "fresh.bin"
    stale = tmp_path / "ns" / "stale.bin"
    fresh.parent.mkdir(parents=True)
    fresh.write_bytes(b"x")
    stale.write_bytes(b"y")
    import os
    old = (pd.Timestamp.now() - pd.Timedelta(days=400)).timestamp()
    os.utime(stale, (old, old))

    result = cache.prune(keep=timedelta(days=30))
    assert result["files_removed"] == 1
    assert fresh.exists() and not stale.exists()


# --- Validation -------------------------------------------------------------

def _manifest(**overrides) -> dict:
    base = {
        "as_of": "2026-09-21",
        "indices": [{"key": "SPX", "label": "S&P 500", "members": 100, "priced": 100}],
        "panels": [],
        "sources": [],
        "errors": {},
    }
    return base | overrides


def test_validation_flags_a_tab_dated_to_a_different_session():
    findings = validate._check_as_of(
        _manifest(), {"markets": {"as_of": "2026-09-21"}, "cross_listing": {"as_of": "2026-09-22"}}
    )
    assert [f.check for f in findings] == ["as_of"]
    assert "cross_listing" in findings[0].detail


def test_validation_allows_a_publisher_that_legitimately_lags():
    """The par curve and the monthly releases are dated by their publisher."""
    findings = validate._check_as_of(
        _manifest(), {"fixed_income": {"as_of": "2026-09-19"}, "macro": {"as_of": "2026-07-01"}}
    )
    assert findings == []


def test_validation_flags_a_preset_whose_legs_were_never_baked():
    """A preset naming an unfetched ticker renders as an empty chart."""
    cfg = {"technicals": {"presets": ["XLK/SPY", "SOXX/SPY"]}}
    findings = validate._check_presets(cfg, {"available": ["XLK", "SPY"]})
    assert len(findings) == 1 and "SOXX" in findings[0].detail
    assert validate._check_presets(cfg, {"available": ["XLK", "SPY", "SOXX"]}) == []


def test_validation_flags_flow_attributed_to_no_provider():
    findings = validate._check_flow_attribution(
        {"flow_coverage": {"published": ["SPY", "SHY"]}, "flow_sources": {"ssga": ["SPY"]}}
    )
    assert len(findings) == 1 and "SHY" in findings[0].detail


def test_validation_flags_thin_index_coverage():
    assert validate._check_coverage(_manifest()) == []
    thin = _manifest(indices=[{"key": "NDX", "label": "Nasdaq 100", "members": 100, "priced": 80}])
    findings = validate._check_coverage(thin)
    assert findings and findings[0].severity == "error"


# --- Macro month alignment -------------------------------------------------

class _Ctx:
    """Minimal stand-in: the macro builder only needs config, a log and a date."""

    def __init__(self, cfg):
        self.config = cfg
        self.as_of = "2026-09-21"
        from market_recap.util import BuildLog

        self.log = BuildLog()


def test_a_lagging_series_leaves_a_blank_instead_of_shifting_a_month(monkeypatch):
    """Each row used to be that series' own last twelve values, printed under
    the *first* series' month headers. These publishers do not share a release
    lag, so a row one month behind was rendered shifted a column -- every
    number under the wrong month, and nothing on the page to show it."""
    from market_recap.panels import macro
    from market_recap.sources import fred, yahoo

    current = pd.date_range("2025-01-01", periods=21, freq="MS")
    lagging = current[:-1]  # this publisher has not printed the latest month

    def fake_series(series_id, **_):
        index = lagging if series_id == "LAGGY" else current
        values = list(range(len(index)))
        return pd.DataFrame({"date": index, "value": values}), f"http://example/{series_id}"

    monkeypatch.setattr(fred, "fetch_series", fake_series)
    monkeypatch.setattr(yahoo, "fetch_closes", lambda *a, **k: pd.DataFrame())

    cfg = config.load_config()
    cfg = dict(cfg)
    cfg["macro"] = dict(cfg["macro"]) | {
        "inflation": [
            {"series_id": "CURRENT", "label": "Current", "unit": "level", "display": "level"},
            {"series_id": "LAGGY", "label": "Lagging", "unit": "level", "display": "level"},
        ]
    }

    payload = macro.build(_Ctx(cfg))
    inflation = payload["inflation"]
    rows = {row["label"]: row for row in inflation["rows"]}

    assert len(inflation["months"]) == inflation["releases"]
    assert inflation["months"][-1] == current[-1].strftime("%Y-%m")
    # The lagging row is blank in the last column, not shifted into it.
    assert rows["Lagging"]["values"][-1] is None
    assert rows["Current"]["values"][-1] is not None
    assert rows["Lagging"]["latest_month"] == lagging[-1].strftime("%Y-%m")
    # Every row is the same length, so a column header describes every cell
    # beneath it.
    assert {len(row["values"]) for row in inflation["rows"]} == {inflation["releases"]}


def test_a_compressed_entry_round_trips_and_is_actually_smaller(tmp_path, monkeypatch):
    """SEC company facts are 3-4 MB of JSON each and 121 of them filled 472 MB
    of a cache that a scheduled job refills every three days."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    payload = json.dumps({"facts": {f"tag{i}": list(range(200)) for i in range(200)}}).encode()

    stored = cache.fetch_bytes(
        "sec", "CIK0000320193", lambda: payload, kind="filings", suffix=".json", compress=True
    )
    assert stored == payload

    path = cache.path_for("sec", "CIK0000320193", ".json.gz")
    assert path.exists(), "a compressed entry is stored under .gz"
    assert path.stat().st_size < len(payload) / 4

    # The second call must come from disk, not the network.
    def explode() -> bytes:
        raise AssertionError("a fresh compressed entry should not be refetched")

    assert cache.fetch_bytes(
        "sec", "CIK0000320193", explode, kind="filings", suffix=".json", compress=True
    ) == payload


def test_a_truncated_compressed_entry_is_refetched_not_fatal(tmp_path, monkeypatch):
    """A build killed mid-write must not poison the cache permanently."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    path = cache.path_for("sec", "broken", ".json.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x1f\x8b not really gzip")

    assert cache.fetch_bytes(
        "sec", "broken", lambda: b"fresh", kind="filings", suffix=".json", compress=True
    ) == b"fresh"


# --- Deployed site ----------------------------------------------------------

def _headers_rules(text: str) -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" "):
            current = line.strip()
            rules[current] = []
        elif current:
            rules[current].append(line.strip())
    return rules


def test_header_paths_do_not_overlap(tmp_path):
    """Cloudflare Pages applies *every* matching rule and concatenates them.

    A "/*" catch-all beside a "/js/*" rule produced
    "no-cache, public, max-age=31536000, immutable" on one response -- a header
    that contradicts itself and leaves the outcome to whichever directive a
    given browser honours.
    """
    from market_recap import site

    site.build(dist=tmp_path)
    rules = _headers_rules((tmp_path / "_headers").read_text())
    assert rules, "the deployed site must set cache headers"

    def matches(pattern: str, path: str) -> bool:
        return path.startswith(pattern[:-1]) if pattern.endswith("*") else pattern == path

    for sample in ("/", "/index.html", "/css/terminal.css", "/js/app.js", "/artifacts/manifest.json"):
        hit = [p for p in rules if matches(p, sample)]
        assert len(hit) <= 1, f"{sample} matches more than one rule: {hit}"


def test_only_build_stamped_assets_are_cached_hard(tmp_path):
    """The JS may be cached forever because its URL carries the build stamp
    (`app.js?v=<generated_at>`), so a new build is a new URL. Nothing else has
    a versioned URL, and a cache lifetime longer than the deploy interval on a
    file whose URL never changes is a way to ship a fix that does not arrive --
    which is exactly what `max-age=3600` on the unversioned stylesheet did."""
    from market_recap import site

    site.build(dist=tmp_path)
    rules = _headers_rules((tmp_path / "_headers").read_text())
    for pattern, directives in rules.items():
        joined = " ".join(directives).lower()
        if "immutable" in joined or "max-age=31536000" in joined:
            assert pattern.startswith("/js/"), (
                f"{pattern} is cached hard but its URL carries no build stamp"
            )
        else:
            assert "no-cache" in joined, f"{pattern} sets neither no-cache nor a versioned cache"


NY = config.MARKET_TIMEZONE


def _ny(text: str) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(NY))


@pytest.mark.parametrize(
    "now, expected",
    [
        ("2026-09-22 19:37", "2026-09-22 18:30"),  # Tue evening run: tonight's rollover
        ("2026-09-22 17:00", "2026-09-21 18:30"),  # Tue, before rollover: still Monday's
        ("2026-09-21 10:00", "2026-09-18 18:30"),  # Mon morning: Friday's
        ("2026-09-19 23:00", "2026-09-18 18:30"),  # Saturday: Friday's
    ],
)
def test_the_session_rollover_is_the_last_weekday_evening_in_new_york(now, expected):
    assert cache.last_rollover(_ny(now)) == _ny(expected)


def test_a_daily_file_from_before_the_rollover_is_stale_even_if_under_a_day_old(tmp_path):
    """The bug this guards: a nightly run starting a few minutes earlier than
    the night before found yesterday's closes under 24h old, reused them, and
    published a page one session behind that passed every check."""
    import os

    path = tmp_path / "closes.parquet"
    path.write_bytes(b"x")
    yesterdays_run = _ny("2026-09-21 19:45").timestamp()
    os.utime(path, (yesterdays_run, yesterdays_run))
    tonight = _ny("2026-09-22 19:37")
    assert tonight - _ny("2026-09-21 19:45") < config.CACHE_TTL["daily_file"]
    assert not cache.is_fresh(path, "daily_file", now=tonight)
    # A kind that is not per-session keeps its plain TTL.
    assert cache.is_fresh(path, "reference_data", now=tonight)
    # And the same file is reused by a rerun on the evening it was written.
    assert cache.is_fresh(path, "daily_file", now=_ny("2026-09-21 21:00"))


def test_validation_flags_a_session_whose_prior_day_is_missing():
    """Every member priced, none measured: the page Yahoo's all-NaN session produces."""
    healthy = {
        "as_of": "2026-09-23",
        "indices": {"SPX": {"members": 503, "advance_decline": {"advancers": 300, "decliners": 200, "unchanged": 3}}},
        "sector_table": {"index": {"1D": 0.4}},
    }
    assert validate._check_latest_session(healthy) == []
    hole = {
        "as_of": "2026-09-23",
        "indices": {"SPX": {"members": 503, "advance_decline": {"advancers": 0, "decliners": 0, "unchanged": 0}}},
        "sector_table": {"index": {"1D": None}},
    }
    findings = validate._check_latest_session(hole)
    assert len(findings) == 2 and all(f.severity == "error" for f in findings)


def test_validation_flags_financials_that_mostly_failed():
    assert validate._check_financials({"universe": 518, "available": [{}] * 512}) == []
    assert validate._check_financials({"universe": 518, "available": [{}] * 300})[0].severity == "warning"
    assert validate._check_financials({"universe": 518, "available": []})[0].severity == "error"


def test_validation_flags_share_counts_that_broke_wholesale():
    ok = {"rows": [{}] * 500, "weight_check": {"checked": 490, "flagged": [{}] * 2}, "without_market_cap": ["V"] * 6}
    assert validate._check_valuation(ok) == []
    broken = {**ok, "weight_check": {"checked": 490, "flagged": [{}] * 60}}
    assert validate._check_valuation(broken)[0].severity == "warning"
    assert validate._check_valuation({"rows": []})[0].severity == "error"


def test_a_ticker_the_build_no_longer_writes_is_not_left_behind(tmp_path):
    from market_recap.util import prune_stale

    for name in ("AAPL", "MNST", "GONE"):
        (tmp_path / f"{name}.json").write_text("{}")
    assert prune_stale(tmp_path, ["AAPL", "MNST"]) == ["GONE.json"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["AAPL.json", "MNST.json"]


def test_an_optional_feed_failing_is_a_notice_and_a_core_one_a_warning():
    from market_recap import validate
    manifest = {"sources": [
        {"source_id": "catalysts_nasdaq_earnings", "status": "error", "error": "refused"},
        {"source_id": "vanguard_xray_holdings", "status": "error", "error": "timeout"},
        {"source_id": "yahoo_constituents", "status": "error", "error": "timeout"},
    ]}
    severities = {f.detail.split(":")[0]: f.severity for f in validate._check_sources(manifest)}
    assert severities == {"catalysts_nasdaq_earnings": "notice", "vanguard_xray_holdings": "notice",
                          "yahoo_constituents": "warning"}


def test_building_the_site_never_shares_a_file_with_the_source(tmp_path):
    from market_recap import site
    site.build(dist=tmp_path / "dist")
    for source in site.WEB_DIR.rglob("*"):
        if source.is_file():
            assert source.stat().st_nlink == 1, f"{source} is hard-linked"
