# Runner image for the Prefect-orchestrated sync.
# Installs this standalone project and runs the flow's .serve() loop, which
# holds the 5-minute schedule and reports each run to the server.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml ./
COPY sync ./sync

RUN uv pip install --system --no-cache .

CMD ["python", "-m", "sync.prefect_flow"]
