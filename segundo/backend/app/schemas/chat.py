"""Chat API contract: intent taxonomy, request and structured response models."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel


class Intent(str, Enum):
    """Canonical intent taxonomy — single source of truth for planner and router."""

    SQL = "sql"
    KPI = "kpi"
    COMPARISON = "comparison"
    FORECAST = "forecast"
    CHART = "chart"
    CONVERSATION = "conversation"


class ChartConfig(BaseModel):
    """Chart payload the frontend feeds directly to Recharts."""

    type: Literal["line", "bar", "pie", "area"]
    title: str | None = None
    data: list[dict]
    x_key: str | None = None
    y_keys: list[str] = []


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None  # None -> server generates one
    model: str | None = None  # None -> server uses settings.llm_model default


class ChatResponse(BaseModel):
    """Structured reply rendered declaratively by the frontend (never parsed prose)."""

    conversation_id: str
    answer: str
    sql: str | None = None
    chart: ChartConfig | None = None
    metrics: dict[str, float] = {}
    suggestions: list[str] = []
    execution_time: float
    confidence: float
