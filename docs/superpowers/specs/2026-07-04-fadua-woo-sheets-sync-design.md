# Design: FADUA WooCommerce → Google Sheets Sync

**Date:** 2026-07-04
**Status:** Approved
**Author:** Facundo Padilla

## Goal

Automatically sync visible products (name, price, image URL) from a WooCommerce
store into a Google Sheet every 5 minutes. On each run, detect newly published
products, append them to the sheet, and email a run summary to
`tejada.ca23@gmail.com`.

This is a technical challenge for FADUA. It ships in **two independent
implementations** — a Python script (code) and an n8n workflow (low-code) — both
running in parallel against the same spreadsheet on the candidate's VPS.

## Non-Goals

- Two-way sync (Sheets → WooCommerce). Read-only from WooCommerce.
- Updating existing rows when a product's price/name changes upstream. Scope is
  **new product detection only**, per the challenge brief.
- Deleting rows when a product is removed from WooCommerce.
- A web UI or dashboard. The deliverable is the cron job plus documentation.

## Source Data

- **Endpoint:** `GET https://fadua.ar/pruebas/wp-json/wc/v3/products`
- **Auth:** HTTP Basic over HTTPS (`ck_...` : `cs_...`), WooCommerce REST API v3.
- **Query params:** `status=publish`, `per_page=100`, paginated via `page`.
- **Fields consumed:** `id`, `name`, `price`, `images[0].src`, `permalink`.

### Verified constraints (from live API probe on 2026-07-04)

1. The authenticated API returns **draft** products (e.g. id 23 "FASTBACK",
   `status: "draft"`). The challenge asks for *visible* products, so we MUST
   filter `status=publish`. This is enforced server-side via the query param.
2. Draft products have `date_created: null`. A draft that gets published keeps
   its original (old) creation date. Therefore **new-product detection cannot
   rely on dates** — it must be by product `id`.
3. `price` is returned as a string (e.g. `"700"`). Stored verbatim; no currency
   math is performed.

## Architecture

```
                    ┌─────────────────────────────┐
                    │  WooCommerce REST API (v3)   │
                    │  fadua.ar/pruebas            │
                    └──────────────┬──────────────┘
                                   │ GET products?status=publish
                 ┌─────────────────┴─────────────────┐
                 │                                     │
        ┌────────▼─────────┐                 ┌─────────▼────────┐
        │  Python script    │                 │  n8n workflow    │
        │  (uv run, cron)   │                 │  (Docker, Sched) │
        └────────┬─────────┘                 └─────────┬────────┘
                 │  diff by id                          │  diff by id
                 │  append rows                         │  append rows
        ┌────────▼─────────┐                 ┌─────────▼────────┐
        │  Sheet tab:       │                 │  Sheet tab:      │
        │  "python"         │                 │  "n8n"           │
        └───────────────────┘                 └──────────────────┘
                 │  if new products                     │  if new products
        ┌────────▼─────────┐                 ┌─────────▼────────┐
        │  Email summary    │                 │  Email summary   │
        │  [PYTHON] subject │                 │  [N8N] subject   │
        └───────────────────┘                 └──────────────────┘
```

Both implementations write to the **same spreadsheet**, each to its own tab
(`python`, `n8n`). This isolates their state so they never race on the same
rows, while letting FADUA compare both side by side in one document.

### Deployment (VPS: Ubuntu 22.04, Docker installed)

- **Python:** runs via `uv run` from a system crontab entry, every 5 min. No
  virtualenv activation — `uv` resolves the environment from `pyproject.toml` on
  each invocation (fast, reproducible). A `flock` guard prevents overlapping runs.
- **n8n:** runs as a Docker Compose service. A **Schedule Trigger** node fires
  every 5 min. Credentials live in n8n's encrypted credential store.

## Data Flow (identical logic in both implementations)

1. **Fetch** all published products from WooCommerce (paginated).
2. **Read** the existing product IDs from the implementation's own sheet tab
   (the sheet is the **source of truth** — no local state file).
3. **Diff** by ID → products present in WooCommerce but absent from the sheet.
4. **Append** one row per new product: `ID | Producto | Precio | Imagen | Sincronizado`.
   `Sincronizado` is an ISO timestamp proving when the cron picked it up.
5. **Notify:** if ≥1 new product, send an email summary. If zero, log and stay
   silent (no every-5-minute spam).

### First run = baseline

On the first run the tab is empty, so every published product is "new": all rows
are inserted and one summary email is sent. This is exactly step 2 of FADUA's
live-test protocol (candidate starts the system → it extracts current data).

### Why "sheet as source of truth"

- **Idempotent:** re-running never duplicates rows; the diff is against live state.
- **Self-healing:** if someone deletes rows, the next run re-inserts them.
- **Transparent:** the same logic reads cleanly in both Python and n8n — easy to
  explain on the recorded Meet.
- **Cost:** one extra Sheets read per run. Trivial at this scale (tens of rows).

Rejected alternative — local JSON of seen IDs: duplicates the source of truth,
desyncs if the sheet is hand-edited, and in n8n needs workflow static data
(opaque in a demo).

## Error Handling

The challenge explicitly asks how errors are handled (e.g. WooCommerce API not
responding during a run).

- **Retry with backoff:** the WooCommerce fetch retries 3× with exponential
  backoff. If it still fails, the run **logs the error and exits without touching
  the sheet**. The idempotent design means the next run (≤5 min later) recovers
  on its own — no product is lost.
- **Append before email:** rows are written first, email sent second. If the
  email fails after a successful append, data is already safe in the sheet; the
  failure is logged. (Conscious trade-off: data integrity > notification.)
- **Overlap guard:** `flock` on the Python cron entry prevents a slow run from
  overlapping the next tick.
- **Per-run logging:** timestamped lines in `logs/sync.log` (Python) and n8n's
  execution log, so every tick is auditable.

## Security (credential handling)

The challenge explicitly asks what security measures protect the credentials.

- **No secrets in code or git.** Python reads from a `.env` file and a
  `service-account.json`, both `chmod 600` and listed in `.gitignore`. A
  committed `.env.example` documents the required variables without values.
- **n8n** uses its native encrypted credential store. The exported blueprint
  `.json` deliverable contains **no** credentials — only node structure.
- **Least privilege:** the Google service account is granted Editor on *only*
  this one spreadsheet. The Gmail App Password is scoped and revocable, and
  requires 2FA on the sending account.
- WooCommerce keys travel only over HTTPS Basic auth.

## Configuration (`.env`)

```
WC_BASE_URL=https://fadua.ar/pruebas
WC_CONSUMER_KEY=ck_...
WC_CONSUMER_SECRET=cs_...
GOOGLE_SHEET_ID=...
GOOGLE_SHEET_TAB=python
GOOGLE_SA_JSON=./service-account.json
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=<sender-gmail>
SMTP_APP_PASSWORD=<gmail-app-password>
NOTIFY_TO=tejada.ca23@gmail.com
```

## Python Stack

- **Runner/packaging:** `uv` with `pyproject.toml` (no venv/pip). Cron calls
  `uv run python -m sync`.
- **Dependencies:** `requests` (WooCommerce), `gspread` + `google-auth`
  (Sheets), `python-dotenv` (`.env` loading). Email via stdlib `smtplib` +
  `email` (no dependency).
- **Layout:**
  - `python/pyproject.toml`
  - `python/sync/__main__.py` — orchestration (fetch → diff → append → notify)
  - `python/sync/woocommerce.py` — API client with retry/backoff
  - `python/sync/sheets.py` — read IDs, append rows
  - `python/sync/notifier.py` — SMTP email
  - `python/sync/config.py` — env loading
  - `python/tests/test_diff.py` — unit test for the diff logic

## Testing & Verification

- **Unit:** test the diff function (the only non-trivial logic) — the one
  runnable check that fails if new-product detection breaks.
- **End-to-end rehearsal:** the API key has write scope on WooCommerce, so before
  the demo we create a test product, confirm it lands in both tabs and triggers
  both emails within 5 min, then delete it. This rehearses FADUA's exact live test.

## Language & Documentation Conventions

- **Code, identifiers, code comments:** English (standard).
- **Deliverables facing FADUA** — `README.md`, the technical explanation doc,
  sheet headers, email body: **neutral Spanish**, written in a **humanized**
  voice (natural prose, not AI-patterned). Technical blocks inside those docs
  (commands, config, code, JSON) stay verbatim.
- The `docs/` folder includes the technical explanation answering the four Meet
  questions (integration structure, credential security, data-flow criteria,
  error handling), ready for the recorded session.

## Deliverables

1. `python/` — documented source, `pyproject.toml`, unit test.
2. `n8n/` — exported workflow blueprint `.json` (no credentials).
3. `docs/` — humanized `README.md` (setup + run) and technical explanation.
4. A shared Google Sheet, Editor access granted to `tejada.ca23@gmail.com`.
