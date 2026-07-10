# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Greenfield, scoped to `tercero/`. The source of truth is `tercero/specs.md` (Spanish) — there is no application code yet. Treat `specs.md` as the contract and this file as the distilled invariants + locked decisions.

Product: an **autonomous agent** (FADUA technical challenge) that reads records from a Google Sheets and fills two Google Forms step by step, replicating human navigation, validation, and submission, with real error handling.

The repository root holds a **different** challenge (an AI Analytics Chatbot). Do not mix the two. This challenge lives entirely under `tercero/`; touch nothing outside it.

## Non-negotiable invariants

The whole design depends on these. Violating any one breaks the core guarantee — *never invent data*:

1. **Deterministic Playwright drives the browser — the LLM never does.** UI automation is explicit, reproducible code. The AI model issues no navigation actions.
2. **The LLM sees schema and labels only, never PII row values.** It maps a column to a field when the deterministic match fails. It never receives names, emails, phones, or amounts. Value normalization is 100% deterministic.
3. **Never invent data. Never guess an option below confidence. Never submit a partial required form.** On doubt, skip the record and report it. A blank required cell is not a `0`.
4. **Sheet access is read-only.** Data comes from the public `gviz` CSV export — no OAuth, no write scope. The agent cannot mutate the source.
5. **Success is recorded only on confirmed submission.** A submit counts as successful only when the confirmation page is detected (view transition + known confirmation phrases, not an exact string). Otherwise the result is `SUBMIT_UNCONFIRMED`.
6. **The AI provider is swappable behind `llm.py`.** Models are consumed through one abstraction; no provider-specific code leaks into the agent.
7. **Real FADUA forms are submitted only with explicit `--live`.** Development uses clone forms plus `--dry-run` (fills, does not submit).

## Locked decisions

- **`FB_PUBLIC_LOAD_DATA_` is parsed LIVE on every run** as the schema source of truth (item IDs for DOM anchoring, entry IDs for POST field names, field types, required flags, options, page breaks). Any form change surfaces as drift, not as broken code. The captured JSON in `fixtures/` are test fixtures only.
- **Deterministic-first mapping.** Column→field is resolved by normalized tokens first; the LLM is a fallback **only** for a required field left unmapped. Mapping is cached in `mapping.json`.
- **Idempotency key `(form, ID_Cliente, content-hash)`** in an append-only JSONL log. An edited row (new content-hash) is re-submitted; an unchanged row is not duplicated.
- **One `BrowserContext` per record.** No state (cookies, autofill, residual fields) leaks between records or between forms. This is also the seam for a bounded worker pool later.
- **Results JSONL doubles as the checkpoint** for idempotency — one file is both the result log and the resume point.

## Architecture

Per-record flow:

```
read sheet row → normalize → completeness gate (missing required: skip+report, no browser)
  → fill field by field with read-back (assert DOM value == expected before advancing)
  → assert section on both sides of each "Siguiente"
  → pre-submit validation → Enviar → assert confirmation → JSONL + evidence
```

| Module | Role |
|--------|------|
| `config.py` | Loads `.env`: URLs, sheet ID, provider, flags |
| `llm.py` | Provider abstraction (OpenCode GO, swappable) |
| `sheets.py` | gviz CSV per sheet → `list[dict]`; strips header whitespace |
| `normalize.py` | Deterministic parsers: currency, Sí/No, option matching |
| `forms_schema.py` | `FB_PUBLIC_LOAD_DATA_` → `FormSchema` (fields, types, required, options, pages) |
| `mapper.py` | Deterministic column→field; LLM fallback only; cache |
| `filler.py` | Playwright: per-type handlers, listbox, "Siguiente", human pacing |
| `validator.py` | Three gates: completeness, read-back, confirmation |
| `errors.py` | Error taxonomy + evidence (screenshot + trace) per failure |
| `runner.py` | Orchestrates one record end-to-end |
| `results.py` | Append-only JSONL: result + idempotency |
| `main.py` | CLI entry point and mode parsing |

## Selector rules

Google Forms uses obfuscated CSS classes. **Never select by class.** Choose the handler from the schema field type, never from the field name.

| Target | Primary locator | Fallback / verification |
|--------|-----------------|-------------------------|
| Any field | Question container via `[data-params*="[<item ID>,"]`, then act by role inside it | Accessible label (`get_by_role` / `get_by_label`, normalized match) |
| Dropdown (type 3) | It is an **ARIA listbox, NOT a `<select>`** | Click to open → click option → verify rendered text. Never `select_option` |
| Radio (type 2) | `get_by_role("radio", name=<option>)` | Click, then verify `aria-checked` |
| Checkbox (type 4) | `get_by_role("checkbox")` | Check **only if** the boolean is true; verify `aria-checked`; false leaves it untouched |
| Section (type 8) | Assert the expected section header is on screen before AND after each "Siguiente" | — |
| Button | `get_by_role("button", name="Siguiente")`; **"Enviar" on the last page** | — |

Multi-page navigation: assert the expected section before filling it, click "Siguiente", assert the next section appeared. Form 1 is multi-page; Form 2 is single-page. The same generic `schema.pages` loop drives both.

Verified against the live DOM (2026-07-10): viewform inputs do NOT carry `name="entry.<ID>"`. Both IDs live in each question container's `data-params` attribute (item ID first, entry ID nested). The entry ID is the POST field name (`formResponse`) and the prefill URL parameter — useful for tests and verification, not for DOM location.

## FB field type codes

| Code | Type |
|------|------|
| 0 | Short text |
| 2 | Radio (single choice) |
| 3 | Dropdown / ARIA listbox |
| 4 | Checkbox |
| 8 | Section header / page break (not a field) |

## Form schemas (verified item + entry IDs)

### Form 1 — Registro de Ventas (`https://forms.gle/oqjtULJ6iGBT7HFR7`, multi-page)

| item ID (DOM) | entry ID (POST) | Label | Type | Required | Options |
|---------------|-----------------|-------|------|----------|---------|
| — | — | DATOS DEL CLIENTE | 8 | — | section |
| `999998362` | `entry.814069894` | ID del Cliente | 0 | yes | — |
| `1400945540` | `entry.657237802` | Nombre Completo | 0 | yes | — |
| `1881411619` | `entry.1855970967` | Correo Electrónico | 0 | yes | — |
| `146186431` | `entry.136415275` | Teléfono de Contacto | 0 | yes | — |
| — | — | DATOS DE LA UNIDAD | 8 | — | section |
| `667185096` | `entry.2099080465` | Modelo de Automóvil | 3 | yes | Fiat Cronos · 600 · Fiat Strada · Fiat Fastback · Fiat Pulse |
| `1583087190` | `entry.1493778692` | Valor Total del Vehículo | 0 | yes | — |
| — | — | DATOS DE COMPRA | 8 | — | section |
| `34738716` | `entry.487326979` | Tipo de Financiación | 2 | yes | Crédito Prendario · Plan de Ahorro · Contado / Directo |

### Form 2 — Control de Morosidad y Pagos (`https://forms.gle/JQTABscuZxn2S6Dh7`, single-page)

| item ID (DOM) | entry ID (POST) | Label | Type | Required | Options |
|---------------|-----------------|-------|------|----------|---------|
| `88995149` | `entry.1568255357` | ID de Cliente Asociado | 0 | yes | — |
| `158888317` | `entry.1088714979` | Nombre del Cliente | 0 | no | — |
| `888542449` | `entry.230995405` | Valor del Vehículo | 0 | yes | — |
| `169419756` | `entry.191355245` | Tipo Financiación | 3 | yes | Plan de Ahorro · Crédito Prendario · Contado / Directo |
| `101891614` | `entry.1430363473` | Estado de Cuenta Actual | 2 | yes | Al día · Moroso |
| `250795746` | `entry.1824761040` | Días de Atraso (Si aplica) | 0 | yes | — |
| `1075955762` | `entry.1373856247` | Monto del Último Pago Registrado | 0 | yes | — |
| `1137417183` | `entry.76508310` | Requiere Acción de Cobranza Legal | 4 | no | Sí, activar protocolo de cobranza legal |

Cross-check: in Form 1 Modelo is a dropdown and Financiación is radio; in Form 2 Financiación is a dropdown and Estado is radio. Read the type from the schema, never from the field name.

## Data traps

Deliberate inconsistencies in the source — the challenge's real "error handling" test. Each has a defined deterministic treatment.

| # | Trap | Example | Treatment |
|---|------|---------|-----------|
| 1 | State does not literally match the form option | Sheet `Al Día` vs option `Al día` | Case/accent-insensitive option matching (deterministic) |
| 2 | Disguised empty required value | `FIAT-002`: ` Ultimo_Pago_Monto` = `" $ -   "` | `SKIPPED_REQUIRED_EMPTY`. Never invent a `0` on a collections form |
| 3 | Dirty currency | `" $ 18,500,000 "` | Deterministic parser: strips symbol, thousands commas, padding; tolerates decimal comma |
| 4 | Boolean to single-option checkbox | `Requiere_Cobranza` = `Sí` / `No` | `Sí`/`No` → bool; check only if true. `No` leaves the control untouched (there is no "No" option) |
| 5 | Headers with leading space | ` Valor_Vehiculo`, ` Ultimo_Pago_Monto` | `.strip()` headers on ingest |
| 6 | Different form structure | Form 1 multi-page vs Form 2 single-page | Generic `schema.pages` loop: same code for both |
| 7 | Business-logic inconsistency | `FIAT-003`: Moroso, 15 days, but `Requiere_Cobranza` = `No` | Trust the sheet: submit `No`, record the inconsistency as an observation. The agent does not infer legal collections |

## Commands

No build files exist yet; these follow from the declared stack. Create `pyproject.toml`, `Dockerfile`, and `.env.example` before relying on them.

```bash
uv sync                                                  # install
uv run python -m app.main run --dry-run --headed         # dev run: fills, does not submit, visible browser
uv run python -m app.main run --live                     # submit to the real FADUA forms (guarded)
uv run pytest                                            # all tests
uv run pytest tests/test_normalize.py::test_currency     # a single test
docker build -t fadua-agent . && docker run --env-file .env fadua-agent   # containerized run
```

## Layout (planned)

```
tercero/
  app/
    config.py       # .env: URLs, sheet ID, provider, flags
    llm.py          # AI provider abstraction (OpenCode GO, swappable)
    sheets.py       # gviz CSV per sheet → list[dict]; clean headers
    normalize.py    # deterministic parsers: currency, Sí/No, option match
    forms_schema.py # FB_PUBLIC_LOAD_DATA_ → FormSchema
    mapper.py       # deterministic column→field; LLM fallback; cache
    filler.py       # Playwright: per-type handlers, listbox, "Siguiente", pacing
    validator.py    # three gates: completeness, read-back, confirmation
    errors.py       # taxonomy + evidence (screenshot + trace) per failure
    runner.py       # orchestrates one record end-to-end
    results.py      # append-only JSONL: result + idempotency
    main.py         # CLI: run | --watch | --dry-run | --headed | --slow-mo | --only <ID> | --live
  clones/           # own clone forms for real-submit tests
  tests/
  fixtures/         # form_ventas_fb.json, form_mora_fb.json, tab_VENTAS.csv, tab_MORA.csv
  pyproject.toml
  Dockerfile
  .env.example
  README.md         # run & delivery guide
```

- `sheets.py` is the **only** read path to the Google Sheet, and it is read-only.
- `filler.py` is the **only** code that touches the browser.
- `llm.py` is the **only** place the AI provider is referenced.
