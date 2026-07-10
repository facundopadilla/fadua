"""Deterministic SQL builder — turns planner hints into a validated query.

Locked decision: the planner is deterministic, not an LLM (CLAUDE.md
"Startup decisions" #3). Since there is no LLM call in the default path
(``settings.llm_api_key`` empty), something has to produce SQL text from
intent + hints without an LLM. This module is that "something": it composes
SQL from the Business Dictionary (app.semantics.dictionary) using fixed
templates keyed by pattern, never by string-interpolating free user text
directly into SQL.

Every query this module builds is still passed through
``app.security.sql_guard.validate_sql`` by the caller before execution —
this module does not get a bypass. It only ever emits SELECTs against
``metricas_campanas_ventas`` using known columns/expressions from the
dictionary, so validation should always pass; the guard call downstream is
the actual enforcement point, not a formality.
"""

from __future__ import annotations

from app.planner.planner import PlannerResult
from app.schemas.chat import Intent
from app.semantics.dictionary import (
    ADS_CHANNELS,
    CHANNEL_METRIC_COLUMNS,
    DATE_COLUMN,
    TABLE_NAME,
)

_DEFAULT_METRIC_EXPRESSION = "cantidad_ventas"
_DEFAULT_METRIC_ALIAS = "cantidad_ventas"

# Words that signal the user wants a time series (one row per day/period),
# not a single aggregate number. A CHART intent also implies a series even
# without one of these words (e.g. "graficá las ventas" still needs a plotted
# series, not one point). Kept separate from _SQL_KEYWORDS/_CHART_KEYWORDS in
# app.planner.planner: this list is specifically about the *shape* of the
# answer (series vs. one row), not about routing to a chart-producing tool.
_SERIES_KEYWORDS = (
    "evolución",
    "evolucion",
    "tendencia",
    "por día",
    "por dia",
    "por mes",
    "diaria",
    "diario",
    "a lo largo",
    "en el tiempo",
    "histórico",
    "historico",
    "serie",
)

# Concept -> (SQL expression, output alias). Aliases are fixed identifiers,
# never derived from user text, so they double as safe result-set keys.
_METRIC_EXPRESSIONS: dict[str, tuple[str, str]] = {
    "ventas": ("SUM(cantidad_ventas)", "total_ventas"),
    "clientes": ("SUM(cantidad_ventas)", "total_ventas"),
    "cantidad_ventas": ("SUM(cantidad_ventas)", "total_ventas"),
    "facturacion": ("SUM(ingresos_ventas_usd)", "total_ingresos"),
    "facturación": ("SUM(ingresos_ventas_usd)", "total_ingresos"),
    "ingresos": ("SUM(ingresos_ventas_usd)", "total_ingresos"),
    "leads": ("SUM(total_leads)", "total_leads"),
    "total_leads": ("SUM(total_leads)", "total_leads"),
    "gasto": ("SUM(google_ads_costo_usd + meta_ads_costo_usd)", "total_gasto"),
    "inversion": ("SUM(google_ads_costo_usd + meta_ads_costo_usd)", "total_gasto"),
    "inversión": ("SUM(google_ads_costo_usd + meta_ads_costo_usd)", "total_gasto"),
    "costo_total": ("SUM(google_ads_costo_usd + meta_ads_costo_usd)", "total_gasto"),
}


def build_sql(planner_result: PlannerResult) -> tuple[str, str]:
    """Build (sql, primary_metric_alias) from a PlannerResult.

    Picks a query template based on the matched keywords/hints:
    - "mejor"/"peor" + "mes" (anywhere in the text, not necessarily adjacent)
      -> monthly ranking, best or worst first
    - "mejor"/"peor" + "modelo" -> ranking by vehicle model
    - a metric concept + explicit series language (see _SERIES_KEYWORDS) or a
      CHART intent -> a daily series (one row per day)
    - a metric concept with no series/ranking language -> a single-row
      aggregate total (e.g. "¿cuántas ventas en total?" -> one SUM row, not
      547 daily rows)
    - fallback -> total row count and date range, so the tool always has
      something concrete to answer with instead of failing

    Direction (best/worst) is resolved by the *last* "mejor"/"peor" token in
    the text rather than a fixed phrase match. This matters for follow-ups:
    the engine's history-aware resolver (app.agent.engine._resolve_follow_up)
    prefixes a bare follow-up like "¿y cuál fue el peor?" with the prior
    turn's full question ("¿cuál fue el mejor mes?"), so the combined text
    contains both "mejor" and "peor" but the noun "mes" only once. A literal
    "peor mes" substring check would miss this and silently answer with the
    best month instead of the worst — using the last direction word fixes
    that without needing the noun to repeat.
    """
    text = planner_result.raw_text.lower()
    expression, alias = _resolve_primary_metric(planner_result)

    if "mes" in text:
        direction = _last_ranking_direction(text)
        if direction is not None:
            return _monthly_ranking_sql(expression, alias, ascending=direction == "peor"), alias
    if "modelo" in text:
        direction = _last_ranking_direction(text)
        if direction is not None:
            return _model_ranking_sql(ascending=direction == "peor"), "total_ventas"
    if planner_result.metrics or expression != _default_expression():
        if _wants_series(planner_result, text):
            return _daily_series_sql(expression, alias), alias
        return _total_sql(expression, alias), alias

    return _fallback_summary_sql(), "total_ventas"


def _wants_series(planner_result: PlannerResult, text: str) -> bool:
    """True when the user asked for a time series rather than one aggregate
    number: explicit series vocabulary in the text, or a CHART intent (a
    chart always needs multiple points to plot)."""
    if planner_result.intent == Intent.CHART:
        return True
    return any(keyword in text for keyword in _SERIES_KEYWORDS)


def _last_ranking_direction(text: str) -> str | None:
    """Return "mejor" or "peor" — whichever appears last in ``text`` — or
    None if neither appears. "Last" tracks the most recent user intent when
    a follow-up has been prefixed with the prior turn's question."""
    best_index = text.rfind("mejor")
    worst_index = text.rfind("peor")
    if best_index == -1 and worst_index == -1:
        return None
    return "peor" if worst_index > best_index else "mejor"


def build_channel_comparison_sql(metric: str = "costo") -> str:
    """Build a per-channel comparison query for google_ads vs meta_ads.

    ``metric`` selects which per-channel column pair to compare
    (impresiones/clics/costo/leads); defaults to cost since "gasto"/
    "inversión" comparisons are the most common comparison ask per the spec.
    """
    columns = []
    for channel in ADS_CHANNELS:
        column = CHANNEL_METRIC_COLUMNS[channel].get(metric)
        if column is None:
            continue
        columns.append(f"SUM({column}) AS {channel}_{metric}")

    if not columns:
        columns = [f"SUM({CHANNEL_METRIC_COLUMNS[channel]['costo']}) AS {channel}_costo" for channel in ADS_CHANNELS]

    select_clause = ", ".join(columns)
    return f"SELECT {select_clause} FROM {TABLE_NAME}"


def build_forecast_source_sql(value_column: str, lookback_days: int = 365) -> str:
    """Build the daily series query the forecast tools consume.

    Pulls the raw daily rows (not pre-aggregated) so ``forecast_*`` can build
    its own (ds, y) series; ``lookback_days`` bounds history to keep the
    result set reasonable on ~18 months of data.
    """
    return (
        f"SELECT {DATE_COLUMN} AS fecha, {value_column} "
        f"FROM {TABLE_NAME} "
        f"WHERE {DATE_COLUMN} >= DATE_SUB(CURDATE(), INTERVAL {int(lookback_days)} DAY) "
        f"ORDER BY {DATE_COLUMN}"
    )


def _resolve_primary_metric(planner_result: PlannerResult) -> tuple[str, str]:
    for concept in planner_result.metrics:
        if concept in _METRIC_EXPRESSIONS:
            return _METRIC_EXPRESSIONS[concept]
    return _default_expression(), _DEFAULT_METRIC_ALIAS


def _default_expression() -> str:
    return f"SUM({_DEFAULT_METRIC_EXPRESSION})"


def _daily_series_sql(expression: str, alias: str) -> str:
    return (
        f"SELECT {DATE_COLUMN} AS fecha, {expression} AS {alias} "
        f"FROM {TABLE_NAME} "
        f"GROUP BY {DATE_COLUMN} "
        f"ORDER BY {DATE_COLUMN}"
    )


def _total_sql(expression: str, alias: str) -> str:
    """Single-row aggregate over the whole table — no GROUP BY, so this
    always returns exactly one row (e.g. SUM(cantidad_ventas) = 6748)."""
    return f"SELECT {expression} AS {alias} FROM {TABLE_NAME}"


def _monthly_ranking_sql(expression: str, alias: str, *, ascending: bool) -> str:
    direction = "ASC" if ascending else "DESC"
    return (
        f"SELECT DATE_FORMAT({DATE_COLUMN}, '%Y-%m') AS periodo, {expression} AS {alias} "
        f"FROM {TABLE_NAME} "
        f"GROUP BY DATE_FORMAT({DATE_COLUMN}, '%Y-%m') "
        f"ORDER BY {alias} {direction} "
        f"LIMIT 12"
    )


def _model_ranking_sql(*, ascending: bool) -> str:
    direction = "ASC" if ascending else "DESC"
    return (
        "SELECT vehiculo_modelo_principal, SUM(cantidad_ventas) AS total_ventas "
        f"FROM {TABLE_NAME} "
        "WHERE vehiculo_modelo_principal IS NOT NULL "
        "GROUP BY vehiculo_modelo_principal "
        f"ORDER BY total_ventas {direction} "
        "LIMIT 10"
    )


def _fallback_summary_sql() -> str:
    return (
        "SELECT COUNT(*) AS total_registros, MIN(fecha) AS desde, MAX(fecha) AS hasta, "
        "SUM(cantidad_ventas) AS total_ventas "
        f"FROM {TABLE_NAME}"
    )
