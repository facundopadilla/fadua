"""Tests for app.agent.templates — natural wording for totals and rankings
(Quality 3: no more "Encontré N registros" for these two cases)."""

from app.agent.templates import render_sql_answer


def test_total_row_renders_natural_sentence() -> None:
    rows = [{"total_ventas": 6748}]
    answer = render_sql_answer(rows, "SELECT SUM(cantidad_ventas) AS total_ventas FROM metricas_campanas_ventas")

    assert answer == "Hubo 6.748 ventas en total."


def test_currency_total_row_renders_natural_sentence() -> None:
    rows = [{"total_ingresos": 1234567.5}]
    answer = render_sql_answer(
        rows, "SELECT SUM(ingresos_ventas_usd) AS total_ingresos FROM metricas_campanas_ventas"
    )

    assert answer.startswith("La facturación total fue USD")
    assert "1.234.567,50" in answer


def test_monthly_ranking_names_the_best_month_only() -> None:
    rows = [
        {"periodo": "2026-05", "total_ventas": 448},
        {"periodo": "2026-03", "total_ventas": 401},
    ]
    sql = (
        "SELECT DATE_FORMAT(fecha, '%Y-%m') AS periodo, SUM(cantidad_ventas) AS total_ventas "
        "FROM metricas_campanas_ventas GROUP BY DATE_FORMAT(fecha, '%Y-%m') "
        "ORDER BY total_ventas DESC LIMIT 12"
    )
    answer = render_sql_answer(rows, sql)

    assert answer == "El mejor mes fue 2026-05 con 448 ventas."
    assert "2026-03" not in answer  # names the winner only, not the full list


def test_monthly_ranking_with_no_metric_named_uses_ventas_noun() -> None:
    """"¿Cuál fue el mejor mes?" names no metric concept, so
    app.agent.sql_builder falls back to the default alias "cantidad_ventas"
    (not "total_ventas"). That alias must still read as "ventas", not the
    literal "cantidad ventas" (regression: this was wrong until the noun
    lookup covered the default alias too)."""
    rows = [
        {"periodo": "2026-05", "cantidad_ventas": 448},
        {"periodo": "2026-06", "cantidad_ventas": 436},
    ]
    sql = (
        "SELECT DATE_FORMAT(fecha, '%Y-%m') AS periodo, SUM(cantidad_ventas) AS cantidad_ventas "
        "FROM metricas_campanas_ventas GROUP BY DATE_FORMAT(fecha, '%Y-%m') "
        "ORDER BY cantidad_ventas DESC LIMIT 12"
    )
    answer = render_sql_answer(rows, sql)

    assert answer == "El mejor mes fue 2026-05 con 448 ventas."


def test_monthly_ranking_names_the_worst_month_for_ascending_order() -> None:
    rows = [
        {"periodo": "2026-01", "total_ventas": 120},
        {"periodo": "2026-02", "total_ventas": 300},
    ]
    sql = (
        "SELECT DATE_FORMAT(fecha, '%Y-%m') AS periodo, SUM(cantidad_ventas) AS total_ventas "
        "FROM metricas_campanas_ventas GROUP BY DATE_FORMAT(fecha, '%Y-%m') "
        "ORDER BY total_ventas ASC LIMIT 12"
    )
    answer = render_sql_answer(rows, sql)

    assert answer == "El peor mes fue 2026-01 con 120 ventas."


def test_daily_series_keeps_the_generic_multi_row_wording() -> None:
    """Regression guard: a real daily series (not a ranking, not a total)
    must keep the existing "Encontré N registros" preview, since that case
    is out of scope for the Quality 3 fix."""
    rows = [{"fecha": "2026-01-01", "total_ventas": 6}, {"fecha": "2026-01-02", "total_ventas": 14}]
    sql = "SELECT fecha AS fecha, SUM(cantidad_ventas) AS total_ventas FROM metricas_campanas_ventas GROUP BY fecha"
    answer = render_sql_answer(rows, sql)

    assert answer.startswith("Encontré 2 registros")
