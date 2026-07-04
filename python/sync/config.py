import os
from dataclasses import dataclass

from dotenv import load_dotenv


class MissingConfigError(RuntimeError):
    """Raised when a required environment variable is missing or invalid."""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingConfigError(f"Missing required environment variable: {name}")
    return value


def _require_int(name: str) -> int:
    value = _require(name)
    try:
        return int(value)
    except ValueError:
        raise MissingConfigError(
            f"Environment variable {name} must be an integer, got: {value!r}"
        ) from None


@dataclass(frozen=True)
class Config:
    wc_base_url: str
    wc_consumer_key: str
    wc_consumer_secret: str
    google_sheet_id: str
    google_sheet_tab: str
    google_sa_json: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_app_password: str
    notify_to: str


def load_config() -> Config:
    """Load and validate configuration from environment variables (.env).

    Fails fast with MissingConfigError if a required variable is missing or,
    for SMTP_PORT, not a valid integer.
    """
    load_dotenv()
    return Config(
        wc_base_url=_require("WC_BASE_URL").rstrip("/"),
        wc_consumer_key=_require("WC_CONSUMER_KEY"),
        wc_consumer_secret=_require("WC_CONSUMER_SECRET"),
        google_sheet_id=_require("GOOGLE_SHEET_ID"),
        google_sheet_tab=_require("GOOGLE_SHEET_TAB"),
        google_sa_json=_require("GOOGLE_SA_JSON"),
        smtp_host=_require("SMTP_HOST"),
        smtp_port=_require_int("SMTP_PORT"),
        smtp_user=_require("SMTP_USER"),
        smtp_app_password=_require("SMTP_APP_PASSWORD"),
        notify_to=_require("NOTIFY_TO"),
    )
