"""create_chart tool — builds the ChartConfig the frontend feeds to Recharts.

Spec mapping (specs.md "Visualizaciones"):
    time series   -> line
    ranking       -> bar
    distribution  -> pie

This module never invents data points — it only reshapes rows already
returned by execute_sql/calculate_kpis into the ChartConfig shape.
"""

from __future__ import annotations

from app.schemas.chat import ChartConfig, Intent

_DATE_KEYS = ("fecha", "periodo", "mes", "anio", "año")
_LABEL_KEYS = ("vehiculo_modelo_principal", "vehiculo_tipo_principal", "modelo", "tipo", "canal", "categoria")


def create_chart(
    rows: list[dict],
    intent: Intent,
    *,
    title: str | None = None,
    chart_type: str | None = None,
) -> ChartConfig | None:
    """Build a ChartConfig from ``rows``, or None if there's nothing to plot.

    ``chart_type`` lets a caller force line/bar/pie explicitly; otherwise the
    type is inferred: a time-series-shaped row set becomes a line chart, a
    row set with a small categorical dimension becomes a bar (ranking) or
    pie (distribution) chart depending on cardinality.
    """
    if not rows:
        return None

    columns = list(rows[0].keys())
    numeric_keys = [key for key in columns if _looks_numeric(rows, key)]
    if not numeric_keys:
        return None

    x_key = _pick_key(columns, _DATE_KEYS) or _pick_key(columns, _LABEL_KEYS) or _first_non_numeric(
        columns, numeric_keys
    )

    resolved_type = chart_type or _infer_type(intent, x_key, len(rows))

    return ChartConfig(
        type=resolved_type,  # type: ignore[arg-type]
        title=title,
        data=rows,
        x_key=x_key,
        y_keys=numeric_keys,
    )


def _infer_type(intent: Intent, x_key: str | None, row_count: int) -> str:
    if x_key in _DATE_KEYS:
        return "line"
    if intent == Intent.CHART and x_key in _DATE_KEYS:
        return "line"
    if row_count <= 6:
        return "pie"
    return "bar"


def _pick_key(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _first_non_numeric(columns: list[str], numeric_keys: list[str]) -> str | None:
    for column in columns:
        if column not in numeric_keys:
            return column
    return columns[0] if columns else None


def _looks_numeric(rows: list[dict], key: str) -> bool:
    for row in rows[:5]:  # sample; good enough for homogeneous SQL result sets
        value = row.get(key)
        if value is None:
            continue
        return isinstance(value, int | float) and not isinstance(value, bool)
    return False
