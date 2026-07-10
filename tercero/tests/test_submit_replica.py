"""End-to-end LIVE-submit test against a local static HTML replica.

Drives the REAL production code path (app.runner.process_record ->
app.filler.fill_record, dry_run=False) against a hand-built 4-field
single-page form served by stdlib http.server on localhost — never
against docs.google.com or forms.gle. Safety is enforced by
`cfg.allowed_url_prefixes`, which points the navigation guard
(`app.filler._assert_allowed_domain`) exclusively at the ephemeral
127.0.0.1 URL for this test run.

Why there is no separate manual read-back assertion:
`fill_text_field` / `fill_radio_field` / `fill_dropdown_field` /
`fill_checkbox_field` (app/filler.py) already perform a read-back
assertion internally for every field and raise a `FormFillerError`
subclass (`ValidationBannerError` / `OptionMatchFailedError`) if the
DOM does not reflect the expected value. `process_record` catches
`FormFillerError` and returns that error's `.status` string instead of
ever reaching the submit-and-confirm code path. Therefore, asserting
`status == "SUBMITTED"` on the returned outcome already proves every
field passed its production read-back check — if any field's
read-back had failed, the outcome status would be something other
than "SUBMITTED" (e.g. "VALIDATION_BANNER" or "OPTION_MATCH_FAILED"),
never "SUBMITTED", since `filler.fill_record` only reaches
`submit_button.click()` after every field's fill handler returns
without raising.
"""

from __future__ import annotations

import http.server
import json
import threading
from functools import partial
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from app import runner
from app.config import Config
from app.forms_schema import Field, FormSchema
from app.results import already_done

pytestmark = pytest.mark.browser

REPLICA_DIR = Path(__file__).parent / "replica"


@pytest.fixture
def replica_server():
    """Serve tests/replica/ over stdlib http.server on an ephemeral port.

    Binds to port 0 so the OS assigns a free port, runs serve_forever()
    in a daemon background thread, and yields the base URL. Shuts the
    server down and joins the thread on teardown.
    """
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(REPLICA_DIR))
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.shutdown()
        thread.join()


def _build_schema() -> FormSchema:
    """Hand-built single-page FormSchema matching tests/replica/index.html.

    Exactly one page (schema.pages has length 1) so filler.fill_record's
    `total_pages > 1` intro-Siguiente branch is skipped, matching the
    replica's single-page layout (all 4 fields + Enviar visible on load,
    no intro card).
    """
    field_text = Field(
        item_id="111",
        entry_id="entry.111",
        label="Nombre del Cliente",
        type=0,
        required=True,
        options=[],
    )
    field_radio = Field(
        item_id="222",
        entry_id="entry.222",
        label="Estado de Cuenta",
        type=2,
        required=True,
        options=["Al día", "Moroso"],
    )
    field_dropdown = Field(
        item_id="333",
        entry_id="entry.333",
        label="Tipo de Financiación",
        type=3,
        required=True,
        options=["Plan de Ahorro", "Crédito Prendario", "Contado"],
    )
    field_checkbox = Field(
        item_id="444",
        entry_id="entry.444",
        label="Requiere Acción de Cobranza",
        type=4,
        required=False,
        options=[],
    )

    all_fields = [field_text, field_radio, field_dropdown, field_checkbox]
    return FormSchema(
        title="Replica Test Form",
        fields=all_fields,
        pages=[all_fields],
        page_labels=[""],
        ignored_types=set(),
    )


def _build_record_and_mapping(schema: FormSchema) -> tuple[dict[str, str], dict[str, Field]]:
    """Build a raw sheet-row `record` and column-header->Field `mapping`.

    Column headers are arbitrary (identity to the field label would
    work too, but distinct headers prove the mapping indirection is
    genuinely exercised, not just a same-string passthrough).

    The checkbox field ("Requiere Acción de Cobranza", type 4) is
    normalized by runner.normalize_record's field.type == 4 branch,
    which routes it through normalize.si_no() -> bool regardless of
    its label. The raw value here is "Sí" (CLAUDE.md's Sí/No boolean
    convention), NOT an arbitrary truthy string -- feeding anything
    si_no() doesn't recognize would now raise DirtyValueError, per the
    checkbox contract fill_checkbox_field enforces (requires an actual
    bool).
    """
    fields_by_label = {f.label: f for f in schema.fields}

    mapping = {
        "col_nombre": fields_by_label["Nombre del Cliente"],
        "col_estado": fields_by_label["Estado de Cuenta"],
        "col_financiacion": fields_by_label["Tipo de Financiación"],
        "col_cobranza": fields_by_label["Requiere Acción de Cobranza"],
    }
    record = {
        "ID_Cliente": "REPLICA-001",
        "col_nombre": "Juan Perez",
        "col_estado": "Moroso",
        "col_financiacion": "Credito Prendario",  # no accent -- exercises match_option folding
        "col_cobranza": "Sí",
    }
    return record, mapping


class TestLiveSubmitReplica:
    def test_process_record_submits_and_confirms(self, replica_server, tmp_path):
        base_url = replica_server
        schema = _build_schema()
        record, mapping = _build_record_and_mapping(schema)

        cfg = Config(
            runs_dir=str(tmp_path),
            allowed_url_prefixes=(base_url,),
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                outcome = runner.process_record(
                    browser=browser,
                    form_key="replica_test",
                    schema=schema,
                    url=f"{base_url}index.html",
                    record=record,
                    mapping=mapping,
                    cfg=cfg,
                    dry_run=False,
                    headed=False,
                    slow_mo=0,
                )
            finally:
                browser.close()

        # Terminal status proves the LIVE branch ran to completion:
        # every field's fill handler passed its internal read-back
        # assertion (otherwise a FormFillerError would have short-
        # circuited process_record to a non-SUBMITTED status), Enviar
        # was clicked, and validator.confirmation detected the
        # "formResponse" marker in the post-click URL.
        assert outcome["status"] == "SUBMITTED"
        assert outcome["id_cliente"] == "REPLICA-001"

        # Idempotency: the real results.jsonl checkpoint was written,
        # via the real results.append_result call inside process_record.
        results_path = tmp_path / "results.jsonl"
        assert results_path.exists()

        lines = [
            json.loads(line)
            for line in results_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        matching = [
            entry
            for entry in lines
            if entry["form"] == "replica_test"
            and entry["id_cliente"] == "REPLICA-001"
            and entry["status"] == "SUBMITTED"
        ]
        assert len(matching) == 1

        # End-to-end idempotency check using the real already_done
        # function against the exact (form, id_cliente, content_hash)
        # triple that was just written.
        content_hash_value = matching[0]["content_hash"]
        assert already_done(
            results_path, "replica_test", "REPLICA-001", content_hash_value
        )
