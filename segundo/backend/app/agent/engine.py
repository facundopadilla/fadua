"""Real analytics agent engine — replaces app.agent.stub.StubAgent.

Preserves the exact streaming interface the stub established so
``api/chat.py`` keeps working unmodified: ``stream(request, conversation_id)``
yields ("token", str) chunks, then exactly one ("done", ChatResponse).

Flow (CLAUDE.md architecture): planner -> tool(s) -> ChatResponse. The
answer text is always a deterministic template over real tool data first
(``app.agent.templates``); ``app.agent.llm_hook`` optionally rewords that
text through an LLM afterwards, never replacing it with invented content.
Word-by-word streaming happens over whichever text is final (template or
LLM-reworded), so the SSE contract is identical either way.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Literal

from app.agent import confidence, templates
from app.agent.llm_agent import LlmRunFailed, LlmRunOutcome, stream_llm_response
from app.agent.llm_hook import maybe_reword
from app.agent.sql_builder import build_channel_comparison_sql, build_forecast_source_sql, build_sql
from app.config import settings
from app.planner.planner import PlannerResult, classify
from app.schemas.chat import ChartConfig, ChatRequest, ChatResponse, Intent
from app.semantics.dictionary import ADS_CHANNELS, TABLE_NAME
from app.tools import (
    SqlExecutionError,
    calculate_kpis,
    create_chart,
    execute_sql,
    forecast_income,
    forecast_leads,
    forecast_sales,
)
from app.security.sql_guard import SqlValidationError

logger = logging.getLogger(__name__)

StreamEvent = tuple[Literal["token"], str] | tuple[Literal["done"], ChatResponse]

_FORECAST_METRIC_MAP = {
    "leads": ("total_leads", forecast_leads, "leads"),
    "ingresos": ("ingresos_ventas_usd", forecast_income, "ingresos"),
    "facturacion": ("ingresos_ventas_usd", forecast_income, "ingresos"),
    "facturación": ("ingresos_ventas_usd", forecast_income, "ingresos"),
}
_DEFAULT_FORECAST = ("cantidad_ventas", forecast_sales, "ventas")

# Text keyword -> canonical calculate_kpis() key, checked in this order so a
# more specific phrase ("costo por lead") is not shadowed by a shorter one.
# Every key here must exist in app.tools.calculate_kpis output and in
# app.agent.templates._KPI_LABELS.
_NAMED_KPI_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("tasa de conversión", "conversion_rate"),
    ("tasa de conversion", "conversion_rate"),
    ("conversion rate", "conversion_rate"),
    ("costo por venta", "costo_por_venta"),
    ("costo por lead", "cpl"),
    ("costo por clic", "cpc"),
    ("roas", "roas"),
    ("roi", "roi"),
    ("ctr", "ctr"),
    ("cpc", "cpc"),
    ("cpl", "cpl"),
    ("cpa", "cpa"),
)

# KPIs computable per channel: their inputs (impresiones/clics/costo) all
# exist as separate google_ads_*/meta_ads_* columns. ROAS/CPA/CPL/ROI/
# conversion_rate are NOT here on purpose — cantidad_ventas, total_leads and
# ingresos_ventas_usd are single combined columns in the schema
# (db/init.sql), never attributed to one channel, so a per-channel split for
# those would have to invent a revenue/sales breakdown that does not exist
# in the data. Answering the named KPI over the whole dataset (see
# _handle_comparison) is the honest option for that case.
_CHANNEL_SPLITTABLE_KPIS = frozenset({"ctr", "cpc"})


class AnalyticsEngine:
    """Real engine: deterministic planner + controlled tools + templated prose."""

    async def stream(
        self,
        request: ChatRequest,
        conversation_id: str,
        history: list[dict] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        started = time.perf_counter()

        try:
            answer, sql, chart, metrics, conf, intent = await self._build_response(
                request, history or []
            )
        except Exception as error:  # noqa: BLE001 - never let an unhandled tool error break SSE
            answer = (
                "Ocurrió un error al procesar la consulta. Por favor, intentá "
                "reformular la pregunta o probá nuevamente en unos minutos."
            )
            sql, chart, metrics = None, None, {}
            intent = Intent.CONVERSATION
            conf = confidence.fallback_score(intent)
            _ = error  # error detail intentionally not leaked to the user-facing answer

        for index, word in enumerate(answer.split(" ")):
            yield ("token", word if index == 0 else f" {word}")

        yield (
            "done",
            ChatResponse(
                conversation_id=conversation_id,
                answer=answer,
                sql=sql,
                chart=chart,
                metrics=metrics,
                suggestions=templates.default_suggestions(intent),
                execution_time=time.perf_counter() - started,
                confidence=conf,
            ),
        )

    async def _build_response(
        self, request: ChatRequest, history: list[dict]
    ) -> tuple[str, str | None, ChartConfig | None, dict[str, float], float, Intent]:
        if settings.llm_api_key:
            llm_result = await self._try_llm_response(request, history)
            if llm_result is not None:
                logger.info("Served by: llm_agent")
                return llm_result

        logger.info("Served by: template_planner")
        return await self._build_deterministic_response(request, history)

    async def _try_llm_response(
        self, request: ChatRequest, history: list[dict]
    ) -> tuple[str, str | None, ChartConfig | None, dict[str, float], float, Intent] | None:
        """Attempt the LLM tool-calling path; return None on ANY failure so
        the caller falls through to the deterministic path unchanged.

        Broad ``except Exception`` is deliberate here (network errors, model
        API errors, a provider that doesn't support tool-calling, an empty
        final answer, anything else pydantic-ai can raise) — the LLM mode is
        additive and must never turn into a hard failure for a request the
        deterministic path could have served.
        """
        try:
            outcome: LlmRunOutcome | None = None
            async for event_type, payload in stream_llm_response(
                request.message, history, request.conversation_id or "", request.model
            ):
                if event_type == "outcome":
                    outcome = payload
            if outcome is None:
                raise LlmRunFailed("LLM stream ended without an outcome event.")
        except LlmRunFailed as error:
            logger.warning("LLM tool-calling path failed, falling back: %s", error)
            return None
        except Exception as error:  # noqa: BLE001 - backstop for anything stream_llm_response didn't wrap
            logger.exception("Unexpected error in LLM tool-calling path, falling back: %s", error)
            return None

        return outcome.answer, outcome.sql, outcome.chart, outcome.metrics, outcome.confidence, outcome.intent

    async def _build_deterministic_response(
        self, request: ChatRequest, history: list[dict]
    ) -> tuple[str, str | None, ChartConfig | None, dict[str, float], float, Intent]:
        effective_message = _resolve_follow_up(request.message, history)
        planner_result = classify(effective_message)
        intent = planner_result.intent

        if intent == Intent.SQL:
            answer, sql, chart, metrics, conf = await self._handle_sql(planner_result)
        elif intent == Intent.KPI:
            answer, sql, chart, metrics, conf = await self._handle_kpi(planner_result)
        elif intent == Intent.COMPARISON:
            answer, sql, chart, metrics, conf = await self._handle_comparison(planner_result)
        elif intent == Intent.FORECAST:
            answer, sql, chart, metrics, conf = await self._handle_forecast(planner_result)
        elif intent == Intent.CHART:
            answer, sql, chart, metrics, conf = await self._handle_chart(planner_result)
        else:
            answer = templates.render_conversation_answer(request.message)
            sql, chart, metrics = None, None, {}
            conf = confidence.score_conversation()

        answer = await maybe_reword(answer, user_message=request.message)
        return answer, sql, chart, metrics, conf, intent

    async def _handle_sql(
        self, planner_result: PlannerResult
    ) -> tuple[str, str | None, ChartConfig | None, dict[str, float], float]:
        sql, _alias = build_sql(planner_result)
        try:
            rows = execute_sql(sql)
        except (SqlValidationError, SqlExecutionError):
            return (
                "No pude ejecutar esa consulta sobre la base de datos. Probá reformularla.",
                None,
                None,
                {},
                confidence.fallback_score(Intent.SQL),
            )

        answer = templates.render_sql_answer(rows, sql)
        chart = create_chart(rows, Intent.SQL) if len(rows) > 1 else None
        conf = confidence.score_sql_result(rows)
        return answer, sql, chart, {}, conf

    async def _handle_kpi(
        self, planner_result: PlannerResult
    ) -> tuple[str, str | None, ChartConfig | None, dict[str, float], float]:
        sql = build_forecast_source_sql_for_kpi()
        try:
            rows = execute_sql(sql)
        except (SqlValidationError, SqlExecutionError):
            return (
                "No pude obtener los datos para calcular los indicadores solicitados.",
                None,
                None,
                {},
                confidence.fallback_score(Intent.KPI),
            )

        metrics = calculate_kpis(rows)
        answer = templates.render_kpi_answer(metrics, planner_result.matched_keywords)
        conf = confidence.score_kpi_result(rows, metrics)
        return answer, sql, None, metrics, conf

    async def _handle_comparison(
        self, planner_result: PlannerResult
    ) -> tuple[str, str | None, ChartConfig | None, dict[str, float], float]:
        named_kpi = _find_named_kpi(planner_result.raw_text)
        if named_kpi is not None:
            if named_kpi in _CHANNEL_SPLITTABLE_KPIS:
                return await self._handle_kpi_channel_comparison(named_kpi)
            return await self._handle_kpi_whole_dataset(named_kpi)

        metric = "costo"
        for candidate in ("clics", "impresiones", "leads", "costo"):
            if candidate in planner_result.raw_text.lower():
                metric = candidate
                break

        sql = build_channel_comparison_sql(metric=metric)
        try:
            rows = execute_sql(sql)
        except (SqlValidationError, SqlExecutionError):
            return (
                "No pude obtener los datos para comparar los canales.",
                None,
                None,
                {},
                confidence.fallback_score(Intent.COMPARISON),
            )

        channel_values: dict[str, float] = {}
        if rows:
            row = rows[0]
            for channel in ADS_CHANNELS:
                key = f"{channel}_{metric}"
                if key in row and row[key] is not None:
                    channel_values[channel] = float(row[key])

        answer = templates.render_comparison_answer(channel_values, metric)
        chart = None
        if channel_values:
            chart_rows = [{"canal": channel, metric: value} for channel, value in channel_values.items()]
            chart = create_chart(chart_rows, Intent.COMPARISON, chart_type="bar")
        conf = confidence.score_comparison_result(channel_values)
        return answer, sql, chart, channel_values, conf

    async def _handle_kpi_whole_dataset(
        self, kpi_key: str
    ) -> tuple[str, str | None, ChartConfig | None, dict[str, float], float]:
        """Answer a named KPI that can't be split per channel (ROAS/CPA/CPL/
        ROI/conversion_rate — see _CHANNEL_SPLITTABLE_KPIS) over the whole
        dataset instead of silently defaulting to a cost comparison.

        This is the same computation _handle_kpi runs, but highlights
        ``kpi_key`` specifically rather than whatever COMPARISON keywords
        (e.g. " vs ") the planner matched — those aren't KPI names, so
        passing them through to render_kpi_answer would highlight nothing
        and fall back to listing every KPI instead of just the one asked
        about.
        """
        sql = build_forecast_source_sql_for_kpi()
        try:
            rows = execute_sql(sql)
        except (SqlValidationError, SqlExecutionError):
            return (
                "No pude obtener los datos para calcular los indicadores solicitados.",
                None,
                None,
                {},
                confidence.fallback_score(Intent.COMPARISON),
            )

        metrics = calculate_kpis(rows)
        answer = templates.render_kpi_answer(metrics, [kpi_key])
        conf = confidence.score_kpi_result(rows, metrics)
        return answer, sql, None, metrics, conf

    async def _handle_kpi_channel_comparison(
        self, kpi_key: str
    ) -> tuple[str, str | None, ChartConfig | None, dict[str, float], float]:
        """Answer a named, channel-splittable KPI (CTR/CPC) per Google Ads vs
        Meta Ads, instead of silently comparing cost (the pre-fix default).

        Only reached for KPIs in _CHANNEL_SPLITTABLE_KPIS: their inputs are
        all per-channel columns, so filtering the row projection down to one
        channel's columns before calling calculate_kpis computes that KPI
        for that channel alone (calculate_kpis sums whichever of its known
        columns are present — see app.tools.calculate_kpis._safe_sum).
        """
        sql = build_forecast_source_sql_for_kpi()
        try:
            rows = execute_sql(sql)
        except (SqlValidationError, SqlExecutionError):
            return (
                "No pude obtener los datos para comparar los canales.",
                None,
                None,
                {},
                confidence.fallback_score(Intent.COMPARISON),
            )

        channel_values: dict[str, float] = {}
        for channel in ADS_CHANNELS:
            channel_rows = [_project_channel_columns(row, channel) for row in rows]
            channel_metrics = calculate_kpis(channel_rows)
            if kpi_key in channel_metrics:
                channel_values[channel] = channel_metrics[kpi_key]

        metric_label = templates.kpi_label(kpi_key)
        answer = templates.render_comparison_answer(channel_values, metric_label)
        chart = None
        if channel_values:
            chart_rows = [{"canal": channel, kpi_key: value} for channel, value in channel_values.items()]
            chart = create_chart(chart_rows, Intent.COMPARISON, chart_type="bar")
        conf = confidence.score_comparison_result(channel_values)
        return answer, sql, chart, channel_values, conf

    async def _handle_forecast(
        self, planner_result: PlannerResult
    ) -> tuple[str, str | None, ChartConfig | None, dict[str, float], float]:
        value_column, forecast_fn, label = _DEFAULT_FORECAST
        for concept, mapping in _FORECAST_METRIC_MAP.items():
            if concept in planner_result.raw_text.lower():
                value_column, forecast_fn, label = mapping
                break

        sql = build_forecast_source_sql(value_column)
        try:
            rows = execute_sql(sql)
        except (SqlValidationError, SqlExecutionError):
            return (
                "No pude obtener el historial necesario para generar la proyección.",
                None,
                None,
                {},
                confidence.fallback_score(Intent.FORECAST),
            )

        result = forecast_fn(rows)
        answer = templates.render_forecast_answer(result, label)
        chart = None
        if result.points:
            chart_rows = [{"fecha": point.date, label: point.value} for point in result.points]
            chart = create_chart(chart_rows, Intent.FORECAST, chart_type="line")
        conf = confidence.score_forecast_result(result)
        metrics = {
            "horizonte_dias": float(result.horizon_days),
            "puntos_historicos": float(result.history_points),
        }
        return answer, sql, chart, metrics, conf

    async def _handle_chart(
        self, planner_result: PlannerResult
    ) -> tuple[str, str | None, ChartConfig | None, dict[str, float], float]:
        sql, _alias = build_sql(planner_result)
        try:
            rows = execute_sql(sql)
        except (SqlValidationError, SqlExecutionError):
            return (
                "No pude obtener los datos para generar el gráfico.",
                None,
                None,
                {},
                confidence.fallback_score(Intent.CHART),
            )

        # A single-row result is a total, not something to plot (Quality 4):
        # a 1-point line/bar chart renders as a visibly broken sliver. Mirrors
        # the same len(rows) > 1 guard _handle_sql already applies.
        chart = create_chart(rows, Intent.CHART) if len(rows) > 1 else None
        answer = templates.render_sql_answer(rows, sql) if rows else "No encontré datos para graficar."
        conf = confidence.score_chart_result(rows, chart is not None)
        return answer, sql, chart, {}, conf


def _find_named_kpi(text: str) -> str | None:
    """Return the canonical calculate_kpis() key for the first named KPI
    found in ``text``, or None if no specific KPI is named.

    Used by _handle_comparison so a comparative question that names a KPI
    (e.g. "¿cuál fue el ROAS de Google Ads vs Meta Ads?") answers that KPI
    instead of silently defaulting to a cost comparison — the bug this
    function exists to close.
    """
    lowered = text.lower()
    for keyword, kpi_key in _NAMED_KPI_KEYWORDS:
        if keyword in lowered:
            return kpi_key
    return None


def _project_channel_columns(row: dict, channel: str) -> dict:
    """Return a copy of ``row`` keeping only columns for ``channel`` plus the
    combined (non-channel-specific) columns.

    This is what lets calculate_kpis (unchanged) compute a per-channel KPI:
    it sums whichever of its known input columns are present in the row
    (app.tools.calculate_kpis._safe_sum). Dropping the other channel's
    google_ads_*/meta_ads_* keys — rather than zeroing them — makes that sum
    see only this channel's impressions/clicks/cost. total_leads,
    cantidad_ventas and ingresos_ventas_usd are combined columns with no
    per-channel counterpart in the schema (db/init.sql), so they pass
    through unfiltered; this is only safe for KPIs in
    _CHANNEL_SPLITTABLE_KPIS, which never depend on those columns.
    """
    other_channel = "meta_ads" if channel == "google_ads" else "google_ads"
    return {key: value for key, value in row.items() if not key.startswith(other_channel)}


# Short pronoun-only follow-ups the planner can't classify on their own
# (spec example: "¿cuál fue el mejor mes?" -> "¿y cuál fue el peor?").
_FOLLOW_UP_MARKERS = ("y el", "y cuál", "y cual", "y qué", "y que", "y cómo", "y como")
_FOLLOW_UP_WORD_LIMIT = 8
# Spanish opens questions/exclamations with an inverted mark (¿, ¡); strip it
# (and any other leading punctuation) before matching markers, otherwise
# "¿y cuál..." never matches a startswith("y cuál") check.
_LEADING_PUNCTUATION = "¿¡?!.,;: "


def _resolve_follow_up(message: str, history: list[dict]) -> str:
    """Prefix ``message`` with the prior user turn when it looks like a bare
    follow-up, so the deterministic planner has enough text to reclassify
    correctly (CLAUDE.md conversational memory example).

    Heuristic, not NLP: short messages that start with a follow-up marker
    ("y el...", "y cuál...") get the last user message from ``history``
    prepended. This never changes ``request.message`` itself — only the text
    handed to the planner/SQL builder — so what gets stored back to memory
    afterwards is still the user's own words.
    """
    lowered = message.strip().lower().lstrip(_LEADING_PUNCTUATION)
    looks_like_follow_up = len(lowered.split()) <= _FOLLOW_UP_WORD_LIMIT and any(
        lowered.startswith(marker) for marker in _FOLLOW_UP_MARKERS
    )
    if not looks_like_follow_up:
        return message

    last_user_message = next(
        (entry["content"] for entry in reversed(history) if entry.get("role") == "user"),
        None,
    )
    if not last_user_message:
        return message

    return f"{last_user_message} {message}"


def build_forecast_source_sql_for_kpi() -> str:
    """KPI queries need the full per-row breakdown (impressions/clicks/cost/
    leads/sales/income), not just one value column — a plain daily pull over
    all numeric columns in the authorized table covers every KPI formula in
    CLAUDE.md's KPI table without a bespoke query per KPI name."""
    return (
        "SELECT fecha, google_ads_impresiones, google_ads_clics, google_ads_costo_usd, "
        "google_ads_leads, meta_ads_impresiones, meta_ads_clics, meta_ads_costo_usd, "
        "meta_ads_leads, total_leads, cantidad_ventas, ingresos_ventas_usd "
        f"FROM {TABLE_NAME} "
        "ORDER BY fecha"
    )
