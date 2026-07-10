"""Deterministic answer templates — the default (no-LLM) wording path.

Invariant (CLAUDE.md #3): the LLM explains, it never computes. Since the
default deployment has no LLM configured (``settings.llm_api_key`` empty),
these templates ARE the explanation layer: they format real tool output into
prose without ever inventing a figure. Every number here is read from the
data the tools returned — this module has no access to anything else.

Answers are neutral, professional Spanish (the domain's user-facing
language), per the task's persona-scope contract: prose to the end user
follows the project's target language, independent of the assistant
persona used elsewhere in this session.
"""

from __future__ import annotations

from app.schemas.chat import Intent
from app.tools.forecast import ForecastResult

_KPI_LABELS: dict[str, str] = {
    "ctr": "CTR",
    "cpc": "CPC",
    "cpl": "CPL",
    "cpa": "CPA",
    "roas": "ROAS",
    "roi": "ROI",
    "conversion_rate": "tasa de conversión",
    "costo_total": "costo total",
    "ingresos_totales": "ingresos totales",
    "costo_por_venta": "costo por venta",
}


def kpi_label(kpi_key: str) -> str:
    """Public label lookup for a calculate_kpis() key (e.g. "ctr" -> "CTR").

    Used by app.agent.engine when it needs to name a specific KPI outside
    the render_kpi_answer flow (e.g. a per-channel KPI comparison title).
    """
    return _KPI_LABELS.get(kpi_key, kpi_key.replace("_", " "))


def format_number(value: float) -> str:
    """Format a number with thousands separators, 2 decimals if fractional."""
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", ".")
    return f"{value:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


# Alias -> plural noun, for both the total sentence ("Hubo {n} {noun} en
# total.") and the ranking sentence ("...con {n} {noun}."). Covers every
# alias app.agent.sql_builder can produce for a *count* metric: the named
# concepts ("total_ventas", "total_leads") plus "cantidad_ventas" — the
# alias used when no metric concept was named at all (_DEFAULT_METRIC_ALIAS
# in sql_builder), which is exactly what a bare "¿cuál fue el mejor mes?"
# resolves to.
_COUNT_NOUNS: dict[str, str] = {
    "total_ventas": "ventas",
    "cantidad_ventas": "ventas",
    "total_leads": "leads",
}
# Alias -> a Spanish label for a *currency* total sentence ("La {label}
# total fue USD {n}."). Only used by _render_total_sentence: a currency
# ranking ("el mejor mes por facturación") still reports its value as a
# plain number via _COUNT_NOUNS-style pluralization, not this USD phrasing.
_TOTAL_CURRENCY_LABELS: dict[str, str] = {
    "total_ingresos": "la facturación",
    "total_gasto": "la inversión",
}

# Row keys that mark a ranking result (app.agent.sql_builder
# _monthly_ranking_sql / _model_ranking_sql) rather than a generic row.
_RANKING_PERIOD_KEY = "periodo"
_RANKING_MODEL_KEY = "vehiculo_modelo_principal"


def render_sql_answer(rows: list[dict], sql: str) -> str:
    if not rows:
        return "No encontré registros para esa consulta en la base de datos."

    if len(rows) == 1:
        row = rows[0]
        if len(row) == 1:
            total_sentence = _render_total_sentence(row)
            if total_sentence is not None:
                return total_sentence
        parts = [f"{key.replace('_', ' ')}: {_format_cell(value)}" for key, value in row.items()]
        return "Según los datos disponibles, " + ", ".join(parts) + "."

    if _RANKING_PERIOD_KEY in rows[0]:
        return _render_ranking_sentence(rows, sql, item_kind="mes", label_key=_RANKING_PERIOD_KEY)
    if _RANKING_MODEL_KEY in rows[0]:
        return _render_ranking_sentence(rows, sql, item_kind="modelo", label_key=_RANKING_MODEL_KEY)

    preview = rows[:5]
    lines = [f"Encontré {len(rows)} registros. Los primeros son:"]
    for row in preview:
        parts = [f"{key.replace('_', ' ')}: {_format_cell(value)}" for key, value in row.items()]
        lines.append("- " + ", ".join(parts))
    return "\n".join(lines)


def _render_total_sentence(row: dict) -> str | None:
    """Natural phrasing for a single-value aggregate row, or None if the
    row's key isn't a known total alias (caller falls back to the generic
    "Según los datos disponibles..." wording in that case)."""
    key, value = next(iter(row.items()))
    formatted = _format_cell(value)

    noun = _COUNT_NOUNS.get(key)
    if noun is not None:
        return f"Hubo {formatted} {noun} en total."

    label = _TOTAL_CURRENCY_LABELS.get(key)
    if label is not None:
        return f"{label[0].upper()}{label[1:]} total fue USD {formatted}."

    return None


def _render_ranking_sentence(rows: list[dict], sql: str, *, item_kind: str, label_key: str) -> str:
    """Name the top row of a ranking result set instead of dumping a list.

    ``rows`` is already ORDER BY {metric} {ASC|DESC} LIMIT N from
    app.agent.sql_builder, so rows[0] is the best-or-worst item depending on
    direction; direction is read back from ``sql`` (deterministic,
    build_sql-generated text — never user input) since render_sql_answer
    otherwise has no signal for which end of the ranking was requested.
    """
    top = rows[0]
    label = top[label_key]
    metric_key = next(key for key in top if key != label_key)
    formatted_value = _format_cell(top[metric_key])
    metric_noun = _COUNT_NOUNS.get(metric_key) or metric_key.replace("total_", "").replace("_", " ")

    direction = "peor" if _is_ascending_order(sql) else "mejor"
    return f"El {direction} {item_kind} fue {label} con {formatted_value} {metric_noun}."


def _is_ascending_order(sql: str) -> bool:
    return " ASC " in sql or sql.rstrip().upper().endswith("ASC")


def render_kpi_answer(metrics: dict[str, float], requested_keywords: list[str]) -> str:
    if not metrics:
        return (
            "No pude calcular los indicadores solicitados porque no hay datos suficientes "
            "en el rango consultado."
        )

    highlighted = [keyword for keyword in requested_keywords if keyword in metrics]
    keys_to_report = highlighted or list(metrics.keys())

    lines = ["Estos son los indicadores calculados sobre los datos reales:"]
    for key in keys_to_report:
        if key not in metrics:
            continue
        label = _KPI_LABELS.get(key, key.replace("_", " "))
        lines.append(f"- {label}: {format_number(metrics[key])}")
    return "\n".join(lines)


def render_comparison_answer(channel_rows: dict, metric_label: str) -> str:
    if not channel_rows:
        return "No pude obtener datos para comparar los canales solicitados."

    lines = [f"Comparación de {metric_label} entre canales:"]
    for channel, value in channel_rows.items():
        lines.append(f"- {channel.replace('_', ' ').title()}: {format_number(value)}")
    return "\n".join(lines)


def render_forecast_answer(result: ForecastResult, metric_label: str) -> str:
    if not result.points:
        return (
            f"No pude generar una proyección de {metric_label}: "
            f"{result.warning or 'no hay suficientes datos históricos.'}"
        )

    total_projected = sum(point.value for point in result.points)
    first_date = result.points[0].date
    last_date = result.points[-1].date
    method_label = "Prophet" if result.method == "prophet" else "una tendencia lineal (método de respaldo)"

    lines = [
        f"Proyección de {metric_label} para los próximos {result.horizon_days} días "
        f"({first_date} a {last_date}), calculada con {method_label} sobre "
        f"{result.history_points} días de historial:",
        f"- Total proyectado: {format_number(total_projected)}",
        f"- Promedio diario proyectado: {format_number(total_projected / len(result.points))}",
    ]
    if result.warning:
        lines.append(f"- Nota: {result.warning}")
    return "\n".join(lines)


def render_conversation_answer(message: str) -> str:
    lowered = message.lower()
    if any(word in lowered for word in ("hola", "buenas", "buenos días", "buenos dias")):
        return (
            "Hola. Soy tu asistente de analítica comercial. Puedo responder preguntas sobre "
            "ventas, leads, ingresos, inversión publicitaria, KPIs (CTR, CPC, CPL, CPA, ROAS, "
            "ROI), comparaciones entre Google Ads y Meta Ads, y proyecciones a futuro."
        )
    if any(word in lowered for word in ("gracias",)):
        return "De nada. Si necesitás otra consulta sobre las métricas, decime."
    if any(word in lowered for word in ("qué podés", "que podes", "ayuda")):
        return (
            "Puedo consultar ventas, leads, ingresos e inversión; calcular KPIs comerciales; "
            "comparar canales o períodos; generar proyecciones de ventas, leads o ingresos; "
            "y mostrar gráficos de la evolución de estas métricas."
        )
    return (
        "No tengo una consulta de datos específica en tu mensaje. Podés preguntarme, por "
        "ejemplo, cuántas ventas hubo, cuál fue el ROAS, o pedirme una proyección de ventas."
    )


def default_suggestions(intent: Intent) -> list[str]:
    """Static follow-up suggestions per intent — not derived from live data,
    just a fixed, honest menu of what the assistant can do next."""
    if intent == Intent.SQL:
        return ["¿Cuál fue el mejor mes?", "¿Cuál fue el peor mes?", "¿Cuál fue el mejor modelo?"]
    if intent == Intent.KPI:
        return ["¿Cuál fue el ROAS del último mes?", "Compará el CPA entre Google Ads y Meta Ads"]
    if intent == Intent.COMPARISON:
        return ["¿Cuál canal tuvo mejor ROAS?", "Mostrame la evolución de la inversión"]
    if intent == Intent.FORECAST:
        return ["¿Cuántas ventas hubo el mes pasado?", "Mostrame la evolución de las ventas"]
    if intent == Intent.CHART:
        return ["¿Cuál fue el mejor mes?", "Proyectá las ventas del próximo mes"]
    return ["¿Cuántas ventas hubo?", "¿Cuál fue el ROAS?", "Proyectá las ventas del próximo mes"]


def _format_cell(value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return format_number(float(value))
    return str(value)
