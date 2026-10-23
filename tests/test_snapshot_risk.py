import csv
from datetime import datetime, timezone
import gzip
import io
import json

import pandas as pd

from market_recap.snapshots import risk as snap


def _no_units(cusip):
    raise RuntimeError("not in tests")


def _series(values, start="2026-09-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_risk_snapshot_records_the_recent_tail_of_each_series_and_its_failures(tmp_path):
    ofr = pd.DataFrame({"OFR FSI": [-2.0, -2.5], "Credit": [-1.0, -1.1]}, index=pd.bdate_range("2026-09-24", periods=2))

    def fred(series_id):
        if series_id == "NFCI":
            raise RuntimeError("503")
        return _series(range(40))

    now = datetime(2026, 9, 25, 23, 17, tzinfo=timezone.utc)
    out = snap.run(root=tmp_path, now=now, fetch_ofr=lambda: ofr, fetch_fred=fred, fetch_cboe=lambda s: _series([15.0, 16.0]), fetch_units=_no_units)
    assert out["status"] == "partial" and "fred NFCI" in out["failed"]
    path = tmp_path / "risk" / "2026" / "2026-09-25.csv.gz"
    rows = list(csv.DictReader(io.StringIO(gzip.decompress(path.read_bytes()).decode())))
    fsi = [r for r in rows if r["series"] == "FSI"]
    assert [r["value"] for r in fsi] == ["-2.0", "-2.5"]
    # FRED series keep only the configured tail, newest last.
    hy = [r for r in rows if r["series"] == "BAMLH0A0HYM2"]
    assert len(hy) == 30 and hy[-1]["value"] == "39.0"
    assert {r["fetched_at"] for r in rows} == {"2026-09-25T23:17:00Z"}
    runs = [json.loads(line) for line in (tmp_path / "risk" / "2026" / "runs.jsonl").read_text().splitlines()]
    assert runs[-1]["rows"] == len(rows)


def test_the_first_run_writes_a_full_history_baseline_and_later_runs_do_not(tmp_path):
    long = _series(range(100))
    kwargs = dict(fetch_ofr=lambda: pd.DataFrame({"OFR FSI": long}), fetch_fred=lambda s: long, fetch_cboe=lambda s: long,
                  fetch_units=_no_units)
    first = snap.run(root=tmp_path, now=datetime(2026, 9, 25, 23, 17, tzinfo=timezone.utc), **kwargs)
    assert first["baseline"]["rows"] > first["rows"]
    baseline = tmp_path / "risk" / "baseline" / "2026-09-25.csv.gz"
    rows = list(csv.DictReader(io.StringIO(gzip.decompress(baseline.read_bytes()).decode())))
    assert len([r for r in rows if r["series"] == "FSI"]) == 100
    assert "Not point-in-time" in json.loads((tmp_path / "risk" / "baseline" / "2026-09-25.json").read_text())["note"]
    second = snap.run(root=tmp_path, now=datetime(2026, 9, 28, 23, 17, tzinfo=timezone.utc), **kwargs)
    assert second["baseline"] is None


def test_the_archive_reads_back_with_the_later_fetch_winning(tmp_path, monkeypatch):
    from market_recap.sources import snapshot_store

    monkeypatch.setattr(snapshot_store, "root", lambda: tmp_path)
    old = _series([1.0, 2.0, 3.0], start="2026-09-21")
    revised = _series([3.5, 4.0], start="2026-09-23")
    common = dict(fetch_ofr=lambda: pd.DataFrame(), fetch_cboe=lambda s: pd.Series(dtype=float), fetch_units=_no_units)
    snap.run(root=tmp_path, now=datetime(2026, 9, 23, 23, 17, tzinfo=timezone.utc), fetch_fred=lambda s: old, **common)
    snap.run(root=tmp_path, now=datetime(2026, 9, 24, 23, 17, tzinfo=timezone.utc), fetch_fred=lambda s: revised, **common)
    series = snapshot_store.risk_archive("fred", "BAMLH0A0HYM2")
    assert series.tolist() == [1.0, 2.0, 3.5, 4.0]


def test_invesco_units_are_recorded_and_read_back_as_a_flow_record(tmp_path, monkeypatch):
    from market_recap.sources import snapshot_store

    monkeypatch.setattr(snapshot_store, "root", lambda: tmp_path)
    snapshot_store._RISK_ROWS.clear()
    empty = dict(fetch_ofr=lambda: pd.DataFrame(), fetch_fred=lambda s: pd.Series(dtype=float),
                 fetch_cboe=lambda s: pd.Series(dtype=float))
    days = iter([{"date": "2026-09-28", "nav": 736.4, "shares_outstanding": 671_450_000},
                 {"date": "2026-09-28", "nav": 736.4, "shares_outstanding": 671_450_000},   # issuer not yet updated
                 {"date": "2026-09-29", "nav": 740.0, "shares_outstanding": 672_000_000}])
    asked = []

    def units(cusip):
        asked.append(cusip)
        return next(days)

    monkeypatch.setattr(snap, "load_config", lambda: {
        "snapshots": {"risk": {"invesco": ["QQQ"], "fred": [], "cboe": []}},
        "etf_xray": {"holdings": {"QQQ": "invesco:46090E103"}},
    })
    first = snap.run(root=tmp_path, now=datetime(2026, 9, 28, 23, 17, tzinfo=timezone.utc), fetch_units=units, **empty)
    # QQQ from config, then QQQM from the module's own list, by its CUSIP.
    assert first["answered"]["invesco QQQ"] == 1 and asked == ["46090E103", "46138G649"]
    assert first["answered"]["invesco QQQM"] == 1
    assert snapshot_store.etf_units("QQQ").empty          # one day is not yet a flow
    snapshot_store._RISK_ROWS.clear()
    snap.run(root=tmp_path, now=datetime(2026, 9, 29, 12, 7, tzinfo=timezone.utc), fetch_units=units, **empty)
    snap.run(root=tmp_path, now=datetime(2026, 9, 29, 23, 17, tzinfo=timezone.utc), fetch_units=units, **empty)
    snapshot_store._RISK_ROWS.clear()
    frame = snapshot_store.etf_units("QQQ")
    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-09-28", "2026-09-29"]
    assert frame["shares_outstanding"].tolist() == [671_450_000, 672_000_000]


def test_a_fund_without_an_invesco_cusip_is_reported_not_guessed(tmp_path, monkeypatch):
    monkeypatch.setattr(snap, "load_config", lambda: {
        "snapshots": {"risk": {"invesco": ["VOO"], "fred": [], "cboe": []}},
        "etf_xray": {"holdings": {"VOO": "vanguard"}},
    })
    out = snap.run(root=tmp_path, now=datetime(2026, 9, 28, 23, 17, tzinfo=timezone.utc),
                   fetch_ofr=lambda: pd.DataFrame(), fetch_fred=lambda s: pd.Series(dtype=float),
                   fetch_cboe=lambda s: pd.Series(dtype=float), fetch_units=_no_units)
    assert "invesco VOO" in out["failed"]
