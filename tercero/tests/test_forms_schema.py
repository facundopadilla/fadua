"""Tests for app.forms_schema — FB_PUBLIC_LOAD_DATA_ parsing.

Assertions are pinned to the exact item IDs, entry IDs, labels, types,
required flags, and options documented in CLAUDE.md's verified form
schema tables. The fixtures under fixtures/*.json are the captured
FB_PUBLIC_LOAD_DATA_ payload (already parsed to a Python list), used
here as offline test data — at runtime the schema is parsed LIVE from
the form HTML.
"""

import json
from pathlib import Path

import pytest

from app.forms_schema import FormSchema, parse_fb

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def ventas_schema() -> FormSchema:
    return parse_fb(load_fixture("form_ventas_fb.json"))


@pytest.fixture
def mora_schema() -> FormSchema:
    return parse_fb(load_fixture("form_mora_fb.json"))


class TestVentasSchema:
    def test_title(self, ventas_schema: FormSchema):
        assert ventas_schema.title == "Registro de Ventas"

    def test_field_count(self, ventas_schema: FormSchema):
        # 7 answerable fields (3 section headers are not fields)
        assert len(ventas_schema.fields) == 7

    def test_page_count(self, ventas_schema: FormSchema):
        # Multi-page form: 3 sections -> 3 pages
        assert len(ventas_schema.pages) == 3

    def test_page_field_distribution(self, ventas_schema: FormSchema):
        assert len(ventas_schema.pages[0]) == 4  # DATOS DEL CLIENTE
        assert len(ventas_schema.pages[1]) == 2  # DATOS DE LA UNIDAD
        assert len(ventas_schema.pages[2]) == 1  # DATOS DE COMPRA

    def test_id_del_cliente_field(self, ventas_schema: FormSchema):
        field = ventas_schema.fields[0]
        assert field.item_id == "999998362"
        assert field.entry_id == "entry.814069894"
        assert field.label == "ID del Cliente"
        assert field.type == 0
        assert field.required is True
        assert field.options == []

    def test_nombre_completo_field(self, ventas_schema: FormSchema):
        field = ventas_schema.fields[1]
        assert field.item_id == "1400945540"
        assert field.entry_id == "entry.657237802"
        assert field.label == "Nombre Completo"
        assert field.type == 0
        assert field.required is True

    def test_correo_electronico_field(self, ventas_schema: FormSchema):
        field = ventas_schema.fields[2]
        assert field.item_id == "1881411619"
        assert field.entry_id == "entry.1855970967"
        assert field.label == "Correo Electrónico"
        assert field.type == 0
        assert field.required is True

    def test_telefono_de_contacto_field(self, ventas_schema: FormSchema):
        field = ventas_schema.fields[3]
        assert field.item_id == "146186431"
        assert field.entry_id == "entry.136415275"
        assert field.label == "Teléfono de Contacto"
        assert field.type == 0
        assert field.required is True

    def test_modelo_de_automovil_field(self, ventas_schema: FormSchema):
        field = ventas_schema.fields[4]
        assert field.item_id == "667185096"
        assert field.entry_id == "entry.2099080465"
        assert field.label == "Modelo de Automóvil"
        assert field.type == 3  # dropdown
        assert field.required is True
        assert field.options == [
            "Fiat Cronos",
            "600",
            "Fiat Strada",
            "Fiat Fastback",
            "Fiat Pulse",
        ]

    def test_valor_total_del_vehiculo_field(self, ventas_schema: FormSchema):
        field = ventas_schema.fields[5]
        assert field.item_id == "1583087190"
        assert field.entry_id == "entry.1493778692"
        assert field.label == "Valor Total del Vehículo"
        assert field.type == 0
        assert field.required is True

    def test_tipo_de_financiacion_field(self, ventas_schema: FormSchema):
        field = ventas_schema.fields[6]
        assert field.item_id == "34738716"
        assert field.entry_id == "entry.487326979"
        assert field.label == "Tipo de Financiación"
        assert field.type == 2  # radio
        assert field.required is True
        assert field.options == [
            "Crédito Prendario",
            "Plan de Ahorro",
            "Contado / Directo",
        ]


class TestMoraSchema:
    def test_title(self, mora_schema: FormSchema):
        assert mora_schema.title == "Control de Morosidad y Pagos"

    def test_field_count(self, mora_schema: FormSchema):
        assert len(mora_schema.fields) == 8

    def test_page_count(self, mora_schema: FormSchema):
        # Single-page form: zero type-8 items -> exactly one page.
        assert len(mora_schema.pages) == 1

    def test_all_fields_on_one_page(self, mora_schema: FormSchema):
        assert len(mora_schema.pages[0]) == 8

    def test_id_cliente_asociado_field(self, mora_schema: FormSchema):
        field = mora_schema.fields[0]
        assert field.item_id == "88995149"
        assert field.entry_id == "entry.1568255357"
        assert field.label == "ID de Cliente Asociado"
        assert field.type == 0
        assert field.required is True

    def test_nombre_del_cliente_field_not_required(self, mora_schema: FormSchema):
        field = mora_schema.fields[1]
        assert field.item_id == "158888317"
        assert field.entry_id == "entry.1088714979"
        assert field.label == "Nombre del Cliente"
        assert field.type == 0
        assert field.required is False

    def test_valor_del_vehiculo_field(self, mora_schema: FormSchema):
        field = mora_schema.fields[2]
        assert field.item_id == "888542449"
        assert field.entry_id == "entry.230995405"
        assert field.label == "Valor del Vehículo"
        assert field.type == 0
        assert field.required is True

    def test_tipo_financiacion_field_is_dropdown(self, mora_schema: FormSchema):
        # Cross-check trap: in Form 2, Financiación is a DROPDOWN
        # (opposite of Form 1, where it's radio).
        field = mora_schema.fields[3]
        assert field.item_id == "169419756"
        assert field.entry_id == "entry.191355245"
        assert field.label == "Tipo Financiación"
        assert field.type == 3
        assert field.required is True
        assert field.options == [
            "Plan de Ahorro",
            "Crédito Prendario",
            "Contado / Directo",
        ]

    def test_estado_de_cuenta_field_is_radio(self, mora_schema: FormSchema):
        # Cross-check trap: in Form 2, Estado is RADIO (opposite of
        # Form 1, where Modelo is dropdown).
        field = mora_schema.fields[4]
        assert field.item_id == "101891614"
        assert field.entry_id == "entry.1430363473"
        assert field.label == "Estado de Cuenta Actual"
        assert field.type == 2
        assert field.required is True
        assert field.options == ["Al día", "Moroso"]

    def test_dias_de_atraso_field(self, mora_schema: FormSchema):
        field = mora_schema.fields[5]
        assert field.item_id == "250795746"
        assert field.entry_id == "entry.1824761040"
        assert field.label == "Días de Atraso (Si aplica)"
        assert field.type == 0
        assert field.required is True

    def test_monto_del_ultimo_pago_field(self, mora_schema: FormSchema):
        field = mora_schema.fields[6]
        assert field.item_id == "1075955762"
        assert field.entry_id == "entry.1373856247"
        assert field.label == "Monto del Último Pago Registrado"
        assert field.type == 0
        assert field.required is True

    def test_requiere_accion_cobranza_field_checkbox_not_required(
        self, mora_schema: FormSchema
    ):
        field = mora_schema.fields[7]
        assert field.item_id == "1137417183"
        assert field.entry_id == "entry.76508310"
        assert field.label == "Requiere Acción de Cobranza Legal"
        assert field.type == 4  # checkbox
        assert field.required is False
        assert field.options == ["Sí, activar protocolo de cobranza legal"]


class TestPageLabels:
    """schema.page_labels carries the section-header text that
    introduced each page, so filler.py can assert the expected section
    is on screen before AND after each "Siguiente" click.
    """

    def test_ventas_page_labels_match_section_headers(self, ventas_schema):
        assert ventas_schema.page_labels == [
            "DATOS DEL CLIENTE",
            "DATOS DE LA UNIDAD",
            "DATOS DE COMPRA",
        ]

    def test_mora_single_page_has_no_section_label(self, mora_schema):
        # Form 2 has zero type-8 items, so its one page has no
        # preceding section header -- represented as an empty string,
        # never None (callers can always index page_labels safely).
        assert mora_schema.page_labels == [""]

    def test_page_labels_length_matches_pages_length(
        self, ventas_schema, mora_schema
    ):
        assert len(ventas_schema.page_labels) == len(ventas_schema.pages)
        assert len(mora_schema.page_labels) == len(mora_schema.pages)


class TestPageHistoryIsNotSourceOfTruth:
    def test_ventas_page_count_ignores_raw_page_history_array(self, ventas_schema):
        # Verified trap: the FB page-history array is [2] regardless of
        # real page count. Page structure MUST derive from type-8 items,
        # never from that array. Form 1 has 3 real pages despite [2].
        assert len(ventas_schema.pages) == 3

    def test_mora_page_count_ignores_raw_page_history_array(self, mora_schema):
        # Form 2 has 1 real page (zero type-8 items) despite the same
        # [2] page-history array appearing in its raw payload.
        assert len(mora_schema.pages) == 1


class TestParseFbAcceptsBothInputShapes:
    def test_accepts_parsed_json_list(self):
        # parse_fb must accept an already-parsed JSON list (as used
        # above via load_fixture + parse_fb), not just raw HTML.
        data = load_fixture("form_mora_fb.json")
        schema = parse_fb(data)
        assert schema.title == "Control de Morosidad y Pagos"

    def test_accepts_raw_html_containing_fb_public_load_data(self):
        raw_json = json.dumps(load_fixture("form_ventas_fb.json"))
        html = f"""
        <html><head></head><body>
        <script>
        var FB_PUBLIC_LOAD_DATA_ = {raw_json};
        </script>
        </body></html>
        """
        schema = parse_fb(html)
        assert schema.title == "Registro de Ventas"
        assert len(schema.fields) == 7
