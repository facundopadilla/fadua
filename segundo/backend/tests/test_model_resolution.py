"""Tests for the per-request LLM model selection feature: the allow-list
security boundary (app.agent.models.resolve_model), the ChatRequest.model
field, and the GET /models endpoint.

resolve_model is the single security boundary that stops an arbitrary
client-supplied string from ever reaching OpenAIChatModel/the provider — the
tests here are the most important ones in this module, mirroring how
test_llm_agent.py treats run_sql's rejection path as its most important test.

Mirrors this repo's existing test conventions (see test_llm_agent.py,
test_comparison_kpi.py): plain assert-based functions, no pytest fixtures.
httpx is already present as a transitive dependency of fastapi (confirmed via
`uv pip list`), so fastapi.testclient.TestClient is used directly for the
/models endpoint test instead of calling the route handler function.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.agent.models import ALLOWED_MODELS, resolve_model
from app.config import settings
from app.main import app
from app.schemas.chat import ChatRequest

# --- ALLOWED_MODELS shape and order -----------------------------------------


def test_allowed_models_has_exactly_twenty_entries() -> None:
    assert len(ALLOWED_MODELS) == 20


def test_allowed_models_contains_known_ids() -> None:
    assert "minimax-m3" in ALLOWED_MODELS
    assert "hy3-preview" in ALLOWED_MODELS
    assert "kimi-k2.7-code" in ALLOWED_MODELS


def test_allowed_models_order_is_locked() -> None:
    """The /models response order matters to the frontend's picker — lock the
    first and last entries against accidental reordering."""
    assert ALLOWED_MODELS[0] == "minimax-m3"
    assert ALLOWED_MODELS[-1] == "hy3-preview"


# --- resolve_model: the security boundary -----------------------------------


def test_resolve_model_valid_id_is_returned_unchanged() -> None:
    assert resolve_model("glm-5.2") == "glm-5.2"


def test_resolve_model_none_falls_back_to_default() -> None:
    original = settings.llm_model
    settings.llm_model = "default-sentinel"
    try:
        assert resolve_model(None) == "default-sentinel"
    finally:
        settings.llm_model = original


def test_resolve_model_empty_string_falls_back_to_default() -> None:
    original = settings.llm_model
    settings.llm_model = "default-sentinel"
    try:
        assert resolve_model("") == "default-sentinel"
    finally:
        settings.llm_model = original


def test_resolve_model_rejects_unknown_model_id() -> None:
    """An id that merely looks plausible (not present in ALLOWED_MODELS)
    must never be passed through — it falls back to the server default."""
    original = settings.llm_model
    settings.llm_model = "default-sentinel"
    try:
        assert resolve_model("gpt-4o") == "default-sentinel"
        assert resolve_model("unknown-model") == "default-sentinel"
    finally:
        settings.llm_model = original


def test_resolve_model_rejects_malicious_strings() -> None:
    """The security boundary itself: arbitrary attacker-controlled strings
    must never reach the provider — they always resolve to the trusted
    server default, never to themselves."""
    original = settings.llm_model
    settings.llm_model = "default-sentinel"
    try:
        assert resolve_model("; DROP TABLE metricas_campanas_ventas") == "default-sentinel"
        assert resolve_model("../etc/passwd") == "default-sentinel"
        assert resolve_model("   ") == "default-sentinel"
    finally:
        settings.llm_model = original


# --- ChatRequest.model parsing ----------------------------------------------


def test_chat_request_model_defaults_to_none() -> None:
    assert ChatRequest(message="x").model is None


def test_chat_request_model_parses_provided_value() -> None:
    assert ChatRequest(message="x", model="glm-5.2").model == "glm-5.2"


# --- GET /models endpoint ----------------------------------------------------


def test_get_models_endpoint_returns_allow_list_in_order() -> None:
    client = TestClient(app)
    response = client.get("/models")

    assert response.status_code == 200
    body = response.json()
    assert list(body.keys()) == ["models"]
    assert len(body["models"]) == 20
    assert body["models"] == list(ALLOWED_MODELS)
