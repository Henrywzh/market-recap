"""Small per-call slices of the published artifacts, for the MCP server.

The MCP server (``mcp/``, served by ``functions/mcp.js``) reads the artifacts
through the Pages ASSETS binding, and on the free Workers plan one call gets
about 10 ms of CPU. A ``ticker`` call used to parse about 2.1 MB of JSON, a
``theme`` or ``search`` call about 2-3 MB. So the site build also writes
``artifacts/mcp/``: for each tool call, the artifacts it reads, reduced to the
fields its adapter reads, with the same values.

A slice is ``{"artifacts": {<artifact name>: <reduced artifact or null>}}``.
The adapter asks for an artifact by the name it has always used, and the server
serves the reduced copy when the slice holds that name. Each reduced copy keeps
the source's ``as_of``, so the envelope's ``sources`` and dates do not change.
Three kinds of file are not reduced artifacts:

- ``ticker/index.json`` and ``theme/index.json`` list the names a call can
  resolve (the adapter needs them before it knows which slice to read).
- ``index.json`` records the sha256 of every source artifact the slices were
  cut from, so ``scripts/check_mcp.mjs`` can confirm they match this build.

Nothing here rounds or recomputes: values are copied as they are, so the server
prints the same JSON from a slice as from the full file. Missing sources are
recorded as null, and a slice that is absent makes the server read the full
artifacts instead, as it did before this module existed.

``scripts/check_mcp.mjs`` runs every tool both ways and asserts that the
outputs are identical and that each slice call parses at most 300 KB.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any

SLICE_DIR = "mcp"
SCHEMA = 1

# The same character classes the server accepts for a file name (mcp/context.mjs).
SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

# The fields that mcp/tools/market.mjs and mcp/tools/moves.mjs read from a risk
# tile, a risk section and a MOVES row. Everything else stays out of the slices.
RISK_TILE_KEYS = ("key", "label", "value", "unit", "date", "pct_1y", "threshold", "risk_when", "breach", "core", "error")
RISK_SECTION_KEYS = ("label", "horizon")
UNUSUAL_ROW_KEYS = (
    "ticker", "name", "sector", "z_own", "ret_pct", "own_pct", "z", "market_pct", "sector_pct", "gap_pct",
    "intraday_pct", "volume_ratio", "reported", "tags", "range_factor", "range_reason",
)
SECTOR_HUB_KEYS = ("as_of", "benchmark", "notes", "sectors", "sub_industries")


class _Sources:
    """Reads source artifacts once, and remembers each file's sha256."""

    def __init__(self, root: Path):
        self.root = root
        self.parsed: dict[str, dict | None] = {}
        self.hashes: dict[str, str | None] = {}

    def __call__(self, name: str) -> dict | None:
        if name not in self.parsed:
            path = self.root / f"{name}.json"
            if path.is_file():
                raw = path.read_bytes()
                self.hashes[name] = hashlib.sha256(raw).hexdigest()
                value = json.loads(raw)
                self.parsed[name] = value if isinstance(value, dict) else None
            else:
                self.hashes[name] = None
                self.parsed[name] = None
        return self.parsed[name]


def _keep(source: Any, keys: tuple[str, ...]) -> dict:
    """The listed keys that the source has, with their values unchanged."""
    if not isinstance(source, dict):
        return {}
    return {key: source[key] for key in keys if key in source}


def _slim(data: dict, scalars: tuple[str, ...], lists: dict[str, tuple[str, ...]]) -> dict:
    """An artifact with its scalar fields and each named list cut to the given fields."""
    out = _keep(data, scalars)
    for list_key, fields in lists.items():
        if isinstance(data.get(list_key), list):
            out[list_key] = [_keep(item, fields) for item in data[list_key]]
    return out


def _rows_by_ticker(data: dict | None) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for row in (data or {}).get("rows") or []:
        if isinstance(row, dict) and isinstance(row.get("ticker"), str):
            grouped.setdefault(row["ticker"], []).append(row)
    return grouped


def _event_symbols(folder: Path) -> list[str]:
    """Symbols that have an events file which parses to a JSON object."""
    names = []
    for path in (sorted(folder.glob("*.json")) if folder.is_dir() else []):
        if not SYMBOL.fullmatch(path.stem):
            continue
        try:
            if isinstance(json.loads(path.read_bytes()), dict):
                names.append(path.stem)
        except ValueError:
            continue
    return sorted(names)


def _ticker_slice(symbol: str, valuation, monitor, moves, by_ticker: dict[str, dict[str, list]]) -> dict:
    """What the ticker adapter reads for one symbol, from the three panels."""
    artifacts: dict[str, Any] = {}
    if valuation is not None:
        artifacts["valuation"] = {**_keep(valuation, ("as_of", "note")), "rows": by_ticker["valuation"].get(symbol, [])}
    else:
        artifacts["valuation"] = None
    if monitor is not None:
        artifacts["monitor"] = {**_keep(monitor, ("as_of",)), "rows": by_ticker["monitor"].get(symbol, [])}
    else:
        artifacts["monitor"] = None
    if moves is not None:
        moves_slice: dict[str, Any] = {**_keep(moves, ("as_of", "note", "settings")), "rows": by_ticker["moves"].get(symbol, [])}
        states = moves.get("move_states")
        if isinstance(states, dict) and "rows" in states:
            moves_slice["move_states"] = {"rows": states["rows"]}
        artifacts["moves"] = moves_slice
    else:
        artifacts["moves"] = None
    return {"artifacts": artifacts}


def _theme_slice(group: dict, themes: dict) -> dict:
    """What the theme adapter reads for one group."""
    key = group["key"]
    drivers = []
    for driver in themes.get("drivers") or []:
        if not isinstance(driver, dict) or key not in (driver.get("themes") or []):
            continue
        reduced = dict(driver)
        if isinstance(driver.get("points"), list):
            # The adapter reads only the last point (util.last), so only it is kept.
            reduced["points"] = driver["points"][-1:]
        drivers.append(reduced)
    reduced_themes: dict[str, Any] = {**_keep(themes, ("as_of",)), "groups": [group], "drivers": drivers}
    # themeText reads the cloud guidance only for the cloud board and the semis
    # adata only for the semis board; the other boards never touch either.
    if key == "cloud" and isinstance(themes.get("cloud"), dict):
        reduced_themes["cloud"] = _keep(themes["cloud"], ("guidance",))
    if key == "semis" and isinstance(themes.get("semis"), dict):
        reduced_themes["semis"] = _keep(themes["semis"], ("adata",))
    return {"artifacts": {"themes": reduced_themes}}


def _risk(risk: dict) -> dict:
    sections = []
    for section in risk.get("sections") or []:
        if not isinstance(section, dict):
            continue
        tiles = [_keep(tile, RISK_TILE_KEYS) for tile in section.get("tiles") or [] if isinstance(tile, dict)]
        sections.append({**_keep(section, RISK_SECTION_KEYS), "tiles": tiles})
    return {**_keep(risk, ("as_of", "sentiment")), "sections": sections}


def write(artifacts: Path, out: Path | None = None) -> dict:
    """Write the slices for the artifacts in ``artifacts`` into ``out``.

    ``artifacts`` is the published artifacts directory (``dist/artifacts``); the
    default output is ``artifacts/mcp``. Files are overwritten, never removed.
    Returns what was written, for the build summary.
    """
    out = out or artifacts / SLICE_DIR
    source = _Sources(artifacts)
    written: Counter = Counter()
    total_bytes = 0

    def emit(rel: str, payload: dict, group: str) -> None:
        nonlocal total_bytes
        target = out / f"{rel}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        target.write_text(text, encoding="utf-8")
        total_bytes += len(text.encode("utf-8"))
        written[group] += 1

    manifest = source("manifest")
    valuation, monitor, moves = source("valuation"), source("monitor"), source("moves")

    # --- ticker: one slice per symbol, and the index that resolves a typed symbol.
    by_ticker = {"valuation": _rows_by_ticker(valuation), "monitor": _rows_by_ticker(monitor), "moves": _rows_by_ticker(moves)}
    panel_symbols = sorted({s for grouped in by_ticker.values() for s in grouped})
    event_symbols = _event_symbols(artifacts / "events")
    emit("ticker/index", {"rows": panel_symbols, "events": event_symbols}, "ticker index")
    for symbol in sorted(set(panel_symbols) | set(event_symbols)):
        if SYMBOL.fullmatch(symbol):
            emit(f"ticker/{symbol}", _ticker_slice(symbol, valuation, monitor, moves, by_ticker), "ticker")

    # --- theme: an index of the group keys and labels, then one slice per group.
    themes = source("themes")
    if themes is not None:
        groups = [g for g in themes.get("groups") or [] if isinstance(g, dict)]
        emit("theme/index", {"groups": [_keep(g, ("key", "label")) for g in groups]}, "theme index")
        for group in groups:
            if isinstance(group.get("key"), str) and SYMBOL.fullmatch(group["key"]):
                emit(f"theme/{group['key']}", _theme_slice(group, themes), "theme")

    # --- search: the fields search reads for each kind of item; titles and urls
    # are still built by the one function in mcp/tools/search.mjs.
    search_sources = {
        "valuation": _slim(valuation or {}, ("as_of",), {"rows": ("ticker", "name", "sector")}) if valuation is not None else None,
        "sectors": None, "themes": None, "catalysts": None,
    }
    sectors = source("sectors")
    if sectors is not None:
        search_sources["sectors"] = _slim(sectors, ("as_of",), {"sectors": ("key", "label"), "sub_industries": ("key", "label", "sector")})
    if themes is not None:
        search_sources["themes"] = _slim(themes, ("as_of",), {"groups": ("key", "label", "proxy")})
    catalysts = source("catalysts")
    if catalysts is not None:
        search_sources["catalysts"] = _slim(catalysts, ("as_of",), {"events": ("event_key", "title", "date", "event_type", "symbol")})
    emit("search_index", {"artifacts": search_sources}, "search")

    # --- market_snapshot: its five panels, with the risk and positioning
    # artifacts cut down to the fields the adapter reads.
    overview = source("overview")
    market_state = source("market_state")
    risk = source("risk")
    positioning = source("positioning")
    snapshot: dict[str, Any] = {
        "overview": overview,
        "market_state": market_state,
        "risk": _risk(risk) if risk is not None else None,
        "positioning": _keep(positioning, ("as_of", "index_put_call", "blackout")) if positioning is not None else None,
        "sectors": _keep(sectors, ("as_of", "benchmark", "sectors")) if sectors is not None else None,
    }
    emit("snapshot", {"artifacts": snapshot}, "snapshot")

    # --- unusual_moves: the MOVES rows, cut to the fields its rows show.
    if moves is not None:
        unusual: dict[str, Any] = _keep(moves, ("as_of", "note", "settings", "sector_selloff"))
        if isinstance(moves.get("rows"), list):
            unusual["rows"] = [_keep(row, UNUSUAL_ROW_KEYS) for row in moves["rows"]]
        emit("unusual", {"artifacts": {"moves": unusual}}, "unusual")
    else:
        emit("unusual", {"artifacts": {"moves": None}}, "unusual")

    # --- sector: the hub without its member list (the largest part of it).
    if sectors is not None:
        emit("sector_hub", {"artifacts": {"sectors": _keep(sectors, SECTOR_HUB_KEYS)}}, "sector")

    # --- macro: the card of one kind (cpi, ppi or commodities) per slice; rates
    # reads two small artifacts and has no slice.
    macro = source("macro")
    for kind in ("cpi", "ppi", "commodities"):
        if macro is not None:
            emit(f"macro/{kind}", {"artifacts": {"macro": {**_keep(macro, ("as_of", "note")), **_keep(macro, (kind,))}}}, "macro")

    index = {
        "schema": SCHEMA,
        "as_of": (manifest or {}).get("as_of"),
        "generated_at": (manifest or {}).get("generated_at"),
        "sources": {name: source.hashes[name] for name in sorted(source.hashes)},
        "slices": dict(sorted(written.items())),
    }
    index_text = json.dumps(index, ensure_ascii=False, indent=1)
    (out / "index.json").parent.mkdir(parents=True, exist_ok=True)
    (out / "index.json").write_text(index_text, encoding="utf-8")
    total_bytes += len(index_text.encode("utf-8"))
    return {"dir": str(out), "files": sum(written.values()) + 1, "bytes": total_bytes, "slices": dict(sorted(written.items()))}
