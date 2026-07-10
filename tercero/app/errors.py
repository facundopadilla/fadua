"""Error taxonomy and evidence capture.

Every failure produces evidence (a screenshot, when a page is
available) and is reported as a JSONL line — record processing never
crashes the batch. Status codes match specs.md's "Manejo de Errores"
table exactly.
"""

from __future__ import annotations

from pathlib import Path


class FormFillerError(Exception):
    """Base class for all recoverable per-record failures.

    Every subclass carries a `status` class attribute matching one of
    the taxonomy codes so callers (runner.py) can log a consistent
    JSONL entry regardless of which specific error was raised.
    """

    status: str = "UNKNOWN_ERROR"


class SkippedRequiredEmptyError(FormFillerError):
    """A required field is empty after normalization (never invent a 0)."""

    status = "SKIPPED_REQUIRED_EMPTY"


class DirtyValueError(FormFillerError):
    """A cell value could not be parsed by the deterministic normalizer."""

    status = "DIRTY_VALUE"


class OptionMatchFailedError(FormFillerError):
    """No form option matches the source value (never guess the closest one)."""

    status = "OPTION_MATCH_FAILED"


class NavigationError(FormFillerError):
    """The expected section did not appear after clicking Siguiente."""

    status = "NAVIGATION_ERROR"


class ValidationBannerError(FormFillerError):
    """The site displayed a validation banner."""

    status = "VALIDATION_BANNER"


class TimeoutFillerError(FormFillerError):
    """A control or page exceeded the load-wait limit."""

    status = "TIMEOUT"


class SubmitUnconfirmedError(FormFillerError):
    """Submission occurred but the confirmation page was never detected."""

    status = "SUBMIT_UNCONFIRMED"


class SchemaDriftError(FormFillerError):
    """The live schema differs from the expected one (new field/option/type)."""

    status = "SCHEMA_DRIFT"


class LlmError(FormFillerError):
    """The LLM mapping fallback failed or returned low confidence."""

    status = "LLM_ERROR"


# Non-error terminal statuses (not exceptions — recorded directly by
# runner.py on the success paths).
DRY_RUN_OK = "DRY_RUN_OK"
SUBMITTED = "SUBMITTED"


def evidence(page, runs_dir: str | Path, name: str) -> str | None:
    """Save a screenshot of `page` under `runs_dir/name.png`.

    Returns the saved path as a string, or None if `page` is falsy
    (e.g. a completeness-gate skip that never opened a browser).
    """
    if not page:
        return None

    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = runs_dir / f"{name}.png"
    page.screenshot(path=str(screenshot_path))
    return str(screenshot_path)
