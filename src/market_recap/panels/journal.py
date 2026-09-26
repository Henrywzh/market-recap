"""JOURNAL: the decision log (config/journal.toml) reviewed against outcomes.

Reads the log, the members' and the index's closes, and the anchor's
exposure history (from this session's anchor artifact) for overrides. See
compute.journal for how each decision is judged.
"""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import tomllib

import pandas as pd

from ..compute import journal as J
from ..config import ARTIFACT_DIR, REPO_ROOT
from ..sources import yahoo

JOURNAL_PATH = REPO_ROOT / "config" / "journal.toml"


def journal_path() -> Path:
    """The log. ``MARKET_RECAP_JOURNAL`` points a local preview at another
    file (e.g. the example); the published build reads config/journal.toml."""
    override = os.environ.get("MARKET_RECAP_JOURNAL")
    return Path(override) if override else JOURNAL_PATH


def _anchor_exposure(as_of: str) -> pd.Series:
    try:
        anchor = json.loads((ARTIFACT_DIR / "anchor.json").read_text())
    except (OSError, ValueError):
        return pd.Series(dtype=float)
    if anchor.get("as_of") != as_of:
        return pd.Series(dtype=float)
    h = anchor["history"]
    return pd.Series(h["exposure"], index=pd.to_datetime(h["dates"]), dtype=float)


def build(ctx) -> dict:
    settings = ctx.config.get("journal", {})
    as_of = date.fromisoformat(ctx.as_of)
    path = journal_path()
    raw = tomllib.loads(path.read_text()) if path.exists() else {}
    entries = list(raw.get("decision") or [])
    problems = [p for i, e in enumerate(entries) for p in J.validate(e, i)]
    valid = [e for i, e in enumerate(entries) if not J.validate(e, i)]

    index_close = ctx.index_closes[ctx.primary.symbol] if ctx.primary.symbol in ctx.index_closes.columns else pd.Series(dtype=float)
    anchor = _anchor_exposure(ctx.as_of)
    horizon = int(settings.get("default_horizon_days", 60))
    tickers = sorted({str(e["ticker"]).upper() for e in valid if e["action"] in J.NAME_ACTIONS})
    closes = ctx.closes
    missing = [t for t in tickers if t not in closes.columns]
    if missing:
        extra = yahoo.fetch_closes(missing, period="2y")
        closes = pd.concat([closes, extra.loc[:, ~extra.columns.isin(closes.columns)]], axis=1) if not extra.empty else closes

    reviews = []
    for e in sorted(valid, key=lambda e: str(e["date"]), reverse=True):
        action = e["action"]
        ticker = str(e.get("ticker") or J.MARKET).upper()
        if action == "override":
            review = J.review_override(e, index_close, anchor, as_of, horizon)
        else:
            series = closes[ticker] if ticker in closes.columns else pd.Series(dtype=float)
            review = J.review_name(e, series, index_close, as_of, horizon)
        reviews.append({
            "date": str(e["date"]), "ticker": ticker, "action": action, "reason": e.get("reason"),
            "checkpoints": e.get("checkpoints") or [], "review": review,
        })
    return {
        "as_of": ctx.as_of,
        "source": str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else path.name,
        "example": path != JOURNAL_PATH,
        "decisions": reviews,
        "summary": J.summary(reviews),
        "open_checkpoints": J.checkpoints(valid, as_of),
        "problems": problems,
        "anchor_available": not anchor.empty,
        "default_horizon_days": horizon,
    }
