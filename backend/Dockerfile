# Multi-stage production Dockerfile for IGRS Backend
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system compilation dependencies for psycopg2, PyYAML, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# Final runtime image
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed python dependencies from builder
COPY --from=builder /install /usr/local

# Copy application source code
COPY . /app

# Create non-root user for security best practices
RUN useradd -m -u 1000 igrsuser && chown -R igrsuser:igrsuser /app
USER igrsuser

# Expose FastAPI port
EXPOSE 8000

# Docker Healthcheck targeting production health probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

# Launch production ASGI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
