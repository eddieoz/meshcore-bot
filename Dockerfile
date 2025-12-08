# Multi-stage Dockerfile for MeshCore Bot
FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libc-dev \
    libdbus-1-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# Final stage
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libdbus-1-3 \
    bluez \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create app directory and user
RUN useradd -m -u 1000 meshcore && \
    mkdir -p /app/data /app/logs && \
    chown -R meshcore:meshcore /app

WORKDIR /app

# Copy application code
COPY --chown=meshcore:meshcore . .

# Expose web viewer port
EXPOSE 8080

# Run as root for serial device access (when using privileged mode)
# If security is a concern and not using serial/BLE, uncomment the following:
# USER meshcore

# Set Python to run in unbuffered mode for better log output
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Run the bot
CMD ["python", "meshcore_bot.py"]
