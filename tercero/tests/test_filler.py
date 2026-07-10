"""Tests for app.filler — pure, page-independent contract checks.

Most of filler.py requires a real Playwright Page (locators, ARIA
state, network waits) and is exercised end-to-end by
test_submit_replica.py's browser-marked test. This file covers the
handful of checks that run BEFORE any page interaction and can
therefore be tested without a browser.
"""

from __future__ import annotations

import pytest

from app.errors import ValidationBannerError
from app.filler import fill_checkbox_field
from app.forms_schema import Field


def _checkbox_field() -> Field:
    return Field(
        item_id="444",
        entry_id="entry.444",
        label="Requiere Acción de Cobranza Legal",
        type=4,
        required=False,
        options=[],
    )


class TestFillCheckboxFieldRequiresActualBool:
    """fill_checkbox_field must reject anything that isn't an actual
    bool BEFORE touching the page -- the contract that closes the
    fragile "any non-empty string is truthy" bug this fix targets."""

    @pytest.mark.parametrize("bad_value", ["Sí", "No", "true", "", "1", 1, None])
    def test_non_bool_value_raises_before_touching_the_page(self, bad_value):
        field = _checkbox_field()

        # `page=None` proves the rejection happens BEFORE any locator
        # call -- if the code tried to use `page`, this would raise
        # AttributeError instead of the expected ValidationBannerError.
        with pytest.raises(ValidationBannerError):
            fill_checkbox_field(None, field, bad_value)
