# ---- Stage 1: Builder ----
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --target=/build/deps -r requirements.txt

# ---- Stage 2: Runtime ----
FROM python:3.12-slim AS runtime

# Security: non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Copy installed dependencies from builder
COPY --from=builder /build/deps /usr/local/lib/python3.12/site-packages/

# Copy application code
COPY pyproject.toml .
COPY alembic/ alembic/
COPY src/ src/

# Own files by appuser
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Default: run the FastAPI app
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
