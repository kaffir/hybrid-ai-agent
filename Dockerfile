# ============================================================
# Hybrid AI Agent — Sandboxed Execution Environment
# ============================================================
# Security principles:
#   1. Non-root user
#   2. Minimal base image
#   3. No unnecessary packages
#   4. Read-only filesystem where possible
#   5. No Docker socket access
# ============================================================

# --- Stage 1: Build dependencies ---
FROM python:3.11-slim AS builder

WORKDIR /build

# Copy only dependency files first (layer caching)
COPY pyproject.toml .

# Install dependencies into a virtual environment
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir .

# --- Stage 2: Runtime ---
FROM python:3.11-slim AS runtime

# Security: Create non-root user
RUN groupadd --gid 1000 agent && \
    useradd --uid 1000 --gid agent --shell /bin/bash --create-home agent

# Install only essential runtime tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        curl \
        jq \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source and config
COPY src/ /app/src/
COPY config/ /app/config/
COPY conftest.py /app/conftest.py
COPY pyproject.toml /app/pyproject.toml

# Set ownership
RUN chown -R agent:agent /app

# Environment
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Security: workspace directory for mounted projects
RUN mkdir -p /workspace && chown agent:agent /workspace

# Security: agent state directory (pending tasks, audit logs)
RUN mkdir -p /workspace/.agent && chown agent:agent /workspace/.agent

# Security: Switch to non-root user
USER agent

# Set working directory to /app so config/ paths resolve correctly
WORKDIR /app

ENTRYPOINT ["python", "-m", "src.main"]
