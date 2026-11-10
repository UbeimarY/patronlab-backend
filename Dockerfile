# syntax=docker/dockerfile:1

# ---------- Build stage: locked dependencies only ----------
FROM python:3.11-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

# Prebuilt wheels only: no third-party build scripts run inside the image.
COPY pyproject.toml uv.lock .python-version ./
# The test suites shipped inside SciPy, scikit-learn, NumPy... are never imported: ~75 MB less.
RUN uv sync --locked --no-dev --no-build --no-install-project \
    && find .venv -type d -name tests -prune -exec rm -rf {} +

COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations

# ---------- Runtime stage ----------
FROM python:3.11-slim
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000

# Migrations run before the server starts (safe with a single instance).
CMD ["sh", "-c", "alembic upgrade head && uvicorn patronlab.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
