"""Business Dictionary — semantic layer mapping business vocabulary to columns.

Spec reference: specs.md "Business Dictionary". Lets the planner and the SQL
tool understand user vocabulary (ventas, facturación, gasto, ...) without the
user needing to know exact column names in ``metricas_campanas_ventas``.

This module is read-only metadata + small pure helpers. It never touches the
database and never builds a full query — callers (planner, tools) compose
these fragments into validated SQL.
"""

from __future__ import annotations

TABLE_NAME = "metricas_campanas_ventas"

# --- Direct concept -> column mappings -------------------------------------
# A concept maps to exactly one real column.
CONCEPT_TO_COLUMN: dict[str, str] = {
    "ventas": "cantidad_ventas",
    "clientes": "cantidad_ventas",
    "cantidad_ventas": "cantidad_ventas",
    "facturacion": "ingresos_ventas_usd",
    "facturación": "ingresos_ventas_usd",
    "ingresos": "ingresos_ventas_usd",
    "leads": "total_leads",
    "total_leads": "total_leads",
}

# --- Composite concepts -> SQL expressions ----------------------------------
# A composite concept maps to a real SQL expression (sum across channels).
CONCEPT_TO_EXPRESSION: dict[str, str] = {
    "gasto": "google_ads_costo_usd + meta_ads_costo_usd",
    "inversion": "google_ads_costo_usd + meta_ads_costo_usd",
    "inversión": "google_ads_costo_usd + meta_ads_costo_usd",
    "costo_total": "google_ads_costo_usd + meta_ads_costo_usd",
    "costo total": "google_ads_costo_usd + meta_ads_costo_usd",
}

# --- Channels ----------------------------------------------------------------
CHANNELS: dict[str, str] = {
    "google_ads": "google_ads",
    "google": "google_ads",
    "meta_ads": "meta_ads",
    "meta": "meta_ads",
    "facebook": "meta_ads",
    "instagram": "meta_ads",
}

ADS_CHANNELS: list[str] = ["google_ads", "meta_ads"]

# Per-channel metric -> column, keyed as {channel}_{metric}.
CHANNEL_METRIC_COLUMNS: dict[str, dict[str, str]] = {
    "google_ads": {
        "impresiones": "google_ads_impresiones",
        "clics": "google_ads_clics",
        "costo": "google_ads_costo_usd",
        "leads": "google_ads_leads",
    },
    "meta_ads": {
        "impresiones": "meta_ads_impresiones",
        "clics": "meta_ads_clics",
        "costo": "meta_ads_costo_usd",
        "leads": "meta_ads_leads",
    },
}

# --- Dimension columns (non-numeric, used for grouping/filtering) -----------
DIMENSION_COLUMNS: dict[str, str] = {
    "modelo": "vehiculo_modelo_principal",
    "modelos": "vehiculo_modelo_principal",
    "vehiculo_modelo_principal": "vehiculo_modelo_principal",
    "tipo": "vehiculo_tipo_principal",
    "tipo de vehiculo": "vehiculo_tipo_principal",
    "tipo de vehículo": "vehiculo_tipo_principal",
    "vehiculo_tipo_principal": "vehiculo_tipo_principal",
}

DATE_COLUMN = "fecha"

# All columns that are safe to SUM/AVG when aggregating a metric expression.
NUMERIC_COLUMNS: frozenset[str] = frozenset(
    {
        "google_ads_impresiones",
        "google_ads_clics",
        "google_ads_costo_usd",
        "google_ads_leads",
        "meta_ads_impresiones",
        "meta_ads_clics",
        "meta_ads_costo_usd",
        "meta_ads_leads",
        "total_leads",
        "cantidad_ventas",
        "ingresos_ventas_usd",
    }
)


def resolve_metric_expression(concept: str) -> str | None:
    """Resolve a business concept to a SQL-safe column or expression.

    Returns None if the concept is unknown. Lookup order: direct column,
    then composite expression. Concept matching is case-insensitive.
    """
    key = concept.strip().lower()
    if key in CONCEPT_TO_COLUMN:
        return CONCEPT_TO_COLUMN[key]
    if key in CONCEPT_TO_EXPRESSION:
        return CONCEPT_TO_EXPRESSION[key]
    return None


def resolve_channel(text: str) -> str | None:
    """Resolve free text to a canonical channel name (google_ads/meta_ads)."""
    key = text.strip().lower()
    return CHANNELS.get(key)


def resolve_channel_metric_column(channel: str, metric: str) -> str | None:
    """Resolve (channel, metric) -> column, e.g. ("google_ads", "clics") -> google_ads_clics."""
    return CHANNEL_METRIC_COLUMNS.get(channel, {}).get(metric)


def resolve_dimension(concept: str) -> str | None:
    """Resolve a grouping/filtering concept to a dimension column."""
    key = concept.strip().lower()
    return DIMENSION_COLUMNS.get(key)


def find_concepts_in_text(text: str) -> list[str]:
    """Return every known concept (direct or composite) mentioned in ``text``.

    Simple substring scan over the lowercased text — the planner is
    deterministic/keyword-based by design (no LLM), so this stays cheap and
    predictable rather than using NLP tokenization.
    """
    lowered = text.lower()
    found: list[str] = []
    for concept in {**CONCEPT_TO_COLUMN, **CONCEPT_TO_EXPRESSION}:
        if concept in lowered and concept not in found:
            found.append(concept)
    return found
