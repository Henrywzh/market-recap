"""Ramp Token Spend Management: weekly totals, shares, effective prices and the page contract."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from market_recap.panels import themes as TH
from market_recap.sources import altdata

WEEKS = ["2026-08-02", "2026-08-09", "2026-08-16", "2026-08-23", "2026-08-30"]
DAYS = [f"2026-08-{d:02d}" for d in range(3, 13)]           # ten days
SETTINGS = {
    "ramp_tokenomics_default_makers": ["google", "xai", "anthropic", "openai", "deepseek"],
    "ramp_tokenomics_models": 1,
    "ramp_tokenomics_names": {"openai": "OpenAI", "anthropic": "Anthropic", "xai": "xAI"},   # google falls back to its key
}


def _series(maker, key, label, metric, values):
    """One series' weekly rows; a None value means no row that week (a gap), a 0.0 is a reported zero."""
    rows = []
    for week, value in zip(WEEKS, values):
        if value is None:
            continue
        rows.append({"scraped_at": "2026-08-31T06:00:00Z", "period_grain": "weekly",
                     "period_start": (pd.Timestamp(week) - pd.Timedelta(days=6)).strftime("%Y-%m-%d"),
                     "period_end": week, "metric_key": metric, "dimension_type": "model",
                     "series_key": key, "series_label": label, "model_maker": maker, "metric_value": value})
    return rows


def _activity() -> pd.DataFrame:
    gpt_a = _series("openai", "gpt-5-a", "GPT-5", "token_volume", [4e9, 5e9, 6e9, 7e9, 8e9])
    gpt_a[0]["series_label"] = "GPT 5 preview"           # an older label: the most recent row's label is used
    rows = gpt_a
    rows += _series("openai", "gpt-5-b", "GPT-5", "token_volume", [1e9] * 5)          # same label, another alias
    rows += _series("anthropic", "claude-x", "Claude X", "token_volume", [2e9, 0.0, 3e9, 3e9, 3e9])
    rows += _series("google", "gemini-y", "Gemini Y", "token_volume", [1e9, 1e9, None, 2e9, 2e9])
    spend_a = _series("openai", "gpt-5-a", "GPT-5", "token_spend", [10e6, 12e6, 14e6, 16e6, 18e6])
    spend_a[0]["series_label"] = "GPT 5 preview"
    rows += spend_a
    rows += _series("openai", "gpt-5-b", "GPT-5", "token_spend", [2e6] * 5)
    rows += _series("anthropic", "claude-x", "Claude X", "token_spend", [4e6, 0.0, 6e6, 6e6, 6e6])
    rows += _series("google", "gemini-y", "Gemini Y", "token_spend", [1e6, 1e6, None, 2e6, 2e6])
    return pd.DataFrame(rows)


def _price(day, maker, cost, count, token_type="all_tokens"):
    return {"usage_date": day, "token_type": token_type, "model_maker": maker,
            "token_cost_usd_7d": cost, "token_count_7d": count}


def _prices() -> pd.DataFrame:
    rows = []
    for i, day in enumerate(DAYS):
        if i == 4:
            rows.append(_price(day, "openai", 0.0, 0.0))                 # zero tokens in the window: no price
        else:
            rows.append(_price(day, "openai", 2.0 * (i + 1), 1e6 * (i + 1)))
        rows.append(_price(day, "anthropic", 3.0 * (i + 1), 1e6 * (i + 1)))
    rows.append(_price(DAYS[0], "openai", 1.0, 3e6))                     # a second row the same day: sums, not averages
    return pd.DataFrame(rows)


def _patch(monkeypatch, activity, prices=None, commit=None):
    tables = {"activity": activity, "prices": _prices() if prices is None else prices}
    monkeypatch.setattr(altdata, "ramp_tokenomics", lambda *, use_cache=True: (tables, commit))


def test_gaps_stay_none_and_reported_zeros_stay_zero(monkeypatch):
    _patch(monkeypatch, _activity())
    out = TH._ramp_tokenomics(SETTINGS)
    assert out["weeks"] == WEEKS
    makers = {m["key"]: m for m in out["volume"]["makers"]}
    assert makers["google"]["values"] == [1.0, 1.0, None, 2.0, 2.0]        # missing week: a gap
    assert makers["anthropic"]["values"][1] == 0.0                         # reported zero: zero
    spend ={m["key"]: m for m in out["spend"]["makers"]}
    assert spend["google"]["values"] == [1.0, 1.0, None, 2.0, 2.0]
    assert spend["anthropic"]["values"] == [4.0, 0.0, 6.0, 6.0, 6.0]


def test_totals_cover_every_reported_series_not_just_the_shipped_one(monkeypatch):
    _patch(monkeypatch, _activity())
    out = TH._ramp_tokenomics(SETTINGS)                                    # ramp_tokenomics_models = 1
    assert out["volume"]["unit"] == "billion tokens" and out["spend"]["unit"] == "USD million"
    assert out["volume"]["total"] == [8.0, 7.0, 10.0, 13.0, 14.0]          # 4+1+2+1, 5+1+0+1, 6+1+3, 7+1+3+2, 8+1+3+2
    assert out["spend"]["total"] == [17.0, 15.0, 22.0, 26.0, 28.0]
    assert [m["key"] for m in out["volume"]["models"]] == ["openai · gpt-5-a"]
    assert out["models_shown"] == 1 and out["models_total"] == 4          # 4 distinct (maker, series_key) with data
    shipped = out["volume"]["models"][0]
    assert shipped["values"] == [4.0, 5.0, 6.0, 7.0, 8.0]
    assert shipped["values"][0] / out["volume"]["total"][0] == 0.5        # share of the full sample, not of the shipped rows


def test_same_label_different_keys_are_separate_models_and_the_latest_label_is_used(monkeypatch):
    _patch(monkeypatch, _activity())
    out = TH._ramp_tokenomics({**SETTINGS, "ramp_tokenomics_models": 10})
    models = {m["key"]: m for m in out["volume"]["models"]}
    assert set(models) == {"openai · gpt-5-a", "openai · gpt-5-b", "anthropic · claude-x", "google · gemini-y"}
    assert models["openai · gpt-5-a"]["values"] == [4.0, 5.0, 6.0, 7.0, 8.0]
    assert models["openai · gpt-5-b"]["values"] == [1.0] * 5
    assert models["openai · gpt-5-a"]["label"] == "GPT-5" and models["openai · gpt-5-a"]["maker"] == "openai"
    assert out["models_shown"] == 4 and out["models_total"] == 4


def test_makers_sorted_by_recent_sum_and_default_makers_in_config_order(monkeypatch):
    _patch(monkeypatch, _activity())
    out = TH._ramp_tokenomics(SETTINGS)
    assert [m["key"] for m in out["volume"]["makers"]] == ["openai", "anthropic", "google"]
    assert [m["name"] for m in out["volume"]["makers"]] == ["OpenAI", "Anthropic", "google"]
    assert out["default_makers"] == ["google", "anthropic", "openai"]      # config order; xai and deepseek have no data


def test_a_whole_missing_week_is_a_gap_in_the_weekly_index(monkeypatch):
    rows = _series("openai", "gpt-5-a", "GPT-5", "token_volume", [1e9, None, 2e9, None, None])
    rows += _series("openai", "gpt-5-a", "GPT-5", "token_spend", [1e6, None, 2e6, None, None])
    _patch(monkeypatch, pd.DataFrame(rows), prices=pd.DataFrame())
    out = TH._ramp_tokenomics(SETTINGS)
    assert out["weeks"] == ["2026-08-02", "2026-08-09", "2026-08-16"]     # the Sunday in between is kept
    assert out["volume"]["total"] == [1.0, None, 2.0]
    assert out["spend"]["total"] == [1.0, None, 2.0]


def test_prices_are_summed_cost_over_summed_tokens_and_zero_tokens_give_none(monkeypatch):
    _patch(monkeypatch, _activity())
    out = TH._ramp_tokenomics(SETTINGS)
    prices = out["prices"]
    assert prices["unit"] == "USD per million tokens"
    assert prices["dates"] == DAYS
    all_tokens = {p["key"]: p for p in prices["types"]["all_tokens"]}
    assert [p["key"] for p in prices["types"]["all_tokens"]] == ["anthropic", "openai"]
    assert all_tokens["openai"]["name"] == "OpenAI" and all_tokens["anthropic"]["name"] == "Anthropic"
    assert all_tokens["openai"]["values"] == [0.75, 2.0, 2.0, 2.0, None, 2.0, 2.0, 2.0, 2.0, 2.0]   # day 1: (2+1)/(1+3) M, not (2+0.33)/2
    assert all_tokens["anthropic"]["values"] == [3.0] * 10
    assert prices["types"]["uncached_input"] == [] and prices["types"]["output"] == []


def test_latest_week_capture_and_staleness(monkeypatch):
    _patch(monkeypatch, _activity(), commit={"sha": "abc123", "date": "2026-08-31T07:00:00Z"})
    out = TH._ramp_tokenomics(SETTINGS)
    assert out["latest_week"] == "2026-08-30"
    assert out["captured_at"] == "2026-08-31T06:00:00+00:00"
    assert out["stale_days"] == (datetime.now(timezone.utc).date() - pd.Timestamp("2026-08-30").date()).days
    assert out["commit"] == {"sha": "abc123", "date": "2026-08-31T07:00:00Z"}


def test_no_activity_rows_raises_so_the_section_records_why(monkeypatch):
    _patch(monkeypatch, pd.DataFrame())
    with pytest.raises(RuntimeError, match="no Ramp tokenomics files read"):
        TH._ramp_tokenomics(SETTINGS)


def test_reader_fetches_the_activity_and_price_files_and_the_activity_commit(monkeypatch):
    read_paths, commit_paths = [], []

    def fake_read(path, *, use_cache=True):
        read_paths.append(path)
        return pd.DataFrame({"x": [1]})

    monkeypatch.setattr(altdata, "read", fake_read)
    monkeypatch.setattr(altdata, "commit", lambda path, *, use_cache=True: commit_paths.append(path) or {"sha": "s", "date": "d"})
    tables, commit = altdata.ramp_tokenomics(use_cache=False)
    assert sorted(read_paths) == ["ramp/ramp_ai_token_activity.parquet", "ramp/ramp_ai_token_prices.parquet"]
    assert commit_paths == ["ramp/ramp_ai_token_activity.parquet"]
    assert set(tables) == {"activity", "prices"} and commit == {"sha": "s", "date": "d"}
