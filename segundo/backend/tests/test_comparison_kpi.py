"""Tests for Bug 2: a named KPI inside a comparative question must be
answered as that KPI, not silently defaulted to a cost comparison.

test_named_kpi_routing is a pure unit test (no DB). The
test_roas_vs_comparison_answers_roas_not_cost case hits the live MySQL
instance (see app/config.py default database_url), matching how this
project's other integration-shaped checks already run against the seeded
``metricas_campanas_ventas`` table.
"""

import asyncio

from app.agent.engine import AnalyticsEngine, _find_named_kpi
from app.planner.planner import classify
from app.schemas.chat import ChatRequest, Intent


def test_find_named_kpi_detects_roas_in_comparative_text() -> None:
    assert _find_named_kpi("¿Cuál fue el ROAS de Google Ads vs Meta Ads?") == "roas"


def test_find_named_kpi_returns_none_when_no_kpi_named() -> None:
    assert _find_named_kpi("Compará Google Ads con Meta Ads") is None


def test_find_named_kpi_detects_ctr_as_channel_splittable() -> None:
    from app.agent.engine import _CHANNEL_SPLITTABLE_KPIS

    assert _find_named_kpi("Comparemos el CTR entre canales") == "ctr"
    assert "ctr" in _CHANNEL_SPLITTABLE_KPIS


def test_roas_comparison_is_classified_as_comparison_intent() -> None:
    """Confirms the planner still routes this to COMPARISON (documenting the
    pre-existing classification the engine has to recover from) rather than
    silently changing planner behavior."""
    planner_result = classify("¿Cuál fue el ROAS de Google Ads vs Meta Ads?")
    assert planner_result.intent == Intent.COMPARISON


def test_roas_vs_comparison_answers_roas_not_cost() -> None:
    """End-to-end: the engine must answer ROAS, and the answer/metrics must
    not be a silent cost comparison (google_ads/meta_ads cost keys)."""
    engine = AnalyticsEngine()
    request = ChatRequest(message="¿Cuál fue el ROAS de Google Ads vs Meta Ads?")

    async def _run() -> tuple[str, dict[str, float]]:
        final_answer = ""
        final_metrics: dict[str, float] = {}
        async for kind, payload in engine.stream(request, "test-conv"):
            if kind == "done":
                final_answer = payload.answer
                final_metrics = payload.metrics
        return final_answer, final_metrics

    answer, metrics = asyncio.run(_run())

    assert "ROAS" in answer
    assert "roas" in metrics
    # The pre-fix bug answered a cost comparison instead — guard against
    # regressing back to that instead of the named KPI.
    assert "Comparación de costo entre canales" not in answer
