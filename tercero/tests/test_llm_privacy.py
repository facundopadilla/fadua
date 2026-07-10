"""Tests for app.llm — the AI provider abstraction and its privacy guarantee.

The critical invariant under test: the mapping prompt builder NEVER
includes record (row) values — only column headers and field labels.
This is a hard security/privacy requirement (CLAUDE.md invariant #2:
"The LLM sees schema and labels only, never PII row values").
"""

import pytest

from app import llm


class TestIsConfigured:
    def test_unconfigured_by_default(self, monkeypatch):
        monkeypatch.delenv("OPENCODE_BASE_URL", raising=False)
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
        monkeypatch.delenv("OPENCODE_MODEL", raising=False)
        assert llm.is_configured() is False

    def test_configured_when_all_env_vars_present(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_BASE_URL", "https://example.com/v1")
        monkeypatch.setenv("OPENCODE_API_KEY", "fake-key")
        monkeypatch.setenv("OPENCODE_MODEL", "fake-model")
        assert llm.is_configured() is True

    def test_not_configured_when_missing_api_key(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_BASE_URL", "https://example.com/v1")
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
        monkeypatch.setenv("OPENCODE_MODEL", "fake-model")
        assert llm.is_configured() is False


class TestMappingPromptNeverIncludesRowValues:
    def test_prompt_builder_excludes_pii_row_values(self):
        # Simulate a real record with PII — the exact kind of value
        # this prompt builder must NEVER leak.
        headers = ["ID_Cliente", "Nombre_Cliente", "Email", "Telefono"]
        labels = ["ID del Cliente", "Nombre Completo", "Correo Electrónico"]
        record_values = {
            "ID_Cliente": "FIAT-001",
            "Nombre_Cliente": "Carlos Mendoza",
            "Email": "carlos.m@mail.com",
            "Telefono": "54119876543",
        }

        prompt = llm.build_mapping_prompt(headers, labels)

        # None of the actual PII values may appear anywhere in the
        # generated prompt text.
        for value in record_values.values():
            assert value not in prompt

    def test_prompt_builder_includes_only_headers_and_labels(self):
        headers = ["Email", "Telefono"]
        labels = ["Correo Electrónico", "Teléfono de Contacto"]

        prompt = llm.build_mapping_prompt(headers, labels)

        for header in headers:
            assert header in prompt
        for label in labels:
            assert label in prompt

    def test_prompt_builder_rejects_a_records_kwarg_if_ever_passed(self):
        # Defensive: build_mapping_prompt's signature must not accept
        # row-value data at all -- calling it with an unexpected
        # values argument must fail loudly (TypeError), not silently
        # accept and embed it.
        with pytest.raises(TypeError):
            llm.build_mapping_prompt(
                ["Email"], ["Correo Electrónico"], record_values={"Email": "x@y.com"}
            )
