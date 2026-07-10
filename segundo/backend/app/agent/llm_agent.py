"""LLM tool-calling agent — conversational mode where the model drives which
controlled tool to call, instead of the deterministic planner picking one.

Invariant (CLAUDE.md #2, #3, #4): the LLM NEVER touches MySQL directly and
NEVER computes KPIs/forecasts itself. Every tool registered on the Agent
below is a thin wrapper delegating to ``app.tools`` (the exact same
functions the deterministic path uses) — the LLM only decides *when* to call
them and how to narrate their results. ``run_sql`` in particular only ever
calls ``app.tools.execute_sql``, which validates via
``app.security.sql_guard.validate_sql`` before touching the database; this
module must never call ``app.database.engine.run_select`` or otherwise
execute SQL text directly.

This module is safe to import with ``settings.llm_api_key`` empty: nothing
here opens a network connection or builds a real provider client at import
time. ``build_agent()`` is the only place a real ``Agent``/model/provider is
constructed, and it is only ever called from ``stream_llm_response`` behind
an explicit ``if settings.llm_api_key:`` guard in ``app.agent.engine``.

Confidence for this path is scored by ``_score_llm_run`` below, from
execution signals (did at least one tool succeed and return data) — never
from anything the LLM claims about itself, per the same invariant the
deterministic path already follows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from pydantic_ai import (
    Agent,
    ModelAPIError,
    ModelRequest,
    ModelResponse,
    RunContext,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.agent.models import resolve_model
from app.agent.sql_builder import build_forecast_source_sql
from app.agent.think_strip import strip_think_tags
from app.config import settings
from app.schemas.chat import ChartConfig, Intent
from app.tools import (
    ForecastResult,
    SqlExecutionError,
    calculate_kpis,
    create_chart,
    execute_sql,
    forecast_income,
    forecast_leads,
    forecast_sales,
)
from app.security.sql_guard import SqlValidationError

# --- System prompt (domain content — Spanish, per project convention) -----

_SYSTEM_PROMPT = """\
Sos un Analista de Datos Comercial. Respondés preguntas sobre campañas \
publicitarias y ventas de una empresa, usando exclusivamente datos reales \
obtenidos a través de las herramientas que tenés disponibles.

Tabla autorizada: metricas_campanas_ventas. Columnas disponibles:
- fecha
- google_ads_impresiones, google_ads_clics, google_ads_costo_usd, google_ads_leads
- meta_ads_impresiones, meta_ads_clics, meta_ads_costo_usd, meta_ads_leads
- total_leads
- cantidad_ventas
- vehiculo_tipo_principal, vehiculo_modelo_principal
- ingresos_ventas_usd

Diccionario de negocio (vocabulario en español -> columnas):
- ventas / clientes -> cantidad_ventas
- facturación / ingresos -> ingresos_ventas_usd
- gasto / inversión -> google_ads_costo_usd + meta_ads_costo_usd (costo_total)
- leads -> total_leads
- ads / google -> google_ads_*
- meta / facebook / instagram -> meta_ads_*

Fórmulas de KPIs (las calcula compute_kpis, vos nunca las calculás a mano):
- CTR = clics / impresiones
- CPC = costo / clics
- CPL = costo / leads
- CPA = costo_total / ventas
- ROAS = ingresos / costo_total
- ROI = (ingresos - costos) / costos
- Tasa de conversión = ventas / leads

REGLAS ESTRICTAS:
1. Accedé a los datos únicamente a través de las herramientas provistas \
(run_sql, compute_kpis, forecast, make_chart). Nunca digas que consultaste \
la base de datos directamente vos mismo.
2. NUNCA inventes cifras. Cada número en tu respuesta tiene que provenir de \
un resultado de una herramienta.
3. run_sql solo acepta SELECT sobre la tabla autorizada y sus columnas \
permitidas — cualquier otra cosa va a ser rechazada antes de ejecutarse.
4. Respondé siempre de forma conversacional, en español neutro y profesional.
5. Si una herramienta falla o no devuelve datos, decilo honestamente en vez \
de adivinar o completar con datos inventados.
6. No anuncies ni narres lo que vas a hacer (no digas "voy a consultar…", \
"primero obtengo…", "en paralelo traigo…"). Ejecutá las herramientas y \
respondé solo con el resultado final.
7. Si el usuario pide un gráfico, visualización o evolución, DESPUÉS de \
traer los datos con run_sql tenés que llamar make_chart con esos datos \
antes de responder.
"""

# --- Deps / collector -------------------------------------------------------


@dataclass
class LlmToolDeps:
    """Per-request mutable collector tools write into as a side effect.

    A fresh instance MUST be created for every request (never shared/reused
    across requests or cached at module level) — concurrent requests must
    not leak sql/chart/metrics state into each other. ``app.agent.engine``
    reads these fields back after the run to assemble ``ChatResponse``.
    """

    last_sql: str | None = None
    last_rows: list[dict] | None = None  # rows from the last successful run_sql, for the auto-chart safety net
    last_chart: ChartConfig | None = None
    last_metrics: dict[str, float] = field(default_factory=dict)
    any_tool_succeeded: bool = False
    any_tool_failed: bool = False


# --- Tool functions ----------------------------------------------------------


async def run_sql(ctx: RunContext[LlmToolDeps], sql: str) -> list[dict] | str:
    """Execute a read-only SELECT query against the metricas_campanas_ventas table.

    The query is validated before execution — only SELECT statements against
    this table's allowed columns and an allow-listed function set are
    permitted. Never attempt UPDATE/DELETE/INSERT/DROP or any other
    statement type; they will be rejected before reaching the database. Use
    this tool whenever you need raw rows, totals, rankings, or any other
    figure that isn't already covered by compute_kpis or forecast. On
    failure, returns a short error message instead of raising — read it and
    either fix the query or tell the user honestly that the data could not
    be retrieved.
    """
    try:
        rows = execute_sql(sql)
    except (SqlValidationError, SqlExecutionError) as error:
        ctx.deps.any_tool_failed = True
        return f"Query rejected or failed: {error}"

    ctx.deps.last_sql = sql
    ctx.deps.last_rows = rows
    ctx.deps.any_tool_succeeded = True
    return rows


async def compute_kpis(ctx: RunContext[LlmToolDeps], rows: list[dict]) -> dict[str, float]:
    """Compute commercial KPIs (CTR, CPC, CPL, CPA, ROAS, ROI, conversion rate,
    total cost, total income, cost per sale) from rows already fetched via
    run_sql.

    ``rows`` must contain the raw numeric columns the formulas need
    (impressions/clicks/cost/leads/sales/income) — a good source query is
    ``SELECT fecha, google_ads_impresiones, google_ads_clics,
    google_ads_costo_usd, google_ads_leads, meta_ads_impresiones,
    meta_ads_clics, meta_ads_costo_usd, meta_ads_leads, total_leads,
    cantidad_ventas, ingresos_ventas_usd FROM metricas_campanas_ventas``. A
    KPI is omitted from the result (not returned as zero) when its
    denominator is zero or its input columns are missing from ``rows`` — do
    not invent a value for a KPI that isn't in the returned dict. Never
    compute these ratios yourself; always call this tool.
    """
    metrics = calculate_kpis(rows)
    ctx.deps.last_metrics.update(metrics)
    if metrics:
        ctx.deps.any_tool_succeeded = True
    return metrics


async def forecast(
    ctx: RunContext[LlmToolDeps], metric: Literal["ventas", "leads", "ingresos"], horizon_days: int = 30
) -> dict:
    """Forecast a metric's future values using historical data (Prophet, with
    a linear-trend fallback if Prophet is unavailable or the history is too
    short).

    ``metric`` must be one of "ventas" (cantidad_ventas), "leads"
    (total_leads), or "ingresos" (ingresos_ventas_usd). ``horizon_days``
    defaults to 30, the trusted forecasting window for this dataset;
    forecasts beyond ~90 days carry a warning and should be treated as
    low-confidence. This tool fetches its own historical data internally —
    do not call run_sql first for this. Returns a dict with "points" (daily
    date/value/lower/upper), "method" ("prophet" or "linear_trend"),
    "history_points", "horizon_days", and "warning" (a string explaining any
    degraded confidence, or null). If "points" is empty, there wasn't enough
    historical data to forecast — say so, don't guess a number.
    """
    value_column, forecast_fn, label = _FORECAST_METRIC_MAP[metric]

    sql = build_forecast_source_sql(value_column)
    try:
        rows = execute_sql(sql)
    except (SqlValidationError, SqlExecutionError) as error:
        ctx.deps.any_tool_failed = True
        return {"points": [], "method": "none", "history_points": 0, "horizon_days": horizon_days,
                "warning": f"Could not fetch historical data: {error}"}

    result: ForecastResult = forecast_fn(rows, horizon_days=horizon_days)

    ctx.deps.last_metrics.update(
        {
            "horizonte_dias": float(result.horizon_days),
            "puntos_historicos": float(result.history_points),
        }
    )

    if result.points:
        chart_rows = [{"fecha": point.date, label: point.value} for point in result.points]
        ctx.deps.last_chart = create_chart(chart_rows, Intent.FORECAST, chart_type="line")
        ctx.deps.any_tool_succeeded = True
    else:
        ctx.deps.any_tool_failed = True

    return result.to_dict()


async def make_chart(
    ctx: RunContext[LlmToolDeps],
    rows: list[dict],
    intent_hint: str = "sql",
    chart_type: str | None = None,
) -> dict | None:
    """Build a chart configuration from rows already fetched via run_sql, for
    the frontend to render.

    ``rows`` needs at least one numeric column and, ideally, a date or
    categorical column to use as the x-axis; a single-row result (a plain
    total) will not build a useful chart, so prefer a query that returns
    multiple rows (a daily series, a monthly ranking, a per-model
    breakdown, ...) before calling this. ``intent_hint`` is one of "sql",
    "kpi", "comparison", "forecast", "chart", "conversation" — it only
    nudges the automatic line/bar/pie choice when ``chart_type`` is not
    given explicitly. Returns None if no chart could be built (e.g. no
    numeric column, or empty rows) — in that case, just answer in text
    without claiming a chart was produced.
    """
    resolved_intent = Intent(intent_hint) if intent_hint in {member.value for member in Intent} else Intent.SQL
    chart = create_chart(rows, resolved_intent, chart_type=chart_type)  # type: ignore[arg-type]
    ctx.deps.last_chart = chart
    if chart is not None:
        ctx.deps.any_tool_succeeded = True
    return chart.model_dump() if chart is not None else None


_FORECAST_METRIC_MAP = {
    "ventas": ("cantidad_ventas", forecast_sales, "ventas"),
    "leads": ("total_leads", forecast_leads, "leads"),
    "ingresos": ("ingresos_ventas_usd", forecast_income, "ingresos"),
}

_TOOLS = (run_sql, compute_kpis, forecast, make_chart)


# --- Agent construction (lazy — never eager, never at import time) --------


def build_agent(model_id: str) -> Agent[LlmToolDeps, str]:
    """Construct a fresh Agent bound to the configured OpenAI-compatible
    provider (OpenCode GO or any other OpenAI-compatible endpoint), using
    ``model_id`` as the model to run.

    ``model_id`` MUST already be a trusted, resolved id by the time it
    reaches this function — this function performs NO allow-list validation
    itself. Callers (currently only ``stream_llm_response`` below) are
    responsible for passing every incoming model id through
    ``app.agent.models.resolve_model`` first; this keeps the single
    security boundary in one place instead of duplicating the check here.

    Callers MUST only invoke this when ``settings.llm_api_key`` is
    non-empty — this function does not itself guard against an empty key,
    so calling it unconditionally would build a client with no credentials.
    The actual guard lives in ``stream_llm_response`` below and in
    ``app.agent.engine``, which checks the key before even importing this
    path's execution.
    """
    model = OpenAIChatModel(
        model_id or "gpt-4o-mini",
        provider=OpenAIProvider(base_url=settings.llm_api_base, api_key=settings.llm_api_key),
    )
    return Agent(
        model,
        deps_type=LlmToolDeps,
        output_type=str,
        instructions=_SYSTEM_PROMPT,
        tools=list(_TOOLS),
    )


# --- Plain-dict history -> pydantic-ai ModelMessage conversion -------------


def _to_model_messages(history: list[dict]) -> list[ModelMessage]:
    """Convert ``ConversationMemory``'s plain ``{"role", "content"}`` dicts
    into the ``list[ModelMessage]`` shape pydantic-ai's ``message_history``
    expects.

    Only "user" and "assistant" roles are handled — that is the only shape
    ``app.memory`` ever stores (see app/api/chat.py). Any other/unexpected
    role is skipped rather than raising, so a future memory entry shape
    change degrades gracefully (fewer history turns sent) instead of
    breaking the whole LLM path.
    """
    messages: list[ModelMessage] = []
    for entry in history:
        role = entry.get("role")
        content = entry.get("content")
        if not content:
            continue
        if role == "user":
            messages.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif role == "assistant":
            messages.append(ModelResponse(parts=[TextPart(content=content)]))
    return messages


# --- Outcome contract with app.agent.engine ---------------------------------


@dataclass
class LlmRunOutcome:
    """Final result of a successful LLM tool-calling run, shaped so
    ``app.agent.engine`` can assemble a ``ChatResponse`` from it directly —
    mirrors the ``(answer, sql, chart, metrics, confidence, intent)`` tuple
    ``AnalyticsEngine._build_response`` already produces for the
    deterministic path.
    """

    answer: str
    sql: str | None
    chart: ChartConfig | None
    metrics: dict[str, float]
    confidence: float
    intent: Intent


class LlmRunFailed(Exception):
    """Raised by ``stream_llm_response`` when the LLM run itself could not
    complete (network/auth/model error, tool-calling unsupported by the
    provider, or any other failure inside the pydantic-ai run).

    ``app.agent.engine`` catches this (plus a broad ``Exception`` backstop)
    and falls back to the deterministic planner+templates path — this
    exception type exists only to give that catch a clear, specific signal
    to log before falling back, rather than swallowing an opaque generic
    error.
    """


async def stream_llm_response(
    message: str, history: list[dict], conversation_id: str, model: str | None = None
) -> AsyncIterator[tuple[Literal["token"], str] | tuple[Literal["outcome"], LlmRunOutcome]]:
    """Run the LLM tool-calling agent over ``message``, streaming answer text
    as ``("token", chunk)`` events and finishing with exactly one
    ``("outcome", LlmRunOutcome)`` event.

    Mirrors the shape ``AnalyticsEngine.stream`` needs: the engine can
    forward every "token" event as-is (or, if it prefers the simpler
    word-split-over-final-text approach, ignore these and only consume the
    final outcome's ``answer``) and use the "outcome" event to build
    ``ChatResponse``. ``conversation_id`` is accepted for symmetry with the
    engine's call signature and future use (e.g. per-conversation tool
    telemetry) — it is not currently required by the run itself since
    ``history`` already carries the prior turns.

    ``model`` is the raw, UNTRUSTED model id the client requested (from
    ``ChatRequest.model``, threaded through ``app.agent.engine``) — it is
    resolved through ``app.agent.models.resolve_model`` immediately below
    before it ever reaches ``build_agent``/the provider. ``None`` (or any
    id outside the allow-list) resolves to ``settings.llm_model``, the
    trusted server default.

    Raises ``LlmRunFailed`` if the run itself cannot complete (network,
    auth, provider not supporting tool-calling, or any other pydantic-ai
    error) — callers must catch this (and, as a backstop, generic
    ``Exception``) and fall back to the deterministic path. Does NOT catch
    exceptions from this function's own setup (e.g. calling this without a
    configured key would raise from ``build_agent`` — callers should not
    invoke this at all in that case).
    """
    _ = conversation_id  # accepted for interface symmetry; not used yet
    resolved_model = resolve_model(model)
    agent = build_agent(resolved_model)
    deps = LlmToolDeps()
    model_history = _to_model_messages(history)

    # IMPORTANT: agent.run() (not run_stream()) is used deliberately. On a
    # multi-tool-call turn, run_stream()'s live token stream reflects the
    # model's FIRST turn only — often a plan narration ("Primero obtengo...
    # y en paralelo traigo...") emitted before any tool has even run, not the
    # final answer produced after every tool call resolves. agent.run() runs
    # the full tool-calling loop internally and returns only the model's
    # FINAL output text via the non-streamed AgentRunResult.output field, so
    # the narration a reasoning/planning turn produces along the way is never
    # exposed to the caller in the first place — there is nothing to filter.
    # (AgentRunResult is a plain dataclass with a real `.output` field; this
    # is distinct from StreamedRunResult, which has no `.output` attribute at
    # all and needs the async get_output() method instead — see build_agent's
    # docstring history / think_strip.py for that unrelated, already-fixed
    # gotcha.)
    try:
        result = await agent.run(message, message_history=model_history, deps=deps)
        final_answer = result.output
    except ModelAPIError as error:
        raise LlmRunFailed(f"LLM provider API error: {error}") from error
    except Exception as error:  # noqa: BLE001 - any pydantic-ai/run failure triggers fallback
        raise LlmRunFailed(f"LLM run failed: {error}") from error

    if not final_answer or not isinstance(final_answer, str):
        raise LlmRunFailed("LLM run produced no final text output.")

    # Some OpenCode GO models (e.g. minimax-m3) emit raw <think>...</think>
    # chain-of-thought inline with their answer. That must never reach the
    # user. Since the full final answer is available up front (no longer a
    # live delta stream), a single whole-string pass is enough — there is no
    # chunk-boundary-split-tag case to guard here anymore.
    final_answer = strip_think_tags(final_answer)
    if not final_answer.strip():
        raise LlmRunFailed("LLM run produced no final text output after stripping <think> reasoning.")

    # Simulate the live-token experience for the caller (same word-by-word
    # shape AnalyticsEngine.stream already uses for the deterministic path)
    # by streaming the already-final, already-stripped text — never the raw
    # model output — so the SSE token stream can only ever show the real
    # answer, not any first-turn narration.
    for index, word in enumerate(final_answer.split(" ")):
        yield ("token", word if index == 0 else f" {word}")

    _maybe_build_auto_chart(message, deps)

    intent = _infer_intent(deps)
    conf = _score_llm_run(deps)

    yield (
        "outcome",
        LlmRunOutcome(
            answer=final_answer,
            sql=deps.last_sql,
            chart=deps.last_chart,
            metrics=deps.last_metrics,
            confidence=conf,
            intent=intent,
        ),
    )


# --- Auto-chart safety net ---------------------------------------------------

# Keyword set (Spanish, matched case-insensitively as substrings so both
# accented and unaccented user input match — e.g. "evolucion" and
# "evolución") that signals the user wants a visualization. Deliberately
# broad/conservative on the "detect intent" side; the row-count and
# numeric-column checks in _maybe_build_auto_chart are what keep this from
# firing on requests that shouldn't get a chart (e.g. a single-row total).
_CHART_REQUEST_KEYWORDS: tuple[str, ...] = (
    "gráfico",
    "grafico",
    "gráfica",
    "grafica",
    "visualiz",
    "mostrame",
    "evolución",
    "evolucion",
    "oscil",
    "tendencia",
)

# Below this row count there isn't a series to plot (a single total, or too
# thin a sample to call a "trend") — mirrors the len(rows) > 1 guards
# app.agent.engine already applies before calling create_chart.
_MIN_ROWS_FOR_AUTO_CHART = 2


def _wants_chart(message: str) -> bool:
    """Best-effort detection of chart/visualization intent from the user's
    own words — used only as a trigger for the auto-chart safety net below,
    never to decide what data goes in the chart (that always comes from
    deps.last_rows, real tool output)."""
    lowered = message.lower()
    return any(keyword in lowered for keyword in _CHART_REQUEST_KEYWORDS)


def _maybe_build_auto_chart(message: str, deps: LlmToolDeps) -> None:
    """Safety net: build a chart from the last run_sql rows when the user
    clearly asked for one but the model never called make_chart itself.

    Mutates ``deps.last_chart`` in place (mirrors how make_chart's own tool
    wrapper writes into deps) only when ALL of these hold:
    - the user's message looks like a chart/visualization request
    - the model hasn't already produced a chart (deps.last_chart is None) —
      this never overrides a chart the model built on purpose, e.g. with a
      caller-picked chart_type
    - there are at least _MIN_ROWS_FOR_AUTO_CHART rows from the last run_sql
      call (a single-row total is never worth plotting)

    Reuses app.tools.create_chart — the same builder make_chart's tool
    wrapper calls — so this never invents a chart shape of its own; it can
    only return the same ChartConfig the model would have gotten had it
    called make_chart with these exact rows. create_chart itself already
    returns None when there's no usable numeric column, which keeps this
    conservative without duplicating that check here.
    """
    if deps.last_chart is not None:
        return
    if not deps.last_rows or len(deps.last_rows) < _MIN_ROWS_FOR_AUTO_CHART:
        return
    if not _wants_chart(message):
        return

    chart = create_chart(deps.last_rows, Intent.CHART)
    if chart is not None:
        deps.last_chart = chart
        deps.any_tool_succeeded = True


def _infer_intent(deps: LlmToolDeps) -> Intent:
    """Best-effort Intent for ``templates.default_suggestions`` — ChatResponse
    itself has no intent field, so this only needs to be reasonable, not
    exact (see llm_agent's module docstring / task spec)."""
    if deps.last_chart is not None:
        return Intent.CHART
    if deps.last_metrics:
        return Intent.KPI
    if deps.last_sql is not None:
        return Intent.SQL
    return Intent.CONVERSATION


def _score_llm_run(deps: LlmToolDeps) -> float:
    """Execution-derived confidence for the LLM tool-calling path — never
    self-reported by the model itself (CLAUDE.md invariant, same rule
    app.agent.confidence enforces for the deterministic path).

    No tool called at all -> plain conversational answer, same baseline as
    confidence.score_conversation(). At least one tool succeeded -> high
    confidence. A tool was attempted and failed with none succeeding ->
    degraded, matching confidence.fallback_score's spirit.
    """
    if not deps.any_tool_succeeded and not deps.any_tool_failed:
        return 0.9
    if deps.any_tool_succeeded:
        return 0.9 if deps.any_tool_failed else 1.0
    return 0.3
