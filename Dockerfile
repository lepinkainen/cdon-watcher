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

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user for security
RUN useradd -m -u 1000 tracker && \
    chown -R tracker:tracker /app

# Copy application files
COPY --chown=tracker:tracker cdon_scraper.py .
COPY --chown=tracker:tracker monitor.py .

# Create directory for database (will be mounted as volume)
RUN mkdir -p /app/data && chown tracker:tracker /app/data

# Switch to non-root user
USER tracker

# Install Playwright browsers as the tracker user
RUN playwright install chromium

# Environment variables for configuration
ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/app/data/cdon_movies.db
ENV FLASK_HOST=0.0.0.0
ENV FLASK_PORT=8080

# Expose Flask port
EXPOSE 8080

# Default command (can be overridden)
CMD ["python", "monitor.py", "web"]
