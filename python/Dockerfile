# Runner image for the Prefect-orchestrated sync.
# Installs the project plus the `prefect` extra, then runs the flow's
# .serve() loop, which holds the 5-minute schedule and reports to the server.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml ./
COPY sync ./sync

RUN uv pip install --system --no-cache ".[prefect]"

CMD ["python", "-m", "sync.prefect_flow"]
