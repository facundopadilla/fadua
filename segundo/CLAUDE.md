# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Greenfield. The only source of truth today is `specs.md` (Spanish) — there is no application code yet. Treat `specs.md` as the contract and this file as the distilled architecture + invariants. `segundo/` is empty scaffolding.

Product: an **AI Analytics Assistant** — a conversational chatbot that answers natural-language questions about ad campaigns, sales, and commercial KPIs over a MySQL database. The AI plays the role of *Analista de Datos Comercial*.

## Non-negotiable invariants

The whole design depends on these. Violating any one breaks the core guarantee — *never invent data*:

1. **The database is the only source of truth.** Every claim in an answer must trace back to real rows.
2. **The LLM never touches MySQL directly.** All data access goes through controlled Tools (`execute_sql`, `calculate_kpis`, `forecast_*`, `create_chart`, `summarize_dataset`).
3. **The LLM explains — it does not compute or predict.** KPI math lives in the analytics layer; forecasts come from Prophet. The LLM only interprets and writes prose over what the tools return.
4. **SQL is validated by AST before execution.** Generated SQL passes `sqlglot` → parse → validate → run. Reject anything that isn't a single `SELECT` against the one authorized table, references unknown columns, or uses dangerous subqueries/functions. Never `UPDATE / DELETE / DROP / ALTER / INSERT / TRUNCATE`.
5. **The LLM provider is swappable.** Models come from OpenCode GO APIs (Qwen, Minimax, GLM, …) behind an abstraction — no provider-specific code leaks into the agent or tools.

## Startup decisions (locked)

Decided before implementation. These refine — not replace — the invariants and architecture below.

1. **API contract — SSE stream + final payload.** The endpoint streams `answer` as SSE `token` events, then emits one `done` event carrying the full structured `ChatResponse`. The frontend accumulates tokens live and renders chart/KPIs on `done`. Never try to stream the structured object incrementally.
2. **Data shape — daily rows, 1–2 years.** `fecha` is one row per day, 1–2 years of history. Prophet consequence: **strong weekly** seasonality, **weak yearly** (1–2 cycles). Trust forecasts to ~30 days (the spec's "next month"); beyond ~90 days widen intervals and state the uncertainty. Enable `weekly_seasonality`; treat `yearly_seasonality` as low-confidence.
3. **Planner — deterministic rules, not an LLM.** Intent is classified by keyword/pattern rules over the business dictionary — no extra LLM call. Canonical intent enum (single source of truth for planner↔router): `SQL · KPI · COMPARISON · FORECAST · CHART · CONVERSATION`. This supersedes the spec's inconsistent `Analytics`/`Chart` naming.
4. **Conversational memory — Redis, per session, 14-day TTL.** This is a technical-evaluation build: the reviewer opens it ~1 week after delivery, so sessions must survive redeploys and restarts across that window. History lives in Redis keyed by `conv:{conversation_id}` (JSON message list) with a 14-day TTL (margin over the ~1-week review window). Enable Redis **AOF + a Docker volume** so data also survives a Redis/VPS restart — otherwise a restart drops everything regardless of TTL. Every request carries `conversation_id`; `ChatResponse` echoes it. This is session durability, not permanent history — add a MySQL `messages` archive only if permanent, auditable history becomes a requirement (YAGNI for the evaluation).

Minor, also locked:
- **`confidence`** is never self-reported by the LLM. Derive it from execution signals (SQL validated, rows returned, forecast had enough points); low on fallback/empty results.
- **Auth** is out of MVP scope on purpose. The SQL layer protects the DB from the LLM; nothing yet protects the API from the outside. Add authn + rate-limiting before any non-local exposure.

## Architecture

Request flow:

```
React → REST/SSE → FastAPI → PydanticAI Agent → Intent Planner
                                                      │
                          ┌───────────────┬───────────┴───────────┐
                       SQL Tool     Analytics Tool           Forecast Tool
                          └───────────────┴───────────────────────┘
                                          ▼
                                        MySQL  → LLM writes answer → ChatResponse
```

**Intent Planner** is the key routing layer: deterministic keyword + business-dictionary rules classify each query *before* invoking the main model into `SQL | KPI | COMPARISON | FORECAST | CHART | CONVERSATION`, so the system runs only the logic that query needs. Don't fold this into the agent — it's a deliberate cost/precision optimization.

**Structured responses.** The backend never returns free text to render. Every reply is a Pydantic `ChatResponse` (`conversation_id`, `answer`, `sql`, `chart`, `metrics`, `suggestions`, `execution_time`, `confidence`) that the frontend renders declaratively. The frontend does not parse prose.

**Semantic layer (Business Dictionary).** A central dictionary maps business vocabulary → real columns so queries work without exact column names:

- `ventas` / `clientes` → `cantidad_ventas`
- `facturación` / `ingresos` → `ingresos_ventas_usd`
- `gasto` / `inversión` → `google_ads_costo_usd + meta_ads_costo_usd`
- `ads` → `google_ads`, `meta_ads`

**Conversational memory.** Context persists across turns (e.g. "¿el mejor mes?" → "¿y el peor?" stays about sales).

## Data model

Single authorized table: **`metricas_campanas_ventas`**. Columns:

`fecha`, `google_ads_impresiones`, `google_ads_clics`, `google_ads_costo_usd`, `google_ads_leads`, `meta_ads_impresiones`, `meta_ads_clics`, `meta_ads_costo_usd`, `meta_ads_leads`, `total_leads`, `cantidad_ventas`, `vehiculo_tipo_principal`, `vehiculo_modelo_principal`, `ingresos_ventas_usd`

The SQL validator's column allow-list derives from exactly these. The spec anticipates future multi-table support — keep the table name configurable, not hardcoded across the code.

## KPI definitions (canonical)

Compute these in the analytics layer, never in the LLM. `costo total` / `gasto` = `google_ads_costo_usd + meta_ads_costo_usd`.

| KPI | Formula |
|-----|---------|
| CTR | clics / impresiones |
| CPC | costo / clics |
| CPL | costo / leads |
| CPA | costo total / ventas |
| ROAS | ingresos / costo total |
| ROI | (ingresos − costos) / costos |
| Conversion Rate | ventas / leads |

## Intended toolchain

No build files exist yet; these commands follow from the declared stack. Create the manifests (`pyproject.toml`, `package.json`, `docker-compose.yml`) before relying on them.

**Backend** (`backend/`, Python via `uv`):
- `uv sync` — install
- `uv run uvicorn app.main:app --reload` — dev server
- `uv run pytest` — all tests · `uv run pytest tests/test_x.py::test_name` — a single test
- `docker compose up` — full stack (API + MySQL + Redis, with AOF volume)

**Frontend** (`frontend/`, Vite + React + TypeScript):
- `npm install`
- `npm run dev` — dev server
- `npm run build` — production build
- UI: **shadcn/ui** (copy-in components via its CLI, Radix + Tailwind) + **lucide-react** icons (shadcn's default set)

## Layout (planned)

```
backend/app/{api,agent,planner,tools,analytics,forecasting,charts,database,models,schemas,prompts,services,utils}
frontend/src/{pages,components,layouts,hooks,services,types}
```

- `tools/` — the controlled data-access tools; the **only** path to MySQL.
- `analytics/` — KPI math. `forecasting/` — Prophet models.
- `charts/` — chart-config builders (line / bar / pie / area) returned in `ChatResponse.chart`.
- `prompts/` — agent system prompt + few-shot SQL examples.
