"""Confidence scoring — derived from execution signals, never self-reported.

Locked decision (CLAUDE.md "Startup decisions", minor): confidence is never
what the LLM claims about itself. It reflects concrete facts about how the
request was actually served: was SQL validated and did it return rows, did
a forecast have enough points, did anything fall back to a degraded path.
"""

from __future__ import annotations

from app.schemas.chat import Intent
from app.tools.forecast import ForecastResult


def score_sql_result(rows: list[dict]) -> float:
    if not rows:
        return 0.3  # validated + executed, but zero rows: real signal, low value
    return 1.0


def score_kpi_result(rows: list[dict], metrics: dict[str, float]) -> float:
    if not rows:
        return 0.3
    if not metrics:
        return 0.4  # rows exist but no KPI could be computed (e.g. zero denominators)
    return 1.0


def score_forecast_result(result: ForecastResult) -> float:
    if not result.points:
        return 0.2
    if result.method == "linear_trend":
        return 0.6  # degraded path: fewer assumptions validated than Prophet
    if result.warning:  # e.g. horizon beyond the ~30-90 day trust window
        return 0.75
    return 0.95  # Prophet succeeded on the intended horizon


def score_comparison_result(channel_rows: dict) -> float:
    if not channel_rows:
        return 0.3
    if len(channel_rows) < 2:
        return 0.5  # only one side of the comparison came back
    return 1.0


def score_chart_result(rows: list[dict], chart_built: bool) -> float:
    if not rows:
        return 0.3
    if not chart_built:
        return 0.4  # data exists but couldn't be shaped into a chart
    return 1.0


def score_conversation() -> float:
    # No data access happened; this is a fixed, honest baseline — not a
    # claim about data accuracy since none was queried.
    return 0.9


def fallback_score(intent: Intent) -> float:
    """Used when an exception was caught and the engine had to degrade."""
    return 0.2
