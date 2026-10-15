"""Datasets published by the alternative-data repository.

Two collections are too large to port here and are read from that repo's
normalized Parquet files on GitHub instead:

- OpenRouter: daily tokens and estimated revenue by model author
  (``marts/daily_provider_economics/YYYY-MM.parquet``, one file per month).
  Revenue is alternative-data's estimate -- observed tokens times the
  model's list price at the time -- not a company figure.
- Ramp AI Index: the share of US businesses on Ramp paying for AI tools,
  and AI spend per employee per month (PEPM), overall, by sector and by
  vendor (``ramp/*.parquet``).
- Ramp Token Spend Management tokenomics: weekly token volume and spend by
  model, and daily effective token prices for OpenAI and Anthropic
  (``ramp/ramp_ai_token_*.parquet``). Ramp's sample of connected businesses,
  not its total AI spend and not a provider's revenue.

Each read records the commit that last touched the file (GitHub API; the
workflow's token is used when present, so the limit is not the anonymous
60 an hour) so a figure on the page can be traced to the exact file.
"""

from __future__ import annotations

from datetime import date
import io
import json
import os

import httpx
import pandas as pd

from .. import cache

REPO = "Henrywzh/alternative-data"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/data/normalized/"
API = f"https://api.github.com/repos/{REPO}/commits"
HOME_URL = f"https://github.com/{REPO}"
NAMESPACE = "altdata"
RAMP_URL = "https://ramp.com/data/ai-index"
RAMP_TOKENOMICS_URL = "https://ramp.com/data/ai-index?metric=token-spend&detail=maker&mode=volume"
OPENROUTER_URL = "https://openrouter.ai/rankings"


def _headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _download(path: str) -> bytes:
    response = httpx.get(RAW + path, timeout=60.0, follow_redirects=True)
    response.raise_for_status()
    return response.content


def read(path: str, *, use_cache: bool = True) -> pd.DataFrame:
    payload = cache.fetch_bytes(NAMESPACE, path.replace("/", "__"), lambda: _download(path),
                                kind="daily_file", suffix=".parquet", use_cache=use_cache)
    return pd.read_parquet(io.BytesIO(payload))


def commit(path: str, *, use_cache: bool = True) -> dict | None:
    """The last commit touching one file: its sha and date."""
    def fetch() -> str:
        response = httpx.get(API, params={"path": f"data/normalized/{path}", "per_page": 1},
                             headers=_headers(), timeout=30.0)
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return "{}"
        return json.dumps({"sha": rows[0]["sha"], "date": rows[0]["commit"]["committer"]["date"]})
    try:
        text = cache.fetch_text(NAMESPACE, "commit-" + path.replace("/", "__"), fetch,
                                kind="daily_file", suffix=".json", use_cache=use_cache)
        return json.loads(text) or None
    except Exception:
        return None                                 # provenance is best effort; the data is not


def _months(today: date, count: int) -> list[str]:
    out, year, month = [], today.year, today.month
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


def openrouter_daily(today: date, *, months: int = 7, use_cache: bool = True) -> tuple[pd.DataFrame, dict | None]:
    """Daily tokens and estimated revenue per model author, from the monthly files."""
    frames, newest = [], None
    for month in _months(today, months):
        path = f"marts/daily_provider_economics/{month}.parquet"
        try:
            frame = read(path, use_cache=use_cache)
        except httpx.HTTPStatusError:
            continue                                # a month the repo has not started
        frames.append(frame[["usage_date", "provider_slug", "provider_name", "total_tokens", "estimated_revenue"]])
        newest = newest or commit(path, use_cache=use_cache)
    if not frames:
        return pd.DataFrame(), None
    data = pd.concat(frames, ignore_index=True)
    data["usage_date"] = pd.to_datetime(data["usage_date"])
    grouped = data.groupby(["usage_date", "provider_slug"], as_index=False).agg(
        provider_name=("provider_name", "first"), tokens=("total_tokens", "sum"), revenue=("estimated_revenue", "sum"))
    return grouped, newest


def ramp(*, use_cache: bool = True) -> tuple[dict[str, pd.DataFrame], dict | None]:
    """Ramp AI Index tables: overall adoption, PEPM spend, sector PEPM, vendor adoption."""
    paths = {
        "adoption": "ramp/ramp_ai_adoption_overall.parquet",
        "pepm": "ramp/ramp_ai_pepm_spend.parquet",
        "pepm_by_dimension": "ramp/ramp_ai_pepm_spend_by_dimension.parquet",
        "vendors": "ramp/ramp_ai_adoption_by_vendor.parquet",
    }
    tables = {key: read(path, use_cache=use_cache) for key, path in paths.items()}
    return tables, commit(paths["pepm"], use_cache=use_cache)


def ramp_tokenomics(*, use_cache: bool = True) -> tuple[dict[str, pd.DataFrame], dict | None]:
    """Ramp Token Spend Management: weekly token volume and spend by model, and daily effective prices."""
    paths = {
        "activity": "ramp/ramp_ai_token_activity.parquet",
        "prices": "ramp/ramp_ai_token_prices.parquet",
    }
    tables = {key: read(path, use_cache=use_cache) for key, path in paths.items()}
    return tables, commit(paths["activity"], use_cache=use_cache)
