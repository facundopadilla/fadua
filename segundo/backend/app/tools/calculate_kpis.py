"""calculate_kpis tool — commercial KPI math, computed here and only here.

Invariant (CLAUDE.md #3): the LLM never computes metrics — it only narrates
what this module returns. Formulas match the canonical table in CLAUDE.md
"KPI definitions", using pandas aggregation over rows already fetched via
execute_sql. This module never queries the database itself.

``costo_total`` / ``gasto`` = google_ads_costo_usd + meta_ads_costo_usd,
per the Business Dictionary composite concept.
"""

from __future__ import annotations

import pandas as pd

_COST_COLUMNS = ("google_ads_costo_usd", "meta_ads_costo_usd")
_CLICK_COLUMNS = ("google_ads_clics", "meta_ads_clics")
_IMPRESSION_COLUMNS = ("google_ads_impresiones", "meta_ads_impresiones")
_LEAD_COLUMNS = ("total_leads",)
_SALES_COLUMN = "cantidad_ventas"
_INCOME_COLUMN = "ingresos_ventas_usd"


def calculate_kpis(rows: list[dict]) -> dict[str, float]:
    """Compute CTR, CPC, CPL, CPA, ROAS, ROI, and Conversion Rate over ``rows``.

    Each KPI is computed over the *sums* of its inputs across all rows
    (not row-by-row averages), which is the standard aggregate definition
    for these commercial ratios. A KPI is omitted (not zero, not NaN) when
    its denominator is zero or the required columns are absent — that is a
    signal to the caller (confidence scoring) rather than a fabricated 0.0.
    """
    if not rows:
        return {}

    frame = pd.DataFrame(rows)

    impresiones = _safe_sum(frame, _IMPRESSION_COLUMNS)
    clics = _safe_sum(frame, _CLICK_COLUMNS)
    costo_total = _safe_sum(frame, _COST_COLUMNS)
    leads = _safe_sum(frame, _LEAD_COLUMNS)
    ventas = _safe_sum(frame, (_SALES_COLUMN,))
    ingresos = _safe_sum(frame, (_INCOME_COLUMN,))

    metrics: dict[str, float] = {}

    _set_ratio(metrics, "ctr", clics, impresiones)
    _set_ratio(metrics, "cpc", costo_total, clics)
    _set_ratio(metrics, "cpl", costo_total, leads)
    _set_ratio(metrics, "cpa", costo_total, ventas)
    _set_ratio(metrics, "roas", ingresos, costo_total)
    _set_ratio(metrics, "conversion_rate", ventas, leads)

    if costo_total is not None and costo_total != 0 and ingresos is not None:
        metrics["roi"] = (ingresos - costo_total) / costo_total

    if costo_total is not None:
        metrics["costo_total"] = costo_total
    if ingresos is not None:
        metrics["ingresos_totales"] = ingresos
    if ventas is not None and ventas != 0 and costo_total is not None:
        metrics["costo_por_venta"] = costo_total / ventas

    return {key: round(float(value), 4) for key, value in metrics.items()}


def _safe_sum(frame: pd.DataFrame, columns: tuple[str, ...]) -> float | None:
    """Sum ``columns`` present in ``frame``; None if none of them exist."""
    present = [column for column in columns if column in frame.columns]
    if not present:
        return None
    return float(frame[present].sum().sum())


def _set_ratio(
    metrics: dict[str, float], key: str, numerator: float | None, denominator: float | None
) -> None:
    if numerator is None or denominator is None or denominator == 0:
        return
    metrics[key] = numerator / denominator
