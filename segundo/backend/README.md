# AI Analytics Chatbot — Backend

FastAPI scaffolding for a conversational analytics assistant over MySQL
(ad campaigns + sales metrics). This iteration ships the API skeleton,
Redis-backed conversation memory (14-day TTL, AOF persistence), and the
AST-based SQL security guard. The agent is a stub.

## Run (Docker)

From the repo root:

```bash
cp backend/env.example backend/.env
docker compose up --build
```

API at `http://localhost:8000` — `GET /health` returns `{"status":"ok"}`.

## Run (local dev)

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload   # needs a reachable Redis (see docker-compose)
uv run pytest                          # SQL guard tests
```

## `POST /chat` — SSE contract

Request body: `{"message": "...", "conversation_id": null}`. When
`conversation_id` is null the server generates one and echoes it back.

The response is `text/event-stream` with two event types:

- `event: token` — `data: {"text": "..."}`, one per answer fragment.
  Accumulate them in order to render the answer live.
- `event: done` — emitted once at the end. `data` is the full `ChatResponse`
  JSON: `conversation_id`, `answer`, `sql`, `chart`, `metrics`, `suggestions`,
  `execution_time`, `confidence`. Render charts/KPIs from this payload only.

```bash
curl -N http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hola"}'
```

## Stubbed for the next iteration

Intent Planner (deterministic rules), the real PydanticAI agent, the
controlled tools (`execute_sql`, `calculate_kpis`, `forecast_*`,
`create_chart`), Prophet forecasting, KPI math, and the frontend.
