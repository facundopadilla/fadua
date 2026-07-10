"""Tests for app.runner — per-record orchestration and error taxonomy.

Uses minimal fake Playwright objects (browser/context/page stand-ins)
so `process_record` can be exercised without a real browser, focusing
on error-code routing and the pre-browser gates it owns.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import errors, runner
from app.config import Config
from app.forms_schema import Field, FormSchema


class _FakePage:
    """Just enough surface for process_record's happy-path calls."""

    def goto(self, url):
        pass

    def wait_for_load_state(self, state):
        pass

    def screenshot(self, path):
        Path(path).write_bytes(b"")


class _FakeContext:
    def __init__(self):
        self.page = _FakePage()

    def new_page(self):
        return self.page

    def close(self):
        pass


class _FakeBrowser:
    def __init__(self):
        self.context = _FakeContext()

    def new_context(self):
        return self.context


def _build_currency_field_schema() -> FormSchema:
    """Single required field whose label is a known currency field
    (see runner._CURRENCY_FIELD_LABELS)."""
    field = Field(
        item_id="1",
        entry_id="entry.1",
        label="Valor del Vehículo",
        type=0,
        required=True,
        options=[],
    )
    return FormSchema(
        title="Fake Form",
        fields=[field],
        pages=[[field]],
        page_labels=[""],
        ignored_types=set(),
    )


def _build_single_field_schema() -> FormSchema:
    field = Field(
        item_id="1",
        entry_id="entry.1",
        label="ID del Cliente",
        type=0,
        required=True,
        options=[],
    )
    return FormSchema(
        title="Fake Form",
        fields=[field],
        pages=[[field]],
        page_labels=[""],
        ignored_types=set(),
    )


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(runs_dir=str(tmp_path))


class TestUnexpectedExceptionTaxonomy:
    def test_generic_exception_is_unknown_error_not_timeout(
        self, monkeypatch, cfg
    ):
        # A KeyError (or any exception that isn't a FormFillerError or
        # Playwright's TimeoutError) must be reported as UNKNOWN_ERROR,
        # never mislabeled as TIMEOUT.
        def _raise_key_error(*args, **kwargs):
            raise KeyError("boom")

        monkeypatch.setattr(runner.filler, "fill_record", _raise_key_error)

        schema = _build_single_field_schema()
        record = {"ID_Cliente": "FIAT-KEYERR", "Nombre_Cliente": "x"}
        mapping = {"Nombre_Cliente": schema.fields[0]}

        outcome = runner.process_record(
            browser=_FakeBrowser(),
            form_key="ventas",
            schema=schema,
            url="https://docs.google.com/fake",
            record=record,
            mapping=mapping,
            cfg=cfg,
            dry_run=True,
            headed=False,
            slow_mo=0,
        )

        assert outcome["status"] == "UNKNOWN_ERROR"

        results_path = Path(cfg.runs_dir) / "results.jsonl"
        lines = [
            json.loads(line)
            for line in results_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert lines[-1]["status"] == "UNKNOWN_ERROR"

    def test_playwright_timeout_error_is_timeout(self, monkeypatch, cfg):
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        def _raise_timeout(*args, **kwargs):
            raise PlaywrightTimeoutError("Timeout 5000ms exceeded")

        monkeypatch.setattr(runner.filler, "fill_record", _raise_timeout)

        schema = _build_single_field_schema()
        record = {"ID_Cliente": "FIAT-TIMEOUT", "Nombre_Cliente": "x"}
        mapping = {"Nombre_Cliente": schema.fields[0]}

        outcome = runner.process_record(
            browser=_FakeBrowser(),
            form_key="ventas",
            schema=schema,
            url="https://docs.google.com/fake",
            record=record,
            mapping=mapping,
            cfg=cfg,
            dry_run=True,
            headed=False,
            slow_mo=0,
        )

        assert outcome["status"] == errors.TimeoutFillerError.status


def _build_two_field_schema() -> FormSchema:
    """A required text field plus a second required field with no
    column mapped to it — the SCHEMA_DRIFT / LLM_ERROR scenario."""
    mapped_field = Field(
        item_id="1",
        entry_id="entry.1",
        label="ID del Cliente",
        type=0,
        required=True,
        options=[],
    )
    drifted_field = Field(
        item_id="2",
        entry_id="entry.2",
        label="Campo Nuevo Sin Mapear",
        type=0,
        required=True,
        options=[],
    )
    fields = [mapped_field, drifted_field]
    return FormSchema(
        title="Fake Form",
        fields=fields,
        pages=[fields],
        page_labels=[""],
        ignored_types=set(),
    )


class TestSchemaDriftGate:
    def test_required_field_with_no_mapped_column_is_schema_drift(self, cfg):
        schema = _build_two_field_schema()
        mapped_field, _drifted_field = schema.fields
        # Only "ID del Cliente" has a mapped column; "Campo Nuevo Sin
        # Mapear" has NO header pointing to it at all.
        mapping = {"ID_Cliente": mapped_field}
        record = {"ID_Cliente": "FIAT-DRIFT", "Otra_Columna": "x"}

        outcome = runner.process_record(
            browser=_FakeBrowser(),
            form_key="ventas",
            schema=schema,
            url="https://docs.google.com/fake",
            record=record,
            mapping=mapping,
            cfg=cfg,
            dry_run=True,
            headed=False,
            slow_mo=0,
        )

        assert outcome["status"] == errors.SchemaDriftError.status
        assert "Campo Nuevo Sin Mapear" in outcome["detail"]
        assert "Otra_Columna" in outcome["detail"]  # available headers listed

    def test_mapped_but_empty_value_is_still_skipped_required_empty(self, cfg):
        # Regression guard: a field that IS mapped but whose value is
        # empty after normalization must remain SKIPPED_REQUIRED_EMPTY,
        # not SCHEMA_DRIFT.
        field = Field(
            item_id="1",
            entry_id="entry.1",
            label="ID del Cliente",
            type=0,
            required=True,
            options=[],
        )
        schema = FormSchema(
            title="Fake Form",
            fields=[field],
            pages=[[field]],
            page_labels=[""],
            ignored_types=set(),
        )
        mapping = {"ID_Cliente": field}
        record = {"ID_Cliente": ""}

        outcome = runner.process_record(
            browser=_FakeBrowser(),
            form_key="ventas",
            schema=schema,
            url="https://docs.google.com/fake",
            record=record,
            mapping=mapping,
            cfg=cfg,
            dry_run=True,
            headed=False,
            slow_mo=0,
        )

        assert outcome["status"] == errors.SkippedRequiredEmptyError.status


class TestLlmErrorGate:
    def test_unmapped_required_field_due_to_llm_failure_is_llm_error(self, cfg):
        schema = _build_two_field_schema()
        mapped_field, drifted_field = schema.fields
        mapping = {"ID_Cliente": mapped_field}
        record = {"ID_Cliente": "FIAT-LLMERR", "Otra_Columna": "x"}

        # Simulates mapper.map_columns having populated llm_failed_labels
        # after llm.suggest_mapping raised for this exact field.
        llm_failed_labels = {drifted_field.label}

        outcome = runner.process_record(
            browser=_FakeBrowser(),
            form_key="ventas",
            schema=schema,
            url="https://docs.google.com/fake",
            record=record,
            mapping=mapping,
            cfg=cfg,
            dry_run=True,
            headed=False,
            slow_mo=0,
            llm_failed_labels=llm_failed_labels,
        )

        assert outcome["status"] == errors.LlmError.status
        assert drifted_field.label in outcome["detail"]

    def test_map_columns_llm_failure_populates_failed_labels_and_never_raises(
        self, monkeypatch
    ):
        from app import llm as llm_module
        from app.mapper import map_columns

        monkeypatch.setattr(llm_module, "is_configured", lambda: True)

        def _raise(*args, **kwargs):
            raise RuntimeError("provider down")

        monkeypatch.setattr(llm_module, "suggest_mapping", _raise)

        schema = _build_two_field_schema()
        headers = ["ID_Cliente"]  # "Campo Nuevo Sin Mapear" has no column at all

        llm_failed_labels: set[str] = set()
        # Must NOT raise even though suggest_mapping raises internally.
        mapping = map_columns(
            headers, schema.fields, llm_failed_labels=llm_failed_labels
        )

        assert "Campo Nuevo Sin Mapear" in llm_failed_labels
        assert len(mapping) == 1  # only the deterministic match, LLM contributed nothing

    def test_map_columns_llm_failure_batch_continues_for_other_headers(
        self, monkeypatch
    ):
        # The regression this guards against: a raising LLM call must
        # not abort map_columns (and therefore run_form) entirely --
        # the deterministic matches already found must still be
        # returned.
        from app import llm as llm_module
        from app.mapper import map_columns

        monkeypatch.setattr(llm_module, "is_configured", lambda: True)
        monkeypatch.setattr(
            llm_module,
            "suggest_mapping",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        schema = _build_two_field_schema()
        headers = ["ID_Cliente"]

        # Must not raise.
        mapping = map_columns(headers, schema.fields)
        assert mapping["ID_Cliente"].label == "ID del Cliente"


class TestDirtyValueGate:
    """runner.normalize_record raises DirtyValueError for unparseable
    currency values; process_record catches it and reports DIRTY_VALUE
    without opening a browser."""

    @pytest.mark.parametrize(
        "raw_value",
        ["$ abc", "N/D", "$ -500", "$ 1.2.3,4,5"],
    )
    def test_normalize_record_raises_dirty_value_error(self, raw_value):
        schema = _build_currency_field_schema()
        field = schema.fields[0]
        mapping = {"Valor_Vehiculo": field}
        record = {"Valor_Vehiculo": raw_value}

        with pytest.raises(errors.DirtyValueError):
            runner.normalize_record(record, mapping)

    @pytest.mark.parametrize(
        "raw_value",
        ["$ abc", "N/D", "$ -500", "$ 1.2.3,4,5"],
    )
    def test_process_record_reports_dirty_value_no_browser(self, cfg, raw_value):
        schema = _build_currency_field_schema()
        field = schema.fields[0]
        mapping = {"Valor_Vehiculo": field}
        record = {"ID_Cliente": "FIAT-DIRTY", "Valor_Vehiculo": raw_value}

        # A browser stand-in whose new_context() would raise if ever
        # called -- proves the dirty-value gate short-circuits BEFORE
        # any browser interaction, same guarantee as the completeness
        # gate.
        class _BrowserThatMustNotBeUsed:
            def new_context(self):
                raise AssertionError(
                    "process_record must not open a browser for a DIRTY_VALUE record"
                )

        outcome = runner.process_record(
            browser=_BrowserThatMustNotBeUsed(),
            form_key="mora",
            schema=schema,
            url="https://docs.google.com/fake",
            record=record,
            mapping=mapping,
            cfg=cfg,
            dry_run=True,
            headed=False,
            slow_mo=0,
        )

        assert outcome["status"] == errors.DirtyValueError.status
        assert outcome["id_cliente"] == "FIAT-DIRTY"

        results_path = Path(cfg.runs_dir) / "results.jsonl"
        lines = [
            json.loads(line)
            for line in results_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert lines[-1]["status"] == "DIRTY_VALUE"

    def test_existing_fixture_currency_values_still_pass(self):
        # Regression guard: real, clean fixture currency values (see
        # test_normalize.py) must NOT be flagged as dirty.
        schema = _build_currency_field_schema()
        field = schema.fields[0]
        mapping = {"Valor_Vehiculo": field}

        clean_raw_values = [" $ 18,500,000 ", " $ 450,000 ", "$ 1.234,56", "450000"]
        for raw_value in clean_raw_values:
            record = {"Valor_Vehiculo": raw_value}
            normalized = runner.normalize_record(record, mapping)
            assert normalized[field.label] != ""

    def test_disguised_empty_currency_is_not_dirty_value(self):
        # The disguised-empty trap (CLAUDE.md trap #2) must still
        # normalize to "" and be caught by the completeness gate
        # (SKIPPED_REQUIRED_EMPTY), NOT raise DirtyValueError.
        schema = _build_currency_field_schema()
        field = schema.fields[0]
        mapping = {"Valor_Vehiculo": field}
        record = {"Valor_Vehiculo": " $ -   "}

        normalized = runner.normalize_record(record, mapping)
        assert normalized[field.label] == ""


class TestSubmitUnconfirmedBlocksReprocessing:
    """process_record must treat a prior SUBMIT_UNCONFIRMED entry as
    blocking (same idempotency effect as SUBMITTED) and report it as
    needing manual review, never as a silent generic skip."""

    def test_prior_submit_unconfirmed_blocks_and_reports_manual_review(self, cfg):
        from app import results

        schema = _build_single_field_schema()
        field = schema.fields[0]
        mapping = {"Nombre_Cliente": field}
        record = {"ID_Cliente": "FIAT-REVIEW", "Nombre_Cliente": "Carlos Mendoza"}

        normalized = runner.normalize_record(record, mapping)
        values_for_hash = {k: str(v) for k, v in sorted(normalized.items())}
        hash_value = results.content_hash(values_for_hash)

        results_path = Path(cfg.runs_dir) / "results.jsonl"
        results.append_result(
            results_path,
            form="ventas",
            id_cliente="FIAT-REVIEW",
            content_hash_value=hash_value,
            status="SUBMIT_UNCONFIRMED",
            detail="no confirmation observed",
            evidence="runs/fiat-review-error.png",
        )

        class _BrowserThatMustNotBeUsed:
            def new_context(self):
                raise AssertionError(
                    "process_record must not open a browser for a "
                    "blocked SUBMIT_UNCONFIRMED record"
                )

        outcome = runner.process_record(
            browser=_BrowserThatMustNotBeUsed(),
            form_key="ventas",
            schema=schema,
            url="https://docs.google.com/fake",
            record=record,
            mapping=mapping,
            cfg=cfg,
            dry_run=True,
            headed=False,
            slow_mo=0,
        )

        # Must NOT be re-processed, and must NOT be the generic
        # "ALREADY_DONE" status used for a confirmed SUBMITTED record --
        # it needs to be visibly distinguishable so a human reviews it.
        assert outcome["status"] != "SUBMITTED"
        assert outcome["status"] == "NEEDS_MANUAL_REVIEW"
        assert "review" in outcome["detail"].lower()


def _build_checkbox_field_schema(label: str = "Requiere Acción de Cobranza Legal") -> FormSchema:
    field = Field(
        item_id="1",
        entry_id="entry.1",
        label=label,
        type=4,
        required=False,
        options=[],
    )
    return FormSchema(
        title="Fake Form",
        fields=[field],
        pages=[[field]],
        page_labels=[""],
        ignored_types=set(),
    )


class TestCheckboxNormalizationByFieldType:
    """runner.normalize_record normalizes ANY checkbox field (field.type
    == 4) via si_no(), regardless of its label -- not just the one
    label previously hardcoded in the removed
    _BOOLEAN_CHECKBOX_FIELD_LABELS allow-list."""

    def test_si_normalizes_to_true(self):
        schema = _build_checkbox_field_schema()
        field = schema.fields[0]
        mapping = {"Requiere_Cobranza": field}
        normalized = runner.normalize_record({"Requiere_Cobranza": "Sí"}, mapping)
        assert normalized[field.label] is True

    def test_no_normalizes_to_false(self):
        schema = _build_checkbox_field_schema()
        field = schema.fields[0]
        mapping = {"Requiere_Cobranza": field}
        normalized = runner.normalize_record({"Requiere_Cobranza": "No"}, mapping)
        assert normalized[field.label] is False

    def test_empty_value_normalizes_to_false(self):
        schema = _build_checkbox_field_schema()
        field = schema.fields[0]
        mapping = {"Requiere_Cobranza": field}
        normalized = runner.normalize_record({"Requiere_Cobranza": ""}, mapping)
        assert normalized[field.label] is False

    def test_unrecognized_value_raises_dirty_value_error(self):
        schema = _build_checkbox_field_schema()
        field = schema.fields[0]
        mapping = {"Requiere_Cobranza": field}
        with pytest.raises(errors.DirtyValueError):
            runner.normalize_record({"Requiere_Cobranza": "Tal vez"}, mapping)

    def test_works_for_a_differently_labeled_checkbox_field(self):
        # The old label allow-list only recognized ONE hardcoded label
        # ("Requiere Acción de Cobranza Legal"). Normalization must now
        # work identically for ANY checkbox field by its type, proving
        # the label allow-list is truly gone.
        schema = _build_checkbox_field_schema(label="Acepta Términos y Condiciones")
        field = schema.fields[0]
        mapping = {"Acepta_TyC": field}
        normalized = runner.normalize_record({"Acepta_TyC": "Sí"}, mapping)
        assert normalized[field.label] is True

    def test_label_allowlist_constant_no_longer_exists(self):
        # Explicit regression guard that the allow-list was actually
        # removed, not just bypassed.
        assert not hasattr(runner, "_BOOLEAN_CHECKBOX_FIELD_LABELS")
