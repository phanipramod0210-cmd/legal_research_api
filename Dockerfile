# ── Stage 1: Builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install poetry==1.8.3

COPY pyproject.toml poetry.lock* ./

RUN poetry config virtualenvs.in-project true \
    && poetry install --no-root --no-interaction --no-ansi --without dev

# ── Stage 2: Production ───────────────────────────────────────
FROM python:3.11-slim AS production

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --group appuser

WORKDIR /app

# System deps for asyncpg + pdf parsing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtualenv from builder
COPY --from=builder /build/.venv /app/.venv

# Copy source
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY alembic.ini ./

# Create logs dir
RUN mkdir -p /app/logs && chown -R appuser:appgroup /app

USER appuser

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Startup: run migrations then launch server
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]
