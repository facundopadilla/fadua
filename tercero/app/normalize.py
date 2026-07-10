"""Deterministic value parsers for dirty spreadsheet cells.

Every function here is 100% deterministic — no LLM involvement, no
guessing. This module implements the treatments defined in CLAUDE.md's
"Data traps" table (currency parsing, Sí/No booleans, and accent/case
-insensitive option matching).
"""

from __future__ import annotations

import re
import unicodedata

# Spanish "empty" placeholders that must never normalize to a numeric zero.
_EMPTY_CURRENCY_MARKERS = {"-", "--", "", "n/a", "na"}


def fold(text: str) -> str:
    """Lowercase, strip accents, and collapse whitespace.

    Used as the comparison key for accent/case-insensitive matching
    (e.g. "Al Día" vs "Al día").
    """
    if text is None:
        return ""
    # NFD decomposes accented chars into base char + combining mark;
    # stripping category "Mn" (combining marks) removes the accent.
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    lowered = stripped.lower()
    collapsed = re.sub(r"\s+", " ", lowered).strip()
    return collapsed


def currency(raw: str) -> str:
    """Parse a dirty currency cell into a clean numeric string.

    Rules (see CLAUDE.md trap #3 and #2):
    - Strips currency symbol, surrounding whitespace/padding.
    - Removes thousands separators.
    - Tolerates both "dot thousands, comma decimal" (es-AR style,
      e.g. "1.234,56") and "comma thousands, dot decimal" (en-US
      style, e.g. "1,234.56").
    - A disguised-empty marker like " $ -   " normalizes to "" (empty
      string), NEVER to "0". A blank required cell is not a zero.
    - Plain numbers (no symbol) pass through unchanged (after strip).

    es-AR disambiguation rule (when only ONE separator kind is
    present, i.e. all dots or all commas, never mixed): the group
    trailing the LAST occurrence of that separator decides its role.
    - A trailing group of 1-2 digits is treated as the DECIMAL part,
      e.g. "$ 12,50" -> "12.50" (comma-as-decimal) and a single-dot
      case like "1234.56" is decimal for the same reason.
    - A trailing group of 3 digits is treated as a THOUSANDS group
      (the separator is dropped entirely, no decimal point is
      introduced), e.g. "$ 1.500" -> "1500" and "18,500,000" -> "18500000"
      (every group here is 3 digits, so every separator is thousands).
    This mirrors the real ambiguity in es-AR formatted amounts, where
    both "." and "," can mean either role depending on grouping size —
    there is no separator that is unconditionally decimal or
    unconditionally thousands when it appears alone.

    Returns the cleaned numeric string, or "" if the value is a
    disguised-empty marker.
    """
    if raw is None:
        return ""

    text = raw.strip()
    # Strip currency symbol and any surrounding spaces around it.
    text = text.replace("$", "").strip()

    if fold(text) in _EMPTY_CURRENCY_MARKERS:
        return ""

    has_dot = "." in text
    has_comma = "," in text

    if has_dot and has_comma:
        # Whichever separator appears LAST is the decimal separator.
        last_dot = text.rfind(".")
        last_comma = text.rfind(",")
        if last_comma > last_dot:
            # Comma is decimal, dot is thousands: "1.234,56" -> "1234.56"
            text = text.replace(".", "").replace(",", ".")
        else:
            # Dot is decimal, comma is thousands: "1,234.56" -> "1234.56"
            text = text.replace(",", "")
    elif has_comma and not has_dot:
        # Only commas present: treat as thousands separators (the common
        # case in these fixtures, e.g. "18,500,000"), UNLESS the comma
        # looks like a decimal separator (exactly one comma with 1-2
        # digits after it and no other commas).
        comma_count = text.count(",")
        if comma_count == 1:
            decimal_part = text.split(",")[-1]
            if len(decimal_part) in (1, 2) and decimal_part.isdigit():
                text = text.replace(",", ".")
            else:
                text = text.replace(",", "")
        else:
            text = text.replace(",", "")
    elif has_dot and not has_comma:
        # Only dots present: could be thousands ("18.500.000") or a
        # decimal ("1234.56"). Treat a single dot followed by 1-2
        # digits as decimal; otherwise treat all dots as thousands.
        dot_count = text.count(".")
        if dot_count == 1:
            decimal_part = text.split(".")[-1]
            if len(decimal_part) not in (1, 2):
                text = text.replace(".", "")
            # else: leave as-is, it's a decimal number
        else:
            text = text.replace(".", "")

    return text.strip()


def si_no(raw: str) -> bool | None:
    """Parse a Spanish yes/no cell into a boolean.

    "Sí" / "Si" / "sí" (any case, with or without accent) -> True
    "No" / "no" (any case) -> False
    Anything else -> None (unrecognized, caller decides how to treat it)
    """
    folded = fold(raw)
    if folded in {"si", "sí"}:
        return True
    if folded == "no":
        return False
    return None


def match_option(value: str, options: list[str]) -> str | None:
    """Match a raw value against a list of canonical form options.

    Case-insensitive, accent-insensitive, whitespace-collapsed
    comparison. Returns the CANONICAL option string from `options` on
    a match (not the raw input). No fuzzy guessing beyond fold() —
    if no option folds to the same key, returns None.
    """
    if value is None:
        return None
    target = fold(value)
    for option in options:
        if fold(option) == target:
            return option
    return None
