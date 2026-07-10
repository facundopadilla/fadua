"""Controlled data-access tools — the ONLY path to MySQL (CLAUDE.md invariant #2).

The agent engine calls these functions; it never builds or runs SQL itself.
"""

from app.tools.calculate_kpis import calculate_kpis
from app.tools.create_chart import create_chart
from app.tools.execute_sql import SqlExecutionError, execute_sql
from app.tools.forecast import ForecastResult, forecast_income, forecast_leads, forecast_sales
from app.tools.summarize import summarize_dataset

__all__ = [
    "calculate_kpis",
    "create_chart",
    "execute_sql",
    "SqlExecutionError",
    "ForecastResult",
    "forecast_sales",
    "forecast_leads",
    "forecast_income",
    "summarize_dataset",
]
