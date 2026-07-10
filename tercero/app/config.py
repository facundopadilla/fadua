"""Runtime configuration: env vars + defaults.

Locked values (sheet ID, form URLs, tab->form routing) come from the
verified FADUA challenge data (CLAUDE.md). Everything overridable via
.env for the swappable-provider and clone-form-testing use cases.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (stdlib only, no python-dotenv dependency).

    Silently does nothing if the file doesn't exist. Does not override
    variables already present in the real environment.
    """
    if not os.path.exists(path):
        return

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv()

DEFAULT_SHEET_ID = "1y6aREOjFrbDd5bKlpt72UBc6svk_pr2wBsAqv_xb_2Y"

DEFAULT_FORM_URLS = {
    "ventas": (
        "https://docs.google.com/forms/d/e/"
        "1FAIpQLSfx7iW9XGsgU0jSFyv9yIcoDPAzqOHYK5Pj2fXHKIBAxZ1MgQ/viewform"
    ),
    "mora": (
        "https://docs.google.com/forms/d/e/"
        "1FAIpQLSd9KkkYFKRicadedg07Pj6sXvOXey4G5vLsqvKw4EZ_VRuKIQ/viewform"
    ),
}

# Sheet tab name -> form key. Determines which form a given sheet tab
# feeds into.
DEFAULT_TAB_ROUTING = {
    "VENTAS": "ventas",
    "MORA": "mora",
}

DEFAULT_RUNS_DIR = "runs"

# Allowed navigation domains (security invariant: abort on any
# redirect outside this allowlist).
ALLOWED_DOMAINS = ("https://docs.google.com/", "https://forms.gle/")


@dataclass
class Config:
    sheet_id: str = field(default_factory=lambda: os.environ.get("SHEET_ID", DEFAULT_SHEET_ID))
    form_urls: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_FORM_URLS))
    tab_routing: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TAB_ROUTING))
    runs_dir: str = field(default_factory=lambda: os.environ.get("RUNS_DIR", DEFAULT_RUNS_DIR))
    allowed_url_prefixes: tuple[str, ...] = field(default_factory=lambda: ALLOWED_DOMAINS)
    opencode_base_url: str = field(default_factory=lambda: os.environ.get("OPENCODE_BASE_URL", ""))
    opencode_api_key: str = field(default_factory=lambda: os.environ.get("OPENCODE_API_KEY", ""))
    opencode_model: str = field(default_factory=lambda: os.environ.get("OPENCODE_MODEL", ""))


def load_config() -> Config:
    """Build a Config from environment variables (with .env pre-loaded)."""
    return Config()
