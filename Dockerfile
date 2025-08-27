# Dockerfile
FROM python:3.11-slim

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libatspi2.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libxcb1 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency files for better caching
COPY pyproject.toml uv.lock ./

# Install uv and dependencies
RUN pip install --no-cache-dir uv
RUN uv sync --frozen --no-dev

# Install Playwright browsers (needs to run as root)
RUN /app/.venv/bin/playwright install chromium

# Create non-root user for security
RUN useradd -m -u 1000 tracker && \
    chown -R tracker:tracker /app

# Switch to non-root user
USER tracker

# Copy application files
COPY --chown=tracker:tracker src/ /app/src/

# Create directory for database (will be mounted as volume)
RUN mkdir -p /app/data && chown tracker:tracker /app/data

# Environment variables for configuration
ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/app/data/cdon_movies.db
ENV FLASK_HOST=0.0.0.0
ENV FLASK_PORT=8080
ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:$PATH"

# Expose Flask port
EXPOSE 8080

# Default command (can be overridden)
CMD ["python", "-m", "src.cdon_watcher.monitor", "web"]
