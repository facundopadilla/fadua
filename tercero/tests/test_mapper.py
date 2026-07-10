"""Tests for app.mapper — deterministic column->field mapping.

Proves that BOTH real sheet tabs map FULLY and deterministically to
BOTH real forms using only tokenization + a minimal synonym seed —
zero LLM involvement. Headers and labels are taken directly from
fixtures/tab_VENTAS.csv, fixtures/tab_MORA.csv, fixtures/form_ventas_fb.json,
and fixtures/form_mora_fb.json (via forms_schema.parse_fb).
"""

import json
from pathlib import Path

import pytest

from app.forms_schema import parse_fb
from app.mapper import map_columns
from app.sheets import parse_csv

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_fixture_json(name: str):
    return json.loads((FIXTURES / name).read_text())


def load_fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.fixture
def ventas_headers() -> list[str]:
    records = parse_csv(load_fixture_text("tab_VENTAS.csv"))
    return list(records[0].keys())


@pytest.fixture
def mora_headers() -> list[str]:
    records = parse_csv(load_fixture_text("tab_MORA.csv"))
    return list(records[0].keys())


@pytest.fixture
def ventas_fields():
    schema = parse_fb(load_fixture_json("form_ventas_fb.json"))
    return schema.fields


@pytest.fixture
def mora_fields():
    schema = parse_fb(load_fixture_json("form_mora_fb.json"))
    return schema.fields


class TestVentasMapping:
    def test_all_seven_columns_map_to_a_field(self, ventas_headers, ventas_fields):
        mapping = map_columns(ventas_headers, ventas_fields)
        assert len(mapping) == 7

    def test_id_cliente_maps_to_id_del_cliente(self, ventas_headers, ventas_fields):
        mapping = map_columns(ventas_headers, ventas_fields)
        assert mapping["ID_Cliente"].label == "ID del Cliente"

    def test_nombre_cliente_maps_to_nombre_completo(
        self, ventas_headers, ventas_fields
    ):
        # Genuine tokenization tie (shares "nombre" with "Nombre
        # Completo" AND "cliente" with "ID del Cliente" at equal
        # score) — must resolve via greedy assignment because
        # ID_Cliente locks "ID del Cliente" first with a stronger
        # (2-token) match.
        mapping = map_columns(ventas_headers, ventas_fields)
        assert mapping["Nombre_Cliente"].label == "Nombre Completo"

    def test_email_maps_to_correo_electronico_via_synonym(
        self, ventas_headers, ventas_fields
    ):
        # Zero shared tokens without the synonym seed
        # (email -> correo, electronico, mail).
        mapping = map_columns(ventas_headers, ventas_fields)
        assert mapping["Email"].label == "Correo Electrónico"

    def test_telefono_maps_to_telefono_de_contacto(
        self, ventas_headers, ventas_fields
    ):
        mapping = map_columns(ventas_headers, ventas_fields)
        assert mapping["Telefono"].label == "Teléfono de Contacto"

    def test_modelo_auto_maps_to_modelo_de_automovil(
        self, ventas_headers, ventas_fields
    ):
        mapping = map_columns(ventas_headers, ventas_fields)
        assert mapping["Modelo_Auto"].label == "Modelo de Automóvil"

    def test_valor_vehiculo_maps_to_valor_total_del_vehiculo(
        self, ventas_headers, ventas_fields
    ):
        mapping = map_columns(ventas_headers, ventas_fields)
        assert mapping["Valor_Vehiculo"].label == "Valor Total del Vehículo"

    def test_tipo_financiacion_maps_to_tipo_de_financiacion(
        self, ventas_headers, ventas_fields
    ):
        mapping = map_columns(ventas_headers, ventas_fields)
        assert mapping["Tipo_Financiacion"].label == "Tipo de Financiación"

    def test_every_required_field_is_mapped(self, ventas_headers, ventas_fields):
        mapping = map_columns(ventas_headers, ventas_fields)
        mapped_field_ids = {f.item_id for f in mapping.values()}
        required_field_ids = {f.item_id for f in ventas_fields if f.required}
        assert required_field_ids.issubset(mapped_field_ids)


class TestMoraMapping:
    def test_all_eight_columns_map_to_a_field(self, mora_headers, mora_fields):
        mapping = map_columns(mora_headers, mora_fields)
        assert len(mapping) == 8

    def test_id_cliente_maps_to_id_de_cliente_asociado(
        self, mora_headers, mora_fields
    ):
        mapping = map_columns(mora_headers, mora_fields)
        assert mapping["ID_Cliente"].label == "ID de Cliente Asociado"

    def test_nombre_cliente_maps_to_nombre_del_cliente(
        self, mora_headers, mora_fields
    ):
        mapping = map_columns(mora_headers, mora_fields)
        assert mapping["Nombre_Cliente"].label == "Nombre del Cliente"

    def test_valor_vehiculo_maps_to_valor_del_vehiculo(
        self, mora_headers, mora_fields
    ):
        mapping = map_columns(mora_headers, mora_fields)
        assert mapping["Valor_Vehiculo"].label == "Valor del Vehículo"

    def test_tipo_financiacion_maps_to_tipo_financiacion_field(
        self, mora_headers, mora_fields
    ):
        mapping = map_columns(mora_headers, mora_fields)
        assert mapping["Tipo_Financiacion"].label == "Tipo Financiación"

    def test_estado_pago_maps_to_estado_de_cuenta_actual(
        self, mora_headers, mora_fields
    ):
        # Genuine tokenization tie (shares "pago" with "Monto del
        # Último Pago Registrado" AND "estado" with "Estado de Cuenta
        # Actual" at equal score) — resolved via greedy assignment
        # because Ultimo_Pago_Monto locks the "pago" field first with
        # a stronger (3-token) match.
        mapping = map_columns(mora_headers, mora_fields)
        assert mapping["Estado_Pago"].label == "Estado de Cuenta Actual"

    def test_dias_atraso_maps_to_dias_de_atraso(self, mora_headers, mora_fields):
        mapping = map_columns(mora_headers, mora_fields)
        assert mapping["Dias_Atraso"].label == "Días de Atraso (Si aplica)"

    def test_ultimo_pago_monto_maps_to_monto_del_ultimo_pago(
        self, mora_headers, mora_fields
    ):
        mapping = map_columns(mora_headers, mora_fields)
        assert (
            mapping["Ultimo_Pago_Monto"].label
            == "Monto del Último Pago Registrado"
        )

    def test_requiere_cobranza_maps_to_requiere_accion_cobranza(
        self, mora_headers, mora_fields
    ):
        mapping = map_columns(mora_headers, mora_fields)
        assert (
            mapping["Requiere_Cobranza"].label
            == "Requiere Acción de Cobranza Legal"
        )

    def test_every_required_field_is_mapped(self, mora_headers, mora_fields):
        mapping = map_columns(mora_headers, mora_fields)
        mapped_field_ids = {f.item_id for f in mapping.values()}
        required_field_ids = {f.item_id for f in mora_fields if f.required}
        assert required_field_ids.issubset(mapped_field_ids)
