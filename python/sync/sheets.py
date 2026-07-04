import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption

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
