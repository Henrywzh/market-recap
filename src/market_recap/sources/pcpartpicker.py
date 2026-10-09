"""PCPartPicker's UK price trends for memory kits and CPUs.

PCPartPicker publishes, per product group, an 18-month chart of the average
retail price across UK sellers, redrawn daily. The page carries no numbers,
only the chart images, so the average-price line (the black line) is read
from each image's pixels:

- The plot box and gridlines sit at fixed positions (checked on every image:
  a chart whose gridlines moved is rejected, not guessed at).
- The price axis starts at zero at the bottom gridline, so the line's height
  above it is proportional to price. The scale (pounds per gridline) is in
  the axis labels, which are not read; only ratios are reported -- percent
  changes and an index -- and they need no scale.
- Dates come from the month gridlines: the last one is the first day of the
  image's month (the file name carries the image date).

Resolution: 400 pixels span the axis, so a kit at a tenth of the axis height
reads to about +/-2.5%. The site asks for use by reference; only the derived
changes are kept, with a link to the page, and the images are not
republished. robots.txt allows these pages. Requests carry this project's own User-Agent: the
browser one this module once sent was never needed.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import re
import statistics

import numpy as np

from .. import cache
from ..compute import png
from ..config import REPO_ROOT
from .http import get_bytes, get_text

BASE = "https://uk.pcpartpicker.com/trends/price/{kind}/"
NAMESPACE = "pcpartpicker"
# The plot box every chart shares, in pixels.
LEFT, RIGHT, TOP, ZERO = 55, 1149, 27, 427
GRID_ROWS = [27, 94, 161, 227, 294, 361, 427]
GRID = (150, 150, 150)
DARK = 40
PX_PER_MONTH = 60.9          # 2 px a day
_IMAGE = re.compile(r'src:\s*"(//cdna[^"]+?/(\d{4})\.(\d{2})\.(\d{2})\.[^"]+\.png)",\s*thumb:[^,]+,\s*heading:[^,]+,\s*title:\s*"([^"]+)"')


class ChartLayoutChanged(ValueError):
    """The image's gridlines are not where every chart so far had them."""


def images(html: str) -> list[dict]:
    """(title, image url, image date) for every chart on a trends page."""
    out = []
    for src, y, m, d, title in _IMAGE.findall(html):
        out.append({"title": title.encode().decode("unicode_escape"), "url": "https:" + src,
                    "image_date": date(int(y), int(m), int(d)).isoformat()})
    return out


def _month_start(day: date, back: int) -> date:
    month = day.month - back
    year = day.year + (month - 1) // 12
    return date(year, (month - 1) % 12 + 1, 1)


def read_line(pixels: np.ndarray, image_date: date) -> list[tuple[str, float]]:
    """(date, height above zero in pixels) along the average-price line."""
    grid = (pixels == GRID).all(axis=2)
    rows = [y for y in range(pixels.shape[0]) if grid[y, LEFT:RIGHT].sum() > 500]
    if rows != GRID_ROWS:
        raise ChartLayoutChanged(f"gridline rows {rows}")
    columns = [x for x in range(LEFT + 1, RIGHT) if grid[TOP:ZERO, x].sum() > 200]
    if len(columns) < 6:
        raise ChartLayoutChanged(f"{len(columns)} month gridlines")
    last, first = columns[-1], columns[0]
    months = round((last - first) / PX_PER_MONTH)
    end_day, start_day = _month_start(image_date, 0), _month_start(image_date, months)
    per_px = (end_day - start_day).days / (last - first)
    dark = pixels[TOP:ZERO + 1].max(axis=2) < DARK
    out = []
    for x in range(LEFT + 1, RIGHT):
        ys = np.flatnonzero(dark[:, x])
        if ys.size == 0 or ys.size > 30:          # nothing drawn, or a vertical rule
            continue
        height = ZERO - (TOP + float(np.median(ys)))
        day = start_day + timedelta(days=round((x - first) * per_px))
        if day <= image_date:
            out.append((day.isoformat(), height))
    # One reading per day: the line is two pixels a day.
    daily: dict[str, list[float]] = {}
    for day, height in out:
        daily.setdefault(day, []).append(height)
    return [(day, float(np.mean(v))) for day, v in sorted(daily.items())]


def _page(kind: str, use_cache: bool) -> str:
    if not use_cache:
        # An unattended refresh must report a failed fetch, rather than stamp
        # an old cached page with a new fetched_at timestamp.
        return get_text(BASE.format(kind=kind), retries=1)
    return cache.fetch_text(NAMESPACE, f"{kind}-page", lambda: get_text(BASE.format(kind=kind), retries=1),
                            kind="daily_file", suffix=".html", use_cache=use_cache)


def fetch(kind: str, *, use_cache: bool = True) -> tuple[list[dict], list[str]]:
    """Every chart on one trends page, read into a daily height series.

    Returns the series and the charts that could not be read (with why)."""
    charts, failed = [], []
    for item in images(_page(kind, use_cache)):
        name = re.sub(r"[^A-Za-z0-9]+", "-", item["title"]).strip("-")
        try:
            data = (cache.fetch_bytes(NAMESPACE, f"{kind}-{name}-{item['image_date']}",
                                      lambda: get_bytes(item["url"], retries=1),
                                      kind="archive", suffix=".png")
                    if use_cache else get_bytes(item["url"], retries=1))
            series = read_line(png.decode(data), date.fromisoformat(item["image_date"]))
        except Exception as exc:  # noqa: BLE001 - one unreadable chart must not drop the rest
            failed.append(f"{item['title']}: {str(exc)[:120]}")
            continue
        charts.append({**item, "series": series})
    return charts, failed


def summary(series: list[tuple[str, float]], image_date: date) -> dict:
    """Percent changes over 1/3/6/12 months and since the low, from heights."""
    if not series:
        return {}
    by_day = dict(series)
    days = sorted(by_day)
    last_day, last = days[-1], by_day[days[-1]]

    def at(back_days: int) -> float | None:
        target = (image_date - timedelta(days=back_days)).isoformat()
        before = [d for d in days if d <= target]
        return by_day[before[-1]] if before and (date.fromisoformat(target) - date.fromisoformat(before[-1])).days <= 7 else None

    out = {"as_of": last_day}
    for label, back in (("1m", 30), ("3m", 91), ("6m", 182), ("12m", 365)):
        base = at(back)
        out[f"chg_{label}"] = round(100 * (last / base - 1), 1) if base and base > 3 else None
    low_day = min(days, key=lambda d: by_day[d])
    out["from_low"] = round(100 * (last / by_day[low_day] - 1), 1) if by_day[low_day] > 3 else None
    out["low_date"] = low_day
    return out


def weekly_index(series: list[tuple[str, float]], dates: list[str] | None = None) -> dict:
    """The line as an index, first reading = 100, one point a week."""
    if not series:
        return {"dates": [], "values": []}
    series = sorted(series)
    base = series[0][1]
    if dates is None:
        first, last = date.fromisoformat(series[0][0]), date.fromisoformat(series[-1][0])
        day = first + timedelta(days=(-first.weekday()) % 7)
        dates = []
        while day <= last:
            dates.append(day.isoformat())
            day += timedelta(days=7)
        if not dates or dates[-1] != last.isoformat():
            dates.append(last.isoformat())
    values = []
    by_day = dict(series)
    for day in dates:
        current = by_day.get(day)
        values.append(round(100 * current / base, 1) if current is not None and base > 3 else None)
    return {"dates": dates, "values": values}


FEED_PATH = REPO_ROOT / "data" / "feeds" / "pcpartpicker.json"
SCHEMA = 1
STALE_DAYS = 4
SKIPPED = (
    "not fetched by the cloud build: PCPartPicker refuses cloud servers (HTTP 403), "
    "and no home-connection snapshot is in data/feeds/pcpartpicker.json. "
    "Its bot protection is not worked around."
)
_FAMILIES = ("DDR5", "DDR4", "AMD", "Intel")


def family(title: str) -> str:
    return next((key for key in _FAMILIES if title.startswith(key)), "other")


def _aggregate(kind: str, charts: list[dict]) -> dict:
    """Charts reduced to ratios on shared calendar dates; no image in the feed."""
    rows = []
    charts = [chart for chart in charts if chart["series"]]
    observed = [day for chart in charts for day, _ in chart["series"]]
    dates = weekly_index([(day, 100.0) for day in sorted(set(observed))])["dates"]
    for chart in charts:
        day = date.fromisoformat(chart["image_date"])
        rows.append({"title": chart["title"], "family": family(chart["title"]), "image_date": chart["image_date"],
                     **summary(chart["series"], day), "index": weekly_index(chart["series"], dates)})
    families = {}
    for name in sorted({row["family"] for row in rows}):
        members = [row for row in rows if row["family"] == name]
        agg = {}
        for key in ("chg_1m", "chg_3m", "chg_6m", "chg_12m"):
            vals = [row[key] for row in members if row.get(key) is not None]
            agg[key] = round(statistics.median(vals), 1) if vals else None
        series = []
        for i in range(len(dates)):
            vals = [member["index"]["values"][i] for member in members
                    if i < len(member["index"]["values"]) and member["index"]["values"][i] is not None]
            series.append(round(statistics.median(vals), 1) if vals else None)
        families[name] = {**agg, "count": len(members), "index": {"dates": dates, "values": series}}
    return {"rows": rows, "families": families, "page": BASE.format(kind=kind)}


def snapshot(*, use_cache: bool = True) -> dict:
    """Both trend pages, as ratios only."""
    from ..util import utc_now_iso
    out: dict = {"schema": SCHEMA, "fetched_at": utc_now_iso(), "failed": []}
    for kind in ("memory", "cpu"):
        charts, failed = fetch(kind, use_cache=use_cache)
        out["failed"].extend(failed)
        out[kind] = _aggregate(kind, charts)
    return out


def write_feed(payload: dict, path: Path | None = None) -> Path:
    path = path or FEED_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({
        "schema": SCHEMA,
        "fetched_at": payload.get("fetched_at"),
        "failed": payload.get("failed") or [],
        "memory": payload.get("memory") or {},
        "cpu": payload.get("cpu") or {},
    }, indent=2, sort_keys=True)
    temporary = path.with_suffix(".json.part")
    temporary.write_text(body + chr(10), encoding="utf-8")
    temporary.replace(path)
    return path


def _chart_dates(payload: dict) -> list[str]:
    found = []
    for kind in ("memory", "cpu"):
        rows = (payload.get(kind) or {}).get("rows") or []
        dates = [row.get("image_date") for row in rows if row.get("image_date")]
        if dates:
            found.extend(dates)
    return found


def load_feed(as_of: date, path: Path | None = None) -> dict:
    """The committed snapshot. Missing means the cloud build has nothing to show.
    A file that is present but unreadable is an error, not an empty card."""
    path = path or FEED_PATH
    if not path.exists():
        return {"skipped": SKIPPED}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"PCPartPicker feed {path} is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("PCPartPicker feed must be an object")
    if payload.get("schema") != SCHEMA:
        raise RuntimeError(f"PCPartPicker feed schema {payload.get('schema')!r}")
    for kind in ("memory", "cpu"):
        section = payload.get(kind)
        if not isinstance(section, dict) or not isinstance(section.get("rows"), list) or not section["rows"]:
            raise RuntimeError(f"PCPartPicker feed has no {kind} charts")
        if not isinstance(section.get("families"), dict):
            raise RuntimeError(f"PCPartPicker feed has invalid {kind} families")
        for row in section["rows"]:
            try:
                date.fromisoformat(row["image_date"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"PCPartPicker feed has invalid {kind} chart date") from exc
    dates = _chart_dates(payload)
    if not dates:
        raise RuntimeError("PCPartPicker feed has no chart date")
    out = {**payload, "from_feed": True}
    oldest = min(dates)
    age = (as_of - date.fromisoformat(oldest)).days
    if age > STALE_DAYS:
        out["stale"] = f"last chart is {oldest}, {age} days before this build"
    return out
