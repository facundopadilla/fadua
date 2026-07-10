"""Read-only access to the Google Sheets data source.

Sheet access is exclusively via the public `gviz` CSV export (no OAuth,
no write scope) — the agent cannot mutate the source. This module is
the ONLY read path to the Google Sheet in the whole codebase.

`parse_csv` is split out as a pure function so its logic (header +
value stripping) can be tested offline against the fixture CSVs
without any network call. `fetch_tab` wraps it with the HTTP fetch.
"""

from __future__ import annotations

import csv
import io
import urllib.request

_GVIZ_URL_TEMPLATE = (
    "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
    "?tqx=out:csv&sheet={tab}"
)


def parse_csv(text: str) -> list[dict[str, str]]:
    """Parse gviz CSV text into a list of records.

    Every header AND every value is `.strip()`-ed on ingest (CLAUDE.md
    trap #5: headers arrive with leading spaces, e.g. " Valor_Vehiculo").
    Value CONTENT is otherwise left as-is — dirty currency strings like
    "$ 18,500,000" are cleaned later by normalize.currency, not here.
    """
    reader = csv.DictReader(io.StringIO(text))
    records: list[dict[str, str]] = []
    for row in reader:
        clean_row = {
            (key.strip() if key is not None else key): (
                value.strip() if value is not None else value
            )
            for key, value in row.items()
        }
        records.append(clean_row)
    return records


def fetch_tab(sheet_id: str, tab: str) -> list[dict[str, str]]:
    """Fetch one sheet tab as CSV and parse it into records.

    Read-only: uses the public gviz export endpoint, no credentials.
    """
    url = _GVIZ_URL_TEMPLATE.format(sheet_id=sheet_id, tab=tab)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request) as response:
        text = response.read().decode("utf-8")
    return parse_csv(text)
