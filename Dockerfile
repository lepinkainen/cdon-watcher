# Dockerfile  
FROM python:3-slim

# Install uv
RUN pip install --no-cache-dir uv

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

# Create non-root user for security
RUN useradd -m -u 1000 tracker

# Create minimal src structure for dependency installation
RUN mkdir -p src/cdon_watcher && \
    touch src/cdon_watcher/__init__.py

# Install dependencies to system Python (no venv needed)
RUN uv pip install --system --no-cache .

# Copy application files after dependencies are installed
COPY --chown=tracker:tracker src/ /app/src/

# Set ownership of app directory
RUN chown -R tracker:tracker /app

# Install the actual package now that source files are available
RUN uv pip install --system -e .

# Switch to non-root user before installing Playwright browsers
USER tracker

# Install Playwright browsers as tracker user so they're in the right location
RUN playwright install chromium

# Create directories for database and posters (will be mounted as volume)
RUN mkdir -p /app/data/posters

# Environment variables for configuration
ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/app/data/cdon_movies.db
ENV POSTER_DIR=/app/data/posters
ENV API_HOST=0.0.0.0
ENV API_PORT=8080
ENV PYTHONPATH=/app

# Expose API port
EXPOSE 8080

# Default command (can be overridden)
CMD ["python", "-m", "cdon_watcher", "web"]
