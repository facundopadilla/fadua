"""Tests for the LLM tool-calling agent module (app.agent.llm_agent).

There is no LLM API key in this environment (settings.llm_api_key == ""), so
none of these tests make a real LLM/network call. They cover the pieces that
don't require one: the plain-dict -> ModelMessage history converter, the
per-request deps collector's isolation, the tool wrappers' delegation to the
real app.tools functions, and — most importantly — that run_sql's wrapper
never lets an invalid query reach the database unhandled, protecting the
security invariant that the LLM can only ever reach MySQL through
app.tools.execute_sql.

Mirrors this repo's existing test conventions (see test_comparison_kpi.py,
test_sql_guard.py): plain assert-based functions, no pytest fixtures, async
calls driven via asyncio.run(...) inline.
"""

from __future__ import annotations

import asyncio

from pydantic_ai import ModelRequest, ModelResponse, RunContext, TextPart, UserPromptPart

from app.agent.llm_agent import (
    LlmToolDeps,
    _infer_intent,
    _maybe_build_auto_chart,
    _score_llm_run,
    _to_model_messages,
    _wants_chart,
    compute_kpis,
    make_chart,
    run_sql,
)
from app.schemas.chat import ChartConfig, Intent


def _run_context(deps: LlmToolDeps) -> RunContext[LlmToolDeps]:
    """Build a minimal RunContext good enough to drive a @agent.tool function
    directly in a unit test, without a real Agent run.

    RunContext is a kw_only dataclass; ``model``/``usage`` have no defaults
    upstream but are never touched by any of the tool wrappers under test
    (they only read ``ctx.deps``), so passing type: ignore placeholders here
    is safe and avoids constructing a real Model/RunUsage just for a test.
    """
    return RunContext(deps=deps, model=None, usage=None)  # type: ignore[arg-type]


# --- _to_model_messages -------------------------------------------------


def test_to_model_messages_empty_history_returns_empty_list() -> None:
    assert _to_model_messages([]) == []


def test_to_model_messages_converts_user_and_assistant_roles() -> None:
    history = [
        {"role": "user", "content": "¿Cuántas ventas hubo?"},
        {"role": "assistant", "content": "Hubo 6.748 ventas en total."},
    ]
    messages = _to_model_messages(history)

    assert len(messages) == 2
    assert isinstance(messages[0], ModelRequest)
    assert isinstance(messages[0].parts[0], UserPromptPart)
    assert messages[0].parts[0].content == "¿Cuántas ventas hubo?"
    assert isinstance(messages[1], ModelResponse)
    assert isinstance(messages[1].parts[0], TextPart)
    assert messages[1].parts[0].content == "Hubo 6.748 ventas en total."


def test_to_model_messages_skips_unknown_roles_and_empty_content() -> None:
    history = [
        {"role": "system", "content": "should be skipped"},
        {"role": "user", "content": ""},
        {"role": "user", "content": "pregunta real"},
    ]
    messages = _to_model_messages(history)

    assert len(messages) == 1
    assert messages[0].parts[0].content == "pregunta real"


# --- LlmToolDeps isolation -------------------------------------------------


def test_llm_tool_deps_fresh_instances_do_not_share_state() -> None:
    """Concurrent-request safety: two deps instances must never leak fields
    into each other — this is a correctness requirement, not just style."""
    deps_a = LlmToolDeps()
    deps_b = LlmToolDeps()

    deps_a.last_sql = "SELECT 1"
    deps_a.last_metrics["roas"] = 3.5

    assert deps_b.last_sql is None
    assert deps_b.last_metrics == {}


# --- run_sql wrapper --------------------------------------------------------


def test_run_sql_rejects_invalid_query_without_raising() -> None:
    """The single most important security-adjacent test in this module:
    run_sql must never let a SqlValidationError propagate and kill the
    agent run, and it must never touch the database for a rejected query."""
    deps = LlmToolDeps()
    ctx = _run_context(deps)

    result = asyncio.run(run_sql(ctx, "DROP TABLE metricas_campanas_ventas"))

    assert isinstance(result, str)
    assert deps.last_sql is None
    assert deps.any_tool_failed is True
    assert deps.any_tool_succeeded is False


def test_run_sql_rejects_unauthorized_table_without_raising() -> None:
    deps = LlmToolDeps()
    ctx = _run_context(deps)

    result = asyncio.run(run_sql(ctx, "SELECT * FROM usuarios"))

    assert isinstance(result, str)
    assert deps.any_tool_failed is True


def test_run_sql_valid_query_stores_sql_and_returns_rows() -> None:
    """Integration-shaped: hits the live seeded MySQL instance, matching how
    other tests in this repo (test_comparison_kpi.py) exercise real queries."""
    deps = LlmToolDeps()
    ctx = _run_context(deps)

    result = asyncio.run(run_sql(ctx, "SELECT SUM(cantidad_ventas) AS total_ventas FROM metricas_campanas_ventas"))

    assert isinstance(result, list)
    assert deps.last_sql == "SELECT SUM(cantidad_ventas) AS total_ventas FROM metricas_campanas_ventas"
    assert deps.any_tool_succeeded is True


def test_run_sql_valid_query_also_stores_rows_for_auto_chart_safety_net() -> None:
    """deps.last_rows must be populated on success — this is what
    _maybe_build_auto_chart reads to build a chart the model forgot to
    request itself (see the auto-chart tests below)."""
    deps = LlmToolDeps()
    ctx = _run_context(deps)

    result = asyncio.run(run_sql(ctx, "SELECT fecha, cantidad_ventas FROM metricas_campanas_ventas ORDER BY fecha"))

    assert deps.last_rows == result


def test_run_sql_rejected_query_does_not_populate_last_rows() -> None:
    deps = LlmToolDeps()
    ctx = _run_context(deps)

    asyncio.run(run_sql(ctx, "DROP TABLE metricas_campanas_ventas"))

    assert deps.last_rows is None


# --- compute_kpis wrapper ----------------------------------------------------


def test_compute_kpis_merges_into_deps_without_overwriting() -> None:
    deps = LlmToolDeps()
    ctx = _run_context(deps)
    deps.last_metrics["preexisting"] = 1.0

    rows = [
        {"google_ads_costo_usd": 100.0, "meta_ads_costo_usd": 50.0, "google_ads_clics": 10, "meta_ads_clics": 5}
    ]
    result = asyncio.run(compute_kpis(ctx, rows))

    assert "cpc" in result
    assert deps.last_metrics["preexisting"] == 1.0  # not clobbered
    assert "cpc" in deps.last_metrics  # new metrics merged in


def test_compute_kpis_empty_rows_returns_empty_dict() -> None:
    deps = LlmToolDeps()
    ctx = _run_context(deps)

    result = asyncio.run(compute_kpis(ctx, []))

    assert result == {}
    assert deps.any_tool_succeeded is False


# --- make_chart wrapper -------------------------------------------------


def test_make_chart_stores_chart_in_deps_and_returns_dict() -> None:
    deps = LlmToolDeps()
    ctx = _run_context(deps)

    rows = [
        {"fecha": "2025-01-01", "total_ventas": 10},
        {"fecha": "2025-01-02", "total_ventas": 20},
    ]
    result = asyncio.run(make_chart(ctx, rows, intent_hint="sql"))

    assert result is not None
    assert deps.last_chart is not None
    assert deps.any_tool_succeeded is True


def test_make_chart_empty_rows_returns_none() -> None:
    deps = LlmToolDeps()
    ctx = _run_context(deps)

    result = asyncio.run(make_chart(ctx, [], intent_hint="sql"))

    assert result is None
    assert deps.last_chart is None


# --- _wants_chart -----------------------------------------------------------


def test_wants_chart_detects_grafico_keyword() -> None:
    assert _wants_chart("haceme un gráfico de precios") is True


def test_wants_chart_detects_unaccented_variant() -> None:
    """Users often skip accents typing casually — 'grafico'/'evolucion'
    without the tilde must still match, not just the accented spelling."""
    assert _wants_chart("hazme un grafico de precios") is True
    assert _wants_chart("mostrame la evolucion de ingresos") is True


def test_wants_chart_detects_oscilar_and_tendencia() -> None:
    assert _wants_chart("como fue oscilando el precio de las campañas") is True
    assert _wants_chart("cuál es la tendencia de ventas") is True


def test_wants_chart_detects_visualiz_and_mostrame() -> None:
    assert _wants_chart("quiero una visualización de los datos") is True
    assert _wants_chart("mostrame las ventas por mes") is True


def test_wants_chart_plain_question_returns_false() -> None:
    assert _wants_chart("¿cuántas ventas hubo en total?") is False
    assert _wants_chart("¿cuál fue el ROAS?") is False


# --- _maybe_build_auto_chart --------------------------------------------


def test_auto_chart_builds_when_user_asked_and_model_forgot() -> None:
    """The core safety-net case this fix exists for: model called run_sql,
    never called make_chart, but the user clearly asked for a chart."""
    deps = LlmToolDeps()
    deps.last_rows = [
        {"fecha": "2025-01-01", "google_ads_costo_usd": 100.0},
        {"fecha": "2025-01-02", "google_ads_costo_usd": 120.0},
        {"fecha": "2025-01-03", "google_ads_costo_usd": 90.0},
    ]

    _maybe_build_auto_chart("mostrame como fue oscilando el precio de las campañas", deps)

    assert deps.last_chart is not None
    assert isinstance(deps.last_chart, ChartConfig)
    assert deps.any_tool_succeeded is True


def test_auto_chart_does_not_override_existing_chart() -> None:
    """If the model DID call make_chart, the safety net must never clobber
    that chart with its own — the model's chart_type/title choices win."""
    deps = LlmToolDeps()
    deps.last_rows = [
        {"fecha": "2025-01-01", "google_ads_costo_usd": 100.0},
        {"fecha": "2025-01-02", "google_ads_costo_usd": 120.0},
    ]
    existing = ChartConfig(type="bar", data=[{"x": 1}], x_key="x", y_keys=["x"])
    deps.last_chart = existing

    _maybe_build_auto_chart("mostrame un gráfico de precios", deps)

    assert deps.last_chart is existing


def test_auto_chart_skips_single_row_total() -> None:
    """A single-row total is never worth plotting — mirrors the len(rows) > 1
    guards app.agent.engine already applies for the deterministic path."""
    deps = LlmToolDeps()
    deps.last_rows = [{"total_ventas": 6748}]

    _maybe_build_auto_chart("hazme un gráfico de las ventas totales", deps)

    assert deps.last_chart is None


def test_auto_chart_skips_when_message_does_not_ask_for_chart() -> None:
    """No chart keyword in the message -> never auto-build, even with a
    perfectly chartable multi-row result (e.g. a plain SQL rows request)."""
    deps = LlmToolDeps()
    deps.last_rows = [
        {"fecha": "2025-01-01", "cantidad_ventas": 10},
        {"fecha": "2025-01-02", "cantidad_ventas": 20},
    ]

    _maybe_build_auto_chart("obtené las primeras 5 filas de la tabla", deps)

    assert deps.last_chart is None


def test_auto_chart_skips_when_no_rows_available() -> None:
    deps = LlmToolDeps()
    deps.last_rows = None

    _maybe_build_auto_chart("mostrame un gráfico de precios", deps)

    assert deps.last_chart is None


def test_auto_chart_skips_when_no_numeric_column() -> None:
    """create_chart itself returns None for rows with no numeric column;
    _maybe_build_auto_chart must stay conservative and respect that."""
    deps = LlmToolDeps()
    deps.last_rows = [
        {"vehiculo_modelo_principal": "Corolla"},
        {"vehiculo_modelo_principal": "Civic"},
    ]

    _maybe_build_auto_chart("mostrame un gráfico de los modelos", deps)

    assert deps.last_chart is None


# --- _infer_intent / _score_llm_run ------------------------------------


def test_infer_intent_no_tool_activity_is_conversation() -> None:
    assert _infer_intent(LlmToolDeps()) == Intent.CONVERSATION


def test_infer_intent_chart_present_is_chart() -> None:
    deps = LlmToolDeps()
    deps.last_chart = object()  # type: ignore[assignment] - only presence matters here
    assert _infer_intent(deps) == Intent.CHART


def test_infer_intent_metrics_without_chart_is_kpi() -> None:
    deps = LlmToolDeps()
    deps.last_metrics["roas"] = 2.0
    assert _infer_intent(deps) == Intent.KPI


def test_infer_intent_sql_only_is_sql() -> None:
    deps = LlmToolDeps()
    deps.last_sql = "SELECT 1"
    assert _infer_intent(deps) == Intent.SQL


def test_score_llm_run_never_self_reported_by_model() -> None:
    """Confidence must always be execution-derived — these three deps states
    are the only signals _score_llm_run is allowed to use."""
    no_activity = LlmToolDeps()
    assert _score_llm_run(no_activity) == 0.9

    succeeded = LlmToolDeps()
    succeeded.any_tool_succeeded = True
    assert _score_llm_run(succeeded) == 1.0

    only_failed = LlmToolDeps()
    only_failed.any_tool_failed = True
    assert _score_llm_run(only_failed) == 0.3
