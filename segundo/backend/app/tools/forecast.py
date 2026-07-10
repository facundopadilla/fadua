"""forecast_sales / forecast_leads / forecast_income tools — Prophet-based.

Locked decisions (CLAUDE.md "Startup decisions" #2, invariant #3):
- Data is daily rows, 1-2 years of history -> strong weekly seasonality,
  weak yearly (only 1-2 cycles observed). ``weekly_seasonality`` stays on;
  ``yearly_seasonality`` is treated as low-confidence (still enabled — data
  can inform it — but forecasts trust window narrows accordingly).
- Trust horizon is ~30 days (the spec's "próximo mes"). This module forecasts
  a 30-day horizon by default and does not claim reliability past ~90 days.
- The LLM never predicts; Prophet (or the documented fallback) does. The
  engine only narrates this module's output.

Prophet is heavy and occasionally fails to import (missing cmdstan/system
deps). The import is wrapped in try/except so a broken Prophet install NEVER
blocks the request path — forecasting degrades to a numpy/pandas linear
trend instead of failing outright.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_HORIZON_DAYS = 30
# Prophet's own duplicate-guard aside, this is our floor for even attempting
# a seasonal decomposition; below it we go straight to the trend fallback.
MIN_POINTS_FOR_PROPHET = 14

try:
    from prophet import Prophet

    _PROPHET_IMPORT_ERROR: Exception | None = None
except Exception as error:  # noqa: BLE001 - Prophet's ImportError surface is broad (cmdstan, etc.)
    Prophet = None  # type: ignore[assignment, misc]
    _PROPHET_IMPORT_ERROR = error


@dataclass
class ForecastPoint:
    date: str
    value: float
    lower: float
    upper: float


@dataclass
class ForecastResult:
    points: list[ForecastPoint]
    method: str  # "prophet" or "linear_trend"
    history_points: int
    horizon_days: int
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "points": [point.__dict__ for point in self.points],
            "method": self.method,
            "history_points": self.history_points,
            "horizon_days": self.horizon_days,
            "warning": self.warning,
        }


def forecast_sales(rows: list[dict], horizon_days: int = DEFAULT_HORIZON_DAYS) -> ForecastResult:
    """Forecast ``cantidad_ventas`` over the next ``horizon_days``."""
    return _forecast_series(rows, value_column="cantidad_ventas", horizon_days=horizon_days)


def forecast_leads(rows: list[dict], horizon_days: int = DEFAULT_HORIZON_DAYS) -> ForecastResult:
    """Forecast ``total_leads`` over the next ``horizon_days``."""
    return _forecast_series(rows, value_column="total_leads", horizon_days=horizon_days)


def forecast_income(rows: list[dict], horizon_days: int = DEFAULT_HORIZON_DAYS) -> ForecastResult:
    """Forecast ``ingresos_ventas_usd`` over the next ``horizon_days``."""
    return _forecast_series(rows, value_column="ingresos_ventas_usd", horizon_days=horizon_days)


def _forecast_series(
    rows: list[dict], *, value_column: str, horizon_days: int
) -> ForecastResult:
    """Build a daily (ds, y) series from ``rows`` and forecast ``horizon_days`` ahead.

    Always returns a result — never raises for "not enough data" or "Prophet
    unavailable". Those become the ``method``/``warning`` fields instead, so
    the engine can narrate the degraded confidence rather than crash.
    """
    series = _build_series(rows, value_column)

    if len(series) < 2:
        return ForecastResult(
            points=[],
            method="none",
            history_points=len(series),
            horizon_days=horizon_days,
            warning="Not enough historical data points to forecast.",
        )

    if Prophet is not None and len(series) >= MIN_POINTS_FOR_PROPHET:
        try:
            return _forecast_with_prophet(series, horizon_days=horizon_days)
        except Exception as error:  # noqa: BLE001 - never let Prophet block the path
            return _forecast_with_linear_trend(
                series,
                horizon_days=horizon_days,
                warning=f"Prophet failed at runtime, used linear trend fallback: {error}",
            )

    warning = None
    if Prophet is None:
        warning = f"Prophet is unavailable ({_PROPHET_IMPORT_ERROR}); used linear trend fallback."
    elif len(series) < MIN_POINTS_FOR_PROPHET:
        warning = (
            f"Only {len(series)} data points (< {MIN_POINTS_FOR_PROPHET}); "
            "used linear trend fallback."
        )
    return _forecast_with_linear_trend(series, horizon_days=horizon_days, warning=warning)


def _build_series(rows: list[dict], value_column: str) -> pd.DataFrame:
    """Reduce raw rows to a clean daily (ds, y) series, sorted and deduped.

    Rows may already be daily (one per ``fecha``) or may need summing when
    the caller passed grouped/aggregated rows; grouping by date and summing
    is safe either way and matches how ``cantidad_ventas``/``total_leads``/
    ``ingresos_ventas_usd`` are additive across a day.
    """
    if not rows:
        return pd.DataFrame(columns=["ds", "y"])

    frame = pd.DataFrame(rows)
    if "fecha" not in frame.columns or value_column not in frame.columns:
        return pd.DataFrame(columns=["ds", "y"])

    frame = frame[["fecha", value_column]].copy()
    frame["fecha"] = pd.to_datetime(frame["fecha"])
    frame[value_column] = pd.to_numeric(frame[value_column], errors="coerce")
    frame = frame.dropna(subset=[value_column])

    grouped = frame.groupby("fecha", as_index=False)[value_column].sum()
    grouped = grouped.sort_values("fecha")
    grouped = grouped.rename(columns={"fecha": "ds", value_column: "y"})
    return grouped.reset_index(drop=True)


def _forecast_with_prophet(series: pd.DataFrame, *, horizon_days: int) -> ForecastResult:
    model = Prophet(weekly_seasonality=True, yearly_seasonality="auto")
    model.fit(series)

    future = model.make_future_dataframe(periods=horizon_days, freq="D")
    forecast = model.predict(future)

    future_only = forecast[forecast["ds"] > series["ds"].max()]

    points = [
        ForecastPoint(
            date=row.ds.strftime("%Y-%m-%d"),
            value=max(0.0, float(row.yhat)),
            lower=max(0.0, float(row.yhat_lower)),
            upper=max(0.0, float(row.yhat_upper)),
        )
        for row in future_only.itertuples()
    ]

    warning = None
    if horizon_days > 90:
        warning = "Horizon exceeds ~90 days; intervals widen and confidence drops sharply beyond that."
    elif horizon_days > 30:
        warning = "Horizon exceeds the ~30-day trust window for this data; treat as low-confidence."

    return ForecastResult(
        points=points,
        method="prophet",
        history_points=len(series),
        horizon_days=horizon_days,
        warning=warning,
    )


def _forecast_with_linear_trend(
    series: pd.DataFrame, *, horizon_days: int, warning: str | None
) -> ForecastResult:
    """Numpy/pandas linear-regression fallback when Prophet is unusable.

    Fits ``y = a*t + b`` over the ordinal day index and projects it forward.
    Residual std sets a simple symmetric interval — deliberately unadorned;
    this path exists to avoid ever blocking on Prophet, not to compete with it.
    """
    ordinals = series["ds"].map(pd.Timestamp.toordinal).to_numpy(dtype=float)
    values = series["y"].to_numpy(dtype=float)

    slope, intercept = np.polyfit(ordinals, values, 1)
    predicted = slope * ordinals + intercept
    residual_std = float(np.std(values - predicted)) if len(values) > 1 else 0.0

    last_date = series["ds"].max()
    points: list[ForecastPoint] = []
    for step in range(1, horizon_days + 1):
        future_date = last_date + pd.Timedelta(days=step)
        future_ordinal = future_date.toordinal()
        value = max(0.0, float(slope * future_ordinal + intercept))
        points.append(
            ForecastPoint(
                date=future_date.strftime("%Y-%m-%d"),
                value=value,
                lower=max(0.0, value - 1.96 * residual_std),
                upper=value + 1.96 * residual_std,
            )
        )

    return ForecastResult(
        points=points,
        method="linear_trend",
        history_points=len(series),
        horizon_days=horizon_days,
        warning=warning,
    )
