FROM python:3.12-slim

# Playwright's Chromium runtime dependencies (headless-shell needs
# these system libraries even on slim images).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY fixtures ./fixtures

RUN uv sync --no-dev
RUN uv run playwright install chromium

ENTRYPOINT ["uv", "run", "python", "-m", "app.main"]
CMD ["run"]
