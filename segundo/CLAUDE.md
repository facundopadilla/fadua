# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Fully implemented and running. `specs.md` (Spanish) is the original contract; this file is the distilled architecture + invariants, updated to match what's actually built. Where this file and `specs.md` disagree, this file wins — it reflects locked decisions made during implementation (see "Startup decisions" below).

Product: an **AI Analytics Assistant** — a conversational chatbot that answers natural-language questions about ad campaigns, sales, and commercial KPIs over a MySQL database. The AI plays the role of *Analista de Datos Comercial*.

Two response paths, tried in order on every request:

1. **LLM tool-calling agent** (`backend/app/agent/llm_agent.py`) — active when `LLM_API_KEY` is configured. A PydanticAI `Agent` decides which controlled tool to call (`run_sql`, `compute_kpis`, `forecast`, `make_chart`) and writes the final answer over their real results.
2. **Deterministic planner** (`backend/app/planner/planner.py` + `backend/app/agent/templates.py`) — the fallback, and the only path when no key is set. Keyword/pattern rules classify intent, a fixed handler per intent calls the same underlying tools, and a template renders the answer. No LLM involved.

`AnalyticsEngine._build_response` (`backend/app/agent/engine.py`) is where this two-path selection is wired: it attempts path 1 first when a key exists, and falls through to path 2 on *any* failure (network error, provider error, empty output) — never a hard failure for the user.

## Non-negotiable invariants

The whole design depends on these. Violating any one breaks the core guarantee — *never invent data*:

1. **The database is the only source of truth.** Every claim in an answer must trace back to real rows.
2. **The LLM never touches MySQL directly.** All data access goes through controlled Tools (`execute_sql`, `calculate_kpis`, `forecast_*`, `create_chart`). In the LLM tool-calling path these are exposed as PydanticAI tools (`run_sql`, `compute_kpis`, `forecast`, `make_chart`) that thinly wrap the exact same functions the deterministic planner calls — there is no second implementation to drift.
3. **The LLM explains — it does not compute or predict.** KPI math lives in the analytics layer; forecasts come from Prophet. The LLM only interprets and writes prose over what the tools return. Confidence is always derived from execution signals (tool succeeded, rows returned, forecast had enough points) — never self-reported by the LLM, in either path.
4. **SQL is validated by AST before execution.** Generated SQL passes `sqlglot` → parse → validate → run (`backend/app/security/sql_guard.py`). Reject anything that isn't a single `SELECT` against the one authorized table, references unknown columns, or uses a function outside the allow-list. Never `UPDATE / DELETE / DROP / ALTER / INSERT / TRUNCATE`.
5. **The LLM provider is swappable.** Models are OpenCode GO's OpenAI-compatible endpoint (`https://opencode.ai/zen/go/v1`), reached through `pydantic-ai`'s `OpenAIChatModel` — no provider-specific code leaks into the agent or tools. The frontend's model selector offers 20 allow-listed OpenCode GO models (`backend/app/agent/models.py::ALLOWED_MODELS`); any id outside that list resolves to the server default instead of being passed to the provider.

## Startup decisions (locked)

Decided before implementation. These refine — not replace — the invariants and architecture below.

1. **API contract — SSE stream + final payload.** The endpoint streams `answer` as SSE `token` events, then emits one `done` event carrying the full structured `ChatResponse`. The frontend accumulates tokens live and renders chart/KPIs on `done`. Never try to stream the structured object incrementally.
2. **Data shape — daily rows, 1–2 years.** `fecha` is one row per day, 1–2 years of history. Prophet consequence: **strong weekly** seasonality, **weak yearly** (1–2 cycles). Trust forecasts to ~30 days (the spec's "next month"); beyond ~90 days widen intervals and state the uncertainty. Enable `weekly_seasonality`; treat `yearly_seasonality` as low-confidence.
3. **Planner — deterministic rules, not an LLM.** This governs the fallback path only (no `LLM_API_KEY`, or the LLM path failed): intent is classified by keyword/pattern rules over the business dictionary — no extra LLM call. Canonical intent enum (single source of truth across both paths): `SQL · KPI · COMPARISON · FORECAST · CHART · CONVERSATION`. This supersedes the spec's inconsistent `Analytics`/`Chart` naming. When the LLM tool-calling path runs instead, there is no separate intent classification step — the model itself decides which tool(s) to call; `Intent` is inferred afterwards from which tools ran, only to pick default suggestion chips (see `llm_agent._infer_intent`).
4. **Conversational memory — Redis, per session, 14-day TTL.** This is a technical-evaluation build: the reviewer opens it ~1 week after delivery, so sessions must survive redeploys and restarts across that window. History lives in Redis keyed by `conv:{conversation_id}` (JSON message list) with a 14-day TTL (margin over the ~1-week review window). Enable Redis **AOF + a Docker volume** so data also survives a Redis/VPS restart — otherwise a restart drops everything regardless of TTL. Every request carries `conversation_id`; `ChatResponse` echoes it. This is session durability, not permanent history — add a MySQL `messages` archive only if permanent, auditable history becomes a requirement (YAGNI for the evaluation).

Minor, also locked:
- **`confidence`** is never self-reported by the LLM. Derive it from execution signals (SQL validated, rows returned, forecast had enough points); low on fallback/empty results.
- **Auth** is out of MVP scope on purpose. The SQL layer protects the DB from the LLM; nothing yet protects the API from the outside. Add authn + rate-limiting before any non-local exposure.

## Architecture

Request flow — `AnalyticsEngine._build_response` (`backend/app/agent/engine.py`) tries path 1 whenever a key is configured, falling through to path 2 on any failure:

```
                                   ┌─ if LLM_API_KEY set ─┐
                                   │  1. LLM tool-calling  │
React → REST/SSE → FastAPI ───────┤     agent picks tools │
                                   │  (run_sql/compute_kpis│
                                   │   /forecast/make_chart)│
                                   └───────────┬───────────┘
                                               │ on failure / no key
                                   ┌───────────▼───────────┐
                                   │  2. Deterministic      │
                                   │     Intent Planner →   │
                                   │     fixed handler →    │
                                   │     template           │
                                   └───────────┬───────────┘
                          ┌────────────────────┼────────────────────┐
                       SQL Tool          Analytics Tool         Forecast Tool
                          └────────────────────┴────────────────────┘
                                               ▼
                                             MySQL  →  ChatResponse
```

Both paths call the same underlying tools (`backend/app/tools/`) and the same SQL guard — they differ only in *what decides which tool to call and how the answer is written* (LLM decision + LLM prose vs. keyword rules + template prose).

**Intent Planner** (fallback path only) is the routing layer: deterministic keyword + business-dictionary rules classify each query into `SQL | KPI | COMPARISON | FORECAST | CHART | CONVERSATION` before any handler runs, so the system runs only the logic that query needs. Don't fold this into the agent — it's a deliberate cost/precision optimization for the no-LLM-key case.

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

## Toolchain

**Backend** (`backend/`, Python via `uv`):
- `uv sync` — install
- `uv run uvicorn app.main:app --reload --env-file .env` — dev server
- `uv run pytest` — all tests · `uv run pytest tests/test_x.py::test_name` — a single test
- `docker compose up` — MySQL + Redis (+ the `api` service, containerized, if used instead of local `uvicorn`)

**Frontend** (`frontend/`, Vite + React 19 + TypeScript):
- `npm install`
- `npm run dev` — dev server (Vite default port `5173`)
- `npm run build` — production build (`tsc -b && vite build`)
- UI primitives: `class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react` icons — hand-built components on Tailwind v4, not shadcn/ui's CLI scaffold (no `components.json`/copy-in `ui/` directory in this codebase).

## Layout (actual)

```
backend/app/
├── agent/       — engine.py (path selection + fallback), llm_agent.py (PydanticAI
│                  tool-calling agent), llm_hook.py (optional reword pass for the
│                  deterministic path), models.py (allow-listed model ids),
│                  sql_builder.py, templates.py, confidence.py, think_strip.py
├── api/         — chat.py: POST /chat SSE endpoint
├── database/    — SQLAlchemy engine
├── memory/      — Redis-backed conversation memory (base.py protocol + redis_store.py)
├── planner/     — deterministic intent classifier (fallback path)
├── schemas/     — chat.py: Intent enum, ChatRequest, ChatResponse, ChartConfig
├── security/    — sql_guard.py: the AST-based SQL validator
├── semantics/   — dictionary.py: business-vocabulary → column mapping
├── tools/       — execute_sql, calculate_kpis, forecast (Prophet), create_chart,
│                  summarize — the only path to MySQL, shared by both response paths
├── config.py    — Settings (env-driven)
└── main.py      — FastAPI app, CORS, GET /health, GET /models

frontend/src/
├── components/  — ChatPanel, ChatInput, MessageBubble, ChartRenderer, MetricsCards,
│                  ModelSelector, Sidebar, SqlDebugPanel, SuggestionChips, EmptyState
├── hooks/       — useChatStream (SSE), useConversations (localStorage), useModels,
│                  useHealth, useSelectedModel, useTheme
├── lib/         — utils.ts
├── types/       — chat.ts
└── App.tsx, main.tsx
```

- `tools/` — the controlled data-access tools; the **only** path to MySQL, called identically by the LLM agent's tool wrappers and the deterministic planner's handlers.
- `agent/engine.py` — where the two response paths are wired together (`_build_response`); this is the file to read first to understand request flow.
- `agent/llm_agent.py` — the PydanticAI agent, its system prompt, and the four tools it exposes (`run_sql`, `compute_kpis`, `forecast`, `make_chart`).
- No separate `analytics/`, `forecasting/`, `charts/`, or `prompts/` top-level packages — that logic lives inside `tools/` (KPI math, Prophet forecasting, chart-config building) and `agent/llm_agent.py` (the system prompt), respectively.
