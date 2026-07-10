"""Intent Planner — deterministic keyword/rule classifier.

Locked decision (CLAUDE.md "Startup decisions"): the planner is NOT an LLM.
It classifies each user message into the canonical ``Intent`` enum
(sql, kpi, comparison, forecast, chart, conversation) using keyword and
business-dictionary rules, before any tool or model call. This keeps the
system cheap and predictable, and lets the engine run only the logic a given
query actually needs.

Classification order matters — more specific intents are checked first so
e.g. "proyectá el ROAS del próximo mes" resolves to FORECAST (it asks about
the future) rather than KPI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.chat import Intent
from app.semantics.dictionary import find_concepts_in_text, resolve_channel

# --- Keyword sets --------------------------------------------------------
# Spanish keywords are user-facing domain vocabulary, not code prose.

_FORECAST_KEYWORDS = (
    "proyect",  # proyección, proyectá, proyectar
    "prediccion",
    "predicción",
    "predecir",
    "pronostic",  # pronóstico, pronosticar
    "forecast",
    "próximo mes",
    "proximo mes",
    "próxima semana",
    "proxima semana",
    "el mes que viene",
    "va a haber",
    "habrá",
    "habra",
    "tendencia futura",
)

_COMPARISON_KEYWORDS = (
    "compar",  # comparar, compará, comparación
    " vs ",
    " versus ",
    "diferencia entre",
    "mes contra mes",
    "año contra año",
    "anio contra anio",
    "mejor que",
    "peor que",
    "frente a",
)

_CHART_KEYWORDS = (
    "gráfico",
    "grafico",
    "gráfica",
    "grafica",
    "chart",
    "visualiza",
    "mostrame la evolución",
    "mostrame la evolucion",
    "evolución de",
    "evolucion de",
    "graficá",
    "graficame",
    "dibuja",
    "curva de",
)

_KPI_KEYWORDS = (
    "ctr",
    "cpc",
    "cpl",
    "cpa",
    "roas",
    "roi",
    "conversion rate",
    "tasa de conversión",
    "tasa de conversion",
    "costo por venta",
    "costo por lead",
    "costo por clic",
    "kpi",
    "indicador",
    "rendimiento",
)

_SQL_KEYWORDS = (
    "cuánt",  # cuántas, cuánto
    "cuant",
    "cuál fue",
    "cual fue",
    "cuáles fueron",
    "cuales fueron",
    "cuándo",
    "cuando",
    "listame",
    "mostrame los datos",
    "dame el total",
    "total de",
    "mejor mes",
    "peor mes",
    "mejor modelo",
    "top ",
    "ranking",
)

_CONVERSATION_KEYWORDS = (
    "hola",
    "gracias",
    "buenas",
    "buenos días",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "cómo estás",
    "como estas",
    "qué podés hacer",
    "que podes hacer",
    "ayuda",
    "quién sos",
    "quien sos",
    "chau",
    "adiós",
    "adios",
)


@dataclass
class PlannerResult:
    """Planner output: the routed intent plus hints for the tool layer."""

    intent: Intent
    metrics: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    raw_text: str = ""


def _normalize(text: str) -> str:
    return text.strip().lower()


def _any_keyword(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


def _extract_channels(text: str) -> list[str]:
    found: list[str] = []
    for token in text.replace(",", " ").split():
        channel = resolve_channel(token)
        if channel and channel not in found:
            found.append(channel)
    # Also catch multi-word forms like "google ads" / "meta ads".
    for phrase in ("google ads", "meta ads"):
        channel = resolve_channel(phrase.replace(" ", "_"))
        if phrase in text and channel and channel not in found:
            found.append(channel)
    return found


def classify(message: str) -> PlannerResult:
    """Classify ``message`` into a canonical Intent with routing hints.

    Rule precedence (most specific / highest business value first):
    1. FORECAST — explicit future/projection language wins even if the
       message also mentions a KPI (e.g. "proyectá el ROAS").
    2. CHART — explicit visualization request.
    3. COMPARISON — explicit comparative language.
    4. KPI — named KPI or KPI-ish vocabulary.
    5. CONVERSATION — greetings/small talk with no data vocabulary.
    6. SQL — default for concrete data questions (counts, totals, rankings,
       "best/worst month", etc.) and the catch-all when nothing else fires
       but a business concept is present.
    7. CONVERSATION — final fallback when nothing matches at all.
    """
    text = _normalize(message)
    metrics = find_concepts_in_text(text)
    channels = _extract_channels(text)

    forecast_hits = _any_keyword(text, _FORECAST_KEYWORDS)
    if forecast_hits:
        return PlannerResult(
            intent=Intent.FORECAST,
            metrics=metrics,
            channels=channels,
            matched_keywords=forecast_hits,
            raw_text=message,
        )

    chart_hits = _any_keyword(text, _CHART_KEYWORDS)
    if chart_hits:
        return PlannerResult(
            intent=Intent.CHART,
            metrics=metrics,
            channels=channels,
            matched_keywords=chart_hits,
            raw_text=message,
        )

    comparison_hits = _any_keyword(text, _COMPARISON_KEYWORDS)
    if comparison_hits or len(channels) >= 2:
        return PlannerResult(
            intent=Intent.COMPARISON,
            metrics=metrics,
            channels=channels,
            matched_keywords=comparison_hits,
            raw_text=message,
        )

    kpi_hits = _any_keyword(text, _KPI_KEYWORDS)
    if kpi_hits:
        return PlannerResult(
            intent=Intent.KPI,
            metrics=metrics,
            channels=channels,
            matched_keywords=kpi_hits,
            raw_text=message,
        )

    sql_hits = _any_keyword(text, _SQL_KEYWORDS)
    if sql_hits or metrics:
        return PlannerResult(
            intent=Intent.SQL,
            metrics=metrics,
            channels=channels,
            matched_keywords=sql_hits,
            raw_text=message,
        )

    conversation_hits = _any_keyword(text, _CONVERSATION_KEYWORDS)
    return PlannerResult(
        intent=Intent.CONVERSATION,
        metrics=metrics,
        channels=channels,
        matched_keywords=conversation_hits,
        raw_text=message,
    )
