"""SQLAlchemy engine + the single read entrypoint used by tools.

Connects lazily (SQLAlchemy engines don't open a connection until first use),
so importing this module never requires a live database. ``run_select`` is
the only function that talks to MySQL — every caller must have already
passed the query through ``app.security.sql_guard.validate_sql``.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, text

from app.config import settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide engine, created on first use.

    ``pool_pre_ping`` avoids handing out stale connections after MySQL
    restarts or idle timeouts, which matters for a long-lived API process.
    """
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


def run_select(sql: str) -> list[dict]:
    """Execute an already-validated SELECT and return rows as dicts.

    Callers MUST call ``validate_sql(sql)`` before this — this function does
    not validate. It only executes and marshals results.

    Normalizes ``Decimal`` values (PyMySQL's type for SUM/AVG/DECIMAL
    columns) to ``float``. Without this, pandas treats a Decimal column as
    ``object`` dtype rather than numeric — ``pd.api.types.is_numeric_dtype``
    then returns False and every downstream numeric check (chart building,
    dataset summarization) silently sees "no numeric columns". ``date``/
    ``datetime`` values are left as-is: pandas and Prophet need real date
    objects, and Pydantic already serializes them correctly at the API
    boundary (``ChatResponse.model_dump_json()``).
    """
    engine = get_engine()
    with engine.connect() as connection:
        result = connection.execute(text(sql))
        return [
            {key: _normalize_value(value) for key, value in row.items()}
            for row in result.mappings()
        ]


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value
