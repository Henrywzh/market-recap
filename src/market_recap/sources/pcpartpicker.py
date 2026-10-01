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
republished. robots.txt allows these pages.
"""

from __future__ import annotations

from datetime import date, timedelta
import re

import numpy as np

from .. import cache
from ..compute import png
from .http import get_bytes, get_text

BASE = "https://uk.pcpartpicker.com/trends/price/{kind}/"
NAMESPACE = "pcpartpicker"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
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
    return cache.fetch_text(NAMESPACE, f"{kind}-page", lambda: get_text(BASE.format(kind=kind), user_agent=USER_AGENT, retries=1),
                            kind="daily_file", suffix=".html", use_cache=use_cache)


def fetch(kind: str, *, use_cache: bool = True) -> tuple[list[dict], list[str]]:
    """Every chart on one trends page, read into a daily height series.

    Returns the series and the charts that could not be read (with why)."""
    charts, failed = [], []
    for item in images(_page(kind, use_cache)):
        name = re.sub(r"[^A-Za-z0-9]+", "-", item["title"]).strip("-")
        try:
            data = cache.fetch_bytes(NAMESPACE, f"{kind}-{name}-{item['image_date']}",
                                     lambda: get_bytes(item["url"], user_agent=USER_AGENT, retries=1),
                                     kind="archive", suffix=".png", use_cache=use_cache)
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


def weekly_index(series: list[tuple[str, float]]) -> dict:
    """The line as an index, first reading = 100, one point a week."""
    if not series:
        return {"dates": [], "values": []}
    base = series[0][1]
    picked = series[::7] + ([series[-1]] if (len(series) - 1) % 7 else [])
    return {"dates": [d for d, _ in picked], "values": [round(100 * h / base, 1) if base else None for _, h in picked]}
