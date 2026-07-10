"""execute_sql tool — the only way the agent ever reaches MySQL.

Invariant (CLAUDE.md #2 and #4): every query is validated by AST before it
runs. This function enforces the order itself so no caller can accidentally
skip validation — there is no other function in this codebase that runs SQL.
"""

from __future__ import annotations

from app.database.engine import run_select
from app.security.sql_guard import SqlValidationError, validate_sql


class SqlExecutionError(Exception):
    """Raised when a validated query fails to execute (connection, syntax vs.
    live schema, etc.) — distinct from SqlValidationError, which is a policy
    rejection that never reaches the database."""


def execute_sql(sql: str) -> list[dict]:
    """Validate ``sql`` then run it, returning rows as a list of dicts.

    Raises SqlValidationError if the query violates the security policy
    (never reaches the database in that case), or SqlExecutionError if a
    validated query fails at the database layer.
    """
    validate_sql(sql)  # raises SqlValidationError; never swallowed here
    try:
        return run_select(sql)
    except SqlValidationError:
        raise
    except Exception as error:  # noqa: BLE001 - normalize all DB-layer failures
        raise SqlExecutionError(f"Query failed to execute: {error}") from error
