"""Load and validate the durable MONITOR observation ledger.

The monitor is the one panel whose useful history is not reproducible from a
daily rebuild.  A local artifact is convenient for development, but a cloud
build must read the last *published* artifact so an evicted CI cache cannot
silently reset the observation window.

This module deliberately only reads state.  Merging today's observations,
rejecting a rollback, and writing the next artifact belong to the monitor
panel/build integration.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import urljoin

from .. import config as dashboard_config
from .http import get_text


SCHEMA_VERSION = 1
MONITOR_FILENAME = "monitor.json"
MANIFEST_FILENAME = "manifest.json"
PUBLISHED_READ_ATTEMPTS = 3
STATE_HTTP_TIMEOUT = 20.0
STATE_HTTP_RETRIES = 1

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_TOP_LEVEL_FIELDS = {
    "schema_version",
    "as_of",
    "tracking_started",
    "universe",
    "settings",
    "rows",
    "notices",
    "note",
}
_UNIVERSE_FIELDS = {"key", "label", "members", "holdings_as_of"}
_ANALYTIC_SETTINGS = (
    "index",
    "drawdown_period",
    "threshold_pct",
    "relative_period",
    "ma_sessions",
    "earnings_days",
)
# Only these settings determine the meaning of the durable observation
# history.  The ledger stores drawdowns, not threshold memberships or any of
# the current evidence columns, so the other settings may change between
# builds without making the old ledger unsafe to reuse.
_HISTORICAL_SETTINGS = ("index", "drawdown_period")
_DERIVED_SETTINGS = ("drawdown_sessions", "relative_sessions")

_ROW_FIELDS = {
    "ticker",
    "name",
    "sector",
    "in_universe",
    "drawdown_pct",
    "price_as_of",
    "history",
    "market_excess_pct",
    "sector_excess_pct",
    "market_benchmark",
    "sector_benchmark",
    "rs_improving",
    "above_ma",
    "pe",
    "pe_percentile",
    "pe_vs_median",
    "fcf_positive",
    "revenue_growth_pct",
    "filed",
    "period_end",
    "earnings_date",
    "earnings_status",
    "estimate_revision",
    "gaps",
}
_LATEST_METRICS = {
    "drawdown_pct",
    "price_as_of",
    "market_excess_pct",
    "sector_excess_pct",
    "market_benchmark",
    "sector_benchmark",
    "rs_improving",
    "above_ma",
    "pe",
    "pe_percentile",
    "pe_vs_median",
    "fcf_positive",
    "revenue_growth_pct",
    "filed",
    "period_end",
    "earnings_date",
    "earnings_status",
    "estimate_revision",
}
_NUMERIC_FIELDS = {
    "market_excess_pct",
    "sector_excess_pct",
    "pe",
    "pe_percentile",
    "pe_vs_median",
    "revenue_growth_pct",
    "estimate_revision",
}
_BOOLEAN_FIELDS = {"rs_improving", "above_ma", "fcf_positive"}
_DATE_FIELDS = {"filed", "period_end", "earnings_date"}


class MonitorStateError(ValueError):
    """A monitor state or published manifest is not safe to consume."""


def _invalid(path: str, detail: str) -> MonitorStateError:
    return MonitorStateError(f"invalid monitor state at {path}: {detail}")


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(path, "expected an object")
    return value


def _require_nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(path, "expected a non-empty string")
    return value


def _optional_string(value: Any, path: str) -> None | str:
    if value is not None and not isinstance(value, str):
        raise _invalid(path, "expected a string or null")
    return value


def _parse_date(value: Any, path: str, *, allow_none: bool = False) -> date | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise _invalid(path, "expected an ISO date YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _invalid(path, "is not a real calendar date") from exc


def _finite_number(value: Any, path: str, *, allow_none: bool = True) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(path, "expected a finite number or null")
    number = float(value)
    if not math.isfinite(number):
        raise _invalid(path, "expected a finite number, not NaN or infinity")
    return number


def _finite_integer(value: Any, path: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(path, f"expected an integer >= {minimum}")
    if value < minimum:
        raise _invalid(path, f"expected an integer >= {minimum}")
    return value


def _drawdown(value: Any, path: str) -> None | float:
    number = _finite_number(value, path)
    if number is not None and not -100.0 <= number <= 0.0:
        raise _invalid(path, "must be null or between -100 and 0 percent")
    return number


def _identity(value: str) -> str:
    return value.casefold()


def _same_setting_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        try:
            return math.isfinite(float(actual)) and math.isfinite(float(expected)) and math.isclose(
                float(actual), float(expected), rel_tol=0.0, abs_tol=1e-12
            )
        except (TypeError, ValueError):
            return False
    return actual == expected


def _effective_settings(raw: Any) -> Mapping[str, Any]:
    settings = _require_mapping(raw, "settings")
    nested = settings.get("config")
    if nested is None:
        return settings
    nested = _require_mapping(nested, "settings.config")
    # Accept both forms used by builders: a flat settings object and an object
    # that keeps the copied monitor config under ``config``.  Derived session
    # counts at the outer level take precedence if both are present.
    merged = dict(nested)
    merged.update({key: value for key, value in settings.items() if key != "config"})
    return merged


def _current_monitor_config() -> Mapping[str, Any] | None:
    """Return the configured analytic monitor settings when available.

    The helper is also useful in older checkouts that predate the monitor
    section, so a missing or unreadable config is not itself a state failure.
    """

    try:
        current = dashboard_config.load_config().get("monitor")
    except Exception:
        return None
    return current if isinstance(current, Mapping) else None


def _validate_settings(raw: Any) -> None:
    settings = _effective_settings(raw)

    for key in (*_ANALYTIC_SETTINGS, *_DERIVED_SETTINGS):
        if key not in settings:
            raise _invalid(f"settings.{key}", "required field is missing")

    _require_nonempty_string(settings["index"], "settings.index")
    drawdown_period = _require_nonempty_string(settings["drawdown_period"], "settings.drawdown_period")
    relative_period = _require_nonempty_string(settings["relative_period"], "settings.relative_period")

    threshold = _finite_number(settings["threshold_pct"], "settings.threshold_pct", allow_none=False)
    if threshold is None or not 0.0 <= threshold <= 100.0:
        raise _invalid("settings.threshold_pct", "must be between 0 and 100 percent")
    _finite_integer(settings["ma_sessions"], "settings.ma_sessions")
    _finite_integer(settings["earnings_days"], "settings.earnings_days", minimum=0)

    # The derived counts are part of the state contract.  Computing the
    # expected values from the shared period table avoids a second hard-coded
    # definition and makes a changed drawdown window incompatible with an old
    # ledger instead of silently mixing the two.  The relative window is
    # checked only against the values recorded in this artifact; it is not a
    # durable-history compatibility gate.
    period_sessions = dashboard_config.PERIOD_TRADING_DAYS
    for period_name, settings_key in (
        (drawdown_period, "drawdown_sessions"),
        (relative_period, "relative_sessions"),
    ):
        if period_name not in period_sessions or period_sessions[period_name] is None:
            raise _invalid(f"settings.{settings_key}", f"unknown or non-fixed period {period_name!r}")
        expected = period_sessions[period_name]
        actual = _finite_integer(settings[settings_key], f"settings.{settings_key}")
        if actual != expected:
            raise _invalid(
                f"settings.{settings_key}",
                f"is {actual}, but {period_name!r} requires {expected} sessions",
            )

    # Only index and the drawdown window define the durable history. Threshold,
    # relative-strength, MA, earnings and URL changes affect current evidence,
    # presentation, or deployment plumbing, so deliberately exclude them from
    # this compatibility comparison.
    configured = _current_monitor_config()
    if configured is not None:
        for key in _HISTORICAL_SETTINGS:
            if key in configured and not _same_setting_value(settings[key], configured[key]):
                raise _invalid(
                    f"settings.{key}",
                    f"does not match the configured monitor value {configured[key]!r}",
                )


def _validate_universe(raw: Any, as_of: date) -> tuple[set[str] | None, int]:
    universe = _require_mapping(raw, "universe")
    for key in _UNIVERSE_FIELDS:
        if key not in universe:
            raise _invalid(f"universe.{key}", "required field is missing")

    _require_nonempty_string(universe["key"], "universe.key")
    _require_nonempty_string(universe["label"], "universe.label")
    members = universe["members"]
    identities: set[str] | None
    if isinstance(members, list):
        identities = set()
        for index, ticker in enumerate(members):
            ticker = _require_nonempty_string(ticker, f"universe.members[{index}]")
            identity = _identity(ticker)
            if identity in identities:
                raise _invalid("universe.members", f"duplicate ticker identity {ticker!r}")
            identities.add(identity)
        member_count = len(identities)
    elif isinstance(members, int) and not isinstance(members, bool) and members >= 0:
        # The current panel writes the member count because the row identities
        # are the durable source of names and symbols.  Keep accepting the
        # list form above for older/prospective producers that serialize the
        # actual member identities in the universe block.
        identities = None
        member_count = members
    else:
        raise _invalid("universe.members", "expected a non-negative member count or ticker list")

    holdings_as_of = _parse_date(universe["holdings_as_of"], "universe.holdings_as_of", allow_none=True)
    if holdings_as_of is not None and holdings_as_of > as_of:
        raise _invalid("universe.holdings_as_of", "cannot be after artifact as_of")
    return identities, member_count


def _validate_history(raw: Any, path: str, tracking_started: date, as_of: date) -> None:
    if not isinstance(raw, list):
        raise _invalid(path, "expected a list of [date, drawdown_pct] observations")

    previous: date | None = None
    for index, observation in enumerate(raw):
        item_path = f"{path}[{index}]"
        if not isinstance(observation, list) or len(observation) != 2:
            raise _invalid(item_path, "expected exactly [date, drawdown_pct]")
        observed = _parse_date(observation[0], f"{item_path}[0]")
        if observed is None:  # for type checkers; _parse_date rejects this form
            raise _invalid(f"{item_path}[0]", "date cannot be null")
        if observed < tracking_started:
            raise _invalid(item_path, "observation predates tracking_started")
        if observed > as_of:
            raise _invalid(item_path, "observation is after artifact as_of")
        if previous is not None and observed <= previous:
            raise _invalid(path, "history dates must be strictly increasing and unique")
        _drawdown(observation[1], f"{item_path}[1]")
        previous = observed


def _validate_scalar(value: Any, path: str) -> None:
    if value is None or isinstance(value, str):
        return
    _finite_number(value, path)


def _validate_row(
    raw: Any,
    index: int,
    member_identities: set[str] | None,
    tracking_started: date,
    as_of: date,
) -> str:
    path = f"rows[{index}]"
    row = _require_mapping(raw, path)
    missing = _ROW_FIELDS - row.keys()
    if missing:
        raise _invalid(path, f"required field(s) missing: {', '.join(sorted(missing))}")

    ticker = _require_nonempty_string(row["ticker"], f"{path}.ticker")
    identity = _identity(ticker)
    _require_nonempty_string(row["name"], f"{path}.name")
    _optional_string(row["sector"], f"{path}.sector")
    if not isinstance(row["in_universe"], bool):
        raise _invalid(f"{path}.in_universe", "expected a boolean")

    if member_identities is not None:
        expected_membership = identity in member_identities
        if row["in_universe"] != expected_membership:
            expected_text = "in" if expected_membership else "outside"
            raise _invalid(
                f"{path}.in_universe",
                f"ticker is {expected_text} the current universe members",
            )

    drawdown = _drawdown(row["drawdown_pct"], f"{path}.drawdown_pct")
    price_as_of = _parse_date(row["price_as_of"], f"{path}.price_as_of", allow_none=True)
    if price_as_of is not None and price_as_of > as_of:
        raise _invalid(f"{path}.price_as_of", "cannot be after artifact as_of")
    _validate_history(row["history"], f"{path}.history", tracking_started, as_of)
    history = row["history"]
    if not history:
        raise _invalid(f"{path}.history", "must contain at least one observation")
    last_date, last_drawdown = history[-1]
    if last_date != as_of.isoformat():
        raise _invalid(f"{path}.history", "last observation date must equal artifact as_of")
    if last_drawdown != drawdown:
        raise _invalid(f"{path}.history", "last drawdown must equal row.drawdown_pct")

    for field in _NUMERIC_FIELDS:
        _finite_number(row[field], f"{path}.{field}")
    for field in _BOOLEAN_FIELDS:
        value = row[field]
        if value is not None and not isinstance(value, bool):
            raise _invalid(f"{path}.{field}", "expected a boolean or null")
    for field in _DATE_FIELDS:
        _parse_date(row[field], f"{path}.{field}", allow_none=True)
    _optional_string(row["earnings_status"], f"{path}.earnings_status")
    _validate_scalar(row["market_benchmark"], f"{path}.market_benchmark")
    _validate_scalar(row["sector_benchmark"], f"{path}.sector_benchmark")

    gaps = row["gaps"]
    if not isinstance(gaps, list) or any(not isinstance(gap, str) for gap in gaps):
        raise _invalid(f"{path}.gaps", "expected a list of strings")

    membership = row.get("membership", "index" if row["in_universe"] else "removed")
    if membership not in _MEMBERSHIPS or (membership == "index") != row["in_universe"]:
        raise _invalid(f"{path}.membership", "must be index (in universe), watchlist or removed")
    _validate_durable(row, path, tracking_started, as_of)

    # An exited symbol remains in the ledger for its metadata and history, but
    # its current readings must not be carried forward as if it were still in
    # the universe. Watchlist names are explicit non-members and are measured.
    if membership == "removed":
        for field in sorted(_LATEST_METRICS):
            if row[field] is not None:
                raise _invalid(f"{path}.{field}", "removed symbols must have null latest metrics")

    return identity


_MEMBERSHIPS = {"index", "watchlist", "removed"}
_PRICE_STATES = {"weak", "stabilising", None}
_EVIDENCE_STATES = {"steady", "deteriorating", "unknown", None}


def _validate_durable(row: Mapping[str, Any], path: str, tracking_started: date, as_of: date) -> None:
    """The fields carried between builds besides history: first_seen,
    state_log and reported. Absent is allowed (ledgers written before them)."""

    first = row.get("first_seen")
    if first is not None:
        first = _require_mapping(first, f"{path}.first_seen")
        seen = _parse_date(first.get("date"), f"{path}.first_seen.date")
        if seen is not None and not tracking_started <= seen <= as_of:
            raise _invalid(f"{path}.first_seen.date", "must lie within the tracked window")
        reasons = first.get("reasons")
        if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
            raise _invalid(f"{path}.first_seen.reasons", "expected a list of strings")
        if not isinstance(first.get("baseline"), bool):
            raise _invalid(f"{path}.first_seen.baseline", "expected a boolean")

    log = row.get("state_log", [])
    if not isinstance(log, list):
        raise _invalid(f"{path}.state_log", "expected a list")
    previous: date | None = None
    for index, entry in enumerate(log):
        item_path = f"{path}.state_log[{index}]"
        if not isinstance(entry, list) or len(entry) != 4:
            raise _invalid(item_path, "expected [date, candidate, price_state, evidence_state]")
        day = _parse_date(entry[0], f"{item_path}[0]")
        if day is None or day > as_of or (previous is not None and day <= previous):
            raise _invalid(item_path, "dates must increase and not pass as_of")
        candidate, price, evidence = entry[1:]
        if not (candidate is None or isinstance(candidate, bool)) \
                or not isinstance(price, (str, type(None))) or price not in _PRICE_STATES \
                or not isinstance(evidence, (str, type(None))) or evidence not in _EVIDENCE_STATES:
            raise _invalid(item_path, f"unexpected state values {entry[1:]!r}")
        previous = day

    reported = row.get("reported")
    if reported is not None:
        reported = _require_mapping(reported, f"{path}.reported")
        day = _parse_date(reported.get("date"), f"{path}.reported.date")
        if day is not None and day > as_of:
            raise _invalid(f"{path}.reported.date", "cannot be after artifact as_of")
        for key in ("eps", "eps_forecast", "surprise_pct", "return_1d"):
            _finite_number(reported.get(key), f"{path}.reported.{key}")


def validate_previous(payload: Any) -> dict[str, Any]:
    """Validate and return a MONITOR v1 artifact without mutating it.

    ``ValueError`` is the public failure contract.  ``MonitorStateError`` is a
    descriptive subclass used internally and by callers that want to be more
    specific.  Unknown extra fields are retained for forward compatibility;
    required v1 fields and their safety invariants are checked here.
    """

    state = _require_mapping(payload, "root")
    missing = _TOP_LEVEL_FIELDS - state.keys()
    if missing:
        raise _invalid("root", f"required field(s) missing: {', '.join(sorted(missing))}")

    schema_version = state["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise _invalid("schema_version", "expected integer 1")
    if schema_version != SCHEMA_VERSION:
        raise _invalid("schema_version", f"unsupported version {schema_version}; expected {SCHEMA_VERSION}")

    as_of = _parse_date(state["as_of"], "as_of")
    tracking_started = _parse_date(state["tracking_started"], "tracking_started")
    if as_of is None or tracking_started is None:  # for type checkers
        raise _invalid("root", "as_of and tracking_started are required dates")
    if tracking_started > as_of:
        raise _invalid("tracking_started", "cannot be after as_of")

    _validate_settings(state["settings"])
    member_identities, member_count = _validate_universe(state["universe"], as_of)

    rows = state["rows"]
    if not isinstance(rows, list):
        raise _invalid("rows", "expected a list")
    row_identities: set[str] = set()
    for index, row in enumerate(rows):
        identity = _validate_row(row, index, member_identities, tracking_started, as_of)
        if identity in row_identities:
            raise _invalid(f"rows[{index}].ticker", "duplicate ticker identity")
        row_identities.add(identity)

    if member_identities is not None and not member_identities.issubset(row_identities):
        missing_members = sorted(member_identities - row_identities)
        raise _invalid("rows", f"current universe member(s) have no row: {', '.join(missing_members)}")

    current_rows = sum(1 for row in rows if isinstance(row, Mapping) and row.get("in_universe") is True)
    if current_rows != member_count:
        raise _invalid(
            "universe.members",
            f"declares {member_count} current members, but rows contain {current_rows}",
        )

    notices = state["notices"]
    if not isinstance(notices, list) or any(not isinstance(notice, str) for notice in notices):
        raise _invalid("notices", "expected a list of strings")
    _optional_string(state["note"], "note")
    if "generated_at" in state:
        _require_nonempty_string(state["generated_at"], "generated_at")
    return state if isinstance(state, dict) else dict(state)


def _decode_json(text: str, description: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise MonitorStateError(f"{description} did not return text")
    stripped = text.lstrip("\ufeff \t\r\n")
    if not stripped:
        raise MonitorStateError(f"{description} is empty, not absent")
    if stripped.lower().startswith("<!doctype html") or stripped.lower().startswith("<html"):
        raise MonitorStateError(
            f"{description} returned HTML instead of JSON; refusing SPA fallback as monitor absence"
        )
    try:
        value = json.loads(stripped)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MonitorStateError(f"{description} is not valid JSON") from exc
    return dict(_require_mapping(value, description))


def _read_local(local_path: Path) -> dict[str, Any] | None:
    path = Path(local_path)
    candidates: list[Path]
    if path.exists() and path.is_file():
        candidates = [path]
    elif path.name == MONITOR_FILENAME or path.suffix.lower() == ".json":
        # The build passes the not-yet-existing artifact file itself.
        candidates = [path]
    else:
        candidates = [path / MONITOR_FILENAME, path / "artifacts" / MONITOR_FILENAME]

    selected = next((candidate for candidate in candidates if candidate.is_file()), None)
    if selected is None:
        return None
    text = selected.read_text(encoding="utf-8")
    return validate_previous(_decode_json(text, str(selected)))


def _published_url(base_url: str, filename: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("published_base_url must be a non-empty URL")
    return urljoin(base_url.rstrip("/") + "/", f"artifacts/{filename}")


def _manifest_info(manifest: Any) -> tuple[str, bool, str | None, tuple[str, str | None]]:
    """The manifest's session, whether it lists MONITOR, its build stamp, and
    the (as_of, generated_at) the published monitor.json must carry.

    Those match the manifest's own, except when a build carried the previous
    ledger forward (``monitor_carried``): the ledger then keeps its own dates.
    """
    value = _require_mapping(manifest, "published manifest")
    as_of = _parse_date(value.get("as_of"), "published manifest.as_of")
    panels = value.get("panels")
    if not isinstance(panels, list) or any(not isinstance(panel, str) for panel in panels):
        raise _invalid("published manifest.panels", "expected a list of panel names")

    skipped = value.get("skipped_panels", [])
    if skipped is None:
        skipped = []
    if not isinstance(skipped, list) or any(not isinstance(panel, str) for panel in skipped):
        raise _invalid("published manifest.skipped_panels", "expected a list of panel names")

    errors = value.get("errors", {})
    if errors is None:
        errors = {}
    if not isinstance(errors, Mapping):
        raise _invalid("published manifest.errors", "expected an object")

    marker_present = "monitor_schema_version" in value
    if marker_present:
        marker = value["monitor_schema_version"]
        if isinstance(marker, bool) or not isinstance(marker, int) or marker != SCHEMA_VERSION:
            raise _invalid(
                "published manifest.monitor_schema_version",
                f"unsupported version {marker!r}; expected {SCHEMA_VERSION}",
            )

    has_monitor = "monitor" in panels
    monitor_failed = "monitor" in skipped or "monitor" in errors
    if monitor_failed or (marker_present and not has_monitor):
        detail = "monitor is missing from panels" if not has_monitor else "monitor is both published and skipped/errored"
        raise _invalid("published manifest", detail)

    generated_at = value.get("generated_at")
    if generated_at is not None:
        _require_nonempty_string(generated_at, "published manifest.generated_at")
    if as_of is None:  # for type checkers
        raise _invalid("published manifest.as_of", "required date is missing")

    expected: tuple[str, str | None] = (as_of.isoformat(), generated_at)
    # A partial refresh that did not rebuild MONITOR republishes the previous
    # build's monitor.json with that build's stamp (scripts/merge_manifest.py).
    # Manifests merged before ``monitor_generated_at`` existed name it only as
    # the partial refresh's previous build.
    partial = value.get("partial_refresh") if isinstance(value.get("partial_refresh"), Mapping) else None
    kept_stamp = value.get("monitor_generated_at")
    if kept_stamp is None and partial and "monitor" not in (partial.get("rebuilt") or []):
        kept_stamp = partial.get("previous_generated_at")
    if kept_stamp is not None:
        _require_nonempty_string(kept_stamp, "published manifest.monitor_generated_at")
        expected = (as_of.isoformat(), kept_stamp)
    carried = value.get("monitor_carried")
    if carried is not None:
        carried = _require_mapping(carried, "published manifest.monitor_carried")
        if not has_monitor:
            raise _invalid("published manifest.monitor_carried", "carries a monitor the manifest does not list")
        carried_as_of = _parse_date(carried.get("as_of"), "published manifest.monitor_carried.as_of")
        if carried_as_of is None or carried_as_of > as_of:
            raise _invalid("published manifest.monitor_carried.as_of", "cannot be after the manifest as_of")
        carried_generated = carried.get("generated_at")
        if carried_generated is not None:
            _require_nonempty_string(carried_generated, "published manifest.monitor_carried.generated_at")
        expected = (carried_as_of.isoformat(), carried_generated)
    return as_of.isoformat(), has_monitor, generated_at, expected


def _read_consistent(base_url: str, *, validate: bool) -> tuple[dict[str, Any], str, dict[str, Any]] | None:
    """The published monitor artifact, read between two identical manifests.

    Returns (state, raw text, manifest), or None for a legacy manifest that
    predates MONITOR. ``validate=False`` returns the artifact as published,
    parsed but not checked against this code's schema -- what carrying it
    forward needs, since a ledger this code no longer accepts must still not
    be lost.
    """
    manifest_url = _published_url(base_url, MANIFEST_FILENAME)
    monitor_url = _published_url(base_url, MONITOR_FILENAME)
    last_mismatch: str | None = None

    for _attempt in range(PUBLISHED_READ_ATTEMPTS):
        # The first manifest tells us whether this is a legacy deployment that
        # predates MONITOR.  Only an unmarked missing panel is an explicit
        # bootstrap; new-build markers and partial-build indicators are
        # rejected by _manifest_info.
        first_manifest = _decode_json(
            get_text(manifest_url, timeout=STATE_HTTP_TIMEOUT, retries=STATE_HTTP_RETRIES),
            manifest_url,
        )
        first_as_of, first_has_monitor, first_generated_at, expected = _manifest_info(first_manifest)
        if not first_has_monitor:
            return None

        # A panel advertised by the manifest is authoritative.  Any fetch or
        # validation failure is allowed to escape; it must never reset state.
        text = get_text(monitor_url, timeout=STATE_HTTP_TIMEOUT, retries=STATE_HTTP_RETRIES)
        state = _decode_json(text, monitor_url)
        if validate:
            state = validate_previous(state)
        observed = (state.get("as_of"), state.get("generated_at"))

        # Re-read the manifest after the artifact.  A Pages deploy can expose
        # files from two versions briefly; accepting that pair would either
        # discard observations or apply a state to the wrong session.
        second_manifest = _decode_json(
            get_text(manifest_url, timeout=STATE_HTTP_TIMEOUT, retries=STATE_HTTP_RETRIES),
            manifest_url,
        )
        second_as_of, second_has_monitor, second_generated_at, _ = _manifest_info(second_manifest)
        if (
            first_as_of == second_as_of
            and first_generated_at == second_generated_at
            and second_has_monitor
            and observed == expected
        ):
            return state, text, first_manifest

        last_mismatch = (
            f"manifest as_of {first_as_of!r} then {second_as_of!r}, generated_at "
            f"{first_generated_at!r} then {second_generated_at!r}; monitor expected "
            f"as_of/generated_at {expected!r}, found {observed!r}"
        )

    raise MonitorStateError(
        "published monitor state raced with a deployment after "
        f"{PUBLISHED_READ_ATTEMPTS} attempts ({last_mismatch or 'unknown mismatch'})"
    )


def _read_published(base_url: str) -> dict[str, Any] | None:
    read = _read_consistent(base_url, validate=True)
    return read[0] if read is not None else None


def carry_published(base_url: str, *, today: str, reason: str) -> tuple[str, dict[str, Any]]:
    """The live monitor artifact, verbatim, for a build that could not make one.

    Returns the text to publish unchanged and the manifest's
    ``monitor_carried`` record. The ledger is not re-validated: when this
    code rejects the published ledger, carrying it keeps every observation
    while the rest of the site still updates; the build is still reported as
    failed. Raises when the live artifact cannot be read consistently -- a
    build that can neither make nor carry the ledger must not publish.
    """
    read = _read_consistent(base_url, validate=False)
    if read is None:
        raise MonitorStateError("the published manifest lists no monitor to carry forward")
    state, text, manifest = read
    previous = manifest.get("monitor_carried") or {}
    record = {
        "as_of": state.get("as_of"),
        "generated_at": state.get("generated_at"),
        # The first session the ledger missed, kept across consecutive carries.
        "since": previous.get("since") or today,
        "reason": reason,
    }
    return text, record


def load_previous(*, local_path: Path, published_base_url: str | None = None) -> dict[str, Any] | None:
    """Load the previous validated monitor artifact.

    With ``published_base_url`` set, the deployed manifest and artifact are
    authoritative and the local file is ignored.  Only a legacy, unmarked
    manifest that does not list ``monitor`` is an explicit first-run bootstrap
    and returns ``None``; all other remote failures raise so the caller cannot
    silently reset the ledger.  Local absence returns ``None`` for the same
    first-run behavior.
    """

    if published_base_url is not None:
        return _read_published(published_base_url)
    return _read_local(local_path)
