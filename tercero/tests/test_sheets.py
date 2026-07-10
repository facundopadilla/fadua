"""Tests for app.sheets — gviz CSV parsing (offline, no network).

Uses the real fixture CSVs (fixtures/tab_VENTAS.csv, fixtures/tab_MORA.csv)
which are raw gviz exports, dirty as-is (leading-space headers, dirty
currency values). parse_csv is pure text-in/list-out so these tests run
without any HTTP call.
"""

from pathlib import Path

import pytest

from app.sheets import parse_csv

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text()


class TestParseCsvVentas:
    def test_returns_four_records(self):
        records = parse_csv(load_fixture_text("tab_VENTAS.csv"))
        assert len(records) == 4

    def test_headers_are_stripped(self):
        records = parse_csv(load_fixture_text("tab_VENTAS.csv"))
        # " Valor_Vehiculo" (leading space) must become "Valor_Vehiculo"
        assert "Valor_Vehiculo" in records[0]
        assert " Valor_Vehiculo" not in records[0]

    def test_all_expected_headers_present(self):
        records = parse_csv(load_fixture_text("tab_VENTAS.csv"))
        expected = {
            "ID_Cliente",
            "Nombre_Cliente",
            "Email",
            "Telefono",
            "Modelo_Auto",
            "Valor_Vehiculo",
            "Tipo_Financiacion",
        }
        assert set(records[0].keys()) == expected

    def test_values_are_stripped(self):
        records = parse_csv(load_fixture_text("tab_VENTAS.csv"))
        # Raw cell is `" Fiat Cronos"`-free but currency has padding —
        # ensure the DictReader-level value itself has no surrounding
        # whitespace after our strip step (currency cleanup is
        # normalize.currency's job, not sheets.py's).
        assert records[0]["ID_Cliente"] == "FIAT-001"
        assert records[0]["Valor_Vehiculo"].strip() == records[0]["Valor_Vehiculo"]

    def test_first_record_values(self):
        records = parse_csv(load_fixture_text("tab_VENTAS.csv"))
        first = records[0]
        assert first["ID_Cliente"] == "FIAT-001"
        assert first["Nombre_Cliente"] == "Carlos Mendoza"
        assert first["Email"] == "carlos.m@mail.com"
        assert first["Telefono"] == "54119876543"
        assert first["Modelo_Auto"] == "Fiat Cronos"
        assert first["Valor_Vehiculo"] == "$ 18,500,000"
        assert first["Tipo_Financiacion"] == "Crédito Prendario"

    def test_all_ids_present_in_order(self):
        records = parse_csv(load_fixture_text("tab_VENTAS.csv"))
        assert [r["ID_Cliente"] for r in records] == [
            "FIAT-001",
            "FIAT-002",
            "FIAT-003",
            "FIAT-004",
        ]


class TestParseCsvMora:
    def test_returns_four_records(self):
        records = parse_csv(load_fixture_text("tab_MORA.csv"))
        assert len(records) == 4

    def test_headers_are_stripped(self):
        records = parse_csv(load_fixture_text("tab_MORA.csv"))
        assert "Valor_Vehiculo" in records[0]
        assert "Ultimo_Pago_Monto" in records[0]
        assert " Valor_Vehiculo" not in records[0]
        assert " Ultimo_Pago_Monto" not in records[0]

    def test_all_expected_headers_present(self):
        records = parse_csv(load_fixture_text("tab_MORA.csv"))
        expected = {
            "ID_Cliente",
            "Nombre_Cliente",
            "Valor_Vehiculo",
            "Tipo_Financiacion",
            "Estado_Pago",
            "Dias_Atraso",
            "Ultimo_Pago_Monto",
            "Requiere_Cobranza",
        }
        assert set(records[0].keys()) == expected

    def test_fiat_002_disguised_empty_value_preserved_raw(self):
        # parse_csv must NOT normalize — that's normalize.currency's
        # job. The raw dirty value must pass through untouched (aside
        # from the strip already applied on ingest).
        records = parse_csv(load_fixture_text("tab_MORA.csv"))
        fiat_002 = next(r for r in records if r["ID_Cliente"] == "FIAT-002")
        assert fiat_002["Ultimo_Pago_Monto"] == "$ -"

    def test_fiat_002_moroso_state(self):
        records = parse_csv(load_fixture_text("tab_MORA.csv"))
        fiat_002 = next(r for r in records if r["ID_Cliente"] == "FIAT-002")
        assert fiat_002["Estado_Pago"] == "Moroso"
        assert fiat_002["Requiere_Cobranza"] == "Sí"

    def test_fiat_001_al_dia_state_case_trap(self):
        # Sheet has "Al Día" (capital D) — the form option is "Al día".
        # sheets.py preserves the raw value; matching happens later in
        # normalize.match_option.
        records = parse_csv(load_fixture_text("tab_MORA.csv"))
        fiat_001 = next(r for r in records if r["ID_Cliente"] == "FIAT-001")
        assert fiat_001["Estado_Pago"] == "Al Día"

    def test_fiat_003_business_inconsistency_values_preserved(self):
        # FIAT-003: Moroso, 15 days late, but Requiere_Cobranza = "No".
        # sheets.py must preserve this as-is; the inconsistency is
        # handled downstream (runner.py logs an observation).
        records = parse_csv(load_fixture_text("tab_MORA.csv"))
        fiat_003 = next(r for r in records if r["ID_Cliente"] == "FIAT-003")
        assert fiat_003["Estado_Pago"] == "Moroso"
        assert fiat_003["Dias_Atraso"] == "15"
        assert fiat_003["Requiere_Cobranza"] == "No"

    def test_all_ids_present_in_order(self):
        records = parse_csv(load_fixture_text("tab_MORA.csv"))
        assert [r["ID_Cliente"] for r in records] == [
            "FIAT-001",
            "FIAT-002",
            "FIAT-003",
            "FIAT-004",
        ]
