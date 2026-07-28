# =============================================================================
# FlintTrade — Multi-stage Production Dockerfile
# =============================================================================
#
# Build:  docker build -t flinttrade:latest .
# Run:    docker run -d -p 5100:5100 flinttrade:latest
#         (add --env-file .env only if you keep a dev/server .env — none is required)
#
# This image is the backend API only. The React terminal is NOT built here:
# .dockerignore excludes packages/apps/terminal/dist, so port 5100 serves no
# UI from this image. In docker-compose the one-shot `terminal` service builds
# the UI into the terminal_dist volume and Nginx serves it — Nginx is the UI
# origin for Docker deployments.
#
# Uses uv (10x faster than pip) for dependency installation in the builder
# stage, then copies only the installed packages to a minimal runtime image.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — install Python dependencies with uv
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Install dependencies first (layer cache optimisation).
# SC-07: hash-verified install only — requirements.lock is the uv-exported,
# fully-hashed runtime lockfile; --require-hashes refuses any unpinned/tampered
# wheel. (requirements.txt is the loose dev input, never installed in prod.)
COPY requirements.lock .
RUN uv pip install --system --no-cache --require-hashes -r requirements.lock

# ---------------------------------------------------------------------------
# Stage 2: Runtime — minimal image with only what we need
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# Install runtime dependencies: curl (health checks), tini (init system)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tini \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r flinttrade && useradd -r -g flinttrade -m flinttrade

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY packages/ packages/
COPY .env.example .env.example

# Copy entrypoint script
COPY infra/docker/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Create data directories with correct ownership
RUN mkdir -p /data/flinttrade/audit \
             /data/flinttrade/logs \
             /data/flinttrade/strategies \
             /home/flinttrade/.flinttrade \
    && chown -R flinttrade:flinttrade /data/flinttrade \
    && chown -R flinttrade:flinttrade /home/flinttrade/.flinttrade \
    && chown -R flinttrade:flinttrade /app

# Environment
ENV PYTHONUNBUFFERED=1
ENV AUDIT_LOG_DIR=/data/flinttrade/audit
ENV FLINTTRADE_BACKEND_PORT=5100
ENV PYTHONPATH=/app/packages/core/core/src:/app/packages/core/data/src:/app/packages/core/historical/src:/app/packages/core/indicators/src:/app/packages/services/backtest/src:/app/packages/services/engine/src:/app/packages/services/screener/src:/app/packages/services/journal/src:/app/packages/services/ai/src:/app/packages/services/ditto/src:/app/packages/services/automation/src:/app/packages/integrations/gateway/src:/app/packages/integrations/webhooks/src

# Expose backend port
EXPOSE 5100

# Switch to non-root user
USER flinttrade

# Use tini as init system for proper signal handling (PID 1 reaping)
ENTRYPOINT ["tini", "--"]
CMD ["./start.sh"]
