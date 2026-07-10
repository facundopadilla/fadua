# AI Analytics Chatbot

A conversational "Analista de Datos Comercial" (commercial data analyst) chatbot. Ask it natural-language questions in Spanish about ad campaigns and vehicle sales — KPIs, comparisons, forecasts, charts — and it answers from a real MySQL dataset, never invented numbers. It runs in two modes: an LLM tool-calling agent when a key is configured, or a fully deterministic rule-based planner when it isn't.

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI, PydanticAI, SQLAlchemy, pandas, Prophet, sqlglot — dependency-managed with `uv` |
| Frontend | React 19, Vite, Tailwind v4, Recharts, TanStack Query, react-markdown |
| LLM | [OpenCode GO](https://opencode.ai/zen/go/v1) (OpenAI-compatible), 20 selectable models |
| Data | MySQL 8, synthetic seed auto-loaded on first start |
| Memory | Redis, per-conversation, 14-day TTL |

## Prerequisites

- Docker + Docker Compose
- [`uv`](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 20+

## Quick path

### 1. Start infrastructure

From the repo root:

```bash
docker compose up
```

This starts MySQL and Redis. MySQL auto-loads the seed data (`db/init.sql`, ~547 daily rows spanning ~18 months) the first time its volume is created.

> The `api` service is also defined in `docker-compose.yml` and can serve the backend in a container — see [Ports](#ports) if you use it instead of step 2. For local development, running the backend directly (step 2) gives faster reload.

### 2. Configure and run the backend

```bash
cd backend
cp env.example .env
# edit .env: set LLM_API_KEY (see Configuration below)
uv sync
uv run uvicorn app.main:app --reload --env-file .env
```

### 3. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

### 4. Open the app

Go to the frontend URL printed by Vite (default `http://localhost:5173`) and start chatting.

## Configuration

Copy the template and fill in your key:

```bash
cp backend/env.example backend/.env
```

The one value you need to set is `LLM_API_KEY`, from your OpenCode GO account. Everything else in `env.example` has a working default for local development.

Without `LLM_API_KEY` set, the backend still works — it falls back to a deterministic planner (see [How it works](#how-it-works) below). Set the key to unlock full conversational tool-calling.

## Ports

Read from `docker-compose.yml` — the source of truth if this drifts:

| Service | Host port | Notes |
|---------|-----------|-------|
| `api` (backend, containerized) | `8010` | Mapped from container port `8000` — `8000` was already taken locally. If you run the backend with `uvicorn` directly instead (step 2 above), it listens on `8000`. |
| `mysql` | `3306` | User/password/db: `analytics` / `analytics` / `analytics` |
| `redis` | `6379` | AOF persistence enabled |
| frontend (Vite dev server) | `5173` | Vite default; printed on `npm run dev` |

## Production deployment

Production runs a different topology than dev. A single public entry point — the **frontend nginx** — serves the built SPA *and* reverse-proxies `/api/` to the internal backend. **MySQL is external** (a managed instance or your own server, not a container); the backend reaches it via `DATABASE_URL`. Redis stays a container with AOF persistence. Files: `docker-compose.prod.yml`, `frontend/Dockerfile`, `frontend/nginx.conf`, `.env.production.example`.

From this directory (`segundo/`):

```bash
# 1. Create the prod env from the template and fill it in
cp .env.production.example .env
#    - DATABASE_URL  -> your EXTERNAL production MySQL (not a container)
#    - LLM_API_KEY   -> your OpenCode GO key

# 2. Load the seed into your external MySQL (no seed-mounting container in prod)
mysql -h YOUR_PROD_MYSQL_HOST -u USER -p DBNAME < db/init.sql

# 3. Build and start (first build is slow — the backend installs Prophet)
docker compose -f docker-compose.prod.yml up -d --build
```

The app is served on **port 80** (`http://<your-host>/`). To use a different host port, change `ports: ["80:80"]` to e.g. `"8080:80"` in `docker-compose.prod.yml`.

How the API path resolves: the SPA is built with `VITE_API_URL=/api`, so the browser calls `/api/chat`, `/api/health`, `/api/models` — same origin. nginx (`frontend/nginx.conf`) proxies `location /api/` to `http://api:8000/` with a trailing slash, which **strips the `/api` prefix**, so the backend receives `/chat`, `/health`, `/models` (its actual routes). Because it's same-origin, `CORS_ORIGINS` isn't needed unless you serve the frontend from a different origin.

SSE note: the nginx `/api/` block disables buffering/caching and sets `proxy_read_timeout 300s` so long streaming responses (deepseek can take 60s+) aren't cut off.

Redis runs in-container by default (durable via a named volume + AOF). To point at an external/managed Redis instead, set `REDIS_URL` in `.env` to that instance and optionally remove the `redis` service from `docker-compose.prod.yml`.

Not covered here (out of MVP scope, per `CLAUDE.md`): TLS/HTTPS termination, API authentication, and rate-limiting — add these before any real public exposure.

## How it works

Every chat request tries the LLM tool-calling agent first (when `LLM_API_KEY` is set): a PydanticAI agent decides which controlled tool to call — `run_sql`, `compute_kpis`, `forecast` (Prophet), `make_chart` — and writes the final answer over their real results. If that path fails for any reason (no key, network error, provider issue), the backend transparently falls back to a deterministic rule-based planner + template engine that answers the same way without an LLM in the loop.

In both modes, the LLM (or the planner) **never touches MySQL directly**. All data access goes through `run_sql`, which is validated by an AST-based SQL guard: SELECT-only, one authorized table (`metricas_campanas_ventas`), a column allow-list, and a blocked-function list. This is the core guarantee — the chatbot cannot invent figures.

Responses stream over SSE: `token` events render the answer live, followed by one `done` event carrying the full structured reply (answer, SQL used, chart config, metrics, suggestions, confidence, execution time).

Use the model selector in the UI to switch between the 20 available OpenCode GO models per request. `deepseek-v4-pro` (the default) is the most reliable at actually completing tool calls — some other models (kimi, minimax) tend to narrate their plan instead of executing it.

## Learn more

- [`specs.md`](./specs.md) — original technical specification (Spanish)
- [`CLAUDE.md`](./CLAUDE.md) — architecture, invariants, and locked design decisions
