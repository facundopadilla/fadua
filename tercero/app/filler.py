"""Playwright-driven form filling. The ONLY module that touches the browser.

Selector strategy (CLAUDE.md "Selector rules" — never select by class,
Google Forms uses obfuscated CSS classes):

- Question container: `[data-params*="[<item_id>,"]`, with a role
  qualifier fallback, then falls back further to accessible-label
  matching.
- Text (type 0): fill + input_value() read-back.
- Radio (type 2): click by accessible name + aria-checked read-back.
- Dropdown (type 3): ARIA listbox, NOT a <select> — click to open,
  click the option (which may render in a page-level popup), verify
  rendered text.
- Checkbox (type 4): click only when the boolean is True; verify
  aria-checked; False never touches the control.

Page loop drives BOTH forms (multi-page Form 1, single-page Form 2)
via the same generic `schema.pages` iteration — the structure is read
from data, never hardcoded per form.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from app import validator
from app.errors import NavigationError, OptionMatchFailedError, ValidationBannerError
from app.normalize import fold

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from app.forms_schema import Field, FormSchema

_ALLOWED_URL_PREFIXES = ("https://docs.google.com/", "https://forms.gle/")

_HUMAN_PACING_MIN_MS = 100
_HUMAN_PACING_MAX_MS = 300


def _assert_allowed_domain(page: "Page", allowed_prefixes: tuple[str, ...]) -> None:
    """Abort with NavigationError if the page navigated off the allowlist."""
    url = page.url
    if not any(url.startswith(prefix) for prefix in allowed_prefixes):
        raise NavigationError(f"Navigated outside the allowed domain: {url}")


def _human_pause(page: "Page") -> None:
    """Small jittered pause between field interactions."""
    page.wait_for_timeout(random.randint(_HUMAN_PACING_MIN_MS, _HUMAN_PACING_MAX_MS))


def locate_container(page: "Page", field: "Field"):
    """Locate the question container for a field.

    Primary: `[data-params*="[<item_id>,"]` — the element carrying
    `data-params` is a DIRECT MATCH on its own (verified against the
    live DOM: `role="listitem"` lives on an OUTER wrapper div, while
    `data-params` lives on a DIFFERENT, nested descendant; the two
    attributes never co-occur on the same element, so combining them
    into one compound CSS selector like
    `div[role="listitem"][data-params*=...]` can never match anything).
    The data-params element alone is sufficient to scope
    `get_by_role("textbox"/"radio"/"listbox"/"checkbox")` calls.
    Fallback: accessible-label match on a heading/aria-label, compared
    with normalize.fold for accent/case-insensitive text.
    """
    primary = page.locator(f'[data-params*="[{field.item_id},"]')
    if primary.count() > 0:
        return primary.first

    # Last resort: match by accessible label text (folded comparison).
    headings = page.get_by_role("heading")
    target_label = fold(field.label)
    count = headings.count()
    for i in range(count):
        heading = headings.nth(i)
        text = heading.text_content() or ""
        if fold(text) == target_label:
            # Walk up to the nearest listitem ancestor.
            container = heading.locator(
                "xpath=ancestor::div[@role='listitem'][1]"
            )
            if container.count() > 0:
                return container.first

    raise NavigationError(
        f"Could not locate question container for field '{field.label}' "
        f"(item_id={field.item_id})"
    )


def fill_text_field(page: "Page", field: "Field", value: str) -> None:
    container = locate_container(page, field)
    textbox = container.get_by_role("textbox")
    textbox.fill(value)
    actual = textbox.input_value()
    if not validator.assert_text_value(actual, value):
        raise ValidationBannerError(
            f"Read-back mismatch for '{field.label}': expected {value!r}, got {actual!r}"
        )


def fill_radio_field(page: "Page", field: "Field", option: str) -> None:
    container = locate_container(page, field)
    radio = container.get_by_role("radio", name=option, exact=True)

    if radio.count() == 0:
        # Fallback: iterate radios and compare accessible names via fold().
        all_radios = container.get_by_role("radio")
        target = fold(option)
        matched = None
        for i in range(all_radios.count()):
            candidate = all_radios.nth(i)
            name = candidate.get_attribute("aria-label") or ""
            if fold(name) == target:
                matched = candidate
                break
        if matched is None:
            raise OptionMatchFailedError(
                f"No radio option matched '{option}' for field '{field.label}'"
            )
        radio = matched

    radio.click()
    try:
        expect(radio).to_have_attribute("aria-checked", "true", timeout=5000)
    except AssertionError as exc:
        raise ValidationBannerError(
            f"Radio read-back failed for '{field.label}' option '{option}'"
        ) from exc


def fill_dropdown_field(page: "Page", field: "Field", option: str) -> None:
    container = locate_container(page, field)
    listbox = container.get_by_role("listbox")
    if listbox.count() == 0:
        listbox = container.locator('[role="listbox"]').first
    listbox.click()

    # Options may render in a page-level popup, not nested inside the
    # container — search the whole page and pick the visible one.
    # The popup opens with a brief animation, so `count()` (a snapshot,
    # not an auto-waiting check) can race it; `wait_for(state="visible")`
    # uses Playwright's real polling instead of a fixed sleep.
    page_option = page.get_by_role("option", name=option, exact=True)
    try:
        page_option.first.wait_for(state="visible", timeout=5000)
    except Exception as exc:
        raise OptionMatchFailedError(
            f"No dropdown option matched '{option}' for field '{field.label}'"
        ) from exc
    page_option.first.click()

    # Verify by the precise ARIA state, not the raw text blob: every
    # option row is ALWAYS present in listbox.text_content() (Google
    # renders the full option list into the accessibility tree even
    # when visually collapsed), so a plain substring check on that
    # text would pass for ANY option, defeating the read-back gate.
    # The reliable signal is the specific option element carrying
    # `data-value="<option>"` and `aria-selected="true"`.
    #
    # Google updates aria-selected ASYNCHRONOUSLY after the click
    # event fires — a bare get_attribute() snapshot taken right after
    # .click() can read the stale pre-update value (verified against
    # the live DOM: the same check passes reliably with a short
    # settle delay, and fails intermittently without one). Use the
    # `expect` assertion helper, which polls/retries instead of
    # sampling once.
    #
    # Scope this lookup at PAGE level, matching the option click above
    # (page_option searches the whole page, since options may render
    # in a page-level popup, not nested inside `listbox`'s container).
    # A container-scoped `listbox.locator(...)` here would never find
    # the option element when it renders outside the container's DOM
    # subtree, making this assertion spuriously fail for that case.
    selected_option = page.locator(f'[role="option"][data-value="{option}"]').first
    try:
        expect(selected_option).to_have_attribute("aria-selected", "true", timeout=5000)
    except AssertionError as exc:
        raise ValidationBannerError(
            f"Dropdown read-back failed for '{field.label}': "
            f"option '{option}' is not marked aria-selected=true"
        ) from exc


def fill_checkbox_field(page: "Page", field: "Field", checked: bool) -> None:
    # The caller (runner.normalize_record) MUST have already converted
    # the raw value to an actual bool via normalize.si_no() -- any
    # truthy non-empty string (e.g. a raw "Sí"/"No" that skipped
    # normalization) would silently be treated as checked=True here,
    # which is exactly the fragile contract this type check closes.
    if not isinstance(checked, bool):
        raise ValidationBannerError(
            f"fill_checkbox_field for '{field.label}' requires an actual bool, "
            f"got {type(checked).__name__}: {checked!r}"
        )

    if not checked:
        # False leaves the control untouched — there is no "No" option
        # (CLAUDE.md trap #4).
        return

    container = locate_container(page, field)
    checkbox = container.get_by_role("checkbox")
    checkbox.click()
    try:
        expect(checkbox).to_have_attribute("aria-checked", "true", timeout=5000)
    except AssertionError as exc:
        raise ValidationBannerError(
            f"Checkbox read-back failed for '{field.label}'"
        ) from exc


_HANDLERS = {
    0: fill_text_field,
    2: fill_radio_field,
    3: fill_dropdown_field,
    4: fill_checkbox_field,
}


def fill_field(page: "Page", field: "Field", value) -> None:
    """Dispatch to the correct handler by field TYPE (never by field name)."""
    handler = _HANDLERS.get(field.type)
    if handler is None:
        raise NavigationError(f"Unsupported field type {field.type} for '{field.label}'")
    handler(page, field, value)
    _human_pause(page)


def assert_section_visible(page: "Page", section_label: str) -> None:
    """Assert the expected section header is on screen."""
    heading = page.get_by_text(section_label, exact=False)
    heading.first.wait_for(state="visible")


def go_to_next_page(
    page: "Page", next_page_first_field: "Field", allowed_prefixes: tuple[str, ...]
) -> None:
    """Click Siguiente and wait for the next page's first field to attach.

    Google Forms re-renders the next page's controls via client-side
    JS after this click (no full navigation), so a bare `wait_for`
    can race the render; wait for network activity to settle first.
    """
    button = page.get_by_role("button", name="Siguiente")
    button.click()
    _assert_allowed_domain(page, allowed_prefixes)
    page.wait_for_load_state("networkidle")
    container = locate_container(page, next_page_first_field)
    container.wait_for(state="attached", timeout=10000)


def locate_submit_button(page: "Page"):
    """Locate the Enviar button on the last page (never clicked in dry-run)."""
    button = page.get_by_role("button", name="Enviar")
    button.wait_for(state="visible")
    return button


def fill_record(
    page: "Page",
    schema: "FormSchema",
    record_values: dict[str, str],
    dry_run: bool = True,
    allowed_url_prefixes: tuple[str, ...] | None = None,
) -> str:
    """Fill every page of the form with the mapped/normalized values.

    `record_values` is keyed by field LABEL (post-mapping,
    post-normalization). Returns the terminal status string:
    - "DRY_RUN_OK" if dry_run=True: Enviar located, asserted visible,
      NOT clicked.
    - "SUBMITTED" if dry_run=False and confirmation was detected
      (live mode is never exercised in this session, but the code
      path exists per the CLI contract).
    - "SUBMIT_UNCONFIRMED" if dry_run=False and no confirmation was
      detected after clicking Enviar.

    `allowed_url_prefixes` overrides the default production allowlist
    (docs.google.com / forms.gle) — used by tests to point the
    navigation guard at a localhost replica. Defaults to the
    hardcoded production tuple when not provided, so every existing
    caller that doesn't pass this parameter keeps working identically.

    Verified against the live DOM: a MULTI-page form (schema.pages has
    more than one page, i.e. the form has section-header items) lands
    on an intro/title card after `page.goto()` — none of the schema's
    field containers are present yet, and the ONLY visible button is
    "Siguiente". A SINGLE-page form (zero section headers) has no
    such intro card: every field renders immediately and "Enviar" is
    already visible. The intro-card click is therefore conditional on
    page count, not hardcoded per form.
    """
    prefixes = (
        allowed_url_prefixes if allowed_url_prefixes is not None else _ALLOWED_URL_PREFIXES
    )

    _assert_allowed_domain(page, prefixes)

    total_pages = len(schema.pages)

    if total_pages > 1:
        # Multi-page form: leave the intro/title card before the first
        # schema page's fields exist in the DOM.
        first_field = schema.pages[0][0]
        page.get_by_role("button", name="Siguiente").click()
        _assert_allowed_domain(page, prefixes)
        page.wait_for_load_state("networkidle")
        locate_container(page, first_field).wait_for(state="attached", timeout=10000)

    for page_index, page_fields in enumerate(schema.pages):
        is_last_page = page_index == total_pages - 1
        page_label = schema.page_labels[page_index] if schema.page_labels else ""

        if page_label:
            assert_section_visible(page, page_label)

        for field in page_fields:
            value = record_values.get(field.label)
            if field.required and (value is None or value == ""):
                # Should have been caught by the completeness gate
                # before the browser opened; defensive re-check here.
                continue
            if value is None:
                continue
            fill_field(page, field, value)

        if not is_last_page:
            next_page_fields = schema.pages[page_index + 1]
            next_page_label = schema.page_labels[page_index + 1]
            go_to_next_page(page, next_page_fields[0], prefixes)
            _assert_allowed_domain(page, prefixes)
            if next_page_label:
                assert_section_visible(page, next_page_label)

    submit_button = locate_submit_button(page)

    if dry_run:
        return "DRY_RUN_OK"

    submit_button.click()
    _assert_allowed_domain(page, prefixes)

    # Deterministic wait for the confirmation transition BEFORE
    # sampling page.url/page.content() -- Google's post-Enviar
    # redirect is asynchronous, so reading the page state right after
    # .click() can race it and observe the PRE-submit page, wrongly
    # reporting SUBMIT_UNCONFIRMED for a submission that actually
    # succeeded. Wait for the "formResponse" URL marker first (the
    # primary, fastest signal); if that specific wait times out (e.g.
    # a confirmation URL that never carries the marker), fall back to
    # waiting for the load state to settle, then let the phrase check
    # in validator.confirmation decide. Only after one of these waits
    # completes do we evaluate validator.confirmation — never on a
    # bare post-click snapshot.
    try:
        page.wait_for_url("**/formResponse*", timeout=15000)
    except Exception:
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    _assert_allowed_domain(page, prefixes)
    if validator.confirmation(page.url, page.content()):
        return "SUBMITTED"
    return "SUBMIT_UNCONFIRMED"
