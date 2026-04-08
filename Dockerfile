# =============================================================================
# FlintTrade — Multi-stage Production Dockerfile
# =============================================================================
#
# Build:  docker build -t flinttrade:latest .
# Run:    docker run -d --env-file .env -p 5100:5100 flinttrade:latest
#
# Uses uv (10x faster than pip) for dependency installation in the builder
# stage, then copies only the installed packages to a minimal runtime image.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — install Python dependencies with uv
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Install dependencies first (layer cache optimisation)
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

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
ENV FLINTTRADE_PORT=5100

# Expose backend port
EXPOSE 5100

# Switch to non-root user
USER flinttrade

# Use tini as init system for proper signal handling (PID 1 reaping)
ENTRYPOINT ["tini", "--"]
CMD ["./start.sh"]
