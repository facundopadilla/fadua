"""Parse Google Forms' FB_PUBLIC_LOAD_DATA_ into a FormSchema.

Every Google Form embeds its live definition in a JavaScript variable
`FB_PUBLIC_LOAD_DATA_` inside the viewform HTML. This module extracts
and parses that structure into a stable `FormSchema` the rest of the
agent depends on (field types, required flags, options, and page
breaks). The schema is parsed LIVE on every run — the JSON fixtures
under fixtures/ are test data only, never the runtime source.

Field type codes (see CLAUDE.md "FB field type codes"):
    0 = short text
    2 = radio (single choice)
    3 = dropdown (ARIA listbox)
    4 = checkbox
    8 = section header / page break (not an answerable field)

IMPORTANT (verified): the raw page-history array in FB_PUBLIC_LOAD_DATA_
is always `[2]` regardless of the real number of pages. Page structure
MUST be derived exclusively from type-8 (section break) items, never
from that array.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field as dc_field

# Field types the agent knows how to fill. Everything else (currently
# only type 8, section breaks) is recorded in the schema but excluded
# from `fields`.
_ANSWERABLE_TYPES = {0, 2, 3, 4}
_SECTION_TYPE = 8

_FB_PATTERN = re.compile(
    r"FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*?\])\s*;", re.DOTALL
)


@dataclass
class Field:
    """One answerable form field."""

    item_id: str
    entry_id: str
    label: str
    type: int
    required: bool
    options: list[str]


@dataclass
class FormSchema:
    """Parsed structure of a Google Form."""

    title: str
    fields: list[Field] = dc_field(default_factory=list)
    pages: list[list[Field]] = dc_field(default_factory=list)
    page_labels: list[str] = dc_field(default_factory=list)
    ignored_types: set[int] = dc_field(default_factory=set)


def _extract_fb_data(html_or_json) -> list:
    """Return the raw FB_PUBLIC_LOAD_DATA_ structure as a Python list.

    Accepts either an already-parsed JSON list/structure (as stored in
    fixtures/) or raw HTML containing the `FB_PUBLIC_LOAD_DATA_ = (...);`
    assignment.
    """
    if isinstance(html_or_json, list):
        return html_or_json

    if isinstance(html_or_json, str):
        match = _FB_PATTERN.search(html_or_json)
        if match:
            return json.loads(match.group(1))
        # Not HTML with the assignment — maybe it's a raw JSON string.
        return json.loads(html_or_json)

    raise ValueError(
        "parse_fb expects a parsed JSON list or a string (raw HTML or "
        "raw JSON text)"
    )


def _parse_field(item: list) -> Field | None:
    """Parse one item array into a Field, or None if not answerable."""
    item_id, label, _description, item_type = item[0], item[1], item[2], item[3]

    if item_type not in _ANSWERABLE_TYPES:
        return None

    entries = item[4]
    if not entries:
        return None

    entry = entries[0]
    entry_id = entry[0]
    raw_options = entry[1] if len(entry) > 1 else None
    required_flag = entry[2] if len(entry) > 2 else 0

    options: list[str] = []
    if raw_options:
        options = [opt[0] for opt in raw_options]

    return Field(
        item_id=str(item_id),
        entry_id=f"entry.{entry_id}",
        label=label,
        type=item_type,
        required=bool(required_flag),
        options=options,
    )


def parse_fb(html_or_json) -> FormSchema:
    """Parse FB_PUBLIC_LOAD_DATA_ (HTML or already-parsed JSON) into a FormSchema."""
    data = _extract_fb_data(html_or_json)

    # data[1] is the form-body array; data[1][0] is the description;
    # data[1][1] is the list of item arrays; data[1][8] is the title.
    form_body = data[1]
    items = form_body[1]
    title = form_body[8]

    fields: list[Field] = []
    pages: list[list[Field]] = []
    page_labels: list[str] = []
    current_page: list[Field] | None = None
    ignored_types: set[int] = set()

    for item in items:
        item_type = item[3]

        if item_type == _SECTION_TYPE:
            # A section header (type 8) STARTS a new page — it does not
            # close the previous one. Google Forms places the section
            # header before the fields it introduces, so opening a page
            # here (rather than on section-close) keeps a form with N
            # section headers at N pages, matching the verified fixtures
            # (Form 1: 3 section headers -> 3 pages). The header's own
            # label (item[1]) becomes this new page's page_label, so
            # filler.py can assert it is on screen before/after
            # "Siguiente".
            current_page = []
            pages.append(current_page)
            page_labels.append(item[1])
            continue

        parsed = _parse_field(item)
        if parsed is None:
            ignored_types.add(item_type)
            continue

        fields.append(parsed)
        if current_page is None:
            # No section header seen yet: this form has zero type-8
            # items, so it is single-page. Open page 0 lazily on the
            # first field (Form 2: 0 section headers -> 1 page), with
            # an empty page_label since no section header introduced it.
            current_page = []
            pages.append(current_page)
            page_labels.append("")
        current_page.append(parsed)

    return FormSchema(
        title=title,
        fields=fields,
        pages=pages,
        page_labels=page_labels,
        ignored_types=ignored_types,
    )


def fetch_schema(url: str) -> FormSchema:
    """Fetch a Google Form's viewform HTML and parse its live schema.

    Appends `hl=es` to force the Spanish locale (so labels/options match
    what the sheet data and CLAUDE.md expect) and sends a Mozilla
    User-Agent header (Google serves a reduced/no-JS page to unknown
    clients otherwise).
    """
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(
        f"{url}{separator}hl=es",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request) as response:
        html = response.read().decode("utf-8")
    return parse_fb(html)
