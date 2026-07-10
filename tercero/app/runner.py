"""Orchestrates one record end-to-end, and loops over a form's records.

Per-record flow (specs.md):
    read sheet row -> normalize -> completeness gate (missing required:
    skip+report, no browser) -> fill field by field with read-back ->
    assert section on both sides of each "Siguiente" -> pre-submit
    validation -> Enviar -> assert confirmation -> JSONL + evidence

One BrowserContext per record: no state (cookies, autofill, residual
fields) leaks between records or forms.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app import config as config_module
from app import errors
from app import filler
from app import forms_schema
from app import mapper
from app import results
from app import sheets
from app.normalize import currency, fold, match_option, si_no

if TYPE_CHECKING:
    from app.config import Config
    from app.forms_schema import Field, FormSchema

logger = logging.getLogger("fadua.runner")

# Field labels whose raw value is a currency amount and must go
# through normalize.currency. Kept as an explicit allow-list rather
# than sniffed from the label, since currency detection from free text
# is exactly the kind of guessing this codebase avoids.
_CURRENCY_FIELD_LABELS = {
    "Valor Total del Vehículo",
    "Valor del Vehículo",
    "Monto del Último Pago Registrado",
}

# Checkbox field type code (see CLAUDE.md "FB field type codes").
# Every checkbox field (not just the one label this system happens to
# have today) is normalized identically: its raw value goes through
# si_no() -> bool. Deciding by field.type, not by a label allow-list,
# means a future second checkbox field is handled correctly with no
# code change -- the allow-list approach silently skipped normalization
# (and the fill_checkbox_field type contract) for any checkbox field
# whose label wasn't hardcoded into the set.
_CHECKBOX_FIELD_TYPE = 4

# FIAT-003-style business inconsistency: Moroso + Requiere_Cobranza=No.
_ESTADO_FIELD_LABEL = "Estado de Cuenta Actual"
_MOROSO_OPTION = "Moroso"
_COBRANZA_FIELD_LABEL = "Requiere Acción de Cobranza Legal"

# A clean, normalize.currency()-produced value must be a plain
# non-negative integer or decimal string ("18500000", "1234.56"). An
# empty string ("") is the disguised-empty case (handled separately by
# the completeness gate, not here) and is intentionally NOT matched by
# this pattern. Anything else non-empty (unparseable garbage like
# "abc", "N/D", or a negative amount, which is nonsensical on this
# domain) is a dirty value that must never be filled into a form.
_CLEAN_CURRENCY_PATTERN = re.compile(r"^\d+(\.\d+)?$")


def normalize_record(
    record: dict[str, str], mapping: dict[str, "Field"]
) -> dict[str, object]:
    """Normalize raw sheet values into field-label-keyed values.

    Returns a dict keyed by FIELD LABEL (not column header), with
    values normalized per field type:
    - currency fields -> normalize.currency() (may be ""); a non-empty
      result that isn't a clean numeric string ("18500000", "1234.56")
      raises DirtyValueError -- e.g. "$ abc", "N/D", "$ -500" (negative
      amounts are nonsensical on this domain), or "$ 1.2.3,4,5"
    - any checkbox field (field.type == 4) -> normalize.si_no() -> bool;
      an unrecognized non-empty value (si_no() returns None) raises
      DirtyValueError -- an empty raw value normalizes to False (no
      "No" option to check, same as an explicit "No")
    - radio/dropdown fields -> normalize.match_option() -> canonical
      option string, or None if no match
    - everything else -> the raw stripped string, unchanged

    Raises DirtyValueError (see errors.py) on the first dirty currency
    or checkbox value encountered. The caller (process_record) catches
    this and reports DIRTY_VALUE, skipping the record without opening a
    browser -- never fills an unparseable value into a required field.
    """
    normalized: dict[str, object] = {}

    for header, field in mapping.items():
        raw_value = record.get(header, "")

        if field.type == _CHECKBOX_FIELD_TYPE:
            parsed = si_no(raw_value)
            if parsed is None and raw_value.strip() != "":
                raise errors.DirtyValueError(
                    f"Unparseable checkbox value for '{field.label}': {raw_value!r}"
                )
            normalized[field.label] = bool(parsed)
            continue

        if field.label in _CURRENCY_FIELD_LABELS:
            clean_value = currency(raw_value)
            if clean_value != "" and not _CLEAN_CURRENCY_PATTERN.match(clean_value):
                raise errors.DirtyValueError(
                    f"Unparseable currency value for '{field.label}': "
                    f"{raw_value!r} -> {clean_value!r}"
                )
            normalized[field.label] = clean_value
            continue

        if field.options:
            matched = match_option(raw_value, field.options)
            normalized[field.label] = matched if matched is not None else raw_value
            continue

        normalized[field.label] = raw_value

    return normalized


def check_business_inconsistency(normalized: dict[str, object]) -> str | None:
    """Detect the FIAT-003 pattern: Moroso but Requiere_Cobranza=No.

    Returns an observation message (to log, not to enforce) or None.
    The agent trusts the sheet and submits the data as-is; it never
    infers legal collections on its own (CLAUDE.md trap #7).
    """
    estado = normalized.get(_ESTADO_FIELD_LABEL)
    requiere_cobranza = normalized.get(_COBRANZA_FIELD_LABEL)

    if estado == _MOROSO_OPTION and requiere_cobranza is False:
        return (
            f"Business-logic inconsistency: {_ESTADO_FIELD_LABEL}='{_MOROSO_OPTION}' "
            f"but {_COBRANZA_FIELD_LABEL}=No. Submitting as-is per sheet data; "
            "the agent does not infer legal collections."
        )
    return None


def process_record(
    *,
    browser,
    form_key: str,
    schema: "FormSchema",
    url: str,
    record: dict[str, str],
    mapping: dict[str, "Field"],
    cfg: "Config",
    dry_run: bool,
    headed: bool,
    slow_mo: int,
    llm_failed_labels: set[str] | None = None,
) -> dict:
    """Process one record end-to-end. Never raises — always returns a result dict.

    `llm_failed_labels` (optional): labels of required fields left
    unmapped because the LLM mapping fallback call itself failed (see
    mapper.map_columns). When a required field with no mapped column
    is ALSO in this set, the record is reported as LLM_ERROR instead
    of SCHEMA_DRIFT — the field is unmapped because the AI provider
    failed, not because the live form schema drifted.
    """
    id_cliente = record.get("ID_Cliente", "UNKNOWN")
    llm_failed_labels = llm_failed_labels or set()
    results_path = Path(cfg.runs_dir) / "results.jsonl"

    try:
        normalized = normalize_record(record, mapping)
    except errors.DirtyValueError as exc:
        # Hash the RAW record (normalization never completed, so there
        # is no normalized dict to hash) -- an edited/corrected sheet
        # row still produces a different raw record and is reprocessed.
        raw_values_for_hash = {k: str(v) for k, v in sorted(record.items())}
        hash_value = results.content_hash(raw_values_for_hash)
        detail = str(exc)
        results.append_result(
            results_path,
            form=form_key,
            id_cliente=id_cliente,
            content_hash_value=hash_value,
            status=errors.DirtyValueError.status,
            detail=detail,
            evidence=None,
        )
        logger.warning("DIRTY_VALUE id=%s: %s", id_cliente, detail)
        return {
            "status": errors.DirtyValueError.status,
            "id_cliente": id_cliente,
            "detail": detail,
        }

    values_for_hash = {k: str(v) for k, v in sorted(normalized.items())}
    hash_value = results.content_hash(values_for_hash)

    prior_status = results.blocking_status(results_path, form_key, id_cliente, hash_value)
    if prior_status is not None:
        if prior_status == errors.SubmitUnconfirmedError.status:
            # A prior SUBMIT_UNCONFIRMED is NOT the same as a confirmed
            # success -- it must not be silently skipped as
            # "already submitted". Surface it explicitly so a human
            # reviews whether the earlier Enviar click actually went
            # through, per specs.md's "marcar para revisión".
            detail = (
                "A prior submission for this exact content-hash ended in "
                "SUBMIT_UNCONFIRMED and needs manual review before "
                "reprocessing; automatic re-run is blocked to avoid a "
                "possible duplicate submission."
            )
            logger.warning("NEEDS_MANUAL_REVIEW id=%s: %s", id_cliente, detail)
            return {
                "status": "NEEDS_MANUAL_REVIEW",
                "id_cliente": id_cliente,
                "detail": detail,
            }
        detail = "Already submitted with this exact content-hash; skipped."
        return {"status": "ALREADY_DONE", "id_cliente": id_cliente, "detail": detail}

    # Completeness gate — BEFORE opening the browser. Distinguishes:
    # - SCHEMA_DRIFT: a required field has NO mapped source column at
    #   all (the live form added a field the mapper never resolved).
    # - LLM_ERROR: same symptom, but specifically because the LLM
    #   mapping fallback call failed for that field.
    # - SKIPPED_REQUIRED_EMPTY: the field IS mapped, but its value is
    #   empty after normalization (unchanged behavior).
    all_fields = [f for page in schema.pages for f in page]
    mapped_field_ids = {f.item_id for f in mapping.values()}
    available_headers = list(record.keys())

    unmapped_required = [
        f for f in all_fields if f.required and f.item_id not in mapped_field_ids
    ]
    if unmapped_required:
        llm_error_fields = [f for f in unmapped_required if f.label in llm_failed_labels]
        if llm_error_fields:
            labels = ", ".join(f.label for f in llm_error_fields)
            detail = (
                f"Required field(s) left unmapped because the LLM mapping "
                f"fallback failed: {labels}. Available headers: "
                f"{', '.join(available_headers)}"
            )
            results.append_result(
                results_path,
                form=form_key,
                id_cliente=id_cliente,
                content_hash_value=hash_value,
                status=errors.LlmError.status,
                detail=detail,
                evidence=None,
            )
            logger.warning("LLM_ERROR id=%s: %s", id_cliente, detail)
            return {
                "status": errors.LlmError.status,
                "id_cliente": id_cliente,
                "detail": detail,
            }

        labels = ", ".join(f.label for f in unmapped_required)
        detail = (
            f"Required field(s) with no mapped source column: {labels}. "
            f"Available headers: {', '.join(available_headers)}"
        )
        results.append_result(
            results_path,
            form=form_key,
            id_cliente=id_cliente,
            content_hash_value=hash_value,
            status=errors.SchemaDriftError.status,
            detail=detail,
            evidence=None,
        )
        logger.warning("SCHEMA_DRIFT id=%s: %s", id_cliente, detail)
        return {
            "status": errors.SchemaDriftError.status,
            "id_cliente": id_cliente,
            "detail": detail,
        }

    missing = [
        label
        for label in (f.label for f in all_fields if f.required)
        if normalized.get(label) in (None, "")
    ]
    if missing:
        detail = f"Missing required fields after normalization: {', '.join(missing)}"
        results.append_result(
            results_path,
            form=form_key,
            id_cliente=id_cliente,
            content_hash_value=hash_value,
            status=errors.SkippedRequiredEmptyError.status,
            detail=detail,
            evidence=None,
        )
        logger.warning("SKIPPED_REQUIRED_EMPTY id=%s: %s", id_cliente, detail)
        return {
            "status": errors.SkippedRequiredEmptyError.status,
            "id_cliente": id_cliente,
            "detail": detail,
        }

    observation = check_business_inconsistency(normalized)
    if observation:
        logger.info("Observation for id=%s: %s", id_cliente, observation)

    context = None
    page = None
    try:
        context = browser.new_context()
        page = context.new_page()
        page.goto(url)
        # Google Forms renders its interactive question controls via
        # client-side JS AFTER the `load` event Playwright's default
        # goto() waits for; wait for network activity to settle before
        # any locator interaction (verified necessary against the live
        # DOM — without it, the intro-card "Siguiente" and/or the
        # first question container are not yet attached).
        page.wait_for_load_state("networkidle")

        status = filler.fill_record(
            page,
            schema,
            normalized,
            dry_run=dry_run,
            allowed_url_prefixes=cfg.allowed_url_prefixes,
        )

        evidence_path = errors.evidence(page, cfg.runs_dir, f"{form_key}-{id_cliente}")
        detail = observation or "OK"
        results.append_result(
            results_path,
            form=form_key,
            id_cliente=id_cliente,
            content_hash_value=hash_value,
            status=status,
            detail=detail,
            evidence=evidence_path,
        )
        return {"status": status, "id_cliente": id_cliente, "detail": detail}

    except errors.FormFillerError as exc:
        evidence_path = errors.evidence(page, cfg.runs_dir, f"{form_key}-{id_cliente}-error")
        results.append_result(
            results_path,
            form=form_key,
            id_cliente=id_cliente,
            content_hash_value=hash_value,
            status=exc.status,
            detail=str(exc),
            evidence=evidence_path,
        )
        logger.error("%s id=%s: %s", exc.status, id_cliente, exc)
        return {"status": exc.status, "id_cliente": id_cliente, "detail": str(exc)}

    except PlaywrightTimeoutError as exc:
        evidence_path = errors.evidence(page, cfg.runs_dir, f"{form_key}-{id_cliente}-error")
        detail = f"Timeout: {exc}"
        results.append_result(
            results_path,
            form=form_key,
            id_cliente=id_cliente,
            content_hash_value=hash_value,
            status=errors.TimeoutFillerError.status,
            detail=detail,
            evidence=evidence_path,
        )
        logger.error("%s id=%s: %s", errors.TimeoutFillerError.status, id_cliente, exc)
        return {
            "status": errors.TimeoutFillerError.status,
            "id_cliente": id_cliente,
            "detail": detail,
        }

    except Exception as exc:  # noqa: BLE001 - never crash the batch
        evidence_path = errors.evidence(page, cfg.runs_dir, f"{form_key}-{id_cliente}-error")
        detail = f"Unexpected error: {exc}"
        results.append_result(
            results_path,
            form=form_key,
            id_cliente=id_cliente,
            content_hash_value=hash_value,
            status="UNKNOWN_ERROR",
            detail=detail,
            evidence=evidence_path,
        )
        logger.exception("Unexpected error id=%s", id_cliente)
        return {"status": "UNKNOWN_ERROR", "id_cliente": id_cliente, "detail": detail}

    finally:
        if context is not None:
            context.close()


def run_form(
    form_key: str,
    *,
    cfg: "Config",
    dry_run: bool = True,
    headed: bool = False,
    slow_mo: int = 0,
    only_id: str | None = None,
) -> list[dict]:
    """Run every record (or a single --only record) for one form."""
    from playwright.sync_api import sync_playwright

    tab_name = next(
        (tab for tab, key in cfg.tab_routing.items() if key == form_key), None
    )
    if tab_name is None:
        raise ValueError(f"No sheet tab routed to form '{form_key}'")

    url = cfg.form_urls[form_key]
    schema = forms_schema.fetch_schema(url)
    records = sheets.fetch_tab(cfg.sheet_id, tab_name)
    headers = list(records[0].keys()) if records else []
    all_fields = [f for page in schema.pages for f in page]
    llm_failed_labels: set[str] = set()
    mapping = mapper.map_columns(
        headers, all_fields, llm_failed_labels=llm_failed_labels
    )

    if only_id is not None:
        records = [r for r in records if r.get("ID_Cliente") == only_id]

    outcomes: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed, slow_mo=slow_mo)
        try:
            for record in records:
                outcome = process_record(
                    browser=browser,
                    form_key=form_key,
                    schema=schema,
                    url=url,
                    record=record,
                    mapping=mapping,
                    cfg=cfg,
                    dry_run=dry_run,
                    headed=headed,
                    slow_mo=slow_mo,
                    llm_failed_labels=llm_failed_labels,
                )
                outcomes.append(outcome)
        finally:
            browser.close()

    return outcomes
