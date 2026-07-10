"""Assert-based tests for the SQL security guard (the critical invariant)."""

from app.security.sql_guard import SqlValidationError, validate_sql


def _assert_rejected(query: str) -> None:
    try:
        validate_sql(query)
    except SqlValidationError:
        return
    raise AssertionError(f"Expected SqlValidationError for: {query!r}")


def test_valid_select_passes() -> None:
    validate_sql(
        "SELECT fecha, SUM(cantidad_ventas) AS ventas "
        "FROM metricas_campanas_ventas "
        "WHERE fecha >= '2025-01-01' "
        "GROUP BY fecha ORDER BY fecha"
    )


def test_select_star_passes() -> None:
    validate_sql("SELECT * FROM metricas_campanas_ventas LIMIT 10")


def test_drop_table_rejected() -> None:
    _assert_rejected("DROP TABLE metricas_campanas_ventas")


def test_update_rejected() -> None:
    _assert_rejected("UPDATE metricas_campanas_ventas SET cantidad_ventas = 0")


def test_delete_rejected() -> None:
    _assert_rejected("DELETE FROM metricas_campanas_ventas")


def test_insert_rejected() -> None:
    _assert_rejected("INSERT INTO metricas_campanas_ventas (fecha) VALUES ('2025-01-01')")


def test_other_table_rejected() -> None:
    _assert_rejected("SELECT * FROM usuarios")


def test_subquery_on_other_table_rejected() -> None:
    _assert_rejected(
        "SELECT fecha FROM metricas_campanas_ventas "
        "WHERE fecha IN (SELECT fecha FROM otra_tabla)"
    )


def test_unknown_column_rejected() -> None:
    _assert_rejected("SELECT password FROM metricas_campanas_ventas")


def test_multiple_statements_rejected() -> None:
    _assert_rejected(
        "SELECT fecha FROM metricas_campanas_ventas; DROP TABLE metricas_campanas_ventas"
    )


def test_sleep_rejected() -> None:
    _assert_rejected("SELECT SLEEP(5) FROM metricas_campanas_ventas")


def test_benchmark_rejected() -> None:
    _assert_rejected("SELECT BENCHMARK(1000000, MD5('x')) FROM metricas_campanas_ventas")


def test_load_file_rejected() -> None:
    _assert_rejected("SELECT LOAD_FILE('/etc/passwd')")


def test_into_outfile_rejected() -> None:
    _assert_rejected(
        "SELECT * FROM metricas_campanas_ventas INTO OUTFILE '/tmp/dump.csv'"
    )


def test_into_dumpfile_rejected() -> None:
    _assert_rejected("SELECT * FROM metricas_campanas_ventas INTO DUMPFILE '/tmp/dump'")


def test_get_lock_rejected() -> None:
    _assert_rejected("SELECT GET_LOCK('lock_name', 10) FROM metricas_campanas_ventas")


def test_unlisted_function_rejected() -> None:
    _assert_rejected("SELECT UUID() FROM metricas_campanas_ventas")


def test_allowed_aggregate_functions_pass() -> None:
    validate_sql(
        "SELECT ROUND(AVG(cantidad_ventas), 2) AS promedio, "
        "COUNT(*) AS total, MIN(fecha) AS desde, MAX(fecha) AS hasta "
        "FROM metricas_campanas_ventas"
    )


def test_curdate_bounded_lookback_passes() -> None:
    """CURDATE()/CURRENT_DATE() is zero-argument and used to bound forecast
    lookback windows (app.agent.sql_builder.build_forecast_source_sql)."""
    validate_sql(
        "SELECT fecha, cantidad_ventas FROM metricas_campanas_ventas "
        "WHERE fecha >= DATE_SUB(CURDATE(), INTERVAL 365 DAY) ORDER BY fecha"
    )


def test_allowed_date_functions_pass() -> None:
    validate_sql(
        "SELECT YEAR(fecha) AS anio, MONTH(fecha) AS mes, "
        "DATE_FORMAT(fecha, '%Y-%m') AS periodo, "
        "SUM(cantidad_ventas) AS ventas "
        "FROM metricas_campanas_ventas "
        "GROUP BY YEAR(fecha), MONTH(fecha), DATE_FORMAT(fecha, '%Y-%m')"
    )
