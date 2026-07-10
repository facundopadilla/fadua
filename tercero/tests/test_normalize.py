"""Tests for app.normalize — deterministic value parsers.

Every case here is a real trap value pulled directly from
fixtures/tab_VENTAS.csv and fixtures/tab_MORA.csv (see CLAUDE.md's
"Data traps" table). No synthetic values.
"""

import pytest

from app.normalize import currency, fold, match_option, si_no


class TestCurrency:
    def test_dirty_currency_with_thousands_commas(self):
        # tab_VENTAS.csv FIAT-001 Valor_Vehiculo
        assert currency(" $ 18,500,000 ") == "18500000"

    def test_dirty_currency_smaller_amount(self):
        # tab_MORA.csv FIAT-001 Ultimo_Pago_Monto
        assert currency(" $ 450,000 ") == "450000"

    def test_disguised_empty_required_value(self):
        # tab_MORA.csv FIAT-002 Ultimo_Pago_Monto — the disguised-empty trap.
        # Must normalize to an empty string, never to "0".
        assert currency(" $ -   ") == ""

    def test_decimal_comma_dot_thousands(self):
        # Dot as thousands separator, comma as decimal separator.
        assert currency("$ 1.234,56") == "1234.56"

    def test_decimal_dot_comma_thousands(self):
        # Comma as thousands separator, dot as decimal separator.
        assert currency("$ 1,234.56") == "1234.56"

    def test_plain_number_passthrough(self):
        assert currency("450000") == "450000"

    def test_other_ventas_values(self):
        assert currency(" $ 22,100,000 ") == "22100000"
        assert currency(" $ 26,400,000 ") == "26400000"
        assert currency(" $ 16,800,000 ") == "16800000"

    def test_other_mora_values(self):
        assert currency(" $ 320,000 ") == "320000"
        assert currency(" $ 380,000 ") == "380000"

    def test_es_ar_single_separator_trailing_two_digits_is_decimal(self):
        # Synthetic (not a fixture value): pins the es-AR disambiguation
        # rule documented in currency()'s docstring — a single comma
        # with a 1-2 digit trailing group is treated as decimal.
        assert currency("$ 12,50") == "12.50"

    def test_es_ar_single_separator_trailing_three_digits_is_thousands(self):
        # Synthetic (not a fixture value): pins the es-AR disambiguation
        # rule — a single dot with a 3-digit trailing group is treated
        # as a thousands separator, not decimal.
        assert currency("$ 1.500") == "1500"


class TestSiNo:
    def test_si_with_accent(self):
        assert si_no("Sí") is True

    def test_si_without_accent(self):
        assert si_no("Si") is True

    def test_si_lowercase_with_accent(self):
        assert si_no("sí") is True

    def test_no_uppercase(self):
        assert si_no("No") is False

    def test_no_lowercase(self):
        assert si_no("no") is False

    def test_unrecognized_returns_none(self):
        assert si_no("Tal vez") is None

    def test_empty_returns_none(self):
        assert si_no("") is None

    def test_real_fixture_values(self):
        # tab_MORA.csv Requiere_Cobranza column: "No", "Sí", "No", "No"
        assert si_no("No") is False
        assert si_no("Sí") is True


class TestMatchOption:
    def test_case_and_accent_insensitive_match(self):
        # Sheet "Al Día" vs form option "Al día" (CLAUDE.md trap #1)
        assert match_option("Al Día", ["Al día", "Moroso"]) == "Al día"

    def test_exact_match(self):
        assert match_option("Moroso", ["Al día", "Moroso"]) == "Moroso"

    def test_whitespace_collapsed_match(self):
        assert match_option("  Al   Día  ", ["Al día", "Moroso"]) == "Al día"

    def test_no_match_returns_none(self):
        assert match_option("Desconocido", ["Al día", "Moroso"]) is None

    def test_ventas_financiacion_options(self):
        options = ["Crédito Prendario", "Plan de Ahorro", "Contado / Directo"]
        assert match_option("Crédito Prendario", options) == "Crédito Prendario"
        assert match_option("credito prendario", options) == "Crédito Prendario"
        assert match_option("Contado / Directo", options) == "Contado / Directo"

    def test_mora_financiacion_options(self):
        options = ["Plan de Ahorro", "Crédito Prendario", "Contado / Directo"]
        assert match_option("Plan de Ahorro", options) == "Plan de Ahorro"

    def test_modelo_auto_options(self):
        options = ["Fiat Cronos", "600", "Fiat Strada", "Fiat Fastback", "Fiat Pulse"]
        assert match_option("Fiat Cronos", options) == "Fiat Cronos"
        assert match_option("fiat pulse", options) == "Fiat Pulse"
        assert match_option("600", options) == "600"


class TestFold:
    def test_lowercases(self):
        assert fold("HOLA") == "hola"

    def test_strips_accents(self):
        assert fold("Día") == "dia"
        assert fold("Financiación") == "financiacion"

    def test_collapses_whitespace(self):
        assert fold("  al   dia  ") == "al dia"

    def test_combined(self):
        assert fold("  Al   DÍA  ") == "al dia"
