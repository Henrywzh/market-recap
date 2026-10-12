"""Pure helpers for the SECTORS hub: keys, cap-weighted returns and extremes.

A sub-industry's key is its sector's fund, a dash and the initials of its words,
so a key can be read off its label and needs no lookup table. The keys are
deterministic: the caller assigns them in label order, so a weight change never
renames a sub-industry.
"""

from __future__ import annotations

import re

from ..util import clean_float

# Words that do not start a key's initials ("Soft Drinks & Non-alcoholic Beverages").
SKIPPED_WORDS = frozenset({"&", "and", "of"})


def initials(label: str) -> str:
    """Uppercase initials of a label's words, skipping "&", "and" and "of".

    A hyphenated word counts once ("Non-alcoholic" is N), and a token with no
    letter or digit ("-") counts for nothing.
    """
    letters = []
    for word in re.split(r"[\s,]+", label or ""):
        if not word or word.lower() in SKIPPED_WORDS:
            continue
        head = next((ch for ch in word if ch.isalnum()), None)
        if head is not None:
            letters.append(head.upper())
    return "".join(letters) or "SUB"


def sub_key(sector_key: str, label: str, taken) -> str:
    """The key for a sub-industry: sector key, dash, initials; a digit on collision.

    ``taken`` holds the keys already given within the sector. The caller adds the
    returned key to it. The first of two colliding labels keeps the bare key and
    the next gets "2", so the order of assignment (label order) decides.
    """
    base = f"{sector_key}-{initials(label)}"
    key, n = base, 1
    while key in taken:
        n += 1
        key = f"{base}{n}"
    return key


def weighted_returns(members: list[dict], periods) -> dict[str, float | None]:
    """Cap-weighted return per period from members with ``weight`` and ``returns``.

    A member with no return for a period is left out of that period and the
    weights that remain are renormalised. None where no member has a return.
    """
    out: dict[str, float | None] = {}
    for period in periods:
        pairs = []
        for member in members:
            weight = clean_float(member.get("weight"))
            value = clean_float((member.get("returns") or {}).get(period))
            if weight is not None and value is not None:
                pairs.append((weight, value))
        total = sum(weight for weight, _ in pairs)
        out[period] = sum(weight * value for weight, value in pairs) / total if total else None
    return out


def excess(value: float | None, base: float | None) -> float | None:
    """``value`` less ``base`` in percentage points, or None if either is missing."""
    if value is None or base is None:
        return None
    return value - base


def best_and_worst(members: list[dict], period: str) -> tuple[dict | None, dict | None]:
    """(best, worst) as ``{"ticker", "return"}`` over the members with a return.

    Ties break on ticker, so the same data always names the same name.
    """
    ranked = []
    for member in members:
        value = clean_float((member.get("returns") or {}).get(period))
        if value is not None:
            ranked.append((value, member["ticker"]))
    if not ranked:
        return None, None
    ranked.sort()
    worst, best = ranked[0], ranked[-1]
    return ({"ticker": best[1], "return": best[0]}, {"ticker": worst[1], "return": worst[0]})
