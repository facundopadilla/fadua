import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption, rowcol_to_a1

# Spreadsheets scope is enough to read/append; Drive scope lets gspread
# resolve the file by key without needing separate Drive API access.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Bound every Sheets API call. gspread defaults to timeout=None (wait forever);
# under the cron's flock, one hung call would silently stall all later runs.
REQUEST_TIMEOUT_SECONDS = 30


def _open_worksheet(sa_json_path: str, sheet_id: str, tab: str) -> gspread.Worksheet:
    credentials = Credentials.from_service_account_file(sa_json_path, scopes=SCOPES)
    client = gspread.authorize(credentials)
    client.set_timeout(REQUEST_TIMEOUT_SECONDS)
    spreadsheet = client.open_by_key(sheet_id)
    return spreadsheet.worksheet(tab)


def read_existing_ids(sa_json_path: str, sheet_id: str, tab: str) -> set:
    """Read the existing product IDs from column A (ID) of the given tab.

    The sheet is the source of truth: no local state file, no caching
    between runs. Empty cells and the header row come back as None or
    non-numeric text from col_values(), so only digit-only values are kept
    as real product IDs; everything is normalized to str.
    """
    worksheet = _open_worksheet(sa_json_path, sheet_id, tab)
    column = worksheet.col_values(1)
    return {
        str(value).strip()
        for value in column
        if value is not None and str(value).strip().isdigit()
    }


def append_rows(sa_json_path: str, sheet_id: str, tab: str, rows: list) -> None:
    """Append rows to the given tab, in the exact order they're passed in.

    Uses RAW value input so values (notably price) are stored verbatim,
    never auto-parsed/coerced into numbers by the Sheets API.
    """
    worksheet = _open_worksheet(sa_json_path, sheet_id, tab)
    worksheet.append_rows(rows, value_input_option=ValueInputOption.raw)


def _safe_cell(row: list, index: int | None) -> str:
    """Return row[index], or "" when index is None or the row is too short.

    get_all_values() returns ragged rows: the Sheets API trims trailing
    empty cells, so a data row can have fewer cells than the header row.
    """
    if index is None or index >= len(row):
        return ""
    return row[index]


def read_existing_rows(sa_json_path: str, sheet_id: str, tab: str) -> dict:
    """Read existing product rows from the sheet, keyed by str(ID).

    Uses get_all_values(): row 1 is the header row, data starts at row 2.
    Columns are looked up BY HEADER NAME (not hardcoded position) so the
    mapping stays correct if a column is reordered or absent. Rows whose ID
    cell isn't numeric (blank cells, stray text) are skipped, matching
    read_existing_ids. Each entry's "row" is the real 1-indexed spreadsheet
    row number, needed by update_rows() to target that exact record.
    """
    worksheet = _open_worksheet(sa_json_path, sheet_id, tab)
    all_values = worksheet.get_all_values()
    if not all_values:
        return {}

    header_row = all_values[0]
    header_index = {header: index for index, header in enumerate(header_row)}

    id_index = header_index.get("ID")
    if id_index is None:
        return {}

    field_indexes = {
        field: header_index.get(field) for field in ("Producto", "Precio", "Imagen")
    }

    existing_by_id = {}
    for row_number, row in enumerate(all_values[1:], start=2):
        raw_id = _safe_cell(row, id_index).strip()
        if not raw_id.isdigit():
            continue
        existing_by_id[raw_id] = {
            "row": row_number,
            "Producto": _safe_cell(row, field_indexes["Producto"]),
            "Precio": _safe_cell(row, field_indexes["Precio"]),
            "Imagen": _safe_cell(row, field_indexes["Imagen"]),
        }

    return existing_by_id


def update_rows(sa_json_path: str, sheet_id: str, tab: str, updates: list) -> None:
    """Update existing rows in place, one Sheets API call per row.

    `updates` is a list of (row_number, [ID, Producto, Precio, Imagen,
    Sincronizado]) pairs; each entry overwrites that exact row's cells
    starting at column A. Uses the same RAW value input as append_rows, so
    values (notably price) are stored verbatim rather than auto-parsed by
    the Sheets API.
    """
    worksheet = _open_worksheet(sa_json_path, sheet_id, tab)
    for row_number, row_values in updates:
        start_cell = rowcol_to_a1(row_number, 1)
        end_cell = rowcol_to_a1(row_number, len(row_values))
        worksheet.update(
            values=[row_values],
            range_name=f"{start_cell}:{end_cell}",
            value_input_option=ValueInputOption.raw,
        )
