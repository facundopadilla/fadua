"""Tests for app.agent.sql_builder — focused on the total-vs-series split
(Bug 1: a plain "en total" question must not return a 547-row daily series).
"""

from app.agent.sql_builder import build_sql
from app.planner.planner import classify
from app.schemas.chat import Intent
from app.security.sql_guard import validate_sql


def test_plain_total_question_returns_single_row_aggregate() -> None:
    """"¿Cuántas ventas hubo en total?" must aggregate to one row, not a
    per-day GROUP BY series."""
    planner_result = classify("¿Cuántas ventas hubo en total?")
    sql, alias = build_sql(planner_result)

    assert "GROUP BY" not in sql
    assert "SUM(cantidad_ventas)" in sql
    assert alias == "total_ventas"
    validate_sql(sql)  # must still pass the security guard


def test_plain_total_question_without_en_total_still_aggregates() -> None:
    """The default for a bare data question ("¿cuántas ventas hubo?", no
    series/ranking language) is the aggregate total, not a daily series."""
    planner_result = classify("¿Cuántas ventas hubo?")
    sql, _alias = build_sql(planner_result)

    assert "GROUP BY" not in sql
    validate_sql(sql)


def test_evolution_question_still_returns_daily_series() -> None:
    """"Mostrame la evolución de ingresos" must NOT be over-corrected into a
    total — explicit series language keeps the daily GROUP BY series."""
    planner_result = classify("Mostrame la evolución de ingresos")
    sql, _alias = build_sql(planner_result)

    assert "GROUP BY fecha" in sql
    assert "SUM(ingresos_ventas_usd)" in sql
    validate_sql(sql)


def test_chart_intent_forces_series_even_without_series_words() -> None:
    """A CHART intent always needs multiple points to plot, even if the text
    itself has no explicit series keyword (e.g. "graficá el total de ventas")."""
    planner_result = classify("Graficá las ventas")
    assert planner_result.intent == Intent.CHART

    sql, _alias = build_sql(planner_result)
    assert "GROUP BY fecha" in sql
    validate_sql(sql)


def test_best_month_ranking_is_unaffected_by_the_total_fix() -> None:
    """"mes" appears in "¿cuál fue el mejor mes?" but must still hit the
    monthly ranking branch, not the new total/series branch."""
    planner_result = classify("¿Cuál fue el mejor mes?")
    sql, _alias = build_sql(planner_result)

    assert "DATE_FORMAT" in sql
    assert "periodo" in sql
    assert "ORDER BY" in sql and "DESC" in sql
    validate_sql(sql)


def test_facturacion_total_uses_ingresos_expression() -> None:
    planner_result = classify("Dame el total de facturación")
    sql, alias = build_sql(planner_result)

    assert "GROUP BY" not in sql
    assert "SUM(ingresos_ventas_usd)" in sql
    assert alias == "total_ingresos"
    validate_sql(sql)
