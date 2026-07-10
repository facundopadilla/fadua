"""The three integrity gates.

A record is declared successful only if it clears all three:

1. Completeness — before opening the browser, every required field
   must have a normalized value.
2. Read-back — after filling each field, assert the DOM reflects the
   expected value before moving on (implemented per-field-type inside
   filler.py, since it needs live Playwright locators; this module
   exposes the assertion HELPERS that filler.py calls).
3. Confirmation — after Enviar, assert a real transition to a
   confirmation view (URL contains "formResponse" OR a known
   confirmation phrase is visible). Only exercised in --live mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.forms_schema import Field

_CONFIRMATION_PHRASES = (
    "Se registró tu respuesta",
    "Tu respuesta se ha registrado",
    "Your response has been recorded",
)


def completeness(
    record_values: dict[str, str], page_fields: list["Field"]
) -> list[str]:
    """Return labels of required fields on this page missing a value.

    `record_values` must already be keyed by field label (i.e. the
    caller has resolved the column->field mapping and normalized
    values before calling this). An empty-string value counts as
    missing (this is exactly the disguised-empty-after-normalization
    case, e.g. currency("$ -") -> "").
    """
    missing: list[str] = []
    for pf in page_fields:
        if not pf.required:
            continue
        value = record_values.get(pf.label)
        if value is None or value == "":
            missing.append(pf.label)
    return missing


def assert_text_value(actual: str, expected: str) -> bool:
    """Read-back helper for text fields: DOM input_value() == expected."""
    return actual == expected


def assert_option_rendered(actual_text: str, expected_option: str) -> bool:
    """Read-back helper for dropdowns: rendered text contains the option."""
    return expected_option in actual_text


def assert_aria_checked(aria_checked_value: str | None, expected: bool) -> bool:
    """Read-back helper for radio/checkbox: aria-checked reflects expected state."""
    return aria_checked_value == ("true" if expected else "false")


def confirmation(url: str, visible_text: str) -> bool:
    """True if the page transitioned to a genuine confirmation view.

    Checks the URL for the "formResponse" marker OR the page text for
    one of the known (non-exact) confirmation phrases in Spanish or
    English. Never compares against one exact string, since Google
    varies the exact wording.
    """
    if "formResponse" in url:
        return True
    return any(phrase in visible_text for phrase in _CONFIRMATION_PHRASES)
