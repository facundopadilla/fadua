"""Tests for app.tools.calculate_kpis — a KPI must be OMITTED (not zeroed)
when its required input columns are missing from the rows, per CLAUDE.md
invariant #3 and the KPI table. Covers the bug where an aggregated query
like ``SELECT SUM(cantidad_ventas), SUM(ingresos_ventas_usd) ...`` (no cost
columns) must never surface ``costo_total: 0`` / ``ingresos_totales: 0``.
"""

from app.tools.calculate_kpis import calculate_kpis


def test_empty_rows_returns_empty_metrics() -> None:
    assert calculate_kpis([]) == {}


def test_sales_count_query_omits_cost_and_income_keys() -> None:
    """Rows from a plain ``SELECT SUM(cantidad_ventas) AS total_ventas``
    query (no cost/income columns at all, and under a non-canonical alias)
    must not produce any metric — nothing recognizable was present."""
    rows = [{"total_ventas": 6748}]

    metrics = calculate_kpis(rows)

    assert metrics == {}
    assert "costo_total" not in metrics
    assert "ingresos_totales" not in metrics


def test_income_present_without_cost_columns_omits_only_cost_derived_keys() -> None:
    """Rows carrying ``ingresos_ventas_usd`` but no
    ``google_ads_costo_usd``/``meta_ads_costo_usd`` must still report
    ``ingresos_totales`` (it was genuinely computed) while omitting every
    KPI that needs cost as an input — never emitting those as 0."""
    rows = [{"cantidad_ventas": 6748, "ingresos_ventas_usd": 200_371_822.08}]

    metrics = calculate_kpis(rows)

    assert metrics == {"ingresos_totales": 200_371_822.08}
    assert "costo_total" not in metrics
    assert "roas" not in metrics
    assert "cpa" not in metrics
    assert "roi" not in metrics
    assert "costo_por_venta" not in metrics


def test_cost_present_without_income_omits_roas_and_roi_but_keeps_costo_total() -> None:
    rows = [
        {
            "google_ads_costo_usd": 500.0,
            "meta_ads_costo_usd": 300.0,
            "google_ads_clics": 100,
            "meta_ads_clics": 50,
        }
    ]

    metrics = calculate_kpis(rows)

    assert metrics["costo_total"] == 800.0
    assert metrics["cpc"] == round(800.0 / 150.0, 4)
    assert "ingresos_totales" not in metrics
    assert "roas" not in metrics
    assert "roi" not in metrics


def test_full_columns_computes_complete_kpi_set_no_regression() -> None:
    """The real KPI path (ROAS etc.) over full-column rows must keep
    working unchanged — this is the happy path CLAUDE.md's KPI table
    describes, and must not be broken by the omission fix."""
    rows = [
        {
            "google_ads_impresiones": 1_000_000,
            "google_ads_clics": 20_000,
            "google_ads_costo_usd": 800_000.0,
            "google_ads_leads": 30_000,
            "meta_ads_impresiones": 500_000,
            "meta_ads_clics": 10_000,
            "meta_ads_costo_usd": 500_255.92,
            "meta_ads_leads": 28_436,
            "total_leads": 58_436,
            "cantidad_ventas": 6_748,
            "ingresos_ventas_usd": 200_371_822.08,
        }
    ]

    metrics = calculate_kpis(rows)

    for key in ("ctr", "cpc", "cpl", "cpa", "roas", "roi", "conversion_rate", "costo_total",
                "ingresos_totales", "costo_por_venta"):
        assert key in metrics, f"expected {key} in full-column KPI result"

    assert metrics["costo_total"] == 1_300_255.92
    assert metrics["ingresos_totales"] == 200_371_822.08
    assert round(metrics["roas"], 2) == 154.10


def test_zero_denominator_is_omitted_not_returned_as_zero_or_inf() -> None:
    """Zero clics with cost present must omit cpc entirely (division by
    zero is a missing-signal case, not a fabricated 0.0 or inf)."""
    rows = [{"google_ads_costo_usd": 100.0, "meta_ads_costo_usd": 0.0, "google_ads_clics": 0, "meta_ads_clics": 0}]

    metrics = calculate_kpis(rows)

    assert metrics["costo_total"] == 100.0
    assert "cpc" not in metrics


def test_genuinely_zero_cost_is_a_real_value_not_an_omission() -> None:
    """A real column that sums to 0 (e.g. a free/organic period with no ad
    spend) is a legitimate computed value, not a missing-column case — it
    must be reported as costo_total: 0.0, distinguishing 'present but zero'
    from 'absent'."""
    rows = [{"google_ads_costo_usd": 0.0, "meta_ads_costo_usd": 0.0, "cantidad_ventas": 10}]

    metrics = calculate_kpis(rows)

    assert metrics["costo_total"] == 0.0
    # cpa needs ventas != 0 which holds, but costo_total == 0 is a valid
    # numerator for cpa (0 cost, real sales) — cpa is a ratio costo/ventas,
    # not gated on costo_total != 0, only on ventas != 0.
    assert metrics["cpa"] == 0.0


def test_multiple_rows_sum_across_rows_not_row_by_row_average() -> None:
    rows = [
        {"cantidad_ventas": 10, "ingresos_ventas_usd": 1000.0},
        {"cantidad_ventas": 20, "ingresos_ventas_usd": 2000.0},
    ]

    metrics = calculate_kpis(rows)

    assert metrics["ingresos_totales"] == 3000.0
    assert "costo_total" not in metrics
